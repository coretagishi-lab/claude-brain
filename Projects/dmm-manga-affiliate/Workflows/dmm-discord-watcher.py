#!/usr/bin/env python3
"""
STEP 2: #dmm-素材投稿 への投稿を検知 → Notionキューに登録（VPS常駐）

投稿フォーマット（tagishiが投稿する内容）:
  漫画タイトル
  https://al.dmm.co.jp/?lurl=... ← アフィリエイトURL
  [画像添付: 漫画コマ画像]

Notion登録フィールド:
  - title:               [YYYY-MM-DD] 漫画タイトル
  - manga_title:         漫画タイトル
  - image_url:           Discord CDN URL（最初の画像）
  - source_discord_url:  Discord投稿URL
  - affiliate_url:       テキスト中のhttps://URL
  - status:              queued

Bot反応:
  ✅ 登録成功 → リプライにNotionページURL
  ❌ 画像なし → エラーリプライ

依存:
  pip3 install discord.py
"""
import os, json, re, asyncio, urllib.request, urllib.error
from datetime import datetime

import discord

DISCORD_BOT_TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_DMM_CHANNEL_ID = int(os.environ.get("DISCORD_DMM_CHANNEL_ID", "0"))
NOTION_TOKEN           = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID   = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION         = "2022-06-28"


# ── Notion API ────────────────────────────────────────────────────────────────

def notion_post(path, data):
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


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def register_to_notion(manga_title, image_url, source_discord_url, affiliate_url, x_post_url=""):
    today = datetime.now().strftime("%Y-%m-%d")
    label = manga_title if manga_title else "(タイトル未記載)"
    page_title = f"[{today}] {label}"

    props = {
        "title":              {"title": rt(page_title)},
        "manga_title":        {"rich_text": rt(label)},
        "image_url":          {"rich_text": [{"type": "text", "text": {"content": image_url}}]},
        "source_discord_url": {"url": source_discord_url},
        "status":             {"select": {"name": "queued"}},
        "created_at":         {"date": {"start": today}},
    }
    if affiliate_url:
        props["affiliate_url"] = {"url": affiliate_url}
    if x_post_url:
        props["x_post_url"] = {"rich_text": [{"type": "text", "text": {"content": x_post_url}}]}

    blocks = [
        {
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": rt("Mac定時処理が台本を生成します。status が draft になるまでお待ちください。"),
                "icon": {"emoji": "⏳"},
            },
        },
        {
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": rt("📎 素材情報")},
        },
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": rt(f"漫画タイトル: {label}")}},
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": rt(f"Discord投稿: {source_discord_url}")}},
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": rt(f"画像URL: {image_url}")}},
    ]
    if affiliate_url:
        blocks.append({
            "object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rt(f"アフィリエイトURL: {affiliate_url}")},
        })

    return notion_post("/pages", {
        "parent":     {"database_id": NOTION_CONTENT_DB_ID},
        "properties": props,
        "children":   blocks,
    })


# ── メッセージパース ───────────────────────────────────────────────────────────

def parse_message(content: str):
    """テキストから (manga_title, affiliate_url, x_post_url) を抽出"""
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]

    affiliate_url = ""
    x_post_url    = ""
    for line in lines:
        m = re.search(r"https?://\S+", line)
        if m:
            url = m.group(0).rstrip(".,)")
            if re.search(r"x\.com|twitter\.com", url):
                x_post_url = url
            else:
                affiliate_url = url

    manga_title = ""
    for line in lines:
        if not re.search(r"https?://", line):
            manga_title = line
            break

    return manga_title, affiliate_url, x_post_url


# ── Discord Bot ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"[dmm-discord-watcher] 起動完了: {client.user}  監視チャンネル: {DISCORD_DMM_CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != DISCORD_DMM_CHANNEL_ID:
        return

    # 画像添付チェック
    images = [
        a for a in message.attachments
        if a.content_type and a.content_type.startswith("image/")
    ]
    if not images:
        await message.add_reaction("❌")
        await message.reply(
            "⚠️ 画像が添付されていません。\n"
            "漫画コマ画像を添付して再投稿してください。",
            delete_after=15,
        )
        return

    manga_title, affiliate_url, x_post_url = parse_message(message.content or "")
    image_url        = " ".join(img.url for img in images)
    guild_id         = message.guild.id if message.guild else 0
    source_discord_url = (
        f"https://discord.com/channels/{guild_id}"
        f"/{message.channel.id}/{message.id}"
    )

    # Notionへの書き込みはブロッキングなのでスレッドで実行
    loop = asyncio.get_event_loop()
    status, res = await loop.run_in_executor(
        None,
        lambda: register_to_notion(manga_title, image_url, source_discord_url, affiliate_url, x_post_url),
    )

    if status == 200:
        notion_url = res.get("url", "")
        warnings = []
        if not manga_title:
            warnings.append("⚠️ タイトルを読み取れませんでした → Notionで編集してください")
        if not x_post_url:
            warnings.append("⚠️ XのURLが見つかりません → Notionで追記してください")

        reply_lines = ["✅ Notionキューに登録しました"] + warnings + [f"→ {notion_url}"]
        await message.add_reaction("✅")
        await message.reply("\n".join(reply_lines))
        print(f"[OK] Notion登録: {manga_title or '(無題)'}  {notion_url}")
    else:
        await message.add_reaction("⚠️")
        await message.reply(f"❌ Notion登録に失敗しました ({status})。VPSログを確認してください。")
        print(f"[ERROR] Notion登録失敗: {status}  {res}")


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    missing = [k for k, v in {
        "DISCORD_BOT_TOKEN":      DISCORD_BOT_TOKEN,
        "DISCORD_DMM_CHANNEL_ID": DISCORD_DMM_CHANNEL_ID,
        "NOTION_TOKEN":           NOTION_TOKEN,
        "NOTION_CONTENT_DB_ID":   NOTION_CONTENT_DB_ID,
    }.items() if not v]

    if missing:
        print(f"[ERROR] 環境変数未設定: {', '.join(missing)}")
        raise SystemExit(1)

    print(f"[dmm-discord-watcher] 監視チャンネルID: {DISCORD_DMM_CHANNEL_ID}")
    client.run(DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
