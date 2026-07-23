from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _decode_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_user_snapshot(existing: Any, incoming: Any) -> dict[str, Any]:
    old_user = _decode_payload(existing)
    new_user = _decode_payload(incoming)
    old_avatar = str(old_user.get("avatar_url") or "").strip()
    if old_avatar:
        new_user["avatar_url"] = old_avatar
    return new_user


def _merge_comment_snapshot(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = dict(incoming)
    result["user"] = _merge_user_snapshot(existing.get("user"), incoming.get("user"))

    old_replies = existing.get("replies") if isinstance(existing.get("replies"), list) else []
    old_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for reply in old_replies:
        if not isinstance(reply, dict):
            continue
        user = reply.get("user") if isinstance(reply.get("user"), dict) else {}
        key = (str(user.get("user_id") or ""), str(reply.get("content") or ""))
        old_by_key[key] = reply

    merged_replies: list[dict[str, Any]] = []
    for reply in incoming.get("replies") or []:
        if not isinstance(reply, dict):
            continue
        user = reply.get("user") if isinstance(reply.get("user"), dict) else {}
        key = (str(user.get("user_id") or ""), str(reply.get("content") or ""))
        old_reply = old_by_key.get(key, {})
        merged = dict(reply)
        merged["user"] = _merge_user_snapshot(old_reply.get("user"), reply.get("user"))
        merged_replies.append(merged)
    result["replies"] = merged_replies
    return result


class InteractionStore:
    """Stores mutable interaction snapshots without touching notification state."""

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interaction_refresh_state(
                    user_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    last_attempt_at TEXT NOT NULL DEFAULT '',
                    last_success_at TEXT NOT NULL DEFAULT '',
                    next_refresh_at TEXT NOT NULL DEFAULT '',
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    comments_status TEXT NOT NULL DEFAULT 'pending',
                    likers_status TEXT NOT NULL DEFAULT 'pending',
                    comment_total INTEGER NOT NULL DEFAULT 0,
                    liker_total INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, event_id)
                )
                """
            )

    def _existing_payloads(
        self,
        conn: sqlite3.Connection,
        table: str,
        id_column: str,
        user_id: str,
        event_id: str,
    ) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            f"SELECT {id_column}, payload FROM {table} WHERE user_id=? AND event_id=?",
            (user_id, event_id),
        ).fetchall()
        return {str(identifier): _decode_payload(payload) for identifier, payload in rows}

    def replace_comments(
        self,
        user_id: str,
        event_id: str,
        comments: Iterable[dict[str, Any]],
    ) -> None:
        values = [item for item in comments if isinstance(item, dict)]
        with closing(sqlite3.connect(self.path)) as conn, conn:
            existing = self._existing_payloads(
                conn,
                "event_comments",
                "comment_id",
                user_id,
                event_id,
            )
            rows: list[tuple[str, str, str, str]] = []
            for position, item in enumerate(values):
                comment_id = str(item.get("comment_id") or "").strip()
                if not comment_id:
                    comment_id = f"synthetic-{position}-{item.get('time_ms', 0)}"
                merged = _merge_comment_snapshot(existing.get(comment_id, {}), item)
                rows.append(
                    (
                        user_id,
                        event_id,
                        comment_id,
                        json.dumps(merged, ensure_ascii=False, sort_keys=True),
                    )
                )
            conn.execute(
                "DELETE FROM event_comments WHERE user_id=? AND event_id=?",
                (user_id, event_id),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO event_comments(user_id,event_id,comment_id,payload)
                    VALUES(?,?,?,?)
                    """,
                    rows,
                )

    def replace_likers(
        self,
        user_id: str,
        event_id: str,
        likers: Iterable[dict[str, Any]],
    ) -> None:
        values = [item for item in likers if isinstance(item, dict)]
        with closing(sqlite3.connect(self.path)) as conn, conn:
            existing = self._existing_payloads(
                conn,
                "event_likers",
                "liker_id",
                user_id,
                event_id,
            )
            rows: list[tuple[str, str, str, str]] = []
            for position, item in enumerate(values):
                liker_id = str(item.get("user_id") or "").strip()
                if not liker_id:
                    liker_id = f"synthetic-{position}-{item.get('nickname', '')}"
                merged = dict(item)
                old_avatar = str(existing.get(liker_id, {}).get("avatar_url") or "").strip()
                if old_avatar:
                    merged["avatar_url"] = old_avatar
                rows.append(
                    (
                        user_id,
                        event_id,
                        liker_id,
                        json.dumps(merged, ensure_ascii=False, sort_keys=True),
                    )
                )
            conn.execute(
                "DELETE FROM event_likers WHERE user_id=? AND event_id=?",
                (user_id, event_id),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO event_likers(user_id,event_id,liker_id,payload)
                    VALUES(?,?,?,?)
                    """,
                    rows,
                )

    def record_refresh(
        self,
        user_id: str,
        event_id: str,
        *,
        next_refresh_at: str,
        comments_status: str,
        likers_status: str,
        comment_total: int,
        liker_total: int,
        error: str = "",
        success: bool,
    ) -> None:
        now = _iso_now()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            previous = conn.execute(
                """
                SELECT failure_count,last_success_at
                FROM interaction_refresh_state
                WHERE user_id=? AND event_id=?
                """,
                (user_id, event_id),
            ).fetchone()
            previous_failures = int(previous[0]) if previous else 0
            previous_success = str(previous[1]) if previous else ""
            failure_count = 0 if success else previous_failures + 1
            last_success_at = now if success else previous_success
            conn.execute(
                """
                INSERT INTO interaction_refresh_state(
                    user_id,event_id,last_attempt_at,last_success_at,next_refresh_at,
                    failure_count,comments_status,likers_status,comment_total,
                    liker_total,last_error,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(user_id,event_id) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    next_refresh_at=excluded.next_refresh_at,
                    failure_count=excluded.failure_count,
                    comments_status=excluded.comments_status,
                    likers_status=excluded.likers_status,
                    comment_total=excluded.comment_total,
                    liker_total=excluded.liker_total,
                    last_error=excluded.last_error,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    event_id,
                    now,
                    last_success_at,
                    next_refresh_at,
                    failure_count,
                    comments_status,
                    likers_status,
                    max(int(comment_total), 0),
                    max(int(liker_total), 0),
                    str(error or "")[:1000],
                ),
            )

    def state_for_event(self, user_id: str, event_id: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                """
                SELECT last_attempt_at,last_success_at,next_refresh_at,failure_count,
                       comments_status,likers_status,comment_total,liker_total,last_error
                FROM interaction_refresh_state
                WHERE user_id=? AND event_id=?
                """,
                (user_id, event_id),
            ).fetchone()
        if not row:
            return {}
        keys = (
            "last_attempt_at",
            "last_success_at",
            "next_refresh_at",
            "failure_count",
            "comments_status",
            "likers_status",
            "comment_total",
            "liker_total",
            "last_error",
        )
        return dict(zip(keys, row))

    def due_events(
        self,
        user_id: str,
        *,
        now: str,
        limit: int,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as conn:
            event_rows = conn.execute(
                "SELECT event_id,payload FROM events WHERE user_id=?",
                (user_id,),
            ).fetchall()
            state_rows = conn.execute(
                """
                SELECT event_id,next_refresh_at,last_attempt_at
                FROM interaction_refresh_state WHERE user_id=?
                """,
                (user_id,),
            ).fetchall()
        states = {
            str(event_id): {
                "next_refresh_at": str(next_refresh_at or ""),
                "last_attempt_at": str(last_attempt_at or ""),
            }
            for event_id, next_refresh_at, last_attempt_at in state_rows
        }
        candidates: list[dict[str, Any]] = []
        for event_id, raw_payload in event_rows:
            event = _decode_payload(raw_payload)
            if not event:
                continue
            state = states.get(str(event_id))
            if not force and state and state["next_refresh_at"] > now:
                continue
            event["_interaction_state"] = state or {}
            candidates.append(event)

        candidates.sort(
            key=lambda event: (
                bool(event.get("_interaction_state")),
                str(event.get("_interaction_state", {}).get("next_refresh_at") or ""),
                -int(event.get("publish_time_ms") or 0),
                str(event.get("event_id") or ""),
            )
        )
        return candidates if limit <= 0 else candidates[: max(limit, 1)]

    def due_count(self, user_id: str, *, now: str) -> int:
        return len(self.due_events(user_id, now=now, limit=0, force=False))

    def load_for_events(
        self,
        keys: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        requested = {(str(user_id), str(event_id)) for user_id, event_id in keys}
        if not requested:
            return {}
        result = {
            key: {"comments": [], "likers": [], "interaction_state": {}}
            for key in requested
        }
        with closing(sqlite3.connect(self.path)) as conn:
            for user_id, event_id in requested:
                comment_rows = conn.execute(
                    """
                    SELECT payload FROM event_comments
                    WHERE user_id=? AND event_id=? ORDER BY updated_at,comment_id
                    """,
                    (user_id, event_id),
                ).fetchall()
                liker_rows = conn.execute(
                    """
                    SELECT payload FROM event_likers
                    WHERE user_id=? AND event_id=? ORDER BY updated_at,liker_id
                    """,
                    (user_id, event_id),
                ).fetchall()
                result[(user_id, event_id)]["comments"] = [
                    decoded
                    for (payload,) in comment_rows
                    if (decoded := _decode_payload(payload))
                ]
                result[(user_id, event_id)]["likers"] = [
                    decoded
                    for (payload,) in liker_rows
                    if (decoded := _decode_payload(payload))
                ]
                result[(user_id, event_id)]["interaction_state"] = self.state_for_event(
                    user_id,
                    event_id,
                )
        return result

    def count_for_event(self, user_id: str, event_id: str) -> tuple[int, int]:
        snapshot = self.load_for_events(((user_id, event_id),)).get(
            (user_id, event_id),
            {},
        )
        return len(snapshot.get("comments") or []), len(snapshot.get("likers") or [])
