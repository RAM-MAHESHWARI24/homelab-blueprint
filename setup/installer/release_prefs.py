"""
Release preferences: the Setup Wizard's "Release preferences" step.

The answers live in the installer config (config.json) under the media_* keys below,
are rendered into mediaserver.env as MEDIA_* (env_manager), and are applied by
`apps/mediaserver/scripts/wire_arr.py profiles apply` at the end of the media module.

Upgrades: a config written before this step existed has none of these keys. When the
install already has a mediaserver.env, its MEDIA_* values are kept, and a missing
MEDIA_PROFILES means "off": an existing server may run Recyclarr or hand-made profiles,
and the pack must not start overwriting them on a re-run. Its owner opts in with
`profiles migrate` (docs/MEDIA_RELEASE_PROFILES.md). Standard library only (ADR-0002).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROFILE_CHOICES = ("compact", "family")
CODEC_CHOICES = ("hevc", "av1", "dv")
SEEDING_CHOICES = ("while-it-helps", "off")
STUCK_CHOICES = ("replace", "off")
DEFAULTS: Dict[str, Any] = {
    "media_profiles": True,
    "media_second_language": "",
    "media_default_profile": "compact",
    "media_codecs": ["hevc"],
    "media_seeding": "while-it-helps",
    "media_stuck_downloads": "replace",
}
# config key -> mediaserver.env key
ENV_KEYS = {
    "media_profiles": "MEDIA_PROFILES",
    "media_second_language": "MEDIA_SECOND_LANGUAGE",
    "media_default_profile": "MEDIA_DEFAULT_PROFILE",
    "media_codecs": "MEDIA_CODECS",
    "media_seeding": "MEDIA_SEEDING",
    "media_stuck_downloads": "MEDIA_STUCK_DOWNLOADS",
}
# Headless-only switch (not a wizard question): off for private trackers.
EXTRA_ENV_KEYS = {"media_public_trackers": "MEDIA_PUBLIC_TRACKERS"}


def supported_languages(repo_root: Path) -> List[str]:
    path = Path(repo_root) / "apps" / "mediaserver" / "profiles" / "languages.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [lang["name"] for lang in data.get("languages", [])]
    except (OSError, ValueError, KeyError):
        return []


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "on", "true", "yes")


def _codecs(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = str(value or "").split(",")
    return [c.strip().lower() for c in items if c.strip()]


def from_env(env: Dict[str, str]) -> Dict[str, Any]:
    """Config values recovered from an existing mediaserver.env (upgrades)."""
    out: Dict[str, Any] = {"media_profiles": _bool(env.get("MEDIA_PROFILES", "off"))}
    for key, env_key in ENV_KEYS.items():
        if key == "media_profiles" or env_key not in env:
            continue
        out[key] = _codecs(env[env_key]) if key == "media_codecs" else env[env_key]
    if "MEDIA_PUBLIC_TRACKERS" in env:
        out["media_public_trackers"] = _bool(env["MEDIA_PUBLIC_TRACKERS"])
    return out


def normalize_release_prefs(config: Dict[str, Any], repo_root: Path,
                            existing_env: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Any], List[str]]:
    """Returns (normalized media_* values, errors). Keys absent from `config` come from
    an existing install's env file when there is one, otherwise from DEFAULTS."""
    prefs = dict(DEFAULTS)
    if existing_env is not None and not any(k in config for k in ENV_KEYS):
        prefs.update(from_env(existing_env))
    for key in list(ENV_KEYS) + list(EXTRA_ENV_KEYS):
        if key in config and config[key] is not None:
            prefs[key] = config[key]

    errors: List[str] = []
    prefs["media_profiles"] = _bool(prefs["media_profiles"])
    prefs["media_public_trackers"] = _bool(prefs.get("media_public_trackers", True))
    language = str(prefs.get("media_second_language") or "").strip()
    if language.lower() in ("none", "off"):
        language = ""
    known = supported_languages(repo_root)
    match = next((name for name in known if name.lower() == language.lower()), None)
    if language and match is None:
        errors.append(f"media_second_language '{language}' is not supported (choose from: {', '.join(known) or 'none found'})")
    prefs["media_second_language"] = match or ""

    profile = str(prefs.get("media_default_profile") or "").strip().lower()
    if profile not in PROFILE_CHOICES:
        errors.append(f"media_default_profile must be one of {', '.join(PROFILE_CHOICES)}")
    elif profile == "family" and not prefs["media_second_language"]:
        errors.append("media_default_profile 'family' (1080p Family) needs a second audio language")
    prefs["media_default_profile"] = profile

    codecs = _codecs(prefs.get("media_codecs"))
    bad = [c for c in codecs if c not in CODEC_CHOICES]
    if bad:
        errors.append(f"media_codecs: unknown {', '.join(bad)} (choose from {', '.join(CODEC_CHOICES)})")
    prefs["media_codecs"] = [c for c in CODEC_CHOICES if c in codecs]

    for key, choices in (("media_seeding", SEEDING_CHOICES), ("media_stuck_downloads", STUCK_CHOICES)):
        value = str(prefs.get(key) or "").strip().lower()
        if value not in choices:
            errors.append(f"{key} must be one of {', '.join(choices)}")
        prefs[key] = value
    return prefs, errors
