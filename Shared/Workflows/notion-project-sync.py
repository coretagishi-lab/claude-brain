#!/usr/bin/env python3
"""
AI-Brain Projects/*/PROJECT_STATUS.md → Notion Project Dashboard DB に同期する

動作:
  - 各 PROJECT_STATUS.md を読んで project_name をキーに upsert
  - ページが存在しなければ新規作成、あれば更新
  - --quiet フラグで変更があった場合のみ出力

使い方:
  python3 notion-project-sync.py           # 全プロジェクト同期
  python3 notion-project-sync.py --quiet   # 変更時のみ出力（hookから呼ぶ用）
  python3 notion-project-sync.py --dry-run # 書き込みなし・確認のみ
"""
import os, sys, re, json, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"
DB_ID    = "36f1cad4-aa98-81ee-9293-c96d63661d79"   # Project Dashboard DB

VAULT        = Path(__file__).resolve().parents[2]
PROJECTS_DIR = VAULT / "Projects"

QUIET   = "--quiet"   in sys.argv
DRY_RUN = "--dry-run" in sys.argv

# ── Notion API ────────────────────────────────────────────────
def notion(method, path, data=None):
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                 "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

# ── PROJECT_STATUS.md パーサー ────────────────────────────────
def parse_status(path):
    text = path.read_text(encoding="utf-8")

    # YAML frontmatter
    fm = {}
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                fm[k.strip()] = v.strip().strip('"')

    def section(key):
        """## key の直後から次の ## までのテキストを返す"""
        p = re.search(rf"^## {key}\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not p:
            return ""
        # 箇条書き行を結合、空行スキップ
        lines = [l.lstrip("- ").strip() for l in p.group(1).splitlines()
                 if l.strip() and l.strip() not in ("-", "なし")]
        return " / ".join(lines)[:1900]  # Notion rich_text 上限

    return {
        "project_name":   fm.get("project_name", path.parent.name),
        "status":         fm.get("current_status", "idle"),
        "priority":       fm.get("priority", "medium"),
        "due_date":       fm.get("due_date", "").strip('"') or None,
        "review_waiting": fm.get("review_waiting", "false").lower() == "true",
        "updated_at":     fm.get("updated_at", datetime.now().strftime("%Y-%m-%d")),
        "current_goal":   section("current_goal"),
        "next_action":    section("next_action"),
        "blockers":       section("blocker"),
    }

# ── 既存ページ検索 ────────────────────────────────────────────
def find_page(project_name):
    s, res = notion("POST", f"/databases/{DB_ID}/query", {
        "filter": {
            "property": "プロジェクト名",
            "title": {"equals": project_name}
        }
    })
    if s == 200 and res.get("results"):
        return res["results"][0]["id"]
    return None

# ── Notion プロパティ構築 ─────────────────────────────────────
def rt(text):
    """rich_text の短縮ヘルパー"""
    if not text:
        return []
    return [{"type": "text", "text": {"content": str(text)[:1900]}}]

def build_props(d):
    props = {
        "プロジェクト名": {"title": rt(d["project_name"])},
        "ステータス":     {"select": {"name": d["status"]}},
        "優先度":         {"select": {"name": d["priority"]}},
        "レビュー待ち":   {"checkbox": d["review_waiting"]},
    }
    if d.get("updated_at"):
        props["最終更新日"] = {"date": {"start": d["updated_at"]}}
    if d.get("due_date"):
        props["期限"] = {"date": {"start": d["due_date"]}}
    else:
        props["期限"] = {"date": None}
    if d.get("current_goal"):
        props["現在のゴール"]   = {"rich_text": rt(d["current_goal"])}
    if d.get("next_action"):
        props["次のアクション"] = {"rich_text": rt(d["next_action"])}
    if d.get("blockers"):
        props["ブロッカー"]     = {"rich_text": rt(d["blockers"])}
    return props

# ── メイン ────────────────────────────────────────────────────
def main():
    if not NOTION_TOKEN:
        print("❌ NOTION_TOKEN 未設定")
        return

    status_files = sorted(PROJECTS_DIR.glob("*/PROJECT_STATUS.md"))
    if not status_files:
        if not QUIET:
            print("ℹ️  Projects/ にPROJECT_STATUS.mdが見つかりません")
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not QUIET:
        print(f"[{ts}] notion-project-sync: {len(status_files)} プロジェクト")

    updated = 0
    for path in status_files:
        d = parse_status(path)
        name = d["project_name"]

        if DRY_RUN:
            print(f"  [dry-run] {name}: {d['status']} / {d['priority']}")
            print(f"    goal:   {d['current_goal'][:60]}")
            print(f"    next:   {d['next_action'][:60]}")
            print(f"    block:  {d['blockers'][:60]}")
            continue

        props = build_props(d)
        existing_id = find_page(name)

        if existing_id:
            s, _ = notion("PATCH", f"/pages/{existing_id}", {"properties": props})
            verb = "更新"
        else:
            s, _ = notion("POST", "/pages", {
                "parent": {"database_id": DB_ID},
                "properties": props,
            })
            verb = "新規作成"

        ok = s in (200, 201)
        updated += 1 if ok else 0

        if not QUIET or not ok:
            icon = "✅" if ok else "❌"
            print(f"  {icon} [{verb}] {name}: {d['status']} / priority={d['priority']}")
            if not ok:
                print(f"      HTTP {s}")
            elif not QUIET:
                if d['next_action']:
                    print(f"      → {d['next_action'][:80]}")

    if not QUIET:
        print(f"\n  同期完了: {updated}/{len(status_files)} 件")
    elif updated > 0:
        print(f"[notion-sync] {updated} プロジェクト更新")

if __name__ == "__main__":
    main()
