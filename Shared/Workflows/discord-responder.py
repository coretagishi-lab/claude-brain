#!/usr/bin/env python3
"""
Discord Responder (最小版) — 1/2 の返信受け取り専用

機能:
  - VPS が discord-ask.py で送った質問に対して「1」か「2」で返信を受け取る
  - 「1」: api_zero なら即実行 / api_needed なら Notion キューに積む
  - 「2」: Notion キューに積んで保留
  - 自然言語解釈なし・Claude API 一切使わない・全処理 API ゼロ

環境変数 (.env から自動ロード):
  DISCORD_BOT_TOKEN      Bot トークン
  DISCORD_BOT_CHANNEL_ID 監視チャンネル ID
  DISCORD_OWNER_ID       受付ユーザー ID（他は無視）
"""
import sys as _sys
# Shared/Workflows/queue.py が stdlib の queue を上書きするのを防ぐ
_sys.path = [p for p in _sys.path if "Workflows" not in p]

import discord, json, os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

PENDING_FILE = Path("/opt/ai-brain/.credentials/.discord_pending.json")
ENV_FILE     = Path("/opt/ai-brain/.credentials/.env")
SCRIPT_DIR   = Path(__file__).resolve().parent
REPORTER     = SCRIPT_DIR / "vps-task-reporter.py"


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^(\w+)="(.+)"$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)


_load_env()

TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("DISCORD_BOT_CHANNEL_ID", "0").strip()
OWNER_ID   = os.environ.get("DISCORD_OWNER_ID", "0").strip()

missing = [k for k, v in {"DISCORD_BOT_TOKEN": TOKEN,
                           "DISCORD_BOT_CHANNEL_ID": CHANNEL_ID,
                           "DISCORD_OWNER_ID": OWNER_ID}.items() if not v or v == "0"]
if missing:
    sys.exit(f"❌ 必須環境変数が未設定: {', '.join(missing)}")

CHANNEL_INT = int(CHANNEL_ID)
OWNER_INT   = int(OWNER_ID)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def load_pending() -> dict | None:
    try:
        return json.loads(PENDING_FILE.read_text()) if PENDING_FILE.exists() else None
    except Exception:
        return None


def clear_pending() -> None:
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()


def add_to_notion_queue(pending: dict, reason: str) -> None:
    if not REPORTER.exists():
        return
    subprocess.run(
        [sys.executable, str(REPORTER),
         "--title",  f"{pending.get('notion_title', pending.get('question', '?')[:60])} [{reason}]",
         "--detail", pending.get("notion_detail", pending.get("question", "")),
         "--action", pending.get("action_1", {}).get("label", "Claude Code で対応"),
         "--source", pending.get("source", "discord-responder")],
        capture_output=True,
    )


def run_command(cmd: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        out = (r.stdout or r.stderr or "(出力なし)").strip()[-400:]
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "タイムアウト (60s)"
    except Exception as e:
        return False, str(e)


@client.event
async def on_ready() -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] ✅ Discord Responder 起動: {client.user}")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_INT:
        return
    if message.author.id != OWNER_INT:
        return

    content = message.content.strip()
    if content not in ("1", "2"):
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    pending = load_pending()

    if not pending:
        await message.channel.send("⚠️ 対応中の質問がありません。")
        return

    question = pending.get("question", "")

    # ── 「1」を選択 ──────────────────────────────────────────
    if content == "1":
        action = pending.get("action_1", {})
        label  = action.get("label", "処理")
        atype  = action.get("type", "api_needed")

        if atype == "api_zero":
            await message.channel.send(f"✅ 今すぐ処理します: **{label}**")
            cmd = action.get("command", "")
            if cmd:
                ok, out = run_command(cmd)
                status = "✅ 完了" if ok else "❌ 失敗"
                await message.channel.send(f"{status}\n```\n{out}\n```")
        else:
            add_to_notion_queue(pending, "1選択・API処理待ち")
            await message.channel.send(
                f"⏳ ターミナル起動後に処理します: **{label}**\n"
                "Notion キューに登録しました。"
            )

    # ── 「2」を選択 ──────────────────────────────────────────
    else:
        label = pending.get("action_2", {}).get("label", "保留")
        add_to_notion_queue(pending, "2選択・保留")
        await message.channel.send(
            f"⏳ 保留にしました: **{label}**\n"
            "Notion キューに登録しました。"
        )

    clear_pending()
    print(f"[{ts}] 返信処理完了: {content} / {question[:40]}")


client.run(TOKEN, log_handler=None)
