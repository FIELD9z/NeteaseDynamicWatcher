from __future__ import annotations

import html
import json
import os
import shutil
import sqlite3
from contextlib import closing
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from netease_dynamic_watcher.media_archive import (
    canonical_media_url,
    iter_media,
    unique_media_urls,
)


TYPE_LABELS = {
    "dynamic": "文字动态",
    "song_share": "歌曲分享",
    "image": "图片动态",
    "forward": "转发动态",
    "video": "视频动态",
}
MediaMap = dict[tuple[str, str, str], Path]


def safe(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def parse_timestamp(milliseconds: Any) -> datetime | None:
    try:
        value = int(milliseconds or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000).astimezone()


def format_time(milliseconds: Any) -> str:
    value = parse_timestamp(milliseconds)
    return "未知时间" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def load_archive_events(database: str | Path) -> list[dict[str, Any]]:
    path = Path(database)
    if not path.exists():
        raise FileNotFoundError(f"数据库不存在：{path}")

    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT payload, seen_at FROM events").fetchall()

    events: list[dict[str, Any]] = []
    for payload, seen_at in rows:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event = dict(event)
        event["seen_at"] = seen_at
        # image_urls is a logical ordered list. It may intentionally contain the
        # same canonical image more than once when the author posted it twice.
        event["image_urls"] = [
            str(value)
            for value in (event.get("image_urls") or [])
            if isinstance(value, str) and value.startswith(("http://", "https://"))
        ]
        event["video_urls"] = unique_media_urls(
            event.get("video_urls") or [],
            "video",
        )
        events.append(event)

    events.sort(
        key=lambda event: (
            int(event.get("publish_time_ms") or 0),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    return events


def load_media_manifest(path: str | Path) -> MediaMap:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    result: MediaMap = {}
    items = manifest.get("items", []) if isinstance(manifest, dict) else []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in {"downloaded", "existing", "deduplicated"}:
            continue
        event_id = str(item.get("event_id") or "")
        kind = str(item.get("kind") or "image")
        source_url = str(item.get("source_url") or "")
        canonical = str(item.get("canonical_url") or "")
        canonical = canonical or canonical_media_url(source_url, kind)
        local_path = str(item.get("local_path") or "")
        if event_id and kind and canonical and local_path:
            result[(event_id, kind, canonical)] = manifest_path.parent / local_path
    return result


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


def _artist_names(song: dict[str, Any]) -> list[str]:
    value = song.get("artists") or song.get("ar") or []
    if not isinstance(value, list):
        return []
    names = [
        str(artist.get("name") or "").strip()
        for artist in value
        if isinstance(artist, dict)
    ]
    return [name for name in names if name]


def extract_song(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("raw_payload")
    raw = raw if isinstance(raw, dict) else {}
    embedded = _decode_mapping(raw.get("json"))
    candidates = (
        embedded.get("song"),
        raw.get("song"),
        embedded.get("resource"),
        raw.get("resource"),
    )
    song: dict[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            song = candidate
            break
    if not song:
        return {}

    album = song.get("album") or song.get("al") or {}
    album = album if isinstance(album, dict) else {}
    song_id = str(song.get("id") or song.get("songId") or "")
    return {
        "name": str(song.get("name") or "未知歌曲").strip(),
        "artists": " / ".join(_artist_names(song)) or "未知歌手",
        "album": str(album.get("name") or "").strip(),
        "cover": str(album.get("picUrl") or song.get("picUrl") or "").strip(),
        "url": (
            f"https://music.163.com/#/song?id={song_id}"
            if song_id
            else str(song.get("url") or "").strip()
        ),
    }


def event_kinds(event: dict[str, Any]) -> set[str]:
    kinds = {str(event.get("event_type") or "dynamic")}
    if event.get("image_urls"):
        kinds.add("image")
    if event.get("video_urls"):
        kinds.add("video")
    if event.get("forwarded_event_id") or event.get("forwarded_summary"):
        kinds.add("forward")
    if extract_song(event):
        kinds.add("song_share")
    return kinds


def group_events_by_month(
    events: Iterable[dict[str, Any]],
) -> OrderedDict[str, list[dict[str, Any]]]:
    result: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for event in events:
        published = parse_timestamp(event.get("publish_time_ms"))
        key = "unknown" if published is None else published.strftime("%Y-%m")
        result.setdefault(key, []).append(event)
    return result


def month_label(key: str) -> str:
    if key == "unknown":
        return "时间未知"
    year, month = key.split("-", 1)
    return f"{year}年{int(month)}月"


def _relative_path(path: Path, output: Path) -> str:
    return os.path.relpath(path, output.parent).replace(os.sep, "/")


def _local_media(
    media_map: MediaMap,
    event_id: str,
    kind: str,
    source_url: str,
) -> Path | None:
    canonical = canonical_media_url(source_url, kind)
    path = media_map.get((event_id, kind, canonical))
    return path if path and path.exists() else None


def _missing_resource(label: str) -> str:
    return (
        '<div class="media-missing">'
        f'<strong>{safe(label)}未完成本地归档</strong>'
        '<span>重新运行 open_ui.py 或 archive_media.py 后再查看。</span>'
        "</div>"
    )


def _render_avatar(
    event: dict[str, Any],
    output: Path,
    media_map: MediaMap,
) -> str:
    event_id = str(event.get("event_id") or "")
    nickname = str(event.get("nickname") or "未知用户")
    avatar_url = str(event.get("avatar_url") or "")
    local_avatar = _local_media(media_map, event_id, "avatar", avatar_url)
    if local_avatar:
        src = safe(_relative_path(local_avatar, output))
        return f'<div class="avatar"><img src="{src}" loading="lazy" alt="{safe(nickname)}的头像"></div>'
    return f'<div class="avatar avatar-fallback">{safe(nickname[:1] or "?")}</div>'


def _render_song_card(
    event: dict[str, Any],
    song: dict[str, str],
    output: Path,
    media_map: MediaMap,
) -> str:
    if not song:
        return ""
    event_id = str(event.get("event_id") or "")
    cover_url = song.get("cover", "")
    local_cover = _local_media(media_map, event_id, "song_cover", cover_url)
    if local_cover:
        cover_src = safe(_relative_path(local_cover, output))
        cover = f'<img src="{cover_src}" loading="lazy" alt="歌曲封面">'
    else:
        cover = '<div class="song-cover-placeholder">♪</div>'

    title = safe(song.get("name"))
    artists = safe(song.get("artists"))
    album = safe(song.get("album"))
    href = safe(song.get("url"))
    link_start = f'<a href="{href}" target="_blank" rel="noreferrer">' if href else "<div>"
    link_end = "</a>" if href else "</div>"
    return f"""
{link_start}
  <div class="song-card">
    <div class="song-cover">{cover}</div>
    <div class="song-info">
      <span>歌曲分享</span>
      <strong>{title}</strong>
      <p>{artists}{f' · {album}' if album else ''}</p>
    </div>
    <div class="song-arrow">↗</div>
  </div>
{link_end}
"""


def _render_images(
    event: dict[str, Any],
    output: Path,
    media_map: MediaMap,
) -> str:
    event_id = str(event.get("event_id") or "")
    urls = [
        str(value)
        for value in (event.get("image_urls") or [])
        if isinstance(value, str)
    ]
    items: list[str] = []
    for index, source_url in enumerate(urls, start=1):
        local = _local_media(media_map, event_id, "image", source_url)
        if not local:
            items.append(_missing_resource(f"图片 {index}"))
            continue
        image_src = _relative_path(local, output)
        caption = f"事件 {event_id} · 图片 {index}/{len(urls)}"
        items.append(
            f"""
<button class="media-item" type="button" data-full="{safe(image_src)}" data-caption="{safe(caption)}">
  <img src="{safe(image_src)}" loading="lazy" alt="{safe(caption)}">
  <span class="media-origin">本地归档</span>
</button>
"""
        )
    if not items:
        return ""
    visible_class = min(len(items), 4)
    return f'<div class="gallery gallery-count-{visible_class}">{"".join(items)}</div>'


def _render_videos(
    event: dict[str, Any],
    output: Path,
    media_map: MediaMap,
) -> str:
    event_id = str(event.get("event_id") or "")
    items: list[str] = []
    for index, source_url in enumerate(
        unique_media_urls(event.get("video_urls") or [], "video"),
        start=1,
    ):
        local = _local_media(media_map, event_id, "video", source_url)
        if not local:
            items.append(_missing_resource(f"视频 {index}"))
            continue
        video_src = _relative_path(local, output)
        items.append(
            f'<video class="local-video" controls preload="metadata" '
            f'src="{safe(video_src)}">浏览器不支持视频播放。</video>'
        )
    return f'<div class="video-gallery">{"".join(items)}</div>' if items else ""


def _render_event_card(
    event: dict[str, Any],
    output: Path,
    media_map: MediaMap,
) -> str:
    published = parse_timestamp(event.get("publish_time_ms"))
    day = "--" if published is None else published.strftime("%d")
    weekday = "未知" if published is None else published.strftime("%a")
    timestamp = format_time(event.get("publish_time_ms"))
    nickname = str(event.get("nickname") or "未知用户")
    event_type = str(event.get("event_type") or "dynamic")
    type_label = TYPE_LABELS.get(event_type, event_type)
    event_id = str(event.get("event_id") or "")
    summary = safe(event.get("summary") or "发布了新的动态")
    forward_summary = safe(event.get("forwarded_summary"))
    forward_id = safe(event.get("forwarded_event_id"))
    song = extract_song(event)
    kinds = sorted(event_kinds(event))
    search_text = " ".join(
        [
            nickname,
            event_type,
            str(event.get("raw_type") or ""),
            str(event.get("summary") or ""),
            str(event.get("forwarded_summary") or ""),
            song.get("name", ""),
            song.get("artists", ""),
            song.get("album", ""),
        ]
    ).lower()
    raw_json = json.dumps(event.get("raw_payload") or {}, ensure_ascii=False, indent=2)
    details = f"""
<div class="detail-grid">
  <span>事件 ID</span><code>{safe(event_id)}</code>
  <span>原始 type</span><code>{safe(event.get('raw_type'))}</code>
  <span>评论线程</span><code>{safe(event.get('comment_thread_id'))}</code>
  <span>入库时间</span><code>{safe(event.get('seen_at'))}</code>
  <span>头像快照</span><code>{'已保存' if event.get('avatar_url') else '无'}</code>
  <details class="raw-details"><summary>完整原始 JSON</summary><pre>{safe(raw_json)}</pre></details>
</div>
"""
    forward = ""
    if forward_summary or forward_id:
        forward = f"""
<div class="forward-card">
  <span class="forward-label">转发内容</span>
  <p>{forward_summary or '原动态内容未解析，但已保留原始 JSON。'}</p>
  {f'<span class="forward-id">原动态 ID：{forward_id}</span>' if forward_id else ''}
</div>
"""
    page_url = safe(event.get("url"))
    page_link = (
        f'<a href="{page_url}" target="_blank" rel="noreferrer">打开网易云</a>'
        if page_url
        else ""
    )
    return f"""
<article class="event-card" data-kinds="{safe(' '.join(kinds))}" data-search="{safe(search_text)}">
  <div class="date-rail"><strong>{day}</strong><span>{safe(weekday)}</span></div>
  <div class="event-body">
    <header class="event-header">
      <div class="identity">
        {_render_avatar(event, output, media_map)}
        <div><h3>{safe(nickname)}</h3><time>{safe(timestamp)}</time></div>
      </div>
      <span class="type-pill">{safe(type_label)}</span>
    </header>
    <div class="event-summary">{summary}</div>
    {_render_song_card(event, song, output, media_map)}
    {forward}
    {_render_images(event, output, media_map)}
    {_render_videos(event, output, media_map)}
    <footer class="event-footer">
      <div class="engagement">
        <span>评论 <b>{safe(event.get('comment_count', 0))}</b></span>
        <span>转发 <b>{safe(event.get('share_count', 0))}</b></span>
        <span>点赞 <b>{safe(event.get('liked_count', 0))}</b></span>
      </div>
      <div class="event-actions">{page_link}<details><summary>数据详情</summary>{details}</details></div>
    </footer>
  </div>
</article>
"""


def _runtime_copy(runtime_summary: dict[str, Any]) -> tuple[str, str, str]:
    runtime = runtime_summary.get("runtime", {}) if isinstance(runtime_summary, dict) else {}
    status = str(runtime.get("status") or "unknown")
    status_label = {
        "success": "最近一次检查成功",
        "failure": "最近一次检查失败",
        "running": "正在检查",
    }.get(status, "尚未记录运行状态")
    detail = str(runtime.get("error_message") or "")
    if not detail and isinstance(runtime.get("report"), dict):
        report = runtime["report"]
        detail = (
            f"获取 {report.get('fetched_events', 0)} 条，"
            f"新增 {report.get('new_events', 0)} 条，"
            f"通知 {report.get('delivered_notifications', 0)} 条，"
            f"待通知 {report.get('pending_notifications', 0)} 条"
        )
    time_value = runtime.get("finished_at") or runtime.get("started_at") or ""
    return status, status_label, str(detail or time_value or "打开页面时读取本地数据库")


def render_archive_html(
    events: list[dict[str, Any]],
    output: str | Path,
    media_map: MediaMap | None = None,
    runtime_summary: dict[str, Any] | None = None,
) -> str:
    output_path = Path(output)
    media_map = media_map or {}
    runtime_summary = runtime_summary or {}
    groups = group_events_by_month(events)
    type_counts = Counter(kind for event in events for kind in event_kinds(event))
    candidates = list(iter_media(events, include_videos=True))
    local_media_count = sum(
        bool(
            _local_media(
                media_map,
                candidate.event_id,
                candidate.kind,
                candidate.source_url,
            )
        )
        for candidate in candidates
    )
    missing_media_count = max(len(candidates) - local_media_count, 0)

    month_options = ['<option value="">跳转到月份</option>']
    month_navigation: list[str] = []
    month_sections: list[str] = []
    for key, month_events in groups.items():
        section_id = f"month-{key}"
        label = month_label(key)
        month_options.append(
            f'<option value="{safe(section_id)}">{safe(label)} · {len(month_events)}条</option>'
        )
        month_navigation.append(
            f'<a href="#{safe(section_id)}"><span>{safe(label)}</span><b>{len(month_events)}</b></a>'
        )
        cards = "".join(
            _render_event_card(event, output_path, media_map) for event in month_events
        )
        month_sections.append(
            f"""
<section class="month-section" id="{safe(section_id)}">
  <header class="month-heading"><h2>{safe(label)}</h2><span>{len(month_events)} 条动态</span></header>
  <div class="month-events">{cards}</div>
</section>
"""
        )

    status, status_label, status_detail = _runtime_copy(runtime_summary)
    filter_definitions = (
        ("all", "全部", len(events)),
        ("song_share", "歌曲", type_counts.get("song_share", 0)),
        ("image", "图片", type_counts.get("image", 0)),
        ("forward", "转发", type_counts.get("forward", 0)),
        ("video", "视频", type_counts.get("video", 0)),
        ("dynamic", "文字", type_counts.get("dynamic", 0)),
    )
    filter_buttons = "".join(
        f'<button class="filter-chip{" active" if key == "all" else ""}" type="button" '
        f'data-filter="{safe(key)}" aria-pressed="{"true" if key == "all" else "false"}">'
        f'{safe(label)} <b>{count}</b></button>'
        for key, label, count in filter_definitions
    )

    return f"""<!doctype html>
<html lang="zh-CN" data-theme="auto">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self' data:; img-src 'self' data:; media-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'">
  <title>网易云动态档案</title>
  <link rel="stylesheet" href="assets/archive.css">
</head>
<body>
<div class="shell">
  <section class="hero">
    <div class="hero-top">
      <div>
        <div class="eyebrow">NETEASE DYNAMIC ARCHIVE</div>
        <h1>把时间线保存成<br>可以慢慢阅读的档案。</h1>
        <p class="hero-copy">页面只加载本地媒体文件。每条动态保留自己的头像快照；重复图片位置会按原发布顺序显示。</p>
      </div>
      <button id="theme-toggle" class="icon-button" type="button" aria-label="切换主题">◐</button>
    </div>
    <div class="stats">
      <div class="stat"><strong>{len(events)}</strong><span>全部动态</span></div>
      <div class="stat"><strong>{type_counts.get('song_share', 0)}</strong><span>歌曲分享</span></div>
      <div class="stat"><strong>{local_media_count}</strong><span>本地媒体</span></div>
      <div class="stat"><strong>{missing_media_count}</strong><span>待补齐资源</span></div>
    </div>
    <div class="runtime-card status-{safe(status)}">
      <div><span class="status-dot"></span><strong>{safe(status_label)}</strong></div>
      <small>{safe(status_detail)}</small>
    </div>
  </section>

  <div class="toolbar">
    <label class="search-wrap"><span>⌕</span><input id="search" type="search" placeholder="搜索正文、歌曲、歌手或转发内容"></label>
    <select id="month-select" aria-label="跳转月份">{"".join(month_options)}</select>
    <select id="density-select" aria-label="阅读密度"><option value="comfortable">舒适阅读</option><option value="compact">紧凑阅读</option></select>
  </div>
  <div class="filters">{filter_buttons}</div>

  <div class="content-grid">
    <nav class="month-nav"><h2>时间线</h2>{"".join(month_navigation)}</nav>
    <main>
      <p>当前显示 <strong id="visible-count">{len(events)}</strong> 条</p>
      {"".join(month_sections)}
      <div id="empty-state" class="empty-state">没有找到符合条件的动态。</div>
    </main>
  </div>
  <p class="footer-note">本地静态档案 · 关闭浏览器后不会有 Web UI 常驻进程</p>
</div>

<dialog id="image-dialog" class="dialog">
  <img id="dialog-image" alt="动态图片">
  <footer><span id="dialog-caption"></span><button id="dialog-close" type="button">关闭</button></footer>
</dialog>
<script src="assets/archive.js"></script>
</body>
</html>
"""


def copy_archive_assets(output_directory: str | Path) -> Path:
    destination = Path(output_directory) / "assets"
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent.parent / "web"
    for name in ("archive.css", "archive.js"):
        source_path = source / name
        if not source_path.exists():
            raise FileNotFoundError(f"缺少 Web UI 资源：{source_path}")
        shutil.copyfile(source_path, destination / name)
    return destination


def write_archive_html(
    events: list[dict[str, Any]],
    output: str | Path,
    *,
    media_manifest: str | Path = "data/media/manifest.json",
    runtime_summary: dict[str, Any] | None = None,
) -> Path:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    media_map = load_media_manifest(media_manifest)
    copy_archive_assets(output_path.parent)
    output_path.write_text(
        render_archive_html(events, output_path, media_map, runtime_summary),
        encoding="utf-8",
    )
    return output_path
