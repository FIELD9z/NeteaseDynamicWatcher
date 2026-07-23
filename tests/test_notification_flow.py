from __future__ import annotations

import tempfile
import unittest

from netease_dynamic_watcher.models import Event
from netease_dynamic_watcher.store import StateStore


class NotificationStateTests(unittest.TestCase):
    def test_existing_event_is_suppressed_after_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(f"{temp}/watcher.sqlite3")
            event = Event(
                event_id="old",
                user_id="1413380977",
                nickname="test",
                event_type="dynamic",
                summary="old",
                publish_time_ms=1,
                url="",
                raw_type="",
                image_urls=(),
                video_urls=(),
                forwarded_event_id="",
                forwarded_summary="",
                comment_count=0,
                share_count=0,
                liked_count=0,
                comment_thread_id="",
                raw_payload={},
            )
            store.save(event)
            StateStore(f"{temp}/watcher.sqlite3")
            self.assertEqual(
                store.get_notification_state("1413380977", "old"),
                "suppressed",
            )

    def test_failed_notification_keeps_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(f"{temp}/watcher.sqlite3")
            store.mark_notification_failed("u", "missing", "error")
            self.assertEqual(store.pending_notification_count("u"), 0)


if __name__ == "__main__":
    unittest.main()
