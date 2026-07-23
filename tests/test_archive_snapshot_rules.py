from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from netease_dynamic_watcher.archive_view import render_archive_html
from netease_dynamic_watcher.media_archive import canonical_media_url
from netease_dynamic_watcher.models import Event
from netease_dynamic_watcher.store import StateStore
from tools import open_ui


class ArchiveSnapshotTests(unittest.TestCase):
    def test_html_uses_only_local_avatar_images_and_video(self):
        events = [
            {
                "event_id": "event-1",
                "nickname": "测试用户",
                "avatar_url": "https://img.music.126.net/avatar-old.jpg",
                "event_type": "dynamic",
                "publish_time_ms": "1750000000000",
                "summary": "包含重复图片位置",
                "image_urls": [
                    "https://img.music.126.net/photo.jpg?a=1",
                ],
                "video_urls": ["https://vod.126.net/video.mp4"],
                "raw_payload": {},
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "export" / "events.html"
            local_avatar = root / "media" / "avatar.jpg"
            local_image = root / "media" / "photo.jpg"
            local_video = root / "media" / "video.mp4"
            for path in (local_avatar, local_image, local_video):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"offline")
            media_map = {
                (
                    "event-1",
                    "avatar",
                    canonical_media_url(events[0]["avatar_url"], "avatar"),
                ): local_avatar,
                (
                    "event-1",
                    "image",
                    canonical_media_url(events[0]["image_urls"][0], "image"),
                ): local_image,
                (
                    "event-1",
                    "video",
                    canonical_media_url(events[0]["video_urls"][0], "video"),
                ): local_video,
            }
            html = render_archive_html(events, output, media_map)

        self.assertIn("测试用户", html)
        self.assertIn("media/avatar.jpg", html)
        self.assertIn("media/photo.jpg", html)
        self.assertIn("media/video.mp4", html)
        self.assertNotIn("https://img.music.126.net", html)
        self.assertNotIn("https://vod.126.net", html)
        self.assertIn("connect-src &#x27;none&#x27;", html.replace("'", "&#x27;"))

    def test_duplicate_image_positions_are_rendered_twice(self):
        source_one = "https://img.music.126.net/photo.jpg?a=1"
        source_two = "https://img.music.126.net/photo.jpg?a=2"
        events = [
            {
                "event_id": "event-1",
                "nickname": "测试用户",
                "event_type": "image",
                "publish_time_ms": "1750000000000",
                "summary": "包含重复图片位置",
                "image_urls": [source_one, source_two],
                "raw_payload": {},
            }
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_image = root / "media" / "photo.jpg"
            local_image.parent.mkdir(parents=True)
            local_image.write_bytes(b"same image")
            media_map = {
                (
                    "event-1",
                    "image",
                    canonical_media_url(source_one, "image"),
                ): local_image
            }
            html = render_archive_html(events, root / "export" / "events.html", media_map)

        self.assertEqual(html.count('class="media-item"'), 2)
        self.assertIn("图片 1/2", html)
        self.assertIn("图片 2/2", html)

    def test_open_ui_skip_archive_never_calls_archiver_or_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "watcher.sqlite3"
            StateStore(str(database)).save(
                Event(
                    event_id="local",
                    user_id="u",
                    nickname="offline",
                    event_type="dynamic",
                    summary="saved",
                    publish_time_ms=1_750_000_000_000,
                    url="",
                )
            )
            with (
                mock.patch(
                    "sys.argv",
                    [
                        "open_ui.py",
                        "--database",
                        str(database),
                        "--skip-archive",
                        "--no-browser",
                    ],
                ),
                mock.patch.object(open_ui, "archive_database_media") as archive,
                mock.patch.object(open_ui.webbrowser, "open") as browser,
            ):
                open_ui.main()

            archive.assert_not_called()
            browser.assert_not_called()
            self.assertTrue((root / "export" / "events.html").exists())

    def test_database_path_change_moves_media_and_export_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "isolated-data" / "alternate.sqlite3"

            media_dir, manifest = __import__("run_watcher").media_paths(str(database))
            output, ui_media, ui_manifest = open_ui.derived_paths(database)

            self.assertEqual(media_dir, database.parent / "media")
            self.assertEqual(manifest, database.parent / "media" / "manifest.json")
            self.assertEqual(output, database.parent / "export" / "events.html")
            self.assertEqual(ui_media, media_dir)
            self.assertEqual(ui_manifest, manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
