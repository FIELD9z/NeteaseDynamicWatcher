from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from netease_dynamic_watcher.archive_view import load_archive_events, write_archive_html
from netease_dynamic_watcher.interaction_export import (
    load_interaction_snapshot,
    write_interaction_assets,
)
from netease_dynamic_watcher.interaction_refresh import (
    InteractionRefresher,
    failure_backoff,
    refresh_interval,
)
from netease_dynamic_watcher.interaction_store import InteractionStore
from netease_dynamic_watcher.interactions import parse_comment_pages, parse_liker_pages
from netease_dynamic_watcher.models import Event
from netease_dynamic_watcher.store import StateStore


UID = "1413380977"
NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def event(event_id: str, *, age: timedelta = timedelta(hours=1)) -> Event:
    published = NOW - age
    return Event(
        event_id=event_id,
        user_id=UID,
        nickname="target",
        event_type="dynamic",
        summary=f"event {event_id}",
        publish_time_ms=int(published.timestamp() * 1000),
        url=f"https://music.163.com/#/event?id={event_id}",
        comment_count=1,
        liked_count=2,
        comment_thread_id=f"A_EV_2_{event_id}",
    )


class FakeInteractionClient:
    def __init__(self, *, fail_comments: bool = False):
        self.fail_comments = fail_comments
        self.comment_calls: list[str] = []
        self.liker_calls: list[str] = []

    def iter_event_comment_pages(
        self,
        template,
        *,
        thread_id,
        page_size,
        max_pages,
    ):
        self.comment_calls.append(thread_id)
        if self.fail_comments:
            raise RuntimeError("offline comment failure")
        yield {
            "code": 200,
            "total": 1,
            "comments": [
                {
                    "commentId": f"comment-{thread_id}",
                    "content": "离线评论",
                    "time": int(NOW.timestamp() * 1000),
                    "likedCount": 3,
                    "user": {
                        "userId": "1001",
                        "nickname": "评论用户",
                        "avatarUrl": "https://p1.music.126.net/not-downloaded.jpg",
                    },
                    "beReplied": [
                        {
                            "content": "离线回复",
                            "user": {"userId": "1002", "nickname": "回复用户"},
                        }
                    ],
                }
            ],
            "more": False,
        }

    def iter_event_liker_pages(
        self,
        template,
        *,
        thread_id,
        page_size,
        max_pages,
    ):
        self.liker_calls.append(thread_id)
        yield {
            "code": 200,
            "total": 2,
            "users": [
                {"userId": "2001", "nickname": "点赞甲"},
                {"userId": "2002", "nickname": "点赞乙"},
            ],
            "more": False,
        }


class InteractionFeatureTests(unittest.TestCase):
    def test_refresh_schedule_is_layered_and_backoff_is_capped(self):
        self.assertEqual(refresh_interval(int((NOW - timedelta(days=1)).timestamp() * 1000), NOW), timedelta(hours=1))
        self.assertEqual(refresh_interval(int((NOW - timedelta(days=4)).timestamp() * 1000), NOW), timedelta(hours=6))
        self.assertEqual(refresh_interval(int((NOW - timedelta(days=20)).timestamp() * 1000), NOW), timedelta(days=1))
        self.assertEqual(refresh_interval(int((NOW - timedelta(days=100)).timestamp() * 1000), NOW), timedelta(days=7))
        self.assertEqual(failure_backoff(0), timedelta(hours=1))
        self.assertEqual(failure_backoff(1), timedelta(hours=2))
        self.assertEqual(failure_backoff(20), timedelta(days=7))

    def test_parser_normalizes_comments_replies_likers_and_profile_links(self):
        comment_pages = [
            {
                "hotComments": [
                    {
                        "commentId": "c1",
                        "content": "hello",
                        "user": {"userId": 11, "nickname": "A"},
                    }
                ],
                "comments": [
                    {
                        "commentId": "c1",
                        "content": "hello",
                        "user": {"userId": 11, "nickname": "A"},
                    },
                    {
                        "commentId": "c2",
                        "content": "world",
                        "user": {"userId": 12, "nickname": "B"},
                        "beReplied": [
                            {
                                "content": "reply",
                                "user": {"userId": 13, "nickname": "C"},
                            }
                        ],
                    },
                ],
            }
        ]
        comments = parse_comment_pages(comment_pages)
        likers = parse_liker_pages(
            [
                {
                    "users": [
                        {"userId": 21, "nickname": "L"},
                        {"userId": 21, "nickname": "L"},
                    ]
                }
            ]
        )
        self.assertEqual([item["comment_id"] for item in comments], ["c1", "c2"])
        self.assertTrue(comments[0]["hot"])
        self.assertEqual(comments[1]["replies"][0]["content"], "reply")
        self.assertEqual(comments[1]["user"]["profile_url"], "https://music.163.com/#/user/home?id=12")
        self.assertEqual(len(likers), 1)
        self.assertEqual(likers[0]["profile_url"], "https://music.163.com/#/user/home?id=21")

    def test_due_refresh_respects_batch_limit_and_never_changes_notifications(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            state = StateStore(database)
            for index in range(3):
                state.save(event(f"event-{index}"), notification_state="pending")
            interactions = InteractionStore(database)
            client = FakeInteractionClient()
            refresher = InteractionRefresher(
                client=client,
                store=interactions,
                target_uid=UID,
                comments_url_template="https://music.163.com/comments/{thread_id}?limit={limit}&offset={offset}",
                likers_url_template="https://music.163.com/likers/{thread_id}?limit={limit}&offset={offset}",
                page_size=100,
                max_pages=5,
                clock=lambda: NOW,
            )

            report = refresher.refresh_due(limit=2)

            self.assertEqual(report.selected_events, 2)
            self.assertEqual(report.refreshed_events, 2)
            self.assertEqual(report.comments_saved, 2)
            self.assertEqual(report.likers_saved, 4)
            self.assertEqual(report.remaining_due, 1)
            self.assertEqual(len(client.comment_calls), 2)
            self.assertEqual(len(client.liker_calls), 2)
            for index in range(3):
                self.assertEqual(
                    state.get_notification_state(UID, f"event-{index}"),
                    "pending",
                )

    def test_interaction_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "watcher.sqlite3"
            state = StateStore(database)
            state.save(event("failure"), notification_state="suppressed")
            interactions = InteractionStore(database)
            interactions.replace_comments(
                UID,
                "failure",
                [
                    {
                        "comment_id": "old",
                        "content": "保留内容",
                        "user": {"user_id": "1", "nickname": "旧用户"},
                        "replies": [],
                    }
                ],
            )
            refresher = InteractionRefresher(
                client=FakeInteractionClient(fail_comments=True),
                store=interactions,
                target_uid=UID,
                comments_url_template="https://music.163.com/comments/{thread_id}?limit={limit}&offset={offset}",
                likers_url_template="",
                page_size=100,
                max_pages=5,
                clock=lambda: NOW,
            )

            report = refresher.refresh_due(limit=1)
            snapshot = interactions.load_for_events(((UID, "failure"),))[(UID, "failure")]

            self.assertEqual(report.failed_events, 1)
            self.assertEqual(snapshot["comments"][0]["content"], "保留内容")
            self.assertEqual(snapshot["interaction_state"]["comments_status"], "failed")
            self.assertEqual(snapshot["interaction_state"]["failure_count"], 1)
            self.assertEqual(state.get_notification_state(UID, "failure"), "suppressed")

    def test_static_archive_exports_interactions_without_avatar_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "watcher.sqlite3"
            state = StateStore(database)
            state.save(event("archive"), notification_state="suppressed")
            interactions = InteractionStore(database)
            interactions.replace_comments(
                UID,
                "archive",
                [
                    {
                        "comment_id": "c1",
                        "content": "应出现在静态数据中",
                        "time_ms": int(NOW.timestamp() * 1000),
                        "liked_count": 5,
                        "user": {
                            "user_id": "31",
                            "nickname": "静态评论者",
                            "avatar_url": "https://p1.music.126.net/remote-avatar.jpg",
                            "profile_url": "https://music.163.com/#/user/home?id=31",
                        },
                        "replies": [],
                    }
                ],
            )
            interactions.replace_likers(
                UID,
                "archive",
                [
                    {
                        "user_id": "32",
                        "nickname": "静态点赞者",
                        "avatar_url": "https://p1.music.126.net/remote-liker.jpg",
                        "profile_url": "https://music.163.com/#/user/home?id=32",
                    }
                ],
            )
            interactions.record_refresh(
                UID,
                "archive",
                next_refresh_at=(NOW + timedelta(hours=1)).isoformat(),
                comments_status="success",
                likers_status="success",
                comment_total=1,
                liker_total=1,
                success=True,
            )
            output = root / "export" / "events.html"
            write_archive_html(load_archive_events(database), output)
            write_interaction_assets(database, output)

            html = output.read_text(encoding="utf-8")
            data = (output.parent / "assets" / "interactions-data.js").read_text(
                encoding="utf-8"
            )
            snapshot = load_interaction_snapshot(database)

            self.assertIn("assets/interaction-ui.css", html)
            self.assertIn("assets/interactions-data.js", html)
            self.assertIn("assets/interaction-ui.js", html)
            self.assertIn("应出现在静态数据中", data)
            self.assertIn("静态点赞者", data)
            self.assertNotIn("avatar_url", data)
            self.assertNotIn("remote-avatar", data)
            self.assertNotIn("interaction_avatar", data)
            self.assertNotIn("avatar_url", json.dumps(snapshot, ensure_ascii=False))
            self.assertTrue((output.parent / "assets" / "interaction-ui.css").exists())
            self.assertTrue((output.parent / "assets" / "interaction-ui.js").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
