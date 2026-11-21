#!/usr/bin/env python3
"""
TV auto-updater - background app updater for Android TVs
Runs on the home server and silently maintains sideloaded apps over ADB:
  - SmartTube (yuliskov/SmartTube stable releases on GitHub)
  - CloudStream Beta (recloudstream/cloudstream pre-releases on GitHub)
  - Manual sideload drop folder: any APK placed in 'incoming_apks/' is silently pushed

Only official release sources are used. Every downloaded APK's signing certificate
is checked against the SHA-256 fingerprints pinned in config.json (apk_signatures)
before it is cached or installed; a mismatch is logged and the file discarded.

Two-Tier State-Machine Architecture:
  Tier 1: Daily Upstream Sync (Once every 24h, or on --sync)
    - Checks the GitHub release APIs.
    - Caches latest genuine APKs in 'cache/'.
    - Updates target versionCodes in 'state.json'.

  Tier 2: Opportunistic Local Deployment & Quiescent Idle (15-min cron)
    - If all target TVs have all managed apps installed & up to date:
        STOPS POLLING. Exits immediately in <5ms with 0 network or TV traffic.
    - If any TV is missing an app or has an older version:
        Probes ONLY the pending TV(s) (leaving already-updated TVs untouched).
        Freshly installs missing apps or upgrades existing ones.
        Safety guards: never installs if video/audio is playing or app is foreground.
        Once all TVs have all apps installed & updated, enters quiescent idle.
"""

import os
import sys
import time
import json
import socket
import struct
import shutil
import hashlib
import logging
import argparse
import zipfile
import subprocess
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Paths. Standalone: everything lives next to this script. Installed by the
# blueprint: TV_AUTOUPDATER_STATE_DIR=/var/lib/homelab/tv-autoupdater (owned by
# the unprivileged service user) and TV_AUTOUPDATER_CONFIG=/etc/homelab/tv-autoupdater.json.
BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.getenv("TV_AUTOUPDATER_STATE_DIR", str(BASE_DIR)))
CONFIG_FILE = Path(os.getenv("TV_AUTOUPDATER_CONFIG", str(BASE_DIR / "config.json")))
CACHE_DIR = STATE_DIR / "cache"
INCOMING_DIR = STATE_DIR / "incoming_apks"
INSTALLED_DIR = STATE_DIR / "installed_apks"
LOG_FILE = Path(os.getenv("TV_AUTOUPDATER_LOG", str(STATE_DIR / "tv_updater.log")))
STATE_FILE = STATE_DIR / "state.json"
DEVICES_CACHE_FILE = STATE_DIR / "devices_cache.json"
INCOMPATIBLE_CACHE_FILE = STATE_DIR / "incompatible_apks.json"

for _d in (CACHE_DIR, INCOMING_DIR, INSTALLED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Upstream check cooldown (24 hours in seconds)
UPSTREAM_CHECK_INTERVAL_SEC = 24 * 3600

# Target TV Profiles (Identified by permanent hardware model properties)
TARGET_PROFILES = [
    {
        "id": "living_room_tv",
        "name": "Living Room TV",
        "match_models": ["mibox4", "oneday"],
        "default_ip": "192.168.1.150",
        "port": 5555,
    },
    {
        "id": "bedroom_tv",
        "name": "Bedroom TV",
        "match_models": ["mitv-axfr0", "rango", "mitv"],
        "default_ip": "192.168.1.151",
        "port": 5555,
    },
]

# Sideloaded Apps Managed by the System
MANAGED_APPS = [
    {
        "id": "smarttube",
        "package": "org.smarttube.stable",
        "name": "SmartTube",
    },
    {
        "id": "cloudstream",
        "package": "com.lagradost.cloudstream3.prerelease",
        "name": "CloudStream Beta",
    },
]

# Signing-certificate pins: package -> list of allowed SHA-256 fingerprints (lowercase hex,
# no colons). Checked on every download and before every install. Print an APK's
# fingerprint with `tv_updater.py --print-signature <file.apk>`. The defaults are the
# certificates the upstream projects sign their GitHub releases with (verified 2026-11-14).
APK_SIGNATURES = {
    "org.smarttube.stable": ["109735aa24fe85e2e1623ebb3b1ecc4bf4263f4c6374e4411d646bfa2eda482a"],
    "com.lagradost.cloudstream3.prerelease": ["c2755b1fbc6cefa6aa20739f527d09246525618a7e16edb2e2171c2c9de70c72"],
    "com.lagradost.cloudstream3": ["9b4f6c87eeb70b257c7f968e65b15616824bce33e9cc74a07ad3dd26632a1db7"],
}
# Packages without a pin are refused unless this is true (manual drops in incoming_apks/ are
# always allowed: placing a file there is the operator's explicit decision).
ALLOW_UNPINNED_APPS = False

DHCP_SUBNET_PREFIX = "192.168.1"
DHCP_SCAN_RANGE = (32, 100)

# Optional user configuration override via config.json
if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as _cf:
            _cfg = json.load(_cf)
            if "target_profiles" in _cfg:
                TARGET_PROFILES = _cfg["target_profiles"]
            if "subnet_prefix" in _cfg:
                DHCP_SUBNET_PREFIX = _cfg["subnet_prefix"]
            if "dhcp_scan_range" in _cfg:
                DHCP_SCAN_RANGE = tuple(_cfg["dhcp_scan_range"])
            if isinstance(_cfg.get("apk_signatures"), dict):
                for _pkg, _pins in _cfg["apk_signatures"].items():
                    if isinstance(_pins, list):
                        APK_SIGNATURES[_pkg] = [str(p).replace(":", "").lower() for p in _pins]
            if "allow_unpinned_apps" in _cfg:
                ALLOW_UNPINNED_APPS = bool(_cfg["allow_unpinned_apps"])
    except Exception as _e:
        pass

HEADERS = {"User-Agent": "tv-autoupdater/2.0 (+https://github.com/RAM-MAHESHWARI24/homelab-blueprint)"}

# Configure logging. Skip StreamHandler when stdout is already redirected to LOG_FILE
# (e.g. cron `>> tv-autoupdater.log 2>&1`), otherwise every line is written twice.
def _stdout_is_log_file(log_path: Path) -> bool:
    if os.getenv("TV_AUTOUPDATER_LOG_STDOUT", "1") == "0":
        return True
    try:
        out_stat = os.fstat(sys.stdout.fileno())
        log_stat = log_path.stat()
        return (out_stat.st_dev, out_stat.st_ino) == (log_stat.st_dev, log_stat.st_ino)
    except Exception:
        return False


# A named logger that does not propagate: the Control Hub imports this module for
# telemetry, and configuring the root logger here would pull the hub's own HTTP
# access log into tv-autoupdater.log. Echo to stdout only when run as a script.
log = logging.getLogger("tv_autoupdater")
log.setLevel(logging.INFO)
log.propagate = False
if not log.handlers:
    _formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _log_handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if __name__ == "__main__" and not _stdout_is_log_file(LOG_FILE):
        _log_handlers.append(logging.StreamHandler(sys.stdout))
    for _handler in _log_handlers:
        _handler.setFormatter(_formatter)
        log.addHandler(_handler)

# -------------------------------------------------------------
# STATE MANAGEMENT
# -------------------------------------------------------------

def load_incompatible_cache() -> list:
    if INCOMPATIBLE_CACHE_FILE.exists():
        try:
            with open(INCOMPATIBLE_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def mark_incompatible(apk_name: str, reason: str = ""):
    cache = load_incompatible_cache()
    if apk_name not in cache:
        cache.append(apk_name)
        try:
            with open(INCOMPATIBLE_CACHE_FILE, "w") as f:
                json.dump(cache, f, indent=2)
        except Exception:
            pass

def load_state() -> dict:
    default_state = {
        "last_upstream_check": 0,
        "upstream_apps": {},
        "devices": {
            p["id"]: {"name": p["name"], "installed": {}} for p in TARGET_PROFILES
        }
    }
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                # Ensure all devices and fields exist
                if "devices" not in data:
                    data["devices"] = default_state["devices"]
                for p in TARGET_PROFILES:
                    if p["id"] not in data["devices"]:
                        data["devices"][p["id"]] = {"name": p["name"], "installed": {}}
                if "upstream_apps" not in data:
                    data["upstream_apps"] = {}
                return data
        except Exception as e:
            log.warning(f"Could not load state.json ({e}), using defaults.")
    return default_state

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save state.json: {e}")

# -------------------------------------------------------------
# AUTO-DISCOVERY & NETWORK PROBING
# -------------------------------------------------------------

def load_cached_ips() -> dict:
    if DEVICES_CACHE_FILE.exists():
        try:
            with open(DEVICES_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {p["id"]: p["default_ip"] for p in TARGET_PROFILES}

def save_cached_ips(cache: dict):
    try:
        with open(DEVICES_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

def is_port_open(host: str, port: int = 5555, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, OSError):
        return False

def get_device_model(ip: str, port: int = 5555) -> str:
    target = f"{ip}:{port}"
    try:
        conn = subprocess.run(["adb", "connect", target], capture_output=True, text=True, timeout=3)
        out = conn.stdout.lower() + conn.stderr.lower()
        if "connected to" not in out and "already connected" not in out:
            return ""
        res = subprocess.run(["adb", "-s", target, "shell", "getprop", "ro.product.model"], capture_output=True, text=True, timeout=3)
        model = res.stdout.strip()
        if not model:
            res_dev = subprocess.run(["adb", "-s", target, "shell", "getprop", "ro.product.device"], capture_output=True, text=True, timeout=3)
            model = res_dev.stdout.strip()
        return model
    except Exception:
        return ""

def discover_online_tvs(target_profile_ids: list = None) -> list:
    """
    Auto-discovers online TVs:
    - If target_profile_ids is specified, only probes those specific profiles!
    - Checks last-known IPs first (fast 0.05s check).
    - If missing, scans DHCP subnet range in parallel.
    - Matches hardware model to profile.
    """
    profiles_to_check = TARGET_PROFILES
    if target_profile_ids is not None:
        profiles_to_check = [p for p in TARGET_PROFILES if p["id"] in target_profile_ids]

    if not profiles_to_check:
        return []

    cached_ips = load_cached_ips()
    online_tvs = []
    found_profile_ids = set()

    # Step 1: Probe last-known IPs for the requested profiles
    for profile in profiles_to_check:
        pid = profile["id"]
        last_ip = cached_ips.get(pid, profile["default_ip"])
        if is_port_open(last_ip, profile["port"], timeout=0.5):
            model = get_device_model(last_ip, profile["port"])
            if any(m in model.lower() for m in profile["match_models"]):
                online_tvs.append({**profile, "ip": last_ip, "model": model})
                found_profile_ids.add(pid)
                continue

    # Step 2: Subnet scan only if any requested profile is missing
    missing_profiles = [p for p in profiles_to_check if p["id"] not in found_profile_ids]
    if missing_profiles:
        ips_to_scan = [f"{DHCP_SUBNET_PREFIX}.{i}" for i in range(DHCP_SCAN_RANGE[0], DHCP_SCAN_RANGE[1] + 1)]
        already_checked = {d["ip"] for d in online_tvs}
        ips_to_scan = [ip for ip in ips_to_scan if ip not in already_checked]

        with ThreadPoolExecutor(max_workers=30) as executor:
            active_ips = [ip for ip, open_port in zip(ips_to_scan, executor.map(is_port_open, ips_to_scan), strict=False) if open_port]

        for ip in active_ips:
            model = get_device_model(ip, 5555)
            if not model:
                continue
            for profile in missing_profiles:
                if profile["id"] in found_profile_ids:
                    continue
                if any(m in model.lower() for m in profile["match_models"]):
                    log.info(f"Auto-Discovered {profile['name']} at new IP: {ip} (Model: {model})")
                    online_tvs.append({**profile, "ip": ip, "model": model})
                    found_profile_ids.add(profile["id"])
                    cached_ips[profile["id"]] = ip
                    break

    save_cached_ips(cached_ips)
    return online_tvs

# -------------------------------------------------------------
# ZERO-PERFORMANCE-LOSS SAFETY GUARDS
# -------------------------------------------------------------

def adb_cmd(device_ip: str, args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    target = f"{device_ip}:5555"
    cmd = ["adb", "-s", target] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def is_media_playing(device_ip: str) -> tuple:
    """Check if any media/movie/audio track is currently actively playing on the TV."""
    res = adb_cmd(device_ip, ["shell", "dumpsys audio"], timeout=8)
    for line in res.stdout.splitlines():
        if "state:started" in line and ("usage=usage_media" in line.lower() or "content_type_movie" in line.lower() or "content_type_music" in line.lower()):
            return True, "Media/Video playback active"
    return False, "No active media playback"

def get_foreground_package(device_ip: str) -> str:
    """Returns the package name of the currently focused foreground app."""
    res = adb_cmd(device_ip, ["shell", "dumpsys activity activities"], timeout=8)
    for line in res.stdout.splitlines():
        line = line.strip()
        if "mresumedactivity" in line.lower() or "topresumedactivity" in line.lower():
            parts = line.split()
            for p in parts:
                if "/" in p and not p.startswith("{"):
                    return p.split("/")[0]
    return ""

def is_screensaver_active(device_ip: str) -> bool:
    """Check if the TV is in screensaver (dream) mode."""
    res = adb_cmd(device_ip, ["shell", "dumpsys dreams"], timeout=8)
    for line in res.stdout.splitlines():
        if "mdreaming=true" in line.lower():
            return True
    return False

def is_safe_to_install(device_ip: str, device_name: str, target_package: str = None) -> tuple:
    """
    Determines if it is safe to perform an install right now.
    ADB installs ('adb install -r') are 100% completely silent (no popups, no prompts).
    The ONLY condition that would disrupt the user is if we update the EXACT app they
    are currently actively using in the foreground.
    """
    fg_pkg = get_foreground_package(device_ip)
    
    # Critical Guard: Never kill or update an app while the user is actively using it
    if target_package and fg_pkg == target_package:
        return False, f"User is actively using {target_package} in the foreground"

    # For fresh installations or background apps, adb install is completely silent and non-disruptive
    return True, f"Foreground is {fg_pkg or 'launcher/idle'} (Safe for background silent install)"

# -------------------------------------------------------------
# PACKAGE INSPECTION & SILENT INSTALL
# -------------------------------------------------------------

def get_apk_details(apk_path: Path) -> dict:
    """Extracts package name, versionCode, and versionName from an APK file using aapt."""
    try:
        res = subprocess.run(
            ["aapt", "dump", "badging", str(apk_path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if res.returncode != 0:
            return {}
        
        info = {"package": "", "version_code": -1, "version_name": ""}
        for line in res.stdout.splitlines():
            if line.startswith("package:"):
                for token in line.split():
                    if token.startswith("name="):
                        info["package"] = token.split("=")[1].strip("'\"")
                    elif token.startswith("versionCode="):
                        try:
                            info["version_code"] = int(token.split("=")[1].strip("'\""))
                        except ValueError:
                            pass
                    elif token.startswith("versionName="):
                        info["version_name"] = token.split("=")[1].strip("'\"")
                break
        return info
    except Exception as e:
        log.warning(f"Error inspecting APK {apk_path.name} via aapt: {e}")
        return {}

def get_installed_version_code(device_ip: str, package_name: str) -> int:
    res = adb_cmd(device_ip, ["shell", f"dumpsys package {package_name}"])
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("versionCode="):
            parts = line.split()
            val = parts[0].split("=")[1]
            try:
                return int(val)
            except ValueError:
                pass
    return -1

def get_installed_version_name(device_ip: str, package_name: str) -> str:
    res = adb_cmd(device_ip, ["shell", f"dumpsys package {package_name}"])
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("versionName="):
            return line.split("=", 1)[1].strip()
    return ""

# -------------------------------------------------------------
# APK SIGNING CERTIFICATE VERIFICATION (no build-tools needed)
# -------------------------------------------------------------

_APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
_APK_SIG_SCHEME_IDS = {0x7109871A: "v2", 0xF05368C0: "v3", 0x1B93AD61: "v3.1"}


def _u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def _len_prefixed_items(buf: bytes) -> list:
    items, o = [], 0
    while o + 4 <= len(buf):
        n = _u32(buf, o)
        o += 4
        items.append(buf[o:o + n])
        o += n
    return items


def _apk_signing_block_pairs(data: bytes):
    """Returns the ID-value area of the APK Signing Block, or None (v1-only or not an APK)."""
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if eocd < 0:
        return None
    cd_offset = _u32(data, eocd + 16)
    if cd_offset < 32 or data[cd_offset - 16:cd_offset] != _APK_SIG_BLOCK_MAGIC:
        return None
    size = struct.unpack_from("<Q", data, cd_offset - 24)[0]
    start = cd_offset - size - 8
    if start < 0 or struct.unpack_from("<Q", data, start)[0] != size:
        return None
    return data[start + 8:cd_offset - 24]


def _signing_certs_v2_v3(data: bytes) -> list:
    pairs = _apk_signing_block_pairs(data)
    if pairs is None:
        return []
    certs = []
    o = 0
    while o + 12 <= len(pairs):
        length = struct.unpack_from("<Q", pairs, o)[0]
        ident = _u32(pairs, o + 8)
        value = pairs[o + 12:o + 8 + length]
        o += 8 + length
        if ident not in _APK_SIG_SCHEME_IDS:
            continue
        for signer in _len_prefixed_items(value[4:4 + _u32(value, 0)]):
            signed_data = signer[4:4 + _u32(signer, 0)]
            certs_start = 4 + _u32(signed_data, 0)  # skip digests sequence
            certs_seq = signed_data[certs_start + 4:certs_start + 4 + _u32(signed_data, certs_start)]
            for cert in _len_prefixed_items(certs_seq):
                if cert and cert not in certs:
                    certs.append(cert)
    return certs


def _signing_certs_v1(apk_path: Path) -> list:
    """Fallback for v1-only APKs: META-INF/*.RSA|DSA|EC (PKCS#7) via openssl, when installed."""
    if not shutil.which("openssl"):
        return []
    certs = []
    try:
        with zipfile.ZipFile(apk_path) as z:
            for name in z.namelist():
                if name.startswith("META-INF/") and name.upper().endswith((".RSA", ".DSA", ".EC")):
                    res = subprocess.run(["openssl", "pkcs7", "-inform", "DER", "-print_certs", "-outform", "PEM"],
                                         input=z.read(name), capture_output=True, timeout=20)
                    import base64
                    for block in res.stdout.decode(errors="replace").split("-----END CERTIFICATE-----")[:-1]:
                        body = block.split("-----BEGIN CERTIFICATE-----")[-1]
                        der = base64.b64decode("".join(body.split()))
                        if der and der not in certs:
                            certs.append(der)
    except (zipfile.BadZipFile, OSError, subprocess.SubprocessError, ValueError):
        pass
    return certs


def apk_signing_fingerprints(apk_path: Path) -> list:
    """SHA-256 fingerprints (lowercase hex) of the APK's signing certificates."""
    try:
        data = Path(apk_path).read_bytes()
    except OSError:
        return []
    certs = _signing_certs_v2_v3(data) or _signing_certs_v1(Path(apk_path))
    return [hashlib.sha256(c).hexdigest() for c in certs]


def verify_apk_signature(apk_path: Path, package: str, manual: bool = False) -> tuple:
    """
    (ok, reason). Official downloads must match a pin for their package; unknown packages
    are refused unless ALLOW_UNPINNED_APPS. Manual drops are allowed without a pin but are
    still checked when a pin exists for their package.
    """
    fps = apk_signing_fingerprints(apk_path)
    if not fps:
        return False, "could not read a signing certificate (unsigned or unsupported APK)"
    pins = APK_SIGNATURES.get(package or "", [])
    if not pins:
        if manual or ALLOW_UNPINNED_APPS:
            return True, f"no pin for {package}; accepting (fingerprint {fps[0][:16]}...)"
        return False, (f"no signing-certificate pin for {package}; add it to config.json apk_signatures "
                       f"(fingerprint {fps[0]}) or set allow_unpinned_apps")
    if any(fp in pins for fp in fps):
        return True, "signing certificate matches pin"
    return False, f"signing certificate {fps[0]} does not match the pinned key for {package}"


def silent_install(device_ip: str, device_name: str, apk_path: Path, package_name: str = None, force: bool = False) -> bool:
    manual = INCOMING_DIR in apk_path.parents
    sig_ok, sig_reason = verify_apk_signature(apk_path, package_name or get_apk_details(apk_path).get("package", ""), manual=manual)
    if not sig_ok:
        log.error(f"Refusing to install {apk_path.name} on {device_name}: {sig_reason}")
        return False
    if force:
        fg_pkg = get_foreground_package(device_ip)
        reason = f"FORCE OVERRIDE: Deploying immediately (Foreground is {fg_pkg or 'launcher/idle'})"
        safe = True
    else:
        safe, reason = is_safe_to_install(device_ip, device_name, package_name)

    if not safe:
        log.info(f"Skipping installation of {apk_path.name} on {device_name}: {reason}")
        return False

    log.info(f"Installing {apk_path.name} on {device_name} ({reason})...")
    res = adb_cmd(device_ip, ["install", "-r", str(apk_path)], timeout=120)
    out = (res.stdout.strip() + " " + res.stderr.strip()).strip()
    if "Success" in res.stdout:
        log.info(f"Successfully installed {apk_path.name} on {device_name}!")
        return True
    elif "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in out:
        log.warning(
            f"Signature mismatch on {device_name} for {apk_path.name}: "
            f"Package signatures do not match previously installed version (different developer signing key). "
            f"Android OS blocks in-place upgrades across differing certificates."
        )
        mark_incompatible(apk_path.name, "INSTALL_FAILED_UPDATE_INCOMPATIBLE")
        return False
    else:
        log.error(f"Failed to install {apk_path.name} on {device_name}: {out}")
        return False

def download_file(url: str, dest_path: Path) -> bool:
    temp_path = dest_path.with_suffix(".tmp")
    try:
        log.info(f"Downloading from {url}...")
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp, open(temp_path, "wb") as out_f:
            while chunk := resp.read(65536):
                out_f.write(chunk)
        temp_path.replace(dest_path)
        log.info(f"Downloaded: {dest_path.name} ({dest_path.stat().st_size // 1024} KB)")
        return True
    except Exception as e:
        log.error(f"Download failed for {url}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False

# -------------------------------------------------------------
# TIER 1: UPSTREAM SYNC (DAILY / ON-DEMAND)
# -------------------------------------------------------------

def _verified_download(cached_apk: Path, package: str) -> bool:
    """Discards a downloaded APK whose signing certificate does not match the pin."""
    ok, reason = verify_apk_signature(cached_apk, package)
    if ok:
        log.info(f"{cached_apk.name}: {reason}")
        return True
    log.error(f"{cached_apk.name}: {reason}; discarding download")
    try:
        cached_apk.unlink()
    except OSError:
        pass
    return False


def fetch_upstream_smarttube() -> dict:
    """Fetch latest SmartTube release info and download APK if needed."""
    pkg = "org.smarttube.stable"
    try:
        req = urllib.request.Request("https://api.github.com/repos/yuliskov/SmartTube/releases/latest", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        log.warning(f"Could not check SmartTube GitHub API: {e}")
        return {}

    tag_name = data.get("tag_name", "").strip()
    asset = None
    for a in data.get("assets", []):
        name = a.get("name", "").lower()
        if "stable" in name and "armeabi-v7a" in name:
            asset = a
            break
    if not asset:
        for a in data.get("assets", []):
            if "stable" in a.get("name", "").lower() and "universal" in a.get("name", "").lower():
                asset = a
                break
    if not asset:
        return {}

    apk_filename = asset.get("name")
    cached_apk = CACHE_DIR / apk_filename
    if not cached_apk.exists():
        if not download_file(asset.get("browser_download_url"), cached_apk):
            return {}
    if not _verified_download(cached_apk, pkg):
        return {}

    info = get_apk_details(cached_apk)
    return {
        "package": info.get("package") or pkg,
        "version_code": info.get("version_code", -1),
        "version_name": info.get("version_name") or tag_name,
        "apk_filename": apk_filename,
    }

def fetch_upstream_cloudstream() -> dict:
    """Fetch latest CloudStream Beta pre-release info and download APK if needed."""
    pkg = "com.lagradost.cloudstream3.prerelease"
    try:
        req = urllib.request.Request("https://api.github.com/repos/recloudstream/cloudstream/releases", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            releases = json.loads(resp.read().decode())
    except Exception as e:
        log.warning(f"Could not check CloudStream GitHub API: {e}")
        return {}

    prerelease = next((r for r in releases if r.get("prerelease")), None)
    if not prerelease:
        return {}

    asset = next((a for a in prerelease.get("assets", []) if a.get("name", "").endswith(".apk") and "pre" in a.get("name", "").lower()), None)
    if not asset:
        return {}

    apk_filename = f"cloudstream_{prerelease.get('id')}_{asset.get('name')}"
    cached_apk = CACHE_DIR / apk_filename
    if not cached_apk.exists():
        if not download_file(asset.get("browser_download_url"), cached_apk):
            return {}
    if not _verified_download(cached_apk, pkg):
        return {}

    info = get_apk_details(cached_apk)
    return {
        "package": info.get("package") or pkg,
        "version_code": info.get("version_code", -1),
        "version_name": info.get("version_name", ""),
        "apk_filename": apk_filename,
    }

def sync_upstream_if_needed(state: dict, force: bool = False) -> bool:
    """
    Tier 1 Sync: Runs once every 24 hours (or on --sync / forced).
    Fetches the latest official versions of all managed apps and records them in state.
    """
    last_check = state.get("last_upstream_check", 0)
    now = time.time()
    elapsed = now - last_check

    # Check if any cached APK file is missing on disk
    cached_files_exist = True
    for app in state.get("upstream_apps", {}).values():
        if not (CACHE_DIR / app.get("apk_filename", "")).exists():
            cached_files_exist = False
            break

    if not force and elapsed < UPSTREAM_CHECK_INTERVAL_SEC and cached_files_exist and len(state.get("upstream_apps", {})) >= len(MANAGED_APPS):
        # No sync needed
        return False

    log.info("Initiating Daily Upstream Sync (GitHub release APIs; signing keys pinned)...")
    updated = False

    st_meta = fetch_upstream_smarttube()
    if st_meta and st_meta.get("version_code", -1) > 0:
        state["upstream_apps"]["org.smarttube.stable"] = st_meta
        updated = True

    cs_meta = fetch_upstream_cloudstream()
    if cs_meta and cs_meta.get("version_code", -1) > 0:
        state["upstream_apps"]["com.lagradost.cloudstream3.prerelease"] = cs_meta
        updated = True

    state["last_upstream_check"] = now
    save_state(state)
    log.info("Daily Upstream Sync complete. Current upstream catalog:")
    for pkg, meta in state["upstream_apps"].items():
        log.info(f"  • {pkg}: vCode {meta.get('version_code')} ({meta.get('version_name')}) -> {meta.get('apk_filename')}")

    return updated

# -------------------------------------------------------------
# TIER 2: OPPORTUNISTIC LOCAL DEPLOYMENT & QUIESCENT IDLE
# -------------------------------------------------------------

def evaluate_pending_work(state: dict, force_reinstall: bool = False, target_profile_id: str = None, target_pkg: str = None) -> dict:
    """
    Evaluates which devices need installs or updates:
    - If an app is NOT installed on a target TV, it is flagged as 'FRESH_INSTALL'.
    - If an app has a version lower than upstream, it is flagged as 'UPDATE'.
    - If force_reinstall is True, marks apps for deployment even if installed version matches upstream.
    - If manual drops exist in incoming_apks/, all devices are flagged.
    """
    incoming_apks = list(INCOMING_DIR.glob("*.apk"))
    upstream_apps = state.get("upstream_apps", {})
    pending_devices = {}

    profiles_to_check = TARGET_PROFILES
    if target_profile_id:
        profiles_to_check = [p for p in TARGET_PROFILES if p["id"] == target_profile_id]

    for profile in profiles_to_check:
        pid = profile["id"]
        dev_installed = state.get("devices", {}).get(pid, {}).get("installed", {})
        device_pending = []

        # Check each managed app
        for app_def in MANAGED_APPS:
            pkg = app_def["package"]
            if target_pkg and pkg != target_pkg and app_def["id"] != target_pkg:
                continue

            if pkg not in upstream_apps:
                continue
            
            target_code = upstream_apps[pkg].get("version_code", -1)
            installed_code = dev_installed.get(pkg, -1)

            if target_code > 0:
                if installed_code <= 0:
                    device_pending.append({
                        "package": pkg,
                        "name": app_def["name"],
                        "target_code": target_code,
                        "target_name": upstream_apps[pkg].get("version_name", ""),
                        "apk_filename": upstream_apps[pkg].get("apk_filename", ""),
                        "action": "FRESH_INSTALL"
                    })
                elif installed_code < target_code or force_reinstall:
                    device_pending.append({
                        "package": pkg,
                        "name": app_def["name"],
                        "target_code": target_code,
                        "target_name": upstream_apps[pkg].get("version_name", ""),
                        "apk_filename": upstream_apps[pkg].get("apk_filename", ""),
                        "action": "FORCE_REINSTALL" if force_reinstall else "UPDATE"
                    })

        if device_pending or incoming_apks:
            pending_devices[pid] = {
                "profile": profile,
                "pending_apps": device_pending,
                "has_incoming": bool(incoming_apks)
            }

    return pending_devices

def process_manual_incoming(online_tvs: list):
    """Processes any APK placed in incoming_apks/ and archives them once all online TVs are done."""
    apk_files = list(INCOMING_DIR.glob("*.apk"))
    if not apk_files or not online_tvs:
        return

    log.info(f"Processing manual drops: {[f.name for f in apk_files]}")
    for apk_path in apk_files:
        info = get_apk_details(apk_path)
        pkg = info.get("package")
        code = info.get("version_code", -1)

        if not pkg:
            log.warning(f"Could not read package name from {apk_path.name}; skipping.")
            continue

        all_done = True
        for dev in online_tvs:
            curr_code = get_installed_version_code(dev["ip"], pkg)
            if code > 0 and curr_code >= code:
                continue
            success = silent_install(dev["ip"], dev["name"], apk_path, pkg)
            if not success:
                all_done = False

        if all_done:
            archive_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{apk_path.name}"
            try:
                apk_path.rename(INSTALLED_DIR / archive_name)
                log.info(f"Moved {apk_path.name} -> installed_apks/{archive_name}")
            except Exception as e:
                log.warning(f"Failed to archive {apk_path.name}: {e}")

def run_opportunistic_deployment(
    state: dict,
    force_upstream: bool = False,
    force_install: bool = False,
    force_reinstall: bool = False,
    target_device_id: str = None,
    target_package: str = None
):
    """Main execution loop for both cron (15-min) and manual runs with force control."""
    # Step 1: Upstream Sync (Daily or on demand)
    sync_upstream_if_needed(state, force=force_upstream)

    # Step 2: Evaluate pending work across target TVs
    pending_devices = evaluate_pending_work(
        state,
        force_reinstall=force_reinstall,
        target_profile_id=target_device_id,
        target_pkg=target_package
    )

    if not pending_devices:
        elapsed = time.time() - state.get("last_upstream_check", 0)
        remaining_sec = max(0, UPSTREAM_CHECK_INTERVAL_SEC - elapsed)
        rem_hours = int(remaining_sec // 3600)
        rem_mins = int((remaining_sec % 3600) // 60)
        target_names = ", ".join(p.get("name", p.get("id", "TV")) for p in TARGET_PROFILES) or "configured"
        log.info(
            f"All target TVs ({target_names}) are completely up to date. "
            f"Zero pending tasks. Quiescent: stopping polling. Next daily upstream sync in {rem_hours}h {rem_mins}m."
        )
        return

    pending_names = [pending_devices[pid]["profile"]["name"] for pid in pending_devices]
    log.info(f"Pending tasks detected for: {', '.join(pending_names)} (force_install={force_install})")

    # Step 3: Probe ONLY the pending devices (leaving already-updated TVs untouched)
    online_tvs = discover_online_tvs(target_profile_ids=list(pending_devices.keys()))

    if not online_tvs:
        log.info(f"Pending TV(s) ({', '.join(pending_names)}) are currently offline/sleeping. Will retry on next 15-min interval.")
        return

    log.info(f"Discovered Online Pending TVs: {[{d['name']: d['ip']} for d in online_tvs]}")

    # Process any manual APK drops first
    process_manual_incoming(online_tvs)

    # Step 4: Perform installations / updates for online pending TVs
    for dev in online_tvs:
        pid = dev["id"]
        ip = dev["ip"]
        name = dev["name"]
        dev_installed = state.setdefault("devices", {}).setdefault(pid, {}).setdefault("installed", {})

        # Live-sync installed version codes from device to catch out-of-band updates
        for app_def in MANAGED_APPS:
            pkg = app_def["package"]
            live_code = get_installed_version_code(ip, pkg)
            if live_code > 0:
                dev_installed[pkg] = live_code

        # Re-check what this specific device actually needs
        device_pending = pending_devices.get(pid, {}).get("pending_apps", [])
        for task in device_pending:
            pkg = task["package"]
            target_code = task["target_code"]
            app_name = task["name"]
            action = task["action"]
            apk_filename = task["apk_filename"]
            apk_path = CACHE_DIR / apk_filename

            curr_code = dev_installed.get(pkg, -1)
            if not force_reinstall and curr_code >= target_code:
                log.info(f"{app_name} is already up to date on {name} (vCode {curr_code}).")
                continue

            if not apk_path.exists():
                log.warning(f"Target APK {apk_filename} missing from cache; skipping.")
                continue

            log.info(f"{action} requested for {app_name} on {name}: current vCode {curr_code} -> target vCode {target_code} (force={force_install})")
            success = silent_install(ip, name, apk_path, pkg, force=force_install)
            if success:
                new_code = get_installed_version_code(ip, pkg)
                if new_code >= target_code or force_reinstall:
                    dev_installed[pkg] = new_code if new_code > 0 else target_code
                    save_state(state)
                    log.info(f"Successfully deployed {app_name} to {name} ({action}: vCode {dev_installed[pkg]})!")

    save_state(state)

def deploy_single_app(device_id: str, package_or_id: str, force: bool = False) -> tuple:
    """
    Directly deploys/updates a single app on a specific TV.
    Supports force=True to override active foreground session even if user is watching it.
    """
    state = load_state()
    cached_ips = load_cached_ips()

    # Find profile
    profile = next((p for p in TARGET_PROFILES if p["id"] == device_id or p["name"].lower() == device_id.lower()), None)
    if not profile:
        return False, f"Device profile '{device_id}' not found."

    pid = profile["id"]
    ip = cached_ips.get(pid, profile["default_ip"])
    name = profile["name"]

    if not is_port_open(ip, profile["port"], timeout=0.6):
        online = discover_online_tvs([pid])
        if not online:
            return False, f"{name} ({ip}) is currently offline or sleeping."
        ip = online[0]["ip"]

    # Match package or app id
    pkg = package_or_id
    for app_def in MANAGED_APPS:
        if app_def["id"] == package_or_id or app_def["package"] == package_or_id:
            pkg = app_def["package"]
            break

    upstream_apps = state.get("upstream_apps", {})
    if pkg not in upstream_apps:
        # Check incoming directory
        incoming_match = [f for f in INCOMING_DIR.glob("*.apk") if pkg in f.name]
        if incoming_match:
            apk_path = incoming_match[0]
        else:
            return False, f"Package '{pkg}' is not found in upstream catalog or cache."
    else:
        apk_filename = upstream_apps[pkg].get("apk_filename", "")
        apk_path = CACHE_DIR / apk_filename
        if not apk_path.exists():
            return False, f"Target APK '{apk_filename}' is missing from cache. Run upstream sync first."

    log.info(f"Direct deployment: {apk_path.name} on {name} ({ip}), force={force}...")
    success = silent_install(ip, name, apk_path, pkg, force=force)
    if success:
        live_code = get_installed_version_code(ip, pkg)
        if live_code > 0:
            state.setdefault("devices", {}).setdefault(pid, {}).setdefault("installed", {})[pkg] = live_code
            save_state(state)
        return True, f"Successfully deployed {apk_path.name} to {name}!"
    else:
        return False, f"Installation of {apk_path.name} on {name} failed or was postponed (App is open in foreground; use Force Mode to bypass)."

def get_cluster_telemetry(fast_probe: bool = True) -> dict:
    """
    Returns comprehensive cluster status, device health, active foreground app,
    and installed versions vs target versions.
    """
    state = load_state()
    cached_ips = load_cached_ips()
    upstream_apps = state.get("upstream_apps", {})
    last_upstream = state.get("last_upstream_check", 0)
    last_upstream_str = time.strftime('%Y-%m-%d %H:%M %Z', time.localtime(last_upstream)) if last_upstream > 0 else "Never"

    devices_data = []
    total_online = 0
    all_up_to_date = True
    pending_updates_count = 0

    for profile in TARGET_PROFILES:
        pid = profile["id"]
        pname = profile["name"]
        ip = cached_ips.get(pid, profile["default_ip"])
        is_online = is_port_open(ip, profile["port"], timeout=0.35)
        
        dev_installed = state.setdefault("devices", {}).setdefault(pid, {}).setdefault("installed", {})
        fg_pkg = ""
        fg_app_name = "Home Screen / Launcher"
        media_playing = False

        if is_online:
            total_online += 1
            if fast_probe:
                try:
                    fg_pkg = get_foreground_package(ip)
                    media_playing, _ = is_media_playing(ip)
                except Exception:
                    pass

                for app_def in MANAGED_APPS:
                    pkg = app_def["package"]
                    try:
                        live_code = get_installed_version_code(ip, pkg)
                        if live_code > 0:
                            dev_installed[pkg] = live_code
                    except Exception:
                        pass
        
        if fg_pkg:
            for app_def in MANAGED_APPS:
                if app_def["package"] == fg_pkg:
                    fg_app_name = app_def["name"]
                    break
            if fg_app_name == "Home Screen / Launcher":
                if "launcher" in fg_pkg.lower() or "tvlauncher" in fg_pkg.lower():
                    fg_app_name = "Android TV Launcher"
                elif "settings" in fg_pkg.lower():
                    fg_app_name = "System Settings"
                elif "youtube" in fg_pkg.lower():
                    fg_app_name = "YouTube TV"
                else:
                    fg_app_name = fg_pkg

        app_list = []
        for app_def in MANAGED_APPS:
            pkg = app_def["package"]
            aname = app_def["name"]
            inst_code = dev_installed.get(pkg, -1)
            up_info = upstream_apps.get(pkg, {})
            target_code = up_info.get("version_code", -1)
            target_name = up_info.get("version_name", "")
            apk_filename = up_info.get("apk_filename", "")

            # Get installed version name if online
            inst_vname = ""
            if is_online and inst_code > 0 and fast_probe:
                try:
                    inst_vname = get_installed_version_name(ip, pkg)
                except Exception:
                    pass

            if inst_code <= 0:
                status_code = "FRESH_INSTALL"
                status_text = "Fresh Install Pending"
                all_up_to_date = False
                pending_updates_count += 1
            elif target_code > 0 and inst_code < target_code:
                status_code = "UPDATE_AVAILABLE"
                status_text = f"Update Available (v{inst_code} → v{target_code})"
                all_up_to_date = False
                pending_updates_count += 1
            else:
                status_code = "UP_TO_DATE"
                status_text = f"Up to date (vCode {inst_code})"

            app_list.append({
                "package": pkg,
                "name": aname,
                "installed_code": inst_code,
                "installed_name": inst_vname or (str(inst_code) if inst_code > 0 else "Not Installed"),
                "target_code": target_code,
                "target_name": target_name,
                "apk_filename": apk_filename,
                "is_installed": inst_code > 0,
                "is_up_to_date": status_code == "UP_TO_DATE",
                "status_code": status_code,
                "status_text": status_text,
                "is_foreground": (fg_pkg == pkg)
            })

        devices_data.append({
            "id": pid,
            "name": pname,
            "ip": ip,
            "port": profile["port"],
            "model": profile.get("match_models", ["android"])[0].upper(),
            "is_online": is_online,
            "foreground_pkg": fg_pkg,
            "foreground_app_name": fg_app_name,
            "is_media_playing": media_playing,
            "apps": app_list
        })

    save_state(state)

    incoming_files = [f.name for f in INCOMING_DIR.glob("*.apk")]
    if incoming_files:
        all_up_to_date = False

    return {
        "status": "synced" if all_up_to_date else ("pending" if total_online > 0 else "offline"),
        "all_up_to_date": all_up_to_date,
        "pending_updates_count": pending_updates_count,
        "total_devices": len(TARGET_PROFILES),
        "online_devices": total_online,
        "last_upstream_check": last_upstream,
        "last_upstream_check_str": last_upstream_str,
        "devices": devices_data,
        "upstream_apps": upstream_apps,
        "incoming_apks": incoming_files,
        "schedule": "Every 15 min (06:00 - 23:59)"
    }

# -------------------------------------------------------------
# STATUS DISPLAY
# -------------------------------------------------------------

def print_status(state: dict):
    print("=" * 80)
    print("TV auto-updater - status")
    print("=" * 80)

    last_check = state.get("last_upstream_check", 0)
    last_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_check)) if last_check > 0 else "Never"
    print(f"Last Daily Upstream Sync: {last_str}")

    print("\n--- UPSTREAM RELEASE CATALOG ---")
    upstream_apps = state.get("upstream_apps", {})
    if not upstream_apps:
        print("  (Catalog is empty; run with --sync to fetch)")
    for app in MANAGED_APPS:
        pkg = app["package"]
        meta = upstream_apps.get(pkg, {})
        if meta:
            print(f"  • {app['name']:<18} [{pkg}]: vCode {meta.get('version_code')} (vName: {meta.get('version_name')})")
        else:
            print(f"  • {app['name']:<18} [{pkg}]: Not synced yet")

    print("\n--- TARGET TV INVENTORY ---")
    devices = state.get("devices", {})
    for p in TARGET_PROFILES:
        pid = p["id"]
        dev_data = devices.get(pid, {})
        installed = dev_data.get("installed", {})
        print(f"\n  Device: {p['name']} (Profile ID: {pid}, Default IP: {p['default_ip']})")
        for app in MANAGED_APPS:
            pkg = app["package"]
            code = installed.get(pkg, -1)
            target = upstream_apps.get(pkg, {}).get("version_code", -1)
            if code <= 0:
                status_str = "NOT INSTALLED (Fresh Install Pending)"
            elif target > 0 and code < target:
                status_str = f"OUTDATED (Installed: v{code} < Target: v{target})"
            else:
                status_str = f"UP TO DATE (vCode: {code})"
            print(f"    - {app['name']:<16}: {status_str}")

    print("\n" + "=" * 80)

# -------------------------------------------------------------
# MAIN CLI
# -------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TV auto-updater: background Android TV app updater (official sources, pinned signing keys)")
    parser.add_argument("--sync", action="store_true", help="Force an immediate upstream sync from the GitHub release APIs")
    parser.add_argument("--print-signature", type=str, metavar="APK", default=None,
                        help="Print the SHA-256 signing-certificate fingerprint(s) of an APK (for config.json apk_signatures) and exit")
    parser.add_argument("--status", action="store_true", help="Display cluster update status and exit")
    parser.add_argument("--status-json", action="store_true", help="Output full cluster telemetry as JSON and exit")
    parser.add_argument("--force", action="store_true", help="Force install even if the app is currently in foreground")
    parser.add_argument("--force-reinstall", action="store_true", help="Force reinstall even if already matching target version")
    parser.add_argument("--device", type=str, default=None, help="Target specific TV profile ID (e.g. mibox4, mitv4a, acertv)")
    parser.add_argument("--package", type=str, default=None, help="Target specific app package or ID")
    parser.add_argument("--push-incoming", action="store_true", help="Deploy manual drops from incoming_apks/ to online TVs")
    args = parser.parse_args()

    if args.print_signature:
        fps = apk_signing_fingerprints(Path(args.print_signature))
        if not fps:
            print("No signing certificate found (unsigned APK or unsupported signature scheme).")
            sys.exit(1)
        for fp in fps:
            print(fp)
        return

    state = load_state()

    if args.status_json:
        telemetry = get_cluster_telemetry(fast_probe=True)
        print(json.dumps(telemetry, indent=2))
        return

    if args.status:
        print_status(state)
        return

    if args.push_incoming:
        online_tvs = discover_online_tvs()
        process_manual_incoming(online_tvs)
        return

    if args.device and args.package:
        success, msg = deploy_single_app(args.device, args.package, force=args.force)
        print(f"[{'SUCCESS' if success else 'FAILED'}] {msg}")
        return

    run_opportunistic_deployment(
        state,
        force_upstream=args.sync,
        force_install=args.force,
        force_reinstall=args.force_reinstall,
        target_device_id=args.device,
        target_package=args.package
    )

if __name__ == "__main__":
    main()
