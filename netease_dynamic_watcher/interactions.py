from __future__ import annotations

from typing import Any, Iterable


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def profile_url(user_id: str) -> str:
    value = str(user_id or "").strip()
    return f"https://music.163.com/#/user/home?id={value}" if value else ""


def normalize_user(value: Any) -> dict[str, Any]:
    user = value if isinstance(value, dict) else {}
    user_id = str(user.get("userId") or user.get("user_id") or user.get("id") or "")
    nickname = str(user.get("nickname") or user.get("name") or "未知用户").strip()
    avatar_url = str(user.get("avatarUrl") or user.get("avatar_url") or "").strip()
    if not avatar_url.startswith(("http://", "https://")):
        avatar_url = ""
    return {
        "user_id": user_id,
        "nickname": nickname or "未知用户",
        "avatar_url": avatar_url,
        "profile_url": profile_url(user_id),
    }


def _payload_sources(payload: Any) -> tuple[dict[str, Any], ...]:
    root = payload if isinstance(payload, dict) else {}
    data = root.get("data") if isinstance(root.get("data"), dict) else {}
    return root, data


def _lists(payload: Any, keys: Iterable[str]) -> list[tuple[str, list[Any]]]:
    result: list[tuple[str, list[Any]]] = []
    for source in _payload_sources(payload):
        for key in keys:
            value = source.get(key)
            if isinstance(value, list):
                result.append((key, value))
    return result


def _reply_items(value: Any) -> list[dict[str, Any]]:
    replies = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for reply in replies:
        if not isinstance(reply, dict):
            continue
        result.append(
            {
                "content": str(reply.get("content") or reply.get("beRepliedContent") or "").strip(),
                "user": normalize_user(reply.get("user")),
            }
        )
    return result


def normalize_comment(value: Any, *, hot: bool = False) -> dict[str, Any] | None:
    comment = value if isinstance(value, dict) else {}
    comment_id = str(comment.get("commentId") or comment.get("comment_id") or comment.get("id") or "")
    content = str(comment.get("content") or "").strip()
    user = normalize_user(comment.get("user"))
    if not comment_id and not content:
        return None
    return {
        "comment_id": comment_id,
        "content": content,
        "time_ms": _as_int(comment.get("time") or comment.get("time_ms")),
        "time_text": str(comment.get("timeStr") or comment.get("time_text") or "").strip(),
        "liked_count": _as_int(comment.get("likedCount") or comment.get("liked_count")),
        "hot": bool(hot),
        "user": user,
        "replies": _reply_items(comment.get("beReplied") or comment.get("replies")),
    }


def parse_comment_pages(pages: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for payload in pages:
        for key, values in _lists(payload, ("comments", "hotComments", "hot_comments")):
            is_hot = key in {"hotComments", "hot_comments"}
            for value in values:
                comment = normalize_comment(value, hot=is_hot)
                if not comment:
                    continue
                dedupe_key = comment["comment_id"] or (
                    f"{comment['user'].get('user_id', '')}:{comment['time_ms']}:{comment['content']}"
                )
                existing_position = index_by_key.get(dedupe_key)
                if existing_position is not None:
                    if is_hot:
                        result[existing_position]["hot"] = True
                    continue
                index_by_key[dedupe_key] = len(result)
                result.append(comment)
    result.sort(
        key=lambda comment: (
            not bool(comment.get("hot")),
            -_as_int(comment.get("time_ms")),
            str(comment.get("comment_id") or ""),
        )
    )
    return tuple(result)


def parse_liker_pages(pages: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in pages:
        for _, values in _lists(payload, ("likers", "users", "likedUsers", "liked_users")):
            for value in values:
                user = normalize_user(value)
                key = user["user_id"] or f"{user['nickname']}:{user['avatar_url']}"
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append(user)
    return tuple(result)


def interaction_total(payloads: Iterable[Any], *, fallback: int = 0) -> int:
    total = fallback
    for payload in payloads:
        for source in _payload_sources(payload):
            for key in ("total", "count", "likedCount", "commentCount"):
                value = _as_int(source.get(key))
                if value > total:
                    total = value
    return total
