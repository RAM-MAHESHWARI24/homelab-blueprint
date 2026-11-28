"""
Tests for scripts/compact_replace.py: compact replacement of oversized TV seasons
(media pipeline plan section 8.6, owner decision 16) and the space report.
A fake Sonarr; time is simulated. Standard library only.
"""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import compact_replace as cr  # noqa: E402
import download_doctor as dd  # noqa: E402

T0 = 1_800_000_000.0
GB = 1e9
EPISODES = 10


def ep_file(fid, n, size=4.69 * GB, codec="x264", langs="eng"):
    return {"id": fid, "seasonNumber": 1, "size": size, "path": f"/data/media/tv/Succession/S01E{n:02d}.{codec}.mkv",
            "mediaInfo": {"runTime": "1:01:00", "audioLanguages": langs, "videoCodec": codec}}


def release(title, size, seeders, episodes=None, full=False, res=1080, cf=None, score=3300, rejections=None, guid=None):
    return {"title": title, "guid": guid or title, "indexerId": 7, "size": size, "seeders": seeders, "fullSeason": full,
            "mappedEpisodeNumbers": episodes or [], "episodeNumbers": episodes or [],
            "quality": {"quality": {"name": f"HDTV-{res}p", "resolution": res}}, "customFormatScore": score,
            "customFormats": [{"name": n} for n in (cf or ["Eff · HEVC", "Res · 1080p"])],
            "rejections": rejections if rejections is not None else ["Existing file on disk has Custom Format score within Custom Format score increment: 400"]}


class FakeSonarr:
    def __init__(self, releases, files=None, langs="eng", profile="1080p Compact", tags=None):
        self.files = files or [ep_file(100 + n, n, langs=langs) for n in range(1, EPISODES + 1)]
        self.episodes = [{"id": n, "seasonNumber": 1, "episodeNumber": n, "hasFile": True, "episodeFileId": 100 + n}
                         for n in range(1, EPISODES + 1)]
        self.series = [{"id": 2, "title": "Succession", "year": 2018, "runtime": 61, "monitored": True,
                        "qualityProfileId": 9, "tags": tags or []}]
        self.profiles = [{"id": 9, "name": profile}]
        self.tags = [{"id": 5, "label": "keep"}]
        self.releases = releases
        self.queue = []
        self.manual = []
        self.calls = []
        self.timeout = 30

    def request_json(self, path, method="GET", payload=None):
        if method != "GET":
            self.calls.append((method, path, payload))
        if path == "/api/v3/qualityprofile":
            return 200, self.profiles
        if path == "/api/v3/tag":
            return 200, self.tags
        if path == "/api/v3/series":
            return 200, self.series
        if path.startswith("/api/v3/episode?"):
            return 200, copy.deepcopy(self.episodes)
        if path.startswith("/api/v3/episodefile?"):
            return 200, copy.deepcopy(self.files)
        if path.startswith("/api/v3/release?"):
            assert self.timeout >= 200, "season searches need a long timeout"
            return 200, copy.deepcopy(self.releases)
        if path == "/api/v3/qualitydefinition":
            return 200, [{"quality": {"name": "HDTV-1080p"}, "minSize": 4}, {"quality": {"name": "HDTV-720p"}, "minSize": 3}]
        if path == "/api/v3/release" and method == "POST":
            rel = next(r for r in self.releases if r["guid"] == payload["guid"])
            self.queue.append({"id": len(self.queue) + 1, "title": rel["title"], "seriesId": 2, "downloadId": f"H{len(self.queue)}",
                               "trackedDownloadState": "downloading"})
            return 200, {}
        if path.startswith("/api/v3/queue?"):
            return 200, {"records": copy.deepcopy(self.queue)}
        if path.startswith("/api/v3/manualimport?"):
            return 200, copy.deepcopy(self.manual)
        if path == "/api/v3/command":
            return 201, {}
        return 404, None

    def posts(self, path):
        return [c for c in self.calls if c[0] == "POST" and c[1] == path]

    def complete(self, title, episodes, size_each, name="Succession.S01.1080p.x265"):
        """The download finishes; Sonarr holds it as not an upgrade."""
        for q in self.queue:
            if q["title"] == title:
                q["trackedDownloadState"] = "importBlocked"
        self.manual = [{"path": f"/data/torrents/tv/{name}/{name}.E{n:02d}.mkv", "folderName": name,
                        "episodes": [{"id": n, "seasonNumber": 1, "episodeNumber": n}], "quality": {"quality": {"name": "HDTV-1080p"}},
                        "languages": [{"id": 1, "name": "English"}]} for n in episodes]
        self.new_size = size_each

    def imported(self, episodes, size_each):
        """ManualImport replaced the files: new file ids, the queue item is gone."""
        for f in self.files:
            n = int(f["path"].split("E")[-1][:2])
            if n in episodes:
                f.update(id=f["id"] + 1000, size=size_each, path=f["path"].replace("x264", "x265"))
                for e in self.episodes:
                    if e["episodeNumber"] == n:
                        e["episodeFileId"] = f["id"]
        self.queue = []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, sonarr, now=T0, watch_days=0, free=500 * GB, streaming=False, language=""):
        doc = dd.Doctor(None, {"sonarr": sonarr}, self.dir, now=lambda: now, watch_days=watch_days, language=language)
        job = cr.CompactJob(doc, "", language, streaming=lambda: streaming, disk_free=lambda: free)
        return doc.run_compact(job), doc


PACK = release("Succession.S01.COMPLETE.1080p.AMZN.10bit.DDP.5.1.x265", 17.5 * GB, 40, full=True)


class TestChoosing(Base):
    def test_pack_with_ten_seeders_is_grabbed(self):
        sonarr = FakeSonarr([PACK])
        status, doc = self.run_job(sonarr)
        self.assertIn("downloading pack", status["state"])
        self.assertEqual(sonarr.posts("/api/v3/release"), [("POST", "/api/v3/release", {"guid": PACK["guid"], "indexerId": 7})])
        self.assertEqual(doc.state["compact"]["inflight"]["releases"][0]["episodes"], list(range(1, 11)))

    def test_thin_pack_loses_to_episodes_that_can_all_be_found(self):
        thin = release("Succession.S01.1080p.x265-THIN", 15 * GB, 6, full=True)
        singles = [release(f"Succession.S01E{n:02d}.1080p.x265", 1.2 * GB, 25, episodes=[n]) for n in range(1, 11)]
        sonarr = FakeSonarr([thin] + singles)
        status, _ = self.run_job(sonarr)
        self.assertIn("episodes", status["state"])
        self.assertEqual(len(sonarr.posts("/api/v3/release")), 10)

    def test_thin_pack_is_the_fallback_when_episodes_are_missing(self):
        thin = release("Succession.S01.1080p.x265-THIN", 15 * GB, 6, full=True)
        singles = [release("Succession.S01E01.1080p.x265", 1.2 * GB, 25, episodes=[1])]
        sonarr = FakeSonarr([thin] + singles)
        status, _ = self.run_job(sonarr)
        self.assertIn("pack", status["state"])
        self.assertEqual(sonarr.posts("/api/v3/release")[0][2]["guid"], thin["guid"])

    def test_untagged_multi_episode_release_counts_as_a_pack(self):
        """Some whole-season releases are not flagged fullSeason; mapped episodes decide."""
        multi = release("Succession.S01E01-E10.1080p.x265", 16 * GB, 30, episodes=list(range(1, 11)))
        status, _ = self.run_job(FakeSonarr([multi]))
        self.assertIn("pack", status["state"])

    def test_rejections(self):
        cases = {
            "not 35% smaller": release("Big", 35 * GB, 50, full=True),
            "lower resolution": release("720p", 5 * GB, 50, full=True, res=720),
            "junk format": release("Junk", 10 * GB, 50, full=True, cf=["Junk · Upscaled"], score=-10000),
            "another objection": release("Queued", 10 * GB, 50, full=True, rejections=["Release in queue already meets cutoff"]),
            "starved encode": release("Tiny", 0.5 * GB, 50, full=True),
            "too few seeders": release("Dead", 10 * GB, 2, full=True),
        }
        for label, rel in cases.items():
            with self.subTest(label):
                self.tearDown()
                self.setUp()
                sonarr = FakeSonarr([rel])
                status, doc = self.run_job(sonarr)
                self.assertEqual(sonarr.posts("/api/v3/release"), [], label)
                self.assertIn("no acceptable candidate", status["state"])

    def test_hindi_files_need_a_hindi_candidate(self):
        english = release("Show.S01.1080p.x265", 10 * GB, 50, full=True)
        hindi = release("Show.S01.Hindi.English.1080p.x265", 12 * GB, 50, full=True,
                        cf=["Eff · HEVC", "Lang · Hindi + Original (named)"])
        sonarr = FakeSonarr([english], langs="hin/eng")
        status, _ = self.run_job(sonarr, language="Hindi")
        self.assertIn("no acceptable candidate", status["state"])
        self.assertIn("no Hindi audio", " ".join(status["reasons"]))
        self.tearDown()
        self.setUp()
        sonarr = FakeSonarr([english, hindi], langs="hin/eng")
        self.run_job(sonarr, language="Hindi")
        self.assertEqual(sonarr.posts("/api/v3/release")[0][2]["guid"], hindi["guid"])

    def test_guards(self):
        for label, kw, sonarr in (("free space", {"free": 30 * GB}, FakeSonarr([PACK])),
                                  ("streaming", {"streaming": True}, FakeSonarr([PACK])),
                                  ("watch-only", {"watch_days": 7}, FakeSonarr([PACK])),
                                  ("keep tag", {}, FakeSonarr([PACK], tags=[5])),
                                  ("other profile", {}, FakeSonarr([PACK], profile="1080p Family"))):
            with self.subTest(label):
                self.tearDown()
                self.setUp()
                status, doc = self.run_job(sonarr, **kw)
                self.assertEqual(sonarr.posts("/api/v3/release"), [], label)
                if label in ("keep tag", "other profile"):
                    self.assertIn("nothing to compact", status["state"], label)

    def test_watch_only_logs_what_it_would_grab(self):
        status, doc = self.run_job(FakeSonarr([PACK]), watch_days=7)
        self.assertIn("would replace", status["state"])
        self.assertEqual([c["action"] for c in doc.calls], ["would_compact"])

    def test_one_pick_every_six_hours_and_no_repeat_within_three_days(self):
        sonarr = FakeSonarr([release("Big", 35 * GB, 50, full=True)])
        self.run_job(sonarr)
        status, _ = self.run_job(sonarr, now=T0 + 3600)
        self.assertIn("waiting", status["state"])
        status, _ = self.run_job(sonarr, now=T0 + 7 * 3600)
        self.assertIn("nothing to compact", status["state"], "searched 7 hours ago: not again for 3 days")


class TestImportAndVerify(Base):
    def start(self):
        sonarr = FakeSonarr([PACK])
        self.run_job(sonarr)
        return sonarr

    def test_full_cycle_saves_space(self):
        sonarr = self.start()
        status, _ = self.run_job(sonarr, now=T0 + 3600)
        self.assertIn("in progress", status["state"])
        sonarr.complete(PACK["title"], range(1, 11), 1.75 * GB)
        self.run_job(sonarr, now=T0 + 7200)
        (_, _, cmd), = sonarr.posts("/api/v3/command")
        self.assertEqual(cmd["name"], "ManualImport")
        self.assertEqual(len(cmd["files"]), 10)
        self.assertEqual(sorted(i for f in cmd["files"] for i in f["episodeIds"]), list(range(1, 11)))
        sonarr.imported(range(1, 11), 1.75 * GB)
        status, doc = self.run_job(sonarr, now=T0 + 10800)
        self.assertIn("replaced", status["state"])
        self.assertAlmostEqual(status["saved_gb"], 46.9 - 17.5, delta=0.2)
        self.assertIsNone(doc.state["compact"]["inflight"])

    def test_import_held_when_files_do_not_match(self):
        sonarr = self.start()
        sonarr.complete(PACK["title"], range(1, 10), 1.75 * GB)       # E10 missing from the download
        status, doc = self.run_job(sonarr, now=T0 + 3600)
        self.assertEqual(sonarr.posts("/api/v3/command"), [])
        self.assertTrue(any(a["kind"] == "compact_import" for a in doc.state["alerts"]))

    def test_import_held_for_the_wrong_series(self):
        sonarr = self.start()
        sonarr.complete(PACK["title"], range(1, 11), 1.75 * GB, name="Billions.S01.1080p")
        self.run_job(sonarr, now=T0 + 3600)
        self.assertEqual(sonarr.posts("/api/v3/command"), [])

    def test_verification_fails_when_not_smaller(self):
        sonarr = self.start()
        sonarr.complete(PACK["title"], range(1, 11), 5 * GB)
        self.run_job(sonarr, now=T0 + 3600)
        sonarr.imported(range(1, 11), 5 * GB)
        status, doc = self.run_job(sonarr, now=T0 + 7200)
        self.assertIn("verification failed", status["state"])
        self.assertTrue(any(a["kind"] == "compact_verify" for a in doc.state["alerts"]))

    def test_three_failed_candidates_pause_the_title(self):
        sonarr = FakeSonarr([PACK])
        now = T0
        for _ in range(3):
            self.run_job(sonarr, now=now)                 # grab
            sonarr.queue = []                             # removed (for example replaced as stuck)
            status, doc = self.run_job(sonarr, now=now + 3600)
            self.assertIn("left the queue", status["state"])
            now += 4 * 86400
        rec = doc.state["compact"]["titles"]["sonarr:2:1"]
        self.assertGreater(rec["retry_after"], now)
        status, _ = self.run_job(sonarr, now=now)
        self.assertIn("nothing to compact", status["state"])


class TestRulesAndSpace(unittest.TestCase):
    def test_runtime_parsing(self):
        self.assertAlmostEqual(cr.runtime_minutes({"mediaInfo": {"runTime": "1:01:14"}}), 61.23, places=2)
        self.assertEqual(cr.runtime_minutes({"mediaInfo": {"runTime": "45:30"}}), 45.5)
        self.assertEqual(cr.runtime_minutes({}, 61), 61)

    def test_space_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "torrents" / "tv" / "Kept").mkdir(parents=True)
            (root / "media" / "tv").mkdir(parents=True)
            (root / "media" / ".recycle").mkdir(parents=True)
            used = root / "torrents" / "tv" / "Kept" / "a.mkv"
            used.write_bytes(b"x" * 10)
            orphan = root / "torrents" / "tv" / "old.mkv"
            orphan.write_bytes(b"x" * 20)
            linked = root / "torrents" / "tv" / "linked.mkv"
            linked.write_bytes(b"x" * 30)
            try:
                os.link(linked, root / "media" / "tv" / "linked.mkv")
            except OSError:
                self.skipTest("hardlinks not supported here")
            (root / "media" / ".recycle" / "gone.mkv").write_bytes(b"x" * 40)
            (root / "media" / "tv" / ".missing.mkv.0.archos.resume.xml").write_text("<x/>", encoding="utf-8")
            (root / "media" / "tv" / ".linked.mkv.0.archos.resume.xml").write_text("<x/>", encoding="utf-8")
            report = cr.space_report(str(root), [{"content_path": "/data/torrents/tv/Kept"}])
            self.assertEqual(report["torrent_orphans"]["files"], 1)
            self.assertEqual(report["torrent_orphans"]["examples"], [str(Path("torrents/tv/old.mkv"))])
            self.assertEqual(report["nova_resume_files"], {"files": 2, "orphans": 1})
            self.assertEqual(cr.resume_video(Path("/m/.Show.S01E01.mkv.0.archos.resume.xml")), Path("/m/Show.S01E01.mkv"))


if __name__ == "__main__":
    unittest.main()
