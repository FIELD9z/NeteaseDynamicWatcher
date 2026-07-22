from netease_dynamic_watcher.parser import parse_events


def test_rich_event_fields_are_kept():
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

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "song_share"
    assert event.image_urls == ("https://example.com/a.jpg",)
    assert event.comment_count == 2
    assert event.raw_payload["id"] == "1"
