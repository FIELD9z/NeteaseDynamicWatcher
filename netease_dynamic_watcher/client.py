from __future__ import annotations

import urllib.request


class NeteaseClient:
    def __init__(self, cookie: str, timeout: int = 15):
        self.cookie = cookie
        self.timeout = timeout

    def fetch_user_events(self, url: str) -> dict:
        request = urllib.request.Request(
            url,
            headers={
                "Cookie": self.cookie,
                "User-Agent": "Mozilla/5.0 NeteaseDynamicWatcher",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8")
