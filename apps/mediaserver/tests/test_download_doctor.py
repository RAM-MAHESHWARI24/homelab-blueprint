"""
Tests for scripts/download_doctor.py (media pipeline plan section 8.8 and Appendix I).
Fake qBittorrent and Radarr/Sonarr clients; time is simulated, one check every 10 minutes.
Standard library only.
"""

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import download_doctor as dd  # noqa: E402

T0 = 1_800_000_000.0  # a fixed start time
MIN = 60
H = 3600


def torrent(h, state="stalledDL", progress=0.0, availability=0.0, downloaded=0, category="radarr", **kw):
    t = {"hash": h, "name": f"Torrent {h}", "state": state, "progress": progress, "availability": availability,
         "downloaded": downloaded, "category": category, "dlspeed": 0, "eta": 8640000, "num_seeds": 0,
         "has_metadata": state not in ("metaDL", "forcedMetaDL"), "tags": "", "private": False}
    t.update(kw)
    return t


def record(rid, h, movie=None, series=None, season=None, title=None, state="downloading", messages=None):
    r = {"id": rid, "downloadId": h.upper(), "title": title or f"Release {h}", "protocol": "torrent",
         "trackedDownloadState": state, "statusMessages": messages or [], "indexer": "Idx"}
    if movie is not None:
        r["movieId"] = movie
    if series is not None:
        r.update(seriesId=series, seasonNumber=season, episodeId=rid)
    return r


class FakeQbit:
    ready, detail = True, ""

    def __init__(self, torrents, connected=True, dht=363):
        self.list = torrents
        self.info = {"connection_status": "connected" if connected else "disconnected", "dht_nodes": dht}
        self.reannounced = []

    def torrents(self):
        return copy.deepcopy(self.list)

    def transfer(self):
        return dict(self.info)

    def reannounce(self, h):
        self.reannounced.append(h)
        return True


class FakeArr:
    def __init__(self, records=None, blocklist=None, movies=None, episodes=None, library=None, files=None, profiles=None):
        self.records = records or []
        self.library = library or []          # GET /movie or /series
        self.files = files or []              # GET /moviefile or /episodefile
        self.profiles = profiles if profiles is not None else [{"id": 1, "upgradeAllowed": True, "cutoffFormatScore": 4700}]
        self.blocklist = blocklist or []
        self.movies = movies or {}
        self.episodes = episodes or {}
        self.calls = []

    def request_json(self, path, method="GET", payload=None):
        if method != "GET":
            self.calls.append((method, path, payload))
        if path.startswith("/api/v3/downloadclient"):
            return 200, []
        if path.startswith("/api/v3/queue?"):
            return 200, {"records": copy.deepcopy(self.records)}
        if path.startswith("/api/v3/queue/") and method == "DELETE":
            ids = payload["ids"] if payload else [int(path.split("/")[-1].split("?")[0])]
            self.records = [r for r in self.records if r["id"] not in ids]
            return 200, {}
        if path == "/api/v3/qualityprofile":
            return 200, self.profiles
        if path in ("/api/v3/movie", "/api/v3/series"):
            return 200, self.library
        if path.startswith("/api/v3/moviefile?"):
            ids = {int(x.split("=")[1]) for x in path.split("?", 1)[1].split("&")}
            return 200, [f for f in self.files if f["movieId"] in ids]
        if path.startswith("/api/v3/episodefile?"):
            sid = int(path.split("=")[1])
            return 200, [f for f in self.files if f["seriesId"] == sid]
        if path == "/api/v3/command":
            return 201, {}
        if path.startswith("/api/v3/blocklist?"):
            return 200, {"records": self.blocklist}
        if path.startswith("/api/v3/blocklist/bulk"):
            return 200, {}
        if path.startswith("/api/v3/movie/"):
            return 200, self.movies.get(int(path.rsplit("/", 1)[1]), {})
        if path.startswith("/api/v3/episode?"):
            ids = [int(x.split("=")[1]) for x in path.split("?", 1)[1].split("&")]
            return 200, [self.episodes[i] for i in ids if i in self.episodes]
        return 404, None

    def deletes(self):
        return [c for c in self.calls if c[0] == "DELETE"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def doctor(self, qbit, arrs, now, **kw):
        kw.setdefault("watch_days", 0)
        return dd.Doctor(qbit, arrs, self.dir, now=lambda: now, **kw)

    def checks(self, qbit, arrs, start, hours, step=10 * MIN, **kw):
        """One check every `step` seconds for `hours`; returns the last status and the end time."""
        t, status = start, None
        while t <= start + hours * H:
            status = self.doctor(qbit, arrs, t, **kw).run_stuck()
            t += step
        return status, t


class TestStuckRules(Base):
    def test_metadata_stuck_is_replaced_after_two_awake_hours(self):
        qbit = FakeQbit([torrent("aa", state="metaDL")])
        radarr = FakeArr([record(1, "aa", movie=11)])
        status, _ = self.checks(qbit, {"radarr": radarr}, T0, 2)  # 30-minute wake grace first
        self.assertEqual(radarr.deletes(), [])
        status, _ = self.checks(qbit, {"radarr": radarr}, T0 + 2 * H + 10 * MIN, 0.6)
        (method, path, payload), = radarr.deletes()
        self.assertEqual(path, "/api/v3/queue/1?removeFromClient=true&blocklist=true&skipRedownload=false")
        self.assertIsNone(payload)
        self.assertNotIn("aa", dd.read_json(self.dir / "state.json", {})["torrents"])

    def test_dead_swarm_at_99_8_percent_is_replaced_after_12_hours(self):
        """Appendix I #9: 99.8% done, availability 0.998 - 4 MB exist nowhere in the swarm."""
        qbit = FakeQbit([torrent("bb", state="forcedDL", progress=0.998, availability=0.998, num_seeds=0)])
        radarr = FakeArr([record(1, "bb", movie=12)])
        status, t = self.checks(qbit, {"radarr": radarr}, T0, 12)
        self.assertEqual(status["problems"][0]["reason"], "dead")
        self.assertEqual(radarr.deletes(), [])
        self.checks(qbit, {"radarr": radarr}, t, 1)
        self.assertEqual(len(radarr.deletes()), 1)

    def test_near_complete_with_a_full_copy_is_reannounced_first_and_waits_twice_as_long(self):
        qbit = FakeQbit([torrent("cc", progress=0.99, availability=1.4)])
        radarr = FakeArr([record(1, "cc", movie=13)])
        _, t = self.checks(qbit, {"radarr": radarr}, T0, 2)
        self.assertEqual(qbit.reannounced, ["cc"])
        _, t = self.checks(qbit, {"radarr": radarr}, t, 12)
        self.assertEqual(radarr.deletes(), [], "patience doubled to 24 h")
        self.checks(qbit, {"radarr": radarr}, t, 12)
        self.assertEqual(len(radarr.deletes()), 1)
        self.assertEqual(qbit.reannounced, ["cc"], "re-announced once")

    def test_no_strikes_right_after_wake_or_while_offline(self):
        qbit = FakeQbit([torrent("dd")])
        radarr = FakeArr([record(1, "dd", movie=14)])
        self.checks(qbit, {"radarr": radarr}, T0, 3)
        state = dd.read_json(self.dir / "state.json", {})
        before = state["torrents"]["DD"]["bad_seconds"]
        status = self.doctor(qbit, {"radarr": radarr}, T0 + 3 * H + 6 * H).run_stuck()  # slept 6 hours
        self.assertIn("woke", status["grace"])
        self.assertEqual(dd.read_json(self.dir / "state.json", {})["torrents"]["DD"]["bad_seconds"], before)
        qbit.info["dht_nodes"] = 10
        self.doctor(qbit, {"radarr": radarr}, T0 + 9 * H + 20 * MIN).run_stuck()
        status = self.doctor(qbit, {"radarr": radarr}, T0 + 9 * H + 40 * MIN).run_stuck()
        self.assertIn("DHT", status["grace"])
        self.assertEqual(dd.read_json(self.dir / "state.json", {})["torrents"]["DD"]["bad_seconds"], before)

    def test_new_bytes_reset_the_strikes(self):
        qbit = FakeQbit([torrent("ee", downloaded=100)])
        radarr = FakeArr([record(1, "ee", movie=15)])
        _, t = self.checks(qbit, {"radarr": radarr}, T0, 6)
        qbit.list[0]["downloaded"] = 100 + 5 * (1 << 20)
        self.doctor(qbit, {"radarr": radarr}, t).run_stuck()
        self.assertEqual(dd.read_json(self.dir / "state.json", {})["torrents"]["EE"]["bad_seconds"], 0)

    def test_untouched_torrents(self):
        """Seeding, manual (not in any queue), wrong category, `keep`-tagged and private ones."""
        qbit = FakeQbit([torrent("f1", state="stalledUP", progress=1.0), torrent("f2"), torrent("f3", category="other"),
                         torrent("f4", tags="keep, x"), torrent("f5", private=True)])
        radarr = FakeArr([record(1, "f1", movie=1), record(3, "f3", movie=3), record(4, "f4", movie=4), record(5, "f5", movie=5)])
        status, _ = self.checks(qbit, {"radarr": radarr}, T0, 30)
        self.assertEqual(radarr.deletes(), [])
        self.assertEqual([p["action"] for p in status["problems"]], ["skipped (private tracker)"])
        self.assertEqual(status["managed"], 3, "f1, f4 and f5: in the queue and in the app's category")

    def test_season_pack_is_one_bulk_delete(self):
        qbit = FakeQbit([torrent("gg", state="metaDL", category="tv-sonarr")])
        sonarr = FakeArr([record(i, "gg", series=7, season=2) for i in (21, 22, 23)])
        self.checks(qbit, {"sonarr": sonarr}, T0, 3)
        (method, path, payload), = sonarr.deletes()
        self.assertTrue(path.startswith("/api/v3/queue/bulk?removeFromClient=true&blocklist=true"))
        self.assertEqual(payload, {"ids": [21, 22, 23]})

    def test_client_error_is_removed_without_blocklist(self):
        qbit = FakeQbit([torrent("hh", state="error")])
        radarr = FakeArr([record(1, "hh", movie=16)])
        self.checks(qbit, {"radarr": radarr}, T0, 2)
        self.assertIn("blocklist=false", radarr.deletes()[0][1])

    def test_queued_forever_only_alerts(self):
        qbit = FakeQbit([torrent("ii", state="queuedDL")])
        radarr = FakeArr([record(1, "ii", movie=17)])
        status, _ = self.checks(qbit, {"radarr": radarr}, T0, 25)
        self.assertEqual(radarr.deletes(), [])
        self.assertTrue(any(a["kind"] == "queued" for a in status["alerts"]))

    def test_permanent_import_block_is_replaced_after_six_hours(self):
        qbit = FakeQbit([torrent("jj", state="stalledUP", progress=1.0)])
        msg = [{"title": "Movie.mkv", "messages": ["No files found are eligible for import"]}]
        radarr = FakeArr([record(1, "jj", movie=18, state="importBlocked", messages=msg)])
        self.checks(qbit, {"radarr": radarr}, T0, 7)
        self.assertIn("blocklist=true", radarr.deletes()[0][1])


class TestSafetyRails(Base):
    def test_watch_only_changes_nothing_and_logs_once(self):
        qbit = FakeQbit([torrent("kk", state="metaDL")])
        radarr = FakeArr([record(1, "kk", movie=19)])
        status, _ = self.checks(qbit, {"radarr": radarr}, T0, 6, watch_days=7)
        self.assertEqual(status["mode"], "watch-only")
        self.assertEqual(radarr.calls, [])
        self.assertEqual(qbit.reannounced, [])
        log = (self.dir / "actions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log), 1)
        self.assertIn('"would_replace"', log[0])
        self.assertEqual(status["problems"][0]["action"], "would replace")

    def test_switched_off_does_nothing(self):
        qbit = FakeQbit([torrent("ll", state="metaDL")])
        radarr = FakeArr([record(1, "ll", movie=20)])
        status, _ = self.checks(qbit, {"radarr": radarr}, T0, 6, enabled=False)
        self.assertEqual(status["mode"], "off")
        self.assertEqual(radarr.calls, [])

    def test_circuit_breaker_when_most_turn_bad_at_once(self):
        healthy = [torrent(f"m{i}", state="downloading", dlspeed=50000, eta=600) for i in range(6)]
        qbit = FakeQbit(healthy)
        radarr = FakeArr([record(i + 1, f"m{i}", movie=100 + i) for i in range(6)])
        _, t = self.checks(qbit, {"radarr": radarr}, T0, 1)
        for x in qbit.list:
            x.update(state="stalledDL", dlspeed=0)
        status = self.doctor(qbit, {"radarr": radarr}, t).run_stuck()
        self.assertTrue(status["breaker"])
        self.assertIn("circuit breaker", status["grace"])

    def test_rate_limit_three_per_run(self):
        """Appendix I: all 20 torrents dead for days, qBittorrent connected (363 DHT nodes):
        no breaker (they did not turn bad at once); replacements go 3 per run."""
        qbit = FakeQbit([torrent(f"n{i}", state="metaDL") for i in range(20)])
        radarr = FakeArr([record(i + 1, f"n{i}", movie=200 + i) for i in range(20)])
        _, t = self.checks(qbit, {"radarr": radarr}, T0, 2.4)   # due at 2 h 20 (after the 30-minute wake grace)
        self.assertEqual(len(radarr.deletes()), 3)
        self.checks(qbit, {"radarr": radarr}, t, 1.5)
        self.assertEqual(len(radarr.deletes()), 15, "15 per day")

    def test_needs_attention_after_three_replacements_in_a_week(self):
        radarr = FakeArr()
        qbit = FakeQbit([])
        t = T0
        for i in range(4):
            qbit.list = [torrent(f"p{i}", state="metaDL")]
            radarr.records = [record(i + 1, f"p{i}", movie=42, title="Goldfinger (1964)")]
            status, t = self.checks(qbit, {"radarr": radarr}, t, 3)
        self.assertEqual(len(radarr.deletes()), 3)
        self.assertEqual(status["needs_attention"], ["Goldfinger (1964)"])


class TestSweepAndPrune(Base):
    def test_sweep_searches_oversized_first_and_caps_daily(self):
        library = [{"id": i, "title": f"Film {i}", "year": 2000, "runtime": 100, "monitored": True, "hasFile": True,
                    "qualityProfileId": 1} for i in range(17)]
        files = [{"movieId": i, "size": (9e9 if i == 7 else 2e9), "customFormatScore": 3050} for i in range(15)]
        files += [{"movieId": 15, "size": 2e9, "customFormatScore": 5010},                 # at its cutoff: skipped
                  {"movieId": 16, "size": 2e9, "customFormatScore": 4750, "qualityCutoffNotMet": False}]
        radarr = FakeArr(library=library, files=files)
        status = self.doctor(FakeQbit([]), {"radarr": radarr}, T0).run_sweep()
        self.assertEqual(len(status["searched"]), 10)
        self.assertEqual(status["searched"][0], "Film 7 (2000)", "90 MB/min is oversized")
        self.assertEqual(radarr.calls[0][2], {"name": "MoviesSearch", "movieIds": [7]})
        again = self.doctor(FakeQbit([]), {"radarr": radarr}, T0 + H).run_sweep()
        self.assertEqual(again["searched"], [], "10 per day")
        later = self.doctor(FakeQbit([]), {"radarr": radarr}, T0 + 2 * 86400).run_sweep()
        self.assertEqual(len(later["searched"]), 5, "the rest; the first 10 wait 14 days")

    def test_sweep_groups_episodes_into_season_searches(self):
        series = [{"id": 3, "title": "Succession", "runtime": 60, "monitored": True, "qualityProfileId": 1},
                  {"id": 4, "title": "Fine Show", "runtime": 60, "monitored": True, "qualityProfileId": 1}]
        files = [{"seriesId": 3, "seasonNumber": 1, "size": 3.5e9, "customFormatScore": 3150} for _ in range(5)]
        files += [{"seriesId": 4, "seasonNumber": 1, "size": 1e9, "customFormatScore": 4650}]
        sonarr = FakeArr(library=series, files=files, profiles=[{"id": 1, "upgradeAllowed": True, "cutoffFormatScore": 4500}])
        status = self.doctor(FakeQbit([]), {"sonarr": sonarr}, T0).run_sweep()
        self.assertEqual(status["searched"], ["Succession S01"])
        self.assertEqual(sonarr.calls[0][2], {"name": "SeasonSearch", "seriesId": 3, "seasonNumber": 1})

    def test_prune_only_old_entries_for_missing_titles(self):
        old, new = dd.iso(T0 - 90 * 86400), dd.iso(T0 - 5 * 86400)
        radarr = FakeArr(blocklist=[{"id": 1, "movieId": 5, "date": old}, {"id": 2, "movieId": 6, "date": old},
                                    {"id": 3, "movieId": 5, "date": new}],
                         movies={5: {"hasFile": False}, 6: {"hasFile": True}})
        status = self.doctor(FakeQbit([]), {"radarr": radarr}, T0).run_prune()
        self.assertEqual(status["pruned"], [{"app": "radarr", "entries": 1}])
        self.assertEqual(radarr.calls, [("DELETE", "/api/v3/blocklist/bulk", {"ids": [1]})])

    def test_watch_only_sweep_and_prune_change_nothing(self):
        radarr = FakeArr(library=[{"id": 1, "title": "F", "year": 1, "monitored": True, "hasFile": True, "qualityProfileId": 1}],
                         files=[{"movieId": 1, "size": 1, "customFormatScore": 0}],
                         blocklist=[{"id": 1, "movieId": 5, "date": dd.iso(T0 - 90 * 86400)}], movies={5: {"hasFile": False}})
        doc = self.doctor(FakeQbit([]), {"radarr": radarr}, T0, watch_days=7)
        doc.run_sweep()
        doc.run_prune()
        self.assertEqual(radarr.calls, [])
        self.assertEqual([c["action"] for c in doc.calls], ["would_search", "would_prune"])

    def test_status_keeps_sweep_section_across_stuck_runs(self):
        radarr = FakeArr(library=[{"id": 1, "title": "F", "year": 1, "monitored": True, "hasFile": True, "qualityProfileId": 1}],
                         files=[{"movieId": 1, "size": 1, "customFormatScore": 0}])
        self.doctor(FakeQbit([]), {"radarr": radarr}, T0).run_sweep()
        self.doctor(FakeQbit([]), {"radarr": radarr}, T0 + 600).run_stuck()
        self.assertIn("sweep", dd.read_json(self.dir / "status.json", {}))


class TestSchedule(unittest.TestCase):
    def test_cron_template(self):
        """Only placeholders the installer renders; every job shares one lock and state folder."""
        import re
        text = (Path(__file__).resolve().parent.parent / "host" / "cron" / "mediaserver-download-doctor").read_text(encoding="utf-8")
        self.assertLessEqual(set(re.findall(r"{{([A-Z_]+)}}", text)), {"MEDIA_APPDATA_DIR", "STATE_DIR", "ETC_DIR", "INSTALL_DIR"})
        jobs = [line for line in text.splitlines() if line and not line.startswith("#")]
        self.assertEqual([re.search(r"--job (\w+)", j).group(1) for j in jobs], ["stuck", "sweep", "prune"])
        for j in jobs:
            self.assertIn(" root /usr/bin/flock -w ", j)
            self.assertIn("{{STATE_DIR}}/download-doctor/.lock", j)
            self.assertIn("--state-dir {{STATE_DIR}}/download-doctor", j)
            self.assertIn("--env-file {{ETC_DIR}}/mediaserver.env", j)


if __name__ == "__main__":
    unittest.main()
