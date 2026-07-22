from __future__ import annotations

from dataclasses import dataclass

from netease_dynamic_watcher.parser import parse_events
from netease_dynamic_watcher.store import StateStore


class EventClient:
    def fetch_user_events(self, url: str, *, limit: int, lasttime: int = -1) -> dict: ...

    def iter_user_event_pages(self, url: str, *, page_size: int, max_pages: int): ...


class EventNotifier:
    def notify(self, event) -> bool: ...


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

    def _fetch_all_history(self) -> list:
        events_by_id = {}
        for payload in self.client.iter_user_event_pages(
            self.events_url,
            page_size=100,
            max_pages=1000,
        ):
            for event in parse_events(payload, user_id=self.target_uid):
                events_by_id[event.event_id] = event
        events = list(events_by_id.values())
        events.sort(key=lambda event: (event.publish_time_ms, event.event_id))
        return events

    def _fetch_recent_events(self) -> list:
        payload = self.client.fetch_user_events(
            self.events_url,
            limit=10,
            lasttime=-1,
        )
        events = parse_events(payload, user_id=self.target_uid)
        events.sort(key=lambda event: (event.publish_time_ms, event.event_id))
        return events

    def _deliver_pending(self) -> int:
        delivered = 0
        for event in self.store.get_pending_events(self.target_uid):
            try:
                if self.notifier.notify(event) is True:
                    self.store.mark_notification_delivered(
                        self.target_uid,
                        event.event_id,
                    )
                    delivered += 1
                else:
                    self.store.mark_notification_failed(
                        self.target_uid,
                        event.event_id,
                        "notification returned false",
                    )
            except Exception as exc:
                self.store.mark_notification_failed(
                    self.target_uid,
                    event.event_id,
                    f"{type(exc).__name__}: {exc}",
                )
        return delivered

    def run_once(self, *, backfill: bool = False) -> RunReport:
        was_initialized = self.store.is_initialized(self.target_uid)

        if backfill:
            events = self._fetch_all_history()
            self.store.save_many(events, notification_state="suppressed")
            self.store.mark_initialized(self.target_uid)
            return RunReport(
                initialized_now=not was_initialized,
                fetched_events=len(events),
                new_events=0,
                delivered_notifications=0,
            )

        events = self._fetch_recent_events()
        if not was_initialized:
            self.store.save_many(events, notification_state="suppressed")
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

        self.store.save_many(new_events, notification_state="pending")
        delivered = self._deliver_pending()

        return RunReport(
            initialized_now=False,
            fetched_events=len(events),
            new_events=len(new_events),
            delivered_notifications=delivered,
        )
