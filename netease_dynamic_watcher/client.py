from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Callable
import urllib.parse
import urllib.request


class NeteaseClientError(RuntimeError):
    """Raised when the user-event response is unavailable or invalid."""


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
        request = urllib.request.Request(
            request_url,
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
            raise NeteaseClientError("Unable to read the user-event response") from exc

        if not isinstance(payload, dict):
            raise NeteaseClientError("Unexpected user-event response type")
        code = payload.get("code")
        if code not in (None, 200):
            raise NeteaseClientError(f"User-event request failed with code {code}")
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
