#!/usr/bin/env python3
"""
Download Doctor: finds downloads that will never finish and replaces them through
Radarr/Sonarr, so the apps blocklist the dead release and pick the next-best one.

Jobs (`--job`, comma list):
  stuck  every 10 minutes. Strikes per torrent, counted in awake time, persisted in
         state.json. A torrent past its patience is removed through the app's queue
         (remove from client + blocklist + search again), never in qBittorrent directly.
  sweep  daily. Searches up to 10 "cutoff unmet" titles (dual-audio and compact
         upgrades), oversized ones first, none searched in the last 14 days.
  prune  monthly. Deletes blocklist entries older than 60 days for titles that are
         still missing: dead swarms do revive.

Safety: only torrents that a Radarr/Sonarr queue owns, in that app's category; never
completed or seeding ones; `keep` tag and private torrents skipped; no strikes while
qBittorrent is offline, DHT is thin or within 30 minutes of wake-up; a circuit breaker
when most torrents turn bad at once; at most 3 replacements per run and 15 per day;
three replacements of one title in 7 days mark it "needs attention" and stop. Watch-only
for the first 7 days: every decision is logged as "would ..." and nothing changes.

Media pipeline plan section 8; docs/DOWNLOAD_DOCTOR.md. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_import import ArrClient, read_api_key_from_config  # noqa: E402
from wire_arr import QBit, jloads, read_env_file  # noqa: E402

HOUR = 3600
DAY = 24 * HOUR
CHECK_CAP = 15 * 60          # one check counts at most 15 minutes of awake time
WAKE_GAP = 25 * 60           # a longer gap between checks means the server slept
WAKE_GRACE = 30 * 60         # no strikes this long after waking
MIN_DHT_NODES = 50
NEW_BYTES = 1 << 20          # progress that resets the strikes
SEEDING_STATES = {"uploading", "stalledUP", "pausedUP", "stoppedUP", "queuedUP", "forcedUP", "checkingUP"}
DEFAULT_CATEGORIES = {"radarr": "radarr", "sonarr": "tv-sonarr"}
PERMANENT_IMPORT_PHRASES = ("no files found are eligible", "sample", "no audio tracks")

# reason -> (patience, action). Patience is awake seconds in the bad state.
RULES: Dict[str, Tuple[int, str]] = {
    "metadata": (2 * HOUR, "replace"),          # stuck fetching metadata, size 0
    "dead": (12 * HOUR, "replace"),             # stalled, availability < 1: pieces exist nowhere
    "stalled": (12 * HOUR, "replace"),          # stalled but a full copy is reachable: re-announce at 1 h
    "crawling": (24 * HOUR, "replace"),         # more than 3 days left
    "client_error": (1 * HOUR, "remove"),       # error / missingFiles: remove without blocklist, search
    "import_blocked": (6 * HOUR, "replace"),    # finished, but the app can never import it
    "queued": (24 * HOUR, "alert"),             # a configuration problem, not a bad release
}
REANNOUNCE_AFTER = 1 * HOUR
CRAWL_ETA = 3 * DAY
LIMIT_PER_RUN = 3
LIMIT_PER_DAY = 15
ITEM_CAP, ITEM_WINDOW = 3, 7 * DAY
BREAKER_SHARE, BREAKER_MIN = 0.6, 5
SWEEP_PER_DAY, SWEEP_REPEAT = 10, 14 * DAY
OVERSIZED_MB_PER_MIN = {"radarr": 55, "sonarr": 30}
PRUNE_AGE = 60 * DAY


# ------------------------------------------------------------------ helpers
def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def parse_ts(value: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def write_json(path: Path, data: Any, mode: int = 0o644) -> None:
    """Atomic write: a crash or power cut never leaves a half-written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def permanent_import_block(record: Dict[str, Any]) -> bool:
    if str(record.get("trackedDownloadState") or "").lower() != "importblocked":
        return False
    texts = []
    for block in record.get("statusMessages") or []:
        if isinstance(block, dict):
            texts.append(str(block.get("title") or ""))
            texts += [str(m) for m in block.get("messages") or []]
    combined = " ".join(texts).lower()
    return any(p in combined for p in PERMANENT_IMPORT_PHRASES)


def classify(t: Dict[str, Any], record: Dict[str, Any]) -> Optional[str]:
    """The bad state a managed torrent is in, or None when it is healthy (section 8.2)."""
    if permanent_import_block(record):
        return "import_blocked"
    state = str(t.get("state") or "")
    if float(t.get("progress") or 0) >= 1 or state in SEEDING_STATES:
        return None
    if state in ("error", "missingFiles"):
        return "client_error"
    if state in ("metaDL", "forcedMetaDL") or t.get("has_metadata") is False:
        return "metadata"
    if state == "queuedDL":
        return "queued"
    speed = int(t.get("dlspeed") or 0)
    if state == "stalledDL" or (state in ("downloading", "forcedDL") and speed == 0):
        return "stalled" if float(t.get("availability") or 0) >= 1 else "dead"
    if state in ("downloading", "forcedDL") and int(t.get("eta") or 0) > CRAWL_ETA and float(t.get("progress") or 0) < 0.9:
        return "crawling"
    return None


def item_key(app: str, record: Dict[str, Any]) -> str:
    if app == "radarr":
        return f"radarr:movie:{record.get('movieId')}"
    return f"sonarr:series:{record.get('seriesId')}:season:{record.get('seasonNumber')}"


# ------------------------------------------------------------------ clients
class QbitApi:
    """The three qBittorrent calls the Doctor needs, over wire_arr's cookie-login client."""

    def __init__(self, host: str, user: str, password: str):
        self.client = QBit(host, user, password)
        self.ready, self.detail = self.client.login(attempts=2)

    def torrents(self) -> Optional[List[Dict[str, Any]]]:
        st, body = self.client._get("/api/v2/torrents/info")
        data = jloads(body, None) if st == 200 else None
        return data if isinstance(data, list) else None

    def transfer(self) -> Dict[str, Any]:
        st, body = self.client._get("/api/v2/transfer/info")
        data = jloads(body, {}) if st == 200 else {}
        return data if isinstance(data, dict) else {}

    def reannounce(self, torrent_hash: str) -> bool:
        st, _ = self.client._form("/api/v2/torrents/reannounce", {"hashes": torrent_hash})
        return st == 200


def arr_category(arr: ArrClient, app: str) -> str:
    """The category the app's qBittorrent download client uses (movieCategory / tvCategory)."""
    st, clients = arr.request_json("/api/v3/downloadclient")
    field = "movieCategory" if app == "radarr" else "tvCategory"
    if st == 200 and isinstance(clients, list):
        for c in clients:
            if str(c.get("implementation") or "").lower() != "qbittorrent" or not c.get("enable", True):
                continue
            for f in c.get("fields") or []:
                if f.get("name") == field and f.get("value"):
                    return str(f["value"])
    return DEFAULT_CATEGORIES[app]


def arr_queue(arr: ArrClient, app: str) -> Optional[List[Dict[str, Any]]]:
    unknown = "includeUnknownMovieItems" if app == "radarr" else "includeUnknownSeriesItems"
    st, data = arr.request_json(f"/api/v3/queue?page=1&pageSize=1000&{unknown}=false")
    if st != 200 or not isinstance(data, dict):
        return None
    return [r for r in data.get("records") or [] if isinstance(r, dict)]


# ------------------------------------------------------------------ doctor
class Doctor:
    def __init__(self, qbit: Any, arrs: Dict[str, Any], state_dir: Path, *, now: Callable[[], float] = time.time,
                 watch_days: float = 7, dry_run: bool = False, enabled: bool = True,
                 logger: Optional[logging.Logger] = None):
        self.qbit, self.arrs, self.dir = qbit, arrs, Path(state_dir)
        self.now = now()
        self.dry_run, self.enabled = dry_run, enabled
        self.log = logger or logging.getLogger("mediaserver.download_doctor")
        self.state = read_json(self.dir / "state.json", {})
        self.state.setdefault("created", self.now)
        for key, empty in (("torrents", {}), ("history", []), ("searched", {}), ("healthy", []), ("alerts", [])):
            self.state.setdefault(key, empty)
        self.overrides = read_json(self.dir / "overrides.json", {})
        self.watch_until = self.state["created"] + watch_days * DAY
        self.watch_only = dry_run or self.now < self.watch_until
        self.calls: List[Dict[str, Any]] = []   # what this run did or would do (status + tests)

    # ---------------------------------------------------------------- common
    @property
    def mode(self) -> str:
        if not self.enabled:
            return "off"
        if self.dry_run:
            return "dry-run"
        return "watch-only" if self.watch_only else "active"

    def audit(self, entry: Dict[str, Any]) -> None:
        entry = dict(entry, ts=iso(self.now), mode=self.mode)
        self.calls.append(entry)
        self.dir.mkdir(parents=True, exist_ok=True)
        log = self.dir / "actions.jsonl"
        if log.exists() and log.stat().st_size > 1_048_576:  # keep one older file
            os.replace(log, self.dir / "actions.jsonl.1")
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        self.log.info("%s %s: %s (%s)", entry.get("action"), entry.get("app", ""), entry.get("title", ""), entry.get("reason", ""))

    def save(self, status: Dict[str, Any]) -> None:
        self.state["last_run"] = self.now
        self.state["history"] = [h for h in self.state["history"] if self.now - h["ts"] < 30 * DAY]
        self.state["searched"] = {k: v for k, v in self.state["searched"].items() if self.now - v < 2 * SWEEP_REPEAT}
        previous = read_json(self.dir / "status.json", {})
        status = dict({k: previous[k] for k in ("sweep", "prune") if k in previous}, **status)
        write_json(self.dir / "state.json", self.state)
        write_json(self.dir / "status.json", status)

    def _recent(self, window: float, key: Optional[str] = None) -> List[Dict[str, Any]]:
        return [h for h in self.state["history"] if self.now - h["ts"] < window and (key is None or h["key"] == key)]

    # ----------------------------------------------------------------- stuck
    def grace_reason(self, transfer: Dict[str, Any]) -> Optional[str]:
        last = self.state.get("last_run")
        if last is None or self.now - last > WAKE_GAP:
            self.state["wake_at"] = self.now
        if self.now - self.state.get("wake_at", 0) < WAKE_GRACE:
            return "just woke up (30-minute grace)"
        if transfer.get("connection_status") != "connected":
            return f"qBittorrent is {transfer.get('connection_status') or 'unreachable'}"
        if int(transfer.get("dht_nodes") or 0) < MIN_DHT_NODES:
            return f"only {int(transfer.get('dht_nodes') or 0)} DHT nodes"
        return None

    def managed(self, torrents: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Tuple[str, List[Dict[str, Any]]]], List[str]]:
        """Torrents an app owns: (torrents by hash, hash -> (app, queue records)), plus problems."""
        owned: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}
        problems = []
        for app, arr in self.arrs.items():
            queue = arr_queue(arr, app)
            if queue is None:
                problems.append(f"{app} queue unreadable")
                continue
            category = arr_category(arr, app)
            by_hash = {str(t.get("hash", "")).upper(): t for t in torrents if t.get("category") == category}
            for rec in queue:
                h = str(rec.get("downloadId") or "").upper()
                if h in by_hash and str(rec.get("protocol") or "torrent") == "torrent":
                    owned.setdefault(h, (app, []))[1].append(rec)
        by_hash_all = {str(t.get("hash", "")).upper(): t for t in torrents}
        return {h: by_hash_all[h] for h in owned}, owned, problems

    def run_stuck(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {"job": "stuck", "mode": self.mode, "updated": iso(self.now),
                                  "watch_only_until": iso(self.watch_until), "problems": [], "grace": None,
                                  "breaker": False, "managed": 0, "errors": []}
        if not self.enabled:
            status["grace"] = "switched off (MEDIA_STUCK_DOWNLOADS=off)"
            self.save(self._finish(status))
            return status
        torrents = self.qbit.torrents() if getattr(self.qbit, "ready", True) else None
        if torrents is None:
            status["errors"].append(f"qBittorrent unreachable: {getattr(self.qbit, 'detail', '')}".strip())
            self.save(self._finish(status))
            return status
        transfer = self.qbit.transfer()
        grace = self.grace_reason(transfer)
        last = self.state.get("last_run")
        step = 0 if grace or last is None else min(self.now - last, CHECK_CAP)
        by_hash, owned, errors = self.managed(torrents)
        status["errors"] += errors
        status["managed"] = len(by_hash)
        protect = {h.upper() for h in self.overrides.get("protect", [])}

        seen: Dict[str, Dict[str, Any]] = {}
        bad_now, healthy_now = set(), []
        for h, t in by_hash.items():
            app, records = owned[h]
            title = records[0].get("title") or t.get("name") or h
            tags = {x.strip().lower() for x in str(t.get("tags") or "").split(",")}
            if "keep" in tags or h in protect:
                continue
            if t.get("private"):
                if classify(t, records[0]):
                    status["problems"].append({"title": title, "app": app, "reason": "private", "action": "skipped (private tracker)"})
                continue
            reason = classify(t, records[0])
            if reason is None:
                healthy_now.append(h)
                continue
            bad_now.add(h)
            prev = self.state["torrents"].get(h, {})
            entry = {"reason": reason, "bad_seconds": prev.get("bad_seconds", 0.0), "bytes": int(t.get("downloaded") or 0),
                     "reannounced": prev.get("reannounced", False), "since": prev.get("since", self.now),
                     "would_done": prev.get("would_done", False)}
            if prev.get("reason") != reason or (reason in ("metadata", "dead", "stalled")
                                                and entry["bytes"] > prev.get("bytes", 0) + NEW_BYTES):
                entry.update(bad_seconds=0.0, reannounced=False, since=self.now, would_done=False)
            elif h in self.state["torrents"]:
                entry["bad_seconds"] += step   # a check that saw progress, or a new problem, earns no strike
            seen[h] = entry

        flipped = bad_now & set(self.state.get("healthy", []))
        if len(by_hash) >= BREAKER_MIN and len(flipped) >= BREAKER_SHARE * len(by_hash):
            status["breaker"] = True
            grace = grace or f"circuit breaker: {len(flipped)} of {len(by_hash)} torrents turned bad at once"
            for h in flipped:
                seen[h]["bad_seconds"] = 0.0
            self.alert("breaker", grace)
        status["grace"] = grace

        due = []
        for h, entry in seen.items():
            app, records = owned[h]
            t = by_hash[h]
            patience, action = RULES[entry["reason"]]
            near = float(t.get("progress") or 0) >= 0.9 and float(t.get("availability") or 0) >= 1
            extend_until = (self.overrides.get("extend") or {}).get(h) or (self.overrides.get("extend") or {}).get(h.lower())
            if near:
                patience *= 2
            if extend_until and self.now < float(extend_until):
                patience = float("inf")
            title = records[0].get("title") or t.get("name") or h
            row = {"title": title, "app": app, "reason": entry["reason"], "hours_bad": round(entry["bad_seconds"] / HOUR, 1),
                   "patience_hours": None if patience == float("inf") else round(patience / HOUR, 1),
                   "progress": round(float(t.get("progress") or 0), 4), "indexer": records[0].get("indexer")}
            status["problems"].append(row)
            if grace:
                continue
            if (entry["reason"] == "stalled" or near) and not entry["reannounced"] and entry["bad_seconds"] >= REANNOUNCE_AFTER:
                ok = True if self.watch_only else self.qbit.reannounce(h.lower())
                entry["reannounced"] = True
                self.audit({"action": ("would_" if self.watch_only else "") + "reannounce", "app": app, "title": title,
                            "hash": h, "reason": entry["reason"], "result": "ok" if ok else "failed"})
            if entry["bad_seconds"] >= patience:
                due.append((entry["bad_seconds"] / patience, h, app, records, entry, action, row))

        for _, h, app, records, entry, action, row in sorted(due, key=lambda d: -d[0]):
            row["action"] = self.act(h, app, records, entry, action, row)

        self.state["torrents"] = {h: e for h, e in seen.items() if not e.get("removed")}
        self.state["healthy"] = healthy_now
        self.save(self._finish(status))
        return status

    def alert(self, kind: str, message: str) -> None:
        self.state["alerts"] = ([a for a in self.state["alerts"] if self.now - a["ts"] < 7 * DAY]
                                + [{"ts": self.now, "kind": kind, "message": message}])[-50:]

    def act(self, h: str, app: str, records: List[Dict[str, Any]], entry: Dict[str, Any], action: str, row: Dict[str, Any]) -> str:
        title, key = row["title"], item_key(app, records[0])
        base = {"app": app, "title": title, "hash": h, "reason": entry["reason"], "hours_bad": row["hours_bad"],
                "indexer": records[0].get("indexer"), "key": key}
        if action == "alert":
            self.alert(entry["reason"], f"{title}: {entry['reason']} for {row['hours_bad']} h")
            self.audit(dict(base, action="alert"))
            return "alert"
        if self.watch_only and entry.get("would_done"):
            return f"would {action}"   # logged once; shown in the status until it recovers
        real = [x for x in self._recent(ITEM_WINDOW, key) if not x.get("would")]
        if len(real) >= ITEM_CAP:
            if not entry.get("attention"):
                self.alert("needs_attention", f"{title}: replaced {ITEM_CAP} times in 7 days; no healthy release found")
                self.audit(dict(base, action="needs_attention"))
                entry["attention"] = True
            return "needs attention"
        done_today = len([x for x in self._recent(DAY) if bool(x.get("would")) == self.watch_only])
        done_run = len([c for c in self.calls if c.get("action") in ("replace", "remove", "would_replace", "would_remove")])
        if done_run >= LIMIT_PER_RUN or done_today >= LIMIT_PER_DAY:
            return "waiting (rate limit)"
        if self.watch_only:
            entry["would_done"] = True
            self.state["history"].append({"ts": self.now, "key": key, "title": title, "would": True})
            self.audit(dict(base, action=f"would_{action}"))
            return f"would {action}"
        ok, detail = self.remove(self.arrs[app], records, blocklist=action == "replace")
        if ok:
            self.state["history"].append({"ts": self.now, "key": key, "title": title})
            entry["removed"] = True
        self.audit(dict(base, action=action, result="ok" if ok else f"failed: {detail}"))
        return action if ok else "failed"

    @staticmethod
    def remove(arr: Any, records: List[Dict[str, Any]], blocklist: bool) -> Tuple[bool, str]:
        """Through the app's queue: removes from qBittorrent, blocklists, searches again (8.1).
        A season pack is several records sharing one download: one bulk call, one search."""
        query = f"removeFromClient=true&blocklist={'true' if blocklist else 'false'}&skipRedownload=false"
        ids = [r["id"] for r in records]
        if len(ids) == 1:
            st, body = arr.request_json(f"/api/v3/queue/{ids[0]}?{query}", method="DELETE")
        else:
            st, body = arr.request_json(f"/api/v3/queue/bulk?{query}", method="DELETE", payload={"ids": ids})
        return st in (200, 202, 204), f"HTTP {st} {str(body)[:120]}"

    def _finish(self, status: Dict[str, Any]) -> Dict[str, Any]:
        recent = self._recent(DAY)
        counts: Dict[str, int] = {}
        for h in self._recent(ITEM_WINDOW):
            if not h.get("would"):
                counts[h["key"]] = counts.get(h["key"], 0) + 1
        status.update({
            "actions_24h": len([h for h in recent if not h.get("would")]),
            "would_24h": len([h for h in recent if h.get("would")]),
            "needs_attention": sorted({h["title"] for h in self._recent(ITEM_WINDOW) if counts.get(h["key"], 0) >= ITEM_CAP}),
            "alerts": [dict(a, ts=iso(a["ts"])) for a in self.state["alerts"][-10:]],
            "last_actions": self.calls[-10:],
        })
        return status

    # ----------------------------------------------------------------- sweep
    def run_sweep(self) -> Dict[str, Any]:
        """Searches cutoff-unmet titles: oversized first, then the longest-unsearched."""
        if not self.enabled:
            return {"job": "sweep", "mode": "off"}
        today = datetime.fromtimestamp(self.now, tz=timezone.utc).strftime("%Y-%m-%d")
        sweep = self.state.setdefault("sweep", {})
        if sweep.get("day") != today:
            sweep.update(day=today, count=0)
        candidates = []
        for app, arr in self.arrs.items():
            candidates += self._cutoff_candidates(app, arr)
        searched = self.state["searched"]
        fresh = [c for c in candidates if self.now - searched.get(c["key"], 0) >= SWEEP_REPEAT]
        fresh.sort(key=lambda c: (not c["oversized"], searched.get(c["key"], 0)))
        picked = fresh[:max(0, SWEEP_PER_DAY - sweep["count"])]
        for c in picked:
            if self.watch_only:
                self.audit({"action": "would_search", "app": c["app"], "title": c["title"], "reason": "cutoff unmet"})
            else:
                st, _ = self.arrs[c["app"]].request_json("/api/v3/command", method="POST", payload=c["command"])
                self.audit({"action": "search", "app": c["app"], "title": c["title"], "reason": "cutoff unmet",
                            "result": "ok" if st in (200, 201) else f"HTTP {st}"})
            searched[c["key"]] = self.now
            sweep["count"] += 1
        status = {"job": "sweep", "mode": self.mode, "updated": iso(self.now), "candidates": len(candidates),
                  "eligible": len(fresh), "searched": [c["title"] for c in picked]}
        self.state["sweep_status"] = status
        self.save(self._finish(dict(read_json(self.dir / "status.json", {}), sweep=status)))
        return status

    def _cutoff_candidates(self, app: str, arr: Any) -> List[Dict[str, Any]]:
        """Titles whose file is below its profile's upgrade-until score or quality. The apps'
        own Cutoff Unmet list is not enough: Radarr 7 leaves out files that are below the
        custom-format cutoff (7 listed against 53 such files on the live server)."""
        st, profiles = arr.request_json("/api/v3/qualityprofile")
        cutoff = {p["id"]: p.get("cutoffFormatScore", 0) for p in profiles if p.get("upgradeAllowed")} \
            if st == 200 and isinstance(profiles, list) else {}
        out: Dict[str, Dict[str, Any]] = {}

        def add(key: str, title: str, command: Dict[str, Any], size: float, runtime: float) -> None:
            mb_min = size / 1e6 / runtime if runtime else 0
            c = out.setdefault(key, {"app": app, "key": key, "title": title, "command": command, "oversized": False})
            c["oversized"] = c["oversized"] or mb_min > OVERSIZED_MB_PER_MIN[app]

        if app == "radarr":
            st, movies = arr.request_json("/api/v3/movie")
            movies = [m for m in movies if m.get("monitored") and m.get("hasFile") and m.get("qualityProfileId") in cutoff] \
                if st == 200 and isinstance(movies, list) else []
            by_id = {m["id"]: m for m in movies}
            ids = list(by_id)
            for i in range(0, len(ids), 100):
                st, files = arr.request_json("/api/v3/moviefile?" + "&".join(f"movieId={x}" for x in ids[i:i + 100]))
                for f in files if st == 200 and isinstance(files, list) else []:
                    m = by_id.get(f.get("movieId"))
                    if m and (f.get("customFormatScore", 0) < cutoff[m["qualityProfileId"]] or f.get("qualityCutoffNotMet")):
                        add(f"radarr:{m['id']}", f"{m.get('title')} ({m.get('year')})",
                            {"name": "MoviesSearch", "movieIds": [m["id"]]}, f.get("size") or 0, m.get("runtime") or 0)
        else:
            st, series = arr.request_json("/api/v3/series")
            for s in series if st == 200 and isinstance(series, list) else []:
                if not s.get("monitored") or s.get("qualityProfileId") not in cutoff:
                    continue
                st, files = arr.request_json(f"/api/v3/episodefile?seriesId={s['id']}")
                for f in files if st == 200 and isinstance(files, list) else []:
                    season = f.get("seasonNumber")
                    if f.get("customFormatScore", 0) < cutoff[s["qualityProfileId"]] or f.get("qualityCutoffNotMet"):
                        add(f"sonarr:{s['id']}:{season}", f"{s.get('title')} S{int(season or 0):02d}",
                            {"name": "SeasonSearch", "seriesId": s["id"], "seasonNumber": season},
                            f.get("size") or 0, s.get("runtime") or 0)
        return list(out.values())

    # ----------------------------------------------------------------- prune
    def run_prune(self) -> Dict[str, Any]:
        """Blocklist entries older than 60 days, for titles that still have no file."""
        if not self.enabled:
            return {"job": "prune", "mode": "off"}
        pruned = []
        for app, arr in self.arrs.items():
            st, data = arr.request_json("/api/v3/blocklist?page=1&pageSize=1000")
            records = data.get("records") if st == 200 and isinstance(data, dict) else []
            old = [r for r in records or [] if (parse_ts(r.get("date")) or self.now) < self.now - PRUNE_AGE]
            ids = [r["id"] for r in old if self._still_missing(app, arr, r)]
            if not ids:
                continue
            if self.watch_only:
                self.audit({"action": "would_prune", "app": app, "title": f"{len(ids)} blocklist entries", "reason": "older than 60 days"})
            else:
                st, _ = arr.request_json("/api/v3/blocklist/bulk", method="DELETE", payload={"ids": ids})
                self.audit({"action": "prune", "app": app, "title": f"{len(ids)} blocklist entries", "reason": "older than 60 days",
                            "result": "ok" if st in (200, 204) else f"HTTP {st}"})
            pruned.append({"app": app, "entries": len(ids)})
        status = {"job": "prune", "mode": self.mode, "updated": iso(self.now), "pruned": pruned}
        self.save(self._finish(dict(read_json(self.dir / "status.json", {}), prune=status)))
        return status

    @staticmethod
    def _still_missing(app: str, arr: Any, rec: Dict[str, Any]) -> bool:
        if app == "radarr":
            st, movie = arr.request_json(f"/api/v3/movie/{rec.get('movieId')}")
            return st == 200 and isinstance(movie, dict) and not movie.get("hasFile")
        ids = rec.get("episodeIds") or []
        if not ids:
            return False
        st, eps = arr.request_json("/api/v3/episode?" + "&".join(f"episodeIds={i}" for i in ids))
        return st == 200 and isinstance(eps, list) and bool(eps) and not any(e.get("hasFile") for e in eps)


# --------------------------------------------------------------------- main
def build(args: argparse.Namespace) -> Doctor:
    env = read_env_file(args.env_file) if args.env_file else {}
    config_dir = Path(args.config_dir) if args.config_dir else None
    arrs: Dict[str, Any] = {}
    for app, port in (("radarr", 7878), ("sonarr", 8989)):
        if app in (args.skip or []):
            continue
        key = env.get(f"{app.upper()}_API_KEY") or (read_api_key_from_config(config_dir, app) if config_dir else "")
        if key:
            arrs[app] = ArrClient(app, f"http://{args.host}:{port}", key, timeout=30)
    qbit = QbitApi(args.host, env.get("QBITTORRENT_USER") or "admin", env.get("QBITTORRENT_PASS", ""))
    enabled = str(env.get("MEDIA_STUCK_DOWNLOADS", "replace")).strip().lower() != "off"
    logger = logging.getLogger("mediaserver.download_doctor")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    return Doctor(qbit, arrs, Path(args.state_dir), watch_days=args.watch_days, dry_run=args.dry_run, enabled=enabled, logger=logger)


def main() -> int:
    p = argparse.ArgumentParser(description="Replace stuck downloads through Radarr/Sonarr (media pipeline plan section 8).")
    p.add_argument("--job", default="stuck", help="Comma list of stuck, sweep, prune")
    p.add_argument("--config-dir", default=os.getenv("CONFIG_DIR", ""), help="Appdata dir holding radarr/sonarr config.xml")
    p.add_argument("--env-file", default="", help="mediaserver.env: qBittorrent login and MEDIA_STUCK_DOWNLOADS")
    p.add_argument("--state-dir", default="/var/lib/homelab/download-doctor", help="state.json, status.json, actions.jsonl")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--watch-days", type=float, default=7, help="Watch-only period from the first run (0 = act at once)")
    p.add_argument("--dry-run", action="store_true", help="Log decisions only, whatever the watch-only period says")
    p.add_argument("--skip", action="append", choices=["radarr", "sonarr"], help="Leave one app out")
    p.add_argument("--once", action="store_true", help="Run once and exit (the default; for cron)")
    p.add_argument("--json", action="store_true", help="Print the job status as JSON")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    jobs = [j.strip() for j in args.job.split(",") if j.strip()]
    bad = [j for j in jobs if j not in ("stuck", "sweep", "prune")]
    if bad:
        p.error(f"unknown job {bad}")
    doctor = build(args)
    out = {}
    for job in jobs:
        out[job] = getattr(doctor, f"run_{job}")()
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
