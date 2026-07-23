from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import time

from netease_dynamic_watcher.config import Config
from netease_dynamic_watcher.runtime_state import configure_logging, write_runtime_status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def media_paths(database_path: str) -> tuple[Path, Path]:
    data_directory = Path(database_path).resolve().parent
    media_directory = data_directory / "media"
    return media_directory, media_directory / "manifest.json"


def run_once(backfill: bool = False):
    from netease_dynamic_watcher.client import NeteaseClient
    from netease_dynamic_watcher.media_archive import archive_database_media
    from netease_dynamic_watcher.notifier import PushMeNotifier, PushNotifier
    from netease_dynamic_watcher.service import WatcherService
    from netease_dynamic_watcher.store import StateStore

    config = Config.from_sources()
    logger = configure_logging(config.database_path)
    mode = "backfill" if backfill else "incremental"
    started_at = utc_now()

    write_runtime_status(
        config.database_path,
        {
            "status": "running",
            "mode": mode,
            "started_at": started_at,
            "target_uid": config.target_uid,
        },
    )
    logger.info("Watcher run started mode=%s target_uid=%s", mode, config.target_uid)

    try:
        config.validate_runtime()
        client = NeteaseClient(config.cookie, config.request_timeout_seconds)
        notifier = PushNotifier(
            lambda title, body: PushMeNotifier(
                config.notification_key,
                config.notification_endpoint,
            ).send(title, body)
        )
        service = WatcherService(
            client=client,
            store=StateStore(config.database_path),
            notifier=notifier,
            target_uid=config.target_uid,
            events_url=config.events_url_template.format(uid=config.target_uid),
        )

        # Commit the event payload first. This makes collection durable before
        # any media or notification network request is attempted.
        report = service.collect_once(backfill=backfill)

        media_directory, media_manifest = media_paths(config.database_path)
        media_report: dict[str, int] = {}
        media_error = ""
        try:
            media_report = archive_database_media(
                config.database_path,
                output_dir=media_directory,
                manifest_path=media_manifest,
                include_videos=True,
                timeout=max(config.request_timeout_seconds, 1),
            )
            if media_report.get("failed", 0) or media_report.get("skipped", 0):
                logger.warning("Media archive completed with gaps: %s", media_report)
            else:
                logger.info("Media archive completed: %s", media_report)
        except Exception as exc:
            # SQLite already contains the event. Keep it and retry media on the
            # next watcher run rather than losing the event or hiding the error.
            media_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Media archive synchronization failed")

        if not backfill and not report.initialized_now:
            delivery = service.deliver_pending_notifications()
            report = replace(
                report,
                delivered_notifications=delivery.delivered_notifications,
                failed_notifications=delivery.failed_notifications,
                pending_notifications=delivery.pending_notifications,
            )

        report_payload = asdict(report)
        write_runtime_status(
            config.database_path,
            {
                "status": "success",
                "mode": mode,
                "started_at": started_at,
                "finished_at": utc_now(),
                "target_uid": config.target_uid,
                "report": report_payload,
                "media_report": media_report,
                "media_error": media_error,
                "media_manifest": str(media_manifest),
            },
        )
        logger.info(
            "Watcher run succeeded mode=%s fetched=%s new=%s delivered=%s failed_notifications=%s pending=%s",
            mode,
            report.fetched_events,
            report.new_events,
            report.delivered_notifications,
            report.failed_notifications,
            report.pending_notifications,
        )
        print(report)
        print("MediaArchiveReport", media_report or {"error": media_error})
        return report
    except Exception as exc:
        write_runtime_status(
            config.database_path,
            {
                "status": "failure",
                "mode": mode,
                "started_at": started_at,
                "finished_at": utc_now(),
                "target_uid": config.target_uid,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        logger.exception("Watcher run failed mode=%s", mode)
        raise


def run_forever() -> None:
    while True:
        config = Config.from_sources()
        try:
            run_once()
        except Exception:
            # run_once has already recorded the failure and traceback.
            pass
        time.sleep(max(config.interval_minutes, 1) * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="initialize all available history without notifications",
    )
    args = parser.parse_args()

    if args.backfill:
        run_once(backfill=True)
    elif args.once:
        run_once()
    else:
        run_forever()
