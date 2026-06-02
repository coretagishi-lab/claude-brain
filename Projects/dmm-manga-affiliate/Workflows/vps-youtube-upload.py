#!/usr/bin/env python3
"""
STEP 5 (VPS): Notionから status=final のコンテンツを取得 → YouTube自動投稿

- YouTube Data API v3 でアップロード
- 完了後 Notion の status を "uploaded" + video_url を記録

前提:
  - YOUTUBE_API_KEY (YouTube Data API v3 キー) in tokens.md
  - YOUTUBE_CHANNEL_ID in tokens.md
  - OAuth2認証済みの credentials.json が必要（初回のみ手動認証）

実行方法:
  python3 vps-youtube-upload.py
  python3 vps-youtube-upload.py --page-id <NOTION_PAGE_ID>

注意:
  YouTube Data API は OAuth2が必要。APIキーのみでのアップロードは不可。
  初回は `python3 vps-youtube-upload.py --auth` で認証フローを実行。
"""
import os, json, subprocess, urllib.request, urllib.error, argparse
from pathlib import Path
from datetime import datetime

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"

OUTPUT_DIR   = Path("/tmp/dmm-manga-output")
CREDS_PATH   = Path("/opt/ai-brain/.credentials/youtube-oauth.json")
TOKEN_PATH   = Path("/opt/ai-brain/.credentials/youtube-token.json")


def notion(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get_final_pages():
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "final"}},
    })
    return res.get("results", [])


def extract_props(page):
    def text(prop_name):
        parts = page["properties"].get(prop_name, {}).get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts)

    return {
        "page_id":       page["id"],
        "manga_title":   text("manga_title"),
        "youtube_title": text("youtube_title"),
        "description":   text("description"),
        "affiliate_url": page["properties"].get("affiliate_url", {}).get("url", ""),
    }


def find_video(manga_title):
    import re
    slug = re.sub(r"[^\w\-]", "_", manga_title).lower()
    for d in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if d.is_dir() and d.name.startswith(slug):
            finals = list(d.glob("*-final.mp4"))
            if finals:
                return finals[0]
    return None


def upload_to_youtube(video_path, title, description, tags=None):
    """
    youtube-upload ライブラリ使用（pip install youtube-upload）
    または Google API Python Client Library 使用
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("   ❌ google-api-python-client 未インストール")
        print("   pip3 install google-api-python-client google-auth-oauthlib")
        return None

    if not TOKEN_PATH.exists():
        print("   ❌ YouTube OAuth トークンなし。--auth オプションで認証してください")
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or ["漫画", "アフィリエイト", "DMMブックス", "漫画紹介"],
            "categoryId": "24",  # Entertainment
            "defaultLanguage": "ja",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True,
                            mimetype="video/mp4")
    request = youtube.videos().insert(part=",".join(body.keys()), body=body,
                                      media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    return f"https://www.youtube.com/watch?v={response['id']}"


def update_notion_uploaded(page_id, video_url):
    notion("PATCH", f"/pages/{page_id}", {
        "properties": {
            "status":    {"select": {"name": "uploaded"}},
            "video_url": {"url": video_url},
        }
    })


def do_auth():
    """YouTube OAuth2 初回認証フロー"""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("pip3 install google-auth-oauthlib")
        return

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    if not CREDS_PATH.exists():
        print(f"❌ {CREDS_PATH} が見つかりません")
        print("   Google Cloud Console から OAuth2 client_secret.json をダウンロードして配置してください")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✅ 認証完了: {TOKEN_PATH}")


def main():
    parser = argparse.ArgumentParser(description="STEP 5: YouTube自動投稿")
    parser.add_argument("--page-id", default="")
    parser.add_argument("--auth", action="store_true", help="YouTube OAuth2初回認証")
    args = parser.parse_args()

    if args.auth:
        do_auth()
        return

    missing = [v for v in ["NOTION_TOKEN", "NOTION_CONTENT_DB_ID"]
               if not os.environ.get(v)]
    if missing:
        print(f"❌ 環境変数未設定: {', '.join(missing)}")
        return

    if args.page_id:
        _, page = notion("GET", f"/pages/{args.page_id}")
        pages = [page]
    else:
        print("🔍 Notionから最終承認済みコンテンツを取得中...")
        pages = get_final_pages()

    if not pages:
        print("✅ 投稿待ちコンテンツなし")
        return

    print(f"📋 {len(pages)}件をYouTubeに投稿します")

    for page in pages:
        props = extract_props(page)
        print(f"\n📖 {props['manga_title']}")

        video_path = find_video(props["manga_title"])
        if not video_path:
            print(f"   ❌ 動画ファイルが見つかりません（{OUTPUT_DIR}）")
            continue

        print(f"   動画: {video_path}")
        print(f"   タイトル: {props['youtube_title']}")

        video_url = upload_to_youtube(
            video_path,
            props["youtube_title"],
            props["description"],
        )

        if video_url:
            update_notion_uploaded(props["page_id"], video_url)
            print(f"   ✅ 投稿完了: {video_url}")
        else:
            print(f"   ❌ 投稿失敗")


if __name__ == "__main__":
    main()
