#!/usr/bin/env python3
"""
Helper for immich_backup_gdrive.sh (standard library only).

    backup_status.py status ...      write status.json atomically (0644), keep run history
    backup_status.py retention ...   decide which nightly dumps to keep or delete
    backup_status.py stats FILE...   print transfer totals parsed from rclone output (JSON)
    backup_status.py count-assets F  count photos/videos (not deleted) in a pg_dumpall .sql.gz
    backup_status.py restore-result  record a restore test in status.json

The Control Hub reads only status.json, so the dashboard never needs `sudo rclone`.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

HISTORY_LIMIT = 30
# Only files written by the nightly script. Anything else on the remote (for example a
# manual immich_db_backup_pre_migration.sql.gz) never matches and is never deleted.
DUMP_RE = re.compile(r"^immich_db_(\d{8})_(\d{6})\.sql\.gz$")

_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4, "PiB": 1024**5,
          "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "PB": 1000**5,
          "k": 1024, "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}
_BYTES_RE = re.compile(r"Transferred:\s+([\d.]+)\s*([KMGTP]?i?B)\s*/")
_FILES_RE = re.compile(r"Transferred:\s+(\d+)\s*/\s*\d+,")
_CHECKS_RE = re.compile(r"Checks:\s+(\d+)\s*/\s*\d+")
_DELETED_RE = re.compile(r"Deleted:\s+(\d+)\s*\(files\)")
_ERRORS_RE = re.compile(r"Errors:\s+(\d+)")


# ---------------------------------------------------------------- rclone stats

def parse_rclone_stats(text: str) -> Dict[str, int]:
    """Totals from the last stats block rclone printed (bytes, files, checks, deleted, errors)."""
    out = {"bytes": 0, "files": 0, "checks": 0, "deleted": 0, "errors": 0}
    for key, regex in (("files", _FILES_RE), ("checks", _CHECKS_RE), ("deleted", _DELETED_RE), ("errors", _ERRORS_RE)):
        found = regex.findall(text)
        if found:
            out[key] = int(found[-1])
    found = _BYTES_RE.findall(text)
    if found:
        value, unit = found[-1]
        out["bytes"] = int(float(value) * _UNITS.get(unit, 1))
    return out


def cmd_stats(args: argparse.Namespace) -> int:
    total = {"bytes": 0, "files": 0, "checks": 0, "deleted": 0, "errors": 0}
    for name in args.files:
        try:
            text = Path(name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, value in parse_rclone_stats(text).items():
            total[key] += value
    print(json.dumps(total))
    return 0


# ---------------------------------------------------------------- retention

def _dump_time(name: str) -> Optional[datetime]:
    m = DUMP_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def plan_retention(names: List[str], keep: int, monthly: int, protect: Optional[str] = None) -> Dict[str, List[str]]:
    """
    Keeps the newest `keep` nightly dumps plus the first dump of each of the newest
    `monthly` months. Names that are not nightly dumps are ignored (never deleted).
    """
    dated = sorted(((t, n) for n in set(names) if (t := _dump_time(n)) is not None), reverse=True)
    keep_set = {n for _, n in dated[: max(0, keep)]}
    if monthly > 0:
        first_of_month: Dict[str, tuple] = {}
        for t, n in dated:
            key = t.strftime("%Y-%m")
            if key not in first_of_month or t < first_of_month[key][0]:
                first_of_month[key] = (t, n)
        for key in sorted(first_of_month, reverse=True)[:monthly]:
            keep_set.add(first_of_month[key][1])
    if protect:
        keep_set.add(protect)
    kept = [n for _, n in dated if n in keep_set]
    delete = [n for _, n in dated if n not in keep_set]
    return {"keep": kept, "delete": sorted(delete)}


def cmd_retention(args: argparse.Namespace) -> int:
    names = [ln.strip() for ln in Path(args.names_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    names = [n.rsplit("/", 1)[-1] for n in names]
    result = plan_retention(names, args.keep, args.monthly, args.protect)
    # What the next nightly run would delete, so the dashboard can say so in advance.
    newest = max((t for n in result["keep"] if (t := _dump_time(n))), default=datetime.now())
    tomorrow = (newest + timedelta(days=1)).strftime("immich_db_%Y%m%d_%H%M%S.sql.gz")
    following = plan_retention(result["keep"] + [tomorrow], args.keep, args.monthly, tomorrow)
    summary = {
        "count_before": len([n for n in names if DUMP_RE.match(n)]),
        "kept": len(result["keep"]),
        "delete": result["delete"],
        "next_delete": following["delete"],
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary) + "\n", encoding="utf-8")
    for name in result["delete"]:
        print(name)
    return 0


# ---------------------------------------------------------------- restore test

def count_assets_in_dump(path: str, table: str = "public.asset") -> Optional[int]:
    """Rows of `table` whose "deletedAt" is NULL in a plain pg_dumpall file (.sql or .sql.gz)."""
    opener = gzip.open if str(path).endswith(".gz") else open
    header = f"COPY {table} ("
    count, deleted_idx, in_copy = 0, None, False
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not in_copy:
                if line.startswith(header):
                    cols = [c.strip().strip('"') for c in line[len(header):line.index(")")].split(",")]
                    deleted_idx = cols.index("deletedAt") if "deletedAt" in cols else None
                    in_copy = True
                continue
            if line.startswith("\\."):
                return count
            if deleted_idx is None:
                count += 1
            else:
                fields = line.rstrip("\n").split("\t")
                if len(fields) > deleted_idx and fields[deleted_idx] == "\\N":
                    count += 1
    return None


def cmd_count_assets(args: argparse.Namespace) -> int:
    n = count_assets_in_dump(args.dump)
    if n is None:
        print("asset table not found", file=sys.stderr)
        return 1
    print(n)
    return 0


def cmd_restore_result(a: argparse.Namespace) -> int:
    path = Path(a.file)
    data = _read_json(str(path))
    data = data if isinstance(data, dict) else {}
    entry = {
        "ok": a.result == "ok", "message": a.message, "started_at": a.started_at, "completed_at": a.completed_at,
        "dump_file": a.dump_file or None,
        "expected": int(a.expected) if (a.expected or "").isdigit() else None,
        "restored": int(a.restored) if (a.restored or "").isdigit() else None,
        "duration_s": _duration(a.started_at, a.completed_at),
    }
    data["restore_test"] = entry
    data["restore_history"] = ([entry] + list(data.get("restore_history") or []))[:12]
    write_atomic(path, data)
    return 0


# ---------------------------------------------------------------- status.json

def _read_json(path: Optional[str]):
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_preflight(path: Optional[str]) -> Optional[dict]:
    if not path or not Path(path).exists():
        return None
    checks = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            checks.append({"name": parts[0], "ok": parts[1] == "ok", "detail": parts[2]})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _duration(started: Optional[str], completed: Optional[str]) -> Optional[int]:
    try:
        return int((datetime.fromisoformat(completed) - datetime.fromisoformat(started)).total_seconds())
    except (TypeError, ValueError):
        return None


def build_status(prev: dict, a: argparse.Namespace) -> dict:
    gdrive = None
    about = _read_json(a.gdrive_json)
    if isinstance(about, dict) and about.get("total"):
        gdrive = {"total_bytes": about.get("total"), "used_bytes": about.get("used"), "free_bytes": about.get("free")}
    if gdrive is None and isinstance(prev.get("gdrive"), dict):
        gdrive = prev["gdrive"]

    final = a.status in ("synced", "error")
    last_good = a.completed_at if a.status == "synced" and a.completed_at else prev.get("last_good_at")
    same_run = prev.get("started_at") == a.started_at
    transfer = _read_json(a.transfer_json) or (prev.get("transfer") if same_run else None)
    preflight = _read_preflight(a.preflight_file) or (prev.get("preflight") if same_run else None)
    retention = _read_json(a.retention_json) or prev.get("retention")

    history = list(prev.get("history") or [])
    if not history and prev.get("status") in ("synced", "error") and prev.get("started_at"):
        # status.json written before run history existed: keep that run as the first entry.
        history.append({
            "started_at": prev.get("started_at"), "completed_at": prev.get("completed_at"),
            "outcome": prev.get("status"), "message": prev.get("message"),
            "dump_file": prev.get("dump_file"), "dump_bytes": prev.get("dump_bytes"),
            "files": None, "bytes": None, "duration_s": _duration(prev.get("started_at"), prev.get("completed_at")),
        })

    dump_bytes = int(a.dump_bytes) if (a.dump_bytes or "").isdigit() else None
    payload = {
        "status": a.status,
        "stage": int(a.stage),
        "stage_label": a.label,
        "message": a.message,
        "started_at": a.started_at,
        "completed_at": a.completed_at or None,
        "last_good_at": last_good,
        "remote": a.remote,
        "dump_file": a.dump_file or prev.get("dump_file"),
        "dump_bytes": dump_bytes if dump_bytes is not None else prev.get("dump_bytes"),
        "gdrive": gdrive,
        "preflight": preflight,
        "transfer": transfer,
        "retention": retention,
        "history": history,
        # Written by the monthly restore test; kept across backup runs.
        "restore_test": prev.get("restore_test"),
        "restore_history": prev.get("restore_history") or [],
    }
    if final:
        entry = {
            "started_at": a.started_at, "completed_at": a.completed_at or None, "outcome": a.status,
            "message": a.message, "dump_file": a.dump_file or None, "dump_bytes": dump_bytes,
            "files": (transfer or {}).get("files"), "bytes": (transfer or {}).get("bytes"),
            "duration_s": _duration(a.started_at, a.completed_at),
        }
        history = [h for h in history if h.get("started_at") != a.started_at]
        payload["history"] = ([entry] + history)[:HISTORY_LIMIT]
    return payload


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def cmd_status(a: argparse.Namespace) -> int:
    path = Path(a.file)
    prev = _read_json(str(path))
    write_atomic(path, build_status(prev if isinstance(prev, dict) else {}, a))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="write status.json")
    s.add_argument("--file", required=True)
    s.add_argument("--status", required=True, choices=["syncing", "synced", "error"])
    s.add_argument("--stage", required=True)
    s.add_argument("--label", default="")
    s.add_argument("--message", default="")
    s.add_argument("--started-at", required=True)
    s.add_argument("--completed-at", default="")
    s.add_argument("--remote", default="")
    s.add_argument("--dump-file", default="")
    s.add_argument("--dump-bytes", default="")
    s.add_argument("--gdrive-json", help="file with `rclone about --json` output")
    s.add_argument("--transfer-json", help="file with `backup_status.py stats` output")
    s.add_argument("--preflight-file", help="tab-separated lines: name, ok|fail, detail")
    s.add_argument("--retention-json", help="file written by `backup_status.py retention --json-out`")
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("retention", help="print the dumps to delete, one per line")
    r.add_argument("--names-file", required=True)
    r.add_argument("--keep", type=int, required=True)
    r.add_argument("--monthly", type=int, default=0)
    r.add_argument("--protect", help="never delete this name (the dump just uploaded)")
    r.add_argument("--json-out")
    r.set_defaults(func=cmd_retention)

    c = sub.add_parser("count-assets", help="count photos/videos (not deleted) in a pg_dumpall file")
    c.add_argument("dump")
    c.set_defaults(func=cmd_count_assets)

    rr = sub.add_parser("restore-result", help="record a restore test in status.json")
    rr.add_argument("--file", required=True)
    rr.add_argument("--result", required=True, choices=["ok", "fail"])
    rr.add_argument("--message", default="")
    rr.add_argument("--started-at", required=True)
    rr.add_argument("--completed-at", default="")
    rr.add_argument("--dump-file", default="")
    rr.add_argument("--expected", default="")
    rr.add_argument("--restored", default="")
    rr.set_defaults(func=cmd_restore_result)

    t = sub.add_parser("stats", help="sum transfer totals from rclone output files")
    t.add_argument("files", nargs="+")
    t.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
