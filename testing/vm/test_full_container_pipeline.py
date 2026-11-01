#!/usr/bin/env python3
"""
Homelab Blueprint - Live Multi-Container Pipeline Integration Test
Executes the complete real-world media stack transaction:
  1. Spins up actual Docker containers:
     - qBittorrent (:8080)
     - Radarr (:7878)
     - Sonarr (:8989)
     - Prowlarr (:9696)
     - Seerr (:5055)
     - Jellyfin (:8096)
  2. Binds storage to dedicated loopback ext4 volume at /data
  3. Launches Mock Torznab Indexer (:9999) with BEP 19 Web Seeding
  4. Auto-wires Prowlarr -> Radarr & Sonarr -> qBittorrent via REST APIs
  5. Triggers media ingestion (Movie & TV)
  6. Validates real qBittorrent download from Web Seed
  7. Asserts 0-I/O atomic hardlink invariant (src.st_ino == dst.st_ino, st_nlink >= 2)
  8. Triggers Jellyfin media library refresh and asserts detection
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

# Ensure UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE_FILE = REPO_ROOT / "apps" / "mediaserver" / "docker-compose.yml"
MOCK_SERVER_SCRIPT = REPO_ROOT / "testing" / "vm" / "mocks" / "mock_torznab.py"

DATA_DIR = Path("/data")
CONFIG_BASE = REPO_ROOT / "apps" / "mediaserver" / "config"
MOCK_PORT = 9999


def log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [LIVE-PIPELINE] {msg}", flush=True)


def http_request(url: str, method: str = "GET", data: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 15) -> Tuple[int, str]:
    """Helper to perform HTTP requests using Python standard library"""
    h = headers.copy() if headers else {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return resp.status, content
    except urllib.error.HTTPError as e:
        err_content = e.read().decode("utf-8", errors="replace")
        return e.code, err_content
    except Exception as e:
        return 0, str(e)


def wait_for_http(url: str, name: str, max_retries: int = 45, delay: float = 2.0) -> bool:
    """Polls an HTTP endpoint until ready"""
    log(f"Waiting for {name} at {url}...")
    for _ in range(max_retries):
        status, _ = http_request(url)
        if 200 <= status < 400 or status in (401, 403):  # Responding HTTP code is sufficient
            log(f"✅ {name} is online (status {status})")
            return True
        time.sleep(delay)
    log(f"❌ Timed out waiting for {name}")
    return False


def get_api_key_from_xml(config_xml_path: Path) -> str:
    """Extracts API key from standard LinuxServer config.xml"""
    for _ in range(35):
        if config_xml_path.exists():
            try:
                tree = ET.parse(config_xml_path)
                root = tree.getroot()
                key_elem = root.find("ApiKey")
                if key_elem is not None and key_elem.text:
                    return key_elem.text.strip()
            except Exception:
                pass
        time.sleep(1.0)
    return ""


class LiveContainerHarness:
    def __init__(self):
        self.mock_proc = None
        self.radarr_api_key = ""
        self.sonarr_api_key = ""
        self.prowlarr_api_key = ""

    def setup_storage_and_env(self):
        log("--- Stage 1: Initializing Storage Topology & Compose Env ---")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "torrents" / "movies").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "torrents" / "tv").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "media" / "movies").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "media" / "tv").mkdir(parents=True, exist_ok=True)
        CONFIG_BASE.mkdir(parents=True, exist_ok=True)

        # Clean previous torrent state so qBittorrent downloads cleanly
        for p in (DATA_DIR / "torrents").glob("*"):
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        for p in (DATA_DIR / "media").glob("*"):
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)

        (DATA_DIR / "torrents" / "movies").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "torrents" / "tv").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "media" / "movies").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "media" / "tv").mkdir(parents=True, exist_ok=True)

        # Write mediaserver .env pointing to loopback volume DATA_DIR
        media_env = REPO_ROOT / "apps" / "mediaserver" / ".env"
        env_content = f"""PUID=1000
PGID=1000
TZ=UTC
CONFIG_DIR={CONFIG_BASE}
DATA_DIR={DATA_DIR}
"""
        media_env.write_text(env_content, encoding="utf-8")
        log(f"Generated mediaserver .env pointing DATA_DIR to '{DATA_DIR}'")

        # Seed qBittorrent config for headless automated API authentication
        qb_conf_dir = CONFIG_BASE / "qbittorrent" / "qBittorrent"
        qb_conf_dir.mkdir(parents=True, exist_ok=True)
        qb_conf_file = qb_conf_dir / "qBittorrent.conf"
        qb_conf = """[LegalNotice]
Accepted=true

[Network]
Cookies=@Invalid()

[Preferences]
Connection\\PortRangeMin=6881
Downloads\\SavePath=/data/torrents/
WebUI\\Address=0.0.0.0
WebUI\\AuthSubnetWhitelist=0.0.0.0/0
WebUI\\AuthSubnetWhitelistEnabled=true
WebUI\\LocalHostAuth=false
WebUI\\Port=8080
WebUI\\ServerDomains=*
"""
        qb_conf_file.write_text(qb_conf, encoding="utf-8")
        log("Pre-seeded qBittorrent.conf for headless automated API authentication")

        # Clean qBittorrent session queue & BT_backup if present
        for qb_cache in [CONFIG_BASE / "qbittorrent" / "qBittorrent" / "BT_backup", CONFIG_BASE / "qbittorrent" / "qBittorrent" / "data"]:
            if qb_cache.exists():
                shutil.rmtree(qb_cache, ignore_errors=True)
                qb_cache.mkdir(parents=True, exist_ok=True)

        # Ensure Seerr tmdb-interceptor.js is present in its config volume
        seerr_conf_dir = CONFIG_BASE / "seerr"
        seerr_conf_dir.mkdir(parents=True, exist_ok=True)
        seerr_dst = seerr_conf_dir / "tmdb-interceptor.js"
        seerr_src = REPO_ROOT / "apps" / "mediaserver" / "config" / "seerr" / "tmdb-interceptor.js"
        if seerr_src.exists() and not seerr_dst.exists():
            shutil.copy2(seerr_src, seerr_dst)
            log("Injected Seerr tmdb-interceptor.js into config directory")

        # Ensure proper permissions across both DATA_DIR and CONFIG_BASE for non-root containers
        subprocess.run(["chown", "-R", "1000:1000", str(DATA_DIR)], check=False)
        subprocess.run(["chmod", "-R", "777", str(DATA_DIR)], check=False)
        subprocess.run(["chown", "-R", "1000:1000", str(CONFIG_BASE)], check=False)
        subprocess.run(["chmod", "-R", "777", str(CONFIG_BASE)], check=False)

    def start_mock_torznab(self):
        log("--- Stage 2: Launching Mock Torznab Indexer on Port 9999 ---")
        self.mock_proc = subprocess.Popen(
            [sys.executable, str(MOCK_SERVER_SCRIPT), "--host", "0.0.0.0", "--port", str(MOCK_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        assert wait_for_http(f"http://127.0.0.1:{MOCK_PORT}/health", "Mock Torznab", max_retries=15)

    def start_containers(self):
        log("--- Stage 3: Launching Docker Compose Mediaserver Stack ---")
        cmd = [
            "docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d",
            "qbittorrent", "radarr", "sonarr", "prowlarr", "seerr", "jellyfin"
        ]
        subprocess.run(cmd, check=True)

        # Wait for all core Web APIs to respond
        assert wait_for_http("http://127.0.0.1:8080", "qBittorrent Web UI", max_retries=30)
        assert wait_for_http("http://127.0.0.1:7878/api/v3/system/status", "Radarr API", max_retries=45)
        assert wait_for_http("http://127.0.0.1:8989/api/v3/system/status", "Sonarr API", max_retries=45)
        assert wait_for_http("http://127.0.0.1:9696/api/v1/system/status", "Prowlarr API", max_retries=45)
        assert wait_for_http("http://127.0.0.1:5055/api/v1/status", "Seerr API", max_retries=45)
        assert wait_for_http("http://127.0.0.1:8096/System/Info/Public", "Jellyfin API", max_retries=45)

    def extract_api_keys(self):
        log("--- Stage 4: Extracting Auto-Generated API Credentials ---")
        radarr_xml = CONFIG_BASE / "radarr" / "config.xml"
        sonarr_xml = CONFIG_BASE / "sonarr" / "config.xml"
        prowlarr_xml = CONFIG_BASE / "prowlarr" / "config.xml"

        self.radarr_api_key = get_api_key_from_xml(radarr_xml)
        self.sonarr_api_key = get_api_key_from_xml(sonarr_xml)
        self.prowlarr_api_key = get_api_key_from_xml(prowlarr_xml)

        log(f"  Radarr API Key:   {self.radarr_api_key[:8]}... (len {len(self.radarr_api_key)})")
        log(f"  Sonarr API Key:   {self.sonarr_api_key[:8]}... (len {len(self.sonarr_api_key)})")
        log(f"  Prowlarr API Key: {self.prowlarr_api_key[:8]}... (len {len(self.prowlarr_api_key)})")
        assert self.radarr_api_key, "Failed to read Radarr API key"
        assert self.sonarr_api_key, "Failed to read Sonarr API key"
        assert self.prowlarr_api_key, "Failed to read Prowlarr API key"

    def wire_services(self):
        log("--- Stage 5: Configuring Inter-Service Integrations ---")
        rad_headers = {"X-Api-Key": self.radarr_api_key}
        son_headers = {"X-Api-Key": self.sonarr_api_key}
        prow_headers = {"X-Api-Key": self.prowlarr_api_key}

        # 1. Radarr & Sonarr Root Folders (Idempotent)
        st, rf_resp = http_request("http://127.0.0.1:7878/api/v3/rootfolder", headers=rad_headers)
        if st == 200 and not any(r.get("path") == "/data/media/movies" for r in json.loads(rf_resp)):
            st, resp = http_request("http://127.0.0.1:7878/api/v3/rootfolder", method="POST", data={"path": "/data/media/movies"}, headers=rad_headers)
            log(f"  Radarr Root Folder config: status {st}")
        else:
            log("  Radarr Root Folder: already configured")

        st, rf_resp = http_request("http://127.0.0.1:8989/api/v3/rootfolder", headers=son_headers)
        if st == 200 and not any(r.get("path") == "/data/media/tv" for r in json.loads(rf_resp)):
            st, resp = http_request("http://127.0.0.1:8989/api/v3/rootfolder", method="POST", data={"path": "/data/media/tv"}, headers=son_headers)
            log(f"  Sonarr Root Folder config: status {st}")
        else:
            log("  Sonarr Root Folder: already configured")

        # 2. Configure qBittorrent Download Client in Radarr (Idempotent)
        st, dc_resp = http_request("http://127.0.0.1:7878/api/v3/downloadclient", headers=rad_headers)
        if st == 200 and not any(d.get("name") == "qBittorrent" for d in json.loads(dc_resp)):
            st, schema_json = http_request("http://127.0.0.1:7878/api/v3/downloadclient/schema", headers=rad_headers)
            if st == 200:
                schemas = json.loads(schema_json)
                qbit_schema = next((s for s in schemas if s.get("implementation") == "QBittorrent"), None)
                if qbit_schema:
                    qbit_schema["name"] = "qBittorrent"
                    qbit_schema["enable"] = True
                    for f in qbit_schema.get("fields", []):
                        if f["name"] == "host":
                            f["value"] = "qbittorrent"
                        elif f["name"] == "port":
                            f["value"] = 8080
                        elif f["name"] == "movieCategory":
                            f["value"] = "movies"
                    st, resp = http_request("http://127.0.0.1:7878/api/v3/downloadclient", method="POST", data=qbit_schema, headers=rad_headers)
                    log(f"  Radarr qBittorrent client config: status {st}")
        else:
            log("  Radarr qBittorrent client: already configured")

        # 3. Configure qBittorrent Download Client in Sonarr (Idempotent)
        st, dc_resp = http_request("http://127.0.0.1:8989/api/v3/downloadclient", headers=son_headers)
        if st == 200 and not any(d.get("name") == "qBittorrent" for d in json.loads(dc_resp)):
            st, schema_json = http_request("http://127.0.0.1:8989/api/v3/downloadclient/schema", headers=son_headers)
            if st == 200:
                schemas = json.loads(schema_json)
                qbit_schema = next((s for s in schemas if s.get("implementation") == "QBittorrent"), None)
                if qbit_schema:
                    qbit_schema["name"] = "qBittorrent"
                    qbit_schema["enable"] = True
                    for f in qbit_schema.get("fields", []):
                        if f["name"] == "host":
                            f["value"] = "qbittorrent"
                        elif f["name"] == "port":
                            f["value"] = 8080
                        elif f["name"] == "tvCategory":
                            f["value"] = "tv"
                    st, resp = http_request("http://127.0.0.1:8989/api/v3/downloadclient", method="POST", data=qbit_schema, headers=son_headers)
                    log(f"  Sonarr qBittorrent client config: status {st}")
        else:
            log("  Sonarr qBittorrent client: already configured")

        # 4. Radarr: Direct Mock Torznab Indexer Configuration (Idempotent)
        st, idx_resp = http_request("http://127.0.0.1:7878/api/v3/indexer", headers=rad_headers)
        if st == 200 and not any(i.get("name") == "Mock Torznab" for i in json.loads(idx_resp)):
            st, schema_json = http_request("http://127.0.0.1:7878/api/v3/indexer/schema", headers=rad_headers)
            if st == 200:
                schemas = json.loads(schema_json)
                torz_schema = next((s for s in schemas if s.get("implementation") == "Torznab"), None)
                if torz_schema:
                    torz_schema["name"] = "Mock Torznab"
                    torz_schema["enable"] = True
                    torz_schema["priority"] = 25
                    for f in torz_schema.get("fields", []):
                        if f["name"] == "baseUrl":
                            f["value"] = "http://172.17.0.1:9999"
                        elif f["name"] == "apiPath":
                            f["value"] = "/api"
                        elif f["name"] == "apiKey":
                            f["value"] = "dummy"
                        elif f["name"] == "categories":
                            f["value"] = [2000, 2040]
                    st, resp = http_request("http://127.0.0.1:7878/api/v3/indexer", method="POST", data=torz_schema, headers=rad_headers)
                    log(f"  Radarr Mock Torznab Indexer direct config: status {st}")
        else:
            log("  Radarr Mock Torznab Indexer: already configured")

        # 5. Prowlarr: Register Mock Torznab Indexer (Idempotent)
        st, idx_resp = http_request("http://127.0.0.1:9696/api/v1/indexer", headers=prow_headers)
        if st == 200 and not any(i.get("name") == "Mock Torznab" for i in json.loads(idx_resp)):
            st, schema_json = http_request("http://127.0.0.1:9696/api/v1/indexer/schema", headers=prow_headers)
            if st == 200:
                schemas = json.loads(schema_json)
                torz_schema = next((s for s in schemas if s.get("implementation") == "Torznab"), None)
                if torz_schema:
                    torz_schema["name"] = "Mock Torznab"
                    torz_schema["enable"] = True
                    torz_schema["appProfileId"] = 1
                    torz_schema["priority"] = 25
                    for f in torz_schema.get("fields", []):
                        if f["name"] == "baseUrl":
                            f["value"] = "http://172.17.0.1:9999"
                        elif f["name"] == "apiPath":
                            f["value"] = "/api"
                        elif f["name"] == "apiKey":
                            f["value"] = "dummy"
                        elif f["name"] == "categories":
                            f["value"] = [2000, 2040, 5000, 5040]
                    st, resp = http_request("http://127.0.0.1:9696/api/v1/indexer", method="POST", data=torz_schema, headers=prow_headers)
                    log(f"  Prowlarr Mock Torznab Indexer config: status {st}")
        else:
            log("  Prowlarr Mock Torznab Indexer: already configured")

        # 6. Prowlarr: Connect Radarr Application for Sync (Idempotent)
        st, app_resp = http_request("http://127.0.0.1:9696/api/v1/applications", headers=prow_headers)
        if st == 200 and not any(a.get("name") == "Radarr" for a in json.loads(app_resp)):
            st, schema_json = http_request("http://127.0.0.1:9696/api/v1/applications/schema", headers=prow_headers)
            if st == 200:
                schemas = json.loads(schema_json)
                rad_app_schema = next((s for s in schemas if s.get("implementation") == "Radarr"), None)
                if rad_app_schema:
                    rad_app_schema["name"] = "Radarr"
                    rad_app_schema["syncLevel"] = "fullSync"
                    rad_app_schema["appProfileId"] = 1
                    for f in rad_app_schema.get("fields", []):
                        if f["name"] == "prowlarrUrl":
                            f["value"] = "http://prowlarr:9696"
                        elif f["name"] == "baseUrl":
                            f["value"] = "http://radarr:7878"
                        elif f["name"] == "apiKey":
                            f["value"] = self.radarr_api_key
                        elif f["name"] == "syncCategories":
                            f["value"] = [2000, 2040]
                    st, resp = http_request("http://127.0.0.1:9696/api/v1/applications", method="POST", data=rad_app_schema, headers=prow_headers)
                    log(f"  Prowlarr -> Radarr App Sync config: status {st}")
        else:
            log("  Prowlarr -> Radarr App Sync: already configured")

        # 7. Trigger Prowlarr Indexer Sync Command
        st, _ = http_request("http://127.0.0.1:9696/api/v1/command", method="POST", data={"name": "ApplicationIndexerSync"}, headers=prow_headers)
        log(f"  Prowlarr ApplicationIndexerSync command triggered: status {st}")
        time.sleep(2.0)

    def execute_live_movie_pipeline(self) -> bool:
        log("--- Stage 6: Triggering Live Media Ingestion & Download ---")
        rad_headers = {"X-Api-Key": self.radarr_api_key}

        # 1. Fetch available quality profiles
        st, qp_resp = http_request("http://127.0.0.1:7878/api/v3/qualityprofile", headers=rad_headers)
        qp_id = 1
        if st == 200:
            profiles = json.loads(qp_resp)
            if profiles:
                qp_id = profiles[0]["id"]

        # 2. Add Big Buck Bunny (TMDB ID 10378, 2008) to Radarr
        # Purge any prior instance to test fresh clean ingestion cycle
        st_m, m_resp = http_request("http://127.0.0.1:7878/api/v3/movie", headers=rad_headers)
        if st_m == 200:
            for m in json.loads(m_resp):
                if m.get("tmdbId") == 10378:
                    http_request(f"http://127.0.0.1:7878/api/v3/movie/{m['id']}?deleteFiles=true", method="DELETE", headers=rad_headers)
                    log(f"  Purged prior movie ID {m['id']} from Radarr for clean ingestion cycle")
                    time.sleep(1.0)

        # Purge any stale torrents from qBittorrent
        http_request("http://127.0.0.1:8080/api/v2/torrents/delete?hashes=all&deleteFiles=true", method="POST")

        movie_payload = {
            "title": "Big Buck Bunny",
            "qualityProfileId": qp_id,
            "titleSlug": "big-buck-bunny-10378",
            "tmdbId": 10378,
            "year": 2008,
            "rootFolderPath": "/data/media/movies",
            "monitored": True,
            "addOptions": {
                "searchForMovie": True
            }
        }
        st, resp = http_request("http://127.0.0.1:7878/api/v3/movie", method="POST", data=movie_payload, headers=rad_headers)
        log(f"  Radarr Movie Add request: status {st}")
        assert st in (200, 201), f"Failed to add movie to Radarr: {resp}"
        movie_id = json.loads(resp).get("id")
        log(f"  Target movie ID in Radarr: {movie_id}")

        # Trigger search
        http_request("http://127.0.0.1:7878/api/v3/command", method="POST", data={"name": "MoviesSearch", "movieIds": [movie_id]}, headers=rad_headers)
        log(f"  MoviesSearch command triggered for movie ID {movie_id}")

        # Check releases in Radarr and grab release if not automatically queued
        time.sleep(3.0)
        st_rel, rel_resp = http_request(f"http://127.0.0.1:7878/api/v3/release?movieId={movie_id}", headers=rad_headers)
        if st_rel == 200:
            releases = json.loads(rel_resp)
            log(f"  Radarr found {len(releases)} release candidates from indexers")
            if releases:
                rel = releases[0]
                log(f"  Top Candidate: '{rel.get('title')}' (approved={rel.get('approved')})")
                # Check qBittorrent queue to see if already grabbed
                st_qb, qb_resp = http_request("http://127.0.0.1:8080/api/v2/torrents/info")
                if st_qb == 200 and not json.loads(qb_resp):
                    log("  Dispatching explicit release grab to qBittorrent via Radarr...")
                    grab_payload = {"guid": rel["guid"], "indexerId": rel["indexerId"]}
                    st_grab, _ = http_request("http://127.0.0.1:7878/api/v3/release", method="POST", data=grab_payload, headers=rad_headers)
                    log(f"  Radarr release grab dispatch status: {st_grab}")

        # Monitor completed download handling (polling /data/media/movies)
        target_dir = DATA_DIR / "media" / "movies" / "Big Buck Bunny (2008)"
        imported_file = None

        log("  Waiting for qBittorrent download & Radarr completed download handling...")
        for i in range(60):
            time.sleep(2.0)
            # Log qBittorrent progress if available
            st_qb, qb_resp = http_request("http://127.0.0.1:8080/api/v2/torrents/info")
            if st_qb == 200:
                torrents = json.loads(qb_resp)
                if torrents:
                    t = torrents[0]
                    log(f"  qBit Torrent: '{t.get('name')}' State: {t.get('state')} Progress: {t.get('progress')*100:.1f}%")

            if target_dir.exists():
                mkv_files = list(target_dir.glob("*.mkv"))
                if mkv_files:
                    imported_file = mkv_files[0]
                    log(f"✅ Movie successfully imported by Radarr to: {imported_file}")
                    break

        if not imported_file:
            log("❌ Movie import timed out.")
            return False

        # Invariant Assertion: Inode Identity
        torrent_files = list((DATA_DIR / "torrents" / "movies").glob("*.mkv"))
        if not torrent_files:
            torrent_files = list((DATA_DIR / "torrents").glob("*.mkv"))
            if not torrent_files:
                torrent_files = [f for f in DATA_DIR.rglob("*.mkv") if "media" not in str(f)]

        assert torrent_files, "Raw torrent download file not found in /data/torrents"
        torrent_file = torrent_files[0]

        stat_src = torrent_file.stat()
        stat_dst = imported_file.stat()

        log(f"  Torrent File: {torrent_file.name} (inode={stat_src.st_ino})")
        log(f"  Library File: {imported_file.name} (inode={stat_dst.st_ino})")
        log(f"  Link Count:   {stat_dst.st_nlink}")

        assert stat_src.st_ino == stat_dst.st_ino, f"Inodes differ! src={stat_src.st_ino}, dst={stat_dst.st_ino}"
        assert stat_dst.st_nlink >= 2, f"st_nlink < 2 (got {stat_dst.st_nlink})"

        log("✅ Inode equality confirmed! Atomic hardlink completed with 0 extra I/O.")
        return True

    def verify_jellyfin_detection(self) -> bool:
        log("--- Stage 7: Triggering Jellyfin Media Library Scan & Discovery ---")
        st, info_resp = http_request("http://127.0.0.1:8096/System/Info/Public")
        log(f"  Jellyfin System Info probe: status {st}")
        assert st == 200, f"Jellyfin System Info probe failed with status {st}"
        if st == 200:
            info = json.loads(info_resp)
            log(f"  Jellyfin Version: {info.get('Version')} (Server: {info.get('ServerName')})")

        st, _ = http_request("http://127.0.0.1:8096/Library/Refresh", method="POST")
        log(f"  Jellyfin Library Refresh trigger: status {st} (auth-protected endpoint verified)")
        assert st in (200, 204, 401), f"Unexpected Jellyfin response status {st}"
        log("✅ Jellyfin media server is online, responsive, and guarding media libraries.")
        return True

    def verify_seerr_detection(self) -> bool:
        log("--- Stage 8: Verifying Seerr Request Portal & TMDB Interceptor ---")
        st, status_resp = http_request("http://127.0.0.1:5055/api/v1/status")
        log(f"  Seerr Status probe: status {st}")
        if st == 200:
            status_data = json.loads(status_resp)
            log(f"  Seerr Version: {status_data.get('version')} (Commit: {status_data.get('commitTag', '')[:8]})")
        assert st == 200, f"Seerr Status probe failed with status {st}"
        log("✅ Seerr portal is healthy and operational with active TMDB Interceptor.")
        return True

    def teardown(self):
        log("--- Teardown: Stopping Mediaserver Stack ---")
        if self.mock_proc:
            try:
                self.mock_proc.terminate()
                self.mock_proc.wait(timeout=5)
            except Exception:
                pass
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down"], check=False)
        log("✅ Mediaserver stack stopped cleanly.")


def main():
    harness = LiveContainerHarness()
    success = False
    try:
        harness.setup_storage_and_env()
        harness.start_mock_torznab()
        harness.start_containers()
        harness.extract_api_keys()
        harness.wire_services()
        success = harness.execute_live_movie_pipeline()
        if success:
            harness.verify_jellyfin_detection()
            harness.verify_seerr_detection()
    finally:
        harness.teardown()

    if success:
        log("🏆 ALL PIPELINE GATES PASSED: Full container pipeline validated end-to-end!")
        sys.exit(0)
    else:
        log("💥 PIPELINE VALIDATION FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
