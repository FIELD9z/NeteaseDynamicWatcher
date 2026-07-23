from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


DEFAULT_EVENTS_URL_TEMPLATE = "https://music.163.com/api/event/get/{uid}"
DEFAULT_COMMENTS_URL_TEMPLATE = (
    "https://music.163.com/api/v1/resource/comments/{thread_id}"
    "?limit={limit}&offset={offset}"
)


def read_env_file(path: str | Path = ".env") -> dict[str, str]:
    """Read a small KEY=VALUE file without printing or transforming secrets."""
    file_path = Path(path)
    if not file_path.exists():
        return {}

    result: dict[str, str] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def _integer_setting(
    env: Mapping[str, str],
    key: str,
    default: int,
) -> int:
    raw_value = str(env.get(key, str(default))).strip()
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _boolean_setting(
    env: Mapping[str, str],
    key: str,
    default: bool,
) -> bool:
    raw_value = str(env.get(key, "1" if default else "0")).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean value")


def _validate_http_url(value: str, name: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{name} must be an HTTP(S) URL with a hostname")
    if parts.username or parts.password:
        raise ValueError(f"{name} must not contain credentials")


def _validate_template(value: str, name: str, required_fields: tuple[str, ...]) -> None:
    for field in required_fields:
        if "{" + field + "}" not in value:
            raise ValueError(f"{name} must contain {{{field}}}")
    sample = value
    for field, replacement in (
        ("uid", "1"),
        ("thread_id", "A_EV_2_1_1"),
        ("limit", "20"),
        ("offset", "0"),
    ):
        sample = sample.replace("{" + field + "}", replacement)
    _validate_http_url(sample, name)


@dataclass(frozen=True)
class Config:
    cookie: str = ""
    notification_key: str = ""
    target_uid: str = "1413380977"
    interval_minutes: int = 15
    database_path: str = "data/watcher.sqlite3"
    events_url_template: str = DEFAULT_EVENTS_URL_TEMPLATE
    notification_endpoint: str = "https://push.i-i.me/"
    request_timeout_seconds: int = 15
    interactions_enabled: bool = True
    comments_url_template: str = DEFAULT_COMMENTS_URL_TEMPLATE
    likers_url_template: str = ""
    interaction_page_size: int = 100
    interaction_max_pages: int = 20
    interaction_batch_size: int = 20

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ
        return cls(
            cookie=env.get("NETEASE_COOKIE", "").strip(),
            notification_key=env.get("PUSHME_KEY", "").strip(),
            target_uid=env.get("TARGET_UID", "1413380977").strip(),
            interval_minutes=_integer_setting(env, "CHECK_INTERVAL_MINUTES", 15),
            database_path=env.get("DATABASE_PATH", "data/watcher.sqlite3").strip(),
            events_url_template=env.get(
                "NETEASE_EVENTS_URL_TEMPLATE",
                DEFAULT_EVENTS_URL_TEMPLATE,
            ).strip(),
            notification_endpoint=env.get(
                "PUSH_ENDPOINT", "https://push.i-i.me/"
            ).strip(),
            request_timeout_seconds=_integer_setting(
                env,
                "REQUEST_TIMEOUT_SECONDS",
                15,
            ),
            interactions_enabled=_boolean_setting(env, "INTERACTIONS_ENABLED", True),
            comments_url_template=env.get(
                "NETEASE_EVENT_COMMENTS_URL_TEMPLATE",
                DEFAULT_COMMENTS_URL_TEMPLATE,
            ).strip(),
            likers_url_template=env.get(
                "NETEASE_EVENT_LIKERS_URL_TEMPLATE",
                "",
            ).strip(),
            interaction_page_size=_integer_setting(env, "INTERACTION_PAGE_SIZE", 100),
            interaction_max_pages=_integer_setting(env, "INTERACTION_MAX_PAGES", 20),
            interaction_batch_size=_integer_setting(env, "INTERACTION_BATCH_SIZE", 20),
        )

    @classmethod
    def from_sources(cls, env_file: str | Path = ".env") -> "Config":
        merged = read_env_file(env_file)
        merged.update(os.environ)
        return cls.from_env(merged)

    def validate_runtime(self, *, require_notification_key: bool = True) -> None:
        if not self.target_uid.isdigit():
            raise ValueError("TARGET_UID must contain digits only")
        if not self.cookie:
            raise ValueError("NETEASE_COOKIE is required")
        if require_notification_key and not self.notification_key:
            raise ValueError("PUSHME_KEY is required for notification delivery")
        if self.interval_minutes < 1:
            raise ValueError("CHECK_INTERVAL_MINUTES must be at least 1")
        if self.request_timeout_seconds < 1:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be at least 1")
        if not self.database_path:
            raise ValueError("DATABASE_PATH must not be empty")
        _validate_template(
            self.events_url_template,
            "NETEASE_EVENTS_URL_TEMPLATE",
            ("uid",),
        )
        _validate_http_url(self.notification_endpoint, "PUSH_ENDPOINT")
        if self.interactions_enabled:
            _validate_template(
                self.comments_url_template,
                "NETEASE_EVENT_COMMENTS_URL_TEMPLATE",
                ("thread_id", "limit", "offset"),
            )
            if self.likers_url_template:
                _validate_template(
                    self.likers_url_template,
                    "NETEASE_EVENT_LIKERS_URL_TEMPLATE",
                    ("thread_id", "limit", "offset"),
                )
            if self.interaction_page_size < 1:
                raise ValueError("INTERACTION_PAGE_SIZE must be at least 1")
            if self.interaction_max_pages < 1:
                raise ValueError("INTERACTION_MAX_PAGES must be at least 1")
            if self.interaction_batch_size < 1:
                raise ValueError("INTERACTION_BATCH_SIZE must be at least 1")

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_uid": self.target_uid,
            "interval_minutes": self.interval_minutes,
            "database_path": self.database_path,
            "request_timeout_seconds": self.request_timeout_seconds,
            "interactions_enabled": self.interactions_enabled,
            "interaction_batch_size": self.interaction_batch_size,
            "has_likers_endpoint": bool(self.likers_url_template),
            "has_cookie": bool(self.cookie),
            "has_notification_key": bool(self.notification_key),
        }
