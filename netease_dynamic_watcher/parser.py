from __future__ import annotations

import json
from typing import Any

from netease_dynamic_watcher.models import Event


def _decode_embedded_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"msg": value.strip()}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _song_summary(payload: dict[str, Any]) -> str:
    song = payload.get("song")
    if not isinstance(song, dict):
        return ""
    name = str(song.get("name") or "").strip()
    artists_value = song.get("artists") or song.get("ar") or []
    artists = []
    if isinstance(artists_value, list):
        for artist in artists_value:
            if isinstance(artist, dict) and artist.get("name"):
                artists.append(str(artist["name"]).strip())
    if name and artists:
        return f"分享歌曲：{name} - {'/'.join(artists)}"
    if name:
        return f"分享歌曲：{name}"
    return "分享了一首歌曲"


def parse_events(payload: dict[str, Any], user_id: str = "") -> list[Event]:
    raw_events = payload.get("events")
    if raw_events is None:
        raw_events = payload.get("event", [])
    if not isinstance(raw_events, list):
        return []

    result: list[Event] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        event_id = item.get("id") or item.get("eventId")
        if event_id is None:
            continue

        embedded = _decode_embedded_payload(item.get("json"))
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        resolved_user_id = str(
            user_id or user.get("userId") or item.get("userId") or ""
        )
        nickname = str(
            item.get("nickname") or user.get("nickname") or "未知用户"
        ).strip()

        raw_type = item.get("type", "dynamic")
        has_song = isinstance(item.get("song"), dict) or isinstance(
            embedded.get("song"), dict
        )
        event_type = "song_share" if has_song or raw_type in (18, 19, "song_share") else "dynamic"

        summary = str(item.get("summary") or embedded.get("msg") or "").strip()
        if not summary and event_type == "song_share":
            summary = _song_summary(embedded or item)
        if not summary:
            summary = "发布了新的动态"
        summary = " ".join(summary.split())[:300]

        publish_time_ms = int(
            item.get("eventTime")
            or item.get("showTime")
            or item.get("time")
            or 0
        )
        page_url = str(
            item.get("url")
            or f"https://music.163.com/#/user/event?id={resolved_user_id}"
        )

        result.append(
            Event(
                event_id=str(event_id),
                user_id=resolved_user_id,
                nickname=nickname,
                event_type=event_type,
                summary=summary,
                publish_time_ms=publish_time_ms,
                url=page_url,
            )
        )
    return result
