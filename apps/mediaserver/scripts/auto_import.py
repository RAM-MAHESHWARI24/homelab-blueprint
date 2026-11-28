#!/usr/bin/env python3
"""
Smart, title-verified auto-importer for Radarr and Sonarr queue holds.

Solves stuck queue items such as:
  "Found matching movie via grab history, but release was matched to movie by ID.
   Manual Import required."

Unlike blind importers, this script verifies both sides before importing:
  1. Only acts on queue items in importBlocked / importPending with Manual Import
     or matched-by-ID status messages.
  2. Queries /api/v3/manualimport?downloadId=<id>&filterExistingFiles=true and drops
     sample clips and non-video files.
  3. Rejects permanent safety blocks (wrong quality, duplicate, unpack failures),
     permitting only clean matches OR lone "Unknown Movie" / "Unknown Series" flags
     when the queue grab already provides the movieId / seriesId.
  4. Verifies the target movie/series normalized title matches inside the downloaded
     file or folder name (plus year guard for short <=4-char titles) so a spoofed
     indexer ID still stays blocked for human review.

Standard library only; safe for cron or systemd timers.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".m4v",
    ".ts",
    ".wmv",
    ".webm",
    ".flv",
    ".mpg",
    ".mpeg",
    ".m2ts",
}

ALLOWED_REJECTION_PREFIXES = (
    "unknown movie",
    "unknown series",
)

TRIGGER_STATUS_PHRASES = (
    "manual import required",
    "matched to movie by id",
    "matched to series by id",
    "automatic import is not possible",
)

_SAMPLE_RE = re.compile(r"(?:^|[\W_])sample(?:[\W_]|$)", re.IGNORECASE)
_EPISODE_TAG_RE = re.compile(r"S(\d{1,3})E(\d{1,3})", re.IGNORECASE)
_STOP_WORDS = {"the", "a", "an"}


def setup_logger(log_file: str = "", verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("mediaserver.auto_import")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=1_048_576, backupCount=2, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger


def normalize_text(value: str) -> str:
    """NFKD-strip accents and fold punctuation into single ASCII spaces."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def strip_leading_article(norm_title: str) -> str:
    parts = norm_title.split(" ", 1)
    if len(parts) == 2 and parts[0] in _STOP_WORDS:
        return parts[1]
    return norm_title


def title_variants(item: Dict[str, Any]) -> List[str]:
    """Extracts primary, original, and alternate titles from a Radarr/Sonarr entity."""
    raw: List[str] = []
    for key in ("title", "originalTitle"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            raw.append(val.strip())
    for alt in item.get("alternateTitles") or []:
        if isinstance(alt, dict):
            t = alt.get("title")
            if isinstance(t, str) and t.strip():
                raw.append(t.strip())
    seen = set()
    variants: List[str] = []
    for text in raw:
        norm = normalize_text(text)
        if not norm:
            continue
        for candidate in (norm, strip_leading_article(norm)):
            if candidate and candidate not in seen:
                seen.add(candidate)
                variants.append(candidate)
    return variants


def title_matches_release(entity: Dict[str, Any], *candidate_names: str) -> bool:
    """
    Returns True if a normalized title/alias of `entity` matches on word boundaries
    inside any of `candidate_names`. For very short titles (<=4 chars), also requires
    the release year when known so short words don't falsely match substrings/words.
    """
    variants = title_variants(entity)
    if not variants:
        return False

    year = entity.get("year")
    year_str = str(year) if isinstance(year, int) and year > 1880 else ""

    norm_candidates = [normalize_text(name) for name in candidate_names if isinstance(name, str) and name.strip()]
    if not norm_candidates:
        return False

    for cand in norm_candidates:
        padded_cand = f" {cand} "
        for variant in variants:
            if f" {variant} " in padded_cand:
                if len(variant) <= 4 and year_str and f" {year_str} " not in padded_cand:
                    continue
                return True
    return False


def is_video_non_sample(path_str: str) -> bool:
    p = Path(path_str)
    if p.suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    return _SAMPLE_RE.search(p.stem) is None


def only_allowed_rejections(rejections: Any) -> bool:
    if not rejections:
        return True
    if not isinstance(rejections, list):
        return False
    for rej in rejections:
        reason = str((rej or {}).get("reason", "")).strip().lower() if isinstance(rej, dict) else str(rej).strip().lower()
        if not any(reason.startswith(prefix) for prefix in ALLOWED_REJECTION_PREFIXES):
            return False
    return True


def queue_item_needs_manual_import(record: Dict[str, Any]) -> bool:
    state = str(record.get("trackedDownloadState") or "").lower()
    if state not in ("importblocked", "importpending"):
        return False
    if not record.get("downloadId"):
        return False
    for msg_block in record.get("statusMessages") or []:
        if not isinstance(msg_block, dict):
            continue
        texts = [str(msg_block.get("title") or "")] + [str(m) for m in (msg_block.get("messages") or [])]
        combined = " ".join(texts).lower()
        if any(phrase in combined for phrase in TRIGGER_STATUS_PHRASES):
            return True
    return False


def read_api_key_from_config(config_dir: Path, app: str) -> str:
    xml_path = config_dir / app / "config.xml"
    if not xml_path.is_file():
        return ""
    try:
        key = ET.parse(xml_path).getroot().findtext("ApiKey")
        return (key or "").strip()
    except ET.ParseError:
        return ""


class ArrClient:
    def __init__(self, app_type: str, base_url: str, api_key: str, timeout: int = 20):
        self.app_type = app_type  # "radarr" or "sonarr"
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key, "Accept": "application/json", "Content-Type": "application/json"}
        self.timeout = timeout

    def request_json(self, path: str, method: str = "GET", payload: Any = None) -> Tuple[int, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=body, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return 0, str(exc)


def process_radarr(client: ArrClient, dry_run: bool, logger: logging.Logger) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"app": "radarr", "checked": 0, "imported": [], "skipped": []}
    st, qdata = client.request_json("/api/v3/queue?pageSize=100&includeUnknownMovieItems=true")
    if st != 200 or not isinstance(qdata, dict):
        logger.warning("Radarr queue query failed (HTTP %s)", st)
        summary["error"] = f"HTTP {st}"
        return summary

    movie_cache: Dict[int, Dict[str, Any]] = {}
    seen_download_ids = set()

    for record in qdata.get("records") or []:
        if not queue_item_needs_manual_import(record):
            continue
        download_id = str(record["downloadId"])
        if download_id in seen_download_ids:
            continue
        seen_download_ids.add(download_id)
        summary["checked"] += 1
        title_label = str(record.get("title") or download_id)

        mst, files = client.request_json(
            f"/api/v3/manualimport?downloadId={urllib.parse.quote(download_id)}&filterExistingFiles=true"
        )
        if mst != 200 or not isinstance(files, list):
            summary["skipped"].append({"title": title_label, "reason": f"manualimport HTTP {mst}"})
            continue

        video_files = [f for f in files if isinstance(f, dict) and is_video_non_sample(str(f.get("path") or ""))]
        if len(video_files) != 1:
            summary["skipped"].append({"title": title_label, "reason": f"expected 1 video file, found {len(video_files)}"})
            continue

        f = video_files[0]
        if not only_allowed_rejections(f.get("rejections")):
            summary["skipped"].append({"title": title_label, "reason": f"rejected: {f.get('rejections')}"})
            continue

        movie_obj = f.get("movie") if isinstance(f.get("movie"), dict) else None
        movie_id = (movie_obj or {}).get("id") or record.get("movieId")
        if not movie_id:
            summary["skipped"].append({"title": title_label, "reason": "no movieId from queue or manualimport"})
            continue

        if movie_obj is None:
            if int(movie_id) not in movie_cache:
                gst, mdata = client.request_json(f"/api/v3/movie/{int(movie_id)}")
                if gst == 200 and isinstance(mdata, dict):
                    movie_cache[int(movie_id)] = mdata
            movie_obj = movie_cache.get(int(movie_id))

        if not movie_obj or not title_matches_release(
            movie_obj,
            str(f.get("relativePath") or ""),
            str(f.get("name") or ""),
            str(f.get("folderName") or ""),
            str(record.get("title") or ""),
        ):
            summary["skipped"].append({"title": title_label, "reason": "title verification mismatch"})
            continue

        if dry_run:
            logger.info("[DRY-RUN] Radarr WOULD IMPORT '%s' -> '%s'", title_label, movie_obj.get("title"))
            summary["imported"].append({"title": title_label, "target": movie_obj.get("title"), "dry_run": True})
            continue

        cmd_payload = {
            "name": "ManualImport",
            "importMode": "auto",
            "files": [
                {
                    "path": f["path"],
                    "folderName": f.get("folderName") or Path(str(f["path"])).parent.name,
                    "movieId": int(movie_id),
                    "quality": f.get("quality"),
                    "languages": f.get("languages") or [{"id": 1, "name": "English"}],
                    "indexerFlags": f.get("indexerFlags", 0),
                    "releaseGroup": f.get("releaseGroup", ""),
                    "downloadId": download_id,
                }
            ],
        }
        pst, presp = client.request_json("/api/v3/command", method="POST", payload=cmd_payload)
        if pst in (200, 201):
            logger.info("Radarr IMPORTED '%s' -> '%s'", title_label, movie_obj.get("title"))
            summary["imported"].append({"title": title_label, "target": movie_obj.get("title"), "dry_run": False})
        else:
            logger.warning("Radarr ManualImport failed for '%s': HTTP %s (%s)", title_label, pst, str(presp)[:160])
            summary["skipped"].append({"title": title_label, "reason": f"command HTTP {pst}"})

    return summary


def _resolve_sonarr_episode_ids(client: ArrClient, series_id: int, f: Dict[str, Any], queue_ep_id: Optional[int], ep_cache: Dict[int, List[Dict[str, Any]]]) -> List[int]:
    eps = f.get("episodes") or []
    ids = [int(ep["id"]) for ep in eps if isinstance(ep, dict) and ep.get("id")]
    if ids:
        return ids
    match = _EPISODE_TAG_RE.search(str(f.get("relativePath") or f.get("name") or ""))
    if match:
        season_num, ep_num = int(match.group(1)), int(match.group(2))
        if series_id not in ep_cache:
            st, data = client.request_json(f"/api/v3/episode?seriesId={series_id}")
            ep_cache[series_id] = data if st == 200 and isinstance(data, list) else []
        for ep in ep_cache[series_id]:
            if ep.get("seasonNumber") == season_num and ep.get("episodeNumber") == ep_num and ep.get("id"):
                return [int(ep["id"])]
    return [int(queue_ep_id)] if queue_ep_id else []


def process_sonarr(client: ArrClient, dry_run: bool, logger: logging.Logger) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"app": "sonarr", "checked": 0, "imported": [], "skipped": []}
    st, qdata = client.request_json("/api/v3/queue?pageSize=100&includeUnknownSeriesItems=true")
    if st != 200 or not isinstance(qdata, dict):
        logger.warning("Sonarr queue query failed (HTTP %s)", st)
        summary["error"] = f"HTTP {st}"
        return summary

    series_cache: Dict[int, Dict[str, Any]] = {}
    ep_cache: Dict[int, List[Dict[str, Any]]] = {}
    seen_download_ids = set()

    for record in qdata.get("records") or []:
        if not queue_item_needs_manual_import(record):
            continue
        download_id = str(record["downloadId"])
        if download_id in seen_download_ids:
            continue
        seen_download_ids.add(download_id)
        summary["checked"] += 1
        title_label = str(record.get("title") or download_id)

        mst, files = client.request_json(
            f"/api/v3/manualimport?downloadId={urllib.parse.quote(download_id)}&filterExistingFiles=true"
        )
        if mst != 200 or not isinstance(files, list):
            summary["skipped"].append({"title": title_label, "reason": f"manualimport HTTP {mst}"})
            continue

        video_files = [f for f in files if isinstance(f, dict) and is_video_non_sample(str(f.get("path") or ""))]
        if not video_files:
            summary["skipped"].append({"title": title_label, "reason": "0 video files remaining"})
            continue

        import_files = []
        target_series: Optional[Dict[str, Any]] = None
        skip_reason = ""

        for f in video_files:
            if not only_allowed_rejections(f.get("rejections")):
                skip_reason = f"rejected: {f.get('rejections')}"
                break
            series_obj = f.get("series") if isinstance(f.get("series"), dict) else None
            series_id = (series_obj or {}).get("id") or record.get("seriesId")
            if not series_id:
                skip_reason = "no seriesId"
                break
            if series_obj is None:
                if int(series_id) not in series_cache:
                    sst, sdata = client.request_json(f"/api/v3/series/{int(series_id)}")
                    if sst == 200 and isinstance(sdata, dict):
                        series_cache[int(series_id)] = sdata
                series_obj = series_cache.get(int(series_id))
            if not series_obj or not title_matches_release(
                series_obj,
                str(f.get("relativePath") or ""),
                str(f.get("name") or ""),
                str(f.get("folderName") or ""),
                str(record.get("title") or ""),
            ):
                skip_reason = "series title verification mismatch"
                break

            queue_ep = record.get("episodeId") if len(video_files) == 1 else None
            ep_ids = _resolve_sonarr_episode_ids(client, int(series_id), f, queue_ep, ep_cache)
            if not ep_ids:
                skip_reason = "could not determine episodeIds"
                break

            target_series = series_obj
            import_files.append(
                {
                    "path": f["path"],
                    "folderName": f.get("folderName") or Path(str(f["path"])).parent.name,
                    "seriesId": int(series_id),
                    "episodeIds": ep_ids,
                    "quality": f.get("quality"),
                    "languages": f.get("languages") or [{"id": 1, "name": "English"}],
                    "releaseGroup": f.get("releaseGroup", ""),
                    "indexerFlags": f.get("indexerFlags", 0),
                    "releaseType": f.get("releaseType") or ("SingleEpisode" if len(video_files) == 1 else "MultiEpisode"),
                    "downloadId": download_id,
                }
            )

        if skip_reason or not import_files:
            summary["skipped"].append({"title": title_label, "reason": skip_reason or "no importable files"})
            continue

        if dry_run:
            logger.info("[DRY-RUN] Sonarr WOULD IMPORT %d file(s) for '%s'", len(import_files), (target_series or {}).get("title"))
            summary["imported"].append({"title": title_label, "target": (target_series or {}).get("title"), "files": len(import_files), "dry_run": True})
            continue

        pst, presp = client.request_json(
            "/api/v3/command",
            method="POST",
            payload={"name": "ManualImport", "importMode": "auto", "files": import_files},
        )
        if pst in (200, 201):
            logger.info("Sonarr IMPORTED %d file(s) for '%s'", len(import_files), (target_series or {}).get("title"))
            summary["imported"].append({"title": title_label, "target": (target_series or {}).get("title"), "files": len(import_files), "dry_run": False})
        else:
            logger.warning("Sonarr ManualImport failed for '%s': HTTP %s (%s)", title_label, pst, str(presp)[:160])
            summary["skipped"].append({"title": title_label, "reason": f"command HTTP {pst}"})

    return summary


def resolve_instances(args: argparse.Namespace) -> Tuple[Optional[ArrClient], Optional[ArrClient]]:
    config_dir = Path(args.config_dir) if args.config_dir else None
    radarr_key = args.radarr_key or (read_api_key_from_config(config_dir, "radarr") if config_dir else "")
    sonarr_key = args.sonarr_key or (read_api_key_from_config(config_dir, "sonarr") if config_dir else "")
    radarr = ArrClient("radarr", args.radarr_url, radarr_key) if radarr_key and args.radarr_url else None
    sonarr = ArrClient("sonarr", args.sonarr_url, sonarr_key) if sonarr_key and args.sonarr_url else None
    return radarr, sonarr


def run_once(args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
    radarr, sonarr = resolve_instances(args)
    results: Dict[str, Any] = {"radarr": None, "sonarr": None}
    if radarr is not None:
        results["radarr"] = process_radarr(radarr, args.dry_run, logger)
    if sonarr is not None:
        results["sonarr"] = process_sonarr(sonarr, args.dry_run, logger)
    if radarr is None and sonarr is None:
        logger.warning("No Radarr or Sonarr API credentials found; nothing checked.")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-import safe, title-verified Radarr/Sonarr queue holds stuck on Manual Import Required."
    )
    parser.add_argument("--config-dir", default=os.getenv("CONFIG_DIR", ""), help="Appdata dir holding radarr/sonarr config.xml")
    parser.add_argument("--radarr-url", default=os.getenv("RADARR_URL", "http://127.0.0.1:7878"))
    parser.add_argument("--radarr-key", default=os.getenv("RADARR_API_KEY", ""))
    parser.add_argument("--sonarr-url", default=os.getenv("SONARR_URL", "http://127.0.0.1:8989"))
    parser.add_argument("--sonarr-key", default=os.getenv("SONARR_API_KEY", ""))
    parser.add_argument("--dry-run", action="store_true", help="Report matches without triggering ManualImport")
    parser.add_argument("--once", action="store_true", help="Run a single queue check and exit (default)")
    parser.add_argument("--loop", action="store_true", help="Run continuously every --interval seconds")
    parser.add_argument("--interval", type=int, default=120, help="Poll interval in seconds when --loop is set")
    parser.add_argument("--log-file", default="", help="Optional rotating log file path (1 MB max, 2 backups)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout")
    args = parser.parse_args()

    logger = setup_logger(args.log_file, args.verbose)
    if args.loop and not args.once:
        interval = max(15, args.interval)
        while True:
            try:
                run_once(args, logger)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected auto_import cycle error: %s", exc)
            time.sleep(interval)

    summary = run_once(args, logger)
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
