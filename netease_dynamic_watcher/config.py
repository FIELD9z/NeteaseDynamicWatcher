from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


@dataclass(frozen=True)
class Config:
    cookie: str = ""
    notification_key: str = ""
    target_uid: str = "1413380977"
    interval_minutes: int = 15
    database_path: str = "data/watcher.sqlite3"
    events_url_template: str = "https://music.163.com/api/user/event/{uid}"
    notification_endpoint: str = "https://push.i-i.me/"
    request_timeout_seconds: int = 15

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ
        return cls(
            cookie=env.get("NETEASE_COOKIE", "").strip(),
            notification_key=env.get("PUSHME_KEY", "").strip(),
            target_uid=env.get("TARGET_UID", "1413380977").strip(),
            interval_minutes=int(env.get("CHECK_INTERVAL_MINUTES", "15")),
            database_path=env.get("DATABASE_PATH", "data/watcher.sqlite3").strip(),
            events_url_template=env.get(
                "NETEASE_EVENTS_URL_TEMPLATE",
                "https://music.163.com/api/user/event/{uid}",
            ).strip(),
            notification_endpoint=env.get(
                "PUSH_ENDPOINT", "https://push.i-i.me/"
            ).strip(),
            request_timeout_seconds=int(env.get("REQUEST_TIMEOUT_SECONDS", "15")),
        )

    def validate_runtime(self) -> None:
        if not self.target_uid.isdigit():
            raise ValueError("TARGET_UID must contain digits only")
        if not self.cookie:
            raise ValueError("NETEASE_COOKIE is required")
        if not self.notification_key:
            raise ValueError("PUSHME_KEY is required")
        if self.interval_minutes < 1:
            raise ValueError("CHECK_INTERVAL_MINUTES must be at least 1")
        if "{uid}" not in self.events_url_template:
            raise ValueError("NETEASE_EVENTS_URL_TEMPLATE must contain {uid}")

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_uid": self.target_uid,
            "interval_minutes": self.interval_minutes,
            "database_path": self.database_path,
            "has_cookie": bool(self.cookie),
            "has_notification_key": bool(self.notification_key),
        }
