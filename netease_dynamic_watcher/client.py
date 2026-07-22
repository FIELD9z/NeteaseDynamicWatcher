from __future__ import annotations

import json
from typing import Any, Callable
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

    def fetch_user_events(self, url: str) -> dict[str, Any]:
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
            raise NeteaseClientError("Unable to read the user-event response") from exc

        if not isinstance(payload, dict):
            raise NeteaseClientError("Unexpected user-event response type")
        code = payload.get("code")
        if code not in (None, 200):
            raise NeteaseClientError(f"User-event request failed with code {code}")
        if "events" not in payload and "event" not in payload:
            raise NeteaseClientError("User-event response contains no event collection")
        return payload
