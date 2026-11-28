#!/usr/bin/env python3
"""
The repo-owned release profile pack (apps/mediaserver/profiles/): loading, rendering
for one app and one second language, and comparing against what an app holds.

Pure functions with no network access, so they are unit-tested directly; the HTTP side
lives in wire_arr.py (`profiles apply|check|migrate`). Standard library only.

Terms:
  * blueprint format  - a custom format defined in profiles/custom_formats/*.json, with
                        {LANG} (language name) and {LANG_RX} (title regex) placeholders
  * vendored format   - a TRaSH Guides custom format kept byte-for-byte under
                        profiles/trash/<app>/, renamed with a pack prefix (pack.json)
  * neutral format    - {"name", "specifications": [{implementation, negate, required,
                        fields: {name: value}}]} before app-specific ids are filled in
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PACK_DIR = Path(__file__).resolve().parent.parent / "profiles"
APPS = ("radarr", "sonarr")
CODECS = ("hevc", "av1", "dv")
SEEDING_CHOICES = ("while-it-helps", "off")
NEVER_MATCH = "(?!)"  # .NET and Python both accept this: a regex that matches nothing
BLOCK = -10000
LANGUAGE_IDS_BUILTIN = {"any": -1, "original": -2}
SEP = r"[ ._+&,/|()\[\]-]{1,4}"


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_pack(pack_dir: Path = PACK_DIR) -> Dict[str, Any]:
    """Reads every pack file. Raises ValueError with the file name when one is malformed."""
    pack_dir = Path(pack_dir)
    out: Dict[str, Any] = {"dir": pack_dir}
    try:
        out["meta"] = _read_json(pack_dir / "pack.json")
        out["languages"] = _read_json(pack_dir / "languages.json")
        out["settings"] = _read_json(pack_dir / "settings.json")
        out["formats"] = [_read_json(p) | {"_file": p.name} for p in sorted((pack_dir / "custom_formats").glob("*.json"))]
        out["profiles"] = {app: [_read_json(p) | {"_file": p.name} for p in sorted((pack_dir / "profiles").glob(f"{app}-*.json"))] for app in APPS}
        out["quality_definitions"] = {app: _read_json(pack_dir / "quality_definitions" / f"{app}.json") for app in APPS}
        out["vendored"] = {}
        for rel, info in out["meta"]["trash"]["vendored"].items():
            out["vendored"][rel] = (info, _read_json(pack_dir / "trash" / rel))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"profile pack unreadable: {exc}") from exc
    return out


# ------------------------------------------------------------------ languages
def language_names(pack: Dict[str, Any]) -> List[str]:
    return [lang["name"] for lang in pack["languages"]["languages"]]


def find_language(pack: Dict[str, Any], name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not name or str(name).strip().lower() in ("", "none", "off"):
        return None
    wanted = str(name).strip().lower()
    for lang in pack["languages"]["languages"]:
        if lang["name"].lower() == wanted:
            return lang
    raise ValueError(f"unsupported second language '{name}' (supported: {', '.join(language_names(pack))})")


def language_regex(pack: Dict[str, Any], lang: Optional[Dict[str, Any]]) -> str:
    """Title regex for one language. Short tokens that are also ordinary words (tel, mal,
    kan) only count when another language marker sits right next to them."""
    if lang is None:
        return NEVER_MATCH
    parts = [r"\b(?:" + "|".join(re.escape(t) for t in lang["tokens"]) + r")\b"]
    adjacent = lang.get("adjacent_tokens") or []
    if adjacent:
        markers = sorted({m for m in pack["languages"]["markers"]} | set(lang["tokens"]), key=lambda m: (-len(m), m))
        m_rx = "(?:" + "|".join(re.escape(m) for m in markers) + ")"
        for tok in adjacent:
            t = re.escape(tok)
            parts.append(rf"\b{m_rx}{SEP}{t}\b")
            parts.append(rf"\b{t}{SEP}{m_rx}\b")
    return "|".join(parts)


# ---------------------------------------------------------------- formatting
def _sub(value: Any, lang_name: str, lang_rx: str) -> Any:
    if isinstance(value, str):
        return value.replace("{LANG_RX}", lang_rx).replace("{LANG}", lang_name)
    return value


def render_name(template: str, lang: Optional[Dict[str, Any]], fallback: Optional[str] = None) -> str:
    if lang is None and "{LANG}" in template:
        return fallback or template.replace("{LANG}", "").strip()
    return template.replace("{LANG}", lang["name"] if lang else "")


def _vendored_to_neutral(info: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    specs = []
    for s in data.get("specifications", []):
        fields = s.get("fields") or {}
        if isinstance(fields, list):  # API shape, in case upstream ever changes
            fields = {f["name"]: f.get("value") for f in fields}
        specs.append({"name": s.get("name", ""), "implementation": s["implementation"], "negate": bool(s.get("negate")),
                      "required": bool(s.get("required")), "fields": dict(fields)})
    return {"name": info["name"], "includeCustomFormatWhenRenaming": False, "specifications": specs,
            "trash_id": info.get("trash_id"), "codec": info.get("codec"), "source": f"trash/{info['source']}"}


def render_formats(pack: Dict[str, Any], app: str, lang: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every custom format the pack wants in `app` for this language, in neutral form."""
    lang_name = lang["name"] if lang else ""
    lang_rx = language_regex(pack, lang)
    out: List[Dict[str, Any]] = []
    for fmt in pack["formats"]:
        if app not in fmt.get("apps", APPS):
            continue
        if fmt.get("when") == "language" and lang is None:
            continue
        specs = []
        for s in fmt["specifications"]:
            if s.get("language_only") and lang is None:
                continue
            fields = {}
            for k, v in s["fields"].items():
                if isinstance(v, dict) and app in v:
                    v = v[app]
                fields[k] = _sub(v, lang_name, lang_rx)
            specs.append({"name": _sub(s.get("name", ""), lang_name, lang_rx), "implementation": s["implementation"],
                          "negate": bool(s.get("negate")), "required": bool(s.get("required")), "fields": fields})
        out.append({"name": render_name(fmt["name"], lang, fmt.get("name_without_language")),
                    "includeCustomFormatWhenRenaming": bool(fmt.get("includeCustomFormatWhenRenaming", False)),
                    "specifications": specs, "source": f"custom_formats/{fmt['_file']}"})
    for rel, (info, data) in pack["vendored"].items():
        if rel.split("/", 1)[0] == app:
            out.append(_vendored_to_neutral(info, data))
    names = [f["name"] for f in out]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate custom format names for {app}: {sorted(dupes)}")
    return out


def owned_format(pack: Dict[str, Any], name: str) -> bool:
    return any(name.startswith(p) for p in pack["meta"]["owned_prefixes"])


def render_profiles(pack: Dict[str, Any], app: str, lang: Optional[Dict[str, Any]], codecs: Iterable[str]) -> List[Dict[str, Any]]:
    """Profiles for `app` with scores keyed by rendered format names. A profile that
    requires a language (1080p Family) is skipped without one. Codec choices turn blocks
    into neutral scores (AV1, DV allowed) or block HEVC when the players cannot decode it."""
    codecs = set(codecs)
    codec_formats = {info["name"]: info.get("codec") for rel, (info, _) in pack["vendored"].items()
                     if rel.startswith(app + "/") and info.get("codec")}
    templates = {f["name"]: f for f in pack["formats"]}
    out = []
    for prof in pack["profiles"][app]:
        if prof.get("requires_language") and lang is None:
            continue
        scores: Dict[str, int] = {}
        for template_name, score in prof["scores"].items():
            tpl = templates.get(template_name)
            if tpl is not None and tpl.get("when") == "language" and lang is None:
                continue
            name = render_name(template_name, lang, tpl.get("name_without_language") if tpl else None)
            codec = codec_formats.get(name)
            if codec == "hevc" and "hevc" not in codecs:
                score = BLOCK
            elif codec in ("av1", "dv") and codec in codecs:
                score = 0
            scores[name] = int(score)
        upgrade = dict(prof["upgrade"])
        if lang is None and "until_score_without_language" in upgrade:
            upgrade["until_score"] = upgrade["until_score_without_language"]
        upgrade.pop("until_score_without_language", None)
        out.append({"name": prof["name"], "language": prof.get("language"), "upgrade": upgrade,
                    "min_format_score": int(prof["min_format_score"]),
                    "min_upgrade_format_score": int(prof["min_upgrade_format_score"]),
                    "qualities": prof["qualities"], "scores": scores, "source": f"profiles/{prof['_file']}"})
    return out


# --------------------------------------------------------------- API payloads
def language_id(app_languages: List[Dict[str, Any]], name: str) -> Optional[int]:
    key = str(name).strip().lower()
    if key in LANGUAGE_IDS_BUILTIN:
        return LANGUAGE_IDS_BUILTIN[key]
    for lang in app_languages or []:
        if str(lang.get("name", "")).lower() == key:
            return int(lang["id"])
    return None


def to_api_format(fmt: Dict[str, Any], app_languages: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
    """Neutral format -> API payload. Language names become ids; a language the app does
    not know drops that condition (returned as a note) so the format still works on title tokens."""
    notes: List[str] = []
    specs = []
    for s in fmt["specifications"]:
        fields = dict(s["fields"])
        if s["implementation"] == "LanguageSpecification":
            value = fields.get("value")
            lid = value if isinstance(value, int) else language_id(app_languages, value)
            if lid is None:
                notes.append(f"{fmt['name']}: the app has no language '{value}'; that condition is left out")
                continue
            fields["value"] = lid
            fields.setdefault("exceptLanguage", False)
        specs.append({"name": s.get("name") or s["implementation"], "implementation": s["implementation"],
                      "negate": s["negate"], "required": s["required"],
                      "fields": [{"name": k, "value": v} for k, v in fields.items()]})
    return {"name": fmt["name"], "includeCustomFormatWhenRenaming": fmt.get("includeCustomFormatWhenRenaming", False),
            "specifications": specs}, notes


def _num(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def _spec_key(spec: Dict[str, Any], field_names: Optional[Iterable[str]] = None) -> Tuple:
    fields = spec.get("fields") or []
    fmap = {f["name"]: f.get("value") for f in fields} if isinstance(fields, list) else dict(fields)
    names = sorted(field_names if field_names is not None else fmap)
    return (spec["implementation"], bool(spec.get("negate")), bool(spec.get("required")),
            tuple((n, _num(fmap.get(n))) for n in names))


def diff_format(live: Dict[str, Any], desired: Dict[str, Any]) -> List[str]:
    """Differences that change matching (condition names are cosmetic and ignored)."""
    want = sorted(_spec_key(s) for s in desired["specifications"])
    names = {f["name"] for s in desired["specifications"] for f in s["fields"]}
    have = sorted(_spec_key(s, [n for n in names if any(f["name"] == n for f in (s.get("fields") or []))])
                  for s in live.get("specifications", []))
    out = []
    if want != have:
        out.append("conditions differ")
    if bool(live.get("includeCustomFormatWhenRenaming")) != bool(desired.get("includeCustomFormatWhenRenaming")):
        out.append("rename flag differs")
    return out


def _item_name(item: Dict[str, Any]) -> str:
    return item.get("name") or (item.get("quality") or {}).get("name", "")


def _allowed_ladder(items: List[Dict[str, Any]]) -> List[frozenset]:
    """Allowed entries highest first; each entry is the set of quality names it holds."""
    ladder = []
    for item in reversed(items or []):
        if not item.get("allowed"):
            continue
        if item.get("items"):
            names = frozenset(_item_name(i) for i in item["items"] if i.get("allowed", True))
        else:
            names = frozenset([_item_name(item)])
        ladder.append(names)
    return ladder


def _cutoff_set(profile: Dict[str, Any]) -> frozenset:
    cutoff = profile.get("cutoff")
    for item in profile.get("items") or []:
        if item.get("items") and item.get("id") == cutoff:
            return frozenset(_item_name(i) for i in item["items"])
        if not item.get("items") and (item.get("quality") or {}).get("id") == cutoff:
            return frozenset([_item_name(item)])
    return frozenset()


def build_profile_payload(desired: Dict[str, Any], app: str, quality_defs: List[Dict[str, Any]],
                          live_formats: List[Dict[str, Any]], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A full quality profile object: every quality listed lowest to highest (as the API
    wants), the pack's group allowed at the top, scores for every custom format in the app."""
    by_name = {qd["quality"]["name"]: qd for qd in quality_defs}
    ordered = sorted(quality_defs, key=lambda qd: qd.get("weight", 0))
    items: List[Dict[str, Any]] = []
    grouped: Dict[str, Dict[str, Any]] = {}
    for gid, entry in enumerate(reversed(desired["qualities"]), start=1000):
        names = entry["qualities"] if "group" in entry else [entry["quality"]]
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(f"{app} has no quality named {missing}")
        if "group" in entry:
            grouped[entry["group"]] = {"id": gid, "name": entry["group"], "allowed": True,
                                       "items": [{"quality": by_name[n]["quality"], "items": [], "allowed": True} for n in reversed(names)]}
        else:
            grouped[entry["quality"]] = {"quality": by_name[entry["quality"]]["quality"], "items": [], "allowed": True}
    in_profile = {n for e in desired["qualities"] for n in (e["qualities"] if "group" in e else [e["quality"]])}
    for qd in ordered:
        if qd["quality"]["name"] not in in_profile:
            items.append({"quality": qd["quality"], "items": [], "allowed": False})
    for entry in reversed(desired["qualities"]):  # lowest allowed entry first, highest last
        items.append(grouped[entry.get("group") or entry["quality"]])
    until = desired["upgrade"]["until_quality"]
    cutoff_item = grouped[until]
    cutoff = cutoff_item.get("id") if "id" in cutoff_item else cutoff_item["quality"]["id"]

    old_scores = {fi.get("format"): fi.get("score", 0) for fi in (existing or {}).get("formatItems", [])}
    format_items = []
    for f in sorted(live_formats, key=lambda f: f["id"]):
        score = desired["scores"].get(f["name"], old_scores.get(f["id"], 0))
        format_items.append({"format": f["id"], "name": f["name"], "score": int(score)})

    payload = dict(existing or {})
    payload.update({
        "name": desired["name"], "upgradeAllowed": bool(desired["upgrade"]["allowed"]), "cutoff": cutoff, "items": items,
        "minFormatScore": desired["min_format_score"], "cutoffFormatScore": int(desired["upgrade"]["until_score"]),
        "minUpgradeFormatScore": desired["min_upgrade_format_score"], "formatItems": format_items,
    })
    if app == "radarr" and desired.get("language"):
        payload["language"] = {"id": LANGUAGE_IDS_BUILTIN.get(desired["language"].lower(), -1), "name": desired["language"]}
    return payload


def diff_profile(live: Dict[str, Any], desired_payload: Dict[str, Any], pack: Dict[str, Any], desired_scores: Dict[str, int]) -> List[str]:
    out = []
    for key, label in (("upgradeAllowed", "upgrades allowed"), ("minFormatScore", "minimum score"),
                       ("cutoffFormatScore", "upgrade-until score"), ("minUpgradeFormatScore", "minimum upgrade increment")):
        if live.get(key) != desired_payload.get(key):
            out.append(f"{label}: {live.get(key)} -> {desired_payload.get(key)}")
    if "language" in desired_payload and (live.get("language") or {}).get("id") != desired_payload["language"]["id"]:
        out.append(f"language: {(live.get('language') or {}).get('name')} -> {desired_payload['language']['name']}")
    if _allowed_ladder(live.get("items")) != _allowed_ladder(desired_payload["items"]):
        out.append("quality order differs (wanted: one merged HD group at the top)")
    if _cutoff_set(live) != _cutoff_set(desired_payload):
        out.append("upgrade-until quality differs")
    live_scores = {fi.get("name"): fi.get("score", 0) for fi in live.get("formatItems", [])}
    for name, score in sorted(desired_scores.items()):
        if live_scores.get(name, 0) != score:
            out.append(f"score {name}: {live_scores.get(name, 0)} -> {score}")
    for name, score in sorted(live_scores.items()):
        if score and name not in desired_scores and not owned_format(pack, name):
            out.append(f"note: non-pack format {name} scores {score} (left as is)")
    return out


def quality_definition_changes(pack: Dict[str, Any], app: str, live_defs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Returns (updated definition objects, human-readable differences)."""
    wanted = pack["quality_definitions"][app]["qualities"]
    updated, notes = [], []
    for qd in live_defs:
        name = qd["quality"]["name"]
        if name not in wanted:
            continue
        w = wanted[name]
        cur = (_num(qd.get("minSize")), _num(qd.get("preferredSize")), _num(qd.get("maxSize")))
        new = (_num(w["min"]), _num(w["preferred"]), _num(w["max"]))
        if cur != new:
            obj = dict(qd)
            obj.update({"minSize": w["min"], "preferredSize": w["preferred"], "maxSize": w["max"]})
            updated.append(obj)
            notes.append(f"{name}: {_fmt_size(cur)} -> {_fmt_size(new)} MB/min")
    return updated, notes


def _fmt_size(t: Tuple) -> str:
    return "/".join("-" if v is None else f"{v:g}" for v in t)


# ------------------------------------------------------------------ settings
def parse_codecs(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = [v for v in str(value or "").replace(" ", "").split(",")]
    out = []
    for v in items:
        v = v.strip().lower()
        if not v:
            continue
        if v not in CODECS:
            raise ValueError(f"unknown codec '{v}' (choose from {', '.join(CODECS)})")
        if v not in out:
            out.append(v)
    return out


def merge_csv(current: str, wanted: Iterable[str]) -> str:
    """Comma list without spaces: Radarr splits on ',' and does not trim (Appendix K item 2)."""
    have = [x.strip() for x in str(current or "").split(",") if x.strip()]
    lower = {x.lower() for x in have}
    for w in wanted:
        if w.lower() not in lower:
            have.append(w)
            lower.add(w.lower())
    return ",".join(have)


def merge_lines(current: str, wanted: Iterable[str]) -> str:
    have = [x.strip() for x in str(current or "").replace(";", "\n").splitlines() if x.strip()]
    for w in wanted:
        if w not in have:
            have.append(w)
    return "\n".join(have)
