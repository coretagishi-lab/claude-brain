#!/usr/bin/env python3
"""
GitHub coretagishi-lab/claude-brain から2種類のinboxをローカルに同期する

1. inbox.md（ルート）      → AI-Brain/Inbox/inbox.md
   Claude実行指示ファイル（watch_inbox.sh が書く）

2. Inbox/inbox.md（サブディレクトリ）→ AI-Brain/Inbox/memos.md
   iPhone inbox-sender.html が書くメモ
"""
import os, json, base64, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER        = "coretagishi-lab"
REPO         = "claude-brain"

VAULT = Path(__file__).resolve().parents[2]  # AI-Brain/

SYNC_TARGETS = [
    # (GitHubパス,             ローカル保存先,                  説明)
    ("inbox.md",               VAULT / "Inbox" / "inbox.md",    "Claude実行指示inbox"),
    ("Inbox/inbox.md",         VAULT / "Inbox" / "memos.md",    "iPhoneメモinbox"),
]

# ── GitHub API ────────────────────────────────────────────────
def fetch(path):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "inbox-sync"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            d = json.loads(res.read())
            return base64.b64decode(d["content"].replace("\n", "")).decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"GitHub API {e.code}: {path}")

# ── 新規エントリを検出 ────────────────────────────────────────
def count_new(remote, local):
    local_lines  = set((local or "").strip().splitlines())
    remote_lines = (remote or "").strip().splitlines()
    return [l for l in remote_lines if l.startswith("- ") and l not in local_lines]

# ── メイン ────────────────────────────────────────────────────
def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] inbox-sync start")

    if not GITHUB_TOKEN:
        print("  ❌ GITHUB_TOKEN 未設定（~/.zshrc に export GITHUB_TOKEN=ghp_... を追加してください）")
        return

    for gh_path, local_path, label in SYNC_TARGETS:
        remote = fetch(gh_path)
        if remote is None:
            print(f"  ℹ️  [{label}] {gh_path} は未作成。スキップ。")
            continue

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local = local_path.read_text(encoding="utf-8") if local_path.exists() else ""

        if remote.rstrip("\n") == local.rstrip("\n"):
            print(f"  ✅ [{label}] 変更なし")
            continue

        new_entries = count_new(remote, local)
        local_path.write_text(remote, encoding="utf-8")

        if new_entries:
            print(f"  ✅ [{label}] 新規エントリ {len(new_entries)} 件 → {local_path.name}")
            for e in new_entries[-5:]:
                print(f"     {e[:100]}")
        else:
            print(f"  ✅ [{label}] 更新完了 → {local_path.name}")

    print(f"  inbox-sync done.")

if __name__ == "__main__":
    main()
