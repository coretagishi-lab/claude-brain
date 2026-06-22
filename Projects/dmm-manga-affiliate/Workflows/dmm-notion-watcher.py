#!/usr/bin/env python3
"""
DMM Notion Watcher: タスク確認ボードの「✅ 確認済み」[台本確認]を30秒ごとに監視。

検知したら:
  1. やり直し指示があればコンテンツDBのscriptを上書き
  2. コンテンツDBのstatusをapprovedに更新
  3. タスクボードのステータスを「🔄 作成中」に変更（再検出防止）
  4. Outboxに待機タスク登録（Mac Claude Codeへの通知）
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
    body = json.dumps(data, ensure_ascii=False).encode() if data else None
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


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def extract_page_id(summary):
    m = re.search(r"page_id:([0-9a-f\-]{32,36})", summary)
    if not m:
        return None
    raw = m.group(1).replace("-", "")
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def poll_task(task_type, items):
    for item in items:
        task_id    = item["id"]
        task_title = "".join(p.get("plain_text", "") for p in item["properties"]["タスク名"]["title"])
        summary    = "".join(p.get("plain_text", "") for p in item["properties"].get("内容要約", {}).get("rich_text", []))
        yarinaoshi = "".join(p.get("plain_text", "") for p in item["properties"].get("やり直し指示", {}).get("rich_text", [])).strip()

        # タスクボードを即「🔄 作成中」に変更（再検出防止）
        notion("PATCH", f"/pages/{task_id}", {
            "properties": {"ステータス": {"select": {"name": "🔄 作成中"}}}
        })

        ts = datetime.now().strftime("%H:%M:%S")

        if task_type == "台本確認":
            content_page_id = extract_page_id(summary)
            if not content_page_id:
                print(f"[{ts}] ⚠️  page_id抽出失敗: {summary[:60]}", flush=True)
                continue
            if yarinaoshi:
                notion("PATCH", f"/pages/{content_page_id}", {
                    "properties": {"script": {"rich_text": rt(yarinaoshi)}}
                })
            notion("PATCH", f"/pages/{content_page_id}", {
                "properties": {"status": {"select": {"name": "approved"}}}
            })
            has_override = " (やり直し指示あり)" if yarinaoshi else ""
            print(f"[{ts}] [台本確認] 検知 → approved更新{has_override}: {task_title}", flush=True)
            subprocess.run([
                "python3", REPORTER,
                "--title",  f"assembler実行待ち: {task_title}",
                "--detail", f"content_page_id:{content_page_id}\n{summary}",
                "--action", "Mac Claude Code: assembler.py を実行してCanva組み立てを行う",
                "--source", "dmm-notion-watcher",
            ], timeout=15)

        elif task_type == "Canva確認":
            has_override = " (やり直し指示あり)" if yarinaoshi else ""
            print(f"[{ts}] [Canva確認] 検知{has_override}: {task_title}", flush=True)
            detail = summary
            if yarinaoshi:
                detail += f"\nやり直し指示: {yarinaoshi}"
            subprocess.run([
                "python3", REPORTER,
                "--title",  f"ffmpeg動画生成待ち: {task_title}",
                "--detail", detail,
                "--action", "Mac Claude Code: Canva透過PNGエクスポート → ffmpeg動画生成 → 動画確認タスク登録",
                "--source", "dmm-notion-watcher",
            ], timeout=15)

        elif task_type == "動画確認":
            print(f"[{ts}] [動画確認] 検知: {task_title}", flush=True)
            if yarinaoshi:
                subprocess.run([
                    "python3", REPORTER,
                    "--title",  f"動画やり直し待ち: {task_title}",
                    "--detail", f"{summary}\nやり直し指示: {yarinaoshi}",
                    "--action", "Mac Claude Code: video-generator.py を再実行して動画を作り直す",
                    "--source", "dmm-notion-watcher",
                ], timeout=15)
            else:
                subprocess.run([
                    "python3", REPORTER,
                    "--title",  f"youtube投稿待ち: {task_title}",
                    "--detail", summary,
                    "--action", "Mac Claude Code: upload-scheduler.py が公開3日前に自動アップロード",
                    "--source", "dmm-notion-watcher",
                ], timeout=15)


def poll():
    for task_type in ["台本確認", "Canva確認", "動画確認"]:
        _, res = notion("POST", f"/databases/{TASK_BOARD_ID}/query", {
            "filter": {"and": [
                {"property": "ステータス", "select": {"equals": "✅ 確認済み"}},
                {"property": "タスク名",   "title":  {"contains": f"[{task_type}]"}},
            ]}
        })
        items = res.get("results", [])
        if items:
            poll_task(task_type, items)


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
