from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import run_watcher
from tools import archive_media, export_events, open_ui


class ToolPathTests(unittest.TestCase):
    def test_all_tool_defaults_follow_database_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "isolated" / "watcher.sqlite3"

            watcher_media, watcher_manifest = run_watcher.media_paths(database)
            ui_output, ui_media, ui_manifest = open_ui.derived_paths(database)
            archive_output, archive_manifest = archive_media.derived_media_paths(database)
            export_output, export_media, export_manifest = export_events.derived_export_paths(
                database
            )

            expected_media = database.parent / "media"
            expected_manifest = expected_media / "manifest.json"
            expected_export = database.parent / "export" / "events.html"

            self.assertEqual(watcher_media, expected_media)
            self.assertEqual(watcher_manifest, expected_manifest)
            self.assertEqual(ui_output, expected_export)
            self.assertEqual(ui_media, expected_media)
            self.assertEqual(ui_manifest, expected_manifest)
            self.assertEqual(archive_output, expected_media)
            self.assertEqual(archive_manifest, expected_manifest)
            self.assertEqual(export_output, expected_export)
            self.assertEqual(export_media, expected_media)
            self.assertEqual(export_manifest, expected_manifest)

    def test_csv_export_keeps_event_avatar_snapshot(self):
        events = [
            {
                "event_id": "event-1",
                "user_id": "user-1",
                "nickname": "测试用户",
                "avatar_url": "https://img.music.126.net/avatar-old.jpg",
                "event_type": "dynamic",
                "publish_time_ms": 1_750_000_000_000,
                "summary": "历史头像快照",
                "image_urls": [],
                "video_urls": [],
                "raw_payload": {},
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "events.csv"
            export_events.export_csv(events, output)
            with output.open(newline="", encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], "event-1")
        self.assertEqual(
            rows[0]["avatar_url"],
            "https://img.music.126.net/avatar-old.jpg",
        )

    def test_export_skip_archive_never_calls_media_archiver(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            output = Path(temp) / "export" / "events.html"

            with (
                mock.patch(
                    "sys.argv",
                    [
                        "export_events.py",
                        "--database",
                        str(database),
                        "--output",
                        str(output),
                        "--skip-archive",
                    ],
                ),
                mock.patch.object(export_events, "archive_database_media") as archive,
                mock.patch.object(export_events, "load_archive_events", return_value=[]),
                mock.patch.object(export_events, "write_archive_html"),
                mock.patch.object(export_events, "collect_runtime_summary", return_value={}),
                mock.patch.object(export_events, "export_json"),
                mock.patch.object(export_events, "export_csv"),
            ):
                export_events.main()

            archive.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
