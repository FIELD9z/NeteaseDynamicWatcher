from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    nickname: str
    event_type: str
    summary: str
    publish_time_ms: int
    url: str

    @property
    def published_at(self) -> datetime:
        return datetime.fromtimestamp(self.publish_time_ms / 1000, tz=timezone.utc)

    def notification_title(self) -> str:
        label = "新歌曲" if self.event_type == "song_share" else "新动态"
        return f"{self.nickname} 发布了{label}"

    def notification_body(self) -> str:
        local_time = self.published_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"昵称：{self.nickname}\n"
            f"类型：{self.event_type}\n"
            f"摘要：{self.summary}\n"
            f"发布时间：{local_time}\n"
            f"链接：{self.url}"
        )
