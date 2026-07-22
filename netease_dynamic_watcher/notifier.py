from __future__ import annotations

import urllib.parse
import urllib.request


class PushMeNotifier:
    def __init__(self, key: str, endpoint: str = "https://push.i-i.me/"):
        self.key = key
        self.endpoint = endpoint

    def send(self, title: str, body: str) -> bool:
        if not self.key:
            raise ValueError("Push key is required")

        data = urllib.parse.urlencode(
            {
                "push_key": self.key,
                "title": title,
                "content": body,
            }
        ).encode("utf-8")

        request = urllib.request.Request(self.endpoint, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200


class PushNotifier:
    def __init__(self, sender):
        self.sender = sender

    def notify(self, event):
        return self.sender(event.notification_title(), event.notification_body())


class NullNotifier:
    def notify(self, event):
        return True
