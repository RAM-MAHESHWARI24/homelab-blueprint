"""
Homelab Blueprint provisioning orchestrator.

Turns a wizard/headless configuration dict into a running system:

  1. storage tree           (data, appdata, photos)
  2. environment files      (/etc/homelab/*.env, 0600, secrets generated)
  3. enabled modules        (compose pull → up → wait healthy; host units)
  4. install manifest       (/var/lib/homelab/installed.json)
  5. static IP (optional)   (applied LAST, with an armed revert timer)

Design rules:
  * every failure is collected in `errors`; `success` is False if any
    required step failed. Nothing is swallowed as a "Notice".
  * dry_run writes only into setup/dry_run_preview and never calls docker,
    systemctl, useradd or netplan.
  * all subprocess calls have timeouts.
"""

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config_core import (
    ETC_DIR,
    STATE_DIR,
    CONTROL_HUB_TOKEN_FILE,
    SERVICE_USER,
    module_appdata_dir,
    is_linux_host,
    create_homelab_directory_tree,
    sync_all_blueprint_envs,
    safe_apply_netplan,
    confirm_netplan_change,
    generate_netplan_yaml,
)

from .host import (
    run_command,
    ensure_system_user,
    install_systemd_unit,
    install_cron,
    install_sudoers,
    install_helper_script,
    write_private_file,
)
from .manifest import InstallManifest

BLUEPRINT_VERSION = "2.0.0"

# Accepted module ids and legacy aliases coming from older configs / the UI.
MODULE_ALIASES = {
    "media": "media",
    "mediaserver": "media",
    "photos": "photos",
    "noodle-gallery": "photos",
    "control_hub": "control_hub",
    "control-hub": "control_hub",
    "tv_updater": "tv_autoupdater",
    "tv-updater": "tv_autoupdater",
    "tv_autoupdater": "tv_autoupdater",
    "sleep_guard": "sleep_guard",
    "ml_schedule": "ml_schedule",
}
DEFAULT_MODULES = ["media", "photos", "control_hub"]

COMPOSE_PULL_TIMEOUT = int(os.getenv("HOMELAB_COMPOSE_PULL_TIMEOUT", "1800"))
COMPOSE_UP_TIMEOUT = int(os.getenv("HOMELAB_COMPOSE_UP_TIMEOUT", "600"))
HEALTH_WAIT_TIMEOUT = int(os.getenv("HOMELAB_HEALTH_WAIT_TIMEOUT", "240"))
# Polls are 5 s apart; a container seen "restarting" this many times is in a crash loop.
RESTART_LOOP_SIGHTINGS = 4


class Deployment:
    """Holds state for one provisioning run."""

    def __init__(self, base_dir: str, config: Dict[str, Any]):
        self.root = Path(base_dir).resolve()
        self.config = config
        self.dry_run = bool(config.get("dry_run", False)) or os.getenv("DRY_RUN", "0") == "1"
        self.linux = is_linux_host() and not self.dry_run
        self.logs: List[str] = []
        self.errors: List[Dict[str, str]] = []
        self.warnings: List[str] = []
        self.services_launched: List[str] = []

        self.preview_dir = self.root / "setup" / "dry_run_preview"
        self.etc_dir = (self.preview_dir / "etc" / "homelab") if self.dry_run else ETC_DIR
        self.state_dir = (self.preview_dir / "var" / "lib" / "homelab") if self.dry_run else STATE_DIR
        self.manifest = InstallManifest(self.state_dir / "installed.json")

        self.modules = self._resolve_modules(config.get("enabled_services"))
        self.tv_dir = next(
            (self.root / "apps" / n for n in ("tv-autoupdater", "tv-updater") if (self.root / "apps" / n).exists()),
            self.root / "apps" / "tv-autoupdater",
        )

    # ------------------------------------------------------------------ utils
    def log(self, msg: str) -> None:
        prefix = "[DRY-RUN] " if self.dry_run else ""
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {prefix}{msg}")

    def fail(self, module: str, msg: str) -> None:
        self.errors.append({"service": module, "msg": msg})
        self.log(f"ERROR ({module}): {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.log(f"WARNING: {msg}")

    @staticmethod
    def _resolve_modules(requested) -> List[str]:
        if not requested:
            return list(DEFAULT_MODULES)
        resolved: List[str] = []
        for item in requested:
            canonical = MODULE_ALIASES.get(str(item))
            if canonical and canonical not in resolved:
                resolved.append(canonical)
        return resolved

    def template_vars(self) -> Dict[str, str]:
        return {
            "INSTALL_DIR": str(self.root),
            "SERVICE_USER": SERVICE_USER,
            "ETC_DIR": str(self.etc_dir),
            "STATE_DIR": str(self.state_dir),
            "PYTHON": str(self.root / "apps" / "control-hub" / "venv" / "bin" / "python3"),
        }

    # ---------------------------------------------------------------- step 1
    def step_storage(self) -> None:
        data_dir = self.config.get("hdd_data", "/mnt/hdd/data")
        memories_dir = self.config.get("hdd_memories", "/mnt/hdd/Memories")
        default_appdata = str(module_appdata_dir("mediaserver")) if self.linux else str(self.root / "apps" / "mediaserver" / "config")
        config_dir = self.config.get("config_dir") or default_appdata
        if config_dir in ("./config", "config"):
            config_dir = default_appdata
        self.config["config_dir"] = config_dir

        # Photo cloud appdata (database, thumbnails, transcodes) also lives outside the checkout.
        photo_appdata = module_appdata_dir("noodle-gallery") if self.linux else self.root / "apps" / "noodle-gallery" / "data"
        self.config.setdefault("photo_db_dir", str(photo_appdata / "postgres"))
        self.config.setdefault("photo_thumbs_dir", str(photo_appdata / "thumbs"))
        self.config.setdefault("photo_video_dir", str(photo_appdata / "encoded-video"))
        self.config.setdefault("photo_upload_dir", f"{memories_dir.rstrip('/')}/uploads")

        puid = int(self.config.get("puid", 1000))
        pgid = int(self.config.get("pgid", 1000))

        if self.dry_run:
            self.log(f"Would create storage tree at '{data_dir}' (torrents/, media/) and appdata at '{config_dir}', owner {puid}:{pgid}.")
            self.log(f"Would create photo library directory '{memories_dir}'.")
            return

        self.log(f"Creating single-mount storage tree at '{data_dir}' and appdata at '{config_dir}'...")
        result = create_homelab_directory_tree(data_dir, config_dir, memories_dir, puid, pgid)
        if result["success"]:
            self.log(f"Created or verified {len(result['created_dirs'])} directories (owner {puid}:{pgid}).")
        else:
            self.fail("storage", f"Directory creation failed: {result['errors']}")

        if "photos" in self.modules:
            for key in ("photo_db_dir", "photo_thumbs_dir", "photo_video_dir", "photo_upload_dir"):
                try:
                    Path(self.config[key]).mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    self.fail("storage", f"could not create {self.config[key]}: {e}")

    # ---------------------------------------------------------------- step 2
    def step_environment(self) -> Dict[str, Any]:
        if self.dry_run:
            self.preview_dir.mkdir(parents=True, exist_ok=True)
            # Mirror the module templates into the preview tree so rendering has inputs.
            for rel in (".env.example", "apps/mediaserver/.env.example", "apps/noodle-gallery/.env.example",
                        "apps/control-hub/.env.example", f"apps/{self.tv_dir.name}/config.example.json"):
                src = self.root / rel
                if src.exists():
                    dst = self.preview_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            self.log(f"Rendering environment previews into '{self.preview_dir.relative_to(self.root)}'...")
            result = sync_all_blueprint_envs(str(self.preview_dir), self.config, env_dir=str(self.etc_dir))
        else:
            self.log(f"Rendering environment files into '{self.etc_dir}' (0600)...")
            result = sync_all_blueprint_envs(str(self.root), self.config, env_dir=str(self.etc_dir))

        for name, path in result.items():
            self.log(f"  -> {name}: {path}")
            self.manifest.add_file(path)

        # Persist the (now secret-bearing) configuration for upgrades and re-runs.
        redacted = {k: v for k, v in self.config.items() if not k.startswith("_")}
        cfg_path = self.etc_dir / "config.json"
        write_private_file(cfg_path, json.dumps(redacted, indent=2) + "\n", self.manifest, mode=0o600)
        self.log(f"  -> saved configuration: {cfg_path}")
        return result

    # ---------------------------------------------------------------- step 3
    def _compose(self, module: str, module_dir: Path, env_file: Path, extra_files: Optional[List[str]] = None) -> bool:
        """pull → up -d → wait for health. Returns True on success."""
        if self.dry_run:
            self.log(f"Would run docker compose pull/up in '{module_dir.relative_to(self.root)}' with env '{env_file}'"
                     + (f" and overrides {extra_files}" if extra_files else "") + ".")
            self.services_launched.append(f"{module} (dry-run)")
            return True

        base = ["docker", "compose", "--env-file", str(env_file), "-f", "docker-compose.yml"]
        for extra in extra_files or []:
            base += ["-f", extra]
        self.log(f"Pulling images for {module} (this can take a while on first install)...")
        pull = run_command(base + ["pull", "--quiet"], cwd=str(module_dir), timeout=COMPOSE_PULL_TIMEOUT)
        if not pull.ok:
            self.fail(module, f"docker compose pull failed: {pull['stderr'] or pull['stdout']}")
            return False

        self.log(f"Starting {module} containers...")
        up = run_command(base + ["up", "-d", "--remove-orphans"], cwd=str(module_dir), timeout=COMPOSE_UP_TIMEOUT)
        if not up.ok:
            self.fail(module, f"docker compose up failed: {up['stderr'] or up['stdout']}")
            return False

        # Record the stack as soon as it exists so teardown can remove it even if
        # the health wait below fails.
        self.manifest.add_compose(module, module_dir, env_file)

        healthy, detail = self._wait_healthy(base, module_dir)
        if not healthy:
            self.fail(module, f"containers did not become healthy: {detail}")
            return False

        self.services_launched.append(module)
        self.log(f"{module} is up and healthy.")
        return True

    def _wait_healthy(self, base: List[str], module_dir: Path) -> "tuple[bool, str]":
        deadline = time.time() + HEALTH_WAIT_TIMEOUT
        last = ""
        restarting_seen: Dict[str, int] = {}
        while time.time() < deadline:
            ps = run_command(base + ["ps", "--format", "json"], cwd=str(module_dir), timeout=60)
            if not ps.ok:
                last = ps["stderr"]
                time.sleep(5)
                continue
            rows = []
            for line in ps["stdout"].splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    rows.extend(parsed if isinstance(parsed, list) else [parsed])
                except json.JSONDecodeError:
                    continue
            if not rows:
                last = "no containers reported by compose ps"
                time.sleep(5)
                continue
            bad = [r for r in rows if r.get("State") not in ("running",) or r.get("Health") in ("unhealthy",)]
            starting = [r for r in rows if r.get("Health") == "starting"]
            if not bad and not starting:
                return True, ""
            exited = [r for r in rows if r.get("State") in ("exited", "dead")]
            if exited:
                names = ", ".join(r.get("Name", r.get("Service", "?")) for r in exited)
                return False, f"exited: {names}"
            # A container with restart:unless-stopped that keeps crashing never shows as
            # "exited"; it flips between restarting and running. Give up after a few
            # sightings instead of waiting out the whole timeout.
            for r in rows:
                if r.get("State") == "restarting":
                    name = r.get("Name", r.get("Service", "?"))
                    restarting_seen[name] = restarting_seen.get(name, 0) + 1
                    if restarting_seen[name] >= RESTART_LOOP_SIGHTINGS:
                        return False, f"restart loop: {name} (exit code {r.get('ExitCode', '?')}); see `docker logs {name}`"
            last = ", ".join(f"{r.get('Name', r.get('Service', '?'))}={r.get('State')}/{r.get('Health') or 'n/a'}" for r in bad + starting)
            time.sleep(5)
        return False, f"timeout after {HEALTH_WAIT_TIMEOUT}s; last state: {last}"

    def _wire_script(self, subcommand: str, extra: List[str]) -> bool:
        """Runs apps/mediaserver/scripts/wire_arr.py (stdlib) as a subprocess; keeps the module standalone."""
        script = self.root / "apps" / "mediaserver" / "scripts" / "wire_arr.py"
        if not script.exists():
            self.fail("media", "scripts/wire_arr.py missing")
            return False
        cmd = [
            "python3", str(script), subcommand,
            "--config-dir", str(self.config["config_dir"]),
            "--qbit-user", str(self.config.get("qbittorrent_user") or "admin"),
            "--qbit-pass", str(self.config.get("qbittorrent_pass") or ""),
            *extra,
        ]
        res = run_command(cmd, cwd=str(script.parent), timeout=900)
        for line in (res["stdout"] or "").splitlines()[-40:]:
            self.log(f"  wire: {line}")
        if not res.ok:
            self.fail("media", f"wire_arr.py {subcommand} failed: {res['stderr'][-400:] or 'see log'}")
        return res.ok

    def module_media(self) -> None:
        module_dir = self.root / "apps" / "mediaserver"
        extra_files = ["docker-compose.dns.yml"] if self.config.get("dns_override") else []

        if self.dry_run:
            self.log("Would seed qBittorrent.conf with the chosen password, start the media stack and wire "
                     "Radarr/Sonarr/Prowlarr/qBittorrent/Jellyfin/Seerr together.")
            self._compose("media", module_dir, self.etc_dir / "mediaserver.env", extra_files)
            return

        if self.config.get("enable_tmdb_bypass"):
            src = module_dir / "config" / "seerr" / "tmdb-interceptor.js"
            dst = Path(self.config["config_dir"]) / "seerr" / "tmdb-interceptor.js"
            if src.exists() and not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    self.log("Installed TMDB interceptor into the Seerr config directory.")
                except OSError as e:
                    self.fail("media", f"could not copy TMDB interceptor: {e}")

        if not self._wire_script("seed", ["--puid", str(self.config.get("puid", 1000)), "--pgid", str(self.config.get("pgid", 1000))]):
            return
        if not self._compose("media", module_dir, self.etc_dir / "mediaserver.env", extra_files):
            return

        self.log("Connecting the media apps to each other (root folders, download client, indexer sync, libraries)...")
        wire_args = ["--host", "127.0.0.1", "--admin-user", str(self.config.get("media_admin_user") or "admin"),
                     "--admin-pass", str(self.config.get("media_admin_pass") or "")]
        if self.config.get("enable_byparr"):
            wire_args.append("--byparr")
        if self._wire_script("wire", wire_args):
            self.log("Media pipeline wired: Radarr/Sonarr → qBittorrent, Prowlarr → Radarr/Sonarr, Jellyfin libraries ready.")

    def module_photos(self) -> None:
        module_dir = self.root / "apps" / "noodle-gallery"
        self._compose("photos", module_dir, self.etc_dir / "noodle-gallery.env")

    def module_ml_schedule(self) -> None:
        """Optional: start/stop the Immich ML container on a schedule (noodle-gallery-tools script)."""
        src = self.root / "apps" / "immich-face-xmp-exporter" / "scripts" / "immich-ml-control.sh"
        cron = self.root / "system" / "cron.d" / "immich-ml"
        if self.dry_run:
            self.log("Would install immich-ml-control.sh and /etc/cron.d/immich-ml.")
            self.services_launched.append("ml_schedule (dry-run)")
            return
        if not src.exists() or not cron.exists():
            self.fail("ml_schedule", "immich-ml-control.sh or its cron template is missing")
            return
        install_helper_script(src, self.manifest)
        install_cron(cron, "immich-ml", self.manifest, variables=self.template_vars())
        self.services_launched.append("ml_schedule")
        self.log("Installed Immich ML on/off schedule.")

    def module_control_hub(self) -> None:
        ch_dir = self.root / "apps" / "control-hub"
        unit_src = self.root / "system" / "systemd" / "control-hub.service"
        sudoers_src = self.root / "system" / "systemd" / "homelab-sudoers.example"
        token = str(self.config.get("control_hub_token", ""))

        if self.dry_run:
            self.log("Would create venv, install requirements, create 'homelab' user, write token, install unit + sudoers.")
            self.services_launched.append("control_hub (dry-run)")
            return

        if not self.linux:
            self.warn("Control Hub host service can only be installed on Linux; skipping.")
            return

        venv_python = ch_dir / "venv" / "bin" / "python3"
        if not venv_python.exists():
            self.log("Creating Control Hub virtual environment...")
            res = run_command(["python3", "-m", "venv", "venv"], cwd=str(ch_dir), timeout=300)
            if not res.ok:
                self.fail("control_hub", f"venv creation failed: {res['stderr']}")
                return
        pip = ch_dir / "venv" / "bin" / "pip"
        self.log("Installing Control Hub Python requirements...")
        res = run_command([str(pip), "install", "-q", "-r", str(ch_dir / "requirements.txt")], cwd=str(ch_dir), timeout=900)
        if not res.ok:
            self.fail("control_hub", f"pip install failed: {res['stderr']}")
            return

        res = ensure_system_user(SERVICE_USER, self.manifest, extra_groups=["docker"])
        if not res.ok:
            self.fail("control_hub", f"could not create service user: {res['stderr']}")
            return
        run_command(["chown", "-R", f"{SERVICE_USER}:{SERVICE_USER}", str(ch_dir / "venv")], timeout=120)

        # The unit runs as `homelab` with WorkingDirectory inside the checkout. A clone
        # under a 0750 home directory fails with status=200/CHDIR; say so up front.
        probe = run_command(["runuser", "-u", SERVICE_USER, "--", "test", "-x", str(ch_dir)], timeout=10)
        if probe.ok is False and probe["returncode"] != -1:
            self.fail(
                "control_hub",
                f"user '{SERVICE_USER}' cannot enter {ch_dir} (check parent directory permissions; "
                f"install from /opt/homelab-blueprint or run: chmod o+x {self.root.parent})",
            )
            return

        if not token:
            self.fail("control_hub", "no Control Hub token was generated")
            return
        write_private_file(CONTROL_HUB_TOKEN_FILE, token + "\n", self.manifest, mode=0o640, owner_group=SERVICE_USER)
        # The daemon reads /etc/homelab/control-hub.env; make it group-readable for the service user.
        env_file = self.etc_dir / "control-hub.env"
        if env_file.exists():
            try:
                import grp

                os.chown(env_file, 0, grp.getgrnam(SERVICE_USER).gr_gid)
                os.chmod(env_file, 0o640)
            except (KeyError, OSError, ImportError):
                pass

        if sudoers_src.exists():
            res = install_sudoers(sudoers_src, "homelab-blueprint", self.manifest, variables=self.template_vars())
            if not res.ok:
                self.fail("control_hub", f"sudoers validation failed: {res['stderr']}")
                return

        if not unit_src.exists():
            self.fail("control_hub", "system/systemd/control-hub.service template missing")
            return
        res = install_systemd_unit(unit_src, "control-hub.service", self.manifest, variables=self.template_vars())
        if not res.ok:
            self.fail("control_hub", f"systemctl enable --now failed: {res['stderr']}")
            return
        self.services_launched.append("control_hub")
        self.log(f"Control Hub service enabled on port {self.config.get('control_hub_port', 7575)}.")

    def module_tv_autoupdater(self) -> None:
        cron_src = self.root / "system" / "cron.d" / "tv-updater"
        if self.dry_run:
            self.log("Would register the TV auto-updater cron schedule.")
            self.services_launched.append("tv_autoupdater (dry-run)")
            return
        if not self.linux:
            return
        if not cron_src.exists():
            self.fail("tv_autoupdater", "cron template system/cron.d/tv-updater missing")
            return
        ensure_system_user(SERVICE_USER, self.manifest, extra_groups=["docker"])
        install_cron(cron_src, "tv-autoupdater", self.manifest, variables=self.template_vars())
        self.services_launched.append("tv_autoupdater")
        self.log("TV auto-updater cron registered.")

    def module_sleep_guard(self) -> None:
        script = self.root / "system" / "power" / "server-suspend.sh"
        cron_src = self.root / "system" / "cron.d" / "server-suspend"
        conf_example = self.root / "system" / "power" / "server-suspend.conf.example"
        if self.dry_run:
            self.log("Would install server-suspend.sh, /etc/server-suspend.conf and the midnight suspend cron.")
            self.services_launched.append("sleep_guard (dry-run)")
            return
        if not self.linux:
            return
        if not script.exists() or not cron_src.exists():
            self.fail("sleep_guard", "server-suspend.sh or its cron template is missing")
            return
        install_helper_script(script, self.manifest)
        conf_dst = Path("/etc/server-suspend.conf")
        if conf_example.exists() and not conf_dst.exists():
            shutil.copy2(conf_example, conf_dst)
            os.chmod(conf_dst, 0o644)
            self.manifest.add_file(conf_dst)
        install_cron(cron_src, "server-suspend", self.manifest, variables=self.template_vars())
        self.services_launched.append("sleep_guard")
        self.log("Sleep Guard (rtcwake suspend schedule) installed.")

    # ---------------------------------------------------------------- step 5
    def step_netplan(self) -> Optional[Dict[str, Any]]:
        if not self.config.get("enable_static_ip", False):
            return None
        nic = self.config.get("active_nic") or ""
        ip = self.config.get("server_ip", "")
        gw = self.config.get("default_gateway", "192.168.1.1")
        dns = self.config.get("dns_servers", ["1.1.1.1", "8.8.8.8"])
        if not nic or not ip:
            self.warn("Static IP requested but interface or IP missing; skipping Netplan.")
            return None

        if self.dry_run:
            preview = generate_netplan_yaml(nic, ip if "/" in ip else f"{ip}/24", gw, dns)
            self.log(f"Would apply static IP {ip} on '{nic}' with a 120s auto-revert timer.")
            return {"success": True, "mode": "dry_run", "preview_yaml": preview}

        self.log(f"Applying static IP {ip} on '{nic}' with an armed revert timer...")
        result = safe_apply_netplan(interface=nic, ip_address=ip, gateway=gw, dns_servers=dns)
        if not result.get("success"):
            self.fail("netplan", result.get("message") or result.get("error", "unknown error"))
            return result

        if result.get("pending") and self.config.get("_headless"):
            # Nobody will click "confirm" in headless mode: verify the address is live, then confirm.
            check = run_command(["ip", "-4", "-o", "addr", "show", "dev", nic], timeout=10)
            if check.ok and ip.split("/")[0] in check["stdout"]:
                confirm = confirm_netplan_change()
                result["confirmed"] = confirm.get("success", False)
                self.log("Static IP verified on the interface and confirmed.")
            else:
                self.fail("netplan", "new address not present on interface; leaving revert timer armed")
        elif result.get("pending"):
            self.log(result["message"])
        return result

    # --------------------------------------------------------------- catalog
    def access_catalog(self) -> List[Dict[str, Any]]:
        ip = self.config.get("server_ip") or "127.0.0.1"
        ch_port = self.config.get("control_hub_port", 7575)
        catalog = [
            {"name": "Control Hub", "desc": "Command center, telemetry and Sleep Guard", "url": f"http://{ip}:{ch_port}", "port": ch_port, "badge": "Dashboard", "primary": True},
        ]
        if "media" in self.modules:
            catalog += [
                {"name": "Jellyfin", "desc": "Media streaming", "url": f"http://{ip}:8096", "port": 8096, "badge": "Media"},
                {"name": "Seerr", "desc": "Requests and discovery", "url": f"http://{ip}:5055", "port": 5055, "badge": "Requests"},
                {"name": "qBittorrent", "desc": "Download client", "url": f"http://{ip}:{self.config.get('qbittorrent_port', 8080)}", "port": self.config.get("qbittorrent_port", 8080), "badge": "Downloads"},
            ]
        if "photos" in self.modules:
            catalog.append({"name": "Noodle Gallery", "desc": "Photo and video cloud", "url": f"http://{ip}:{self.config.get('gallery_port', 2283)}", "port": self.config.get("gallery_port", 2283), "badge": "Photos"})
        return catalog

    # ------------------------------------------------------------------- run
    def run(self) -> Dict[str, Any]:
        if self.dry_run:
            self.log("=== DRY-RUN: nothing on the host will be modified ===")
        self.log(f"Homelab Blueprint {BLUEPRINT_VERSION} provisioning: modules={', '.join(self.modules)}")

        self.step_storage()
        self.step_environment()

        handlers = {
            "media": self.module_media,
            "photos": self.module_photos,
            "ml_schedule": self.module_ml_schedule,
            "control_hub": self.module_control_hub,
            "tv_autoupdater": self.module_tv_autoupdater,
            "sleep_guard": self.module_sleep_guard,
        }
        for module in self.modules:
            handler = handlers.get(module)
            if handler is None:
                self.warn(f"Unknown module '{module}' ignored.")
                continue
            handler()

        self.manifest.set_meta(install_dir=str(self.root), service_user=SERVICE_USER, blueprint_version=BLUEPRINT_VERSION)
        for module in self.modules:
            self.manifest.add_module(module)
        try:
            manifest_path = self.manifest.save()
            self.log(f"Install manifest written: {manifest_path}")
        except OSError as e:
            self.warn(f"could not write install manifest: {e}")

        netplan_result = self.step_netplan()

        success = not self.errors
        self.log("Provisioning completed." if success else f"Provisioning finished with {len(self.errors)} error(s).")

        ch_port = self.config.get("control_hub_port", 7575)
        return {
            "success": success,
            "version": BLUEPRINT_VERSION,
            "dry_run": self.dry_run,
            "logs": self.logs,
            "errors": self.errors,
            "warnings": self.warnings,
            "services_launched": self.services_launched,
            "launch_errors": self.errors,  # backward-compatible alias
            "access_catalog": self.access_catalog(),
            "dashboard_url": f"http://{self.config.get('server_ip') or '127.0.0.1'}:{ch_port}",
            "netplan_result": netplan_result,
            "credentials": {
                "control_hub_token": self.config.get("control_hub_token", ""),
                "qbittorrent_user": self.config.get("qbittorrent_user", "admin"),
                "qbittorrent_pass": self.config.get("qbittorrent_pass", ""),
                "media_admin_user": self.config.get("media_admin_user", "admin"),
                "media_admin_pass": self.config.get("media_admin_pass", ""),
                "postgres_password": self.config.get("postgres_password", ""),
            },
            "manifest": str(self.manifest.path),
        }


def deploy_homelab_stack(base_dir: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Public entry point used by the wizard API, headless runner and tests."""
    return Deployment(base_dir, config).run()
