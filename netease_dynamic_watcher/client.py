from __future__ import annotations

from collections.abc import Iterator
import json
from typing import Any, Callable
import urllib.parse
import urllib.request


class NeteaseClientError(RuntimeError):
    """Raised when a NetEase response is unavailable or invalid."""


class NeteaseClient:
    def __init__(
        self,
        cookie: str,
        timeout: int = 15,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._cookie = cookie
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen

    @staticmethod
    def _with_query(url: str, **parameters: object) -> str:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        query.update({key: str(value) for key, value in parameters.items()})
        return urllib.parse.urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urllib.parse.urlencode(query),
                parts.fragment,
            )
        )

    def _request_json(self, url: str, *, context: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Cookie": self._cookie,
                "Referer": "https://music.163.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NeteaseClientError(f"Unable to read {context} response") from exc

        if not isinstance(payload, dict):
            raise NeteaseClientError(f"Unexpected {context} response type")
        code = payload.get("code")
        if code not in (None, 200):
            raise NeteaseClientError(f"{context} request failed with code {code}")
        return payload

    def fetch_user_events(
        self,
        url: str,
        *,
        limit: int,
        lasttime: int = -1,
    ) -> dict[str, Any]:
        # The public wrapper calls this argument ``lasttime``, but the direct
        # NetEase endpoint expects the underlying query field to be ``time``.
        request_url = self._with_query(url, limit=limit, time=lasttime)
        payload = self._request_json(request_url, context="user-event")
        if "events" not in payload and "event" not in payload:
            raise NeteaseClientError("User-event response contains no event collection")
        return payload

    def iter_user_event_pages(
        self,
        url: str,
        *,
        page_size: int,
        max_pages: int,
    ) -> Iterator[dict[str, Any]]:
        """Yield event pages until NetEase reports that no older page remains."""
        cursor = -1
        seen_cursors: set[int] = set()

        for _ in range(max_pages):
            payload = self.fetch_user_events(
                url,
                limit=page_size,
                lasttime=cursor,
            )
            yield payload

            raw_events = payload.get("events", payload.get("event", []))
            if not isinstance(raw_events, list) or not raw_events:
                return
            if not bool(payload.get("more")):
                return

            next_cursor_value = payload.get("lasttime")
            try:
                next_cursor = int(next_cursor_value)
            except (TypeError, ValueError) as exc:
                raise NeteaseClientError(
                    "User-event response has no valid pagination cursor"
                ) from exc
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise NeteaseClientError("User-event pagination cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        raise NeteaseClientError("User-event pagination exceeded the safety limit")

    @staticmethod
    def _format_interaction_url(
        template: str,
        *,
        thread_id: str,
        limit: int,
        offset: int,
    ) -> str:
        try:
            return template.format(
                thread_id=urllib.parse.quote(thread_id, safe=""),
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise NeteaseClientError(
                f"Interaction URL template contains an unsupported placeholder: {exc}"
            ) from exc

    @staticmethod
    def _collection(payload: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
        for source in (
            payload,
            payload.get("data") if isinstance(payload.get("data"), dict) else {},
        ):
            for key in keys:
                value = source.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _more(payload: dict[str, Any], *, offset: int, page_size: int, count: int) -> bool:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        for source in (payload, data):
            for key in ("more", "hasMore", "has_more"):
                if key in source:
                    return bool(source.get(key))
            try:
                total = int(source.get("total") or source.get("count") or 0)
            except (TypeError, ValueError):
                total = 0
            if total > 0:
                return offset + count < total
        return count >= page_size

    def iter_event_comment_pages(
        self,
        template: str,
        *,
        thread_id: str,
        page_size: int,
        max_pages: int,
    ) -> Iterator[dict[str, Any]]:
        """Yield comment pages from the direct event-comment endpoint.

        The endpoint is reverse-engineered and may change. Callers must treat a
        failure as an interaction-only degradation rather than an event failure.
        """
        offset = 0
        for _ in range(max(max_pages, 1)):
            url = self._format_interaction_url(
                template,
                thread_id=thread_id,
                limit=max(page_size, 1),
                offset=offset,
            )
            payload = self._request_json(url, context="event-comment")
            yield payload
            values = self._collection(payload, ("comments", "hotComments", "hot_comments"))
            if not self._more(
                payload,
                offset=offset,
                page_size=max(page_size, 1),
                count=len(values),
            ):
                return
            if not values:
                return
            offset += len(values)
        raise NeteaseClientError("Event-comment pagination exceeded the safety limit")

    def iter_event_liker_pages(
        self,
        template: str,
        *,
        thread_id: str,
        page_size: int,
        max_pages: int,
    ) -> Iterator[dict[str, Any]]:
        """Yield event liker pages when the configured endpoint is available.

        NetEase does not publish this interface. Keeping the URL configurable lets
        a local installation adapt without changing storage or UI code.
        """
        if not template.strip():
            return
        offset = 0
        for _ in range(max(max_pages, 1)):
            url = self._format_interaction_url(
                template,
                thread_id=thread_id,
                limit=max(page_size, 1),
                offset=offset,
            )
            payload = self._request_json(url, context="event-liker")
            yield payload
            values = self._collection(
                payload,
                ("likers", "users", "likedUsers", "liked_users"),
            )
            if not self._more(
                payload,
                offset=offset,
                page_size=max(page_size, 1),
                count=len(values),
            ):
                return
            if not values:
                return
            offset += len(values)
        raise NeteaseClientError("Event-liker pagination exceeded the safety limit")
