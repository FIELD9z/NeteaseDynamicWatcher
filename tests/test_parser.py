from netease_dynamic_watcher.parser import parse_events


def test_parse_mock_response():
    events = parse_events({"events": [{"id": 1, "type": "song_share", "summary": "test"}]})
    assert len(events) == 1
    assert events[0].event_type == "song_share"
