from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from netease_dynamic_watcher.archive_view import (
    load_archive_events,
    write_archive_html,
)
from netease_dynamic_watcher.runtime_state import collect_runtime_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="打开网易云动态档案页面")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output", default="data/export/events.html")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    events = load_archive_events(args.database)
    write_archive_html(
        events,
        output,
        runtime_summary=collect_runtime_summary(args.database),
    )

    print(output.resolve())
    if not args.no_browser:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
