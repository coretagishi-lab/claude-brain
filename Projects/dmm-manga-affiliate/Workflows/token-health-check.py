#!/usr/bin/env python3
"""
token-health-check.py — YouTube OAuth トークン有効性チェック
launchd で毎日実行。切れていたら Notion タスクを登録して通知。
"""
import json, os, sys, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path

NOTION_TOKEN    = os.environ.get("NOTION_TOKEN", "")
TASK_BOARD_ID   = "3671cad4aa98813b85b2ed9e3127b913"
NOTION_VERSION  = "2022-06-28"
BASE_DIR        = Path.home() / ".config" / "dmm-youtube"
LOG_FILE        = Path.home() / "Library" / "Logs" / "ai-brain" / "token-health.log"

ACCOUNTS = [
    {"id": 1, "path": BASE_DIR / "token.json"},
    {"id": 2, "path": BASE_DIR / "account2" / "token.json"},
]

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def notion_post(path, data):
    body = json.dumps(data, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method="POST",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                 "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"  Notion API エラー: {e}")
        return {}

def check_token(account_id, token_path):
    if not token_path.exists():
        return "missing"
    token = json.loads(token_path.read_text())
    body = urllib.parse.urlencode({
        "client_id":     token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            json.loads(r.read())
        return "ok"
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode()).get("error", "")
        return "expired" if err == "invalid_grant" else f"error:{err}"

def register_alert(account_id, status):
    msg = f"YouTube account{account_id} のOAuthトークンが{status}です。再認証してください：\npython3 youtube-uploader.py --auth --account {account_id}"
    notion_post("/pages", {
        "parent": {"database_id": TASK_BOARD_ID},
        "properties": {
            "タスク名": {"title": [{"text": {"content": f"⚠️ [要認証] account{account_id} トークン切れ"}}]},
            "ステータス": {"select": {"name": "要対応"}},
            "メモ":      {"rich_text": [{"text": {"content": msg}}]},
        }
    })
    log(f"  ✅ Notionタスク登録: account{account_id}")

def main():
    if not NOTION_TOKEN:
        log("NOTION_TOKEN 未設定")
        sys.exit(1)
    log("token-health-check 起動")
    all_ok = True
    for acct in ACCOUNTS:
        status = check_token(acct["id"], acct["path"])
        log(f"  account{acct['id']}: {status}")
        if status != "ok":
            all_ok = False
            register_alert(acct["id"], status)
    if all_ok:
        log("全トークン正常")

if __name__ == "__main__":
    main()
