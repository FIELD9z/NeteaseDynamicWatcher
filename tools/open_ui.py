from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from netease_dynamic_watcher.archive_view import (  # noqa: E402
    load_archive_events,
    write_archive_html,
)
from netease_dynamic_watcher.interaction_export import write_interaction_assets  # noqa: E402
from netease_dynamic_watcher.media_archive import archive_database_media  # noqa: E402
from netease_dynamic_watcher.runtime_state import collect_runtime_summary  # noqa: E402


def derived_paths(
    database: str | Path,
    *,
    output: str | None = None,
    media_dir: str | None = None,
    media_manifest: str | None = None,
) -> tuple[Path, Path, Path]:
    data_directory = Path(database).resolve().parent
    resolved_media_dir = Path(media_dir) if media_dir else data_directory / "media"
    resolved_manifest = (
        Path(media_manifest)
        if media_manifest
        else resolved_media_dir / "manifest.json"
    )
    resolved_output = (
        Path(output)
        if output
        else data_directory / "export" / "events.html"
    )
    return resolved_output, resolved_media_dir, resolved_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="打开网易云动态档案页面")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output")
    parser.add_argument("--media-dir")
    parser.add_argument("--media-manifest")
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="完全跳过媒体网络归档，只使用当前数据库和本地 manifest 生成页面",
    )
    parser.add_argument(
        "--skip-videos",
        action="store_true",
        help="归档头像、图片和歌曲封面，但跳过视频",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    output, media_dir, media_manifest = derived_paths(
        args.database,
        output=args.output,
        media_dir=args.media_dir,
        media_manifest=args.media_manifest,
    )

    media_report: dict[str, int] | None = None
    if not args.skip_archive:
        media_report = archive_database_media(
            args.database,
            output_dir=media_dir,
            manifest_path=media_manifest,
            include_videos=not args.skip_videos,
        )

    events = load_archive_events(args.database)
    write_archive_html(
        events,
        output,
        media_manifest=media_manifest,
        runtime_summary=collect_runtime_summary(args.database),
    )
    write_interaction_assets(args.database, output)

    if media_report is not None:
        print("媒体归档结果：", media_report)
    else:
        print("已跳过媒体归档；本次未发起媒体网络请求。")
    print(f"已生成 {len(events)} 条动态的本地档案：{output.resolve()}")
    if not args.no_browser:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
