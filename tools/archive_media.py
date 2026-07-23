from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from netease_dynamic_watcher.media_archive import (  # noqa: E402,F401
    DEFAULT_ALLOWED_HOST_SUFFIXES,
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_VIDEO_BYTES,
    archive_database_media,
    canonical_media_url,
    host_is_allowed,
    unique_media_urls,
    validate_download_target,
    validate_url_syntax,
)


def derived_media_paths(
    database: str | Path,
    *,
    output_dir: str | Path | None = None,
    manifest: str | Path | None = None,
) -> tuple[Path, Path]:
    """Resolve archive paths beside the selected SQLite database by default."""
    data_directory = Path(database).resolve().parent
    resolved_output = Path(output_dir) if output_dir else data_directory / "media"
    resolved_manifest = Path(manifest) if manifest else resolved_output / "manifest.json"
    return resolved_output, resolved_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把数据库中的图片、头像、歌曲封面和视频归档到本地"
    )
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument(
        "--output-dir",
        help="默认使用数据库同级的 media 目录",
    )
    parser.add_argument(
        "--manifest",
        help="默认使用归档目录中的 manifest.json",
    )
    parser.add_argument(
        "--skip-videos",
        action="store_true",
        help="归档头像、图片和歌曲封面，但跳过视频",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-items", type=int, default=0, help="0 表示不限制")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--max-image-bytes",
        type=int,
        default=DEFAULT_MAX_IMAGE_BYTES,
    )
    parser.add_argument(
        "--max-video-bytes",
        type=int,
        default=DEFAULT_MAX_VIDEO_BYTES,
    )
    parser.add_argument(
        "--allowed-host-suffix",
        action="append",
        dest="allowed_suffixes",
        help="附加允许的网易云 CDN 域名后缀，可重复指定",
    )
    args = parser.parse_args()

    output_dir, manifest = derived_media_paths(
        args.database,
        output_dir=args.output_dir,
        manifest=args.manifest,
    )
    allowed_suffixes = tuple(
        dict.fromkeys(
            DEFAULT_ALLOWED_HOST_SUFFIXES + tuple(args.allowed_suffixes or ())
        )
    )
    totals = archive_database_media(
        args.database,
        output_dir=output_dir,
        manifest_path=manifest,
        include_videos=not args.skip_videos,
        timeout=max(args.timeout, 1),
        max_image_bytes=max(args.max_image_bytes, 1),
        max_video_bytes=max(args.max_video_bytes, 1),
        max_items=max(args.max_items, 0),
        dry_run=args.dry_run,
        allowed_suffixes=allowed_suffixes,
    )
    print("媒体归档结果：", totals)
    print("归档目录：", output_dir.resolve())
    print("归档清单：", manifest.resolve())


if __name__ == "__main__":
    main()
