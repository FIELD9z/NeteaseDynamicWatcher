from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from netease_dynamic_watcher.archive_view import (
    load_archive_events,
    write_archive_html,
)
from netease_dynamic_watcher.runtime_state import collect_runtime_summary


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
        "event_type",
        "publish_time_ms",
        "summary",
        "source_url",
        "song_name",
        "artist_name",
        "album_name",
        "image_count",
    ]
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            writer.writerow(event)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output", default="data/export/events.html")
    args = parser.parse_args()

    events = load_archive_events(args.database)
    output = Path(args.output)
    write_archive_html(
        events,
        output,
        runtime_summary=collect_runtime_summary(args.database),
    )
    export_json(events, output.with_suffix(".json"))
    export_csv(events, output.with_suffix(".csv"))
    print(f"Exported {len(events)} events to {output}")


if __name__ == "__main__":
    main()
