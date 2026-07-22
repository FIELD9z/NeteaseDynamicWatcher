from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from netease_dynamic_watcher.archive_view import (
    load_archive_events,
    load_media_manifest,
    write_archive_html,
)


def export_json(events: list[dict[str, Any]], output: Path) -> None:
    output.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def export_csv(events: list[dict[str, Any]], output: Path) -> None:
    import csv

    columns = [
        "event_id", "nickname", "event_type", "publish_time_ms",
        "summary", "url", "raw_payload_json"
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for event in events:
            writer.writerow({
                "event_id": event.get("event_id", ""),
                "nickname": event.get("nickname", ""),
                "event_type": event.get("event_type", ""),
                "publish_time_ms": event.get("publish_time_ms", ""),
                "summary": event.get("summary", ""),
                "url": event.get("url", ""),
                "raw_payload_json": json.dumps(
                    event.get("raw_payload") or {},
                    ensure_ascii=False,
                ),
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="导出网易云动态档案")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output-dir", default="data/export")
    parser.add_argument("--media-manifest", default="data/media/manifest.json")
    parser.add_argument("--format", choices=("all", "html", "json", "csv"), default="all")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events = load_archive_events(args.database)
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
        write_archive_html(
            events,
            path,
            media_manifest=args.media_manifest,
        )
        written.append(path)

    print(f"已导出 {len(events)} 条动态：")
    for path in written:
        print(path.resolve())


if __name__ == "__main__":
    main()
