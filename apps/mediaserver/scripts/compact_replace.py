"""
Compact replacement (media pipeline plan section 8.6) and the weekly space report.
Run by download_doctor.py as `--job compact` (hourly) and `--job space` (weekly).

Compact replacement keeps hunting for smaller versions of oversized TV seasons on
1080p Compact. Films need no job: their size formats make a compact HEVC release an
ordinary upgrade, which the daily sweep triggers. For TV, codec alone never upgrades
(revision 4) and Sonarr cannot size a season pack per episode, so this job:

  1. picks the oversized season (over 30 MB per minute) with the most GB on disk that
     was not searched in the last 3 days, one title in flight at a time;
  2. runs Sonarr's own season search and accepts a candidate only if it is 1080p, at
     least 35% smaller per minute and above the quality's minimum, free of Junk/Compat
     formats, keeps the second language when the files have it, and Sonarr's only
     objection is "not an upgrade". Season packs need 10 seeders (owner decision 16);
     otherwise episodes with 4 each, and a 4-9 seeder pack only when the episodes
     cannot all be found;
  3. starts only with the candidate's size plus 20 GB free; grabs with POST /release;
  4. once downloaded (Sonarr holds it as "not an upgrade"), verifies the files like
     auto_import.py (video, no samples, the right series and episodes) and runs Sonarr's
     ManualImport, which replaces each old file during import (old ones go to the
     recycle bin);
  5. verifies that every episode has a new, smaller file and records the GB saved.
     Three failed candidates pause the title for 14 days.

Watch-only with the rest of the Doctor for its first 7 days, and paused while a TV is
playing from the Samba share. Standard library only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from auto_import import is_video_non_sample, title_matches_release

GB = 1e9
DAY = 86400
TV_OVERSIZED_MB_MIN = 30
SHRINK = 0.65                     # at least 35% smaller per minute
PACK_MIN_SEEDERS, EPISODE_MIN_SEEDERS = 10, 4
HEADROOM = 20 * GB
SEARCH_REPEAT = 3 * DAY
PICK_EVERY = 6 * 3600
MAX_FAILURES, RETRY_AFTER = 3, 14 * DAY
INFLIGHT_LIMIT = 7 * DAY
IMPORT_WAIT = 2 * 3600            # an import sent this long ago without new files has failed
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov", ".wmv", ".m2ts")
LANG_CODES = {"Hindi": "hin", "Tamil": "tam", "Telugu": "tel", "Malayalam": "mal", "Kannada": "kan", "Bengali": "ben",
              "Marathi": "mar", "Spanish": "spa", "French": "fre", "German": "ger", "Italian": "ita", "Portuguese": "por",
              "Japanese": "jpn", "Korean": "kor", "Arabic": "ara"}


# ------------------------------------------------------------------ pure rules
def runtime_minutes(file: Dict[str, Any], fallback: float = 0) -> float:
    """mediaInfo.runTime is "h:mm:ss" or "mm:ss"; the series runtime is the fallback."""
    parts = str((file.get("mediaInfo") or {}).get("runTime") or "").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return float(fallback or 0)
    if len(nums) == 3:
        return nums[0] * 60 + nums[1] + nums[2] / 60
    if len(nums) == 2:
        return nums[0] + nums[1] / 60
    return float(fallback or 0)


def mb_per_min(size: float, minutes: float) -> float:
    return size / 1e6 / minutes if minutes else 0.0


def covered(release: Dict[str, Any], season_episodes: List[int]) -> set:
    """Episodes a release holds. Some whole-season releases are not flagged fullSeason, so
    Sonarr's mapped episode numbers decide."""
    if release.get("fullSeason"):
        return set(season_episodes)
    return set(release.get("mappedEpisodeNumbers") or release.get("episodeNumbers") or [])


def has_language(release: Dict[str, Any], language: str) -> bool:
    """Any of the pack's `Lang · {LANG} ...` formats matched (named, dual tag, only, untagged)."""
    return any(str(cf.get("name", "")).startswith(f"Lang · {language} ") for cf in release.get("customFormats") or [])


def why_not(release: Dict[str, Any], current_mb_min: float, minutes: float, min_mb: Dict[str, float],
            need_language: str, min_seeders: int) -> Optional[str]:
    """None when the release is an acceptable compact replacement, otherwise the reason."""
    quality = (release.get("quality") or {}).get("quality") or {}
    if int(quality.get("resolution") or 0) < 1080:
        return "lower resolution"
    other = [r for r in release.get("rejections") or [] if not str(r).lower().startswith("existing file on disk")]
    if other:
        return f"rejected: {other[0]}"
    names = [str(cf.get("name", "")) for cf in release.get("customFormats") or []]
    if any(n.startswith(("Junk · ", "Compat · ")) for n in names) or int(release.get("customFormatScore") or 0) < 0:
        return "junk or incompatible format"
    if int(release.get("seeders") or 0) < min_seeders:
        return f"{release.get('seeders') or 0} seeders"
    cand = mb_per_min(float(release.get("size") or 0), minutes)
    if cand > SHRINK * current_mb_min:
        return f"only {round(100 * (1 - cand / current_mb_min)) if current_mb_min else 0}% smaller"
    if cand < float(min_mb.get(quality.get("name"), 0) or 0):
        return "below the quality's minimum size (starved encode)"
    if need_language and not has_language(release, need_language):
        return f"no {need_language} audio"
    return None


def choose(releases: List[Dict[str, Any]], files: Dict[int, Dict[str, Any]], runtime: float, min_mb: Dict[str, float],
           need_language: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """The replacement plan for one season: {"kind": "pack"|"episodes", "releases": [...]},
    or None with the reasons. `files` maps episode number -> episode file. Releases come in
    Sonarr's own order of preference."""
    eps = sorted(files)
    minutes = {n: runtime_minutes(f, runtime) for n, f in files.items()}
    total_min, total_size = sum(minutes.values()), sum(float(f.get("size") or 0) for f in files.values())
    season_mb = mb_per_min(total_size, total_min)
    oversized = [n for n in eps if mb_per_min(float(files[n].get("size") or 0), minutes[n]) > TV_OVERSIZED_MB_MIN]
    packs = [r for r in releases if len(covered(r, eps)) >= 2 and set(eps) <= covered(r, eps)]
    reasons: Dict[str, int] = {}

    def first_pack(min_seeders: int) -> Optional[Dict[str, Any]]:
        for r in packs:
            why = why_not(r, season_mb, total_min, min_mb, need_language, min_seeders)
            if why is None:
                return r
            reasons[why] = reasons.get(why, 0) + 1
        return None

    pack = first_pack(PACK_MIN_SEEDERS)
    if pack:
        return {"kind": "pack", "releases": [pack]}, []
    singles = {}
    for n in oversized:
        f = files[n]
        for r in releases:
            if covered(r, eps) != {n}:
                continue
            why = why_not(r, mb_per_min(float(f.get("size") or 0), minutes[n]), minutes[n], min_mb, need_language, EPISODE_MIN_SEEDERS)
            if why is None:
                singles[n] = r
                break
            reasons[why] = reasons.get(why, 0) + 1
    if oversized and len(singles) == len(oversized):
        return {"kind": "episodes", "releases": [singles[n] for n in oversized]}, []
    weak = first_pack(EPISODE_MIN_SEEDERS)
    if weak:
        return {"kind": "pack", "releases": [weak]}, []
    if singles:
        return {"kind": "episodes", "releases": list(singles.values())}, []
    top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
    return None, [f"{why} ({n})" for why, n in top] or ["no releases found"]


# ------------------------------------------------------------------ the job
def smb_streaming() -> bool:
    """True while a video file is open on the Samba share (the Doctor runs as root)."""
    exe = shutil.which("smbstatus")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=15).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return any(ext in out for ext in VIDEO_EXT)


class CompactJob:
    def __init__(self, doctor: Any, data_dir: str = "", language: str = "",
                 streaming: Callable[[], bool] = smb_streaming, disk_free: Optional[Callable[[], float]] = None):
        self.d, self.data_dir, self.language, self.streaming = doctor, data_dir, language, streaming
        self.disk_free = disk_free or (lambda: shutil.disk_usage(data_dir).free if data_dir else float("inf"))
        self.state = doctor.state.setdefault("compact", {})
        for key, empty in (("inflight", None), ("titles", {}), ("saved_gb", 0.0), ("last_pick", 0)):
            self.state.setdefault(key, empty)

    @property
    def sonarr(self) -> Any:
        return self.d.arrs.get("sonarr")

    def get(self, path: str, timeout: Optional[int] = None) -> Any:
        """GET through the Doctor's client; a season search queries every indexer and can
        take minutes, so it gets a longer timeout."""
        old = getattr(self.sonarr, "timeout", None)
        if timeout and old is not None:
            self.sonarr.timeout = timeout
        try:
            st, data = self.sonarr.request_json(path)
        finally:
            if timeout and old is not None:
                self.sonarr.timeout = old
        return data if st == 200 else None

    def run(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {"job": "compact", "mode": self.d.mode, "saved_gb": round(self.state["saved_gb"], 1)}
        if not self.d.enabled or self.sonarr is None:
            status["state"] = "off" if not self.d.enabled else "no Sonarr"
            return status
        if self.state["inflight"]:
            status.update(self.follow())
        elif self.d.now - self.state["last_pick"] < PICK_EVERY:
            status["state"] = "waiting for the next pick (every 6 hours)"
        elif self.streaming():
            status["state"] = "paused: a video is playing from the share"
        else:
            status.update(self.pick())
        status["saved_gb"] = round(self.state["saved_gb"], 1)
        status["inflight"] = (self.state["inflight"] or {}).get("title")
        status["titles"] = {k: {x: v for x, v in t.items() if x != "key"} for k, t in self.state["titles"].items()}
        return status

    # --------------------------------------------------------------- pick + grab
    def seasons(self) -> List[Dict[str, Any]]:
        """Oversized seasons of series on 1080p Compact without a `keep` tag, most GB first."""
        profiles = {p["id"]: p.get("name") for p in self.get("/api/v3/qualityprofile") or []}
        keep = {t["id"] for t in self.get("/api/v3/tag") or [] if str(t.get("label", "")).lower() == "keep"}
        out = []
        for s in self.get("/api/v3/series") or []:
            if not s.get("monitored") or profiles.get(s.get("qualityProfileId")) != "1080p Compact" or keep & set(s.get("tags") or []):
                continue
            episodes = {e["episodeFileId"]: e for e in self.get(f"/api/v3/episode?seriesId={s['id']}") or [] if e.get("hasFile")}
            by_season: Dict[int, Dict[int, Dict[str, Any]]] = {}
            for f in self.get(f"/api/v3/episodefile?seriesId={s['id']}") or []:
                ep = episodes.get(f["id"])
                if ep:
                    by_season.setdefault(f["seasonNumber"], {})[ep["episodeNumber"]] = dict(f, episodeId=ep["id"])
            for season, files in by_season.items():
                size = sum(float(f.get("size") or 0) for f in files.values())
                minutes = sum(runtime_minutes(f, s.get("runtime") or 0) for f in files.values())
                if mb_per_min(size, minutes) > TV_OVERSIZED_MB_MIN:
                    out.append({"key": f"sonarr:{s['id']}:{season}", "series": s, "season": season, "files": files,
                                "size": size, "title": f"{s.get('title')} S{int(season):02d}"})
        return sorted(out, key=lambda x: -x["size"])

    def pick(self) -> Dict[str, Any]:
        titles = self.state["titles"]
        todo = [x for x in self.seasons()
                if self.d.now - titles.get(x["key"], {}).get("last_search", 0) >= SEARCH_REPEAT
                and self.d.now >= titles.get(x["key"], {}).get("retry_after", 0)]
        if not todo:
            return {"state": "nothing to compact right now"}
        t = todo[0]
        rec = titles.setdefault(t["key"], {"title": t["title"], "failures": 0})
        rec["last_search"] = self.d.now
        self.state["last_pick"] = self.d.now
        releases = self.get(f"/api/v3/release?seriesId={t['series']['id']}&seasonNumber={t['season']}", timeout=240) or []
        min_mb = {q["quality"]["name"]: q.get("minSize") or 0 for q in self.get("/api/v3/qualitydefinition") or []}
        need = self.language if self.language and any(
            LANG_CODES.get(self.language, "~") in str((f.get("mediaInfo") or {}).get("audioLanguages", "")).lower()
            for f in t["files"].values()) else ""
        plan, reasons = choose(releases, t["files"], t["series"].get("runtime") or 0, min_mb, need)
        base = {"app": "sonarr", "title": t["title"], "reason": "oversized", "gb_on_disk": round(t["size"] / GB, 1)}
        if plan is None:
            rec["last_result"] = "no candidate: " + "; ".join(reasons)
            self.d.audit(dict(base, action="compact_no_candidate", detail=reasons))
            return {"state": f"{t['title']}: no acceptable candidate", "reasons": reasons}
        size = sum(float(r.get("size") or 0) for r in plan["releases"])
        detail = [f"{r.get('title')} ({round(float(r.get('size') or 0) / GB, 1)} GB, {r.get('seeders')} seeders)" for r in plan["releases"]]
        if self.disk_free() < size + HEADROOM:
            rec["last_result"] = "waiting for free space"
            self.d.audit(dict(base, action="compact_waiting_space", detail=detail))
            return {"state": f"{t['title']}: needs {round((size + HEADROOM) / GB)} GB free"}
        if self.d.watch_only:
            rec["last_result"] = f"would replace with {plan['kind']}"
            self.d.audit(dict(base, action="would_compact", kind=plan["kind"], new_gb=round(size / GB, 1), detail=detail))
            return {"state": f"{t['title']}: would replace ({plan['kind']}, {round(size / GB, 1)} GB)", "candidates": detail}
        grabbed = []
        for r in plan["releases"]:
            st, body = self.sonarr.request_json("/api/v3/release", method="POST", payload={"guid": r["guid"], "indexerId": r["indexerId"]})
            if st not in (200, 201):
                self.d.audit(dict(base, action="compact_grab_failed", detail=f"{r.get('title')}: HTTP {st} {str(body)[:120]}"))
                continue
            grabbed.append({"title": r.get("title"), "guid": r["guid"], "size": float(r.get("size") or 0),
                            "episodes": sorted(covered(r, sorted(t["files"])) & set(t["files"]))})
        if not grabbed:
            rec["failures"] += 1
            return {"state": f"{t['title']}: grab failed"}
        self.state["inflight"] = {"key": t["key"], "title": t["title"], "series_id": t["series"]["id"], "season": t["season"],
                                  "grabbed": self.d.now, "releases": grabbed, "need_language": need,
                                  "old": {str(n): {"id": f["id"], "path": f.get("path"), "size": float(f.get("size") or 0)}
                                          for n, f in t["files"].items()}}
        rec["last_result"] = f"downloading {plan['kind']}"
        self.d.audit(dict(base, action="compact_grab", kind=plan["kind"], new_gb=round(size / GB, 1), detail=detail))
        return {"state": f"{t['title']}: downloading {plan['kind']} ({round(size / GB, 1)} GB)"}

    # ------------------------------------------------------------ follow + import
    def follow(self) -> Dict[str, Any]:
        inf = self.state["inflight"]
        rec = self.state["titles"].setdefault(inf["key"], {"title": inf["title"], "failures": 0})
        series = next((s for s in self.get("/api/v3/series") or [] if s.get("id") == inf["series_id"]), {"title": inf["title"]})
        queue = (self.get("/api/v3/queue?page=1&pageSize=1000&includeUnknownSeriesItems=false") or {}).get("records") or []
        files_now = self.files_for(inf)
        pending = []
        for rel in inf["releases"]:
            if rel.get("imported"):
                continue
            if all(files_now.get(n) and files_now[n].get("id") != inf["old"].get(str(n), {}).get("id") for n in rel["episodes"]):
                rel["imported"] = self.d.now
                continue
            records = [q for q in queue if q.get("title") == rel["title"] and q.get("seriesId") == inf["series_id"]]
            if records:
                state = str(records[0].get("trackedDownloadState") or "").lower()
                if state in ("importpending", "importblocked") and not rel.get("import_sent"):
                    self.manual_import(inf, rel, series, records[0])
                pending.append(rel["title"])
            elif rel.get("import_sent") and self.d.now - rel["import_sent"] < IMPORT_WAIT:
                pending.append(rel["title"])
            else:
                return self.fail(inf, rec, f"{rel['title']} left the queue without importing (removed, or replaced as stuck)")
        if pending:
            if self.d.now - inf["grabbed"] > INFLIGHT_LIMIT:
                return self.fail(inf, rec, "not finished within 7 days")
            return {"state": f"{inf['title']}: in progress", "pending": pending}
        return self.verify(inf, rec, files_now)

    def files_for(self, inf: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        episodes = {e["episodeFileId"]: e for e in self.get(f"/api/v3/episode?seriesId={inf['series_id']}") or []
                    if e.get("hasFile") and e.get("seasonNumber") == inf["season"]}
        out = {}
        for f in self.get(f"/api/v3/episodefile?seriesId={inf['series_id']}") or []:
            ep = episodes.get(f["id"])
            if ep:
                out[ep["episodeNumber"]] = f
        return out

    def manual_import(self, inf: Dict[str, Any], rel: Dict[str, Any], series: Dict[str, Any], record: Dict[str, Any]) -> None:
        """The verified manual import of auto_import.py, over existing files: video files only,
        no samples, the series title in the name, exactly the expected episodes of this season."""
        did = record.get("downloadId")
        items = self.get(f"/api/v3/manualimport?downloadId={did}&seriesId={inf['series_id']}&filterExistingFiles=false") or []
        videos = [f for f in items if is_video_non_sample(str(f.get("path") or ""))]
        mapped: Dict[int, Dict[str, Any]] = {}
        problems = []
        for f in videos:
            eps = [e for e in f.get("episodes") or [] if e.get("seasonNumber") == inf["season"]]
            if not eps or len(eps) != len(f.get("episodes") or []):
                problems.append(f"{Path(str(f.get('path'))).name}: episodes not mapped to season {inf['season']}")
            if not title_matches_release(series, str(f.get("path") or ""), str(f.get("folderName") or "")):
                problems.append(f"{Path(str(f.get('path'))).name}: series title not in the name")
            for e in eps:
                if e["episodeNumber"] in mapped:
                    problems.append(f"episode {e['episodeNumber']} twice")
                mapped[e["episodeNumber"]] = f
        if set(mapped) != set(rel["episodes"]):
            problems.append(f"episodes {sorted(mapped)} do not match the expected {rel['episodes']}")
        base = {"app": "sonarr", "title": inf["title"], "reason": "compact import", "release": rel["title"]}
        if problems:
            rel["import_problems"] = problems[:5]
            self.d.alert("compact_import", f"{inf['title']}: import held for review: {problems[0]}")
            self.d.audit(dict(base, action="compact_import_held", detail=problems[:5]))
            return
        files = []
        for f in {id(x): x for x in mapped.values()}.values():
            files.append({"path": f["path"], "folderName": f.get("folderName") or Path(str(f["path"])).parent.name,
                          "seriesId": inf["series_id"], "episodeIds": [e["id"] for e in f["episodes"]],
                          "quality": f.get("quality"), "languages": f.get("languages") or [{"id": 1, "name": "English"}],
                          "releaseGroup": f.get("releaseGroup", ""), "indexerFlags": f.get("indexerFlags", 0),
                          "releaseType": f.get("releaseType") or ("SeasonPack" if len(mapped) > 1 else "SingleEpisode"),
                          "downloadId": did})
        st, body = self.sonarr.request_json("/api/v3/command", method="POST",
                                            payload={"name": "ManualImport", "importMode": "auto", "files": files})
        rel["import_sent"] = self.d.now
        self.d.audit(dict(base, action="compact_import", result="ok" if st in (200, 201) else f"HTTP {st} {str(body)[:120]}",
                          files=len(files)))

    def verify(self, inf: Dict[str, Any], rec: Dict[str, Any], files_now: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
        episodes = sorted({n for rel in inf["releases"] for n in rel["episodes"]})
        old_size = sum(inf["old"][str(n)]["size"] for n in episodes if str(n) in inf["old"])
        new_size = sum(float(files_now[n].get("size") or 0) for n in episodes if n in files_now)
        problems = [f"E{n:02d} has no new file" for n in episodes
                    if n not in files_now or files_now[n].get("id") == inf["old"].get(str(n), {}).get("id")]
        if new_size >= old_size:
            problems.append(f"not smaller ({round(new_size / GB, 1)} GB against {round(old_size / GB, 1)} GB)")
        code = LANG_CODES.get(inf.get("need_language") or "", "")
        for n in episodes:
            langs = str((files_now.get(n, {}).get("mediaInfo") or {}).get("audioLanguages", "")).lower()
            if code and langs and code not in langs and "und" not in langs:
                problems.append(f"E{n:02d} lost its {inf['need_language']} audio ({langs})")
        base = {"app": "sonarr", "title": inf["title"], "reason": "compact verify"}
        self.state["inflight"] = None
        if problems:
            rec["last_result"] = "verify failed: " + "; ".join(problems[:3])
            self.d.alert("compact_verify", f"{inf['title']}: {problems[0]}. The old files are in the recycle bin for 7 days")
            self.d.audit(dict(base, action="compact_verify_failed", detail=problems[:5]))
            return {"state": f"{inf['title']}: verification failed", "problems": problems[:5]}
        saved = (old_size - new_size) / GB
        self.state["saved_gb"] += saved
        rec.update(last_result=f"replaced: {round(old_size / GB, 1)} GB -> {round(new_size / GB, 1)} GB", done=self.d.now,
                   saved_gb=round(saved, 1), failures=0)
        self.d.audit(dict(base, action="compact_done", saved_gb=round(saved, 1),
                          detail=f"{round(old_size / GB, 1)} GB -> {round(new_size / GB, 1)} GB"))
        return {"state": f"{inf['title']}: replaced, {round(saved, 1)} GB saved"}

    def fail(self, inf: Dict[str, Any], rec: Dict[str, Any], why: str) -> Dict[str, Any]:
        rec["failures"] = rec.get("failures", 0) + 1
        if rec["failures"] >= MAX_FAILURES:
            rec["retry_after"] = self.d.now + RETRY_AFTER
            rec["failures"] = 0
            why += "; three candidates failed, retrying in 14 days"
        rec["last_result"] = "failed: " + why
        self.state["inflight"] = None
        self.d.audit({"app": "sonarr", "title": inf["title"], "reason": "compact", "action": "compact_failed", "detail": why})
        return {"state": f"{inf['title']}: {why}"}


# ------------------------------------------------------------------ space report
def space_report(data_dir: str, torrents: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Report only, nothing is deleted: torrent-folder files no torrent uses and not
    hardlinked into the library, the recycle bin, and Nova resume files whose video is gone."""
    root = Path(data_dir)
    out: Dict[str, Any] = {"data_dir": data_dir}
    if not data_dir or not root.is_dir():
        out["error"] = "data folder not found (pass --data-dir)"
        return out
    used = [Path(data_dir + str(t.get("content_path") or "")[len("/data"):]) for t in torrents or []
            if str(t.get("content_path") or "").startswith("/data/")]
    orphans, orphan_size = [], 0
    for dirpath, _, names in os.walk(root / "torrents"):
        for name in names:
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_nlink > 1 or any(p == u or u in p.parents for u in used):
                continue
            orphans.append(str(p.relative_to(root)))
            orphan_size += st.st_size
    out["torrent_orphans"] = {"files": len(orphans), "gb": round(orphan_size / GB, 2), "examples": orphans[:10]}
    recycle = root / "media" / ".recycle"
    size = sum(f.stat().st_size for f in recycle.rglob("*") if f.is_file()) if recycle.is_dir() else 0
    out["recycle_bin_gb"] = round(size / GB, 2)
    resume = [p for p in (root / "media").rglob("*.archos.resume.xml")] if (root / "media").is_dir() else []
    out["nova_resume_files"] = {"files": len(resume),
                                "orphans": len([p for p in resume if not Path(str(p)[:-len(".archos.resume.xml")]).exists()])}
    return out
