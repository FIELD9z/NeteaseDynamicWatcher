from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable


class InteractionStore:
    """Stores mutable interaction snapshots separately from event notification state.

    Interaction refreshes must never affect whether an event is considered new.
    """

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_comments(
                    user_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, event_id, comment_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_likers(
                    user_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    liker_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, event_id, liker_id)
                )
                """
            )

    def save_comments(
        self,
        user_id: str,
        event_id: str,
        comments: Iterable[dict[str, Any]],
    ) -> None:
        rows = [
            (user_id, event_id, str(item.get("comment_id") or ""), json.dumps(item, ensure_ascii=False))
            for item in comments
            if isinstance(item, dict) and str(item.get("comment_id") or "")
        ]
        if not rows:
            return
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executemany(
                """
                INSERT INTO event_comments(user_id,event_id,comment_id,payload)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id,event_id,comment_id)
                DO UPDATE SET payload=excluded.payload,
                              updated_at=CURRENT_TIMESTAMP
                """,
                rows,
            )

    def save_likers(
        self,
        user_id: str,
        event_id: str,
        likers: Iterable[dict[str, Any]],
    ) -> None:
        rows = [
            (user_id, event_id, str(item.get("user_id") or ""), json.dumps(item, ensure_ascii=False))
            for item in likers
            if isinstance(item, dict) and str(item.get("user_id") or "")
        ]
        if not rows:
            return
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executemany(
                """
                INSERT INTO event_likers(user_id,event_id,liker_id,payload)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id,event_id,liker_id)
                DO UPDATE SET payload=excluded.payload,
                              updated_at=CURRENT_TIMESTAMP
                """,
                rows,
            )

    def count_for_event(self, user_id: str, event_id: str) -> tuple[int, int]:
        with closing(sqlite3.connect(self.path)) as conn:
            comments = conn.execute(
                "SELECT COUNT(*) FROM event_comments WHERE user_id=? AND event_id=?",
                (user_id, event_id),
            ).fetchone()[0]
            likers = conn.execute(
                "SELECT COUNT(*) FROM event_likers WHERE user_id=? AND event_id=?",
                (user_id, event_id),
            ).fetchone()[0]
        return int(comments), int(likers)
