"""
Tests for the repo-owned release profile pack (profiles/ + scripts/profile_pack.py +
`wire_arr.py profiles`).

* Pack invariants: files parse, quality order, reachable scores, ownership prefixes.
* Release-title corpus: real titles seen on a live server (plus marked synthetic ones).
  Regexes are evaluated for real with Python's `re`; what the apps parse themselves
  (resolution, source, languages, size, release type) is recorded per title as the
  app reported it or as its parser behaves, and fed to the conditions.
* apply/check/migrate against in-memory fakes of Radarr, Sonarr, Prowlarr and qBittorrent.

Standard library only.
"""

import argparse
import copy
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import profile_pack as pp  # noqa: E402
import wire_arr  # noqa: E402

PACK = pp.load_pack()
HINDI = pp.find_language(PACK, "Hindi")

NAMED = "Lang · Hindi + Original (named)"
DUAL = "Lang · Hindi + Dual/Multi tag"
ONLY = "Lang · Hindi only (original missing)"
NOTORIG = "Lang · Not Original or Hindi"
LANG_FORMATS = {NAMED, DUAL, ONLY, NOTORIG}
RES = "Res · 1080p"
HEVC = "Eff · HEVC"
BD, WEBDL, WEBRIP = "Src · Bluray", "Src · WEB-DL", "Src · WEBRip"
BAND, OVER = "Size · Compact band", "Size · Oversized"

# Quality names as the apps list them (lowest first), from GET /qualitydefinition.
RADARR_QUALITIES = ["Unknown", "WORKPRINT", "CAM", "TELESYNC", "TELECINE", "REGIONAL", "DVDSCR", "SDTV", "DVD", "DVD-R",
                    "WEBDL-480p", "WEBRip-480p", "Bluray-480p", "Bluray-576p", "HDTV-720p", "WEBDL-720p", "WEBRip-720p",
                    "Bluray-720p", "HDTV-1080p", "WEBDL-1080p", "WEBRip-1080p", "Bluray-1080p", "Remux-1080p", "HDTV-2160p",
                    "WEBDL-2160p", "WEBRip-2160p", "Bluray-2160p", "Remux-2160p", "BR-DISK", "Raw-HD"]
SONARR_QUALITIES = ["Unknown", "SDTV", "WEBRip-480p", "WEBDL-480p", "DVD", "Bluray-480p", "Bluray-576p", "HDTV-720p",
                    "HDTV-1080p", "Raw-HD", "WEBRip-720p", "WEBDL-720p", "Bluray-720p", "WEBRip-1080p", "WEBDL-1080p",
                    "Bluray-1080p", "Bluray-1080p Remux", "HDTV-2160p", "WEBRip-2160p", "WEBDL-2160p", "Bluray-2160p",
                    "Bluray-2160p Remux"]
QUALITIES = {"radarr": RADARR_QUALITIES, "sonarr": SONARR_QUALITIES}
SOURCE_ENUM = {"radarr": {9: "bluray", 7: "webdl", 8: "webrip", 6: "tv", 0: "unknown"},
               "sonarr": {6: "bluray", 3: "webdl", 4: "webrip", 1: "tv", 0: "unknown"}}


# ------------------------------------------------------------------ evaluator
# .NET allows variable-width look-behind and Python does not. The constructs TRaSH uses
# are rewritten into equivalents for a search: (?<!A|B) is (?<!A)(?<!B), and a leading
# (?<=P) can consume P instead, because re.search tries every starting position.
DOTNET_LOOKBEHIND = {
    r"(?<!HD[._ -]|HD)": r"(?<!HD[._ -])(?<!HD)",   # BR-DISK
    r"(?<=\bS\d+\b)": r"\bS\d+\b",                   # Sonarr Extras
    r"(?<=\b\d{3,4}p\b)": r"\b\d{3,4}p\b",           # Sonarr Upscaled
}


def _compile(rx):
    for dotnet, python in DOTNET_LOOKBEHIND.items():
        rx = rx.replace(dotnet, python)
    return re.compile(rx, re.IGNORECASE)


def spec_matches(app, spec, rel):
    impl, f = spec["implementation"], spec["fields"]
    if impl == "ReleaseTitleSpecification":
        hit = bool(_compile(f["value"]).search(rel["title"]))
    elif impl == "ReleaseGroupSpecification":
        hit = bool(rel.get("group")) and bool(_compile(f["value"]).search(rel["group"]))
    elif impl == "LanguageSpecification":
        want = rel["original"] if f["value"] == "Original" else f["value"]
        hit = want in (rel.get("languages") or [rel["original"]])
    elif impl == "ResolutionSpecification":
        hit = rel.get("resolution") == f["value"]
    elif impl == "SourceSpecification":
        hit = SOURCE_ENUM[app].get(f["value"]) == rel.get("source")
    elif impl == "SizeSpecification":
        size = rel.get("size_gb")
        hit = size is not None and f["min"] < size <= f["max"]
    elif impl == "ReleaseTypeSpecification":
        hit = rel.get("release_type") == f["value"]
    else:
        raise AssertionError(f"no evaluator for {impl}")
    return hit != spec["negate"]


def format_matches(app, fmt, rel):
    """Radarr/Sonarr CustomFormatCalculationService: conditions are grouped by type; a
    group fails when a required condition fails or when none of its conditions match."""
    groups = {}
    for spec in fmt["specifications"]:
        groups.setdefault(spec["implementation"], []).append((spec["required"], spec_matches(app, spec, rel)))
    return all(not any(req and not ok for req, ok in g) and any(ok for _, ok in g) for g in groups.values())


def matched(app, rel, lang=HINDI):
    return {f["name"] for f in pp.render_formats(PACK, app, lang) if format_matches(app, f, rel)}


def profile(app, name, lang=HINDI, codecs=("hevc",)):
    return next(p for p in pp.render_profiles(PACK, app, lang, codecs) if p["name"] == name)


def score(app, rel, profile_name, lang=HINDI, codecs=("hevc",)):
    scores = profile(app, profile_name, lang, codecs)["scores"]
    return sum(scores.get(n, 0) for n in matched(app, rel, lang))


def in_group(app, quality, profile_name="1080p Compact"):
    return any(quality in e.get("qualities", [e.get("quality")]) for e in profile(app, profile_name)["qualities"])


# --------------------------------------------------------------------- corpus
def R(n, title, original="English", languages=None, resolution=1080, source="unknown", quality=None, size_gb=None,
      group=None, release_type=None, app="radarr", lang=frozenset(), has=frozenset(), hasnot=frozenset(),
      rejected=False, quality_ok=True, below_minimum=False):
    if quality is None:
        names = {"bluray": "Bluray", "webdl": "WEBDL", "webrip": "WEBRip", "tv": "HDTV", "unknown": "HDTV"}
        quality = f"{names[source]}-{resolution}p" if resolution else "Unknown"
    if group is None:
        m = re.search(r"-([A-Za-z0-9]+)(?:\[[^\]]*\])?(?:\.mkv)?$", title)
        group = m.group(1) if m else None
    return {"n": n, "app": app, "title": title, "original": original, "languages": languages or [original],
            "resolution": resolution, "source": source, "quality": quality, "size_gb": size_gb, "group": group,
            "release_type": release_type, "lang": set(lang), "has": set(has), "hasnot": set(hasnot),
            "rejected": rejected, "quality_ok": quality_ok, "below_minimum": below_minimum}


# Appendix H of the Media Pipeline Reliability Plan. Languages are what Radarr/Sonarr
# parse: "hindi" and "eng"/"english" are recognised, "hin" and "Dual Audio" are not, and a
# title without any language falls back to the film's original language.
CORPUS = [
    R(1, "Goldfinger (1964) DS4K 1080p BDRip HEVC [Hindi English] DDP 5.1 – PeruGuy", languages=["Hindi", "English"],
      source="bluray", size_gb=5.67, group="", lang={NAMED}, has={RES, HEVC, BD, BAND}),
    R(2, "Goldfinger 1964 BDRip 1080p Dual Audio [ Hindi 2.0 Eng 5.1] Tariq Qureshi.mkv", languages=["Hindi", "English"],
      source="bluray", group="", lang={NAMED}, has={RES, BD}),
    R(3, "James Bond   Goldfinger (1964) 720p BluRay x264 Dual Audio [English + Hindi]   Bond93   TBI",
      languages=["English", "Hindi"], resolution=720, source="bluray", size_gb=1.0, group="", lang={NAMED}, has={BD}, hasnot={RES}),
    R(4, "Goldfinger (1964) | m-HD | 720p | Hindi | Eng | BHATTI87", languages=["Hindi", "English"], resolution=720,
      source="tv", group="", lang={NAMED}, quality_ok=False),
    R(5, "James Bond Goldfinger (1964) BRRip x264 AC3 [Dual Audio] [Hindi-", languages=["Hindi"], resolution=480,
      source="bluray", group="", lang={DUAL}, quality_ok=False),
    R(6, "James Bond   Goldfinger (1964) 720p BluRay Hindi DD 2.0   Esub ~AbhiSona~", languages=["Hindi"], resolution=720,
      source="bluray", size_gb=1.4, group="", lang={ONLY}, has={BD}, below_minimum=True),
    R(7, "James Bond 007-GoldFinger(1964)HDTVrip[Dual audio][Eng Hindi]Cur", languages=["English", "Hindi"], resolution=0,
      source="tv", quality="Unknown", group="", lang={NAMED}, quality_ok=False),
    R(8, "Goldfinger (James Bond 3) (1964) [MicroHD 1080p][DUAL]", lang=set(), has={RES}),
    R(9, "007 James Bond Goldfinger 1964 1080p BluRay x264 AC3 -Ozlem", source="bluray", has={"Junk · Banned uploaders"}, rejected=True),
    R(10, "Goldfinger 1964 1080p UHD Bluray OPUS 7 1 SDR AV1-WhiskeyJack", source="bluray", has={"Compat · AV1"}, rejected=True),
    R(11, "Goldfinger.1964.1080p.BluRay.DV.HDR.X265.DDP.7.1-Chivaman", source="bluray", has={HEVC, BD},
      hasnot={"Compat · DV w/o HDR fallback"}),
    R(12, "Goldfinger 1964 1080p UHD BluRay DD 5 1 Atmos DV HDR x265-HiDt", source="bluray", size_gb=25.7, has={HEVC, OVER}),
    R(13, "Goldfinger 1964 1080p NF WEB-DL DDP5 1 Atmos H 264-HDSWEB", source="webdl", size_gb=5.17, has={RES, WEBDL, BAND}),
    R(14, "Agente 007   Missione Goldfinger (1964) WEBRip 1080p HEVC AAC ITA ENG SUB ENG", languages=["Italian", "English"],
      source="webrip", group="", has={HEVC, WEBRIP}),
    R(15, "Goldfinger 1964 REPACK MULTi VFi 1080p HDLight AC3 5 1 H264-LiHDL", languages=["French"],
      has={"Fix · Repack/Proper"}),
    R(16, "Goldfinger (1964) 1080p BRRip x264 -YTS", source="bluray", size_gb=1.87, has={RES, BD}),
    R(17, "Goldfinger (1964)-JAMES BOND-Sean Connery-1080p-H264-AC 3 (DolbyDigital-5.1) & nickarad", source="tv", group="",
      has={RES}),
    R(18, "Goldfinger.1964.1080p.BluRay.REMUX-DDB", source="bluray", quality="Remux-1080p", quality_ok=False),
    R(19, "Casino Royale (2006) 1080p Rifftrax 6ch 2ch v2", has={"Junk · Commentary editions"}, rejected=True),
    R(20, "Drishyam the Conclusion (2026) 1080p WEBRip 5.1 x264 -YTS", original="Hindi", source="webrip", has={WEBRIP}),
    R(21, "Drishyam 2 (2022) Hindi 1080p WEB-DL DD5.1 ESub", original="Hindi", languages=["Hindi"], source="webdl",
      lang={NAMED}, has={WEBDL}),
    R(22, "Oppenheimer (2023) 1080p BluRay [Hindi DD5.1 + English DD5.1] x264 ESubs", languages=["Hindi", "English"],
      source="bluray", lang={NAMED}, has={BD}),
    R(23, "Movie.2023.1080p.AMZN.WEB-DL.DDP5.1.Hindi.English.x264-GRP", languages=["Hindi", "English"], source="webdl",
      lang={NAMED}, has={WEBDL}),
    R(24, "Kantara (2022) Dual Audio [Hindi + Kannada] 1080p WEB-DL", original="Kannada", languages=["Hindi", "Kannada"],
      source="webdl", lang={NAMED}),
    R(24.1, "Kantara (2022) Dual Audio [Hindi + Kannada] 1080p WEB-DL", original="Kannada", languages=["Hindi"],
      source="webdl", lang={DUAL}),
    R(25, "Pushpa 2 (2024) Multi Audio [Hindi Tamil Telugu Malayalam Kannada] 1080p WEB-DL", original="Telugu",
      languages=["Hindi", "Tamil", "Telugu", "Malayalam", "Kannada"], source="webdl", lang={NAMED}),
    R(25.1, "Pushpa 2 (2024) Multi Audio [Hindi Tamil Telugu Malayalam Kannada] 1080p WEB-DL", original="Telugu",
      languages=["Hindi", "Tamil", "Malayalam"], source="webdl", lang={DUAL}),
    R(26, "Vikram (2022) Hindi Dubbed 1080p WEB-DL", original="Tamil", languages=["Hindi"], source="webdl", lang={ONLY}),
    R(27, "Movie (2023) Hindi LiNE 1080p HQ HDTC x264", languages=["Hindi"],
      lang={ONLY}, has={"Junk · Line/cam audio", "Junk · Cam / PreDVD / S-Print"}, rejected=True),
    R(28, "Movie 2024 Hindi (Cleaned) 720p PreDVDRip", languages=["Hindi"], resolution=720, quality_ok=False,
      lang={ONLY}, has={"Junk · Line/cam audio", "Junk · Cam / PreDVD / S-Print"}, rejected=True),
    R(29, "The Thin Red Line (1998) Hindi Dual Audio 1080p BluRay", languages=["Hindi"], source="bluray", lang={DUAL},
      hasnot={"Junk · Line/cam audio"}),
    R(30, "Ben-Hur (1959) 1080p BluRay x264", source="bluray", group="", lang=set()),
    R(31, "Mar Adentro (2004) 1080p WEB-DL", original="Spanish", source="webdl", lang=set()),
    R(32, "Movie.2023.iTALiAN.1080p.WEB-DL.x264", languages=["Italian"], source="webdl", lang={NOTORIG}, rejected=True),
    R(33, "Movie.2023.German.DL.1080p.BluRay.x264", languages=["English", "German"], source="bluray", lang=set()),
    R(34, "Movie.2023.1080p.WEB-DL.DV.H265", source="webdl", group="", has={"Compat · DV w/o HDR fallback"}, rejected=True),
    R(35, "Slow.Horses.S01E03.1080p.HEVC.x265-MeGusta[TGx]", app="sonarr", release_type=1, has={HEVC, RES}),
    R(36, "Slow Horses S04 1080p x265-ELiTE", app="sonarr", release_type=3, has={"TV · Season Pack", HEVC}),
    R(37, "NCIS.Origins.S01.1080p.x265-ELiTE", app="sonarr", release_type=3, has={"TV · Season Pack", HEVC}),
    R(38, "The Office US S06E26 Whistleblower 1080p HEVC x265 MeGusta", app="sonarr", release_type=1, group="", has={HEVC}),
    R(39, "Slow Horses S01E01-02 [1080p Ita Eng Spa h265 10Bit SubS][MirCrewRelease]", app="sonarr",
      languages=["Italian", "English", "Spanish"], release_type=2, group="", has={HEVC}),
]
BY_N = {r["n"]: r for r in CORPUS}


class TestCorpus(unittest.TestCase):
    def test_expected_formats(self):
        for rel in CORPUS:
            with self.subTest(n=rel["n"], title=rel["title"]):
                got = matched(rel["app"], rel)
                self.assertEqual(got & LANG_FORMATS, rel["lang"], f"language formats for #{rel['n']}")
                self.assertTrue(rel["has"] <= got, f"#{rel['n']} missing {rel['has'] - got}; got {sorted(got)}")
                self.assertFalse(rel["hasnot"] & got, f"#{rel['n']} must not match {rel['hasnot'] & got}")
                self.assertFalse({NAMED, DUAL} <= got, "named and dual-tag must never both match")
                self.assertEqual(in_group(rel["app"], rel["quality"]), rel["quality_ok"], f"quality {rel['quality']}")
                for name in ("1080p Compact", "Dual Audio First"):
                    scores = profile(rel["app"], name)["scores"]
                    blocked = any(scores.get(n, 0) <= pp.BLOCK for n in got)
                    self.assertEqual(blocked, rel["rejected"], f"#{rel['n']} blocked in {name}: {sorted(got)}")
                    if not blocked:
                        below = score(rel["app"], rel, name) < profile(rel["app"], name)["min_format_score"]
                        self.assertEqual(below, rel["below_minimum"], f"#{rel['n']} under the minimum score in {name}")

    def test_hindi_only_is_a_1080p_last_resort(self):
        """Hindi only (-500) leaves a 720p dub under the minimum score of 0 in both profiles;
        at 1080p it is accepted (recorded in the plan's implementation notes)."""
        dub_1080 = R(0, "Film (2020) 1080p BluRay Hindi DD 2.0 Esub", languages=["Hindi"], source="bluray")
        self.assertEqual(score("radarr", dub_1080, "1080p Compact"), 3000 - 500 + 60)
        self.assertGreater(score("radarr", dub_1080, "Dual Audio First"), 0)

    def test_untagged_1080p_ranks_below_tagged(self):
        self.assertEqual(matched("radarr", BY_N[17]) - {BAND}, {RES})
        for name in ("1080p Compact", "Dual Audio First"):
            self.assertLess(score("radarr", BY_N[17], name), score("radarr", BY_N[13], name))

    def test_goldfinger_top_pick_in_both_profiles(self):
        candidates = [r for r in CORPUS if r["app"] == "radarr" and r["title"].lower().find("goldfinger") >= 0
                      and r["quality_ok"] and not r["rejected"]]
        for name in ("1080p Compact", "Dual Audio First"):
            ranked = sorted(candidates, key=lambda r: score("radarr", r, name), reverse=True)
            self.assertEqual(ranked[0]["n"], 1, f"{name}: {[(r['n'], score('radarr', r, name)) for r in ranked[:4]]}")
        self.assertEqual(score("radarr", BY_N[1], "1080p Compact"), 3000 + 1500 + 400 + 200 + 60)
        self.assertEqual(score("radarr", BY_N[1], "Dual Audio First"), 1000 + 3000 + 200 + 60)

    def test_dual_audio_first_prefers_720p_dual_over_1080p_english(self):
        dual_720, english_1080 = BY_N[3], BY_N[13]
        self.assertGreater(score("radarr", dual_720, "Dual Audio First"), score("radarr", english_1080, "Dual Audio First"))
        self.assertGreater(score("radarr", english_1080, "1080p Compact"), score("radarr", dual_720, "1080p Compact"))

    def test_season_packs_rank_first(self):
        self.assertGreater(score("sonarr", BY_N[36], "1080p Compact"), score("sonarr", BY_N[35], "1080p Compact"))

    def test_esub_whitelisted_as_soft_subtitles(self):
        # Radarr's hardcoded-subtitle regex reads ESub as burned in; the pack whitelists it.
        hc = re.compile(r"\b(?P<hcsub>\w+(?<!SOFT)(?<!MULTI)(?<!HORRIBLE)SUBS?)\b", re.IGNORECASE)
        found = hc.search(BY_N[6]["title"]).group("hcsub")
        whitelist = pp.merge_csv("", PACK["settings"]["radarr"]["config/indexer"]["whitelistedHardcodedSubs"]["merge_csv"])
        self.assertNotIn(" ", whitelist, "Radarr does not trim list entries")
        self.assertTrue(any(t and t.lower() in found.lower() for t in whitelist.split(",")), found)
        self.assertFalse(any(t.lower() in "korsub" for t in whitelist.split(",")), "real burned-in tags stay blocked")

    def test_space_reclaim_examples(self):
        """Section 5.3: compact upgrades count only when they are worth 400 or more."""
        base = dict(title="Film 2020 1080p WEB-DL x264-GRP", source="webdl", resolution=1080)
        big_x264 = R(0, **dict(base, size_gb=9.7))
        small_hevc = R(0, **dict(base, title="Film 2020 1080p WEB-DL HEVC-GRP", size_gb=4.3))
        compact_x264 = R(0, **dict(base, size_gb=4.0))
        bigger_hevc = R(0, **dict(base, title="Film 2020 1080p WEB-DL HEVC-GRP", size_gb=7.0))
        huge = R(0, **dict(base, size_gb=11))
        c = "1080p Compact"
        self.assertEqual(score("radarr", big_x264, c), 3050)
        self.assertEqual(score("radarr", small_hevc, c), 3650)
        self.assertGreaterEqual(score("radarr", small_hevc, c) - score("radarr", big_x264, c), 400)
        # A bigger HEVC file is held back only when it leaves the compact band (+400 - 200).
        # Inside the same band HEVC alone is +400, which equals the increment (plan notes).
        self.assertLess(score("radarr", bigger_hevc, c) - score("radarr", compact_x264, c), 400)
        self.assertLess(score("radarr", huge, c), 3050 - 400)


class TestLanguages(unittest.TestCase):
    GUARDS = ["The Thin Red Line (1998) 1080p BluRay", "Ben-Hur (1959) 1080p", "Mar Adentro (2004) 1080p",
              "The Tel Aviv Job (2019) 1080p", "Malcolm X (1992) 1080p", "Kansas City (1996) 1080p",
              "Mal.de.Mer.2020.1080p", "Kan Eng (2021) 1080p", "Machine.Within.2020.1080p", "Shining.Through.1992.1080p"]

    def test_short_tokens_need_a_neighbour(self):
        for lang in PACK["languages"]["languages"]:
            rx = _compile(pp.language_regex(PACK, lang))
            for title in self.GUARDS:
                if lang["name"] == "Kannada" and title.startswith("Kan Eng"):
                    continue  # "Kan" next to "Eng" is the documented adjacency case
                with self.subTest(lang=lang["name"], title=title):
                    self.assertIsNone(rx.search(title))
        telugu = _compile(pp.language_regex(PACK, pp.find_language(PACK, "Telugu")))
        for title in ("Movie 2024 Telugu 1080p", "Movie [Hin + Tel] 1080p", "Movie.Tel.Hindi.1080p", "Movie [Tam-Tel] 720p"):
            self.assertIsNotNone(telugu.search(title), title)

    def test_every_language_renders(self):
        for name in pp.language_names(PACK):
            lang = pp.find_language(PACK, name)
            for app in pp.APPS:
                names = {f["name"] for f in pp.render_formats(PACK, app, lang)}
                self.assertIn(f"Lang · {name} + Original (named)", names)
                self.assertIn(f"Lang · Not Original or {name}", names)
        with self.assertRaises(ValueError):
            pp.find_language(PACK, "Klingon")
        self.assertIsNone(pp.find_language(PACK, "none"))

    def test_language_missing_in_app_keeps_title_tokens(self):
        telugu = pp.find_language(PACK, "Telugu")
        fmt = next(f for f in pp.render_formats(PACK, "sonarr", telugu) if f["name"] == "Lang · Not Original or Telugu")
        sonarr_languages = [{"id": 27, "name": "Hindi"}, {"id": 1, "name": "English"}]
        api, notes = pp.to_api_format(fmt, sonarr_languages)
        self.assertTrue(notes and "Telugu" in notes[0])
        impls = [s["implementation"] for s in api["specifications"]]
        self.assertEqual(impls.count("LanguageSpecification"), 1, "the Original condition stays")
        self.assertIn("ReleaseTitleSpecification", impls)


class TestPackInvariants(unittest.TestCase):
    def test_every_format_is_owned_and_scored(self):
        for lang in (HINDI, None):
            for app in pp.APPS:
                formats = {f["name"] for f in pp.render_formats(PACK, app, lang)}
                for name in formats:
                    self.assertTrue(pp.owned_format(PACK, name), name)
                for prof in pp.render_profiles(PACK, app, lang, ["hevc"]):
                    self.assertEqual(set(prof["scores"]), formats, f"{app} {prof['name']} lang={lang and lang['name']}")

    def test_quality_order_and_names(self):
        for app in pp.APPS:
            for prof in PACK["profiles"][app]:
                flat = [q for e in prof["qualities"] for q in (e["qualities"] if "group" in e else [e["quality"]])]
                for q in flat:
                    self.assertIn(q, QUALITIES[app], f"{app} {prof['name']}")
                for entry in prof["qualities"]:  # highest first: no unknown-source quality alone above Bluray/WEB
                    if "quality" in entry:
                        self.assertFalse(entry["quality"].startswith("HDTV-"), f"{entry} must sit inside a group")
                res = [int(re.search(r"(\d+)p", q).group(1)) for q in flat]
                self.assertEqual(res, sorted(res, reverse=True), "qualities are listed highest first")
                self.assertEqual(prof["upgrade"]["until_quality"], prof["qualities"][0].get("group"))

    def test_minimum_and_upgrade_scores_reachable(self):
        tops = {"radarr": BY_N[1], "sonarr": None}
        for app in pp.APPS:
            for lang in (HINDI, None):
                for prof in pp.render_profiles(PACK, app, lang, ["hevc"]):
                    self.assertLessEqual(prof["min_format_score"], 0)
                    positive = sum(s for n, s in prof["scores"].items() if s > 0 and not n.startswith("Lang · "))
                    best_lang = max([s for n, s in prof["scores"].items() if n.startswith("Lang · ")] + [0])
                    reachable = positive + best_lang - (300 if app == "sonarr" else 0)  # a season pack is not per episode
                    self.assertGreaterEqual(reachable, prof["upgrade"]["until_score"], f"{app} {prof['name']}")
                    if app == "radarr" and lang is not None:
                        self.assertGreaterEqual(score(app, tops[app], prof["name"]), prof["upgrade"]["until_score"])

    def test_codec_choices(self):
        blocked = profile("radarr", "1080p Compact", codecs=())["scores"]
        self.assertEqual(blocked[HEVC], pp.BLOCK)
        allowed = profile("radarr", "1080p Compact", codecs=("hevc", "av1", "dv"))["scores"]
        self.assertEqual(allowed["Compat · AV1"], 0)
        self.assertEqual(allowed["Compat · DV w/o HDR fallback"], 0)
        with self.assertRaises(ValueError):
            pp.parse_codecs("hevc,vp9")

    def test_regexes_compile(self):
        for app in pp.APPS:
            for fmt in pp.render_formats(PACK, app, HINDI):
                for spec in fmt["specifications"]:
                    if spec["implementation"] not in ("ReleaseTitleSpecification", "ReleaseGroupSpecification"):
                        continue
                    try:
                        _compile(spec["fields"]["value"])
                    except re.error as exc:  # a new .NET-only construct upstream: extend DOTNET_LOOKBEHIND
                        self.fail(f"{fmt['name']} ({fmt.get('source')}): {exc}")

    def test_vendored_files_match_pack_metadata(self):
        self.assertIn("MIT License", (PACK["dir"] / "trash" / "LICENSE").read_text(encoding="utf-8"))
        self.assertRegex(PACK["meta"]["trash"]["commit"], r"^[0-9a-f]{40}$")
        for rel, (info, data) in PACK["vendored"].items():
            self.assertEqual(data["trash_id"], info["trash_id"], rel)
            self.assertTrue(info["source"].endswith(rel.split("/", 1)[1]), rel)
            self.assertTrue(pp.owned_format(PACK, info["name"]), info["name"])

    def test_settings_choices(self):
        self.assertEqual(set(PACK["settings"]["qbittorrent"]["seeding"]), set(pp.SEEDING_CHOICES))
        self.assertEqual(pp.merge_csv("ESub,Foo", ["esub", "MSub"]), "ESub,Foo,MSub")
        self.assertEqual(pp.merge_lines("*.exe\n*.bat", ["*.bat", "*.msi"]), "*.exe\n*.bat\n*.msi")


# ---------------------------------------------------------------- live fakes
def quality_defs(app):
    out = []
    for i, name in enumerate(QUALITIES[app]):
        m = re.search(r"(\d+)p", name)
        out.append({"id": i + 1, "weight": i + 1, "title": name, "minSize": 0, "preferredSize": 95, "maxSize": 100,
                    "quality": {"id": 100 + i, "name": name, "source": "x", "resolution": int(m.group(1)) if m else 0}})
    return out


def legacy_profile(app, defs, pid, name, allowed):
    items = [{"quality": d["quality"], "items": [], "allowed": d["quality"]["name"] in allowed} for d in defs]
    return {"id": pid, "name": name, "upgradeAllowed": True, "cutoff": defs[0]["quality"]["id"], "items": items,
            "minFormatScore": 0, "cutoffFormatScore": 10000, "minUpgradeFormatScore": 1, "formatItems": [],
            "language": {"id": -2, "name": "Original"}}


class FakeArr:
    """Enough of the Radarr/Sonarr v3 API for the pack: lists, schema-free POST/PUT/DELETE."""

    def __init__(self, name):
        self.name = name
        self.calls = []
        defs = quality_defs(name)
        self.db = {
            "language": [{"id": -2, "name": "Original"}, {"id": 1, "name": "English"},
                         {"id": 26 if name == "radarr" else 27, "name": "Hindi"}],
            "qualitydefinition": defs,
            "customformat": [
                {"id": 1, "name": "Hindi Audio", "includeCustomFormatWhenRenaming": False, "specifications": []},
                {"id": 2, "name": "x265 (HD)", "includeCustomFormatWhenRenaming": False, "specifications": []},
                {"id": 3, "name": "My Own Format", "includeCustomFormatWhenRenaming": False, "specifications": []},
            ],
            "qualityprofile": [
                legacy_profile(name, defs, 7, "1080p Balanced", {"Bluray-1080p"}),
                legacy_profile(name, defs, 9, "1080p Compact", {"Bluray-1080p", "WEBRip-1080p", "WEBDL-1080p", "HDTV-1080p"}),
            ],
            "delayprofile": [{"id": 1, "order": 2147483647, "bypassIfAboveCustomFormatScore": False, "minimumCustomFormatScore": 0}],
            "releaseprofile": [{"id": 1, "name": "Phase 0 bans (until profile pack)", "ignored": ["rifftrax", "Ozlem"]},
                               {"id": 2, "name": "My own bans", "ignored": ["cam"]}] if name == "radarr" else [],
            "movie" if name == "radarr" else "series": [{"id": 11, "title": "Stranded", "qualityProfileId": 7},
                                                        {"id": 12, "title": "Fine", "qualityProfileId": 9}],
        }
        self.db["qualityprofile"][1]["formatItems"] = [{"format": 1, "name": "Hindi Audio", "score": 50000},
                                                      {"format": 3, "name": "My Own Format", "score": 25}]
        self.config = {"config/indexer": {"id": 1, "whitelistedHardcodedSubs": "", "allowHardcodedSubs": False},
                       "config/mediamanagement": {"id": 1, "recycleBin": "", "recycleBinCleanupDays": 7}}

    def get(self, path):
        if path in self.config:
            return 200, copy.deepcopy(self.config[path])
        if path in self.db:
            return 200, copy.deepcopy(self.db[path])
        return 404, None

    def post(self, path, data):
        self.calls.append(("POST", path))
        coll = self.db[path]
        obj = copy.deepcopy(data)
        obj["id"] = max([o["id"] for o in coll] + [100]) + 1
        coll.append(obj)
        return 201, obj

    def put(self, path, data):
        self.calls.append(("PUT", path))
        if path in self.config:
            self.config[path] = copy.deepcopy(data)
            return 202, data
        if path == "qualitydefinition/update":
            byid = {d["id"]: d for d in data}
            self.db["qualitydefinition"] = [copy.deepcopy(byid.get(d["id"], d)) for d in self.db["qualitydefinition"]]
            return 202, data
        if path.endswith("/editor"):
            coll = "movie" if path.startswith("movie") else "series"
            ids = data["movieIds" if coll == "movie" else "seriesIds"]
            for t in self.db[coll]:
                if t["id"] in ids:
                    t["qualityProfileId"] = data["qualityProfileId"]
            return 202, data
        coll, oid = path.rsplit("/", 1)
        items = self.db[coll]
        for i, o in enumerate(items):
            if o["id"] == int(oid):
                items[i] = copy.deepcopy(data)
                return 202, data
        return 404, "missing"

    def delete(self, path):
        self.calls.append(("DELETE", path))
        coll, oid = path.rsplit("/", 1)
        before = len(self.db[coll])
        self.db[coll] = [o for o in self.db[coll] if o["id"] != int(oid)]
        if coll == "customformat":
            for p in self.db["qualityprofile"]:
                p["formatItems"] = [fi for fi in p.get("formatItems", []) if fi["format"] != int(oid)]
        return (200, {}) if len(self.db[coll]) < before else (404, "missing")


class FakeProwlarr(FakeArr):
    def __init__(self):
        self.name = "prowlarr"
        self.calls = []
        self.config = {}
        self.db = {"applications": [{"id": 1, "name": "Radarr", "syncLevel": "addOnly"}, {"id": 2, "name": "Sonarr", "syncLevel": "fullSync"}],
                   "appprofile": [{"id": 1, "name": "Standard", "enableRss": True, "enableAutomaticSearch": True,
                                   "enableInteractiveSearch": True, "minimumSeeders": 1}]}


class FakeQBit:
    def __init__(self):
        self.prefs = {"max_ratio_enabled": True, "max_ratio": 0.1, "max_seeding_time_enabled": True, "max_seeding_time": 1,
                      "max_inactive_seeding_time_enabled": False, "max_inactive_seeding_time": -1, "max_ratio_act": 0,
                      "queueing_enabled": True, "max_active_downloads": 99999, "max_active_torrents": 100000,
                      "max_active_uploads": 50, "dont_count_slow_torrents": False, "slow_torrent_dl_rate_threshold": 2,
                      "slow_torrent_ul_rate_threshold": 2, "slow_torrent_inactive_timer": 60, "scheduler_enabled": False,
                      "schedule_from_hour": 8, "schedule_from_min": 0, "schedule_to_hour": 20, "schedule_to_min": 0,
                      "scheduler_days": 0, "alt_up_limit": 10240, "alt_dl_limit": 10240, "reannounce_when_address_changed": False,
                      "add_trackers_from_url_enabled": False, "add_trackers_url": "", "excluded_file_names_enabled": True,
                      "excluded_file_names": "*.exe\n*.bat"}
        self.cats = {"movies": {"savePath": "/data/torrents/movies"}}

    def login(self, attempts=1):
        return True, "ok"

    def preferences(self):
        return copy.deepcopy(self.prefs)

    def set_preferences(self, prefs):
        self.prefs.update(prefs)
        return True, ""

    def categories(self):
        return dict(self.cats)

    def ensure_categories(self, wanted=None):
        for n, path in wanted:
            self.cats.setdefault(n, {"savePath": path})
        return True


def settings(language="Hindi", seeding="while-it-helps", codecs=("hevc",)):
    return {"enabled": True, "language": pp.find_language(PACK, language), "language_name": language or "",
            "default_profile": "compact", "default_profile_name": "1080p Compact", "codecs": list(codecs),
            "seeding": seeding, "public_trackers": True, "qbit_user": "admin", "qbit_pass": "x"}


class TestApplyCheckMigrate(unittest.TestCase):
    def setUp(self):
        wire_arr.report.update({"steps": [], "errors": [], "warnings": []})
        self.radarr, self.sonarr, self.prowlarr, self.qbit = FakeArr("radarr"), FakeArr("sonarr"), FakeProwlarr(), FakeQBit()

    def runner(self, **kw):
        return wire_arr.PackRunner(PACK, settings(**kw), {"radarr": self.radarr, "sonarr": self.sonarr}, self.prowlarr, self.qbit)

    def test_apply_then_check_is_in_sync(self):
        r = self.runner()
        actions = r.plan()
        self.assertTrue(actions)
        self.assertEqual(r.execute(actions), 0, wire_arr.report["errors"])
        again = self.runner().plan()
        self.assertEqual([a.what for a in again], [], [(a.app, a.what, a.detail) for a in again])

        compact = next(p for p in self.radarr.db["qualityprofile"] if p["name"] == "1080p Compact")
        self.assertEqual(compact["id"], 9, "updated in place: Seerr points at the profile id")
        self.assertEqual(compact["language"]["id"], -1)
        top = compact["items"][-1]
        self.assertEqual(top["name"], "HD")
        self.assertEqual(compact["cutoff"], top["id"])
        self.assertEqual({i["quality"]["name"] for i in top["items"]}, set(PACK["profiles"]["radarr"][0]["qualities"][0]["qualities"]))
        scores = {fi["name"]: fi["score"] for fi in compact["formatItems"]}
        self.assertEqual(scores["My Own Format"], 25, "a user's own format keeps its score")
        self.assertEqual(scores["Hindi Audio"], 50000, "legacy formats are only removed by migrate")
        self.assertEqual(scores[RES], 3000)
        self.assertEqual(len(compact["formatItems"]), len(self.radarr.db["customformat"]), "every format is listed")
        self.assertTrue(any(p["name"] == "Dual Audio First" for p in self.sonarr.db["qualityprofile"]))
        self.assertEqual(self.radarr.config["config/indexer"]["whitelistedHardcodedSubs"], "ESub,ESubs,MSub,MSubs,EngSub,EngSubs")
        self.assertEqual(self.radarr.config["config/mediamanagement"]["recycleBin"], "/data/media/.recycle")
        bd = next(d for d in self.radarr.db["qualitydefinition"] if d["quality"]["name"] == "Bluray-1080p")
        self.assertEqual((bd["minSize"], bd["preferredSize"], bd["maxSize"]), (12, 40, 75))
        self.assertEqual(self.prowlarr.db["applications"][0]["syncLevel"], "fullSync")
        self.assertEqual(self.prowlarr.db["appprofile"][0]["minimumSeeders"], 4)
        self.assertTrue(any(p["name"] == "Live seeders" for p in self.prowlarr.db["appprofile"]))
        self.assertEqual(self.qbit.prefs["max_ratio"], 1.0)
        self.assertEqual(self.qbit.prefs["max_seeding_time"], 1440)
        self.assertTrue(self.qbit.prefs["add_trackers_from_url_enabled"])
        self.assertIn("*.msi", self.qbit.prefs["excluded_file_names"])
        self.assertIn("radarr", self.qbit.cats)
        self.assertIn("movies", self.qbit.cats, "an older category is never removed")

    def test_no_second_language(self):
        r = self.runner(language=None)
        r.execute(r.plan())
        names = {p["name"] for p in self.radarr.db["qualityprofile"]}
        self.assertNotIn("Dual Audio First", names)
        formats = {f["name"] for f in self.radarr.db["customformat"]}
        self.assertIn("Lang · Not Original", formats)
        self.assertFalse(any("Hindi" in n and n.startswith("Lang") for n in formats))
        self.assertEqual(self.runner(language=None).plan(), [])

    def test_migrate_moves_titles_and_removes_legacy(self):
        r = self.runner()
        actions = r.plan() + r.legacy_plan()
        whats = [a.what for a in actions]
        self.assertIn("move 1 title(s) from 1080p Balanced to 1080p Compact", whats)
        self.assertIn("delete profile 1080p Balanced", whats)
        self.assertIn("delete legacy format Hindi Audio", whats)
        self.assertNotIn("delete legacy format My Own Format", whats)
        self.assertEqual(whats.count("delete interim release profile Phase 0 bans (until profile pack)"), 1)
        self.assertEqual(r.execute(actions), 0, wire_arr.report["errors"])
        self.assertEqual([rp["name"] for rp in self.radarr.db["releaseprofile"]], ["My own bans"],
                         "only the interim Phase 0 release profile is removed")
        for arr, coll in ((self.radarr, "movie"), (self.sonarr, "series")):
            self.assertEqual({t["qualityProfileId"] for t in arr.db[coll]}, {9})
            self.assertNotIn("1080p Balanced", {p["name"] for p in arr.db["qualityprofile"]})
            self.assertFalse({"Hindi Audio", "x265 (HD)"} & {f["name"] for f in arr.db["customformat"]})
        self.assertEqual(self.runner().legacy_plan(), [])
        self.assertEqual(self.runner().plan(), [])

    def test_phase0_merged_group_converges(self):
        """Phase 0 left profile 9 with the four 1080p qualities in a group with id 1002."""
        for arr in (self.radarr, self.sonarr):
            prof = next(p for p in arr.db["qualityprofile"] if p["id"] == 9)
            group_names = {"Bluray-1080p", "WEBDL-1080p", "WEBRip-1080p", "HDTV-1080p"}
            members = [i for i in prof["items"] if i["quality"]["name"] in group_names]
            prof["items"] = [i for i in prof["items"] if i["quality"]["name"] not in group_names]
            prof["items"].append({"id": 1002, "name": "HD 1080p", "allowed": True, "items": members})
            prof["cutoff"] = 1002
            arr.db["qualityprofile"] = [p for p in arr.db["qualityprofile"] if p["name"] != "1080p Balanced"]
        r = self.runner()
        actions = r.plan() + r.legacy_plan()
        self.assertFalse(any(a.what.startswith("move ") or "1080p Balanced" in a.what for a in actions))
        self.assertEqual(r.execute(actions), 0, wire_arr.report["errors"])
        self.assertEqual(self.runner().plan(), [])
        compact = next(p for p in self.radarr.db["qualityprofile"] if p["id"] == 9)
        self.assertEqual(compact["items"][-1]["name"], "HD")
        self.assertEqual(sum(1 for i in compact["items"] if i.get("items")), 1, "one group only")

    def test_dry_run_changes_nothing(self):
        before = copy.deepcopy(self.radarr.db)
        r = self.runner()
        r.plan()
        r.legacy_plan()
        self.assertEqual(self.radarr.calls, [])
        self.assertEqual(self.radarr.db, before)

    def test_seeding_off(self):
        r = self.runner(seeding="off")
        r.execute(r.plan())
        self.assertEqual(self.qbit.prefs["max_ratio"], 0)
        self.assertEqual(self.qbit.prefs["max_seeding_time"], 0)


class TestSettingsResolution(unittest.TestCase):
    def args(self, **kw):
        base = dict(env_file="", language=None, default_profile=None, codecs=None, seeding=None,
                    no_public_trackers=False, qbit_user="", qbit_pass="")
        base.update(kw)
        return argparse.Namespace(**base)

    def test_env_file_and_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "media.env"
            env.write_text("MEDIA_PROFILES=on\nMEDIA_SECOND_LANGUAGE=Hindi\nMEDIA_DEFAULT_PROFILE=dual-audio-first\n"
                           "MEDIA_CODECS=hevc,av1\nMEDIA_SEEDING=off\nQBITTORRENT_PASS=pw\n", encoding="utf-8")
            s = wire_arr.resolve_pack_settings(self.args(env_file=str(env)), PACK)
            self.assertEqual((s["language_name"], s["default_profile_name"], s["codecs"], s["seeding"], s["qbit_pass"]),
                             ("Hindi", "Dual Audio First", ["hevc", "av1"], "off", "pw"))
            s = wire_arr.resolve_pack_settings(self.args(env_file=str(env), language="Tamil", seeding="while-it-helps"), PACK)
            self.assertEqual((s["language_name"], s["seeding"]), ("Tamil", "while-it-helps"))

    def test_defaults_and_errors(self):
        s = wire_arr.resolve_pack_settings(self.args(), PACK)
        self.assertEqual((s["enabled"], s["language"], s["default_profile"], s["codecs"]), (True, None, "compact", ["hevc"]))
        with self.assertRaises(ValueError):
            wire_arr.resolve_pack_settings(self.args(default_profile="dual-audio-first"), PACK)
        with self.assertRaises(ValueError):
            wire_arr.resolve_pack_settings(self.args(language="Klingon"), PACK)

    def test_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "media.env"
            env.write_text("MEDIA_PROFILES=off\n", encoding="utf-8")
            self.assertFalse(wire_arr.resolve_pack_settings(self.args(env_file=str(env)), PACK)["enabled"])


if __name__ == "__main__":
    unittest.main()
