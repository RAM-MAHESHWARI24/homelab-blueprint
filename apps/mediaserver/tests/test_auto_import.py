"""Unit tests for scripts/auto_import.py: title verification, safety guards, and Radarr/Sonarr queue handling."""

from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import auto_import as ai  # noqa: E402
import wire_arr as wa  # noqa: E402


class FakeArrClient(ai.ArrClient):
    def __init__(self, app_type: str, responses: Dict[str, Tuple[int, Any]]):
        super().__init__(app_type, f"http://127.0.0.1:{7878 if app_type == 'radarr' else 8989}", "secret-test-key")
        self.responses = responses
        self.posts: list[tuple[str, Any]] = []

    def request_json(self, path: str, method: str = "GET", payload: Any = None) -> Tuple[int, Any]:
        if method == "POST":
            self.posts.append((path, payload))
            return 201, {"id": 99}
        for prefix, val in self.responses.items():
            if path.startswith(prefix):
                return val
        return 404, {"error": f"unmocked path {path}"}


class TestTitleVerification(unittest.TestCase):
    def test_franchise_prefixed_release_matches_exact_title(self) -> None:
        movie = {"title": "Quantum of Solace", "originalTitle": "Quantum of Solace", "year": 2008, "alternateTitles": []}
        self.assertTrue(
            ai.title_matches_release(
                movie,
                "007 James Bond Quantum of Solace 2008 1080p BluRay x264 AAC - Ozlem.mp4",
            )
        )

    def test_spoofed_different_movie_fails_title_check(self) -> None:
        movie = {"title": "Quantum of Solace", "originalTitle": "Quantum of Solace", "year": 2008, "alternateTitles": []}
        self.assertFalse(
            ai.title_matches_release(movie, "Casino Royale 2006 1080p BluRay.mkv")
        )

    def test_short_title_requires_word_boundary_and_year(self) -> None:
        movie = {"title": "Up", "originalTitle": "Up", "year": 2009, "alternateTitles": []}
        self.assertFalse(ai.title_matches_release(movie, "Backup.Guide.2024.1080p.mkv"))
        self.assertFalse(ai.title_matches_release(movie, "Up.1080p.BluRay.mkv"))
        self.assertTrue(ai.title_matches_release(movie, "Up.2009.1080p.BluRay.mkv"))

    def test_sample_filtering_and_rejection_guards(self) -> None:
        self.assertFalse(ai.is_video_non_sample("/data/torrents/movies/Movie/Sample/movie-sample.mkv"))
        self.assertFalse(ai.is_video_non_sample("/data/torrents/movies/Movie/payload.exe"))
        self.assertTrue(ai.is_video_non_sample("/data/torrents/movies/Movie/Sample.Man.2020.mkv") is False)
        self.assertTrue(ai.is_video_non_sample("/data/torrents/movies/Movie/Quantum.of.Solace.2008.mp4"))

        self.assertTrue(ai.only_allowed_rejections([]))
        self.assertTrue(ai.only_allowed_rejections([{"reason": "Unknown Movie", "type": "permanent"}]))
        self.assertFalse(
            ai.only_allowed_rejections([
                {"reason": "Unknown Movie", "type": "permanent"},
                {"reason": "Not an upgrade for existing movie file", "type": "permanent"},
            ])
        )


class TestRadarrAndSonarrAutoImport(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("test_auto_import")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def test_imports_single_file_matched_by_id_when_title_matches(self) -> None:
        client = FakeArrClient(
            "radarr",
            {
                "/api/v3/queue": (
                    200,
                    {
                        "records": [
                            {
                                "id": 1131356426,
                                "movieId": 108,
                                "title": "007 James Bond Quantum of Solace 2008 1080p -Ozlem",
                                "trackedDownloadState": "importBlocked",
                                "downloadId": "HASH108",
                                "statusMessages": [
                                    {
                                        "title": "007 James Bond Quantum of Solace 2008 1080p -Ozlem",
                                        "messages": [
                                            "Found matching movie via grab history, but release was matched to movie by ID. Manual Import required."
                                        ],
                                    }
                                ],
                            }
                        ]
                    },
                ),
                "/api/v3/manualimport": (
                    200,
                    [
                        {
                            "path": "/data/torrents/movies/007 Quantum/007 James Bond Quantum of Solace 2008 1080p - Ozlem.mp4",
                            "relativePath": "007 James Bond Quantum of Solace 2008 1080p - Ozlem.mp4",
                            "folderName": "007 Quantum",
                            "name": "007 James Bond Quantum of Solace 2008 1080p - Ozlem",
                            "movie": None,
                            "quality": {"quality": {"id": 7, "name": "Bluray-1080p"}},
                            "languages": [{"id": 1, "name": "English"}],
                            "indexerFlags": 1,
                            "releaseGroup": "Ozlem",
                            "rejections": [{"reason": "Unknown Movie", "type": "permanent"}],
                        },
                        {
                            "path": "/data/torrents/movies/007 Quantum/sample.mp4",
                            "relativePath": "sample.mp4",
                            "rejections": [],
                        },
                    ],
                ),
                "/api/v3/movie/108": (
                    200,
                    {"id": 108, "title": "Quantum of Solace", "originalTitle": "Quantum of Solace", "year": 2008, "alternateTitles": []},
                ),
            },
        )
        res = ai.process_radarr(client, dry_run=False, logger=self.logger)
        self.assertEqual(len(res["imported"]), 1)
        self.assertEqual(res["imported"][0]["target"], "Quantum of Solace")
        self.assertEqual(len(client.posts), 1)
        path, payload = client.posts[0]
        self.assertEqual(path, "/api/v3/command")
        self.assertEqual(payload["name"], "ManualImport")
        self.assertEqual(payload["files"][0]["movieId"], 108)
        self.assertEqual(payload["files"][0]["downloadId"], "HASH108")

    def test_skips_spoofed_movie_id_with_different_title(self) -> None:
        client = FakeArrClient(
            "radarr",
            {
                "/api/v3/queue": (
                    200,
                    {
                        "records": [
                            {
                                "id": 22,
                                "movieId": 108,
                                "title": "Completely Unrelated Release 2024",
                                "trackedDownloadState": "importBlocked",
                                "downloadId": "HASHSPOOF",
                                "statusMessages": [{"title": "x", "messages": ["Manual Import required."]}],
                            }
                        ]
                    },
                ),
                "/api/v3/manualimport": (
                    200,
                    [
                        {
                            "path": "/data/torrents/movies/Wrong/Completely Unrelated Release 2024.mkv",
                            "relativePath": "Completely Unrelated Release 2024.mkv",
                            "movie": {"id": 108, "title": "Quantum of Solace", "year": 2008, "alternateTitles": []},
                            "rejections": [],
                        }
                    ],
                ),
            },
        )
        res = ai.process_radarr(client, dry_run=False, logger=self.logger)
        self.assertEqual(res["imported"], [])
        self.assertEqual(res["skipped"][0]["reason"], "title verification mismatch")
        self.assertEqual(client.posts, [])

    def test_skips_multi_file_pack_in_radarr(self) -> None:
        client = FakeArrClient(
            "radarr",
            {
                "/api/v3/queue": (
                    200,
                    {
                        "records": [
                            {
                                "id": 33,
                                "movieId": 108,
                                "title": "Bond Pack",
                                "trackedDownloadState": "importBlocked",
                                "downloadId": "HASHPACK",
                                "statusMessages": [{"title": "x", "messages": ["Manual Import required."]}],
                            }
                        ]
                    },
                ),
                "/api/v3/manualimport": (
                    200,
                    [
                        {"path": "/data/torrents/movies/Pack/part1.mkv", "rejections": []},
                        {"path": "/data/torrents/movies/Pack/part2.mkv", "rejections": []},
                    ],
                ),
            },
        )
        res = ai.process_radarr(client, dry_run=False, logger=self.logger)
        self.assertEqual(res["imported"], [])
        self.assertIn("found 2", res["skipped"][0]["reason"])

    def test_sonarr_imports_single_matched_episode_and_reads_xml_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "sonarr"
            cfg.mkdir()
            (cfg / "config.xml").write_text("<Config><ApiKey>sonarr-key-xyz</ApiKey></Config>", encoding="utf-8")
            self.assertEqual(ai.read_api_key_from_config(Path(tmp), "sonarr"), "sonarr-key-xyz")

        client = FakeArrClient(
            "sonarr",
            {
                "/api/v3/queue": (
                    200,
                    {
                        "records": [
                            {
                                "id": 77,
                                "seriesId": 12,
                                "episodeId": 401,
                                "title": "Severance S02E01 1080p",
                                "trackedDownloadState": "importBlocked",
                                "downloadId": "SONARRHASH1",
                                "statusMessages": [{"title": "x", "messages": ["Manual Import required."]}],
                            }
                        ]
                    },
                ),
                "/api/v3/manualimport": (
                    200,
                    [
                        {
                            "path": "/data/torrents/tv/Severance.S02E01/Severance.S02E01.1080p.mkv",
                            "relativePath": "Severance.S02E01.1080p.mkv",
                            "folderName": "Severance.S02E01",
                            "series": {"id": 12, "title": "Severance", "year": 2022, "alternateTitles": []},
                            "episodes": [{"id": 401}],
                            "quality": {"quality": {"id": 7, "name": "WEBDL-1080p"}},
                            "languages": [{"id": 1, "name": "English"}],
                            "rejections": [],
                        }
                    ],
                ),
            },
        )
        res = ai.process_sonarr(client, dry_run=False, logger=self.logger)
        self.assertEqual(len(res["imported"]), 1)
        self.assertEqual(client.posts[0][1]["files"][0]["episodeIds"], [401])


class TestWireArrHardening(unittest.TestCase):
    def setUp(self) -> None:
        wa.report["steps"].clear()
        wa.report["errors"].clear()
        wa.report["warnings"].clear()

    def test_ensure_restriction_term_is_idempotent(self) -> None:
        class _FakeArr:
            name = "radarr"

            def __init__(self) -> None:
                self.posted: list[tuple[str, Any]] = []
                self.items: list[Dict[str, Any]] = []

            def get(self, path: str) -> Tuple[int, Any]:
                return (200, self.items) if path == "restriction" else (404, None)

            def post(self, path: str, data: Any) -> Tuple[int, Any]:
                self.posted.append((path, data))
                self.items.append(data)
                return 201, data

        arr = _FakeArr()
        wa.ensure_restriction_term(arr, "Ozlem")  # type: ignore[arg-type]
        wa.ensure_restriction_term(arr, "Ozlem")  # type: ignore[arg-type]
        self.assertEqual(len(arr.posted), 1)
        self.assertEqual(arr.posted[0][1]["ignored"], ["Ozlem"])

    def test_deprioritize_tpb_only_when_multiple_enabled_and_default_priority(self) -> None:
        class _FakeProwlarr:
            name = "prowlarr"

            def __init__(self) -> None:
                self.puts: list[tuple[str, Any]] = []

            def get(self, path: str) -> Tuple[int, Any]:
                return 200, [
                    {"id": 1, "name": "YTS", "enable": True, "priority": 25},
                    {"id": 2, "name": "The Pirate Bay", "enable": True, "priority": 25},
                ]

            def put(self, path: str, data: Any) -> Tuple[int, Any]:
                self.puts.append((path, data))
                return 202, data

        px = _FakeProwlarr()
        wa.deprioritize_unmoderated_indexers(px)  # type: ignore[arg-type]
        self.assertEqual(len(px.puts), 1)
        self.assertEqual(px.puts[0][0], "indexer/2")
        self.assertEqual(px.puts[0][1]["priority"], 45)


if __name__ == "__main__":
    unittest.main()
