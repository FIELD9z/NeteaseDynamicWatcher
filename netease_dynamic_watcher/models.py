from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    nickname: str
    event_type: str
    summary: str
    publish_time_ms: int
    url: str
    raw_type: str = ""
    avatar_url: str = ""
    image_urls: tuple[str, ...] = ()
    video_urls: tuple[str, ...] = ()
    forwarded_event_id: str = ""
    forwarded_summary: str = ""
    comment_count: int = 0
    share_count: int = 0
    liked_count: int = 0
    comment_thread_id: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def published_at(self) -> datetime:
        return datetime.fromtimestamp(self.publish_time_ms / 1000, tz=timezone.utc)

    def notification_title(self) -> str:
        label = "新歌曲" if self.event_type == "song_share" else "新动态"
        return f"{self.nickname} 发布了{label}"

    def notification_body(self) -> str:
        local_time = self.published_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        details = [
            f"昵称：{self.nickname}",
            f"类型：{self.event_type}",
            f"摘要：{self.summary}",
        ]
        if self.image_urls:
            details.append(f"图片：{len(self.image_urls)} 张")
        if self.video_urls:
            details.append(f"视频资源：{len(self.video_urls)} 个")
        if self.forwarded_event_id or self.forwarded_summary:
            details.append(f"转发内容：{self.forwarded_summary or self.forwarded_event_id}")
        details.extend(
            [
                f"发布时间：{local_time}",
                f"链接：{self.url}",
            ]
        )
        return "\n".join(details)
