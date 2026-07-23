from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from typing import Any, Iterable
import urllib.error
import urllib.request

from netease_dynamic_watcher.media_archive import (
    DEFAULT_ALLOWED_HOST_SUFFIXES,
    DEFAULT_MAX_IMAGE_BYTES,
    SafeRedirectHandler,
    _content_index,
    canonical_media_url,
    download_one,
    load_manifest,
    manifest_index,
    sanitize_component,
    save_manifest,
    validate_download_target,
    validate_url_syntax,
)


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _iter_users(value: Any) -> Iterable[dict[str, Any]]:
    item = _decode(value)
    user = _decode(item.get("user"))
    if user:
        yield user
    for reply in item.get("replies") or []:
        if isinstance(reply, dict):
            reply_user = _decode(reply.get("user"))
            if reply_user:
                yield reply_user


def interaction_avatar_candidates(database: str | Path) -> list[tuple[str, str, str]]:
    path = Path(database)
    if not path.exists():
        return []
    candidates: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    with closing(sqlite3.connect(path)) as connection:
        if _table_exists(connection, "event_comments"):
            for event_id, payload in connection.execute(
                "SELECT event_id,payload FROM event_comments"
            ).fetchall():
                for user in _iter_users(payload):
                    source = str(user.get("avatar_url") or "").strip()
                    canonical = canonical_media_url(source, "avatar")
                    key = (str(event_id), canonical)
                    if source and canonical and key not in seen:
                        seen.add(key)
                        candidates.append((str(event_id), source, canonical))
        if _table_exists(connection, "event_likers"):
            for event_id, payload in connection.execute(
                "SELECT event_id,payload FROM event_likers"
            ).fetchall():
                user = _decode(payload)
                source = str(user.get("avatar_url") or "").strip()
                canonical = canonical_media_url(source, "avatar")
                key = (str(event_id), canonical)
                if source and canonical and key not in seen:
                    seen.add(key)
                    candidates.append((str(event_id), source, canonical))
    return candidates


def archive_interaction_avatars(
    database: str | Path,
    *,
    output_dir: str | Path,
    manifest_path: str | Path,
    timeout: int = 20,
    max_items: int = 0,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    allowed_suffixes: tuple[str, ...] = DEFAULT_ALLOWED_HOST_SUFFIXES,
) -> dict[str, int]:
    output = Path(output_dir)
    manifest_file = Path(manifest_path)
    manifest = load_manifest(manifest_file)
    index = manifest_index(manifest)
    content_index = _content_index(manifest, manifest_file)
    opener = urllib.request.build_opener(SafeRedirectHandler(allowed_suffixes))
    candidates = interaction_avatar_candidates(database)
    totals = {
        "candidates": len(candidates),
        "downloaded": 0,
        "existing": 0,
        "deduplicated": 0,
        "failed": 0,
        "skipped": 0,
    }

    for position, (event_id, source_url, canonical) in enumerate(candidates):
        if max_items > 0 and position >= max_items:
            break
        key = (event_id, "interaction_avatar", canonical)
        previous = index.get(key)
        if previous:
            local_path = str(previous.get("local_path") or "")
            existing_path = manifest_file.parent / local_path if local_path else None
            if existing_path and existing_path.exists():
                previous["status"] = "existing"
                totals["existing"] += 1
                continue

        try:
            validate_url_syntax(source_url, allowed_suffixes)
        except ValueError as exc:
            item = {
                "event_id": event_id,
                "kind": "interaction_avatar",
                "source_url": source_url,
                "canonical_url": canonical,
                "status": "skipped",
                "error": str(exc),
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
            totals["skipped"] += 1
        else:
            event_directory = output / sanitize_component(event_id)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
            destination_base = event_directory / f"interaction-avatar-{digest}"
            try:
                validate_download_target(source_url, allowed_suffixes)
                destination, size_bytes, content_type, content_digest = download_one(
                    opener,
                    source_url,
                    destination_base,
                    expected_kind="image",
                    timeout=max(timeout, 1),
                    max_bytes=max(max_image_bytes, 1),
                )
                duplicate_path = content_index.get(content_digest)
                if duplicate_path and duplicate_path.exists():
                    destination.unlink(missing_ok=True)
                    destination = duplicate_path
                    status = "deduplicated"
                    totals["deduplicated"] += 1
                else:
                    content_index[content_digest] = destination
                    status = "downloaded"
                    totals["downloaded"] += 1
                item = {
                    "event_id": event_id,
                    "kind": "interaction_avatar",
                    "source_url": source_url,
                    "canonical_url": canonical,
                    "local_path": os.path.relpath(
                        destination,
                        manifest_file.parent,
                    ).replace(os.sep, "/"),
                    "status": status,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                    "sha256": content_digest,
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                }
            except (OSError, ValueError, urllib.error.URLError) as exc:
                item = {
                    "event_id": event_id,
                    "kind": "interaction_avatar",
                    "source_url": source_url,
                    "canonical_url": canonical,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                }
                totals["failed"] += 1

        if previous and previous in manifest["items"]:
            previous.clear()
            previous.update(item)
            index[key] = previous
        else:
            manifest["items"].append(item)
            index[key] = item
        save_manifest(manifest_file, manifest)

    save_manifest(manifest_file, manifest)
    return totals
