#!/usr/bin/env python3
"""
#inbox Discord Bot — 投稿をルーティング（VPS常駐）

即実行（API不要）:
  YouTube/Instagram URL  → yt-dlp で全情報収集 → #通知に返送
  status / sync / restart <svc> / log <svc> / メモ: <text>

Notionキュー登録（Claude API必要）:
  上記以外の全メッセージ

依存:
  pip3 install discord.py --break-system-packages
  pip3 install instaloader --break-system-packages
  apt install yt-dlp  または  pip3 install yt-dlp --break-system-packages
"""
import sys, os as _os
# Shared/Workflows/ に queue.py があり標準ライブラリと衝突するため除去
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here in sys.path:
    sys.path.remove(_here)

import asyncio, os, json, re, shutil, subprocess, tempfile, urllib.request, urllib.error, urllib.parse
from datetime import datetime

import discord

# ── 環境変数 ─────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN         = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_INBOX_CHANNEL_ID  = int(os.environ.get("DISCORD_INBOX_CHANNEL_ID", "0"))
DISCORD_NOTIFY_CHANNEL_ID = int(os.environ.get("DISCORD_NOTIFY_CHANNEL_ID", "0"))
NOTION_TOKEN              = os.environ.get("NOTION_TOKEN", "")
NOTION_OUTBOX_DB_ID       = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"
NOTION_VERSION            = "2022-06-28"

ALLOWED_SERVICES = {
    "sync", "memory-monitor", "auth-monitor", "morning-report",
    "conoha-monitor", "dmm-discord-watcher", "discord-responder",
    "discord-inbox-bot",
}

HELP_TEXT = """\
**#inbox コマンド**

**即実行（API不要）:**
YouTube/Instagram URL を貼る → 全情報収集して #通知 に返送
`status` — サービス状態確認
`sync` — Vault同期を即時実行
`restart <サービス>` — 再起動
`log <サービス>` — ログ最新20行
`メモ: <内容>` — Notionにメモ保存

**次回ターミナル起動時に処理（Claude API必要）:**
上記以外のメッセージ → Notionキューに登録"""

# ── yt-dlp クッキー設定 ────────────────────────────────────────────────────────
YTDLP_COOKIES = "/opt/ai-brain/.credentials/youtube-cookies.txt"

def cookies_args() -> list:
    """クッキーファイルが存在する場合のみ --cookies 引数を返す"""
    return ["--cookies", YTDLP_COOKIES] if os.path.exists(YTDLP_COOKIES) else []

# ── URL パターン ──────────────────────────────────────────────────────────────
YT_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/)|youtu\.be/)[\w\-]+"
)
IG_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[\w\-]+"
)

# ── ユーティリティ ─────────────────────────────────────────────────────────────

def safe_service(raw: str):
    name = re.sub(r"^ai-brain-", "", raw.strip().lower())
    name = re.sub(r"\.service$", "", name)
    return f"ai-brain-{name}.service" if name in ALLOWED_SERVICES else None


def run(cmd: list, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "⏱ タイムアウト"
    except FileNotFoundError as e:
        return f"❌ コマンド未インストール: {e}"
    except Exception as e:
        return f"❌ 実行エラー: {e}"


def trim(text: str, limit: int = 1800) -> str:
    return text[-limit:] if len(text) > limit else text


# ── URL分析 ───────────────────────────────────────────────────────────────────

def parse_vtt(content: str) -> str:
    """VTTファイルから字幕テキストのみ抽出（タイムスタンプ・ヘッダー除去）"""
    lines, seen = [], set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if "-->" in line or re.match(r"^\d{2}:\d{2}", line) or re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)  # HTMLタグ除去
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return " ".join(lines)


def _ytdlp_fetch_json(cmd_args: list, url: str, timeout: int = 90) -> tuple:
    """
    yt-dlp --dump-json を実行。
    1. クッキー + EJSソルバー（node + remote-components）で試行
    2. 失敗した場合はクッキーなしでリトライ（bot検知されない公開URLの場合）
    Returns: (data_dict, used_cookies: bool)
    """
    base = ["yt-dlp", "--dump-json", "--skip-download", "--no-playlist", "--no-warnings"]
    ejs_args = ["--js-runtimes", "node", "--remote-components", "ejs:github"]

    # クッキー + EJSソルバーで試行
    if os.path.exists(YTDLP_COOKIES):
        raw = run(base + ejs_args + cmd_args + ["--cookies", YTDLP_COOKIES, url], timeout=timeout)
        try:
            return json.loads(raw), True
        except json.JSONDecodeError:
            pass  # フォールバックへ

    # クッキーなしで再試行（公開動画・EJS不要の場合）
    raw = run(base + cmd_args + [url], timeout=timeout)
    try:
        return json.loads(raw), False
    except json.JSONDecodeError:
        return None, False


def analyze_youtube(url: str) -> str:
    work = tempfile.mkdtemp(prefix="yt-")
    try:
        # 1. メタデータ取得（クッキーあり→失敗時はなしでリトライ）
        data, used_cookies = _ytdlp_fetch_json(
            ["--write-comments", "--extractor-args", "youtube:max_comments=30,20,5"],
            url, timeout=90,
        )
        if data is None:
            return f"❌ YouTube情報取得失敗（クッキーあり・なし両方試行済み）"

        title       = data.get("title", "(不明)")
        description = (data.get("description") or "")
        uploader    = data.get("uploader") or data.get("channel", "")
        views       = data.get("view_count") or 0
        likes       = data.get("like_count") or 0
        duration    = data.get("duration_string") or ""
        tags        = (data.get("tags") or [])[:10]
        ud          = data.get("upload_date") or ""
        upload_date = f"{ud[:4]}-{ud[4:6]}-{ud[6:]}" if len(ud) == 8 else ud
        comments    = data.get("comments") or []
        chapters    = data.get("chapters") or []

        # 2. 字幕ダウンロード（日本語優先 → 英語フォールバック）
        sub_cmd = ["yt-dlp", "--write-subs", "--write-auto-subs",
                   "--sub-lang", "ja.*,en.*", "--sub-format", "vtt",
                   "--skip-download", "--no-playlist", "--no-warnings",
                   "--js-runtimes", "node", "--remote-components", "ejs:github"]
        if os.path.exists(YTDLP_COOKIES):
            run(sub_cmd + ["--cookies", YTDLP_COOKIES, "-o", f"{work}/sub", url], timeout=60)
        if not any(f.endswith(".vtt") for f in os.listdir(work)):
            run(sub_cmd + ["-o", f"{work}/sub", url], timeout=60)

        # 日本語優先でVTTファイルを選択
        vtt_files = [f for f in os.listdir(work) if f.endswith(".vtt")]
        ja_files  = [f for f in vtt_files if ".ja." in f or f.endswith(".ja.vtt")]
        en_files  = [f for f in vtt_files if ".en." in f or f.endswith(".en.vtt")]
        chosen    = (ja_files or en_files or vtt_files)
        sub_lang  = "ja" if ja_files else ("en" if en_files else "")
        subtitle_text = ""
        if chosen:
            raw_vtt = open(os.path.join(work, chosen[0]), encoding="utf-8", errors="ignore").read()
            subtitle_text = parse_vtt(raw_vtt)[:2000]

        # 3. 上位コメント（いいね順）
        top_comments = []
        if comments:
            for c in sorted(comments, key=lambda x: x.get("like_count", 0), reverse=True)[:5]:
                text = (c.get("text") or "")[:120].replace("\n", " ")
                top_comments.append(f"👍{c.get('like_count',0):,}  {text}")

        # 4. 説明文中のURLからドメイン抽出
        desc_urls = re.findall(r"https?://[^\s\)\"'<>]+", description)
        domains   = sorted({urllib.parse.urlparse(u).netloc for u in desc_urls if urllib.parse.urlparse(u).netloc})

        # 5. チャプター情報（秒 → MM:SS）
        def sec_to_mmss(s):
            s = int(s)
            return f"{s // 60:02d}:{s % 60:02d}"

        chapter_lines = [
            f"`{sec_to_mmss(c['start_time'])}` {c['title']}"
            for c in chapters
        ]

        # ── フォーマット ──
        lines = [
            f"**📺 YouTube分析** | <{url}>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"**{title}**",
            f"👤 {uploader}  📅 {upload_date}  ⏱ {duration}",
            f"▶️ {views:,}回視聴  👍 {likes:,}",
        ]
        if tags:
            lines.append(f"🏷️ {', '.join(tags)}")

        lines += ["", "**📝 説明文:**", description[:1000] or "(なし)"]

        if domains:
            lines += ["", f"**🔗 説明文内リンク ({len(domains)}件):**"]
            lines += [f"  • {d}" for d in domains[:15]]

        if chapter_lines:
            lines += ["", f"**📑 チャプター ({len(chapters)}件):**"]
            lines += chapter_lines[:20]

        if subtitle_text:
            lang_label = f"（{sub_lang}）" if sub_lang else ""
            lines += ["", f"**📄 字幕{lang_label}（冒頭）:**", subtitle_text[:1500]]

        if top_comments:
            lines += ["", "**💬 上位コメント:**"] + top_comments

        return "\n".join(lines)

    finally:
        shutil.rmtree(work, ignore_errors=True)


def analyze_instagram(url: str) -> str:
    # yt-dlpでまず試みる（クッキーあり→なしフォールバック）
    data, _ = _ytdlp_fetch_json([], url, timeout=60)
    try:
        if data is None:
            raise ValueError("fetch failed")
        title       = data.get("title") or ""
        description = (data.get("description") or "")[:1500]
        uploader    = data.get("uploader") or data.get("channel") or ""
        likes       = data.get("like_count") or 0
        views       = data.get("view_count") or 0

        lines = [
            f"**📸 Instagram分析** | <{url}>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"👤 {uploader}  👍 {likes:,}" + (f"  ▶️ {views:,}回" if views else ""),
        ]
        if title:
            lines.append(f"**タイトル:** {title}")
        lines += ["", "**📝 キャプション:**", description or "(なし)"]
        return "\n".join(lines)

    except json.JSONDecodeError:
        # fallback: instaloader
        return _instagram_instaloader(url)


def _instagram_instaloader(url: str) -> str:
    shortcode_m = re.search(r"/(?:p|reel|tv)/([\w\-]+)", url)
    if not shortcode_m:
        return f"❌ Instagram URL解析失敗: {url}"
    shortcode = shortcode_m.group(1)
    work = tempfile.mkdtemp(prefix="ig-")
    try:
        out = run(
            ["instaloader", "--no-videos", "--no-video-thumbnails",
             "--dirname-pattern", work, "--", f"-{shortcode}"],
            timeout=60,
        )
        # キャプション .txt ファイルを読む
        for fname in os.listdir(work):
            if fname.endswith(".txt") and "UTC" in fname:
                caption = open(os.path.join(work, fname), encoding="utf-8").read()[:1500]
                return (
                    f"**📸 Instagram分析（instaloader）** | <{url}>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"**📝 キャプション:**\n{caption}"
                )
        return f"**📸 Instagram** | <{url}>\n{out[:800]}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def analyze_url(url: str) -> str:
    if YT_RE.search(url):
        return analyze_youtube(url)
    if IG_RE.search(url):
        return analyze_instagram(url)
    return f"❌ 未対応のURL: {url}"


# ── 即実行コマンド ─────────────────────────────────────────────────────────────

def do_status() -> str:
    raw = run(["systemctl", "list-units", "ai-brain*", "--no-pager", "--no-legend", "--all"])
    rows = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name   = parts[0].replace(".service", "").replace("ai-brain-", "")
        active = parts[2]
        rows.append(f"{'✅' if active == 'active' else '❌'} `{name}` — {active} / {parts[3]}")
    return "**VPS サービス状態**\n" + "\n".join(rows) if rows else "サービス情報なし"


def do_sync() -> str:
    out = run(["systemctl", "start", "ai-brain-sync.service"])
    return "✅ 同期を開始しました（30秒ほどで完了します）" if not out else f"⚠️ {out[:500]}"


def do_restart(svc_raw: str) -> str:
    svc = safe_service(svc_raw)
    if not svc:
        return f"❌ 不明なサービス: `{svc_raw}`\n許可: {', '.join(sorted(ALLOWED_SERVICES))}"
    out = run(["systemctl", "restart", svc])
    return f"✅ `{svc}` を再起動しました" if not out else f"⚠️ 再起動:\n```\n{out[:600]}\n```"


def do_log(svc_raw: str) -> str:
    svc = safe_service(svc_raw)
    if not svc:
        return f"❌ 不明なサービス: `{svc_raw}`\n許可: {', '.join(sorted(ALLOWED_SERVICES))}"
    out = run(["journalctl", "-u", svc, "-n", "20", "--no-pager"])
    return f"**`{svc}` ログ（最新20行）**\n```\n{trim(out)}\n```" if out else f"`{svc}` のログが見つかりません"


# ── Notion ────────────────────────────────────────────────────────────────────

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
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(text)}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(f"Discord: {discord_url}")}},
        ],
    })
    return f"✅ メモをNotionに保存しました\n→ {res.get('url','')}" if status == 200 else f"❌ 保存失敗 ({status})"


def queue_task(title: str, body: str, discord_url: str) -> tuple:
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
             "callout": {"rich_text": rt("次回 Claude Code セッション開始時に処理されます"), "icon": {"emoji": "⏳"}}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(body[:2000])}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(f"Discord: {discord_url}")}},
        ],
    })
    return (True, res.get("url", "")) if status == 200 else (False, f"登録失敗 ({status})")


# ── Discord Bot ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


class CopyView(discord.ui.View):
    """URL分析結果に付与する「📋 全文コピー」ボタン"""

    def __init__(self, full_text: str):
        super().__init__(timeout=600)  # 10分でタイムアウト
        self.full_text = full_text

    @discord.ui.button(label="📋 全文コピー", style=discord.ButtonStyle.secondary)
    async def copy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Discord markdown を除去してプレーンテキスト化
        plain = re.sub(r"\*\*(.*?)\*\*", r"\1", self.full_text)  # **bold** → bold
        plain = re.sub(r"`([^`\n]*)`", r"\1", plain)             # `code` → code
        plain = plain.strip()

        # コードブロック1件あたり最大1950文字（``` × 2 + \n × 2 のオーバーヘッド考慮）
        limit = 1950
        chunks = [plain[i:i + limit] for i in range(0, len(plain), limit)]
        total  = len(chunks)

        # 最初のchunkで即座に応答（インタラクション3秒タイムアウト回避）
        header = f"（1/{total}）\n" if total > 1 else ""
        await interaction.response.send_message(f"```\n{header}{chunks[0]}\n```")

        # 2件目以降はfollowupで続けて送信
        for idx, chunk in enumerate(chunks[1:], start=2):
            await interaction.followup.send(f"```\n（{idx}/{total}）\n{chunk}\n```")


async def send_to_notify(text: str, view: discord.ui.View = None):
    ch = client.get_channel(DISCORD_NOTIFY_CHANNEL_ID)
    if not ch:
        return
    chunks = [text[i:i + 1990] for i in range(0, min(len(text), 8000), 1990)]
    for i, chunk in enumerate(chunks):
        # ボタンは最後のメッセージにだけ付ける
        await ch.send(chunk, view=view if i == len(chunks) - 1 else None)


@client.event
async def on_ready():
    print(f"[discord-inbox-bot] 起動: {client.user}  #inbox={DISCORD_INBOX_CHANNEL_ID}  #通知={DISCORD_NOTIFY_CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != DISCORD_INBOX_CHANNEL_ID:
        return
    content = message.content.strip()
    if not content:
        return

    guild_id   = message.guild.id if message.guild else 0
    discord_url = f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"
    loop        = asyncio.get_event_loop()

    # ── URL分析（YouTube / Instagram）────────────────────────────────────────
    yt_m = YT_RE.search(content)
    ig_m = IG_RE.search(content)
    if yt_m or ig_m:
        url = (yt_m or ig_m).group(0)
        await message.add_reaction("🔍")
        await message.reply("🔍 URL分析中... 結果は #通知 に送ります（最大2分）")
        result = await loop.run_in_executor(None, lambda: analyze_url(url))
        header    = f"📊 **URL分析結果** (依頼: {message.author.display_name})\n"
        full_text = header + result
        await send_to_notify(full_text, view=CopyView(full_text))
        await message.add_reaction("✅")
        print(f"[url] {url[:80]}")
        return

    # ── テキストコマンドルーティング ────────────────────────────────────────
    text = content

    if re.match(r"^(help|ヘルプ|使い方)$", text, re.I):
        await message.reply(HELP_TEXT)
        return

    if re.match(r"^(status|状態|サービス確認|確認)$", text, re.I):
        result = await loop.run_in_executor(None, do_status)
        await message.add_reaction("✅")
        await message.reply(result)
        return

    if re.match(r"^(sync|同期)$", text, re.I):
        result = await loop.run_in_executor(None, do_sync)
        await message.add_reaction("✅")
        await message.reply(result)
        return

    m = re.match(r"^(restart|再起動)\s+(.+)", text, re.I)
    if m:
        result = await loop.run_in_executor(None, lambda: do_restart(m.group(2).strip()))
        await message.add_reaction("✅")
        await message.reply(result)
        return

    m = re.match(r"^(log|ログ)\s+(.+)", text, re.I)
    if m:
        result = await loop.run_in_executor(None, lambda: do_log(m.group(2).strip()))
        await message.add_reaction("✅")
        reply = result if len(result) <= 1990 else result[:1990]
        await message.reply(reply)
        return

    m = re.match(r"^(メモ|memo)[:：]\s*(.+)", text, re.I | re.DOTALL)
    if m:
        result = await loop.run_in_executor(None, lambda: do_memo(m.group(2).strip(), discord_url))
        await message.add_reaction("✅")
        await message.reply(result)
        return

    # ── Notionキュー登録 ─────────────────────────────────────────────────────
    lines = text.splitlines()
    title = f"[inbox] {lines[0][:60]}" if lines else "[inbox] タスク"
    ok, url_or_err = await loop.run_in_executor(None, lambda: queue_task(title, text, discord_url))
    await message.add_reaction("⏳")
    if ok:
        await message.reply(f"⏳ Notionキューに登録しました。次回ターミナル起動時に処理します。\n→ {url_or_err}")
    else:
        await message.reply(f"❌ キュー登録失敗: {url_or_err}")
    print(f"[queue] {message.author}: {text[:60]}")


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
    client.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
