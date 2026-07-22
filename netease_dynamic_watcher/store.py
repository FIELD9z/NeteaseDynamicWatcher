import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Event:
    event_id: str
    event_type: str
    summary: str
    publish_time: int
    url: str


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT)")

    def is_seen(self, event_id: str) -> bool:
        with sqlite3.connect(self.path) as conn:
            return conn.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is not None

    def save(self, event: Event):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT OR IGNORE INTO events VALUES (?, ?)", (event.event_id, json.dumps(event.__dict__, ensure_ascii=False)))
