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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把数据库中的图片、歌曲封面和视频归档到本地"
    )
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output-dir", default="data/media")
    parser.add_argument("--manifest", default="data/media/manifest.json")
    parser.add_argument(
        "--skip-videos",
        action="store_true",
        help="只归档图片和歌曲封面",
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

    allowed_suffixes = tuple(
        dict.fromkeys(
            DEFAULT_ALLOWED_HOST_SUFFIXES + tuple(args.allowed_suffixes or ())
        )
    )
    totals = archive_database_media(
        args.database,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        include_videos=not args.skip_videos,
        timeout=max(args.timeout, 1),
        max_image_bytes=max(args.max_image_bytes, 1),
        max_video_bytes=max(args.max_video_bytes, 1),
        max_items=max(args.max_items, 0),
        dry_run=args.dry_run,
        allowed_suffixes=allowed_suffixes,
    )
    print("媒体归档结果：", totals)
    print("归档目录：", Path(args.output_dir).resolve())
    print("归档清单：", Path(args.manifest).resolve())


if __name__ == "__main__":
    main()
