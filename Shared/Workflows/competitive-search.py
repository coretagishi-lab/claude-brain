#!/usr/bin/env python3
"""
VPS: ジャンル名でYouTube Shortsを検索してNotionキューに登録する
discord-inbox-bot.py から subprocess で呼び出される

Usage:
  python3 competitive-search.py "ドキドキ漫画" [--max 20]

登録内容:
  - Notion 競合分析DB に status:queued でページ作成
  - 収集URLリストをページbodyに記録
"""
import os, sys, json, re, subprocess, urllib.request, urllib.error, argparse
from datetime import datetime

NOTION_TOKEN          = os.environ.get("NOTION_TOKEN", "")
NOTION_COMPETITIVE_DB = os.environ.get("NOTION_COMPETITIVE_DB_ID", "")
YTDLP_COOKIES         = "/opt/ai-brain/.credentials/youtube-cookies.txt"
NOTION_VERSION        = "2022-06-28"

# 検索クエリテンプレ（日本語漫画ショート向け）
SEARCH_SUFFIXES = ["漫画 shorts", "マンガ ショート", "漫画動画"]


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
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def search_youtube_shorts(genre: str, max_results: int) -> list:
    """yt-dlp でYouTube Shortsを検索してURLリストを返す"""
    results = []
    seen_ids = set()

    for suffix in SEARCH_SUFFIXES:
        query = f"{genre} {suffix}"
        n = max_results // len(SEARCH_SUFFIXES) + 1

        cookies = ["--cookies", YTDLP_COOKIES] if os.path.exists(YTDLP_COOKIES) else []
        cmd = [
            "yt-dlp",
            f"ytsearch{n}:{query}",
            "--flat-playlist", "--dump-json", "--no-playlist",
            "--no-warnings",
            "--js-runtimes", "node", "--remote-components", "ejs:github",
        ] + cookies

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                vid_id = item.get("id", "")
                if not vid_id or vid_id in seen_ids:
                    continue

                duration = item.get("duration") or 0
                # Shorts: 60秒以下に絞る（duration=0は不明なので含める）
                if duration > 60:
                    continue

                seen_ids.add(vid_id)
                results.append({
                    "id":       vid_id,
                    "url":      f"https://www.youtube.com/watch?v={vid_id}",
                    "title":    item.get("title", ""),
                    "duration": duration,
                    "view_count": item.get("view_count") or 0,
                })

                if len(results) >= max_results:
                    break
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ タイムアウト: {query}", file=sys.stderr)
            continue

        if len(results) >= max_results:
            break

    return results[:max_results]


def register_to_notion(genre: str, videos: list) -> tuple:
    today = datetime.now().strftime("%Y-%m-%d")
    page_title = f"[{today}] 競合分析: {genre}"
    url_list_json = json.dumps(
        [{"url": v["url"], "title": v["title"], "duration": v["duration"]} for v in videos],
        ensure_ascii=False, indent=2
    )

    props = {
        "title":       {"title": rt(page_title)},
        "genre":       {"rich_text": rt(genre)},
        "status":      {"select": {"name": "queued"}},
        "video_count": {"number": len(videos)},
        "created_at":  {"date": {"start": today}},
    }

    blocks = [
        {"object": "block", "type": "callout",
         "callout": {
             "rich_text": rt("Mac定時処理（毎日2:00）が分析を実行します"),
             "icon": {"emoji": "⏳"},
         }},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt(f"📋 収集URL一覧（{len(videos)}件）")}},
    ]
    for v in videos:
        dur = f"{v['duration']}秒" if v['duration'] else "不明"
        blocks.append({
            "object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rt(f"{v['title'][:60]} ({dur}) {v['url']}")},
        })
    blocks += [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("🔢 URL JSON（analyzer用）")}},
        {"object": "block", "type": "code",
         "code": {"rich_text": rt(url_list_json[:2000]), "language": "json"}},
    ]

    return notion("POST", "/pages", {
        "parent":     {"database_id": NOTION_COMPETITIVE_DB},
        "properties": props,
        "children":   blocks,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("genre",      help="分析するジャンル名")
    parser.add_argument("--max", type=int, default=20, help="収集動画数（デフォルト20）")
    args = parser.parse_args()

    if not NOTION_TOKEN or not NOTION_COMPETITIVE_DB:
        print("❌ NOTION_TOKEN / NOTION_COMPETITIVE_DB_ID 未設定", file=sys.stderr)
        sys.exit(1)

    print(f"🔍 検索中: {args.genre} （最大{args.max}本）")
    videos = search_youtube_shorts(args.genre, args.max)

    if not videos:
        print("⚠️ 動画が見つかりませんでした")
        sys.exit(0)

    print(f"📋 {len(videos)}本収集 → Notionに登録中...")
    status, res = register_to_notion(args.genre, videos)

    if status == 200:
        print(f"✅ 登録完了: {res.get('url','')}")
        print(f"COUNT:{len(videos)}")   # discord-inbox-bot がパースする
        print(f"PAGE_URL:{res.get('url','')}")
    else:
        print(f"❌ Notion登録失敗 ({status})", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
