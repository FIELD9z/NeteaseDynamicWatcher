from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from netease_dynamic_watcher.models import Event
from netease_dynamic_watcher.parser import parse_events
from netease_dynamic_watcher.store import StateStore


class EventClient(Protocol):
    def fetch_user_events(self, url: str, *, limit: int, lasttime: int = -1) -> dict: ...

    def iter_user_event_pages(self, url: str, *, page_size: int, max_pages: int): ...


class EventNotifier(Protocol):
    def notify(self, event: Event) -> bool: ...


@dataclass(frozen=True)
class RunReport:
    initialized_now: bool
    fetched_events: int
    new_events: int
    delivered_notifications: int = 0
    failed_notifications: int = 0
    pending_notifications: int = 0


@dataclass(frozen=True)
class DeliveryReport:
    delivered_notifications: int
    failed_notifications: int
    pending_notifications: int


class WatcherService:
    def __init__(self, client, store: StateStore, notifier, target_uid, events_url):
        self.client = client
        self.store = store
        self.notifier = notifier
        self.target_uid = target_uid
        self.events_url = events_url

    def _fetch_all_history(self) -> list[Event]:
        events_by_id: dict[str, Event] = {}
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

    def _fetch_recent_events(self) -> list[Event]:
        payload = self.client.fetch_user_events(
            self.events_url,
            limit=10,
            lasttime=-1,
        )
        events = parse_events(payload, user_id=self.target_uid)
        events.sort(key=lambda event: (event.publish_time_ms, event.event_id))
        return events

    def collect_once(self, *, backfill: bool = False) -> RunReport:
        """Fetch and commit event data without sending notifications."""

        was_initialized = self.store.is_initialized(self.target_uid)

        if backfill:
            events = self._fetch_all_history()
            self.store.save_many(events, notification_state="suppressed")
            self.store.mark_initialized(self.target_uid)
            return RunReport(
                initialized_now=not was_initialized,
                fetched_events=len(events),
                new_events=0,
                pending_notifications=self.store.pending_notification_count(
                    self.target_uid
                ),
            )

        events = self._fetch_recent_events()
        if not was_initialized:
            self.store.save_many(events, notification_state="suppressed")
            self.store.mark_initialized(self.target_uid)
            return RunReport(
                initialized_now=True,
                fetched_events=len(events),
                new_events=0,
                pending_notifications=0,
            )

        new_events = [
            event
            for event in events
            if not self.store.is_seen(self.target_uid, event.event_id)
        ]
        existing_events = [
            event
            for event in events
            if self.store.is_seen(self.target_uid, event.event_id)
        ]

        # Refresh mutable metadata such as engagement counts and raw payloads, while
        # StateStore keeps each event's first non-empty avatar snapshot unchanged.
        self.store.save_many(existing_events)
        self.store.save_many(new_events, notification_state="pending")

        return RunReport(
            initialized_now=False,
            fetched_events=len(events),
            new_events=len(new_events),
            pending_notifications=self.store.pending_notification_count(
                self.target_uid
            ),
        )

    def deliver_pending_notifications(self) -> DeliveryReport:
        delivered = 0
        failed = 0
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
                    failed += 1
            except Exception as exc:
                self.store.mark_notification_failed(
                    self.target_uid,
                    event.event_id,
                    f"{type(exc).__name__}: {exc}",
                )
                failed += 1
        return DeliveryReport(
            delivered_notifications=delivered,
            failed_notifications=failed,
            pending_notifications=self.store.pending_notification_count(
                self.target_uid
            ),
        )

    def run_once(self, *, backfill: bool = False) -> RunReport:
        """Compatibility entry point for callers that do not archive media."""

        report = self.collect_once(backfill=backfill)
        if backfill or report.initialized_now:
            return report
        delivery = self.deliver_pending_notifications()
        return replace(
            report,
            delivered_notifications=delivery.delivered_notifications,
            failed_notifications=delivery.failed_notifications,
            pending_notifications=delivery.pending_notifications,
        )
