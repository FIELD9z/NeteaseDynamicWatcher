from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from netease_dynamic_watcher.models import Event


_NOTIFICATION_STATES = {"pending", "delivered", "suppressed"}


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_state(
                    user_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, event_id),
                    FOREIGN KEY(user_id, event_id)
                        REFERENCES events(user_id, event_id)
                        ON DELETE CASCADE
                )
                """
            )
            # Existing databases predate delivery tracking. Treat their rows as
            # historical baseline so an upgrade never sends hundreds of old alerts.
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_state(user_id, event_id, state)
                SELECT user_id, event_id, 'suppressed' FROM events
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
    def _serialize(event: Event, *, avatar_url: str | None = None) -> str:
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
                "avatar_url": event.avatar_url if avatar_url is None else avatar_url,
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

    @staticmethod
    def _deserialize(payload: str) -> Event:
        value = json.loads(payload)
        return Event(
            event_id=str(value.get("event_id") or ""),
            user_id=str(value.get("user_id") or ""),
            nickname=str(value.get("nickname") or "未知用户"),
            event_type=str(value.get("event_type") or "dynamic"),
            summary=str(value.get("summary") or "发布了新的动态"),
            publish_time_ms=int(value.get("publish_time_ms") or 0),
            url=str(value.get("url") or ""),
            raw_type=str(value.get("raw_type") or ""),
            avatar_url=str(value.get("avatar_url") or ""),
            image_urls=tuple(value.get("image_urls") or ()),
            video_urls=tuple(value.get("video_urls") or ()),
            forwarded_event_id=str(value.get("forwarded_event_id") or ""),
            forwarded_summary=str(value.get("forwarded_summary") or ""),
            comment_count=int(value.get("comment_count") or 0),
            share_count=int(value.get("share_count") or 0),
            liked_count=int(value.get("liked_count") or 0),
            comment_thread_id=str(value.get("comment_thread_id") or ""),
            raw_payload=(
                value.get("raw_payload")
                if isinstance(value.get("raw_payload"), dict)
                else {}
            ),
        )

    @staticmethod
    def _validate_notification_state(state: str | None) -> None:
        if state is not None and state not in _NOTIFICATION_STATES:
            raise ValueError(f"Unsupported notification state: {state}")

    def _payload_for_save(self, conn: sqlite3.Connection, event: Event) -> str:
        """Keep the avatar captured when this event was first archived.

        Old rows without an avatar may be enriched once. After a non-empty avatar
        has been stored, later backfills cannot replace it with the user's current
        avatar.
        """

        row = conn.execute(
            "SELECT payload FROM events WHERE user_id=? AND event_id=?",
            (event.user_id, event.event_id),
        ).fetchone()
        existing_avatar = ""
        if row:
            try:
                existing = json.loads(str(row[0]))
            except json.JSONDecodeError:
                existing = {}
            if isinstance(existing, dict):
                existing_avatar = str(existing.get("avatar_url") or "").strip()
        return self._serialize(
            event,
            avatar_url=existing_avatar or event.avatar_url,
        )

    def save(self, event: Event, *, notification_state: str | None = None) -> None:
        self._validate_notification_state(notification_state)
        with sqlite3.connect(self.path) as conn:
            payload = self._payload_for_save(conn, event)
            conn.execute(
                """
                INSERT INTO events(user_id, event_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, event_id)
                DO UPDATE SET payload=excluded.payload
                """,
                (event.user_id, event.event_id, payload),
            )
            if notification_state is not None:
                conn.execute(
                    """
                    INSERT INTO notification_state(user_id, event_id, state, last_error)
                    VALUES (?, ?, ?, '')
                    ON CONFLICT(user_id, event_id) DO NOTHING
                    """,
                    (event.user_id, event.event_id, notification_state),
                )

    def save_many(
        self,
        events: Iterable[Event],
        *,
        notification_state: str | None = None,
    ) -> None:
        self._validate_notification_state(notification_state)
        values = list(events)
        if not values:
            return
        with sqlite3.connect(self.path) as conn:
            rows = [
                (
                    event.user_id,
                    event.event_id,
                    self._payload_for_save(conn, event),
                )
                for event in values
            ]
            conn.executemany(
                """
                INSERT INTO events(user_id, event_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, event_id)
                DO UPDATE SET payload=excluded.payload
                """,
                rows,
            )
            if notification_state is not None:
                conn.executemany(
                    """
                    INSERT INTO notification_state(user_id, event_id, state, last_error)
                    VALUES (?, ?, ?, '')
                    ON CONFLICT(user_id, event_id) DO NOTHING
                    """,
                    [
                        (event.user_id, event.event_id, notification_state)
                        for event in values
                    ],
                )

    def get_pending_events(self, user_id: str, *, limit: int = 100) -> list[Event]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT events.payload
                FROM notification_state
                JOIN events USING(user_id, event_id)
                WHERE notification_state.user_id=?
                  AND notification_state.state='pending'
                ORDER BY events.seen_at, events.event_id
                LIMIT ?
                """,
                (user_id, max(limit, 1)),
            ).fetchall()
        events = [self._deserialize(str(row[0])) for row in rows]
        events.sort(key=lambda event: (event.publish_time_ms, event.event_id))
        return events

    def pending_notification_count(self, user_id: str) -> int:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM notification_state
                WHERE user_id=? AND state='pending'
                """,
                (user_id,),
            ).fetchone()
        return int(row[0] if row else 0)

    def get_notification_state(self, user_id: str, event_id: str) -> str | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT state FROM notification_state
                WHERE user_id=? AND event_id=?
                """,
                (user_id, event_id),
            ).fetchone()
        return None if row is None else str(row[0])

    def mark_notification_delivered(self, user_id: str, event_id: str) -> None:
        self._set_notification_result(user_id, event_id, "delivered", "")

    def mark_notification_failed(
        self,
        user_id: str,
        event_id: str,
        error: str,
    ) -> None:
        self._set_notification_result(user_id, event_id, "pending", error[:500])

    def _set_notification_result(
        self,
        user_id: str,
        event_id: str,
        state: str,
        error: str,
    ) -> None:
        self._validate_notification_state(state)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                UPDATE notification_state
                SET state=?, last_error=?, updated_at=CURRENT_TIMESTAMP
                WHERE user_id=? AND event_id=?
                """,
                (state, error, user_id, event_id),
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
