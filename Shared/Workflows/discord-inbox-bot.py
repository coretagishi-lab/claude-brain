#!/usr/bin/env python3
"""
#inbox Discord Bot — 投稿をルーティング（VPS常駐）

API不要タスク（即実行）:
  status          VPSサービス状態一覧
  sync            Vault同期を即時実行
  restart <svc>   サービス再起動
  log <svc>       ログ最新20行
  メモ: <text>    Notionにメモ保存
  help            コマンド一覧

API必要タスク（Notionキューに登録 → 次回ターミナル起動時に処理）:
  上記以外の全メッセージ

依存:
  pip3 install discord.py --break-system-packages
"""
import sys, os as _os
# Shared/Workflows/ に queue.py があり標準ライブラリと衝突するため除去
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here in sys.path:
    sys.path.remove(_here)

import asyncio, os, json, re, subprocess, urllib.request, urllib.error
from datetime import datetime

import discord

# ── 環境変数 ────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN        = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_INBOX_CHANNEL_ID = int(os.environ.get("DISCORD_INBOX_CHANNEL_ID", "0"))
NOTION_TOKEN             = os.environ.get("NOTION_TOKEN", "")
NOTION_OUTBOX_DB_ID      = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"
NOTION_VERSION           = "2022-06-28"

# ── 許可サービスホワイトリスト ────────────────────────────────────────────
ALLOWED_SERVICES = {
    "sync", "memory-monitor", "auth-monitor", "morning-report",
    "conoha-monitor", "dmm-discord-watcher", "discord-responder",
    "discord-inbox-bot",
}

HELP_TEXT = """\
**#inbox コマンド**

**即実行（API不要）:**
`status` — サービス状態確認
`sync` — Vault同期を即時実行
`restart <サービス>` — 再起動（例: `restart dmm-discord-watcher`）
`log <サービス>` — ログ最新20行（例: `log auth-monitor`）
`メモ: <内容>` — Notionにメモ保存

**次回ターミナル起動時に処理（Claude API必要）:**
上記以外のメッセージはすべてNotionキューに登録されます。"""


# ── ユーティリティ ──────────────────────────────────────────────────────────

def safe_service(raw: str):
    """サービス名をホワイトリスト確認して ai-brain-*.service 形式に正規化"""
    name = raw.strip().lower()
    name = re.sub(r"^ai-brain-", "", name)
    name = re.sub(r"\.service$", "", name)
    if name not in ALLOWED_SERVICES:
        return None
    return f"ai-brain-{name}.service"


def run(cmd: list, timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "⏱ タイムアウト"
    except Exception as e:
        return f"❌ 実行エラー: {e}"


def trim(text: str, limit: int = 1800) -> str:
    return text[-limit:] if len(text) > limit else text


# ── 即実行コマンド ──────────────────────────────────────────────────────────

def do_status() -> str:
    raw = run([
        "systemctl", "list-units", "ai-brain*",
        "--no-pager", "--no-legend", "--all",
    ])
    rows = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[0].replace(".service", "").replace("ai-brain-", "")
        active = parts[2]
        icon = "✅" if active == "active" else "❌"
        rows.append(f"{icon} `{name}` — {active} / {parts[3]}")
    return "**VPS サービス状態**\n" + "\n".join(rows) if rows else "サービス情報なし"


def do_sync() -> str:
    out = run(["systemctl", "start", "ai-brain-sync.service"])
    return "✅ 同期を開始しました（30秒ほどで完了します）" if not out else f"⚠️ {out[:500]}"


def do_restart(svc_raw: str) -> str:
    svc = safe_service(svc_raw)
    if not svc:
        allowed = ", ".join(sorted(ALLOWED_SERVICES))
        return f"❌ 不明なサービス: `{svc_raw}`\n許可リスト: {allowed}"
    out = run(["systemctl", "restart", svc])
    return f"✅ `{svc}` を再起動しました" if not out else f"⚠️ 再起動:\n```\n{out[:600]}\n```"


def do_log(svc_raw: str) -> str:
    svc = safe_service(svc_raw)
    if not svc:
        allowed = ", ".join(sorted(ALLOWED_SERVICES))
        return f"❌ 不明なサービス: `{svc_raw}`\n許可リスト: {allowed}"
    out = run(["journalctl", "-u", svc, "-n", "20", "--no-pager"])
    if not out:
        return f"`{svc}` のログが見つかりません"
    return f"**`{svc}` ログ（最新20行）**\n```\n{trim(out)}\n```"


def do_memo(text: str, discord_url: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    status, res = notion_post("/pages", {
        "parent": {"database_id": NOTION_OUTBOX_DB_ID},
        "properties": {
            "title":      {"title": rt(f"[メモ] {text[:80]}")},
            "status":     {"select": {"name": "sent"}},
            "type":       {"select": {"name": "note"}},
            "project":    {"rich_text": rt("inbox")},
            "created_at": {"date": {"start": today}},
        },
        "children": [
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": rt(text)}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": rt(f"Discord: {discord_url}")}},
        ],
    })
    if status == 200:
        return f"✅ メモをNotionに保存しました\n→ {res.get('url', '')}"
    return f"❌ Notion保存失敗 ({status})"


# ── Notion キュー登録 ────────────────────────────────────────────────────────

def notion_post(path: str, data: dict):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method="POST",
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        })
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def rt(text: str) -> list:
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def queue_task(title: str, body: str, discord_url: str) -> tuple:
    """API必要タスクをNotionキューに登録。戻り値: (ok: bool, url_or_err: str)"""
    today = datetime.now().strftime("%Y-%m-%d")
    status, res = notion_post("/pages", {
        "parent": {"database_id": NOTION_OUTBOX_DB_ID},
        "properties": {
            "title":      {"title": rt(title[:100])},
            "status":     {"select": {"name": "pending"}},
            "type":       {"select": {"name": "task"}},
            "project":    {"rich_text": rt("inbox")},
            "created_at": {"date": {"start": today}},
        },
        "children": [
            {"object": "block", "type": "callout",
             "callout": {
                 "rich_text": rt("次回 Claude Code セッション開始時に処理されます"),
                 "icon": {"emoji": "⏳"},
             }},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": rt(body[:2000])}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": rt(f"Discord: {discord_url}")}},
        ],
    })
    if status == 200:
        return True, res.get("url", "")
    return False, f"Notion登録失敗 ({status})"


# ── ルーター ─────────────────────────────────────────────────────────────────

def route(content: str, discord_url: str) -> tuple:
    """
    Returns:
      ('immediate', reply_str)
      ('queue',     reply_str)
    """
    loop = asyncio.get_event_loop()
    text = content.strip()

    # help
    if re.match(r"^(help|ヘルプ|使い方)$", text, re.I):
        return "immediate", HELP_TEXT

    # status
    if re.match(r"^(status|状態|サービス確認|確認)$", text, re.I):
        return "immediate", do_status()

    # sync
    if re.match(r"^(sync|同期)$", text, re.I):
        return "immediate", do_sync()

    # restart <service>
    m = re.match(r"^(restart|再起動)\s+(.+)", text, re.I)
    if m:
        return "immediate", do_restart(m.group(2).strip())

    # log <service>
    m = re.match(r"^(log|ログ)\s+(.+)", text, re.I)
    if m:
        return "immediate", do_log(m.group(2).strip())

    # メモ
    m = re.match(r"^(メモ|memo)[:：]\s*(.+)", text, re.I | re.DOTALL)
    if m:
        return "immediate", do_memo(m.group(2).strip(), discord_url)

    # その他 → Notionキュー
    lines = text.splitlines()
    title = f"[inbox] {lines[0][:60]}" if lines else "[inbox] タスク"
    ok, url_or_err = queue_task(title, text, discord_url)
    if ok:
        reply = (
            f"⏳ Notionキューに登録しました。次回ターミナル起動時に処理します。\n"
            f"→ {url_or_err}"
        )
    else:
        reply = f"❌ キュー登録失敗: {url_or_err}\n内容: {text[:200]}"
    return "queue", reply


# ── Discord Bot ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"[discord-inbox-bot] 起動完了: {client.user}  監視チャンネル: {DISCORD_INBOX_CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != DISCORD_INBOX_CHANNEL_ID:
        return
    if not message.content.strip():
        return

    guild_id = message.guild.id if message.guild else 0
    discord_url = f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"

    # ルーティングはブロッキング処理なのでスレッドで実行
    loop = asyncio.get_event_loop()
    kind, reply = await loop.run_in_executor(
        None, lambda: route(message.content, discord_url)
    )

    icon = "✅" if kind == "immediate" else "⏳"
    await message.add_reaction(icon)
    # 2000文字超は分割
    if len(reply) <= 1999:
        await message.reply(reply)
    else:
        await message.reply(reply[:1999])
        await message.channel.send(reply[1999:3998])

    print(f"[{kind}] {message.author}: {message.content[:60]}")


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    missing = [k for k, v in {
        "DISCORD_BOT_TOKEN":        DISCORD_BOT_TOKEN,
        "DISCORD_INBOX_CHANNEL_ID": DISCORD_INBOX_CHANNEL_ID,
        "NOTION_TOKEN":             NOTION_TOKEN,
    }.items() if not v]
    if missing:
        print(f"[ERROR] 環境変数未設定: {', '.join(missing)}")
        raise SystemExit(1)

    print(f"[discord-inbox-bot] #inbox チャンネルID: {DISCORD_INBOX_CHANNEL_ID}")
    client.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
