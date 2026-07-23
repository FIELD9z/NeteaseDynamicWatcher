import unittest

from netease_dynamic_watcher.parser import parse_events


class RichEventTests(unittest.TestCase):
    def test_rich_event_fields_are_kept(self):
        events = parse_events(
            {
                "events": [
                    {
                        "id": "1",
                        "type": 18,
                        "time": 123,
                        "pics": [{"originUrl": "https://example.com/a.jpg"}],
                        "json": {
                            "msg": "hello",
                            "song": {
                                "name": "song name",
                                "artists": [{"name": "artist"}],
                            },
                        },
                        "info": {
                            "commentCount": 2,
                            "shareCount": 3,
                            "likedCount": 4,
                            "threadId": "thread",
                        },
                    }
                ]
            },
            user_id="1413380977",
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "song_share")
        self.assertEqual(event.image_urls, ("https://example.com/a.jpg",))
        self.assertEqual(event.comment_count, 2)
        self.assertEqual(event.raw_payload["id"], "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
