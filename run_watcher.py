from __future__ import annotations

import argparse
import time

from netease_dynamic_watcher.config import Config


def run_once(backfill: bool = False) -> None:
    from netease_dynamic_watcher.client import NeteaseClient
    from netease_dynamic_watcher.notifier import PushMeNotifier, PushNotifier
    from netease_dynamic_watcher.service import WatcherService
    from netease_dynamic_watcher.store import StateStore

    config = Config.from_sources()
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
    print(service.run_once(backfill=backfill))


def run_forever(interval_seconds: int = 900):
    while True:
        run_once()
        time.sleep(interval_seconds)


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
