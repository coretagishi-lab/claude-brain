#!/usr/bin/env python3
"""
STEP 2: #dmm-素材投稿 への投稿を検知 → Notionキューに登録（VPS常駐）

投稿フォーマット（tagishiが投稿する内容）:
  漫画タイトル
  https://x.com/... ← XのURL
  [画像添付: 漫画コマ画像]

時刻指定不要 → 次の空き枠（8:00 or 21:00 JST ±15〜30分ランダム）に自動スケジュール

Notion登録フィールド:
  - title, manga_title, image_url, source_discord_url, x_post_url
  - status: queued
  - publish_at: 自動で次の空き枠を割り当て

Bot反応:
  ✅ 登録成功 → リプライにNotionページURL + 予約時刻
  ❌ 画像なし → エラーリプライ
"""
import os, json, re, asyncio, random, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

import discord

DISCORD_BOT_TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_DMM_CHANNEL_ID = int(os.environ.get("DISCORD_DMM_CHANNEL_ID", "0"))
NOTION_TOKEN           = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID   = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION         = "2022-06-28"
CALENDAR_DB_ID         = "3831cad4-aa98-81c2-9c66-e7f9ee3597e9"

JST = timezone(timedelta(hours=9))

# 1日の投稿スロット（JST時刻）
SLOT_HOURS = [8, 21]


# ── Notion API ────────────────────────────────────────────────────────────────

def notion(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


# ── 空き枠探索 ────────────────────────────────────────────────────────────────

def get_occupied_slots(account="アカウント①", days=30):
    """カレンダーDBから予約済み・公開済みの日時リストを取得"""
    _, res = notion("POST", f"/databases/{CALENDAR_DB_ID}/query", {
        "filter": {"and": [
            {"property": "アカウント", "select": {"equals": account}},
            {"property": "ステータス", "select": {"does_not_equal": "キャンセル"}},
        ]},
        "page_size": 100,
    })
    occupied = []
    for page in res.get("results", []):
        date_val = page["properties"].get("公開日時", {}).get("date")
        if date_val and date_val.get("start"):
            try:
                dt = datetime.fromisoformat(date_val["start"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=JST)
                occupied.append(dt.astimezone(JST))
            except Exception:
                pass
    return occupied


def find_next_slot(account="アカウント①", not_before=None):
    """次の空き枠を返す（JST datetime）
    not_before: この日時より後のスロットのみ対象
    """
    occupied = get_occupied_slots(account)
    now = datetime.now(JST)
    search_from = not_before if not_before else now

    for day_offset in range(60):
        date = search_from.date() + timedelta(days=day_offset)
        for hour in SLOT_HOURS:
            candidate = datetime(date.year, date.month, date.day,
                                 hour, 0, 0, tzinfo=JST)
            if candidate <= now + timedelta(hours=1):
                continue
            if not_before and candidate <= not_before:
                continue
            is_occupied = any(
                abs((candidate - occ).total_seconds()) < 3600
                for occ in occupied
            )
            if not is_occupied:
                offset_min = random.randint(15, 30) * random.choice([-1, 1])
                return candidate + timedelta(minutes=offset_min)

    fallback = search_from + timedelta(days=61)
    return fallback.replace(hour=8, minute=random.randint(0, 30), second=0)


def register_to_calendar(manga_title, youtube_url, x_url,
                          publish_at, account="アカウント①"):
    """投稿カレンダーに予約済みエントリを作成"""
    title = f"秒で出しちゃった{manga_title}男の漫画"
    props = {
        "動画タイトル": {"title": rt(title)},
        "アカウント":   {"select": {"name": account}},
        "公開日時":     {"date": {"start": publish_at.isoformat()}},
        "ステータス":   {"select": {"name": "予約済み"}},
        "漫画タイトル": {"rich_text": rt(manga_title)},
    }
    if x_url:
        props["X URL"] = {"url": x_url}
    notion("POST", "/pages", {
        "parent": {"database_id": CALENDAR_DB_ID},
        "properties": props,
    })


def register_to_notion(manga_title, image_url, source_discord_url,
                        x_post_url="", publish_at=None):
    today = datetime.now(JST).strftime("%Y-%m-%d")
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
    if x_post_url:
        props["x_post_url"] = {"rich_text": rt(x_post_url)}
    if publish_at:
        props["publish_at"] = {"date": {"start": publish_at.isoformat()}}

    publish_str = publish_at.strftime("%m/%d %H:%M") if publish_at else "未定"
    blocks = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": rt(f"📅 予約投稿: {publish_str} JST"),
            "icon": {"emoji": "📅"},
        }},
        {"object": "block", "type": "callout", "callout": {
            "rich_text": rt("台本生成後にパイプラインが進みます。"),
            "icon": {"emoji": "⏳"},
        }},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("📎 素材情報")}},
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": rt(f"漫画タイトル: {label}")}},
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": rt(f"Discord投稿: {source_discord_url}")}},
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": rt(f"画像URL: {image_url}")}},
    ]
    if x_post_url:
        blocks.append({"object": "block", "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": rt(f"X URL: {x_post_url}")}})

    return notion("POST", "/pages", {
        "parent":     {"database_id": NOTION_CONTENT_DB_ID},
        "properties": props,
        "children":   blocks,
    })


# ── メッセージパース ───────────────────────────────────────────────────────────

def parse_message(content: str):
    """テキストから (manga_title, x_post_url) を抽出"""
    lines = [l.strip() for l in (content or "").strip().splitlines() if l.strip()]
    x_post_url = ""
    for line in lines:
        m = re.search(r"https?://\S+", line)
        if m:
            url = m.group(0).rstrip(".,)")
            if re.search(r"x\.com|twitter\.com", url):
                x_post_url = url

    manga_title = ""
    for line in lines:
        if not re.search(r"https?://", line):
            manga_title = line
            break

    return manga_title, x_post_url


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

    images = [a for a in message.attachments
              if a.content_type and a.content_type.startswith("image/")]
    if not images:
        await message.add_reaction("❌")
        await message.reply("⚠️ 画像が添付されていません。", delete_after=15)
        return

    manga_title, x_post_url = parse_message(message.content or "")
    image_url = " ".join(img.url for img in images)
    guild_id  = message.guild.id if message.guild else 0
    source_url = f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"

    loop = asyncio.get_event_loop()
    base = manga_title or "(タイトル未記載)"

    # ── バリエーション①: 次の空き枠 ──────────────────────────────────────
    slot1 = await loop.run_in_executor(None, find_next_slot)
    title1 = f"{base}①"
    status1, res1 = await loop.run_in_executor(
        None,
        lambda: register_to_notion(title1, image_url, source_url, x_post_url, slot1),
    )

    # ── バリエーション②: ①の7日後以降の空き枠 ───────────────────────────
    after = slot1 + timedelta(days=7)
    slot2 = await loop.run_in_executor(None, lambda: find_next_slot(not_before=after))
    title2 = f"{base}②"
    status2, res2 = await loop.run_in_executor(
        None,
        lambda: register_to_notion(title2, image_url, source_url, x_post_url, slot2),
    )

    # カレンダーに両方登録
    if status1 == 200:
        await loop.run_in_executor(
            None, lambda: register_to_calendar(title1, "", x_post_url, slot1))
    if status2 == 200:
        await loop.run_in_executor(
            None, lambda: register_to_calendar(title2, "", x_post_url, slot2))

    warnings = []
    if not manga_title:
        warnings.append("⚠️ タイトルを読み取れませんでした → Notionで編集してください")
    if not x_post_url:
        warnings.append("⚠️ XのURLが見つかりません → Notionで追記してください")

    if status1 == 200 and status2 == 200:
        s1 = slot1.strftime("%m/%d（%a） %H:%M")
        s2 = slot2.strftime("%m/%d（%a） %H:%M")
        reply_lines = (
            ["✅ 2本分をNotionキューに登録しました"]
            + warnings
            + [f"📅 ①: {s1} JST → {res1.get('url', '')}",
               f"📅 ②: {s2} JST → {res2.get('url', '')}"]
        )
        await message.add_reaction("✅")
        await message.reply("\n".join(reply_lines))
        print(f"[OK] 2本登録: {base}  ①{s1}  ②{s2}")
    else:
        await message.add_reaction("⚠️")
        await message.reply(f"❌ Notion登録に失敗しました（①:{status1} ②:{status2}）")
        print(f"[ERROR] 登録失敗 ①:{status1} ②:{status2}")


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
