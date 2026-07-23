from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import sqlite3
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ALLOWED_HOST_SUFFIXES = (
    "music.126.net",
    "vod.126.net",
    "music.163.com",
    "netease.com",
    "127.net",
)
DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_VIDEO_BYTES = 200 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
)
_IMAGE_KINDS = {"image", "song_cover", "avatar"}
_PROXY_FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)


@dataclass(frozen=True)
class MediaCandidate:
    event_id: str
    kind: str
    source_url: str
    canonical_url: str


def _decode_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def extract_song_cover(event: dict[str, Any]) -> str:
    raw = event.get("raw_payload")
    raw = raw if isinstance(raw, dict) else {}
    embedded = _decode_mapping(raw.get("json"))
    for candidate in (
        embedded.get("song"),
        raw.get("song"),
        embedded.get("resource"),
        raw.get("resource"),
    ):
        if not isinstance(candidate, dict):
            continue
        album = candidate.get("album") or candidate.get("al") or {}
        album = album if isinstance(album, dict) else {}
        cover = album.get("picUrl") or candidate.get("picUrl")
        if isinstance(cover, str) and cover.startswith(("http://", "https://")):
            return cover
    return ""


def canonical_media_url(url: str, kind: str = "image") -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parts = urllib.parse.urlsplit(value)
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower().rstrip(".")
    netloc = hostname
    if parts.port and parts.port not in {80, 443}:
        netloc = f"{hostname}:{parts.port}"
    query = parts.query
    if kind in _IMAGE_KINDS:
        # NetEase image query strings normally select a resized representation.
        # The path identifies the original asset and is stable for de-duplication.
        query = ""
    return urllib.parse.urlunsplit((scheme, netloc, parts.path, query, ""))


def unique_media_urls(urls: Iterable[Any], kind: str = "image") -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        if not isinstance(raw_url, str):
            continue
        url = raw_url.strip()
        canonical = canonical_media_url(url, kind)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        result.append(url)
    return result


def load_events(database: str | Path) -> list[dict[str, Any]]:
    database_path = Path(database)
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")
    with closing(sqlite3.connect(database_path)) as connection:
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


def iter_media(
    events: Iterable[dict[str, Any]],
    include_videos: bool = True,
) -> Iterable[MediaCandidate]:
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue

        sources: list[tuple[str, str]] = []
        avatar_url = str(event.get("avatar_url") or "").strip()
        if avatar_url:
            sources.append(("avatar", avatar_url))
        sources.extend(
            ("image", url)
            for url in unique_media_urls(event.get("image_urls") or [], "image")
        )
        cover = extract_song_cover(event)
        if cover:
            sources.append(("song_cover", cover))
        if include_videos:
            sources.extend(
                ("video", url)
                for url in unique_media_urls(event.get("video_urls") or [], "video")
            )

        for kind, source_url in sources:
            canonical = canonical_media_url(source_url, kind)
            key = (event_id, kind, canonical)
            if not canonical or key in seen:
                continue
            seen.add(key)
            yield MediaCandidate(event_id, kind, source_url, canonical)


def normalize_suffix(value: str) -> str:
    return value.strip().lower().lstrip(".")


def host_is_allowed(hostname: str, allowed_suffixes: Iterable[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in (normalize_suffix(value) for value in allowed_suffixes)
        if suffix
    )


def validate_url_syntax(
    url: str,
    allowed_suffixes: Iterable[str],
) -> urllib.parse.SplitResult:
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


def is_proxy_fake_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(value in network for network in _PROXY_FAKE_IP_NETWORKS)


def validate_public_target(parts: urllib.parse.SplitResult) -> None:
    hostname = parts.hostname
    if not hostname:
        raise ValueError("URL 缺少主机名")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("无法解析下载主机")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        # Clash and similar TUN/Fake-IP DNS modes intentionally map public hosts
        # into RFC 2544's benchmarking range. The hostname has already passed a
        # strict NetEase CDN suffix allowlist, so this one range is safe to accept.
        if not ip.is_global and not is_proxy_fake_ip(ip):
            raise ValueError(f"下载主机解析到非公网地址：{ip}")


def validate_download_target(url: str, allowed_suffixes: Iterable[str]) -> None:
    validate_public_target(validate_url_syntax(url, allowed_suffixes))


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


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {"version": 2, "items": []}
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "items": []}
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        return {"version": 2, "items": []}
    value["version"] = 2
    return value


def save_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)


def _manifest_key(item: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(item.get("kind") or "image")
    canonical = str(item.get("canonical_url") or "")
    if not canonical:
        canonical = canonical_media_url(str(item.get("source_url") or ""), kind)
    return str(item.get("event_id") or ""), kind, canonical


def manifest_index(
    manifest: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        key = _manifest_key(item)
        if all(key):
            result[key] = item
    return result


def _content_index(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        digest = str(item.get("sha256") or "")
        local_path = str(item.get("local_path") or "")
        if not digest or not local_path:
            continue
        path = manifest_path.parent / local_path
        if path.exists():
            result[digest] = path
    return result


def download_one(
    opener,
    url: str,
    destination_without_suffix: Path,
    *,
    expected_kind: str,
    timeout: int,
    max_bytes: int,
) -> tuple[Path, int, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "video/*" if expected_kind == "video" else "image/*",
            "User-Agent": USER_AGENT,
        },
    )
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = str(response.headers.get("Content-Type") or "")
        normalized_type = content_type.split(";", 1)[0].strip().lower()
        required_prefix = "video/" if expected_kind == "video" else "image/"
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
        hasher = hashlib.sha256()
        try:
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"文件超过大小限制：{max_bytes} bytes")
                    hasher.update(chunk)
                    handle.write(chunk)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return destination, total, content_type, hasher.hexdigest()


def archive_database_media(
    database: str | Path,
    *,
    output_dir: str | Path = "data/media",
    manifest_path: str | Path = "data/media/manifest.json",
    include_videos: bool = True,
    timeout: int = 20,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_video_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
    max_items: int = 0,
    dry_run: bool = False,
    allowed_suffixes: tuple[str, ...] = DEFAULT_ALLOWED_HOST_SUFFIXES,
) -> dict[str, int]:
    output = Path(output_dir)
    manifest_file = Path(manifest_path)
    manifest = load_manifest(manifest_file)
    index = manifest_index(manifest)
    content_index = _content_index(manifest, manifest_file)
    opener = urllib.request.build_opener(SafeRedirectHandler(allowed_suffixes))
    candidates = list(iter_media(load_events(database), include_videos=include_videos))
    totals = {
        "candidates": len(candidates),
        "downloaded": 0,
        "existing": 0,
        "deduplicated": 0,
        "failed": 0,
        "skipped": 0,
    }

    for position, candidate in enumerate(candidates):
        if max_items > 0 and position >= max_items:
            break
        key = (candidate.event_id, candidate.kind, candidate.canonical_url)
        previous = index.get(key)
        if previous:
            local_path = str(previous.get("local_path") or "")
            existing_path = manifest_file.parent / local_path if local_path else None
            if existing_path and existing_path.exists():
                previous["status"] = "existing"
                totals["existing"] += 1
                continue

        try:
            validate_url_syntax(candidate.source_url, allowed_suffixes)
        except ValueError as exc:
            item = {
                "event_id": candidate.event_id,
                "kind": candidate.kind,
                "source_url": candidate.source_url,
                "canonical_url": candidate.canonical_url,
                "status": "skipped",
                "error": str(exc),
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
            totals["skipped"] += 1
        else:
            if dry_run:
                totals["skipped"] += 1
                continue
            event_directory = output / sanitize_component(candidate.event_id)
            url_digest = hashlib.sha256(
                candidate.canonical_url.encode("utf-8")
            ).hexdigest()[:16]
            destination_base = event_directory / f"{candidate.kind}-{url_digest}"
            try:
                validate_download_target(candidate.source_url, allowed_suffixes)
                expected_kind = "video" if candidate.kind == "video" else "image"
                max_bytes = (
                    max_video_bytes
                    if candidate.kind == "video"
                    else max_image_bytes
                )
                destination, size_bytes, content_type, content_digest = download_one(
                    opener,
                    candidate.source_url,
                    destination_base,
                    expected_kind=expected_kind,
                    timeout=max(timeout, 1),
                    max_bytes=max(max_bytes, 1),
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
                local_path = os.path.relpath(
                    destination,
                    manifest_file.parent,
                ).replace(os.sep, "/")
                item = {
                    "event_id": candidate.event_id,
                    "kind": candidate.kind,
                    "source_url": candidate.source_url,
                    "canonical_url": candidate.canonical_url,
                    "local_path": local_path,
                    "status": status,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                    "sha256": content_digest,
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                }
            except (OSError, ValueError, urllib.error.URLError) as exc:
                item = {
                    "event_id": candidate.event_id,
                    "kind": candidate.kind,
                    "source_url": candidate.source_url,
                    "canonical_url": candidate.canonical_url,
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

    if not dry_run:
        save_manifest(manifest_file, manifest)
    return totals
