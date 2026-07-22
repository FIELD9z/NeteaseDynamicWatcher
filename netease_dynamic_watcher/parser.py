from netease_dynamic_watcher.models import Event


def parse_events(payload: dict, user_id: str = ""):
    result = []
    for item in payload.get("events", []):
        if not item.get("id"):
            continue
        event_type = item.get("type", "dynamic")
        if item.get("song") or event_type == "song_share":
            event_type = "song_share"
        result.append(Event(
            event_id=str(item["id"]),
            user_id=user_id,
            nickname=item.get("nickname", "未知用户"),
            event_type=event_type,
            summary=item.get("summary", ""),
            publish_time_ms=int(item.get("time", 0)),
            url=item.get("url", "https://music.163.com")
        ))
    return result
