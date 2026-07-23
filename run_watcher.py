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


def _interaction_refresher(config: Config, client):
    from netease_dynamic_watcher.interaction_refresh import InteractionRefresher
    from netease_dynamic_watcher.interaction_store import InteractionStore

    return InteractionRefresher(
        client=client,
        store=InteractionStore(config.database_path),
        target_uid=config.target_uid,
        comments_url_template=config.comments_url_template,
        likers_url_template=config.likers_url_template,
        page_size=config.interaction_page_size,
        max_pages=config.interaction_max_pages,
    )


def run_once(backfill: bool = False, *, config: Config | None = None):
    from netease_dynamic_watcher.client import NeteaseClient
    from netease_dynamic_watcher.media_archive import archive_database_media
    from netease_dynamic_watcher.notifier import NullNotifier, PushMeNotifier, PushNotifier
    from netease_dynamic_watcher.service import WatcherService
    from netease_dynamic_watcher.store import StateStore

    config = config or Config.from_sources()
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
        config.validate_runtime(require_notification_key=not backfill)
        client = NeteaseClient(config.cookie, config.request_timeout_seconds)
        if backfill:
            notifier = NullNotifier()
        else:
            notifier = PushNotifier(
                lambda title, body: PushMeNotifier(
                    config.notification_key,
                    config.notification_endpoint,
                    timeout=config.request_timeout_seconds,
                ).send(title, body)
            )
        service = WatcherService(
            client=client,
            store=StateStore(config.database_path),
            notifier=notifier,
            target_uid=config.target_uid,
            events_url=config.events_url_template.format(uid=config.target_uid),
        )

        # Event persistence remains the durable boundary. Interaction and media
        # failures are recorded separately and never erase a collected event.
        report = service.collect_once(backfill=backfill)

        interaction_report: dict[str, int] = {}
        interaction_error = ""
        if config.interactions_enabled:
            try:
                interaction_report = asdict(
                    _interaction_refresher(config, client).refresh_due(
                        limit=config.interaction_batch_size,
                        force=False,
                    )
                )
                if interaction_report.get("failed_events", 0):
                    logger.warning(
                        "Interaction refresh completed with gaps: %s",
                        interaction_report,
                    )
                else:
                    logger.info("Interaction refresh completed: %s", interaction_report)
            except Exception as exc:
                interaction_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Interaction refresh failed")

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
                "interaction_report": interaction_report,
                "interaction_error": interaction_error,
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
        print("InteractionRefreshReport", interaction_report or {"error": interaction_error})
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


def refresh_interactions(*, force_all: bool = False, config: Config | None = None):
    from dataclasses import asdict
    from netease_dynamic_watcher.client import NeteaseClient

    config = config or Config.from_sources()
    logger = configure_logging(config.database_path)
    started_at = utc_now()
    mode = "interaction_refresh_all" if force_all else "interaction_refresh_due"
    try:
        config.validate_runtime(require_notification_key=False)
        if not config.interactions_enabled:
            raise ValueError("INTERACTIONS_ENABLED is disabled")
        client = NeteaseClient(config.cookie, config.request_timeout_seconds)
        report = _interaction_refresher(config, client).refresh_due(
            limit=0 if force_all else config.interaction_batch_size,
            force=force_all,
        )
        payload = asdict(report)
        write_runtime_status(
            config.database_path,
            {
                "status": "success",
                "mode": mode,
                "started_at": started_at,
                "finished_at": utc_now(),
                "target_uid": config.target_uid,
                "interaction_report": payload,
            },
        )
        logger.info("Manual interaction refresh completed: %s", payload)
        print("InteractionRefreshReport", payload)
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
        logger.exception("Manual interaction refresh failed")
        raise


def run_forever() -> None:
    while True:
        config = Config.from_sources()
        try:
            run_once(config=config)
        except Exception:
            pass
        time.sleep(max(config.interval_minutes, 1) * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument(
        "--backfill",
        action="store_true",
        help="initialize all available history without notifications",
    )
    mode.add_argument(
        "--refresh-interactions",
        action="store_true",
        help="refresh only the currently due interaction batch",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="with --refresh-interactions, explicitly refresh every stored event",
    )
    args = parser.parse_args()

    if args.all and not args.refresh_interactions:
        parser.error("--all can only be used with --refresh-interactions")
    if args.backfill:
        run_once(backfill=True)
    elif args.refresh_interactions:
        refresh_interactions(force_all=args.all)
    elif args.once:
        run_once()
    else:
        run_forever()
