#!/usr/bin/env python3
"""
youtube-uploader.py — YouTube Shorts 投稿スクリプト

使い方:
  # 初回のみ: Google認証（ブラウザが開きます）
  python3 youtube-uploader.py --auth

  # 動画を投稿
  python3 youtube-uploader.py --video <mp4パス> --title "タイトル" --description "説明"

  # Notionページから自動で情報を取得して投稿
  python3 youtube-uploader.py --page-id <NotionページID>
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# ── 設定 ─────────────────────────────────────────────────────────────────────
CREDS_DIR    = Path.home() / ".config" / "dmm-youtube"
TOKEN_FILE   = CREDS_DIR / "token.json"
CLIENT_FILE  = CREDS_DIR / "client_secret.json"

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
REDIRECT_URI  = "http://localhost:8080"

# YouTube動画のデフォルト設定
DEFAULT_CATEGORY   = "2"       # Entertainment
DEFAULT_PRIVACY    = "private" # 最初はprivateで安全に
DEFAULT_TAGS       = ["漫画", "マンガ", "アニメ", "ショート", "Shorts"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Notion ────────────────────────────────────────────────────────────────────
def notion(method, path, data=None):
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


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def get_notion_page(page_id):
    _, res = notion("GET", f"/pages/{page_id}")
    props = res.get("properties", {})
    def text(k):
        return "".join(p.get("plain_text", "") for p in props.get(k, {}).get("rich_text", []))
    return {
        "manga_title":   text("manga_title"),
        "youtube_title": text("youtube_title"),
        "description":   text("description"),
        "affiliate_url": props.get("affiliate_url", {}).get("url", ""),
    }


def update_notion_uploaded(page_id, youtube_url):
    notion("PATCH", f"/pages/{page_id}", {
        "properties": {"status": {"select": {"name": "uploaded"}}}
    })
    notion("PATCH", f"/blocks/{page_id}/children", {"children": [{
        "object": "block", "type": "callout", "callout": {
            "rich_text": rt(f"📺 YouTube投稿完了\nURL: {youtube_url}\n投稿日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
            "icon": {"type": "emoji", "emoji": "📺"},
            "color": "green_background",
        }
    }]})


# ── OAuth2 ────────────────────────────────────────────────────────────────────
def load_client_secret():
    if not CLIENT_FILE.exists():
        print(f"""
❌ Google認証ファイルが見つかりません: {CLIENT_FILE}

以下の手順で取得してください:
  1. https://console.cloud.google.com/ を開く
  2. プロジェクト作成 → 「dmm-manga」など適当な名前
  3. 「APIとサービス」→「ライブラリ」→「YouTube Data API v3」を有効化
  4. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuthクライアントID」
  5. アプリの種類: 「デスクトップアプリ」を選択
  6. JSONをダウンロードして以下に保存:
     {CLIENT_FILE}
  7. 再度 python3 youtube-uploader.py --auth を実行
""")
        sys.exit(1)
    data = json.loads(CLIENT_FILE.read_text())
    creds = data.get("installed") or data.get("web") or {}
    return creds.get("client_id"), creds.get("client_secret")


class _AuthHandler(BaseHTTPRequestHandler):
    code = None
    def do_GET(self):
        _AuthHandler.code = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query
        ).get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write("<h2>OK! このタブを閉じてターミナルに戻ってください</h2>".encode("utf-8"))
    def log_message(self, *a): pass


def run_auth_flow():
    client_id, client_secret = load_client_secret()
    CREDS_DIR.mkdir(parents=True, exist_ok=True)

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(YOUTUBE_SCOPE)}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print("\n🌐 ブラウザが開きます。Googleアカウントにログインして許可してください...")
    time.sleep(1)
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), _AuthHandler)
    server.handle_request()

    code = _AuthHandler.code
    if not code:
        print("❌ 認証コードの取得に失敗しました")
        sys.exit(1)

    # コードをトークンに交換
    body = urllib.parse.urlencode({
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        token = json.loads(r.read())

    token["client_id"]     = client_id
    token["client_secret"] = client_secret
    TOKEN_FILE.write_text(json.dumps(token, indent=2))
    TOKEN_FILE.chmod(0o600)

    print(f"✅ 認証成功！トークンを保存しました: {TOKEN_FILE}")
    print("   次回から --auth は不要です。")


def get_access_token():
    if not TOKEN_FILE.exists():
        print("❌ 認証が完了していません。先に: python3 youtube-uploader.py --auth")
        sys.exit(1)

    token = json.loads(TOKEN_FILE.read_text())

    # refresh_tokenでアクセストークンを更新
    body = urllib.parse.urlencode({
        "client_id":     token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        refreshed = json.loads(r.read())

    return refreshed["access_token"]


# ── YouTube 投稿 ──────────────────────────────────────────────────────────────
def upload_video(video_path: Path, title: str, description: str,
                 tags: list = None, privacy: str = DEFAULT_PRIVACY) -> str:
    """動画をYouTubeにアップロードしてURLを返す"""
    access_token = get_access_token()
    tags = tags or DEFAULT_TAGS

    # メタデータ
    metadata = json.dumps({
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        tags,
            "categoryId":  DEFAULT_CATEGORY,
        },
        "status": {
            "privacyStatus":           privacy,
            "selfDeclaredMadeForKids": False,
        }
    }, ensure_ascii=False).encode("utf-8")

    # Step 1: Resumable uploadセッション開始
    init_url = (
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status"
    )
    req = urllib.request.Request(init_url, data=metadata, method="POST", headers={
        "Authorization":           f"Bearer {access_token}",
        "Content-Type":            "application/json; charset=UTF-8",
        "X-Upload-Content-Type":   "video/mp4",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        upload_url = r.headers["Location"]

    # Step 2: 動画データをアップロード
    video_bytes = video_path.read_bytes()
    file_size   = len(video_bytes)

    log(f"📤 アップロード中... ({file_size // (1024*1024)}MB)")
    req = urllib.request.Request(upload_url, data=video_bytes, method="PUT", headers={
        "Authorization":  f"Bearer {access_token}",
        "Content-Type":   "video/mp4",
        "Content-Length": str(file_size),
    })
    with urllib.request.urlopen(req, timeout=600) as r:
        result = json.loads(r.read())

    video_id  = result["id"]
    video_url = f"https://youtube.com/shorts/{video_id}"
    log(f"✅ 投稿完了: {video_url}")
    return video_id, video_url


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts アップローダー")
    parser.add_argument("--auth",        action="store_true", help="初回認証（ブラウザが開きます）")
    parser.add_argument("--video",       type=str, default="", help="動画ファイルパス")
    parser.add_argument("--title",       type=str, default="", help="動画タイトル")
    parser.add_argument("--description", type=str, default="", help="動画説明文")
    parser.add_argument("--page-id",     type=str, default="", help="NotionページIDから情報を取得")
    parser.add_argument("--privacy",     type=str, default=DEFAULT_PRIVACY,
                        choices=["private", "unlisted", "public"], help="公開設定")
    args = parser.parse_args()

    if args.auth:
        run_auth_flow()
        return

    # 動画ファイルの確認
    video_path = Path(args.video) if args.video else None

    # Notionページから情報取得
    title       = args.title
    description = args.description

    if args.page_id:
        if not NOTION_TOKEN:
            print("❌ NOTION_TOKEN が未設定です")
            sys.exit(1)
        props = get_notion_page(args.page_id)
        title       = title       or props.get("youtube_title") or props.get("manga_title", "")
        description = description or props.get("description", "") + "\n" + props.get("affiliate_url", "")

    if not video_path or not video_path.exists():
        print("❌ 動画ファイルを --video で指定してください")
        sys.exit(1)
    if not title:
        print("❌ タイトルを --title で指定してください")
        sys.exit(1)

    print(f"\n📺 YouTube投稿開始")
    print(f"   動画: {video_path.name}")
    print(f"   タイトル: {title}")
    print(f"   公開設定: {args.privacy}")

    video_id, video_url = upload_video(video_path, title, description,
                                        privacy=args.privacy)

    # Notionページを更新
    if args.page_id and NOTION_TOKEN:
        update_notion_uploaded(args.page_id, video_url)
        log("✅ Notion更新完了")

    print(f"""
════════════════════════════════════════════
📺 投稿完了!
   URL: {video_url}
   ID:  {video_id}
   ※ 「{args.privacy}」設定で投稿されました
════════════════════════════════════════════""")


if __name__ == "__main__":
    main()
