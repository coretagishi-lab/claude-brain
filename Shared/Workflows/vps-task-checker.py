#!/usr/bin/env python3
"""
VPS Task Checker: Notion の VPS待機タスクを確認・処理する (Mac Claude Code 用)

セッション開始時に自動実行される。待機タスクがあれば一覧を出力する。

使い方:
  python3 vps-task-checker.py                        # 待機タスク一覧（件数のみ）
  python3 vps-task-checker.py --detail               # タスクの詳細内容も表示
  python3 vps-task-checker.py --complete PAGE_ID \   # タスクを解決済みにする
    --resolution "解決内容"
"""
import argparse, json, os, sys, urllib.request, urllib.error
from datetime import datetime

NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"
OUTBOX_DB_ID   = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"


def _notion(method: str, path: str, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get_pending_tasks() -> list:
    s, res = _notion("POST", f"/databases/{OUTBOX_DB_ID}/query", {
        "filter": {"and": [
            {"property": "type",   "select": {"equals": "vps-task"}},
            {"property": "status", "select": {"equals": "pending"}},
        ]},
        "sorts": [{"property": "created_at", "direction": "ascending"}],
    })
    if s != 200:
        print(f"⚠️  Notion クエリ失敗 ({s}) — スキップ", file=sys.stderr)
        return []
    return res.get("results", [])


def get_page_content(page_id: str) -> str:
    s, res = _notion("GET", f"/blocks/{page_id}/children")
    if s != 200:
        return "(詳細取得失敗)"
    lines = []
    for block in res.get("results", []):
        btype = block.get("type", "")
        rich  = block.get(btype, {}).get("rich_text", [])
        text  = "".join(r.get("text", {}).get("content", "") for r in rich)
        if btype == "heading_2":
            lines.append(f"\n  ### {text}")
        elif text:
            lines.append(f"  {text}")
    return "\n".join(lines)


def complete_task(page_id: str, resolution: str) -> bool:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    s, _ = _notion("PATCH", f"/pages/{page_id}", {
        "properties": {"status": {"select": {"name": "completed"}}},
    })
    if s != 200:
        return False
    _notion("PATCH", f"/blocks/{page_id}/children", {
        "children": [{
            "object": "block",
            "type":   "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {
                    "content": f"✅ Claude Code が解決 [{now}]\n{resolution}"
                }}],
                "icon":  {"type": "emoji", "emoji": "✅"},
                "color": "green_background",
            },
        }],
    })
    return True


def _parse_task(page: dict) -> dict:
    props = page["properties"]
    title = props["title"]["title"][0]["text"]["content"] if props["title"]["title"] else "(無題)"
    src   = ""
    if props.get("project", {}).get("rich_text"):
        src = props["project"]["rich_text"][0]["text"]["content"]
    date  = props.get("created_at", {}).get("date", {}).get("start", "")
    return {"id": page["id"], "title": title, "source": src, "date": date, "url": page.get("url", "")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail",   action="store_true", help="タスク本文も表示")
    parser.add_argument("--complete", metavar="PAGE_ID",   help="解決済みにするページID")
    parser.add_argument("--resolution", default="Claude Codeが処理しました")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("⚠️  NOTION_TOKEN 未設定 — VPS待機タスク確認をスキップ", file=sys.stderr)
        return

    if args.complete:
        ok = complete_task(args.complete, args.resolution)
        print("✅ 解決済みにしました" if ok else "❌ 更新失敗")
        return

    tasks = get_pending_tasks()
    if not tasks:
        print("✅ VPS待機タスクなし")
        return

    print(f"⏳ VPS待機タスク {len(tasks)} 件 — 優先処理してください\n")
    for i, page in enumerate(tasks, 1):
        t = _parse_task(page)
        print(f"  [{i}/{len(tasks)}] {t['title']}")
        print(f"         発生元: {t['source']} | {t['date']}")
        print(f"         ID:  {t['id']}")
        print(f"         URL: {t['url']}")
        if args.detail:
            print(get_page_content(t["id"]))
        print()

    print("── 処理コマンド ──")
    print("  詳細表示:  python3 Shared/Workflows/vps-task-checker.py --detail")
    print("  解決済み:  python3 Shared/Workflows/vps-task-checker.py \\")
    print("               --complete <PAGE_ID> --resolution '解決内容'")


if __name__ == "__main__":
    main()
