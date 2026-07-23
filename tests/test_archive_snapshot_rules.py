from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from netease_dynamic_watcher.archive_view import render_archive_html


class ArchiveSnapshotTests(unittest.TestCase):
    def test_avatar_snapshot_and_duplicate_image_positions_are_rendered(self):
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
                    "https://img.music.126.net/photo.jpg?a=2",
                ],
                "raw_payload": {},
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            html = render_archive_html(events, Path(temp) / "events.html")

        self.assertIn("测试用户", html)
        self.assertIn("图片 1/2", html)
        self.assertIn("图片 2/2", html)


if __name__ == "__main__":
    unittest.main()
