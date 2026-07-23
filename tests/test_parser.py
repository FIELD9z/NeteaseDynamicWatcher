import unittest

from netease_dynamic_watcher.parser import parse_events


class ParserTests(unittest.TestCase):
    def test_parse_mock_response(self):
        events = parse_events(
            {"events": [{"id": 1, "type": "song_share", "summary": "test"}]}
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "song_share")

    def test_one_image_object_merges_multiple_thumbnail_urls(self):
        events = parse_events(
            {
                "events": [
                    {
                        "id": "thumbs",
                        "pics": [
                            {
                                "originUrl": "https://p1.music.126.net/photo.jpg",
                                "squareUrl": "https://p1.music.126.net/photo.jpg?size=200",
                                "rectangleUrl": "https://p1.music.126.net/photo.jpg?size=400",
                            }
                        ],
                    }
                ]
            }
        )
        self.assertEqual(
            events[0].image_urls,
            ("https://p1.music.126.net/photo.jpg",),
        )

    def test_two_logically_equal_image_positions_are_preserved(self):
        events = parse_events(
            {
                "events": [
                    {
                        "id": "duplicates",
                        "pics": [
                            {"originUrl": "https://p1.music.126.net/photo.jpg?x=1"},
                            {"originUrl": "https://p1.music.126.net/photo.jpg?x=2"},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(len(events[0].image_urls), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
