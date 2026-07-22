from __future__ import annotations

from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request


class PushMeError(RuntimeError):
    """Raised when the PushMe request cannot be completed."""


class PushMeNotifier:
    def __init__(
        self,
        key: str,
        endpoint: str = "https://push.i-i.me/",
        timeout: int = 15,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._key = key
        self._endpoint = endpoint
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def send(self, title: str, body: str) -> bool:
        if not self._key:
            raise ValueError("Push key is required")

        data = urllib.parse.urlencode(
            {
                "push_key": self._key,
                "title": title,
                "content": body,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with self._opener(request, timeout=self._timeout) as response:
                status = int(getattr(response, "status", 0))
                result = response.read().decode("utf-8", errors="replace").strip()
        except (OSError, urllib.error.URLError) as exc:
            raise PushMeError("PushMe request failed") from exc

        return 200 <= status < 300 and result.lower() == "success"


class PushNotifier:
    def __init__(self, sender: Callable[[str, str], bool]) -> None:
        self._sender = sender

    def notify(self, event) -> bool:
        return self._sender(event.notification_title(), event.notification_body())


class NullNotifier:
    def notify(self, event) -> bool:
        return True
