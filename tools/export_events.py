from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def load_events(database: Path) -> list[dict[str, Any]]:
    if not database.exists():
        raise SystemExit(f"数据库不存在：{database}")
    with sqlite3.connect(database) as connection:
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
            event["seen_at"] = seen_at
            events.append(event)
    events.sort(
        key=lambda event: (
            int(event.get("publish_time_ms") or 0),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    return events


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


def load_media_manifest(path: Path) -> dict[tuple[str, str], Path]:
    if not path.exists():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    result: dict[tuple[str, str], Path] = {}
    items = manifest.get("items", []) if isinstance(manifest, dict) else []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in {"downloaded", "existing"}:
            continue
        event_id = str(item.get("event_id") or "")
        source_url = str(item.get("source_url") or "")
        local_path = str(item.get("local_path") or "")
        if event_id and source_url and local_path:
            result[(event_id, source_url)] = path.parent / local_path
    return result


def export_json(events: list[dict[str, Any]], output: Path) -> None:
    output.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def export_csv(events: list[dict[str, Any]], output: Path) -> None:
    columns = [
        "event_id",
        "user_id",
        "nickname",
        "event_type",
        "raw_type",
        "published_at",
        "summary",
        "image_urls",
        "video_urls",
        "forwarded_event_id",
        "forwarded_summary",
        "comment_count",
        "share_count",
        "liked_count",
        "comment_thread_id",
        "url",
        "seen_at",
        "raw_payload_json",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "event_id": event.get("event_id", ""),
                    "user_id": event.get("user_id", ""),
                    "nickname": event.get("nickname", ""),
                    "event_type": event.get("event_type", ""),
                    "raw_type": event.get("raw_type", ""),
                    "published_at": format_time(event.get("publish_time_ms")),
                    "summary": event.get("summary", ""),
                    "image_urls": "\n".join(event.get("image_urls") or []),
                    "video_urls": "\n".join(event.get("video_urls") or []),
                    "forwarded_event_id": event.get("forwarded_event_id", ""),
                    "forwarded_summary": event.get("forwarded_summary", ""),
                    "comment_count": event.get("comment_count", 0),
                    "share_count": event.get("share_count", 0),
                    "liked_count": event.get("liked_count", 0),
                    "comment_thread_id": event.get("comment_thread_id", ""),
                    "url": event.get("url", ""),
                    "seen_at": event.get("seen_at", ""),
                    "raw_payload_json": json.dumps(
                        event.get("raw_payload") or {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )


def _safe(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def export_html(
    events: list[dict[str, Any]],
    output: Path,
    media_map: dict[tuple[str, str], Path],
) -> None:
    type_counts = Counter(str(event.get("event_type") or "unknown") for event in events)
    cards: list[str] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        summary = _safe(event.get("summary"))
        forward = _safe(event.get("forwarded_summary"))
        images: list[str] = []
        for source_url in event.get("image_urls") or []:
            source_url = str(source_url)
            local = media_map.get((event_id, source_url))
            if local and local.exists():
                image_src = os.path.relpath(local, output.parent).replace(os.sep, "/")
            else:
                image_src = source_url
            images.append(
                f'<a href="{_safe(image_src)}" target="_blank" rel="noreferrer">'
                f'<img src="{_safe(image_src)}" loading="lazy" alt="动态图片"></a>'
            )

        raw_payload = json.dumps(
            event.get("raw_payload") or {},
            ensure_ascii=False,
            indent=2,
        )
        searchable = " ".join(
            str(event.get(key) or "")
            for key in ("nickname", "event_type", "raw_type", "summary", "forwarded_summary")
        ).lower()
        cards.append(
            f"""
<article class="card" data-search="{_safe(searchable)}">
  <div class="meta">
    <span>{_safe(format_time(event.get('publish_time_ms')))}</span>
    <span>{_safe(event.get('nickname'))}</span>
    <span class="tag">{_safe(event.get('event_type'))}</span>
    <span>原始 type: {_safe(event.get('raw_type'))}</span>
  </div>
  <p class="summary">{summary}</p>
  {f'<blockquote>转发：{forward}</blockquote>' if forward else ''}
  <div class="gallery">{''.join(images)}</div>
  <div class="counts">评论 {_safe(event.get('comment_count', 0))} · 转发 {_safe(event.get('share_count', 0))} · 点赞 {_safe(event.get('liked_count', 0))}</div>
  <div class="links"><a href="{_safe(event.get('url'))}" target="_blank" rel="noreferrer">打开网易云页面</a> · 事件 ID {_safe(event_id)}</div>
  <details><summary>完整原始 JSON</summary><pre>{_safe(raw_payload)}</pre></details>
</article>
"""
        )

    stats = " · ".join(f"{_safe(key)} {_safe(value)}" for key, value in type_counts.items())
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>网易云动态档案</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ max-width: 1000px; margin: 0 auto; padding: 24px; line-height: 1.6; }}
header {{ position: sticky; top: 0; padding: 12px 0; backdrop-filter: blur(12px); z-index: 2; }}
input {{ width: 100%; box-sizing: border-box; padding: 12px; font-size: 16px; }}
.card {{ border: 1px solid #8885; border-radius: 14px; padding: 18px; margin: 18px 0; }}
.meta, .counts, .links {{ display: flex; gap: 12px; flex-wrap: wrap; opacity: .78; font-size: 14px; }}
.tag {{ font-weight: 700; }}
.summary {{ white-space: pre-wrap; font-size: 17px; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
.gallery img {{ width: 100%; max-height: 420px; object-fit: contain; border-radius: 10px; background: #0001; }}
blockquote {{ border-left: 4px solid #8888; margin-left: 0; padding-left: 12px; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; max-height: 600px; overflow: auto; }}
</style>
</head>
<body>
<header>
  <h1>网易云动态档案</h1>
  <p>共 {_safe(len(events))} 条 · {stats}</p>
  <input id="search" type="search" placeholder="搜索昵称、类型、正文或转发内容">
</header>
<main>{''.join(cards)}</main>
<script>
const input = document.getElementById('search');
input.addEventListener('input', () => {{
  const q = input.value.trim().toLowerCase();
  document.querySelectorAll('.card').forEach(card => {{
    card.hidden = q && !card.dataset.search.includes(q);
  }});
}});
</script>
</body>
</html>
"""
    output.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出网易云动态档案")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output-dir", default="data/export")
    parser.add_argument(
        "--format",
        choices=("all", "html", "json", "csv"),
        default="all",
    )
    parser.add_argument("--media-manifest", default="data/media/manifest.json")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events = load_events(Path(args.database))
    media_map = load_media_manifest(Path(args.media_manifest))

    written: list[Path] = []
    if args.format in {"all", "json"}:
        path = output_dir / "events.json"
        export_json(events, path)
        written.append(path)
    if args.format in {"all", "csv"}:
        path = output_dir / "events.csv"
        export_csv(events, path)
        written.append(path)
    if args.format in {"all", "html"}:
        path = output_dir / "events.html"
        export_html(events, path, media_map)
        written.append(path)

    print(f"已导出 {len(events)} 条动态：")
    for path in written:
        print(path.resolve())


if __name__ == "__main__":
    main()
