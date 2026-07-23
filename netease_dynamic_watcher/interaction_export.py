from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from netease_dynamic_watcher.media_archive import canonical_media_url


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _avatar_map(
    manifest_path: str | Path,
    output_html: Path,
) -> dict[tuple[str, str], str]:
    path = Path(manifest_path)
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = document.get("items") if isinstance(document, dict) else []
    result: dict[tuple[str, str], str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "interaction_avatar":
            continue
        if item.get("status") not in {"downloaded", "existing", "deduplicated"}:
            continue
        event_id = str(item.get("event_id") or "")
        source_url = str(item.get("source_url") or "")
        canonical = str(item.get("canonical_url") or "")
        canonical = canonical or canonical_media_url(source_url, "avatar")
        local_path = str(item.get("local_path") or "")
        absolute = path.parent / local_path
        if event_id and canonical and local_path and absolute.exists():
            result[(event_id, canonical)] = os.path.relpath(
                absolute,
                output_html.parent,
            ).replace(os.sep, "/")
    return result


def _attach_local_avatar(
    user: Any,
    *,
    event_id: str,
    avatars: dict[tuple[str, str], str],
) -> dict[str, Any]:
    value = _decode(user)
    source_url = str(value.get("avatar_url") or "")
    canonical = canonical_media_url(source_url, "avatar")
    value["avatar_local"] = avatars.get((event_id, canonical), "") if canonical else ""
    return value


def load_interaction_snapshot(
    database: str | Path,
    *,
    media_manifest: str | Path,
    output_html: str | Path,
) -> dict[str, Any]:
    database_path = Path(database)
    output_path = Path(output_html)
    if not database_path.exists():
        return {}
    avatars = _avatar_map(media_manifest, output_path)
    result: dict[str, Any] = {}
    with closing(sqlite3.connect(database_path)) as connection:
        if not _table_exists(connection, "events"):
            return {}
        keys = connection.execute("SELECT user_id,event_id FROM events").fetchall()
        has_comments = _table_exists(connection, "event_comments")
        has_likers = _table_exists(connection, "event_likers")
        has_state = _table_exists(connection, "interaction_refresh_state")
        for raw_user_id, raw_event_id in keys:
            user_id = str(raw_user_id)
            event_id = str(raw_event_id)
            comments: list[dict[str, Any]] = []
            likers: list[dict[str, Any]] = []
            state: dict[str, Any] = {}
            if has_comments:
                rows = connection.execute(
                    """
                    SELECT payload FROM event_comments
                    WHERE user_id=? AND event_id=? ORDER BY updated_at,comment_id
                    """,
                    (user_id, event_id),
                ).fetchall()
                for (payload,) in rows:
                    comment = _decode(payload)
                    if not comment:
                        continue
                    comment["user"] = _attach_local_avatar(
                        comment.get("user"),
                        event_id=event_id,
                        avatars=avatars,
                    )
                    replies = []
                    for reply in comment.get("replies") or []:
                        if not isinstance(reply, dict):
                            continue
                        value = dict(reply)
                        value["user"] = _attach_local_avatar(
                            value.get("user"),
                            event_id=event_id,
                            avatars=avatars,
                        )
                        replies.append(value)
                    comment["replies"] = replies
                    comments.append(comment)
            if has_likers:
                rows = connection.execute(
                    """
                    SELECT payload FROM event_likers
                    WHERE user_id=? AND event_id=? ORDER BY updated_at,liker_id
                    """,
                    (user_id, event_id),
                ).fetchall()
                for (payload,) in rows:
                    liker = _decode(payload)
                    if liker:
                        likers.append(
                            _attach_local_avatar(
                                liker,
                                event_id=event_id,
                                avatars=avatars,
                            )
                        )
            if has_state:
                row = connection.execute(
                    """
                    SELECT last_attempt_at,last_success_at,next_refresh_at,failure_count,
                           comments_status,likers_status,comment_total,liker_total,last_error
                    FROM interaction_refresh_state
                    WHERE user_id=? AND event_id=?
                    """,
                    (user_id, event_id),
                ).fetchone()
                if row:
                    names = (
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
                    state = dict(zip(names, row))
            if comments or likers or state:
                result[event_id] = {
                    "comments": comments,
                    "likers": likers,
                    "state": state,
                }
    return result


def write_interaction_assets(
    database: str | Path,
    output_html: str | Path,
    *,
    media_manifest: str | Path,
) -> Path:
    output_path = Path(output_html)
    assets = output_path.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    source_directory = Path(__file__).resolve().parent.parent / "web"
    for name in ("interaction-ui.js", "interaction-ui.css"):
        source = source_directory / name
        if not source.exists():
            raise FileNotFoundError(f"缺少互动 UI 资源：{source}")
        shutil.copyfile(source, assets / name)

    snapshot = load_interaction_snapshot(
        database,
        media_manifest=media_manifest,
        output_html=output_path,
    )
    destination = assets / "interactions-data.js"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    temporary.write_text(
        "window.__NETEASE_INTERACTIONS__=" + payload + ";\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
