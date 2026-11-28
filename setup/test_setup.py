"""
Verification test for the Homelab Blueprint Setup Wizard server and REST API.

Runs the wizard on an ephemeral localhost port with a fixed token and checks:
health (public), token enforcement (401 without, 200 with), hardware probe,
hardlink verification, secrets generation, static assets and a dry-run deploy.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from setup.server import SetupApiHandler

TEST_TOKEN = "wizard-test-token-0123456789"
PORT = 8089
BASE = f"http://127.0.0.1:{PORT}"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def request(path: str, data=None, auth: bool = True, method: str = None):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers.update(AUTH)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
        return res.status, (json.loads(raw.decode()) if res.headers.get("Content-Type", "").startswith("application/json") else raw.decode())


def test_exit_waits_for_netplan_confirm():
    """A real deploy with a pending static IP must keep the wizard up until confirm.

    The deployer and the exit timer are stubbed: no host changes, no shutdown.
    """
    import setup.server as wizard

    print("Testing wizard stays up while a static-IP change is pending...")
    scheduled = []
    original_deploy = wizard.deploy_homelab_stack
    original_exit = SetupApiHandler.schedule_exit
    original_confirm = wizard.confirm_netplan_change
    try:
        SetupApiHandler.schedule_exit = lambda self, delay: scheduled.append(delay)
        wizard.confirm_netplan_change = lambda: {"success": True, "message": "confirmed (stub)"}

        wizard.deploy_homelab_stack = lambda root, cfg: {
            "success": True, "dry_run": False,
            "netplan_result": {"success": True, "pending": True, "ip": "192.168.1.50/24", "timeout_sec": 120},
        }
        status, _ = request("/api/deploy", {"mode": "express"})
        assert status == 200
        assert scheduled == [120 + wizard.NETPLAN_EXIT_GRACE_SEC], f"pending IP: expected revert window + grace, got {scheduled}"

        status, data = request("/api/netplan/confirm", {})
        assert status == 200 and data["success"], data
        assert scheduled[-1] == wizard.EXIT_AFTER_DEPLOY_SEC, f"confirm should schedule the normal exit, got {scheduled}"

        scheduled.clear()
        wizard.deploy_homelab_stack = lambda root, cfg: {"success": True, "dry_run": False, "netplan_result": {"success": True}}
        request("/api/deploy", {"mode": "express"})
        assert scheduled == [wizard.EXIT_AFTER_DEPLOY_SEC], f"no pending IP: expected normal exit, got {scheduled}"
    finally:
        wizard.deploy_homelab_stack = original_deploy
        wizard.confirm_netplan_change = original_confirm
        SetupApiHandler.schedule_exit = original_exit
        SetupApiHandler.deployed = False


def test_photos_image_override():
    """Existing photo libraries can pin their running images; floating tags are refused."""
    from setup.installer.deployer import Deployment

    print("Testing photo image pins for existing libraries...")
    root = Path(__file__).resolve().parent.parent
    d = Deployment(str(root), {"dry_run": True})
    assert d.photos_image_override() == (True, None)

    d = Deployment(str(root), {"dry_run": True, "photos_server_image": "ghcr.io/immich-app/immich-server:v1.140.1",
                               "photos_ml_image": "ghcr.io/immich-app/immich-machine-learning@sha256:" + "a" * 64})
    ok, yml = d.photos_image_override()
    assert ok and "gallery-server:\n    image: ghcr.io/immich-app/immich-server:v1.140.1" in yml, yml
    assert "gallery-machine-learning:" in yml

    for bad in ("ghcr.io/immich-app/immich-server", "ghcr.io/immich-app/immich-server:release", "x:latest"):
        d = Deployment(str(root), {"dry_run": True, "photos_server_image": bad})
        assert d.photos_image_override() == (False, None), bad
        assert d.errors and d.errors[-1]["service"] == "photos"
    print("  [OK] pins accepted, floating tags refused")


def test_photo_external_mount():
    """An existing library can keep the container path and mode its database recorded."""
    import shutil
    import tempfile
    sys.path.insert(0, str(REPO_ROOT / "apps" / "control-hub"))
    from core.config_core.env_manager import load_env_file, sync_all_blueprint_envs

    print("Testing photo external library mount settings...")
    cases = [
        ({}, "/mnt/media", "ro"),
        ({"photo_external_mount_path": "/mnt/hdd/Memories/", "photo_external_mount_mode": "rw"}, "/mnt/hdd/Memories", "rw"),
        ({"photo_external_mount_path": "relative:bad", "photo_external_mount_mode": "yes"}, "/mnt/media", "ro"),
    ]
    for extra, want_path, want_mode in cases:
        tmp = Path(tempfile.mkdtemp(prefix="photo_mount_"))
        try:
            module = tmp / "apps" / "noodle-gallery"
            module.mkdir(parents=True)
            shutil.copy(REPO_ROOT / "apps" / "noodle-gallery" / ".env.example", module / ".env.example")
            out = sync_all_blueprint_envs(str(tmp), dict(extra))
            env = load_env_file(out["noodle_gallery_env"])
            assert env.get("EXTERNAL_LIBRARY_MOUNT_PATH") == want_path, (extra, env.get("EXTERNAL_LIBRARY_MOUNT_PATH"))
            assert env.get("EXTERNAL_LIBRARY_MOUNT_MODE") == want_mode, (extra, env.get("EXTERNAL_LIBRARY_MOUNT_MODE"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    compose = (REPO_ROOT / "apps" / "noodle-gallery" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${EXTERNAL_LIBRARY_MOUNT_PATH:-/mnt/media}:${EXTERNAL_LIBRARY_MOUNT_MODE:-ro}" in compose
    print("  [OK] defaults /mnt/media:ro, overrides kept, bad values fall back")


def test_release_preferences():
    """Release preferences: defaults, validation, and upgrades that keep (or default off) the pack."""
    from setup.installer.release_prefs import normalize_release_prefs, supported_languages

    print("Testing release preference validation and upgrade defaults...")
    langs = supported_languages(REPO_ROOT)
    pack_langs = json.loads((REPO_ROOT / "apps" / "mediaserver" / "profiles" / "languages.json").read_text(encoding="utf-8"))
    assert langs == [entry["name"] for entry in pack_langs["languages"]] and "Hindi" in langs, langs

    prefs, errors = normalize_release_prefs({}, REPO_ROOT)
    assert not errors and prefs["media_profiles"] is True and prefs["media_second_language"] == ""
    assert prefs["media_default_profile"] == "compact" and prefs["media_codecs"] == ["hevc"], prefs

    prefs, errors = normalize_release_prefs({"media_second_language": "hindi", "media_default_profile": "dual-audio-first",
                                             "media_codecs": "av1,hevc", "media_seeding": "off"}, REPO_ROOT)
    assert not errors, errors
    assert prefs["media_second_language"] == "Hindi" and prefs["media_codecs"] == ["hevc", "av1"]

    for bad in ({"media_default_profile": "dual-audio-first"}, {"media_second_language": "Klingon"},
                {"media_codecs": ["vp9"]}, {"media_seeding": "forever"}, {"media_stuck_downloads": "maybe"}):
        _, errors = normalize_release_prefs(bad, REPO_ROOT)
        assert errors, f"expected an error for {bad}"

    # Upgrade from a pre-pack install: no media_* keys, env without MEDIA_PROFILES -> off.
    prefs, _ = normalize_release_prefs({}, REPO_ROOT, existing_env={"PUID": "1000"})
    assert prefs["media_profiles"] is False, prefs
    prefs, _ = normalize_release_prefs({}, REPO_ROOT, existing_env={"MEDIA_PROFILES": "on", "MEDIA_SECOND_LANGUAGE": "Tamil",
                                                                    "MEDIA_CODECS": "hevc,dv"})
    assert prefs["media_profiles"] is True and prefs["media_second_language"] == "Tamil" and prefs["media_codecs"] == ["hevc", "dv"]
    prefs, _ = normalize_release_prefs({"media_profiles": True}, REPO_ROOT, existing_env={"PUID": "1000"})
    assert prefs["media_profiles"] is True, "an explicit wizard answer wins over the upgrade default"
    print("  [OK] defaults, validation and upgrade behaviour")


def test_schema_migrator_upgrade_default():
    """The schema migrator adds MEDIA_PROFILES=off to an existing mediaserver.env."""
    import tempfile
    from setup.installer.schema_migrator import migrate_single_env

    print("Testing the schema migrator's upgrade default for MEDIA_PROFILES...")
    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / "mediaserver.env"
        env.write_text("PUID=1000\nPGID=1000\n", encoding="utf-8")
        result = migrate_single_env(env, REPO_ROOT / "apps" / "mediaserver" / ".env.example", backup_dir=Path(tmp) / "bak")
        assert result["success"] and "MEDIA_PROFILES" in result["injected_keys"], result
        text = env.read_text(encoding="utf-8")
        assert "\nMEDIA_PROFILES=off\n" in text and "MEDIA_PROFILES=on" not in text, text
        assert "MEDIA_SECOND_LANGUAGE=" in text
    print("  [OK] existing installs opt in to the profile pack")


def test_no_stdlib_shadowing():
    """Scripts run directly put their folder first on sys.path, so a file named after a
    standard module (token.py, secrets.py, ...) breaks any stdlib import of it."""
    import subprocess
    print("Testing that no file shadows a standard library module...")
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.split()
    names = getattr(sys, "stdlib_module_names", None)
    if not names:  # Python < 3.10
        print("  [SKIP] sys.stdlib_module_names needs Python 3.10+")
        return
    bad = [f for f in files if Path(f).stem in names]
    assert not bad, f"rename these files, they shadow standard modules: {bad}"
    print(f"  [OK] {len(files)} files checked")


def test_sudoers_template_sudo_rs():
    """sudo-rs (Ubuntu 26.04) accepts a wildcard only as a whole last argument."""
    print("Testing the sudoers template against sudo-rs rules...")
    tpl = (REPO_ROOT / "system" / "systemd" / "homelab-sudoers.example").read_text(encoding="utf-8")
    for line in tpl.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "NOPASSWD:" not in line:
            continue
        args = line.split("NOPASSWD:", 1)[1].split()
        for i, arg in enumerate(args):
            if any(c in arg for c in "*?[") and not (arg == "*" and i == len(args) - 1):
                raise AssertionError(f"sudo-rs rejects this wildcard: {line.strip()}")
    print("  [OK] wildcards only as a whole trailing argument")


def run_tests():
    SetupApiHandler.token = TEST_TOKEN
    server = ThreadingHTTPServer(("127.0.0.1", PORT), SetupApiHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)

    try:
        print("Testing GET /api/health (public)...")
        status, data = request("/api/health", auth=False)
        assert status == 200 and data["status"] == "healthy", data

        print("Testing token enforcement: GET /api/probe without token must be 401...")
        try:
            request("/api/probe", auth=False)
            raise AssertionError("expected HTTP 401 without token")
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"expected 401, got {e.code}"

        print("Testing token enforcement: wrong token must be 401...")
        try:
            req = urllib.request.Request(BASE + "/api/probe", headers={"Authorization": "Bearer nope"})
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("expected HTTP 401 with wrong token")
        except urllib.error.HTTPError as e:
            assert e.code == 401

        print("Testing GET /api/probe...")
        status, data = request("/api/probe")
        assert status == 200
        print(" -> CPU:", data["cpu"]["model"])
        print(" -> RAM:", data["ram"]["total_gib"], "GiB")
        print(" -> Active NIC:", data["network"]["active_nic"])
        print(" -> Disks count:", len(data["disks"]))
        assert data["network"]["active_nic"], "active NIC must be detected"

        print("Testing GET /api/ai/context...")
        status, data = request("/api/ai/context")
        assert status == 200 and len(data["prompt"]) > 100

        print("Testing POST /api/verify/hardlink...")
        status, data = request("/api/verify/hardlink", {"path": "."})
        assert status == 200
        print(" -> Hardlink test result:", data)

        print("Testing POST /api/secrets/generate...")
        status, data = request("/api/secrets/generate", {})
        assert status == 200
        for key in ("qbittorrent_pass", "postgres_password", "radarr_api_key"):
            assert len(data[key]) >= 16, key
        print(" -> Generated secrets:", list(data.keys()))

        print("Testing static HTML / CSS / JS (public)...")
        status, html = request("/", auth=False)
        assert status == 200 and "Homelab Blueprint Setup" in html
        status, css = request("/css/setup.css", auth=False)
        assert status == 200 and "--cyan" in css
        status, js = request("/js/setup.js", auth=False)
        assert status == 200 and "Authorization" in js, "wizard JS must send the bearer token"

        print("Testing path traversal is blocked...")
        try:
            request("/../server.py", auth=False)
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404)

        print("Testing POST /api/deploy with dry_run=True...")
        deploy_payload = {
            "mode": "express",
            "dry_run": True,
            "hdd_data": "/mnt/hdd/data",
            "hdd_memories": "/mnt/hdd/Memories",
            "server_ip": "192.168.1.100",
            "enable_static_ip": True,
            "active_nic": "enp3s0",
            "qbittorrent_pass": "testpass123",
            "puid": 1000,
            "pgid": 1000,
            "timezone": "UTC",
            "enabled_services": ["media", "photos", "control_hub"],
        }
        status, deploy_res = request("/api/deploy", deploy_payload)
        assert status == 200
        assert deploy_res["success"] is True, deploy_res.get("errors")
        assert deploy_res["dry_run"] is True
        assert deploy_res["credentials"]["control_hub_token"], "a Control Hub token must be generated"
        assert deploy_res["credentials"]["postgres_password"] not in ("", "postgres"), "no default DB password"
        print(" -> Deployment success:", deploy_res["success"])
        print(" -> Services launched:", deploy_res["services_launched"])
        print(" -> Dashboard URL:", deploy_res["dashboard_url"])

        preview_env = REPO_ROOT / "setup" / "dry_run_preview" / "etc" / "homelab" / "mediaserver.env"
        assert preview_env.exists(), "dry run must render env previews under setup/dry_run_preview/etc/homelab"
        rendered = preview_env.read_text(encoding="utf-8")
        assert "QBITTORRENT_PASS=testpass123" in rendered
        assert "adminadmin" not in rendered

        print("Testing the Release preferences step (languages endpoint, page, validation, rendering)...")
        status, data = request("/api/release/languages")
        assert status == 200 and "Hindi" in data["languages"], data
        for element_id in ("pow-rel-language", "pow-rel-default", "pow-rel-hevc", "pow-rel-av1", "pow-rel-dv",
                           "pow-rel-seeding", "pow-rel-stuck", "pow-rel-pack", "exp-rel-language"):
            assert f'id="{element_id}"' in html, f"wizard page is missing #{element_id}"
        assert "media_second_language" in js and "/api/release/languages" in js
        try:
            request("/api/deploy", dict(deploy_payload, media_default_profile="dual-audio-first", media_second_language=""))
            raise AssertionError("expected HTTP 400 for Dual Audio First without a language")
        except urllib.error.HTTPError as e:
            assert e.code == 400, e.code
            body = json.loads(e.read().decode())
            assert body["errors"] and body["errors"][0]["service"] == "media", body
        status, deploy_res = request("/api/deploy", dict(deploy_payload, media_profiles=True, media_second_language="Hindi",
                                                          media_default_profile="dual-audio-first", media_codecs=["hevc", "av1"],
                                                          media_seeding="off", media_stuck_downloads="replace"))
        assert status == 200 and deploy_res["success"] is True, deploy_res.get("errors")
        rendered = preview_env.read_text(encoding="utf-8")
        for line in ("MEDIA_PROFILES=on", "MEDIA_SECOND_LANGUAGE=Hindi", "MEDIA_DEFAULT_PROFILE=dual-audio-first",
                     "MEDIA_CODECS=hevc,av1", "MEDIA_SEEDING=off", "MEDIA_STUCK_DOWNLOADS=replace"):
            assert line in rendered.splitlines(), f"{line} missing from the rendered mediaserver.env"
        assert any("release profile pack" in line for line in deploy_res["logs"]), "dry run should say it would apply the pack"
        assert any("'Dual Audio First' as the default profile" in line for line in deploy_res["logs"])

        test_exit_waits_for_netplan_confirm()
        test_release_preferences()
        test_schema_migrator_upgrade_default()
        test_photos_image_override()
        test_photo_external_mount()
        test_no_stdlib_shadowing()
        test_sudoers_template_sudo_rs()

        print("ALL TESTS PASSED WITH 100% SUCCESS!")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_tests()
