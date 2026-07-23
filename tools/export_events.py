from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from netease_dynamic_watcher.archive_view import (  # noqa: E402
    extract_song,
    format_time,
    load_archive_events,
    write_archive_html,
)
from netease_dynamic_watcher.media_archive import archive_database_media  # noqa: E402
from netease_dynamic_watcher.runtime_state import collect_runtime_summary  # noqa: E402


def export_json(events: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def export_csv(events: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "event_id",
        "user_id",
        "nickname",
        "avatar_url",
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
        "song_name",
        "artist_name",
        "album_name",
        "raw_payload_json",
    ]
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for event in events:
            song = extract_song(event)
            writer.writerow(
                {
                    "event_id": event.get("event_id", ""),
                    "user_id": event.get("user_id", ""),
                    "nickname": event.get("nickname", ""),
                    "avatar_url": event.get("avatar_url", ""),
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
                    "song_name": song.get("name", ""),
                    "artist_name": song.get("artists", ""),
                    "album_name": song.get("album", ""),
                    "raw_payload_json": json.dumps(
                        event.get("raw_payload") or {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )


def derived_export_paths(
    database: str | Path,
    *,
    output: str | Path | None = None,
    media_dir: str | Path | None = None,
    media_manifest: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    data_directory = Path(database).resolve().parent
    resolved_output = Path(output) if output else data_directory / "export" / "events.html"
    resolved_media = Path(media_dir) if media_dir else data_directory / "media"
    resolved_manifest = (
        Path(media_manifest)
        if media_manifest
        else resolved_media / "manifest.json"
    )
    return resolved_output, resolved_media, resolved_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="导出网易云动态档案")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output")
    parser.add_argument("--media-dir")
    parser.add_argument("--media-manifest")
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="完全跳过媒体网络归档，只导出现有数据库和本地 manifest",
    )
    parser.add_argument(
        "--skip-videos",
        action="store_true",
        help="归档头像、图片和歌曲封面，但跳过视频",
    )
    args = parser.parse_args()

    output, media_dir, manifest = derived_export_paths(
        args.database,
        output=args.output,
        media_dir=args.media_dir,
        media_manifest=args.media_manifest,
    )
    if not args.skip_archive:
        archive_database_media(
            args.database,
            output_dir=media_dir,
            manifest_path=manifest,
            include_videos=not args.skip_videos,
        )

    events = load_archive_events(args.database)
    write_archive_html(
        events,
        output,
        media_manifest=manifest,
        runtime_summary=collect_runtime_summary(args.database),
    )
    export_json(events, output.with_suffix(".json"))
    export_csv(events, output.with_suffix(".csv"))

    if args.skip_archive:
        print("已跳过媒体归档；本次未发起媒体网络请求。")
    print(f"已导出 {len(events)} 条动态：{output.resolve()}")
    print(f"JSON：{output.with_suffix('.json').resolve()}")
    print(f"CSV：{output.with_suffix('.csv').resolve()}")


if __name__ == "__main__":
    main()
