from __future__ import annotations

import json
from typing import Any, Iterable

from netease_dynamic_watcher.models import Event


_IMAGE_CONTAINER_KEYS = ("pics", "images", "pictures")
_VIDEO_CONTAINER_KEYS = ("video", "videoInfo", "videoUrl", "mv")
_IMAGE_URL_KEYS = {
    "url",
    "originurl",
    "squareurl",
    "pcsquareurl",
    "rectangleurl",
    "picurl",
    "imageurl",
}
_VIDEO_URL_KEYS = {
    "url",
    "playurl",
    "downloadurl",
    "mp4url",
    "videourl",
}


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


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _collect_urls(value: Any, allowed_keys: set[str]) -> tuple[str, ...]:
    result: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                normalized_key = str(key).replace("_", "").lower()
                if (
                    isinstance(child, str)
                    and child.startswith(("http://", "https://"))
                    and normalized_key in allowed_keys
                ):
                    result.append(child)
                else:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return tuple(dict.fromkeys(result))


def _extract_urls_from_containers(
    sources: Iterable[dict[str, Any]],
    container_keys: Iterable[str],
    allowed_keys: set[str],
) -> tuple[str, ...]:
    urls: list[str] = []
    for source in sources:
        for key in container_keys:
            if key in source:
                urls.extend(_collect_urls(source[key], allowed_keys))
    return tuple(dict.fromkeys(urls))


def _find_forward_payload(
    item: dict[str, Any], embedded: dict[str, Any]
) -> dict[str, Any]:
    candidates = (
        item.get("insiteForward"),
        item.get("forward"),
        item.get("forwardEvent"),
        embedded.get("event"),
        embedded.get("forward"),
    )
    for candidate in candidates:
        decoded = _decode_embedded_payload(candidate)
        if decoded:
            return decoded
    return {}


def _forward_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    embedded = _decode_embedded_payload(payload.get("json"))
    for value in (
        payload.get("msg"),
        payload.get("summary"),
        payload.get("title"),
        embedded.get("msg"),
        _song_summary(embedded),
        _song_summary(payload),
    ):
        text = str(value or "").strip()
        if text:
            return " ".join(text.split())[:300]
    return ""


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

        image_urls = _extract_urls_from_containers(
            (item, embedded),
            _IMAGE_CONTAINER_KEYS,
            _IMAGE_URL_KEYS,
        )
        video_urls = _extract_urls_from_containers(
            (item, embedded),
            _VIDEO_CONTAINER_KEYS,
            _VIDEO_URL_KEYS,
        )
        forward_payload = _find_forward_payload(item, embedded)
        forwarded_event_id = str(
            forward_payload.get("id")
            or forward_payload.get("eventId")
            or forward_payload.get("resourceId")
            or forward_payload.get("uuid")
            or ""
        )
        forwarded_summary = _forward_summary(forward_payload)

        raw_type_value = item.get("type", "dynamic")
        raw_type = str(raw_type_value)
        has_song = isinstance(item.get("song"), dict) or isinstance(
            embedded.get("song"), dict
        )
        if has_song or raw_type_value in (18, 19, "song_share"):
            event_type = "song_share"
        elif forward_payload:
            event_type = "forward"
        elif video_urls:
            event_type = "video"
        elif image_urls:
            event_type = "image"
        else:
            event_type = "dynamic"

        summary = str(item.get("summary") or embedded.get("msg") or "").strip()
        if not summary and event_type == "song_share":
            summary = _song_summary(embedded) or _song_summary(item)
        if not summary and event_type == "forward":
            summary = forwarded_summary or "转发了一条动态"
        if not summary:
            summary = "发布了新的动态"
        summary = " ".join(summary.split())[:300]

        publish_time_ms = _as_int(
            item.get("eventTime")
            or item.get("showTime")
            or item.get("time")
        )
        page_url = str(
            item.get("url")
            or f"https://music.163.com/#/user/event?id={resolved_user_id}"
        )

        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        comment_count = _as_int(info.get("commentCount") or item.get("commentCount"))
        share_count = _as_int(info.get("shareCount") or item.get("shareCount"))
        liked_count = _as_int(info.get("likedCount") or item.get("likedCount"))
        comment_thread_id = str(
            info.get("threadId") or item.get("threadId") or ""
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
                raw_type=raw_type,
                image_urls=image_urls,
                video_urls=video_urls,
                forwarded_event_id=forwarded_event_id,
                forwarded_summary=forwarded_summary,
                comment_count=comment_count,
                share_count=share_count,
                liked_count=liked_count,
                comment_thread_id=comment_thread_id,
                raw_payload=item,
            )
        )
    return result
