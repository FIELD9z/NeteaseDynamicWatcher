from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from netease_dynamic_watcher.archive_view import (
    format_time,
    load_archive_events,
    write_archive_html,
)
from netease_dynamic_watcher.runtime_state import collect_runtime_summary


def export_json(events: list[dict[str, Any]], output: Path) -> None:
