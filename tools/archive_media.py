from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ALLOWED_HOST_SUFFIXES = (
    "music.126.net",
    "music.163.com",
    "netease.com",
    "127.net",
)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
)


def load_events(database: Path) -> list[dict[str, Any]]:
    if not database.exists():
        raise SystemExit(f"数据库不存在：{database}")
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT payload FROM events").fetchall()

    events: list[dict[str, Any]] = []
    for (payload,) in rows:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def normalize_suffix(value: str) -> str:
    return value.strip().lower().lstrip(".")


def host_is_allowed(hostname: str, allowed_suffixes: Iterable[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in (normalize_suffix(value) for value in allowed_suffixes)
        if suffix
    )


def validate_url_syntax(url: str, allowed_suffixes: Iterable[str]) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("只允许 HTTP/HTTPS URL")
    if parts.username or parts.password:
        raise ValueError("URL 不允许包含用户名或密码")
    if not parts.hostname:
        raise ValueError("URL 缺少主机名")
    if parts.port not in {None, 80, 443}:
        raise ValueError("URL 端口不在允许范围")
    if not host_is_allowed(parts.hostname, allowed_suffixes):
        raise ValueError(f"主机不在允许列表：{parts.hostname}")
    return parts


def validate_public_target(parts: urllib.parse.SplitResult) -> None:
    hostname = parts.hostname
    if not hostname:
        raise ValueError("URL 缺少主机名")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("无法解析下载主机")
    for address in addresses:
        ip_text = address[4][0]
        ip = ipaddress.ip_address(ip_text)
        if not ip.is_global:
            raise ValueError(f"下载主机解析到非公网地址：{ip}")


def validate_download_target(url: str, allowed_suffixes: Iterable[str]) -> None:
    parts = validate_url_syntax(url, allowed_suffixes)
    validate_public_target(parts)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_suffixes: tuple[str, ...]) -> None:
        super().__init__()
        self.allowed_suffixes = allowed_suffixes

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_target(newurl, self.allowed_suffixes)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sanitize_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned[:120] or "unknown"


def extension_for(content_type: str, url: str, kind: str) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(media_type) or ""
    if extension == ".jpe":
        extension = ".jpg"
    if extension:
        return extension

    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    return ".bin" if kind == "video" else ".img"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": []}
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        return {"version": 1, "items": []}
    return value


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def manifest_index(manifest: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("event_id") or ""),
            str(item.get("kind") or ""),
            str(item.get("source_url") or ""),
        )
        if all(key):
            result[key] = item
    return result


def iter_media(events: Iterable[dict[str, Any]], include_videos: bool):
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        for url in event.get("image_urls") or []:
            if isinstance(url, str) and url:
                yield event_id, "image", url
        if include_videos:
            for url in event.get("video_urls") or []:
                if isinstance(url, str) and url:
                    yield event_id, "video", url


def download_one(
    opener,
    url: str,
    destination_without_suffix: Path,
    *,
    expected_kind: str,
    timeout: int,
    max_bytes: int,
) -> tuple[Path, int, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/*" if expected_kind == "image" else "video/*",
            "User-Agent": USER_AGENT,
        },
    )
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = str(response.headers.get("Content-Type") or "")
        normalized_type = content_type.split(";", 1)[0].strip().lower()
        required_prefix = "image/" if expected_kind == "image" else "video/"
        if not normalized_type.startswith(required_prefix):
            raise ValueError(f"响应类型不是 {required_prefix}：{content_type or '未知'}")

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > max_bytes:
                raise ValueError(f"文件超过大小限制：{declared_size} bytes")

        extension = extension_for(content_type, final_url, expected_kind)
        destination = destination_without_suffix.with_suffix(extension)
        temporary = destination.with_suffix(destination.suffix + ".part")
        destination.parent.mkdir(parents=True, exist_ok=True)

        total = 0
        try:
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"文件超过大小限制：{max_bytes} bytes")
                    handle.write(chunk)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    return destination, total, content_type


def main() -> None:
    parser = argparse.ArgumentParser(description="将数据库中的图片安全归档到本地")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output-dir", default="data/media")
    parser.add_argument("--manifest", default="data/media/manifest.json")
    parser.add_argument("--include-videos", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-items", type=int, default=0, help="0 表示不限制")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--allowed-host-suffix",
        action="append",
        dest="allowed_suffixes",
        help="附加允许的 CDN 域名后缀，可重复指定",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest)
    allowed_suffixes = tuple(
        dict.fromkeys(
            DEFAULT_ALLOWED_HOST_SUFFIXES + tuple(args.allowed_suffixes or ())
        )
    )
    events = load_events(Path(args.database))
    manifest = load_manifest(manifest_path)
    index = manifest_index(manifest)
    opener = urllib.request.build_opener(SafeRedirectHandler(allowed_suffixes))

    totals = {"downloaded": 0, "existing": 0, "failed": 0, "skipped": 0}
    processed = 0
    candidates = list(iter_media(events, args.include_videos))
    print(f"发现媒体 URL：{len(candidates)} 个")

    for event_id, kind, source_url in candidates:
        if args.max_items > 0 and processed >= args.max_items:
            break
        processed += 1
        key = (event_id, kind, source_url)
        previous = index.get(key)
        if previous:
            local_path = str(previous.get("local_path") or "")
            existing_path = manifest_path.parent / local_path if local_path else None
            if existing_path and existing_path.exists():
                previous["status"] = "existing"
                totals["existing"] += 1
                continue

        try:
            validate_url_syntax(source_url, allowed_suffixes)
        except ValueError as exc:
            item = {
                "event_id": event_id,
                "kind": kind,
                "source_url": source_url,
                "status": "skipped",
                "error": str(exc),
            }
            manifest["items"].append(item)
            index[key] = item
            totals["skipped"] += 1
            continue

        event_directory = output_dir / sanitize_component(event_id)
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
        destination_base = event_directory / f"{kind}-{digest}"

        if args.dry_run:
            print(f"DRY RUN {event_id} {kind}: {source_url}")
            continue

        try:
            validate_download_target(source_url, allowed_suffixes)
            destination, size_bytes, content_type = download_one(
                opener,
                source_url,
                destination_base,
                expected_kind=kind,
                timeout=max(args.timeout, 1),
                max_bytes=max(args.max_bytes, 1),
            )
            local_path = os.path.relpath(destination, manifest_path.parent).replace(
                os.sep, "/"
            )
            item = {
                "event_id": event_id,
                "kind": kind,
                "source_url": source_url,
                "local_path": local_path,
                "status": "downloaded",
                "content_type": content_type,
                "size_bytes": size_bytes,
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
            totals["downloaded"] += 1
        except (OSError, ValueError, urllib.error.URLError) as exc:
            item = {
                "event_id": event_id,
                "kind": kind,
                "source_url": source_url,
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
        save_manifest(manifest_path, manifest)

    if not args.dry_run:
        save_manifest(manifest_path, manifest)
    print("归档结果：", totals)
    print("清单：", manifest_path.resolve())


if __name__ == "__main__":
    main()
