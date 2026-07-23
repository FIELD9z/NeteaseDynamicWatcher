import unittest

from netease_dynamic_watcher.config import Config
from netease_dynamic_watcher.parser import parse_events


class RuntimeFlowTests(unittest.TestCase):
    def test_config_does_not_print_secrets(self):
        config = Config.from_env(
            {
                "NETEASE_COOKIE": "secret-cookie",
                "PUSHME_KEY": "secret-key",
                "TARGET_UID": "1413380977",
            }
        )
        summary = config.safe_summary()
        self.assertIs(summary["has_cookie"], True)
        self.assertIs(summary["has_notification_key"], True)
        self.assertNotIn("secret-cookie", str(summary))
        self.assertNotIn("secret-key", str(summary))

    def test_song_share_detection_from_mock_data(self):
        events = parse_events(
            {
                "events": [
                    {
                        "id": 100,
                        "song": {"id": 1},
                        "summary": "shared song",
                    }
                ]
            }
        )
        self.assertEqual(events[0].event_type, "song_share")


if __name__ == "__main__":
    unittest.main(verbosity=2)
