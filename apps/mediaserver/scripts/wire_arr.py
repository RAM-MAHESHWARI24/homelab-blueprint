#!/usr/bin/env python3
"""
Connect the media pipeline apps to each other so a fresh install is usable
without touching any web UI. Standard library only; idempotent (safe to re-run).

    # before first `docker compose up`: write qBittorrent's config with the chosen password
    python3 scripts/wire_arr.py seed --config-dir /srv/homelab/appdata/mediaserver \
        --qbit-user admin --qbit-pass '<password>'

    # after the containers are healthy: wire everything together
    python3 scripts/wire_arr.py wire --config-dir /srv/homelab/appdata/mediaserver \
        --qbit-user admin --qbit-pass '<password>' --admin-pass '<jellyfin/seerr admin password>' \
        [--host 127.0.0.1] [--byparr] [--skip-seerr] [--json]

    # release profiles from apps/mediaserver/profiles/ (see the release profiles guide)
    python3 scripts/wire_arr.py profiles apply   --config-dir ... [--env-file .env] [--language Hindi]
    python3 scripts/wire_arr.py profiles check   --config-dir ... --json     # exit 1 when out of sync
    python3 scripts/wire_arr.py profiles migrate --config-dir ... --dry-run  # one-off cleanup of older setups

    # register Radarr/Sonarr in Seerr with the default profile (after `profiles apply`)
    python3 scripts/wire_arr.py seerr --config-dir ... --admin-pass '<password>' --profile "1080p Compact"

What `wire` does:
  * reads each app's API key from <config-dir>/<app>/config.xml (generated on first start)
  * qBittorrent: categories radarr/tv-sonarr with save paths under /data/torrents
  * Radarr/Sonarr: root folders /data/media/{movies,tv}; qBittorrent as download client
  * Prowlarr: Radarr and Sonarr as applications (Full Sync, also enforced on existing links);
    Byparr as indexer proxy (optional)
  * Jellyfin: completes the startup wizard, creates the admin user, adds Movies and Shows libraries
  * Seerr: initialises against Jellyfin and registers Radarr/Sonarr (best effort)

Exit code 0 when every required step succeeded, 1 otherwise. --json prints a
machine-readable report (used by the blueprint installer).
"""

import argparse
import base64
import hashlib
from http.cookiejar import CookieJar
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_pack as pp  # noqa: E402  (same folder; standard library only)

PORTS = {"radarr": 7878, "sonarr": 8989, "prowlarr": 9696, "qbittorrent": 8080, "jellyfin": 8096, "seerr": 5055}
# Container-to-container addresses (compose default network, service names)
INTERNAL = {
    "radarr": "http://radarr:7878",
    "sonarr": "http://sonarr:8989",
    "prowlarr": "http://prowlarr:9696",
    "qbittorrent": "qbittorrent",
    "jellyfin": "jellyfin",
    "byparr": "http://byparr:8191",
}

report: Dict[str, Any] = {"steps": [], "errors": [], "warnings": []}


def step(name: str, ok: bool, detail: str = "", required: bool = True) -> bool:
    report["steps"].append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        (report["errors"] if required else report["warnings"]).append(f"{name}: {detail}")
    tag = "ok" if ok else ("FAIL" if required else "warn")
    print(f"[{tag}] {name}{(' - ' + detail) if detail else ''}", flush=True)
    return ok


# --------------------------------------------------------------------------- http
def http(url: str, method: str = "GET", data: Any = None, headers: Optional[Dict[str, str]] = None, timeout: int = 20) -> Tuple[int, str, Dict[str, str]]:
    body = json.dumps(data).encode() if data is not None else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), dict(e.headers)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 0, str(e), {}


def wait_http(url: str, headers=None, retries: int = 60, delay: float = 3.0, accept=(200, 401, 403)) -> bool:
    for _ in range(retries):
        status, _, _ = http(url, headers=headers, timeout=5)
        if status in accept:
            return True
        time.sleep(delay)
    return False


def jloads(text: str, default):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


# ----------------------------------------------------------------------- qbittorrent
def qbit_pbkdf2(password: str) -> str:
    """qBittorrent 4.2+ WebUI password format: @ByteArray(base64(salt):base64(pbkdf2-sha512))"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, 100_000, dklen=64)
    return f"@ByteArray({base64.b64encode(salt).decode()}:{base64.b64encode(digest).decode()})"


def seed_qbittorrent(config_dir: Path, user: str, password: str, puid: int, pgid: int) -> bool:
    """
    Writes qBittorrent.conf before first start so the WebUI has the chosen
    password and the save path points at /data/torrents. Existing configs are
    left alone.
    """
    conf_dir = config_dir / "qbittorrent" / "qBittorrent"
    conf = conf_dir / "qBittorrent.conf"
    if conf.exists():
        return step("qBittorrent config", True, "already exists, left unchanged")
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf.write_text(
        "[LegalNotice]\nAccepted=true\n\n"
        "[BitTorrent]\nSession\\DefaultSavePath=/data/torrents\nSession\\TempPathEnabled=false\n"
        "Session\\Port=6881\nSession\\QueueingSystemEnabled=true\n\n"
        "[Preferences]\n"
        "Downloads\\SavePath=/data/torrents/\n"
        "WebUI\\Address=*\n"
        "WebUI\\Port=8080\n"
        "WebUI\\CSRFProtection=true\n"
        "WebUI\\ServerDomains=*\n"
        f"WebUI\\Username={user}\n"
        f"WebUI\\Password_PBKDF2=\"{qbit_pbkdf2(password)}\"\n",
        encoding="utf-8",
    )
    if hasattr(os, "chown") and os.name != "nt":
        try:
            for p in (config_dir / "qbittorrent", conf_dir, conf):
                os.chown(p, puid, pgid)
        except PermissionError:
            pass
    return step("qBittorrent config", True, f"seeded {conf}")


class QBit:
    def __init__(self, host: str, user: str, password: str):
        self.base = f"http://{host}:{PORTS['qbittorrent']}"
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.user, self.password = user, password

    def _form(self, path: str, fields: Dict[str, str]) -> Tuple[int, str]:
        body = urllib.parse.urlencode(fields).encode()
        # No Referer/Origin header: qBittorrent treats a missing one as a non-browser client
        # (same as Radarr/Sonarr), while a present one must match the Host header exactly.
        req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except (urllib.error.URLError, OSError) as e:
            return 0, str(e)

    def _get(self, path: str) -> Tuple[int, str]:
        req = urllib.request.Request(self.base + path)
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except (urllib.error.URLError, OSError) as e:
            return 0, str(e)

    def login(self, attempts: int = 4) -> Tuple[bool, str]:
        """
        Returns (ok, detail). qBittorrent 4.x answers a successful login with 200 'Ok.',
        5.x with 204 and a QBT_SID session cookie; a 204 without a cookie means the
        client needs no authentication (LocalHostAuth off or a whitelisted subnet). Every
        case is confirmed with an authenticated call, and the detail carries status and
        body so a failure is diagnosable from the install log.
        """
        st, body = 0, ""
        for i in range(attempts):
            st, body = self._form("/api/v2/auth/login", {"username": self.user, "password": self.password})
            if (st == 200 and "Ok" in body) or st == 204:
                vst, version = self._get("/api/v2/app/version")
                if vst == 200:
                    has_session = any(c.name.startswith("QBT_SID") for c in self.jar)
                    how = f"password accepted (HTTP {st})" if (st == 200 or has_session) else "no auth required for this client"
                    return True, f"{how}, qBittorrent {version.strip()}"
                return False, f"login HTTP {st} but app/version HTTP {vst} {version.strip()[:120]!r}"
            if i + 1 < attempts:
                time.sleep(3)
        return False, f"HTTP {st} {body.strip()[:160]!r} (user={self.user})"

    # The categories Radarr and Sonarr use by default; the download clients are wired to these.
    CATEGORIES = (("radarr", "/data/torrents/movies"), ("tv-sonarr", "/data/torrents/tv"))

    def categories(self) -> Dict[str, Any]:
        st, body = self._get("/api/v2/torrents/categories")
        data = jloads(body, {}) if st == 200 else {}
        return data if isinstance(data, dict) else {}

    def ensure_categories(self, wanted=None) -> bool:
        """Creates missing categories. Existing ones (and an older movies/tv pair) are left alone."""
        existing = self.categories()
        ok = True
        for name, path in (wanted or self.CATEGORIES):
            if name in existing:
                continue
            st, _ = self._form("/api/v2/torrents/createCategory", {"category": name, "savePath": path})
            ok = ok and st in (200, 409)
        return ok

    def preferences(self) -> Dict[str, Any]:
        st, body = self._get("/api/v2/app/preferences")
        data = jloads(body, None) if st == 200 else None
        return data if isinstance(data, dict) else {}

    def set_preferences(self, prefs: Dict[str, Any]) -> Tuple[bool, str]:
        st, body = self._form("/api/v2/app/setPreferences", {"json": json.dumps(prefs)})
        return st == 200, ("" if st == 200 else f"setPreferences HTTP {st}: {body[:120]}")

    DEFAULT_EXCLUDED_PATTERNS = ("*.exe", "*.bat", "*.cmd", "*.scr", "*.lnk", "*.pif", "*.com", "*.vbs")

    def ensure_excluded_files(self) -> Tuple[bool, str]:
        """Set default non-media payload exclusions when qBittorrent has none configured yet."""
        st, body = self._get("/api/v2/app/preferences")
        if st != 200:
            return False, f"GET preferences -> HTTP {st}"
        prefs = jloads(body, {})
        existing = str(prefs.get("excluded_file_names") or "").strip()
        if existing:
            return True, "already configured"
        payload = json.dumps({"excluded_file_names_enabled": True, "excluded_file_names": "\n".join(self.DEFAULT_EXCLUDED_PATTERNS)})
        pst, pbody = self._form("/api/v2/app/setPreferences", {"json": payload})
        return pst == 200, ("configured" if pst == 200 else f"setPreferences HTTP {pst}: {pbody[:120]}")


# ------------------------------------------------------------------------ *arr apps
def read_api_key(config_dir: Path, app: str, retries: int = 40) -> str:
    xml_path = config_dir / app / "config.xml"
    for _ in range(retries):
        if xml_path.exists():
            try:
                key = ET.parse(xml_path).getroot().findtext("ApiKey")
                if key:
                    return key.strip()
            except ET.ParseError:
                pass
        time.sleep(3)
    return ""


class Arr:
    def __init__(self, name: str, host: str, api_key: str, api_version: str):
        self.name = name
        self.base = f"http://{host}:{PORTS[name]}/api/{api_version}"
        self.headers = {"X-Api-Key": api_key}

    def get(self, path: str):
        st, body, _ = http(f"{self.base}/{path}", headers=self.headers)
        return st, jloads(body, None)

    def post(self, path: str, data):
        st, body, _ = http(f"{self.base}/{path}", method="POST", data=data, headers=self.headers, timeout=60)
        return st, jloads(body, body)

    def put(self, path: str, data):
        st, body, _ = http(f"{self.base}/{path}", method="PUT", data=data, headers=self.headers, timeout=60)
        return st, jloads(body, body)

    def delete(self, path: str):
        st, body, _ = http(f"{self.base}/{path}", method="DELETE", headers=self.headers, timeout=60)
        return st, jloads(body, body)

    def ensure(self, collection: str, match_key: str, match_value, build) -> Tuple[bool, str]:
        """Creates a resource from its schema unless one with match_key==match_value exists."""
        st, existing = self.get(collection)
        if st != 200 or not isinstance(existing, list):
            return False, f"GET {collection} -> {st}"
        if any(item.get(match_key) == match_value for item in existing):
            return True, "already configured"
        st, schemas = self.get(f"{collection}/schema")
        if st != 200 or not isinstance(schemas, list):
            return False, f"GET {collection}/schema -> {st}"
        payload = build(schemas)
        if payload is None:
            return False, "no matching implementation in schema"
        st, resp = self.post(collection, payload)
        if st in (200, 201):
            return True, "created"
        return False, f"POST {collection} -> {st}: {str(resp)[:200]}"

    def ensure_root_folder(self, path: str) -> Tuple[bool, str]:
        st, existing = self.get("rootfolder")
        if st != 200 or not isinstance(existing, list):
            return False, f"GET rootfolder -> {st}"
        if any(r.get("path") == path for r in existing):
            return True, "already configured"
        st, resp = self.post("rootfolder", {"path": path})
        return st in (200, 201), ("created" if st in (200, 201) else f"{st}: {str(resp)[:200]}")


def set_fields(schema: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    for f in schema.get("fields", []):
        if f.get("name") in values:
            f["value"] = values[f["name"]]
    return schema


def pick(schemas: List[Dict[str, Any]], implementation: str) -> Optional[Dict[str, Any]]:
    return next((dict(s) for s in schemas if s.get("implementation") == implementation), None)


def wire_arr(app: Arr, root_folder: str, category_key: str, category: str, qbit_user: str, qbit_pass: str) -> None:
    ok, detail = app.ensure_root_folder(root_folder)
    step(f"{app.name}: root folder {root_folder}", ok, detail)

    def build(schemas):
        schema = pick(schemas, "QBittorrent")
        if not schema:
            return None
        schema.update({"name": "qBittorrent", "enable": True, "priority": 1, "removeCompletedDownloads": True, "removeFailedDownloads": True})
        return set_fields(schema, {"host": INTERNAL["qbittorrent"], "port": 8080, "useSsl": False, "username": qbit_user, "password": qbit_pass, category_key: category})

    ok, detail = app.ensure("downloadclient", "name", "qBittorrent", build)
    step(f"{app.name}: qBittorrent download client", ok, detail)
    # Uploaders with mangled names (Ozlem) are blocked by the profile pack's
    # "Junk · Banned uploaders" format: Radarr 7 and Sonarr 4 removed /restriction.


DEFAULT_DEPRIORITIZED_INDEXERS = {"the pirate bay": 45}


def ensure_prowlarr_full_sync(prowlarr: Arr, dry_run: bool = False) -> List[str]:
    """Moves Prowlarr's app links to Full Sync so indexer priorities and minimum seeders
    reach Radarr and Sonarr ("Add and Remove Only" stops at adding). Returns what changed."""
    st, apps = prowlarr.get("applications")
    if st != 200 or not isinstance(apps, list):
        return [f"GET applications -> HTTP {st}"]
    changed = []
    for item in apps:
        if item.get("syncLevel") == "fullSync" or not item.get("id"):
            continue
        changed.append(f"{item.get('name')}: sync level {item.get('syncLevel')} -> fullSync")
        if dry_run:
            continue
        updated = dict(item)
        updated["syncLevel"] = "fullSync"
        pst, _ = prowlarr.put(f"applications/{item['id']}", updated)
        step(f"Prowlarr: {item.get('name')} sync level Full Sync", pst in (200, 202), f"HTTP {pst}", required=False)
    return changed


def deprioritize_unmoderated_indexers(prowlarr: Arr) -> None:
    """Lower priority of unmoderated public trackers (from default 25 -> 45) when cleaner indexers exist."""
    st, indexers = prowlarr.get("indexer")
    if st != 200 or not isinstance(indexers, list):
        return
    enabled = [i for i in indexers if i.get("enable")]
    if len(enabled) < 2:
        return
    for ix in enabled:
        name = str(ix.get("name") or "")
        target = DEFAULT_DEPRIORITIZED_INDEXERS.get(name.lower())
        if target and ix.get("priority") == 25 and ix.get("id"):
            updated = dict(ix)
            updated["priority"] = target
            pst, _ = prowlarr.put(f"indexer/{ix['id']}", updated)
            step(f"Prowlarr: deprioritize {name} (priority {target})", pst in (200, 202), f"HTTP {pst}", required=False)


def wire_prowlarr(prowlarr: Arr, radarr_key: str, sonarr_key: str, byparr: bool) -> None:
    targets = (
        ("Radarr", INTERNAL["radarr"], radarr_key, [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060, 2070, 2080]),
        ("Sonarr", INTERNAL["sonarr"], sonarr_key, [5000, 5010, 5020, 5030, 5040, 5045, 5050, 5090]),
    )
    for name, base_url, api_key, cats in targets:
        def build(schemas, name=name, base_url=base_url, api_key=api_key, cats=cats):
            schema = pick(schemas, name)
            if not schema:
                return None
            schema.update({"name": name, "syncLevel": "fullSync", "appProfileId": 1})
            return set_fields(schema, {"prowlarrUrl": INTERNAL["prowlarr"], "baseUrl": base_url, "apiKey": api_key, "syncCategories": cats})

        ok, detail = prowlarr.ensure("applications", "name", name, build)
        step(f"Prowlarr: application {name}", ok, detail)
    ensure_prowlarr_full_sync(prowlarr)

    if byparr:
        def build_proxy(schemas):
            schema = pick(schemas, "FlareSolverr")
            if not schema:
                return None
            schema.update({"name": "Byparr", "tags": []})
            return set_fields(schema, {"host": INTERNAL["byparr"], "requestTimeout": 60})

        ok, detail = prowlarr.ensure("indexerProxy", "name", "Byparr", build_proxy)
        step("Prowlarr: Byparr (FlareSolverr-compatible) proxy", ok, detail, required=False)

    st, _ = prowlarr.post("command", {"name": "ApplicationIndexerSync"})
    step("Prowlarr: application sync triggered", st in (200, 201), f"HTTP {st}", required=False)
    deprioritize_unmoderated_indexers(prowlarr)


# -------------------------------------------------------------------------- jellyfin
class Jellyfin:
    def __init__(self, host: str):
        self.base = f"http://{host}:{PORTS['jellyfin']}"
        self.auth_header = 'MediaBrowser Client="homelab-blueprint", Device="installer", DeviceId="homelab-blueprint-installer", Version="2.0.0"'
        self.token = ""

    def _h(self):
        return {"Authorization": self.auth_header + (f', Token="{self.token}"' if self.token else "")}

    def complete_startup(self, admin_user: str, admin_pass: str) -> bool:
        st, body, _ = http(f"{self.base}/System/Info/Public")
        info = jloads(body, {})
        if st != 200:
            return step("Jellyfin: reachable", False, f"HTTP {st}")
        if info.get("StartupWizardCompleted"):
            return step("Jellyfin: startup wizard", True, "already completed")

        http(f"{self.base}/Startup/Configuration", "POST", {"UICulture": "en-US", "MetadataCountryCode": "US", "PreferredMetadataLanguage": "en"}, headers=self._h())
        http(f"{self.base}/Startup/User", "GET", headers=self._h())
        st, body, _ = http(f"{self.base}/Startup/User", "POST", {"Name": admin_user, "Password": admin_pass}, headers=self._h())
        if st not in (200, 204):
            return step("Jellyfin: create admin user", False, f"HTTP {st}: {body[:160]}")
        http(f"{self.base}/Startup/RemoteAccess", "POST", {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False}, headers=self._h())
        st, body, _ = http(f"{self.base}/Startup/Complete", "POST", headers=self._h())
        return step("Jellyfin: startup wizard", st in (200, 204), f"HTTP {st}")

    def login(self, user: str, password: str) -> bool:
        st, body, _ = http(f"{self.base}/Users/AuthenticateByName", "POST", {"Username": user, "Pw": password}, headers=self._h())
        data = jloads(body, {})
        self.token = data.get("AccessToken", "") if st == 200 else ""
        return step("Jellyfin: admin login", bool(self.token), f"HTTP {st}")

    def ensure_library(self, name: str, collection_type: str, path: str) -> bool:
        st, body, _ = http(f"{self.base}/Library/VirtualFolders", headers=self._h())
        existing = jloads(body, [])
        if isinstance(existing, list) and any(v.get("Name") == name for v in existing):
            return step(f"Jellyfin: library {name}", True, "already configured")
        q = urllib.parse.urlencode({"name": name, "collectionType": collection_type, "paths": path, "refreshLibrary": "true"})
        payload = {"LibraryOptions": {"EnableRealtimeMonitor": True, "EnablePhotos": False, "SaveLocalMetadata": True, "PathInfos": [{"Path": path}]}}
        st, body, _ = http(f"{self.base}/Library/VirtualFolders?{q}", "POST", payload, headers=self._h(), timeout=60)
        return step(f"Jellyfin: library {name}", st in (200, 204), "created" if st in (200, 204) else f"HTTP {st}: {body[:120]}")


# ----------------------------------------------------------------------------- seerr
def wire_seerr(host: str, admin_user: str, admin_pass: str, radarr_key: str, sonarr_key: str, profile_name: str = "") -> None:
    base = f"http://{host}:{PORTS['seerr']}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(path, method="GET", data=None, timeout=30):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"}, method=method)
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, jloads(r.read().decode(), {})
        except urllib.error.HTTPError as e:
            return e.code, jloads(e.read().decode(errors="replace"), {})
        except (urllib.error.URLError, OSError) as e:
            return 0, {"error": str(e)}

    st, _ = call("/api/v1/status")
    if st != 200:
        step("Seerr: reachable", False, f"HTTP {st}", required=False)
        return
    st, settings = call("/api/v1/settings/public")
    if isinstance(settings, dict) and settings.get("initialized"):
        step("Seerr: initialisation", True, "already initialised", required=False)
        return

    st, resp = call("/api/v1/auth/jellyfin", "POST", {"username": admin_user, "password": admin_pass, "hostname": INTERNAL["jellyfin"], "port": PORTS["jellyfin"], "useSsl": False, "urlBase": "", "serverType": 2})
    if st not in (200, 201):
        step("Seerr: sign in with Jellyfin admin", False, f"HTTP {st}: {str(resp)[:160]}", required=False)
        return
    step("Seerr: sign in with Jellyfin admin", True, required=False)

    call("/api/v1/settings/jellyfin/library?sync=true", timeout=60)
    targets = (
        ("radarr", "/api/v1/settings/radarr", radarr_key, PORTS["radarr"], "/data/media/movies"),
        ("sonarr", "/api/v1/settings/sonarr", sonarr_key, PORTS["sonarr"], "/data/media/tv"),
    )
    for name, path, key, port, root_hint in targets:
        st, existing = call(path)
        if isinstance(existing, list) and existing:
            step(f"Seerr: {name} already registered", True, required=False)
            continue
        st, test = call(f"{path}/test", "POST", {"hostname": name, "port": port, "apiKey": key, "useSsl": False, "baseUrl": ""})
        profiles = test.get("profiles", []) if isinstance(test, dict) else []
        root_folders = test.get("rootFolders", []) if isinstance(test, dict) else []
        preferred = [n for n in (profile_name, "1080p Compact", "HD-1080p", "Any") if n]
        profile = next((p for n in preferred for p in profiles if p.get("name") == n), profiles[0] if profiles else None)
        root = next((r for r in root_folders if r.get("path") == root_hint), root_folders[0] if root_folders else None)
        if not profile or not root:
            step(f"Seerr: register {name}", False, f"test endpoint returned no profiles/root folders (HTTP {st})", required=False)
            continue
        payload = {
            "name": name.capitalize(), "hostname": name, "port": port, "apiKey": key, "useSsl": False, "baseUrl": "",
            "activeProfileId": profile["id"], "activeProfileName": profile["name"], "activeDirectory": root["path"],
            "is4k": False, "isDefault": True, "minimumAvailability": "released", "tags": [], "externalUrl": "",
            "syncEnabled": True, "preventSearch": False,
        }
        if name == "sonarr":
            payload.update({"activeAnimeProfileId": profile["id"], "activeAnimeProfileName": profile["name"], "activeAnimeDirectory": root["path"], "enableSeasonFolders": True, "animeTags": []})
        st, resp = call(path, "POST", payload)
        step(f"Seerr: register {name}", st in (200, 201), f"HTTP {st}", required=False)

    st, _ = call("/api/v1/settings/initialize", "POST", {})
    step("Seerr: initialisation", st in (200, 201), f"HTTP {st}", required=False)


# ------------------------------------------------------------------------- indexers
def prowlarr_indexer_schemas(prowlarr: Arr) -> List[Dict[str, Any]]:
    """Prowlarr's own indexer definition list (ships with Prowlarr; nothing comes from this repo)."""
    st, schemas = prowlarr.get("indexer/schema")
    return schemas if st == 200 and isinstance(schemas, list) else []


def prowlarr_indexers(prowlarr: Arr) -> List[Dict[str, Any]]:
    st, existing = prowlarr.get("indexer")
    return existing if st == 200 and isinstance(existing, list) else []


def prowlarr_add_indexer(prowlarr: Arr, name: str, values: Optional[Dict[str, Any]] = None, force: bool = False) -> Tuple[bool, str]:
    """Adds one indexer by its definition name, filling credential fields from `values`."""
    schema = next((dict(s) for s in prowlarr_indexer_schemas(prowlarr) if s.get("name") == name), None)
    if schema is None:
        return False, "unknown indexer"
    if any(i.get("name") == name for i in prowlarr_indexers(prowlarr)):
        return True, "already configured"
    schema.update({"name": name, "enable": True, "priority": schema.get("priority") or 25, "tags": schema.get("tags") or []})
    schema.setdefault("appProfileId", 1)
    set_fields(schema, values or {})
    st, resp = prowlarr.post("indexer?forceSave=true" if force else "indexer", schema)
    if st in (200, 201):
        return True, "added"
    return False, f"HTTP {st}: {str(resp)[:200]}"


def write_key_file(path: Path, key: str, group: str = "") -> bool:
    """Writes an API key 0640 root:<group> so an unprivileged daemon in <group> can read it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(key + "\n", encoding="utf-8")
        os.chmod(tmp, 0o640)
        actual_group = "root"
        if group and hasattr(os, "chown"):
            import grp

            try:
                os.chown(tmp, 0, grp.getgrnam(group).gr_gid)
                actual_group = group
            except (KeyError, PermissionError) as e:
                tmp.replace(path)
                return step(f"Prowlarr: API key file {path}", False,
                            f"written 0640 root:root but group '{group}' could not be applied ({e}); the indexer picker cannot read it",
                            required=False)
        tmp.replace(path)
        return step(f"Prowlarr: API key file {path}", True, f"0640 root:{actual_group}")
    except OSError as e:
        return step(f"Prowlarr: API key file {path}", False, str(e), required=False)


def cmd_indexers(args) -> int:
    key = args.api_key or ""
    if not key and args.key_file:
        try:
            key = Path(args.key_file).read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
    if not key and args.config_dir:
        key = read_api_key(Path(args.config_dir), "prowlarr", retries=1)
    if not key:
        print("error: no Prowlarr API key (--api-key, --key-file or --config-dir)", file=sys.stderr)
        return 2
    prowlarr = Arr("prowlarr", args.host, key, "v1")

    if args.action == "list":
        configured = {i.get("name") for i in prowlarr_indexers(prowlarr)}
        rows = [{"name": s.get("name"), "protocol": s.get("protocol"), "privacy": s.get("privacy"),
                 "language": s.get("language"), "configured": s.get("name") in configured}
                for s in prowlarr_indexer_schemas(prowlarr) if s.get("name")]
        rows.sort(key=lambda r: ((r["privacy"] != "public"), (r["name"] or "").lower()))
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                flag = "*" if r["configured"] else " "
                print(f"{flag} {r['name']:<40} {r['protocol'] or '':<8} {r['privacy'] or '':<12} {r['language'] or ''}")
        return 0

    values: Dict[str, Any] = {}
    for item in args.field or []:
        if "=" in item:
            k, v = item.split("=", 1)
            values[k.strip()] = v
    rc = 0
    for name in args.names:
        ok, detail = prowlarr_add_indexer(prowlarr, name, values, force=args.force)
        step(f"Prowlarr: indexer {name}", ok, detail)
        rc = rc if ok else 1
    if args.names:
        prowlarr.post("command", {"name": "ApplicationIndexerSync"})
    return rc


# ---------------------------------------------------------------- profile pack
PACK_ENV_DEFAULTS = {
    "MEDIA_PROFILES": "on",
    "MEDIA_SECOND_LANGUAGE": "",
    "MEDIA_DEFAULT_PROFILE": "compact",
    "MEDIA_CODECS": "hevc",
    "MEDIA_SEEDING": "while-it-helps",
    "MEDIA_PUBLIC_TRACKERS": "on",
}


def read_env_file(path: str) -> Dict[str, str]:
    """KEY=VALUE lines (docker compose env-file syntax); comments and blanks ignored."""
    out: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _on(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "on", "true", "yes")


def resolve_pack_settings(args, pack: Dict[str, Any]) -> Dict[str, Any]:
    """Command-line flags win over the env file, which wins over the defaults."""
    env = dict(PACK_ENV_DEFAULTS)
    if getattr(args, "env_file", ""):
        env.update({k: v for k, v in read_env_file(args.env_file).items() if v != "" or k == "MEDIA_SECOND_LANGUAGE"})

    def pick(flag: str, key: str) -> str:
        value = getattr(args, flag, None)
        return str(value) if value not in (None, "") else env.get(key, PACK_ENV_DEFAULTS.get(key, ""))

    language = pp.find_language(pack, pick("language", "MEDIA_SECOND_LANGUAGE"))
    default_profile = pick("default_profile", "MEDIA_DEFAULT_PROFILE").strip().lower()
    slugs = pack["meta"]["profile_slugs"]
    if default_profile not in slugs:
        raise ValueError(f"unknown default profile '{default_profile}' (choose from {', '.join(slugs)})")
    if default_profile == "dual-audio-first" and language is None:
        raise ValueError("the Dual Audio First profile needs a second language")
    seeding = pick("seeding", "MEDIA_SEEDING").strip().lower()
    if seeding not in pp.SEEDING_CHOICES:
        raise ValueError(f"unknown seeding choice '{seeding}' (choose from {', '.join(pp.SEEDING_CHOICES)})")
    trackers = not getattr(args, "no_public_trackers", False) and _on(env.get("MEDIA_PUBLIC_TRACKERS", "on"))
    return {
        "enabled": _on(env.get("MEDIA_PROFILES", "on")),
        "language": language,
        "language_name": language["name"] if language else "",
        "default_profile": default_profile,
        "default_profile_name": slugs[default_profile],
        "codecs": pp.parse_codecs(pick("codecs", "MEDIA_CODECS")),
        "seeding": seeding,
        "public_trackers": trackers,
        "qbit_user": getattr(args, "qbit_user", "") or env.get("QBITTORRENT_USER", "") or "admin",
        "qbit_pass": getattr(args, "qbit_pass", "") or env.get("QBITTORRENT_PASS", ""),
    }


class Action:
    """One change the pack wants. `run` performs it and returns (ok, detail)."""

    def __init__(self, app: str, what: str, detail: Optional[List[str]] = None, run=None, required: bool = True):
        self.app, self.what, self.detail, self.run, self.required = app, what, detail or [], run, required

    def as_dict(self) -> Dict[str, Any]:
        return {"app": self.app, "change": self.what, "detail": self.detail}


class PackRunner:
    """Plans and applies the profile pack against live apps. Only objects with the pack's
    prefixes and its own profiles are created or changed; everything else is left alone."""

    def __init__(self, pack: Dict[str, Any], settings: Dict[str, Any], arrs: Dict[str, "Arr"],
                 prowlarr: Optional["Arr"] = None, qbit: Optional[QBit] = None, data_dir: str = "",
                 puid: int = 1000, pgid: int = 1000):
        self.pack, self.s, self.arrs, self.prowlarr, self.qbit = pack, settings, arrs, prowlarr, qbit
        self.data_dir, self.puid, self.pgid = data_dir, puid, pgid
        self.notes: List[str] = []
        self.errors: List[str] = []

    # ------------------------------------------------------------ helpers
    def _get_list(self, arr: "Arr", path: str) -> Optional[List[Dict[str, Any]]]:
        st, data = arr.get(path)
        if st != 200 or not isinstance(data, list):
            self.errors.append(f"{arr.name}: GET {path} -> HTTP {st}")
            return None
        return data

    def _get_obj(self, arr: "Arr", path: str) -> Optional[Dict[str, Any]]:
        st, data = arr.get(path)
        if st != 200 or not isinstance(data, dict):
            self.errors.append(f"{arr.name}: GET {path} -> HTTP {st}")
            return None
        return data

    @staticmethod
    def _ok(st: int, resp: Any) -> Tuple[bool, str]:
        if st in (200, 201, 202, 204):
            return True, f"HTTP {st}"
        return False, f"HTTP {st}: {str(resp)[:200]}"

    # --------------------------------------------------------------- plan
    def plan(self) -> List[Action]:
        actions: List[Action] = []
        for app, arr in self.arrs.items():
            actions += self._plan_formats(app, arr)
        for app, arr in self.arrs.items():
            actions += self._plan_quality_definitions(app, arr)
        for app, arr in self.arrs.items():
            actions += self._plan_profiles(app, arr)
        for app, arr in self.arrs.items():
            actions += self._plan_app_settings(app, arr)
        if self.prowlarr is not None:
            actions += self._plan_prowlarr()
        if self.qbit is not None:
            actions += self._plan_qbit()
        return actions

    def _desired_formats(self, app: str, arr: "Arr") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        langs = self._get_list(arr, "language") or []
        desired = []
        for fmt in pp.render_formats(self.pack, app, self.s["language"]):
            api, notes = pp.to_api_format(fmt, langs)
            self.notes += [f"{app}: {n}" for n in notes]
            desired.append(api)
        return desired, langs

    def _plan_formats(self, app: str, arr: "Arr") -> List[Action]:
        live = self._get_list(arr, "customformat")
        if live is None:
            return []
        desired, _ = self._desired_formats(app, arr)
        by_name = {f.get("name"): f for f in live}
        actions = []
        for api in desired:
            cur = by_name.get(api["name"])
            if cur is None:
                actions.append(Action(app, f"create format {api['name']}", run=lambda a=arr, p=api: self._ok(*a.post("customformat", p))))
                continue
            diffs = pp.diff_format(cur, api)
            if diffs:
                payload = dict(api, id=cur["id"])
                actions.append(Action(app, f"update format {api['name']}", diffs,
                                      run=lambda a=arr, p=payload: self._ok(*a.put(f"customformat/{p['id']}", p))))
        return actions

    def _plan_quality_definitions(self, app: str, arr: "Arr") -> List[Action]:
        live = self._get_list(arr, "qualitydefinition")
        if live is None:
            return []
        updated, notes = pp.quality_definition_changes(self.pack, app, live)
        if not updated:
            return []
        return [Action(app, "update size limits", notes, run=lambda a=arr, u=updated: self._ok(*a.put("qualitydefinition/update", u)))]

    def _plan_profiles(self, app: str, arr: "Arr") -> List[Action]:
        live_profiles = self._get_list(arr, "qualityprofile")
        live_formats = self._get_list(arr, "customformat")
        defs = self._get_list(arr, "qualitydefinition")
        if live_profiles is None or live_formats is None or defs is None:
            return []
        actions = []
        for desired in pp.render_profiles(self.pack, app, self.s["language"], self.s["codecs"]):
            existing = next((p for p in live_profiles if p.get("name") == desired["name"]), None)
            payload = pp.build_profile_payload(desired, app, defs, live_formats, existing)
            if existing is None:
                diffs = ["new profile"]
            else:
                diffs = pp.diff_profile(existing, payload, self.pack, desired["scores"])
                self.notes += [f"{app}: {desired['name']}: {d[6:]}" for d in diffs if d.startswith("note: ")]
                diffs = [d for d in diffs if not d.startswith("note: ")]
                missing = [n for n in desired["scores"] if n not in {f["name"] for f in live_formats}]
                diffs += [f"score {n}: (format not created yet) -> {desired['scores'][n]}" for n in missing
                          if not any(d.startswith(f"score {n}:") for d in diffs)]
            if diffs:
                verb = "create" if existing is None else "update"
                actions.append(Action(app, f"{verb} profile {desired['name']}", diffs,
                                      run=lambda a=arr, d=desired, ap=app: self._apply_profile(ap, a, d)))
        return actions

    def _apply_profile(self, app: str, arr: "Arr", desired: Dict[str, Any]) -> Tuple[bool, str]:
        live_profiles = self._get_list(arr, "qualityprofile")
        live_formats = self._get_list(arr, "customformat")
        defs = self._get_list(arr, "qualitydefinition")
        if live_profiles is None or live_formats is None or defs is None:
            return False, "could not read the app's profiles, formats or qualities"
        existing = next((p for p in live_profiles if p.get("name") == desired["name"]), None)
        payload = pp.build_profile_payload(desired, app, defs, live_formats, existing)
        if existing is None:
            return self._ok(*arr.post("qualityprofile", payload))
        return self._ok(*arr.put(f"qualityprofile/{existing['id']}", payload))

    def _plan_app_settings(self, app: str, arr: "Arr") -> List[Action]:
        cfg = self.pack["settings"].get(app, {})
        actions = []
        indexer_cfg = cfg.get("config/indexer", {})
        if "whitelistedHardcodedSubs" in indexer_cfg:
            cur = self._get_obj(arr, "config/indexer")
            if cur is not None:
                want = pp.merge_csv(cur.get("whitelistedHardcodedSubs") or "", indexer_cfg["whitelistedHardcodedSubs"]["merge_csv"])
                if want != (cur.get("whitelistedHardcodedSubs") or ""):
                    payload = dict(cur, whitelistedHardcodedSubs=want)
                    actions.append(Action(app, "whitelist soft-subtitle tags (ESub, MSub, EngSub)",
                                          [f"whitelisted hardcoded subs: '{cur.get('whitelistedHardcodedSubs') or ''}' -> '{want}'"],
                                          run=lambda a=arr, p=payload: self._ok(*a.put("config/indexer", p)), required=False))
        mm = cfg.get("config/mediamanagement", {}).get("recycleBin")
        if mm:
            cur = self._get_obj(arr, "config/mediamanagement")
            if cur is not None and not (cur.get("recycleBin") or "").strip():
                payload = dict(cur, recycleBin=mm["if_empty"], **mm.get("also", {}))
                actions.append(Action(app, f"recycle bin {mm['if_empty']}",
                                      ["upgrades and deletions go to the recycle bin (same filesystem, instant move)"],
                                      run=lambda a=arr, p=payload: self._set_recycle_bin(a, p), required=False))
        delay = cfg.get("delayprofile")
        if delay:
            profiles = self._get_list(arr, "delayprofile") or []
            default = next((d for d in profiles if d.get("id") == 1), profiles[-1] if profiles else None)
            if default is not None:
                want = {k: v["set"] for k, v in delay.items()}
                diffs = [f"{k}: {default.get(k)} -> {v}" for k, v in want.items() if default.get(k) != v]
                if diffs:
                    payload = dict(default, **want)
                    actions.append(Action(app, "delay profile: grab a near-perfect release at once", diffs,
                                          run=lambda a=arr, p=payload: self._ok(*a.put(f"delayprofile/{p['id']}", p)), required=False))
        return actions

    def _set_recycle_bin(self, arr: "Arr", payload: Dict[str, Any]) -> Tuple[bool, str]:
        if self.data_dir:
            # The apps see the data root as /data; create the folder on the host side first.
            rel = Path(payload["recycleBin"]).relative_to("/data")
            host_path = Path(self.data_dir) / rel
            try:
                host_path.mkdir(parents=True, exist_ok=True)
                if hasattr(os, "chown") and os.name != "nt":
                    try:
                        os.chown(host_path, self.puid, self.pgid)
                    except PermissionError:
                        pass
            except OSError as exc:
                return False, f"could not create {host_path}: {exc}"
        ok, detail = self._ok(*arr.put("config/mediamanagement", payload))
        if not ok and not self.data_dir:
            detail += " (create the folder under your data root, or pass --data-dir)"
        return ok, detail

    def _plan_prowlarr(self) -> List[Action]:
        p = self.prowlarr
        cfg = self.pack["settings"]["prowlarr"]
        actions = []
        changes = ensure_prowlarr_full_sync(p, dry_run=True)
        if changes and not changes[0].startswith("GET "):
            actions.append(Action("prowlarr", "app links: Full Sync", changes,
                                  run=lambda: (ensure_prowlarr_full_sync(p) is not None, "done"), required=False))
        elif changes:
            self.errors.append(f"prowlarr: {changes[0]}")
        profiles = self._get_list(p, "appprofile")
        if profiles:
            default = next((x for x in profiles if x.get("id") == 1), profiles[0])
            want = int(cfg["default_app_profile_min_seeders"])
            if int(default.get("minimumSeeders") or 0) < want:
                payload = dict(default, minimumSeeders=want)
                actions.append(Action("prowlarr", f"app profile {default.get('name')}: minimum seeders {want}",
                                      [f"minimum seeders: {default.get('minimumSeeders')} -> {want} (1-3 seeders rank like 0)"],
                                      run=lambda pl=payload: self._ok(*p.put(f"appprofile/{pl['id']}", pl)), required=False))
            live = cfg["live_app_profile"]
            if not any(x.get("name") == live["name"] for x in profiles):
                payload = {k: v for k, v in default.items() if k != "id"}
                payload.update(name=live["name"], minimumSeeders=live["minimumSeeders"])
                actions.append(Action("prowlarr", f"app profile {live['name']} (minimum seeders {live['minimumSeeders']})",
                                      ["for indexers with live, accurate seeder counts; assign it per indexer"],
                                      run=lambda pl=payload: self._ok(*p.post("appprofile", pl)), required=False))
        return actions

    def _qbit_wanted(self, prefs: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.pack["settings"]["qbittorrent"]
        want: Dict[str, Any] = {}
        want.update(cfg["seeding"][self.s["seeding"]])
        want.update(cfg["queue"])
        want.update(cfg["evening_upload_limit"])
        want.update(cfg["other"])
        if self.s["public_trackers"] and "add_trackers_from_url_enabled" in prefs:
            want.update(cfg["trackers_from_url"])
        if "excluded_file_names" in prefs:
            want["excluded_file_names_enabled"] = True
            want["excluded_file_names"] = pp.merge_lines(prefs.get("excluded_file_names") or "", cfg["excluded_file_names"])
        # Only keys this qBittorrent version knows about.
        return {k: v for k, v in want.items() if k in prefs}

    @staticmethod
    def _same(a: Any, b: Any) -> bool:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
            return abs(float(a) - float(b)) < 1e-6
        return a == b

    def _plan_qbit(self) -> List[Action]:
        q = self.qbit
        ok, detail = q.login(attempts=1)
        if not ok:
            self.errors.append(f"qbittorrent: login failed ({detail})")
            return []
        prefs = q.preferences()
        if not prefs:
            self.errors.append("qbittorrent: could not read preferences")
            return []
        want = self._qbit_wanted(prefs)
        changed = {k: v for k, v in want.items() if not self._same(prefs.get(k), v)}
        actions = []
        if changed:
            detail = [f"{k}: {str(prefs.get(k))[:60]!s} -> {str(v)[:60]}" for k, v in sorted(changed.items())]
            label = "seed while it helps" if self.s["seeding"] == "while-it-helps" else "no seeding after download"
            actions.append(Action("qbittorrent", f"preferences ({label}, queue limits, evening upload limit)", detail,
                                  run=lambda c=changed: q.set_preferences(c), required=False))
        cats = q.categories()
        missing = [(n, path) for n, path in self.pack["settings"]["qbittorrent"]["categories"].items() if n not in cats]
        if missing:
            actions.append(Action("qbittorrent", "categories " + ", ".join(n for n, _ in missing), [],
                                  run=lambda m=missing: (q.ensure_categories(m), "created"), required=False))
        return actions

    # ------------------------------------------------------------ migrate
    def legacy_plan(self) -> List[Action]:
        legacy = self.pack["meta"]["legacy"]
        target = legacy["move_titles_to"]
        actions: List[Action] = []
        for app, arr in self.arrs.items():
            profiles = self._get_list(arr, "qualityprofile") or []
            old = [p for p in profiles if p.get("name") in legacy["profiles"]]
            if old:
                coll, key, editor = ("movie", "movieIds", "movie/editor") if app == "radarr" else ("series", "seriesIds", "series/editor")
                titles = self._get_list(arr, coll) or []
                for prof in old:
                    users = [t for t in titles if t.get("qualityProfileId") == prof["id"]]
                    if users:
                        names = [str(t.get("title")) for t in users]
                        actions.append(Action(app, f"move {len(users)} title(s) from {prof['name']} to {target}", names[:20],
                                              run=lambda a=arr, ids=[t["id"] for t in users], k=key, e=editor: self._move_titles(a, ids, k, e, target)))
                    actions.append(Action(app, f"delete profile {prof['name']}", [f"id {prof['id']}"],
                                          run=lambda a=arr, pid=prof["id"]: self._ok(*a.delete(f"qualityprofile/{pid}"))))
            formats = self._get_list(arr, "customformat") or []
            for fmt in formats:
                if fmt.get("name") in legacy["custom_formats"]:
                    actions.append(Action(app, f"delete legacy format {fmt['name']}", [f"id {fmt['id']}"],
                                          run=lambda a=arr, fid=fmt["id"]: self._ok(*a.delete(f"customformat/{fid}"))))
        return actions

    def _move_titles(self, arr: "Arr", ids: List[int], key: str, editor: str, target: str) -> Tuple[bool, str]:
        profiles = self._get_list(arr, "qualityprofile") or []
        dest = next((p for p in profiles if p.get("name") == target), None)
        if dest is None:
            return False, f"profile {target} not found"
        return self._ok(*arr.put(editor, {key: ids, "qualityProfileId": dest["id"]}))

    # ------------------------------------------------------------ execute
    def execute(self, actions: List[Action]) -> int:
        failed = 0
        for a in actions:
            ok, detail = a.run() if a.run else (True, "")
            step(f"{a.app}: {a.what}", ok, detail, required=a.required)
            failed += 0 if (ok or not a.required) else 1
        return failed


def _pack_clients(args, settings: Dict[str, Any]) -> Tuple[Dict[str, "Arr"], Optional["Arr"], Optional[QBit]]:
    config_dir = Path(args.config_dir)
    arrs: Dict[str, Arr] = {}
    prowlarr = None
    for app, version in (("radarr", "v3"), ("sonarr", "v3"), ("prowlarr", "v1")):
        if app in (getattr(args, "skip", None) or []):
            continue
        key = read_api_key(config_dir, app, retries=args.retries)
        if not key:
            step(f"{app}: API key", False, f"{config_dir / app / 'config.xml'} missing or without <ApiKey>", required=app != "prowlarr")
            continue
        if app == "prowlarr":
            prowlarr = Arr(app, args.host, key, version)
        else:
            arrs[app] = Arr(app, args.host, key, version)
    qbit = None
    if "qbittorrent" not in (getattr(args, "skip", None) or []):
        if settings["qbit_pass"]:
            qbit = QBit(args.host, settings["qbit_user"], settings["qbit_pass"])
        else:
            step("qbittorrent: settings", True, "skipped (no password: --qbit-pass or QBITTORRENT_PASS in --env-file)", required=False)
    return arrs, prowlarr, qbit


def cmd_profiles(args) -> int:
    try:
        pack = pp.load_pack(Path(args.pack_dir) if args.pack_dir else pp.PACK_DIR)
        settings = resolve_pack_settings(args, pack)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    summary = {k: settings[k] for k in ("enabled", "language_name", "default_profile_name", "codecs", "seeding", "public_trackers")}
    report["settings"] = summary
    if not settings["enabled"] and args.action != "check":
        step("profile pack", True, "switched off (MEDIA_PROFILES=off); nothing changed", required=False)
        return 0
    for app in ("radarr", "sonarr"):
        if app not in (args.skip or []):
            if not wait_http(f"http://{args.host}:{PORTS[app]}/ping", retries=args.retries):
                step(f"{app}: reachable", False, f"http://{args.host}:{PORTS[app]}")
    if report["errors"]:
        return 2
    arrs, prowlarr, qbit = _pack_clients(args, settings)
    if report["errors"]:
        return 2
    runner = PackRunner(pack, settings, arrs, prowlarr, qbit, data_dir=args.data_dir, puid=args.puid, pgid=args.pgid)
    actions = runner.plan()
    if args.action == "migrate":
        actions += runner.legacy_plan()
    report["changes"] = [a.as_dict() for a in actions]
    report["notes"] = runner.notes
    report["errors"] += runner.errors

    dry = args.action == "check" or getattr(args, "dry_run", False)
    if dry:
        if not args.json:
            title = "Drift (live differs from the pack)" if args.action == "check" else "Planned changes (dry run, nothing changed)"
            print(f"{title}: {len(actions)}" + ("" if settings["enabled"] else "  [pack switched off]"))
            for a in actions:
                print(f"  - {a.app}: {a.what}")
                for d in a.detail:
                    print(f"      {d}")
            for n in runner.notes:
                print(f"  note: {n}")
            for e in runner.errors:
                print(f"  error: {e}")
        report["in_sync"] = not actions
        if runner.errors:
            return 2
        return 0 if (args.action == "migrate" or not actions) else 1

    if not actions:
        step("profile pack", True, f"already in sync ({settings['language_name'] or 'no second language'})", required=False)
    failed = runner.execute(actions)
    for n in runner.notes:
        print(f"note: {n}")
    return 0 if not failed and not runner.errors else 1


def cmd_seerr(args) -> int:
    config_dir = Path(args.config_dir)
    keys = {app: read_api_key(config_dir, app, retries=args.retries) for app in ("radarr", "sonarr")}
    for app, key in keys.items():
        step(f"{app}: API key from config.xml", bool(key), "" if key else "missing")
    if report["errors"]:
        return 1
    wire_seerr(args.host, args.admin_user, args.admin_pass, keys["radarr"], keys["sonarr"], args.profile)
    return 0 if not report["errors"] else 1


# ------------------------------------------------------------------------------ main
def cmd_seed(args) -> int:
    seed_qbittorrent(Path(args.config_dir), args.qbit_user, args.qbit_pass, args.puid, args.pgid)
    return 0 if not report["errors"] else 1


def cmd_wire(args) -> int:
    config_dir = Path(args.config_dir)
    host = args.host

    probes = {"radarr": "ping", "sonarr": "ping", "prowlarr": "ping", "qbittorrent": "", "jellyfin": "health"}
    for app, path in probes.items():
        url = f"http://{host}:{PORTS[app]}/{path}"
        step(f"{app}: reachable", wait_http(url, retries=args.retries), url)
    if report["errors"]:
        return 1

    keys = {app: read_api_key(config_dir, app) for app in ("radarr", "sonarr", "prowlarr")}
    for app, key in keys.items():
        step(f"{app}: API key from config.xml", bool(key), "" if key else f"{config_dir / app / 'config.xml'} missing or without <ApiKey>")
    if report["errors"]:
        return 1

    qb = QBit(host, args.qbit_user, args.qbit_pass)
    qb_ok, qb_detail = qb.login()
    if step("qBittorrent: login", qb_ok, qb_detail):
        step("qBittorrent: categories radarr/tv-sonarr", qb.ensure_categories())
        ex_ok, ex_detail = qb.ensure_excluded_files()
        step("qBittorrent: excluded payload extensions", ex_ok, ex_detail, required=False)

    radarr = Arr("radarr", host, keys["radarr"], "v3")
    sonarr = Arr("sonarr", host, keys["sonarr"], "v3")
    prowlarr = Arr("prowlarr", host, keys["prowlarr"], "v1")
    wire_arr(radarr, "/data/media/movies", "movieCategory", "radarr", args.qbit_user, args.qbit_pass)
    wire_arr(sonarr, "/data/media/tv", "tvCategory", "tv-sonarr", args.qbit_user, args.qbit_pass)
    wire_prowlarr(prowlarr, keys["radarr"], keys["sonarr"], args.byparr)

    if args.admin_pass:
        jf = Jellyfin(host)
        if jf.complete_startup(args.admin_user, args.admin_pass) and jf.login(args.admin_user, args.admin_pass):
            jf.ensure_library("Movies", "movies", "/data/media/movies")
            jf.ensure_library("Shows", "tvshows", "/data/media/tv")
        if not args.skip_seerr:
            wire_seerr(host, args.admin_user, args.admin_pass, keys["radarr"], keys["sonarr"])
    else:
        step("Jellyfin/Seerr: skipped (no --admin-pass)", True, required=False)

    if args.key_file:
        # Lets the Control Hub (an unprivileged daemon) offer the indexer picker without root.
        write_key_file(Path(args.key_file), keys["prowlarr"], args.key_group)

    report["api_keys"] = keys
    return 0 if not report["errors"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Wire the media pipeline apps together")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--config-dir", required=True, help="Host directory holding <app>/config.xml etc.")
        p.add_argument("--qbit-user", default="admin")
        p.add_argument("--qbit-pass", default=os.getenv("QBITTORRENT_PASS", ""))
        p.add_argument("--json", action="store_true", help="Print a JSON report at the end")

    seed = sub.add_parser("seed", help="Pre-seed qBittorrent.conf before the first start")
    common(seed)
    seed.add_argument("--puid", type=int, default=1000)
    seed.add_argument("--pgid", type=int, default=1000)

    wire = sub.add_parser("wire", help="Connect running apps to each other")
    common(wire)
    wire.add_argument("--host", default="127.0.0.1", help="Where the published ports are reachable")
    wire.add_argument("--admin-user", default="admin", help="Jellyfin/Seerr admin user to create")
    wire.add_argument("--admin-pass", default=os.getenv("MEDIA_ADMIN_PASS", ""), help="Jellyfin/Seerr admin password (skip Jellyfin/Seerr when empty)")
    wire.add_argument("--byparr", action="store_true", help="Register Byparr as Prowlarr's FlareSolverr proxy")
    wire.add_argument("--skip-seerr", action="store_true")
    wire.add_argument("--retries", type=int, default=60, help="Reachability retries (3s apart)")
    wire.add_argument("--key-file", default="", help="Also write Prowlarr's API key here (0640) for the Control Hub indexer picker")
    wire.add_argument("--key-group", default="", help="Group owner of --key-file (e.g. homelab)")

    prof = sub.add_parser("profiles", help="Apply, check or migrate the repo-owned release profiles")
    prof.add_argument("action", choices=["apply", "check", "migrate"])
    prof.add_argument("--config-dir", required=True, help="Host directory holding <app>/config.xml")
    prof.add_argument("--host", default="127.0.0.1")
    prof.add_argument("--env-file", default="", help="Read MEDIA_* choices and qBittorrent login from this env file")
    prof.add_argument("--language", default=None, help="Second audio language (e.g. Hindi), or 'none'")
    prof.add_argument("--default-profile", default=None, choices=["compact", "dual-audio-first"])
    prof.add_argument("--codecs", default=None, help="What the players decode: comma list of hevc,av1,dv")
    prof.add_argument("--seeding", default=None, choices=list(pp.SEEDING_CHOICES))
    prof.add_argument("--no-public-trackers", action="store_true", help="Do not append the public tracker list (private trackers)")
    prof.add_argument("--qbit-user", default="")
    prof.add_argument("--qbit-pass", default=os.getenv("QBITTORRENT_PASS", ""))
    prof.add_argument("--data-dir", default="", help="Host path mounted as /data (creates the recycle bin folder)")
    prof.add_argument("--puid", type=int, default=1000)
    prof.add_argument("--pgid", type=int, default=1000)
    prof.add_argument("--skip", action="append", choices=["radarr", "sonarr", "prowlarr", "qbittorrent"], help="Leave one app out")
    prof.add_argument("--pack-dir", default="", help=argparse.SUPPRESS)
    prof.add_argument("--retries", type=int, default=20, help="Reachability retries (3s apart)")
    prof.add_argument("--dry-run", action="store_true", help="migrate: print the plan only")
    prof.add_argument("--json", action="store_true")

    seerr = sub.add_parser("seerr", help="Initialise Seerr and register Radarr/Sonarr with a default profile")
    seerr.add_argument("--config-dir", required=True)
    seerr.add_argument("--host", default="127.0.0.1")
    seerr.add_argument("--admin-user", default="admin")
    seerr.add_argument("--admin-pass", default=os.getenv("MEDIA_ADMIN_PASS", ""))
    seerr.add_argument("--profile", default="1080p Compact", help="Default quality profile for requests")
    seerr.add_argument("--retries", type=int, default=20)
    seerr.add_argument("--json", action="store_true")

    ix = sub.add_parser("indexers", help="List Prowlarr's indexer definitions or add some by name")
    ix.add_argument("action", choices=["list", "add"])
    ix.add_argument("names", nargs="*", help="Indexer names to add (as shown by `indexers list`)")
    ix.add_argument("--host", default="127.0.0.1")
    ix.add_argument("--api-key", default=os.getenv("PROWLARR_API_KEY", ""))
    ix.add_argument("--key-file", default="", help="Read the API key from this file")
    ix.add_argument("--config-dir", default="", help="Or read it from <config-dir>/prowlarr/config.xml")
    ix.add_argument("--field", action="append", help="Credential field for private trackers, e.g. --field username=me --field password=secret")
    ix.add_argument("--force", action="store_true", help="Save even if Prowlarr's connection test fails")
    ix.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "indexers":
        return cmd_indexers(args)
    if args.command in ("profiles", "seerr"):
        if args.command == "seerr" and not args.admin_pass:
            print("error: --admin-pass (or MEDIA_ADMIN_PASS) is required", file=sys.stderr)
            return 2
        rc = cmd_profiles(args) if args.command == "profiles" else cmd_seerr(args)
        report["success"] = rc == 0
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        return rc
    if not args.qbit_pass:
        print("error: --qbit-pass (or QBITTORRENT_PASS) is required", file=sys.stderr)
        return 2

    rc = cmd_seed(args) if args.command == "seed" else cmd_wire(args)
    report["success"] = rc == 0
    if args.json:
        print(json.dumps(report, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
