#!/usr/bin/env python3
"""
Homelab Blueprint - Zero-Dependency Mock Torznab Indexer & Web Seed Server
Serves:
  1. Torznab XML Feed (/api?t=caps & /api?t=movie/search)
  2. Compliant BitTorrent .torrent payload with BEP 19 Web Seeding
  3. HTTP Range-capable Web Seed media streamer (/media/...)
  4. Minimal BitTorrent HTTP Tracker (/announce)
Runs using only the Python standard library.
"""

import hashlib
import json
import math
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Ensure UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
DUMMY_MEDIA_PATH = FIXTURES_DIR / "dummy_movie.mkv"
TORRENT_NAME = "Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-MOCK.mkv"
TV_TORRENT_NAME = "Cosmos.Laundromat.S01E01.1080p.WEBDL.AAC2.0.H.264-MOCK.mkv"


def bencode(val) -> bytes:
    """Encodes Python data structure into standard BitTorrent Bencode format"""
    if isinstance(val, int):
        return f"i{val}e".encode("ascii")
    elif isinstance(val, str):
        b = val.encode("utf-8")
        return f"{len(b)}:".encode("ascii") + b
    elif isinstance(val, bytes):
        return f"{len(val)}:".encode("ascii") + val
    elif isinstance(val, list):
        b = b"".join(bencode(x) for x in val)
        return b"l" + b + b"e"
    elif isinstance(val, dict):
        return b"d" + b"".join(bencode(k) + bencode(val[k]) for k in sorted(val.keys())) + b"e"
    raise TypeError(f"Bencode unsupported type: {type(val)}")


def get_media_bytes() -> bytes:
    """Loads dummy media bytes, generating file on-the-fly if missing or stale"""
    if not DUMMY_MEDIA_PATH.exists() or DUMMY_MEDIA_PATH.stat().st_size > 4 * 1024 * 1024:
        if str(FIXTURES_DIR) not in sys.path:
            sys.path.insert(0, str(FIXTURES_DIR))
        from generate_dummy_mkv import generate_with_ffmpeg, generate_synthesized_mkv
        if not generate_with_ffmpeg(DUMMY_MEDIA_PATH):
            generate_synthesized_mkv(DUMMY_MEDIA_PATH)
    return DUMMY_MEDIA_PATH.read_bytes()


def build_torrent_dict(host: str, port: int, media_bytes: bytes, filename: str = TORRENT_NAME) -> dict:
    """Builds a complete BEP 19 compliant torrent dictionary with web seeding"""
    piece_length = 262144  # 256 KiB
    pieces = bytearray()
    for offset in range(0, len(media_bytes), piece_length):
        chunk = media_bytes[offset:offset + piece_length]
        pieces.extend(hashlib.sha1(chunk).digest())

    info_dict = {
        "name": filename,
        "length": len(media_bytes),
        "piece length": piece_length,
        "pieces": bytes(pieces),
    }

    # Base dictionary
    torrent = {
        "announce": f"http://{host}:{port}/announce",
        "created by": "Homelab Blueprint Mock Torznab 1.0",
        "creation date": int(time.time()),
        "info": info_dict,
        # BEP 19: GetRight style Web Seed url-list
        "url-list": f"http://{host}:{port}/media/{filename}",
    }
    return torrent


def compute_info_hash(info_dict: dict) -> str:
    """Calculates 40-character hex SHA-1 infohash of torrent info dictionary"""
    bencoded_info = bencode(info_dict)
    return hashlib.sha1(bencoded_info).hexdigest()


class MockTorznabHandler(BaseHTTPRequestHandler):
    """Handles Torznab queries, torrent downloads, web seeding, and tracker announces"""

    server_version = "MockTorznab/1.0"

    def log_message(self, format, *args):
        # Concise logging
        sys.stderr.write(f"[MockTorznab] {self.client_address[0]} - {args[0]} {args[1]}\n")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        host_header = self.headers.get("Host", "127.0.0.1:9999")
        if ":" in host_header:
            host, port = host_header.split(":", 1)
            port = int(port)
        else:
            host, port = host_header, 9999

        media_bytes = get_media_bytes()
        media_size = len(media_bytes)

        movie_torrent = build_torrent_dict(host, port, media_bytes, TORRENT_NAME)
        movie_hash = compute_info_hash(movie_torrent["info"])

        tv_torrent = build_torrent_dict(host, port, media_bytes, TV_TORRENT_NAME)
        tv_hash = compute_info_hash(tv_torrent["info"])

        # 1. Health / Ready Probes
        if path in ("/health", "/readyz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready", "service": "mock_torznab"}).encode("utf-8"))
            return

        # 2. Torznab API (/api or /torznab/api)
        if path in ("/api", "/torznab/api", "/torznab"):
            t_mode = query.get("t", [""])[0]

            if t_mode == "caps":
                caps_xml = """<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server version="1.0" title="MockTorznab" />
  <searching>
    <search available="yes" supportedParams="q" />
    <tv-search available="yes" supportedParams="q,season,ep,imdbid,tvdbid,rid" />
    <movie-search available="yes" supportedParams="q,imdbid,tmdbid" />
  </searching>
  <categories>
    <category id="2000" name="Movies">
      <subcat id="2040" name="Movies/HD" />
      <subcat id="2045" name="Movies/UHD" />
    </category>
    <category id="5000" name="TV">
      <subcat id="5030" name="TV/SD" />
      <subcat id="5040" name="TV/HD" />
      <subcat id="5045" name="TV/UHD" />
    </category>
  </categories>
</caps>"""
                body = caps_xml.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            else:
                movie_item = f"""    <item>
      <title>Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-MOCK</title>
      <guid>mock-bbb-2008-1080p</guid>
      <link>http://{host}:{port}/download/big_buck_bunny.torrent</link>
      <comments>http://{host}:{port}/details/mock-bbb</comments>
      <pubDate>Sun, 01 Nov 2026 12:00:00 +0000</pubDate>
      <size>{media_size}</size>
      <enclosure url="http://{host}:{port}/download/big_buck_bunny.torrent" length="{media_size}" type="application/x-bittorrent" />
      <torznab:attr name="category" value="2000" />
      <torznab:attr name="category" value="2040" />
      <torznab:attr name="imdbid" value="10378" />
      <torznab:attr name="tmdbid" value="10378" />
      <torznab:attr name="seeders" value="100" />
      <torznab:attr name="peers" value="105" />
      <torznab:attr name="infohash" value="{movie_hash}" />
      <torznab:attr name="downloadvolumefactor" value="0" />
      <torznab:attr name="uploadvolumefactor" value="1" />
    </item>"""

                tv_item = f"""    <item>
      <title>Cosmos.Laundromat.S01E01.1080p.WEBDL.AAC2.0.H.264-MOCK</title>
      <guid>mock-cosmos-s01e01-1080p</guid>
      <link>http://{host}:{port}/download/cosmos_laundromat.torrent</link>
      <comments>http://{host}:{port}/details/mock-cosmos</comments>
      <pubDate>Sun, 01 Nov 2026 12:00:00 +0000</pubDate>
      <size>{media_size}</size>
      <enclosure url="http://{host}:{port}/download/cosmos_laundromat.torrent" length="{media_size}" type="application/x-bittorrent" />
      <torznab:attr name="category" value="5000" />
      <torznab:attr name="category" value="5040" />
      <torznab:attr name="season" value="1" />
      <torznab:attr name="episode" value="1" />
      <torznab:attr name="seeders" value="100" />
      <torznab:attr name="peers" value="105" />
      <torznab:attr name="infohash" value="{tv_hash}" />
      <torznab:attr name="downloadvolumefactor" value="0" />
      <torznab:attr name="uploadvolumefactor" value="1" />
    </item>"""

                cats = query.get("cat", [""])[0].split(",") if "cat" in query else []
                items = []

                if t_mode == "tvsearch" or any(c.startswith("5") for c in cats):
                    items.append(tv_item)
                elif t_mode == "movie" or any(c.startswith("2") for c in cats):
                    items.append(movie_item)
                else:
                    # Generic search: return both
                    items.append(movie_item)
                    items.append(tv_item)

                items_xml = "\n".join(items)
                rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>MockTorznab</title>
    <description>Homelab Blueprint Offline Mock Indexer</description>
{items_xml}
  </channel>
</rss>"""
                body = rss_xml.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        # 3. Torrent File Download
        if path.startswith("/download"):
            if "cosmos" in path.lower() or "tv" in path.lower():
                torrent_to_send = tv_torrent
                send_name = TV_TORRENT_NAME
            else:
                torrent_to_send = movie_torrent
                send_name = TORRENT_NAME

            torrent_payload = bencode(torrent_to_send)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-bittorrent")
            self.send_header("Content-Disposition", f'attachment; filename="{send_name}.torrent"')
            self.send_header("Content-Length", str(len(torrent_payload)))
            self.end_headers()
            self.wfile.write(torrent_payload)
            return

        # 4. Web Seed Direct File Streaming (supports Range requests for fast block fetching)
        if path.startswith("/media/"):
            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                # Format: bytes=START-END
                byte_range = range_header.split("=", 1)[1]
                parts = byte_range.split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if parts[1] else (media_size - 1)
                end = min(end, media_size - 1)
                chunk_len = (end - start) + 1

                self.send_response(206)  # Partial Content
                self.send_header("Content-Type", "video/x-matroska")
                self.send_header("Content-Range", f"bytes {start}-{end}/{media_size}")
                self.send_header("Content-Length", str(chunk_len))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(media_bytes[start:end + 1])
                return
            else:
                self.send_response(200)
                self.send_header("Content-Type", "video/x-matroska")
                self.send_header("Content-Length", str(media_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(media_bytes)
                return

        # 5. Tracker Announce (libtorrent HTTP tracker protocol)
        if path.startswith("/announce"):
            # Return bencoded tracker dictionary with 0 compact peers (client uses web seed)
            tracker_resp = {
                "interval": 1800,
                "min interval": 300,
                "complete": 100,
                "incomplete": 0,
                "peers": b"",  # 0 binary compact peers; triggers webseed
            }
            body = bencode(tracker_resp)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 404 Fallback
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404 Not Found")


def run_mock_server(host: str = "0.0.0.0", port: int = 9999):
    """Starts the Mock Torznab and Web Seed HTTP daemon"""
    # Pre-generate dummy media if not existing
    get_media_bytes()

    server = HTTPServer((host, port), MockTorznabHandler)
    print(f"📡 Mock Torznab & Web Seed Server listening on http://{host}:{port}")
    print(f"  * Torznab API:    http://{host}:{port}/api?t=caps")
    print(f"  * Torrent URL:    http://{host}:{port}/download/big_buck_bunny.torrent")
    print(f"  * Web Seed Media: http://{host}:{port}/media/{TORRENT_NAME}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Mock Torznab Server terminated.")
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Homelab Blueprint Mock Torznab & Web Seed Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9999, help="Port to bind (default 9999)")
    args = parser.parse_args()
    run_mock_server(args.host, args.port)

