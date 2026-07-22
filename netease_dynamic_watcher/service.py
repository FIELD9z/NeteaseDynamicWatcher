from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from netease_dynamic_watcher.parser import parse_events
from netease_dynamic_watcher.store import StateStore


class EventClient(Protocol):
    def fetch_user_events(self, url: str, *, limit: int, lasttime: int = -1) -> dict: ...


class EventNotifier(Protocol):
    def notify(self, event) -> bool: ...


class NotificationDeliveryError(RuntimeError):
    """Raised when a new event could not be delivered."""


@dataclass(frozen=True)
class RunReport:
    initialized_now: bool
    fetched_events: int
    new_events: int
    delivered_notifications: int


class WatcherService:
    def __init__(self, client, store, notifier, target_uid, events_url):
        self.client = client
        self.store = store
        self.notifier = notifier
        self.target_uid = target_uid
        self.events_url = events_url

    def run_once(self, *, backfill: bool = False) -> RunReport:
        payload = self.client.fetch_user_events(
            self.events_url,
            limit=100,
            lasttime=-1,
        )
        events = parse_events(payload, user_id=self.target_uid)
        events.sort(key=lambda event: (event.publish_time_ms, event.event_id))

        if not self.store.is_initialized(self.target_uid) or backfill:
            self.store.save_many(events)
            self.store.mark_initialized(self.target_uid)
            return RunReport(
                initialized_now=True,
                fetched_events=len(events),
                new_events=0,
                delivered_notifications=0,
            )

        new_events = [
            event
            for event in events
            if not self.store.is_seen(self.target_uid, event.event_id)
        ]
        delivered = 0
        for event in new_events:
            if self.notifier.notify(event) is not True:
                raise NotificationDeliveryError(
                    "Notification service did not confirm delivery"
                )
            self.store.save(event)
            delivered += 1

        return RunReport(
            initialized_now=False,
            fetched_events=len(events),
            new_events=len(new_events),
            delivered_notifications=delivered,
        )
