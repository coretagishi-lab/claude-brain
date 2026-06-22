#!/usr/bin/env python3
"""
STEP 2: #dmm-素材投稿 への投稿を検知 → Notionキューに6件登録（VPS常駐）

1 Discord投稿 → 6エントリ自動生成
  ①②③ → アカウント① （アカウント①カレンダーで空き枠を探す）
  ④⑤⑥ → アカウント② （アカウント②カレンダーで空き枠を探す）

スケジュール計算:
  各アカウント独立して管理。1本目は直近空き枠、2本目は+7日、3本目は+14日。
  1日2枠（8:00 / 21:00）、毎回±15〜30分ランダムずらし。
"""
import os, json, re, asyncio, random, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

import discord

DISCORD_BOT_TOKEN      = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_DMM_CHANNEL_ID = int(os.environ.get("DISCORD_DMM_CHANNEL_ID", "0"))
NOTION_TOKEN           = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID   = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION         = "2022-06-28"
CALENDAR_DB_ID         = "3831cad4-aa98-81c2-9c66-e7f9ee3597e9"

JST = timezone(timedelta(hours=9))

# バリエーション設定
CIRCLES              = "①②③④⑤⑥"
VARIATIONS_PER_ACCT  = 3   # アカウントごとのバリエーション数
NUM_ACCOUNTS         = 2
ACCOUNT_NAMES        = {1: "アカウント①", 2: "アカウント②"}
SLOTS_OF_DAY         = [8, 21]  # 8:00 / 21:00


# ── Notion API ────────────────────────────────────────────────────────────────

def _notion(method: str, path: str, data=None):
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


# ── スケジュール計算 ───────────────────────────────────────────────────────────

def get_taken_slots(account_name: str) -> set:
    """Notionカレンダーから指定アカウントの予約済みスロット(datetime)セットを返す"""
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    _, res = _notion("POST", f"/databases/{CALENDAR_DB_ID}/query", {
        "filter": {"and": [
            {"property": "アカウント", "select": {"equals": account_name}},
            {"property": "公開日時",   "date":   {"on_or_after": today_str}},
        ]},
        "page_size": 100,
    })
    taken = set()
    for page in res.get("results", []):
        date_prop = page["properties"].get("公開日時", {}).get("date", {})
        start_str = date_prop.get("start") if date_prop else None
        if not start_str:
            continue
        try:
            dt = datetime.fromisoformat(start_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            taken.add(dt.astimezone(JST))
        except Exception:
            pass
    return taken


def find_next_slot(account_name: str, base_date: datetime, taken: set) -> datetime:
    """
    base_date以降でアカウントの次の空きスロット(JST)を返す。
    既取得のtakenセットを参照し、見つけたスロットはtakenに追加する。
    """
    now = datetime.now(JST)
    if base_date.tzinfo is None:
        base_date = base_date.replace(tzinfo=JST)
    start_day = base_date.replace(hour=0, minute=0, second=0, microsecond=0)

    for day_offset in range(90):
        check_day = start_day + timedelta(days=day_offset)
        for hour in SLOTS_OF_DAY:
            slot = check_day.replace(hour=hour, minute=0, second=0, microsecond=0)
            if slot <= now + timedelta(hours=1):
                continue
            # ±60分以内に既存予約があれば埋まりとみなす
            conflict = any(abs((slot - t).total_seconds()) <= 3600 for t in taken)
            if not conflict:
                jitter = random.randint(15, 30) * random.choice([-1, 1])
                result = slot + timedelta(minutes=jitter)
                taken.add(result)  # 次のバリエーション検索に反映
                return result
    return None  # 90日以内に空きなし（実際には起きない）


def format_notion_date(dt: datetime) -> str:
    """datetimeをNotion日付フォーマット(JST)に変換"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    jst = dt.astimezone(JST)
    return jst.strftime("%Y-%m-%dT%H:%M:%S+09:00")


# ── Notion 登録 ───────────────────────────────────────────────────────────────

def register_to_notion(manga_title, image_url, source_discord_url,
                       affiliate_url, x_post_url="", publish_at: datetime = None):
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
    if affiliate_url:
        props["affiliate_url"] = {"url": affiliate_url}
    if x_post_url:
        props["x_post_url"] = {"rich_text": [{"type": "text", "text": {"content": x_post_url}}]}
    if publish_at:
        props["publish_at"] = {"date": {"start": format_notion_date(publish_at)}}

    blocks = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": rt("Mac定時処理が台本を生成します。status が draft になるまでお待ちください。"),
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
    if affiliate_url:
        blocks.append({"object": "block", "type": "bulleted_list_item",
                       "bulleted_list_item": {"rich_text": rt(f"アフィリエイトURL: {affiliate_url}")}})
    if publish_at:
        blocks.append({"object": "block", "type": "bulleted_list_item",
                       "bulleted_list_item": {"rich_text": rt(f"公開予定: {format_notion_date(publish_at)}")}})

    return _notion("POST", "/pages", {
        "parent":     {"database_id": NOTION_CONTENT_DB_ID},
        "properties": props,
        "children":   blocks,
    })


def register_all_variations(manga_title, image_url, source_discord_url,
                             affiliate_url, x_post_url) -> list:
    """
    6バリエーション（①〜⑥）を全てNotionに登録。
    アカウントごとに独立してスロットを計算する。
    Returns: [(circle, account_name, publish_at, status, res), ...]
    """
    base = manga_title if manga_title else "(タイトル未記載)"
    now  = datetime.now(JST)

    # アカウントごとに取得済みスロットを管理（find_next_slotが内部で更新する）
    taken_per_account = {}
    for acc_num in range(1, NUM_ACCOUNTS + 1):
        taken_per_account[acc_num] = get_taken_slots(ACCOUNT_NAMES[acc_num])

    account_first_slot = {}  # アカウントごとの1本目スロット
    results = []

    for i in range(NUM_ACCOUNTS * VARIATIONS_PER_ACCT):
        circle          = CIRCLES[i]
        acc_num         = (i // VARIATIONS_PER_ACCT) + 1
        var_within_acc  = i % VARIATIONS_PER_ACCT
        acc_name        = ACCOUNT_NAMES[acc_num]
        title           = f"{base}{circle}"

        if var_within_acc == 0:
            slot = find_next_slot(acc_name, now, taken_per_account[acc_num])
            account_first_slot[acc_num] = slot
        else:
            first = account_first_slot[acc_num]
            base_date = first + timedelta(days=7 * var_within_acc) if first else now
            slot = find_next_slot(acc_name, base_date, taken_per_account[acc_num])

        status, res = register_to_notion(
            title, image_url, source_discord_url,
            affiliate_url, x_post_url, publish_at=slot,
        )
        results.append((circle, acc_name, slot, status, res))
        print(f"[登録] {title} → {acc_name} / {format_notion_date(slot) if slot else 'スロット未定'} : HTTP {status}")

    return results


# ── メッセージパース ───────────────────────────────────────────────────────────

def parse_message(content: str):
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
client  = discord.Client(intents=intents)


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
        await message.reply("⚠️ 画像が添付されていません。\n漫画コマ画像を添付して再投稿してください。",
                            delete_after=15)
        return

    manga_title, affiliate_url, x_post_url = parse_message(message.content or "")
    image_url = " ".join(img.url for img in images)
    guild_id  = message.guild.id if message.guild else 0
    source_discord_url = (
        f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"
    )

    loop    = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        lambda: register_all_variations(
            manga_title, image_url, source_discord_url, affiliate_url, x_post_url
        ),
    )

    ok_count  = sum(1 for _, _, _, s, _ in results if s == 200)
    err_count = len(results) - ok_count

    warnings = []
    if not manga_title:
        warnings.append("⚠️ タイトルを読み取れませんでした → Notionで編集してください")
    if not x_post_url:
        warnings.append("⚠️ XのURLが見つかりません → Notionで追記してください")

    # 登録サマリーをDiscordに返信
    lines = [f"✅ Notionキューに{ok_count}件登録しました（{err_count}件失敗）"] + warnings
    for circle, acc_name, slot, status, res in results:
        slot_str = format_notion_date(slot) if slot else "スロット未定"
        mark = "✅" if status == 200 else "❌"
        lines.append(f"  {mark} {circle} {acc_name}  公開予定: {slot_str}")

    await message.add_reaction("✅" if err_count == 0 else "⚠️")
    await message.reply("\n".join(lines))


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
