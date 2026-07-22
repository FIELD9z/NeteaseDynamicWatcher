from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from netease_dynamic_watcher.models import Event


_NOTIFICATION_STATES = {"pending", "delivered", "suppressed"}


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite