from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_watcher
from netease_dynamic_watcher.archive_view import load_archive_events
from netease_dynamic_watcher.config import Config
from netease_dynamic_watcher.models import Event
from netease_dynamic_watcher.service import WatcherService
from netease_dynamic_watcher.store import StateStore


UID = "1413380977"


def payload(*event_ids: str, avatar: str = "https://p1.music.126.net/avatar.jpg"):
    return {
        "events": [
            {
                "id": event_id,
                "eventTime": index + 1,
                "summary": f"event {event_id}",
                "user": {
                    "userId": UID,
                    "nickname": "offline-user",
                    "avatarUrl": avatar,
                },
            }
            for index, event_id in enumerate(event_ids)
        ]
    }


def make_event(event_id: str, avatar: str = "") -> Event:
    return Event(
        event_id=event_id,
        user_id=UID,
        nickname="offline-user",
        event_type="dynamic",
        summary=event_id,
        publish_time_ms=1,
        url="",
        avatar_url=avatar,
    )


class FakeClient:
    def __init__(self, recent=None, pages=None):
        self.recent = recent or {"events": []}
        self.pages = pages or []

    def fetch_user_events(self, url, *, limit, lasttime=-1):
        return self.recent

    def iter_user_event_pages(self, url, *, page_size, max_pages):
        yield from self.pages


class RecordingNotifier:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.events: list[str] = []

    def notify(self, event):
        self.events.append(event.event_id)
        if not self.outcomes:
            return True
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class WatcherBusinessFlowTests(unittest.TestCase):
    def service(self, database: Path, client, notifier):
        return WatcherService(
            client=client,
            store=StateStore(str(database)),
            notifier=notifier,
            target_uid=UID,
            events_url="https://music.163.com/offline-test",
        )

    def test_first_run_establishes_baseline_without_notification(self):
        with tempfile.TemporaryDirectory() as temp:
            notifier = RecordingNotifier()
            service = self.service(
                Path(temp) / "watcher.sqlite3",
                FakeClient(recent=payload("baseline")),
                notifier,
            )

            report = service.run_once()

            self.assertTrue(report.initialized_now)
            self.assertEqual(report.new_events, 0)
            self.assertEqual(notifier.events, [])
            self.assertEqual(
                service.store.get_notification_state(UID, "baseline"),
                "suppressed",
            )

    def test_backfill_never_notifies_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            notifier = RecordingNotifier()
            service = self.service(
                database,
                FakeClient(pages=[payload("old-1", "old-2"), payload("old-2")]),
                notifier,
            )

            first = service.run_once(backfill=True)
            second = service.run_once(backfill=True)

            self.assertEqual((first.new_events, second.new_events), (0, 0))
            self.assertEqual(notifier.events, [])
            self.assertEqual(len(load_archive_events(database)), 2)
            self.assertEqual(
                service.store.get_notification_state(UID, "old-1"),
                "suppressed",
            )

    def test_new_event_transitions_from_pending_to_delivered(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            notifier = RecordingNotifier()
            service = self.service(database, FakeClient(recent=payload("base")), notifier)
            service.run_once()
            service.client.recent = payload("base", "new")

            collected = service.collect_once()

            self.assertEqual(collected.new_events, 1)
            self.assertEqual(collected.pending_notifications, 1)
            self.assertEqual(service.store.get_notification_state(UID, "new"), "pending")

            delivered = service.deliver_pending_notifications()

            self.assertEqual(delivered.delivered_notifications, 1)
            self.assertEqual(delivered.pending_notifications, 0)
            self.assertEqual(service.store.get_notification_state(UID, "new"), "delivered")

    def test_notification_failure_stays_pending_then_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            notifier = RecordingNotifier([RuntimeError("offline failure"), True])
            service = self.service(database, FakeClient(recent=payload("base")), notifier)
            service.run_once()
            service.client.recent = payload("base", "retry")

            failed = service.run_once()
            retried = service.run_once()

            self.assertEqual(failed.failed_notifications, 1)
            self.assertEqual(failed.pending_notifications, 1)
            self.assertEqual(retried.delivered_notifications, 1)
            self.assertEqual(retried.pending_notifications, 0)
            self.assertEqual(
                service.store.get_notification_state(UID, "retry"),
                "delivered",
            )

    def test_old_database_events_migrate_to_suppressed(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE events(
                        user_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(user_id, event_id)
                    )
                    """
                )
                connection.execute(
                    "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO events(user_id, event_id, payload) VALUES (?, ?, ?)",
                    (UID, "legacy", StateStore._serialize(make_event("legacy"))),
                )
                connection.commit()
            finally:
                connection.close()

            store = StateStore(str(database))

            self.assertEqual(store.get_notification_state(UID, "legacy"), "suppressed")

    def test_existing_event_avatar_snapshot_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            store = StateStore(str(database))
            store.save(make_event("same", "https://p1.music.126.net/old.jpg"))
            store.save(make_event("same", "https://p1.music.126.net/new.jpg"))

            [saved] = load_archive_events(database)

            self.assertEqual(saved["avatar_url"], "https://p1.music.126.net/old.jpg")

    def test_new_event_can_store_new_avatar_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            store = StateStore(str(database))
            store.save(make_event("old", "https://p1.music.126.net/old.jpg"))
            store.save(make_event("new", "https://p1.music.126.net/new.jpg"))

            saved = {event["event_id"]: event for event in load_archive_events(database)}

            self.assertEqual(saved["old"]["avatar_url"], "https://p1.music.126.net/old.jpg")
            self.assertEqual(saved["new"]["avatar_url"], "https://p1.music.126.net/new.jpg")

    def test_media_archive_failure_does_not_lose_committed_event(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            config = Config(
                cookie="offline-placeholder",
                notification_key="offline-placeholder",
                target_uid=UID,
                database_path=str(database),
                request_timeout_seconds=1,
            )

            class RunClient(FakeClient):
                def __init__(self, cookie, timeout):
                    super().__init__(recent=payload("durable"))

            with (
                mock.patch.object(Config, "from_sources", return_value=config),
                mock.patch("netease_dynamic_watcher.client.NeteaseClient", RunClient),
                mock.patch(
                    "netease_dynamic_watcher.media_archive.archive_database_media",
                    side_effect=RuntimeError("mocked archive failure"),
                ),
                mock.patch.object(run_watcher, "configure_logging"),
                mock.patch.object(run_watcher, "write_runtime_status"),
            ):
                report = run_watcher.run_once()

            self.assertTrue(report.initialized_now)
            self.assertEqual(
                [event["event_id"] for event in load_archive_events(database)],
                ["durable"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
