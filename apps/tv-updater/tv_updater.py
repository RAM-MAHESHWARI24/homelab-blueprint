#!/usr/bin/env python3
"""
CleanYourTV - Automated Background App Updater for Android TVs
Runs on the home server and silently maintains sideloaded apps over ADB:
  - SmartTube (yuliskov/SmartTube stable releases)
  - CloudStream Beta (recloudstream/cloudstream pre-releases)
  - HD Streamz (official developer origin via https://hdstreamz.ru/get)
  - Manual Sideload Drop folder: any APK placed in 'incoming_apks/' is silently pushed

Two-Tier State-Machine Architecture:
  Tier 1: Daily Upstream Sync (Once every 24h, or on --sync)
    - Checks GitHub APIs and official HD Streamz endpoint.
    - Caches latest genuine APKs in 'cache/'.
    - Updates target versionCodes in 'state.json'.

  Tier 2: Opportunistic Local Deployment & Quiescent Idle (15-min cron)
    - If all 3 target TVs have all managed apps installed & up to date:
        STOPS POLLING. Exits immediately in <5ms with 0 network or TV traffic.
    - If any TV is missing an app or has an older version:
        Probes ONLY the pending TV(s) (leaving already-updated TVs untouched).
        Freshly installs missing apps or upgrades existing ones.
        Safety guards: never installs if video/audio is playing or app is foreground.
        Once all 3 TVs have all apps installed & updated, enters quiescent idle.
"""

import os
import re
import sys
import time
import json
import socket
import logging
import argparse
import subprocess
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Paths
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
CACHE_DIR = BASE_DIR / "cache"
INCOMING_DIR = BASE_DIR / "incoming_apks"
INSTALLED_DIR = BASE_DIR / "installed_apks"
LOG_FILE = BASE_DIR / "tv_updater.log"
STATE_FILE = BASE_DIR / "state.json"
DEVICES_CACHE_FILE = BASE_DIR / "devices_cache.json"
INCOMPATIBLE_CACHE_FILE = BASE_DIR / "incompatible_apks.json"

CACHE_DIR.mkdir(exist_ok=True)
INCOMING_DIR.mkdir(exist_ok=True)
INSTALLED_DIR.mkdir(exist_ok=True)

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
    {
        "id": "hdstreamz",
        "package": "topic.election.sector",
        "name": "HD Streamz",
    },
]

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
    except Exception as _e:
        pass

HEADERS = {"User-Agent": "CleanYourTV-AppUpdater/1.0"}
HDSTREAMZ_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HDSTREAMZ_PAGE_URLS = [
    "https://hdstreamz.ru/get",
    "https://hdstreamz.ru/",
    "https://hdstreamzin.com/",
    "https://hdstreamz2.com.co/download-apk-latest-version/",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

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
            logging.warning(f"Could not load state.json ({e}), using defaults.")
    return default_state

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save state.json: {e}")

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
            active_ips = [ip for ip, open_port in zip(ips_to_scan, executor.map(is_port_open, ips_to_scan)) if open_port]

        for ip in active_ips:
            model = get_device_model(ip, 5555)
            if not model:
                continue
            for profile in missing_profiles:
                if profile["id"] in found_profile_ids:
                    continue
                if any(m in model.lower() for m in profile["match_models"]):
                    logging.info(f"Auto-Discovered {profile['name']} at new IP: {ip} (Model: {model})")
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
        logging.warning(f"Error inspecting APK {apk_path.name} via aapt: {e}")
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

def silent_install(device_ip: str, device_name: str, apk_path: Path, package_name: str = None, force: bool = False) -> bool:
    if force:
        fg_pkg = get_foreground_package(device_ip)
        reason = f"FORCE OVERRIDE: Deploying immediately (Foreground is {fg_pkg or 'launcher/idle'})"
        safe = True
    else:
        safe, reason = is_safe_to_install(device_ip, device_name, package_name)

    if not safe:
        logging.info(f"Skipping installation of {apk_path.name} on {device_name}: {reason}")
        return False

    logging.info(f"Installing {apk_path.name} on {device_name} ({reason})...")
    res = adb_cmd(device_ip, ["install", "-r", str(apk_path)], timeout=120)
    out = (res.stdout.strip() + " " + res.stderr.strip()).strip()
    if "Success" in res.stdout:
        logging.info(f"Successfully installed {apk_path.name} on {device_name}!")
        return True
    elif "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in out:
        logging.warning(
            f"Signature mismatch on {device_name} for {apk_path.name}: "
            f"Package signatures do not match previously installed version (different developer signing key). "
            f"Android OS blocks in-place upgrades across differing certificates."
        )
        mark_incompatible(apk_path.name, "INSTALL_FAILED_UPDATE_INCOMPATIBLE")
        return False
    else:
        logging.error(f"Failed to install {apk_path.name} on {device_name}: {out}")
        return False

def download_file(url: str, dest_path: Path) -> bool:
    temp_path = dest_path.with_suffix(".tmp")
    try:
        logging.info(f"Downloading from {url}...")
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp, open(temp_path, "wb") as out_f:
            while chunk := resp.read(65536):
                out_f.write(chunk)
        temp_path.replace(dest_path)
        logging.info(f"Downloaded: {dest_path.name} ({dest_path.stat().st_size // 1024} KB)")
        return True
    except Exception as e:
        logging.error(f"Download failed for {url}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False

# -------------------------------------------------------------
# TIER 1: UPSTREAM SYNC (DAILY / ON-DEMAND)
# -------------------------------------------------------------

def fetch_upstream_smarttube() -> dict:
    """Fetch latest SmartTube release info and download APK if needed."""
    pkg = "org.smarttube.stable"
    try:
        req = urllib.request.Request("https://api.github.com/repos/yuliskov/SmartTube/releases/latest", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logging.warning(f"Could not check SmartTube GitHub API: {e}")
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
        logging.warning(f"Could not check CloudStream GitHub API: {e}")
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

    info = get_apk_details(cached_apk)
    return {
        "package": info.get("package") or pkg,
        "version_code": info.get("version_code", -1),
        "version_name": info.get("version_name", ""),
        "apk_filename": apk_filename,
    }

def fetch_upstream_hdstreamz() -> dict:
    """Scrape official HD Streamz websites and mirrors for genuine APK."""
    pkg = "topic.election.sector"
    found_apk_urls = set()
    for page_url in HDSTREAMZ_PAGE_URLS:
        try:
            req = urllib.request.Request(page_url, headers={"User-Agent": HDSTREAMZ_USER_AGENT})
            with urllib.request.urlopen(req, timeout=12) as resp:
                final_url = resp.geturl()
                if ".apk" in final_url:
                    found_apk_urls.add(final_url)
                else:
                    html = resp.read().decode("utf-8", errors="ignore")
                    links = re.findall(r'https?://[^\s"\'<>#]+\.apk', html)
                    for link in links:
                        found_apk_urls.add(link)
        except Exception as e:
            logging.warning(f"Could not check HD Streamz site ({page_url}): {e}")

    if not found_apk_urls:
        return {}

    incompatible_list = load_incompatible_cache()
    valid_candidates = []

    for apk_url in sorted(found_apk_urls, reverse=True):
        apk_filename = apk_url.rstrip("/").split("/")[-1]
        if not apk_filename.endswith(".apk"):
            apk_filename = f"hdstreamz_{int(time.time())}.apk"

        if apk_filename in incompatible_list:
            continue

        cached_apk = CACHE_DIR / apk_filename
        if not cached_apk.exists():
            if not download_file(apk_url, cached_apk):
                continue

        apk_info = get_apk_details(cached_apk)
        if apk_info.get("version_code", -1) > 0:
            valid_candidates.append((apk_info["version_code"], apk_filename, apk_info))

    if not valid_candidates:
        return {}

    valid_candidates.sort(key=lambda c: c[0], reverse=True)
    best_code, best_file, best_info = valid_candidates[0]

    return {
        "package": best_info.get("package") or pkg,
        "version_code": best_code,
        "version_name": best_info.get("version_name", ""),
        "apk_filename": best_file,
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

    if not force and elapsed < UPSTREAM_CHECK_INTERVAL_SEC and cached_files_exist and len(state.get("upstream_apps", {})) >= 3:
        # No sync needed
        return False

    logging.info("Initiating Daily Upstream Sync (Checking GitHub & Official Release Endpoints)...")
    updated = False

    st_meta = fetch_upstream_smarttube()
    if st_meta and st_meta.get("version_code", -1) > 0:
        state["upstream_apps"]["org.smarttube.stable"] = st_meta
        updated = True

    cs_meta = fetch_upstream_cloudstream()
    if cs_meta and cs_meta.get("version_code", -1) > 0:
        state["upstream_apps"]["com.lagradost.cloudstream3.prerelease"] = cs_meta
        updated = True

    hds_meta = fetch_upstream_hdstreamz()
    if hds_meta and hds_meta.get("version_code", -1) > 0:
        state["upstream_apps"]["topic.election.sector"] = hds_meta
        updated = True

    state["last_upstream_check"] = now
    save_state(state)
    logging.info("Daily Upstream Sync complete. Current upstream catalog:")
    for pkg, meta in state["upstream_apps"].items():
        logging.info(f"  • {pkg}: vCode {meta.get('version_code')} ({meta.get('version_name')}) -> {meta.get('apk_filename')}")

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

    logging.info(f"Processing manual drops: {[f.name for f in apk_files]}")
    for apk_path in apk_files:
        info = get_apk_details(apk_path)
        pkg = info.get("package")
        code = info.get("version_code", -1)
        name = info.get("version_name", "")

        if not pkg:
            logging.warning(f"Could not read package name from {apk_path.name}; skipping.")
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
                logging.info(f"Moved {apk_path.name} -> installed_apks/{archive_name}")
            except Exception as e:
                logging.warning(f"Failed to archive {apk_path.name}: {e}")

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
        logging.info(
            f"All target TVs (Mi Box 4, Mi TV 4A, Acer TV) are completely up to date. "
            f"Zero pending tasks. Quiescent: stopping polling. Next daily upstream sync in {rem_hours}h {rem_mins}m."
        )
        return

    pending_names = [pending_devices[pid]["profile"]["name"] for pid in pending_devices]
    logging.info(f"Pending tasks detected for: {', '.join(pending_names)} (force_install={force_install})")

    # Step 3: Probe ONLY the pending devices (leaving already-updated TVs untouched)
    online_tvs = discover_online_tvs(target_profile_ids=list(pending_devices.keys()))

    if not online_tvs:
        logging.info(f"Pending TV(s) ({', '.join(pending_names)}) are currently offline/sleeping. Will retry on next 15-min interval.")
        return

    logging.info(f"Discovered Online Pending TVs: {[{d['name']: d['ip']} for d in online_tvs]}")

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
                logging.info(f"{app_name} is already up to date on {name} (vCode {curr_code}).")
                continue

            if not apk_path.exists():
                logging.warning(f"Target APK {apk_filename} missing from cache; skipping.")
                continue

            logging.info(f"{action} requested for {app_name} on {name}: current vCode {curr_code} -> target vCode {target_code} (force={force_install})")
            success = silent_install(ip, name, apk_path, pkg, force=force_install)
            if success:
                new_code = get_installed_version_code(ip, pkg)
                if new_code >= target_code or force_reinstall:
                    dev_installed[pkg] = new_code if new_code > 0 else target_code
                    save_state(state)
                    logging.info(f"Successfully deployed {app_name} to {name} ({action}: vCode {dev_installed[pkg]})!")

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

    logging.info(f"Direct deployment: {apk_path.name} on {name} ({ip}), force={force}...")
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
    last_upstream_str = time.strftime('%Y-%m-%d %I:%M %p IST', time.localtime(last_upstream)) if last_upstream > 0 else "Never"

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
        "schedule": "Every 15 min (06:00 - 23:59 IST)"
    }

# -------------------------------------------------------------
# STATUS DISPLAY
# -------------------------------------------------------------

def print_status(state: dict):
    print("=" * 80)
    print("CleanYourTV - Automated Sideload Updater Status")
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
    parser = argparse.ArgumentParser(description="CleanYourTV Background TV App Updater")
    parser.add_argument("--sync", action="store_true", help="Force immediate daily upstream sync from GitHub & websites")
    parser.add_argument("--status", action="store_true", help="Display cluster update status and exit")
    parser.add_argument("--status-json", action="store_true", help="Output full cluster telemetry as JSON and exit")
    parser.add_argument("--force", action="store_true", help="Force install even if the app is currently in foreground")
    parser.add_argument("--force-reinstall", action="store_true", help="Force reinstall even if already matching target version")
    parser.add_argument("--device", type=str, default=None, help="Target specific TV profile ID (e.g. mibox4, mitv4a, acertv)")
    parser.add_argument("--package", type=str, default=None, help="Target specific app package or ID")
    parser.add_argument("--push-incoming", action="store_true", help="Deploy manual drops from incoming_apks/ to online TVs")
    args = parser.parse_args()

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
