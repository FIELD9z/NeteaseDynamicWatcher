from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def load_events(database: Path) -> list[dict[str, Any]]:
    if not database.exists():
        raise SystemExit(f"数据库不存在：{database}")
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(
            "SELECT payload, seen_at FROM events"
        ).fetchall()

    events: list[dict[str, Any]] = []
    for payload, seen_at in rows:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            event["_seen_at"] = seen_at
            events.append(event)
    return events


def matches_kind(event: dict[str, Any], kind: str) -> bool:
    if kind == "all":
        return True
    if kind == "image":
        return bool(event.get("image_urls"))
    if kind == "video":
        return bool(event.get("video_urls"))
    if kind == "forward":
        return bool(event.get("forwarded_event_id") or event.get("forwarded_summary"))
    if kind == "comments":
        return bool(event.get("comment_count") or event.get("comment_thread_id"))
    return False


def format_time(milliseconds: Any) -> str:
    try:
        value = int(milliseconds or 0)
    except (TypeError, ValueError):
        return "未知"
    if value <= 0:
        return "未知"
    return datetime.fromtimestamp(value / 1000).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def print_stats(events: list[dict[str, Any]]) -> None:
    event_types = Counter(str(event.get("event_type") or "unknown") for event in events)
    raw_types = Counter(str(event.get("raw_type") or "unknown") for event in events)
    raw_keys: Counter[str] = Counter()
    for event in events:
        raw_payload = event.get("raw_payload")
        if isinstance(raw_payload, dict):
            raw_keys.update(str(key) for key in raw_payload)

    print(f"动态总数：{len(events)}")
    print(f"带完整原始 JSON：{sum(bool(event.get('raw_payload')) for event in events)}")
    print(f"带图片 URL：{sum(bool(event.get('image_urls')) for event in events)}")
    print(f"带视频 URL：{sum(bool(event.get('video_urls')) for event in events)}")
    print(
        "包含转发信息："
        f"{sum(bool(event.get('forwarded_event_id') or event.get('forwarded_summary')) for event in events)}"
    )
    print(
        "包含评论计数或线程 ID："
        f"{sum(bool(event.get('comment_count') or event.get('comment_thread_id')) for event in events)}"
    )
    print("解析类型：", dict(event_types))
    print("网易云原始 type：", dict(raw_types))
    print("原始 JSON 常见顶层字段：", dict(raw_keys.most_common(30)))


def print_event(event: dict[str, Any], *, show_raw: bool) -> None:
    print("=" * 80)
    print("事件 ID：", event.get("event_id"))
    print("发布时间：", format_time(event.get("publish_time_ms")))
    print("昵称：", event.get("nickname"))
    print("解析类型：", event.get("event_type"))
    print("网易云原始 type：", event.get("raw_type"))
    print("摘要：", event.get("summary"))
    print("图片 URL：", event.get("image_urls") or [])
    print("视频 URL：", event.get("video_urls") or [])
    print("转发事件 ID：", event.get("forwarded_event_id") or "")
    print("转发摘要：", event.get("forwarded_summary") or "")
    print("评论/转发/点赞：", event.get("comment_count", 0), event.get("share_count", 0), event.get("liked_count", 0))
    print("评论线程 ID：", event.get("comment_thread_id") or "")
    print("页面链接：", event.get("url") or "")
    print("入库时间：", event.get("_seen_at") or "")
    if show_raw:
        print("原始 JSON：")
        print(json.dumps(event.get("raw_payload") or {}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="检查本地网易云动态数据库")
    parser.add_argument(
        "database",
        nargs="?",
        default="data/watcher.sqlite3",
        help="SQLite 数据库路径",
    )
    parser.add_argument(
        "--kind",
        choices=("all", "image", "video", "forward", "comments"),
        default="all",
        help="只显示特定类型的样例",
    )
    parser.add_argument("--limit", type=int, default=3, help="样例数量")
    parser.add_argument("--oldest", action="store_true", help="从最旧动态开始显示")
    parser.add_argument("--raw", action="store_true", help="打印完整原始 JSON")
    parser.add_argument("--event-id", help="只查看指定事件 ID")
    args = parser.parse_args()

    events = load_events(Path(args.database))
    print_stats(events)

    if args.event_id:
        selected = [
            event for event in events if str(event.get("event_id")) == args.event_id
        ]
    else:
        selected = [event for event in events if matches_kind(event, args.kind)]
        selected.sort(
            key=lambda event: (
                int(event.get("publish_time_ms") or 0),
                str(event.get("event_id") or ""),
            ),
            reverse=not args.oldest,
        )
        selected = selected[: max(args.limit, 0)]

    print(f"\n符合条件的样例：{len(selected)} 条")
    for event in selected:
        print_event(event, show_raw=args.raw)


if __name__ == "__main__":
    main()
