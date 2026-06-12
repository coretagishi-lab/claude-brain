#!/usr/bin/env python3
"""
DMM Notion Watcher: タスク確認ボードの「✅ 確認済み」[台本確認]を30秒ごとに監視。
検知したら即「🔄 作成中」に変更（再検出防止）→ Outboxに待機タスク登録。
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

ENV_FILE = Path("/opt/ai-brain/.credentials/.env")

def _load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^(\w+)="(.+)"$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)

_load_env()

NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"
TASK_BOARD_ID  = "3671cad4aa98813b85b2ed9e3127b913"
REPORTER       = "/opt/ai-brain/Shared/Workflows/vps-task-reporter.py"
INTERVAL       = 30


def notion(method, path, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def poll():
    _, res = notion("POST", f"/databases/{TASK_BOARD_ID}/query", {
        "filter": {"and": [
            {"property": "ステータス", "select": {"equals": "✅ 確認済み"}},
            {"property": "タスク名",   "title":  {"contains": "[台本確認]"}},
        ]}
    })
    items = res.get("results", [])
    for item in items:
        page_id = item["id"]
        title   = "".join(p.get("plain_text", "") for p in item["properties"]["タスク名"]["title"])
        summary = "".join(p.get("plain_text", "") for p in item["properties"].get("内容要約", {}).get("rich_text", []))

        # 即「🔄 作成中」に変更（再検出防止）
        notion("PATCH", f"/pages/{page_id}", {
            "properties": {"ステータス": {"select": {"name": "🔄 作成中"}}}
        })
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] 検知 → Outbox登録: {title}", flush=True)

        subprocess.run([
            "python3", REPORTER,
            "--title",  f"assembler実行待ち: {title}",
            "--detail", summary or "(内容要約なし)",
            "--action", "Mac Claude Code: python3 Projects/dmm-manga-affiliate/Workflows/assembler.py を実行してCanva組み立てを行う",
            "--source", "dmm-notion-watcher",
        ], timeout=15)


def main():
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN未設定", flush=True)
        sys.exit(1)
    print(f"[dmm-notion-watcher] 起動 (interval={INTERVAL}s)", flush=True)
    while True:
        try:
            poll()
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] エラー: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
