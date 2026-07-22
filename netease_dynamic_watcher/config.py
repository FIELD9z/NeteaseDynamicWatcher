from dataclasses import dataclass
import os


@dataclass
class Config:
    cookie: str = ""
    push_key: str = ""
    target_uid: str = "1413380977"
    interval_minutes: int = 15
    database_path: str = "data/watcher.sqlite3"

    @classmethod
    def from_env(cls):
        return cls(
            cookie=os.getenv("NETEASE_COOKIE", ""),
            push_key=os.getenv("PUSHME_KEY", ""),
            target_uid=os.getenv("TARGET_UID", "1413380977"),
            interval_minutes=int(os.getenv("CHECK_INTERVAL_MINUTES", "15")),
            database_path=os.getenv("DATABASE_PATH", "data/watcher.sqlite3"),
        )

    def safe_summary(self):
        return {
            "target_uid": self.target_uid,
            "has_cookie": bool(self.cookie),
            "has_push_key": bool(self.push_key),
        }
