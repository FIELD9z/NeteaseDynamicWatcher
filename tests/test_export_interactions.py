from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools import export_events


class ExportInteractionTests(unittest.TestCase):
    def test_attach_interactions_adds_snapshot_without_changing_events(self):
        events = [{"event_id": "e1", "summary": "demo"}]
        interactions = {
            "e1": {
                "comments": [{"content": "hello"}],
                "likers": [{"user_id": "1"}],
                "state": {"status": "success"},
            }
        }
        result = export_events.attach_interactions(events, interactions)
        self.assertEqual(events, [{"event_id": "e1", "summary": "demo"}])
        self.assertEqual(result[0]["interactions"]["comments"][0]["content"], "hello")
        self.assertEqual(result[0]["interactions"]["likers"][0]["user_id"], "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
