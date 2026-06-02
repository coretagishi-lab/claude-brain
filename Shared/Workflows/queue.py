#!/usr/bin/env python3
"""
Inbox/inbox.md キューマネージャー

キューフォーマット:
  - 2026-05-29 10:30 タスク内容        ← pending（プレフィックスなし）
  - ⏳ 2026-05-29 10:00 タスク内容     ← in-progress（⏳）
  - ✅ 2026-05-29 09:00 タスク内容     ← done（✅）

コマンド:
  python3 queue.py status            # キュー全体を表示
  python3 queue.py next              # 次のpendingをin-progressにして返す
  python3 queue.py done [完了メモ]   # 処理中タスクを完了にマーク
  python3 queue.py list              # pending一覧のみ

ルール:
  - ⏳が存在する間はnextを実行しても新しいタスクは取得できない（1タスクずつの保証）
  - 追加は常にファイル末尾（FIFO順）
  - 完了後は✅になり記録として残る（削除しない）
"""
import os, sys, json, base64, re, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = "coretagishi-lab"
REPO  = "claude-brain"
GH_PATH = "Inbox/inbox.md"
API   = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{GH_PATH}"

VAULT       = Path(__file__).resolve().parents[2]
LOCAL_QUEUE = VAULT / "Inbox" / "memos.md"

S_DONE = "✅"
S_WIP  = "⏳"

HEADER = "# Inbox Queue\n\n"

# ── GitHub API ────────────────────────────────────────────────
def gh_get():
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "queue-manager"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = urllib.request.Request(API, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            d = json.loads(res.read())
            content = base64.b64decode(d["content"].replace("\n","")).decode("utf-8")
            return content, d["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise RuntimeError(f"GitHub GET {e.code}")

def gh_put(content, sha, message):
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN 未設定")
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(API,
        data=json.dumps(body).encode(), method="PUT",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def local_write(content):
    LOCAL_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_QUEUE.write_text(content, encoding="utf-8")

# ── エントリパース ────────────────────────────────────────────
def parse(content):
    """
    return list of:
      {"idx": int, "status": "pending"|"wip"|"done", "ts": str, "text": str, "line": str}
    """
    entries = []
    for i, line in enumerate(content.splitlines()):
        if not line.startswith("- "):
            continue
        rest = line[2:]
        if rest.startswith(S_DONE + " "):
            status = "done"
            rest   = rest[len(S_DONE)+1:]
        elif rest.startswith(S_WIP + " "):
            status = "wip"
            rest   = rest[len(S_WIP)+1:]
        else:
            status = "pending"

        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (.*)", rest)
        ts   = m.group(1) if m else ""
        text = m.group(2) if m else rest
        entries.append({"idx": i, "status": status, "ts": ts, "text": text, "line": line})
    return entries

def update_line(content, idx, new_line):
    lines = content.splitlines()
    lines[idx] = new_line
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result

# ── コマンド実装 ──────────────────────────────────────────────
def cmd_status(content):
    entries = parse(content)
    wip     = [e for e in entries if e["status"] == "wip"]
    pending = [e for e in entries if e["status"] == "pending"]
    done    = [e for e in entries if e["status"] == "done"]

    print(f"キュー状態: ⏳{len(wip)} 件処理中  /  📋{len(pending)} 件待機  /  ✅{len(done)} 件完了")
    print()

    if wip:
        print("⏳ 処理中:")
        for e in wip:
            print(f"   [{e['ts']}] {e['text']}")
        print()

    if pending:
        print("📋 待機中:")
        for e in pending:
            print(f"   [{e['ts']}] {e['text']}")
        print()

    if not wip and not pending:
        print("   キューは空です。")

def cmd_next(content, sha):
    entries = parse(content)
    wip     = [e for e in entries if e["status"] == "wip"]

    # 処理中タスクが存在する間は新規取得不可（1タスクずつの保証）
    if wip:
        e = wip[0]
        print(f"⚠️  処理中のタスクが完了するまで次を取得できません。")
        print()
        print(f"⏳ 現在処理中: [{e['ts']}] {e['text']}")
        print()
        print(f"   完了後: python3 Shared/Workflows/queue.py done \"完了メモ\"")
        return None

    pending = [e for e in entries if e["status"] == "pending"]
    if not pending:
        print("📭 待機中のタスクはありません。")
        return None

    task = pending[0]  # FIFO: 先頭のpendingを取得
    new_line = f"- {S_WIP} {task['ts']} {task['text']}"
    new_content = update_line(content, task["idx"], new_line)

    status, _ = gh_put(new_content, sha, f"Queue: start [{task['ts']}] {task['text'][:40]}")
    if status not in (200, 201):
        print(f"❌ GitHub更新失敗: {status}")
        return None

    local_write(new_content)

    print(f"⏳ タスクを取得しました:")
    print()
    print(f"   [{task['ts']}] {task['text']}")
    print()
    print(f"   処理後: python3 Shared/Workflows/queue.py done \"完了メモ\"")
    return task["text"]

def cmd_done(content, sha, note=""):
    entries = parse(content)
    wip     = [e for e in entries if e["status"] == "wip"]

    if not wip:
        print("⚠️  処理中のタスクはありません。")
        return

    task    = wip[0]
    suffix  = f" — {note}" if note else ""
    new_line = f"- {S_DONE} {task['ts']} {task['text']}{suffix}"
    new_content = update_line(content, task["idx"], new_line)

    status, _ = gh_put(new_content, sha, f"Queue: done [{task['ts']}] {task['text'][:40]}")
    if status not in (200, 201):
        print(f"❌ GitHub更新失敗: {status}")
        return

    local_write(new_content)

    print(f"✅ 完了: [{task['ts']}] {task['text']}{suffix}")

    # 次のpendingを案内
    entries_new = parse(new_content)
    next_tasks  = [e for e in entries_new if e["status"] == "pending"]
    if next_tasks:
        n = next_tasks[0]
        print()
        print(f"📋 次のタスク: [{n['ts']}] {n['text']}")
        print(f"   python3 Shared/Workflows/queue.py next  で取得")
    else:
        print()
        print("📭 キューは空になりました。")

def cmd_list(content):
    entries = [e for e in parse(content) if e["status"] == "pending"]
    if not entries:
        print("📭 待機中のタスクはありません。")
        return
    for e in entries:
        print(f"  [{e['ts']}] {e['text']}")

# ── メイン ────────────────────────────────────────────────────
def main():
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN 未設定（export GITHUB_TOKEN=ghp_... が必要）")
        sys.exit(1)

    args = sys.argv[1:]
    cmd  = args[0] if args else "status"

    content, sha = gh_get()
    if content is None:
        # ファイル未作成 → 初期化
        content = HEADER
        sha     = None

    if cmd == "status":
        cmd_status(content)
    elif cmd == "next":
        cmd_next(content, sha)
    elif cmd == "done":
        note = " ".join(args[1:]) if len(args) > 1 else ""
        cmd_done(content, sha, note)
    elif cmd == "list":
        cmd_list(content)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
