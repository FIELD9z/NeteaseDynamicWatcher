from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from netease_dynamic_watcher.archive_view import render_archive_html


class ArchiveViewTests(unittest.TestCase):
    def test_render_archive_contains_core_sections(self):
        events = [
            {
                "event_id": "1",
                "nickname": "测试用户",
                "event_type": "dynamic",
                "publish_time_ms": "1750000000000",
                "summary": "普通动态",
                "image_urls": ["https://example.com/a.jpg"],
                "raw_payload": {},
            },
            {
                "event_id": "2",
                "nickname": "测试用户",
                "event_type": "song_share",
                "publish_time_ms": "1751000000000",
                "summary": "分享歌曲",
                "raw_payload": {
                    "song": {
                        "id": 123,
                        "name": "测试歌曲",
                        "ar": [{"name": "测试歌手"}],
                    }
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp:
            html = render_archive_html(events, Path(temp) / "events.html")

        self.assertIn("测试歌曲", html)
        self.assertIn("测试用户", html)
        self.assertIn("data-filter", html)
        self.assertIn("archive.css", html)
        self.assertIn("archive.js", html)


if __name__ == "__main__":
    unittest.main()
