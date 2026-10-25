#!/usr/bin/env python3
"""
Immich Shared Space Face Synchronizer
Automatically maps face groups into designated Immich Shared Spaces via the REST API.
"""

import os
import json
import urllib.request
import urllib.error

IMMICH_URL = os.getenv("IMMICH_URL", "http://127.0.0.1:2283")
API_KEY = os.getenv("IMMICH_API_KEY", "YOUR_IMMICH_API_KEY")


def api_request(method, path, body=None):
    url = f"{IMMICH_URL}/api{path}"
    headers = {
        "x-api-key": API_KEY,
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
        print(f"HTTP Error {e.code} on {method} {path}: {err}")
        return None


def main():
    print("Testing Immich API authentication...")
    me = api_request("GET", "/users/me")
    if me:
        print(f"Authenticated as: {me.get('name')} ({me.get('email')})")
    else:
        print("Failed to authenticate via API! Please verify IMMICH_API_KEY and IMMICH_URL.")
        exit(1)

    print("\nListing Shared Spaces...")
    spaces = api_request("GET", "/shared-spaces")
    if not spaces:
        print("No spaces returned by API.")
        return

    for s in spaces:
        sid = s["id"]
        title = s.get("title", "Untitled")
        print(f"- Space: {title} (ID: {sid})")


if __name__ == "__main__":
    main()
