#!/usr/bin/env python3
"""
Checks the TRaSH Guides custom formats vendored in profiles/trash/ against upstream.

    python3 scripts/trash_sync.py --check   # exit 1 when any vendored file differs upstream
    python3 scripts/trash_sync.py --write   # update the files and the commit in pack.json

The weekly workflow (.github/workflows/trash-sync.yml in homelab-blueprint) runs --write
and opens a pull request when something changed, so upstream changes arrive reviewed,
like dependency updates. A file whose trash_id changed or that disappeared upstream is
reported and left alone. TRaSH Guides is MIT-licensed (profiles/trash/LICENSE).
Standard library only.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

PACK_DIR = Path(__file__).resolve().parent.parent / "profiles"
RAW = "https://raw.githubusercontent.com/TRaSH-Guides/Guides/{ref}/{path}"
COMMITS = "https://api.github.com/repos/TRaSH-Guides/Guides/commits/{ref}"
USER_AGENT = "homelab-mediaserver-trash-sync"


def fetch(url: str, timeout: int = 30) -> Tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def upstream_commit(ref: str) -> Optional[str]:
    status, body = fetch(COMMITS.format(ref=ref))
    if status != 200:
        return None
    try:
        return json.loads(body.decode("utf-8"))["sha"]
    except (ValueError, KeyError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare vendored TRaSH custom formats with upstream")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Report differences; exit 1 when any")
    mode.add_argument("--write", action="store_true", help="Update changed files and pack.json")
    parser.add_argument("--ref", default="master", help="Upstream branch or commit (default master)")
    parser.add_argument("--pack-dir", default=str(PACK_DIR))
    args = parser.parse_args()

    pack_dir = Path(args.pack_dir)
    meta_path = pack_dir / "pack.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    commit = upstream_commit(args.ref) or args.ref
    changed, problems = [], []
    for rel, info in meta["trash"]["vendored"].items():
        status, body = fetch(RAW.format(ref=commit, path=info["source"]))
        if status != 200:
            problems.append(f"{rel}: upstream {info['source']} -> HTTP {status}")
            continue
        try:
            upstream = json.loads(body.decode("utf-8"))
        except ValueError:
            problems.append(f"{rel}: upstream file is not JSON")
            continue
        if upstream.get("trash_id") != info["trash_id"]:
            problems.append(f"{rel}: trash_id changed upstream ({info['trash_id']} -> {upstream.get('trash_id')}); review by hand")
            continue
        local = pack_dir / "trash" / rel
        if local.read_bytes() != body:
            changed.append(rel)
            if args.write:
                local.write_bytes(body)

    for rel in changed:
        print(f"changed upstream: {rel}")
    for p in problems:
        print(f"problem: {p}", file=sys.stderr)
    if args.write and changed and commit != meta["trash"]["commit"]:
        meta["trash"]["commit"] = commit
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"pack.json: TRaSH commit -> {commit}")
    if not changed and not problems:
        print(f"vendored TRaSH formats match upstream ({commit[:12]})")
    if problems:
        return 2
    return 1 if (changed and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
