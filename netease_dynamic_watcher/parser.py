from netease_dynamic_watcher.store import Event


def parse_events(payload: dict):
    result = []
    for item in payload.get("events", []):
        result.append(Event(
            event_id=str(item.get("id")),
            event_type=item.get("type", "unknown"),
            summary=item.get("summary", ""),
            publish_time=int(item.get("time", 0)),
            url=item.get("url", "https://music.163.com")
        ))
    return result
