from __future__ import annotations

import argparse
import html
import json
import webbrowser
from pathlib import Path

from netease_dynamic_watcher.runtime_state import collect_runtime_summary


def render(summary: dict) -> str:
    database = summary.get("database", {})
    runtime = summary.get("runtime", {})
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>NeteaseDynamicWatcher 状态</title>
<style>
body {{ max-width:900px; margin:40px auto; font-family:system-ui; line-height:1.6; }}
.card {{ border:1px solid #8885; border-radius:12px; padding:16px; margin:16px 0; }}
pre {{ white-space:pre-wrap; }}
</style>
<h1>网易云动态监控状态</h1>
<div class="card">
<h2>数据库</h2>
<pre>{html.escape(json.dumps(database, ensure_ascii=False, indent=2))}</pre>
</div>
<div class="card">
<h2>最近运行</h2>
<pre>{html.escape(json.dumps(runtime, ensure_ascii=False, indent=2))}</pre>
</div>
<div class="card">
<h2>文件</h2>
<pre>{html.escape(json.dumps({k:v for k,v in summary.items() if k not in {'database','runtime'}}, ensure_ascii=False, indent=2))}</pre>
</div>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="打开本地监控状态页面")
    parser.add_argument("--database", default="data/watcher.sqlite3")
    parser.add_argument("--output", default="data/status.html")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render(collect_runtime_summary(args.database)),
        encoding="utf-8",
    )
    print(output.resolve())
    if not args.no_browser:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
