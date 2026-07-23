from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from netease_dynamic_watcher.interaction_store import InteractionStore
from netease_dynamic_watcher.interactions import (
    interaction_total,
    parse_comment_pages,
    parse_liker_pages,
)


@dataclass(frozen=True)
class InteractionRefreshReport:
    selected_events: int
    refreshed_events: int
    failed_events: int
    skipped_events: int
    comments_saved: int
    likers_saved: int
    remaining_due: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def refresh_interval(publish_time_ms: int, now: datetime) -> timedelta:
    try:
        published = datetime.fromtimestamp(int(publish_time_ms) / 1000, tz=timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError):
        return timedelta(days=7)
    age = max(now - published, timedelta())
    if age <= timedelta(days=3):
        return timedelta(hours=1)
    if age <= timedelta(days=14):
        return timedelta(hours=6)
    if age <= timedelta(days=90):
        return timedelta(days=1)
    return timedelta(days=7)


def failure_backoff(failure_count: int) -> timedelta:
    hours = min(2 ** max(int(failure_count), 0), 24 * 7)
    return timedelta(hours=max(hours, 1))


class InteractionRefresher:
    def __init__(
        self,
        *,
        client,
        store: InteractionStore,
        target_uid: str,
        comments_url_template: str,
        likers_url_template: str,
        page_size: int,
        max_pages: int,
        clock=utc_now,
    ) -> None:
        self.client = client
        self.store = store
        self.target_uid = str(target_uid)
        self.comments_url_template = str(comments_url_template or "")
        self.likers_url_template = str(likers_url_template or "")
        self.page_size = max(int(page_size), 1)
        self.max_pages = max(int(max_pages), 1)
        self.clock = clock

    def _next_refresh(
        self,
        event: dict[str, Any],
        *,
        now: datetime,
        success: bool,
    ) -> str:
        if success:
            interval = refresh_interval(int(event.get("publish_time_ms") or 0), now)
        else:
            state = event.get("_interaction_state")
            state = state if isinstance(state, dict) else {}
            interval = failure_backoff(int(state.get("failure_count") or 0) + 1)
        return (now + interval).isoformat()

    def _refresh_event(self, event: dict[str, Any], now: datetime) -> tuple[bool, int, int, bool]:
        event_id = str(event.get("event_id") or "").strip()
        thread_id = str(event.get("comment_thread_id") or "").strip()
        comment_total = max(int(event.get("comment_count") or 0), 0)
        liker_total = max(int(event.get("liked_count") or 0), 0)
        if not event_id or not thread_id:
            self.store.record_refresh(
                self.target_uid,
                event_id or "unknown",
                next_refresh_at=self._next_refresh(event, now=now, success=True),
                comments_status="unavailable",
                likers_status="unavailable",
                comment_total=comment_total,
                liker_total=liker_total,
                error="event has no comment_thread_id",
                success=True,
            )
            return True, 0, 0, True

        comments_status = "unsupported"
        likers_status = "unsupported"
        comments_saved = 0
        likers_saved = 0
        errors: list[str] = []

        if self.comments_url_template:
            try:
                pages = list(
                    self.client.iter_event_comment_pages(
                        self.comments_url_template,
                        thread_id=thread_id,
                        page_size=self.page_size,
                        max_pages=self.max_pages,
                    )
                )
                comments = parse_comment_pages(pages)
                self.store.replace_comments(self.target_uid, event_id, comments)
                comments_saved = len(comments)
                comment_total = interaction_total(pages, fallback=comment_total)
                comments_status = "success"
            except Exception as exc:
                comments_status = "failed"
                errors.append(f"comments {type(exc).__name__}: {exc}")

        if self.likers_url_template:
            try:
                pages = list(
                    self.client.iter_event_liker_pages(
                        self.likers_url_template,
                        thread_id=thread_id,
                        page_size=self.page_size,
                        max_pages=self.max_pages,
                    )
                )
                likers = parse_liker_pages(pages)
                self.store.replace_likers(self.target_uid, event_id, likers)
                likers_saved = len(likers)
                liker_total = interaction_total(pages, fallback=liker_total)
                likers_status = "success"
            except Exception as exc:
                likers_status = "failed"
                errors.append(f"likers {type(exc).__name__}: {exc}")

        success = comments_status in {"success", "unsupported"} and likers_status in {
            "success",
            "unsupported",
        }
        self.store.record_refresh(
            self.target_uid,
            event_id,
            next_refresh_at=self._next_refresh(event, now=now, success=success),
            comments_status=comments_status,
            likers_status=likers_status,
            comment_total=comment_total,
            liker_total=liker_total,
            error="; ".join(errors),
            success=success,
        )
        return success, comments_saved, likers_saved, False

    def refresh_due(
        self,
        *,
        limit: int,
        force: bool = False,
    ) -> InteractionRefreshReport:
        now = self.clock()
        now_iso = now.isoformat()
        events = self.store.due_events(
            self.target_uid,
            now=now_iso,
            limit=limit,
            force=force,
        )
        refreshed = 0
        failed = 0
        skipped = 0
        comments_saved = 0
        likers_saved = 0
        for event in events:
            success, comment_count, liker_count, was_skipped = self._refresh_event(event, now)
            comments_saved += comment_count
            likers_saved += liker_count
            if was_skipped:
                skipped += 1
            elif success:
                refreshed += 1
            else:
                failed += 1

        return InteractionRefreshReport(
            selected_events=len(events),
            refreshed_events=refreshed,
            failed_events=failed,
            skipped_events=skipped,
            comments_saved=comments_saved,
            likers_saved=likers_saved,
            remaining_due=self.store.due_count(self.target_uid, now=now_iso),
        )
