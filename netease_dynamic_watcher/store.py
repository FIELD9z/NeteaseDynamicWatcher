from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from netease_dynamic_watcher.models import Event


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events(
                    user_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, event_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def is_initialized(self, user_id: str) -> bool:
        return self.get_metadata(f"initialized:{user_id}") == "1"

    def mark_initialized(self, user_id: str) -> None:
        self.set_metadata(f"initialized:{user_id}", "1")

    def is_seen(self, user_id: str, event_id: str) -> bool:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT 1 FROM events WHERE user_id=? AND event_id=?",
                (user_id, event_id),
            ).fetchone()
        return row is not None

    @staticmethod
    def _serialize(event: Event) -> str:
        return json.dumps(
            {
                "event_id": event.event_id,
                "user_id": event.user_id,
                "nickname": event.nickname,
                "event_type": event.event_type,
                "summary": event.summary,
                "publish_time_ms": event.publish_time_ms,
                "url": event.url,
                "raw_type": event.raw_type,
                "image_urls": list(event.image_urls),
                "video_urls": list(event.video_urls),
                "forwarded_event_id": event.forwarded_event_id,
                "forwarded_summary": event.forwarded_summary,
                "comment_count": event.comment_count,
                "share_count": event.share_count,
                "liked_count": event.liked_count,
                "comment_thread_id": event.comment_thread_id,
                "raw_payload": event.raw_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def save(self, event: Event) -> None:
        payload = self._serialize(event)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO events(user_id, event_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, event_id)
                DO UPDATE SET payload=excluded.payload
                """,
                (event.user_id, event.event_id, payload),
            )

    def save_many(self, events: Iterable[Event]) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT INTO events(user_id, event_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, event_id)
                DO UPDATE SET payload=excluded.payload
                """,
                [
                    (
                        event.user_id,
                        event.event_id,
                        self._serialize(event),
                    )
                    for event in events
                ],
            )

    def get_metadata(self, key: str) -> str | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key=?", (key,)
            ).fetchone()
        return None if row is None else str(row[0])

    def set_metadata(self, key: str, value: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
