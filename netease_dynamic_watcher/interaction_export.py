from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


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


def _public_user(value: Any) -> dict[str, Any]:
    user = _decode(value)
    return {
        "user_id": str(user.get("user_id") or ""),
        "nickname": str(user.get("nickname") or "未知用户"),
        "profile_url": str(user.get("profile_url") or ""),
    }


def load_interaction_snapshot(database: str | Path) -> dict[str, Any]:
    database_path = Path(database)
    if not database_path.exists():
        return {}
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
                    replies: list[dict[str, Any]] = []
                    for reply in comment.get("replies") or []:
                        if not isinstance(reply, dict):
                            continue
                        replies.append(
                            {
                                "content": str(reply.get("content") or ""),
                                "user": _public_user(reply.get("user")),
                            }
                        )
                    comments.append(
                        {
                            "comment_id": str(comment.get("comment_id") or ""),
                            "content": str(comment.get("content") or ""),
                            "time_ms": int(comment.get("time_ms") or 0),
                            "time_text": str(comment.get("time_text") or ""),
                            "liked_count": int(comment.get("liked_count") or 0),
                            "hot": bool(comment.get("hot")),
                            "user": _public_user(comment.get("user")),
                            "replies": replies,
                        }
                    )
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
                        likers.append(_public_user(liker))
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


def _inject_assets(output_path: Path) -> None:
    html = output_path.read_text(encoding="utf-8")
    stylesheet = '<link rel="stylesheet" href="assets/interaction-ui.css">'
    data_script = '<script src="assets/interactions-data.js"></script>'
    ui_script = '<script src="assets/interaction-ui.js"></script>'
    if stylesheet not in html:
        html = html.replace("</head>", f"  {stylesheet}\n</head>")
    if data_script not in html:
        html = html.replace(
            '<script src="assets/archive.js"></script>',
            '<script src="assets/interactions-data.js"></script>\n'
            '<script src="assets/archive.js"></script>\n'
            '<script src="assets/interaction-ui.js"></script>',
        )
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output_path)


def write_interaction_assets(
    database: str | Path,
    output_html: str | Path,
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

    snapshot = load_interaction_snapshot(database)
    destination = assets / "interactions-data.js"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    temporary.write_text(
        "window.__NETEASE_INTERACTIONS__=" + payload + ";\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    _inject_assets(output_path)
    return destination
