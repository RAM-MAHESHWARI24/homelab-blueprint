#!/usr/bin/env python3
"""
Nightly off-site backup of the media apps' settings (standard library + rclone).

What it saves: every app's configuration under MEDIA_APPDATA (default
/srv/homelab/appdata/mediaserver): the Sonarr, Radarr, Prowlarr, Bazarr and Seerr
databases, Jellyfin's database and settings, qBittorrent's settings and torrent
list. What it skips, because it is large and comes back by itself: logs, caches,
transcodes, cover art (MediaCover) and Jellyfin's downloaded metadata images.

Databases are copied with SQLite's online backup API, so the apps keep running.

    0. Pre-flight  rclone and the remote answer, the folder exists, enough space
    1. Snapshot    consistent copy into a staging folder
    2. Archive     media_config_YYYYMMDD_HHMMSS.tar.zst (or .tar.gz without zstd)
    3. Upload      rclone copy to <remote>Media_Backup/, then checked on the remote
    4. Retention   newest KEEP_LOCAL here; newest KEEP_REMOTE plus the first archive
                   of each of the last KEEP_MONTHLY months on the remote

Progress and the last 30 runs go to status.json next to the archives (0644, written
atomically); the Control Hub's backup card and alerts read it. Only one run at a time.

Settings come from the environment; values that are not set are read from
/etc/cron.d/media-backup (MEDIA_BACKUP_CRON_FILE), so a run started by hand uses the
same remote as the nightly job.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SETTING_KEYS = ("MEDIA_APPDATA", "MEDIA_BACKUP_DIR", "GDRIVE_REMOTE", "KEEP_LOCAL", "KEEP_REMOTE", "KEEP_MONTHLY",
                "INCLUDE_JELLYFIN_METADATA")
ARCHIVE_PREFIX = "media_config_"
ARCHIVE_RE = re.compile(r"^media_config_(\d{8})_(\d{6})\.tar\.(zst|gz)$")
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")
HISTORY_LIMIT = 30

# Skipped anywhere in the tree (directory names), and file patterns.
SKIP_DIRS = {"logs", "log", "cache", "Cache", "transcodes", "MediaCover", "Backups", "crash-reports", "__pycache__"}
SKIP_FILE_SUFFIXES = (".log", ".pid", ".lock", "-wal", "-shm", "-journal", ".tmp")
SKIP_FILE_NAMES = {"logs.db", "lockfile"}
SKIP_FILE_RE = re.compile(r"\.log\.\d+$|\.txt\.\d+$")


# ---------------------------------------------------------------- settings

def load_settings(env: Dict[str, str]) -> Dict[str, str]:
    values = {k: env[k] for k in SETTING_KEYS if env.get(k)}
    cron = Path(env.get("MEDIA_BACKUP_CRON_FILE", "/etc/cron.d/media-backup"))
    try:
        for line in cron.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key in SETTING_KEYS and key not in values and value:
                values[key] = value
    except OSError:
        pass
    remote = values.get("GDRIVE_REMOTE", "")
    if remote and not remote.endswith((":", "/")):
        remote += "/"
    return {
        "appdata": values.get("MEDIA_APPDATA", "/srv/homelab/appdata/mediaserver"),
        "local": values.get("MEDIA_BACKUP_DIR", "/var/lib/homelab/media-backups"),
        "remote": remote,
        "remote_dir": f"{remote}Media_Backup" if remote else "",
        "keep_local": int(values.get("KEEP_LOCAL", "3")),
        "keep_remote": int(values.get("KEEP_REMOTE", "14")),
        "keep_monthly": int(values.get("KEEP_MONTHLY", "12")),
        "jellyfin_metadata": values.get("INCLUDE_JELLYFIN_METADATA", "0").lower() in ("1", "true", "yes"),
    }


# ---------------------------------------------------------------- snapshot

def should_skip(rel: Path, is_dir: bool, jellyfin_metadata: bool) -> bool:
    name = rel.name
    if is_dir:
        if name in SKIP_DIRS:
            return True
        # Jellyfin's downloaded posters and NFOs (about 1 GB) come back from the internet.
        return (not jellyfin_metadata) and rel.parts[-3:] == ("jellyfin", "data", "metadata")
    if name in SKIP_FILE_NAMES or name.endswith(SKIP_FILE_SUFFIXES) or SKIP_FILE_RE.search(name):
        return True
    return False


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def copy_database(src: Path, dst: Path) -> None:
    """Consistent copy of a live SQLite database (WAL included) without stopping the app."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
    try:
        target = sqlite3.connect(str(dst))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def snapshot(appdata: Path, staging: Path, jellyfin_metadata: bool) -> Dict[str, int]:
    """Copies the settings tree into `staging`; returns counts."""
    stats = {"files": 0, "databases": 0, "bytes": 0, "skipped_dirs": 0}
    for dirpath, dirnames, filenames in os.walk(appdata):
        here = Path(dirpath)
        rel_dir = here.relative_to(appdata)
        keep = []
        for d in dirnames:
            if should_skip(rel_dir / d, True, jellyfin_metadata) or (here / d).is_symlink():
                stats["skipped_dirs"] += 1
            else:
                keep.append(d)
        dirnames[:] = keep
        (staging / rel_dir).mkdir(parents=True, exist_ok=True)
        for f in filenames:
            rel = rel_dir / f
            src = here / f
            if should_skip(rel, False, jellyfin_metadata) or src.is_symlink() or not src.is_file():
                continue
            dst = staging / rel
            if f.endswith(DB_SUFFIXES) and src.stat().st_size > 0:
                try:
                    copy_database(src, dst)
                    stats["databases"] += 1
                except sqlite3.Error:
                    shutil.copy2(src, dst)  # not SQLite after all
            else:
                shutil.copy2(src, dst)
            if _is_root():
                st = src.stat()
                os.chown(dst, st.st_uid, st.st_gid)  # keep the apps' owner (PUID) for a restore
            stats["files"] += 1
            stats["bytes"] += dst.stat().st_size
    return stats


def make_archive(staging: Path, out_dir: Path, stamp: str) -> Path:
    zstd = shutil.which("zstd")
    if zstd:
        out = out_dir / f"{ARCHIVE_PREFIX}{stamp}.tar.zst"
        tar = subprocess.Popen(["tar", "-C", str(staging), "-cf", "-", "."], stdout=subprocess.PIPE)
        with open(out, "wb") as fh:
            comp = subprocess.run([zstd, "-q", "-T0", "-10"], stdin=tar.stdout, stdout=fh, check=False)
        tar.stdout.close()
        if tar.wait() != 0 or comp.returncode != 0:
            out.unlink(missing_ok=True)
            raise RuntimeError("tar | zstd failed")
        return out
    out = out_dir / f"{ARCHIVE_PREFIX}{stamp}.tar.gz"
    with tarfile.open(out, "w:gz", compresslevel=6) as tf:
        tf.add(str(staging), arcname=".")
    return out


# ---------------------------------------------------------------- retention

def plan_retention(names: List[str], keep: int, monthly: int, protect: Optional[str] = None) -> Dict[str, List[str]]:
    """Newest `keep` archives plus the first archive of each of the newest `monthly` months."""
    dated = []
    for n in set(names):
        m = ARCHIVE_RE.match(n)
        if m:
            dated.append((datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), n))
    dated.sort(reverse=True)
    keep_set = {n for _, n in dated[: max(0, keep)]}
    if monthly > 0:
        firsts: Dict[str, Tuple[datetime, str]] = {}
        for t, n in dated:
            k = t.strftime("%Y-%m")
            if k not in firsts or t < firsts[k][0]:
                firsts[k] = (t, n)
        for k in sorted(firsts, reverse=True)[:monthly]:
            keep_set.add(firsts[k][1])
    if protect:
        keep_set.add(protect)
    return {"keep": [n for _, n in dated if n in keep_set], "delete": sorted(n for _, n in dated if n not in keep_set)}


# ---------------------------------------------------------------- status.json

class Status:
    def __init__(self, path: Path, remote: str):
        self.path = path
        try:
            self.prev = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(self.prev, dict):
                self.prev = {}
        except (OSError, ValueError):
            self.prev = {}
        self.data = {
            "status": "syncing", "stage": 0, "stage_label": "0. Pre-flight", "message": "Checking the remote and free space...",
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"), "completed_at": None,
            "last_good_at": self.prev.get("last_good_at"), "remote": remote,
            "last_good_remote": self.prev.get("last_good_remote")
            or (self.prev.get("remote") if self.prev.get("last_good_at") else None),
            "dump_file": self.prev.get("dump_file"), "dump_bytes": self.prev.get("dump_bytes"),
            "preflight": {"ok": True, "checks": []}, "transfer": None,
            "retention": self.prev.get("retention"), "snapshot": None,
            "history": list(self.prev.get("history") or []),
        }

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.data["preflight"]["checks"].append({"name": name, "ok": ok, "detail": detail})
        self.data["preflight"]["ok"] = self.data["preflight"]["ok"] and ok
        log(f"  [{'ok' if ok else 'fail'}] {name}: {detail}")

    def stage(self, n: int, label: str, message: str) -> None:
        self.data.update(stage=n, stage_label=label, message=message)
        self.write()

    def finish(self, ok: bool, message: str) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        d = self.data
        d.update(status="synced" if ok else "error", message=message, completed_at=now)
        if ok:
            d["last_good_at"] = now
            d["last_good_remote"] = d["remote"]
        try:
            duration = int((datetime.fromisoformat(now) - datetime.fromisoformat(d["started_at"])).total_seconds())
        except ValueError:
            duration = None
        entry = {"started_at": d["started_at"], "completed_at": now, "outcome": d["status"], "message": message,
                 "dump_file": d["dump_file"] if ok else None, "dump_bytes": d["dump_bytes"] if ok else None,
                 "files": (d.get("snapshot") or {}).get("files"), "bytes": (d.get("transfer") or {}).get("bytes"),
                 "duration_s": duration}
        d["history"] = ([entry] + d["history"])[:HISTORY_LIMIT]  # finish() runs once per run
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- helpers

LOG_FH = None


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    if LOG_FH:
        LOG_FH.write(line + "\n")
        LOG_FH.flush()


def rclone(args: List[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(["rclone", *args], capture_output=True, text=True, timeout=timeout)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


class PreflightError(Exception):
    pass


def detach_from_control_hub(argv: List[str]) -> None:
    """Started by "Run now" in the Control Hub: move into a unit of our own (see the photo backup)."""
    if os.environ.get("MEDIA_BACKUP_DETACHED") or not _is_root() or not shutil.which("systemd-run"):
        return
    try:
        if "control-hub.service" not in Path("/proc/self/cgroup").read_text():
            return
    except OSError:
        return
    unit = f"media-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    os.execvp("systemd-run", ["systemd-run", "--quiet", "--collect", f"--unit={unit}",
                              "--setenv=MEDIA_BACKUP_DETACHED=1", sys.executable, os.path.abspath(argv[0]), *argv[1:]])


# ---------------------------------------------------------------- main

def run(settings: Dict) -> int:
    import fcntl  # Linux only; imported here so the helpers can be tested anywhere

    global LOG_FH
    local = Path(settings["local"])
    local.mkdir(parents=True, exist_ok=True)
    lock = open(local / ".backup.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another media settings backup is running; not starting a second one.", file=sys.stderr)
        return 0
    LOG_FH = open(local / "backup.log", "a", encoding="utf-8")
    status = Status(local / "status.json", settings["remote"])
    log("=" * 50)
    log("Starting media settings backup")
    status.write()
    staging = None
    try:
        # 0. Pre-flight
        appdata = Path(settings["appdata"])
        if not appdata.is_dir() or not any(appdata.iterdir()):
            status.check("settings folder", False, f"{appdata} is missing or empty")
            raise PreflightError(f"Pre-flight: {appdata} is missing or empty.")
        status.check("settings folder", True, str(appdata))
        if not settings["remote"]:
            status.check("remote", False, "GDRIVE_REMOTE is not set")
            raise PreflightError("Pre-flight: no rclone remote configured (GDRIVE_REMOTE).")
        if not shutil.which("rclone"):
            status.check("rclone", False, "rclone is not installed")
            raise PreflightError("Pre-flight: rclone is not installed.")
        res = rclone(["lsd", settings["remote"]], timeout=120)
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "no output").strip().splitlines()[-1]
            status.check("remote", False, f"{settings['remote']} did not answer: {detail}")
            raise PreflightError(f"Pre-flight: the remote {settings['remote']} did not answer ({detail}).")
        status.check("remote", True, f"{settings['remote']} answers")
        has_folder = any(line.split()[-1] == "Media_Backup" for line in res.stdout.splitlines() if line.strip())
        # Only for the same remote: after switching remotes the first run creates the folder.
        if not has_folder and status.data["last_good_at"] and status.data["last_good_remote"] == settings["remote"]:
            status.check("folder Media_Backup", False, "missing although earlier runs wrote to it")
            raise PreflightError(f"Pre-flight: {settings['remote_dir']} is missing although earlier runs wrote to it. Was it moved or renamed?")
        status.check("folder Media_Backup", True, "present" if has_folder else "not there yet; this run creates it")
        need = max(1 << 30, 2 * int(status.prev.get("dump_bytes") or 0))
        free = shutil.disk_usage(local).free
        if free < need:
            status.check("local space", False, f"{human(free)} free, need {human(need)}")
            raise PreflightError(f"Pre-flight: only {human(free)} free in {local}.")
        status.check("local space", True, f"{human(free)} free")

        # 1. Snapshot
        status.stage(1, "1. Snapshot", "Copying settings and databases...")
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=local))
        os.chmod(staging, 0o700)
        snap = snapshot(appdata, staging, settings["jellyfin_metadata"])
        status.data["snapshot"] = snap
        log(f"Snapshot: {snap['files']} files ({snap['databases']} databases), {human(snap['bytes'])}")

        # 2. Archive
        status.stage(2, "2. Archive", "Compressing the snapshot...")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive = make_archive(staging, local, stamp)
        os.chmod(archive, 0o600)  # contains API keys and password hashes
        status.data.update(dump_file=archive.name, dump_bytes=archive.stat().st_size)
        log(f"Archive: {archive.name} ({human(archive.stat().st_size)})")

        # 3. Upload
        status.stage(3, "3. Upload", f"Uploading to {settings['remote_dir']}...")
        res = rclone(["copy", str(archive), settings["remote_dir"] + "/"])
        if res.returncode != 0:
            raise RuntimeError(f"Upload failed: {(res.stderr or res.stdout).strip().splitlines()[-1]}")
        status.data["transfer"] = {"files": 1, "bytes": archive.stat().st_size}

        # 4. Retention and verification
        status.stage(4, "4. Verified", "Applying retention and checking the upload...")
        local_names = [p.name for p in local.iterdir()]
        for old in plan_retention(local_names, settings["keep_local"], 0, archive.name)["delete"]:
            log(f"  local: deleting {old}")
            (local / old).unlink(missing_ok=True)
        res = rclone(["lsf", "--files-only", settings["remote_dir"] + "/"], timeout=300)
        if res.returncode != 0:
            raise RuntimeError("Could not list the remote folder to verify the upload.")
        remote_names = [n.strip() for n in res.stdout.splitlines() if n.strip()]
        if archive.name not in remote_names:
            raise RuntimeError(f"{archive.name} is not on {settings['remote_dir']} after the upload.")
        plan = plan_retention(remote_names, settings["keep_remote"], settings["keep_monthly"], archive.name)
        for old in plan["delete"]:
            log(f"  remote: deleting {old}")
            if rclone(["deletefile", f"{settings['remote_dir']}/{old}"], timeout=300).returncode != 0:
                log(f"  Warning: could not delete {old}")
        following = plan_retention(plan["keep"] + [f"{ARCHIVE_PREFIX}99991231_235959.tar.zst"],
                                   settings["keep_remote"], settings["keep_monthly"], f"{ARCHIVE_PREFIX}99991231_235959.tar.zst")
        status.data["retention"] = {"kept": len(plan["keep"]), "delete": plan["delete"], "next_delete": following["delete"]}
        status.finish(True, f"Media settings backed up to {settings['remote_dir']}")
        log("Media settings backup completed successfully")
        return 0
    except PreflightError as exc:
        log(f"ERROR: {exc}")
        status.finish(False, str(exc))
        return 1
    except Exception as exc:  # anything else: record it, never leave "syncing" behind
        log(f"ERROR: {exc}")
        status.finish(False, f"Failed during step {status.data['stage']} ({status.data['stage_label']}): {exc}")
        return 1
    finally:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)
        LOG_FH.close()
        LOG_FH = None


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print-settings", action="store_true", help="show the settings this run would use and exit")
    args = parser.parse_args(argv[1:])
    settings = load_settings(dict(os.environ))
    if args.print_settings:
        print(json.dumps(settings, indent=2))
        return 0
    detach_from_control_hub(argv)
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())
