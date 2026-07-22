from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "netease_dynamic_watcher.runtime"


def runtime_paths(database_path: str | Path) -> tuple[Path, Path]:
    data_directory = Path(database_path).parent
    return data_directory / "logs" / "watcher.log", data_directory / "status.json"


def configure_logging(database_path: str | Path) -> logging.Logger:
    log_path, _ = runtime_paths(database_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


def write_runtime_status(
    database_path: str | Path,
    payload: dict[str, Any],
) -> Path:
    _, status_path = runtime_paths(database_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    temporary = status_path.with_suffix(status_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(status_path)
    return status_path


def read_runtime_status(database_path: str | Path) -> dict[str, Any]:
    _, status_path = runtime_paths(database_path)
    if not status_path.exists():
        return {}
    try:
        value = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def collect_database_summary(database_path: str | Path) -> dict[str, Any]:
    path = Path(database_path)
    summary: dict[str, Any] = {
        "exists": path.exists(),
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "event_count": 0,
        "oldest_publish_time_ms": 0,
        "newest_publish_time_ms": 0,
    }
    if not path.exists():
        return summary

    publish_times: list[int] = []
    try:
        with sqlite3.connect(path) as connection:
            rows = connection.execute("SELECT payload FROM events").fetchall()
    except sqlite3.Error as exc:
        summary["database_error"] = f"{type(exc).__name__}: {exc}"
        return summary

    summary["event_count"] = len(rows)
    for (payload,) in rows:
        try:
            event = json.loads(payload)
            publish_time = int(event.get("publish_time_ms") or 0)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            continue
        if publish_time > 0:
            publish_times.append(publish_time)
    if publish_times:
        summary["oldest_publish_time_ms"] = min(publish_times)
        summary["newest_publish_time_ms"] = max(publish_times)
    return summary


def collect_runtime_summary(database_path: str | Path) -> dict[str, Any]:
    log_path, status_path = runtime_paths(database_path)
    return {
        "database": collect_database_summary(database_path),
        "runtime": read_runtime_status(database_path),
        "log_path": str(log_path),
        "status_path": str(status_path),
    }
