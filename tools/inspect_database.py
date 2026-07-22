from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter


path = sys.argv[1] if len(sys.argv) > 1 else "data/watcher.sqlite3"

with sqlite3.connect(path) as conn:
    rows = conn.execute("SELECT payload FROM events").fetchall()

stats = Counter()
for (payload,) in rows:
    event = json.loads(payload)
    stats["total"] += 1
    stats[event.get("event_type", "unknown")] += 1
    if event.get("image_urls"):
        stats["with_images"] += 1
    if event.get("video_urls"):
        stats["with_videos"] += 1
    if event.get("forwarded_event_id") or event.get("forwarded_summary"):
        stats["with_forwards"] += 1

print("动态总数:", stats["total"])
print("类型:", dict(stats))

for payload, in rows[:3]:
    print(json.dumps(json.loads(payload), ensure_ascii=False, indent=2)[:2000])
    print("-" * 50)
