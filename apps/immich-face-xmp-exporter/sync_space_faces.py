#!/usr/bin/env python3
"""
Immich Shared Space Face Synchronizer
Automatically maps face groups into designated Immich Shared Spaces via the REST API.
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

IMMICH_URL = os.getenv("IMMICH_URL", "http://127.0.0.1:2283")
API_KEY = os.getenv("IMMICH_API_KEY", "YOUR_IMMICH_API_KEY")


def api_request(method, path, body=None, url_base=None, api_key=None):
    base = (url_base or IMMICH_URL).rstrip("/")
    key = api_key or API_KEY
    url = f"{base}/api{path}"
    headers = {
        "x-api-key": key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"HTTP Error {e.code} on {method} {path}: {err}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Connection error on {method} {path}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Immich Shared Space Face Synchronizer")
    parser.add_argument("--url", default=IMMICH_URL, help="Immich instance base URL (default: %(default)s)")
    parser.add_argument("--api-key", default=API_KEY, help="Immich API key (default: from IMMICH_API_KEY env)")
    args = parser.parse_args()

    print("Testing Immich API authentication...")
    me = api_request("GET", "/users/me", url_base=args.url, api_key=args.api_key)
    if me:
        print(f"Authenticated as: {me.get('name')} ({me.get('email')})")
    else:
        print("Failed to authenticate via API! Please verify IMMICH_API_KEY and IMMICH_URL.")
        sys.exit(1)

    print("\nListing Shared Spaces...")
    spaces = api_request("GET", "/shared-spaces", url_base=args.url, api_key=args.api_key)
    if not spaces:
        print("No spaces returned by API.")
        return

    for s in spaces:
        sid = s["id"]
        title = s.get("title", "Untitled")
        print(f"- Space: {title} (ID: {sid})")


if __name__ == "__main__":
    main()
