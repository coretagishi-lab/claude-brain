#!/usr/bin/env python3
"""
x-poster.py — X (Twitter) 自動投稿 + アフィURL短縮

使い方:
  python3 x-poster.py --text "テキスト"
  python3 x-poster.py --notion-page-id <ID> --youtube-url <URL>

Notionページから自動で情報取得して投稿する場合は --notion-page-id を指定。
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

# ── 設定 ─────────────────────────────────────────────────────────────────────
CREDS_FILE   = Path.home() / ".config" / "dmm-x" / "credentials.json"

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"

TWEET_MAX_LEN = 280


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── X OAuth1 ──────────────────────────────────────────────────────────────────
def load_creds() -> OAuth1:
    if not CREDS_FILE.exists():
        print(f"❌ 認証ファイルが見つかりません: {CREDS_FILE}")
        sys.exit(1)
    c = json.loads(CREDS_FILE.read_text())
    return OAuth1(
        c["api_key"], c["api_secret"],
        c["access_token"], c["access_token_secret"]
    )


def post_tweet(text: str) -> dict:
    """ツイートを投稿してレスポンスを返す"""
    auth = load_creds()
    res = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text[:TWEET_MAX_LEN]},
        timeout=30
    )
    if not res.ok:
        print(f"❌ X投稿失敗 ({res.status_code}): {res.text}")
        sys.exit(1)
    return res.json()


def get_tweet_url(tweet_id: str, screen_name: str = "") -> str:
    """ツイートのURLを返す"""
    # screen_nameが不明な場合はXの短縮形式を使う
    return f"https://x.com/i/web/status/{tweet_id}"


# ── URL短縮 (TinyURL) ─────────────────────────────────────────────────────────
def shorten_url(url: str) -> str:
    """TinyURLでURLを短縮する（無料・登録不要）"""
    if not url:
        return ""
    try:
        res = urllib.request.urlopen(
            f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}",
            timeout=10
        )
        short = res.read().decode().strip()
        return short if short.startswith("https://") else url
    except Exception as e:
        log(f"⚠️  URL短縮失敗: {e} → 元URLを使用")
        return url


# ── Notion ────────────────────────────────────────────────────────────────────
def notion(method: str, path: str, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def rt(text: str) -> list:
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def get_notion_page(page_id: str) -> dict:
    _, res = notion("GET", f"/pages/{page_id}")
    props = res.get("properties", {})
    def text(k):
        return "".join(p.get("plain_text", "") for p in props.get(k, {}).get("rich_text", []))
    return {
        "manga_title":   text("manga_title"),
        "youtube_title": text("youtube_title"),
        "affiliate_url": props.get("affiliate_url", {}).get("url", ""),
    }


def update_notion_x_url(page_id: str, tweet_url: str, short_affiliate_url: str):
    """NotionページにXポストURLと短縮アフィURLを記録"""
    notion("PATCH", f"/blocks/{page_id}/children", {"children": [{
        "object": "block", "type": "callout", "callout": {
            "rich_text": rt(
                f"🐦 X投稿完了\n"
                f"URL: {tweet_url}\n"
                f"アフィURL（短縮）: {short_affiliate_url}\n"
                f"投稿日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            ),
            "icon": {"type": "emoji", "emoji": "🐦"},
            "color": "blue_background",
        }
    }]})


# ── ツイートテキスト生成 ──────────────────────────────────────────────────────
def build_tweet(manga_title: str, short_url: str, youtube_url: str) -> str:
    """投稿テキストを組み立てる"""
    lines = []
    if manga_title:
        lines.append(f"【{manga_title}】")
    lines.append("続きはこちら👇")
    if short_url:
        lines.append(short_url)
    if youtube_url:
        lines.append(f"\n▶ {youtube_url}")
    lines.append("\n#漫画 #マンガ #Shorts #漫画紹介")
    return "\n".join(lines)


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="X自動投稿スクリプト")
    parser.add_argument("--text",             type=str, default="", help="投稿テキスト（直接指定）")
    parser.add_argument("--notion-page-id",   type=str, default="", help="NotionページIDから情報取得")
    parser.add_argument("--youtube-url",      type=str, default="", help="YouTube動画URL")
    parser.add_argument("--affiliate-url",    type=str, default="", help="アフィリエイトURL（省略時はNotionから取得）")
    args = parser.parse_args()

    manga_title   = ""
    affiliate_url = args.affiliate_url
    youtube_url   = args.youtube_url
    text          = args.text

    # Notionから情報取得
    if args.notion_page_id and NOTION_TOKEN:
        props = get_notion_page(args.notion_page_id)
        manga_title   = props.get("manga_title", "")
        affiliate_url = affiliate_url or props.get("affiliate_url", "")
        log(f"📄 Notion取得: {manga_title}")

    # アフィURLを短縮
    short_url = ""
    if affiliate_url:
        log("🔗 URL短縮中...")
        short_url = shorten_url(affiliate_url)
        log(f"   {affiliate_url[:50]}... → {short_url}")

    # ツイートテキスト組み立て
    if not text:
        text = build_tweet(manga_title, short_url, youtube_url)

    print(f"\n投稿テキスト:\n{'─'*40}\n{text}\n{'─'*40}")
    print(f"文字数: {len(text)}/280\n")

    # 投稿
    log("🐦 X投稿中...")
    result = post_tweet(text)
    tweet_id  = result["data"]["id"]
    tweet_url = get_tweet_url(tweet_id)
    log(f"✅ 投稿完了: {tweet_url}")

    # Notion更新
    if args.notion_page_id and NOTION_TOKEN:
        update_notion_x_url(args.notion_page_id, tweet_url, short_url)
        log("✅ Notion更新完了")

    print(f"""
════════════════════════════════════════════
🐦 X投稿完了!
   URL: {tweet_url}
   ID:  {tweet_id}
════════════════════════════════════════════""")

    return tweet_url


if __name__ == "__main__":
    main()
