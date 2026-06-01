#!/usr/bin/env python3
"""
VPS Task Reporter: 自己解決できない問題を Notion 待機タスクリストに登録 + Discord 通知

VPS の自動スクリプト（auth-monitor 等）から呼び出される。
解決には Claude Code（Mac）が必要と判断された問題を記録する。

使い方:
  python3 vps-task-reporter.py \
    --title "GitHub 認証エラー: トークン期限切れ" \
    --detail "sync.sh が 401 で失敗。tokens.md の PAT が無効。" \
    --action "tokens.md の GITHUB.PAT を新しいトークンで更新してください" \
    --source "auth-monitor"

  python3 vps-task-reporter.py --list  # 未解決タスク一覧
"""
import argparse, json, os, re, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

NOTION_VERSION = "2022-06-28"
OUTBOX_DB_ID   = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"
ENV_FILE       = Path("/opt/ai-brain/.credentials/.env")


def _load_env() -> None:
    """systemd 外から呼ばれた時のために .env を手動ロード"""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^(\w+)="(.+)"$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)


_load_env()
NOTION_TOKEN    = os.environ.get("NOTION_TOKEN", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")


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


def _blocks(text: str) -> list:
    blocks = []
    for line in text.strip().splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": s[3:]}}]}})
        elif s.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": s[2:]}}]}})
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": s}}]}})
    return blocks[:50]


def create_notion_task(
    title: str, detail: str, suggested_action: str, source: str
) -> tuple[bool, str, str]:
    now = datetime.now()
    body = (
        f"## 問題の詳細\n{detail}\n\n"
        f"## 推奨アクション\n{suggested_action}\n\n"
        f"## 発生元 / 発生時刻\n{source}  /  {now.strftime('%Y-%m-%d %H:%M:%S')} JST"
    )
    s, res = _notion("POST", "/pages", {
        "parent":     {"database_id": OUTBOX_DB_ID},
        "properties": {
            "title":      {"title": [{"type": "text", "text": {"content": title[:100]}}]},
            "status":     {"select": {"name": "pending"}},
            "type":       {"select": {"name": "vps-task"}},
            "project":    {"rich_text": [{"type": "text", "text": {"content": f"vps/{source}"}}]},
            "created_at": {"date": {"start": now.strftime("%Y-%m-%d")}},
        },
        "children": _blocks(body),
    })
    if s == 200:
        return True, res["id"], res.get("url", "")
    return False, "", str(res)


def send_discord(
    title: str, detail: str, suggested_action: str, source: str, notion_url: str = ""
) -> bool:
    if not DISCORD_WEBHOOK:
        return False
    fields = [
        {"name": "📋 問題",          "value": detail[:200],           "inline": False},
        {"name": "🔧 推奨アクション", "value": suggested_action[:200], "inline": False},
        {"name": "📌 発生元",         "value": source,                 "inline": True},
    ]
    if notion_url:
        fields.append({"name": "🔗 Notion", "value": f"[タスクを見る]({notion_url})", "inline": True})

    payload = {
        "username": "AI-Brain VPS",
        "embeds": [{
            "title":       f"⏳ 待機タスク: {title}",
            "description": "Claude Code が次回起動時に処理します",
            "color":       0xFFAA00,
            "fields":      fields,
            "footer":      {"text": f"AI-Brain VPS • {datetime.now().strftime('%Y-%m-%d %H:%M')}"},
        }],
    }
    req = urllib.request.Request(
        DISCORD_WEBHOOK, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "DiscordBot (AI-Brain, 1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status in (200, 204)
    except Exception as e:
        print(f"Discord通知失敗: {e}", file=sys.stderr)
        return False


def list_pending() -> list:
    s, res = _notion("POST", f"/databases/{OUTBOX_DB_ID}/query", {
        "filter": {"and": [
            {"property": "type",   "select": {"equals": "vps-task"}},
            {"property": "status", "select": {"equals": "pending"}},
        ]},
        "sorts": [{"property": "created_at", "direction": "ascending"}],
    })
    if s != 200:
        return []
    tasks = []
    for page in res.get("results", []):
        props = page["properties"]
        title = props["title"]["title"][0]["text"]["content"] if props["title"]["title"] else ""
        date  = props.get("created_at", {}).get("date", {}).get("start", "")
        tasks.append({"id": page["id"], "title": title, "date": date, "url": page.get("url", "")})
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title",  default="")
    parser.add_argument("--detail", default="")
    parser.add_argument("--action", default="Claude Codeで調査・対応してください")
    parser.add_argument("--source", default="vps")
    parser.add_argument("--list",   action="store_true", help="待機タスク一覧を表示")
    args = parser.parse_args()

    if args.list:
        tasks = list_pending()
        if not tasks:
            print("✅ 待機タスクなし")
        else:
            print(f"⏳ 待機タスク {len(tasks)} 件:")
            for t in tasks:
                print(f"  [{t['date']}] {t['title']}")
                print(f"    {t['url']}")
        return

    if not args.title:
        parser.error("--title が必要です（または --list）")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] ⏳ Notion 待機タスク登録: {args.title}")

    notion_url = ""
    if NOTION_TOKEN:
        ok, _, notion_url = create_notion_task(
            args.title, args.detail, args.action, args.source
        )
        print(f"  {'✅' if ok else '❌'} Notion {'登録完了' if ok else '登録失敗'}: {notion_url or '—'}")
    else:
        print("  ⚠️  NOTION_TOKEN 未設定のためスキップ", file=sys.stderr)

    ok = send_discord(args.title, args.detail, args.action, args.source, notion_url)
    print(f"  {'✅' if ok else '❌'} Discord 通知")


if __name__ == "__main__":
    main()
