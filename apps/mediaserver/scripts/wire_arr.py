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
        [--host 127.0.0.1] [--byparr] [--json]

What `wire` does:
  * reads each app's API key from <config-dir>/<app>/config.xml (generated on first start)
  * qBittorrent: categories movies/tv with save paths under /data/torrents
  * Radarr/Sonarr: root folders /data/media/{movies,tv}; qBittorrent as download client
  * Prowlarr: Radarr and Sonarr as applications (full sync); Byparr as indexer proxy (optional)
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

    def ensure_categories(self) -> bool:
        req = urllib.request.Request(self.base + "/api/v2/torrents/categories")
        try:
            with self.opener.open(req, timeout=15) as r:
                existing = json.loads(r.read().decode() or "{}")
        except Exception:
            existing = {}
        ok = True
        for name, path in (("movies", "/data/torrents/movies"), ("tv", "/data/torrents/tv")):
            if name in existing:
                continue
            st, _ = self._form("/api/v2/torrents/createCategory", {"category": name, "savePath": path})
            ok = ok and st in (200, 409)
        return ok


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
def wire_seerr(host: str, admin_user: str, admin_pass: str, radarr_key: str, sonarr_key: str) -> None:
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
        profile = next((p for p in profiles if p.get("name") in ("HD-1080p", "Any")), profiles[0] if profiles else None)
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
        if group and hasattr(os, "chown"):
            import grp

            try:
                os.chown(tmp, 0, grp.getgrnam(group).gr_gid)
            except (KeyError, PermissionError):
                pass
        tmp.replace(path)
        return step(f"Prowlarr: API key file {path}", True, f"0640 root:{group or 'root'}")
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
        step("qBittorrent: categories movies/tv", qb.ensure_categories())

    radarr = Arr("radarr", host, keys["radarr"], "v3")
    sonarr = Arr("sonarr", host, keys["sonarr"], "v3")
    prowlarr = Arr("prowlarr", host, keys["prowlarr"], "v1")
    wire_arr(radarr, "/data/media/movies", "movieCategory", "movies", args.qbit_user, args.qbit_pass)
    wire_arr(sonarr, "/data/media/tv", "tvCategory", "tv", args.qbit_user, args.qbit_pass)
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
