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
from netease_dynamic_watcher.media_archive import archive_database_media  # noqa: E402
from netease_dynamic_watcher.runtime_state import collect_runtime_summary  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="打开网易云动态档案页面")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output", default="data/export/events.html")
    parser.add_argument("--media-manifest", default="data/media/manifest.json")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    events = load_archive_events(args.database)
    archive_database_media(
        args.database,
        output_dir="data/media",
        manifest_path=args.media_manifest,
        include_videos=True,
    )
    write_archive_html(
        events,
        output,
        media_manifest=args.media_manifest,
        runtime_summary=collect_runtime_summary(args.database),
    )

    print(f"已生成 {len(events)} 条动态的本地档案：{output.resolve()}")
    if not args.no_browser:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
