from __future__ import annotations

import time

from netease_dynamic_watcher.config import Config


# The concrete wiring is intentionally kept local. Secrets are never stored here.
def run_forever(interval_seconds: int = 900):
    from netease_dynamic_watcher.client import NeteaseClient
    from netease_dynamic_watcher.notifier import PushMeNotifier, PushNotifier
    from netease_dynamic_watcher.service import WatcherService
    from netease_dynamic_watcher.store import StateStore

    config = Config.from_env()
    client = NeteaseClient(config.cookie, config.request_timeout_seconds)
    notifier = PushNotifier(
        PushMeNotifier(config.notification_key).send
    )
    service = WatcherService(
        client=client,
        store=StateStore(config.database_path),
        notifier=notifier,
        target_uid=config.target_uid,
        events_url=config.events_url_template.format(uid=config.target_uid),
    )

    while True:
        service.run_once()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_forever()
