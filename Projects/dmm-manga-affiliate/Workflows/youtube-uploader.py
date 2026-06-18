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

YOUTUBE_SCOPE = " ".join([
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
])
REDIRECT_URI  = "http://localhost:8080"

# YouTube動画のデフォルト設定
DEFAULT_CATEGORY   = "2"       # Entertainment
DEFAULT_PRIVACY    = "public"  # Notionで動画確認済みのため即公開
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
    publish_at_raw = props.get("publish_at", {}).get("date", {})
    return {
        "manga_title":   text("manga_title"),
        "youtube_title": text("youtube_title"),
        "description":   text("description"),
        "affiliate_url": props.get("affiliate_url", {}).get("url", ""),
        "x_post_url":    text("x_post_url"),
        "publish_at":    publish_at_raw.get("start") if publish_at_raw else None,
    }


CALENDAR_DB_ID = "3831cad4-aa98-81c2-9c66-e7f9ee3597e9"

def find_calendar_entry(manga_title: str) -> str:
    """漫画タイトルで既存カレンダーエントリを検索してpage_idを返す（なければ空文字）"""
    _, res = notion("POST", f"/databases/{CALENDAR_DB_ID}/query", {
        "filter": {"property": "漫画タイトル", "rich_text": {"contains": manga_title[:10]}},
    })
    for page in res.get("results", []):
        props = page["properties"]
        existing = "".join(p.get("plain_text", "") for p in props.get("漫画タイトル", {}).get("rich_text", []))
        if existing == manga_title:
            return page["id"]
    return ""


def register_to_calendar(manga_title: str, youtube_url: str, x_url: str,
                          account: str = "アカウント①", publish_at: str = None):
    """既存カレンダーエントリを更新、なければ作成する"""
    status = "予約済み" if publish_at else "公開済み"
    date_str = publish_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")
    title = f"秒で出しちゃった{manga_title}男の漫画"

    existing_id = find_calendar_entry(manga_title)
    if existing_id:
        # 既存エントリを更新（YouTube URL・ステータスのみ）
        notion("PATCH", f"/pages/{existing_id}", {
            "properties": {
                "YouTube URL": {"url": youtube_url},
                "ステータス":  {"select": {"name": status}},
            }
        })
        log(f"📅 カレンダー更新: {manga_title} → {status}")
    else:
        # 新規作成
        notion("POST", "/pages", {
            "parent": {"database_id": CALENDAR_DB_ID},
            "properties": {
                "動画タイトル": {"title": rt(title)},
                "アカウント":   {"select": {"name": account}},
                "公開日時":     {"date": {"start": date_str}},
                "ステータス":   {"select": {"name": status}},
                "YouTube URL":  {"url": youtube_url},
                "X URL":        {"url": x_url} if x_url else {"url": None},
                "漫画タイトル": {"rich_text": rt(manga_title)},
            }
        })
        log(f"📅 カレンダー新規登録: {manga_title} → {status}")


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
                 tags: list = None, privacy: str = DEFAULT_PRIVACY,
                 publish_at: str = None) -> str:
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
            "privacyStatus":           "private" if publish_at else privacy,
            "selfDeclaredMadeForKids": False,
            **({"publishAt": publish_at} if publish_at else {}),
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


def set_thumbnail(video_id: str, thumbnail_path: Path):
    """動画のサムネイルを設定する"""
    access_token = get_access_token()
    img_data = thumbnail_path.read_bytes()
    req = urllib.request.Request(
        f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
        data=img_data, method="POST",
        headers={
            "Authorization":  f"Bearer {access_token}",
            "Content-Type":   "image/png",
            "Content-Length": str(len(img_data)),
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            log("✅ サムネイル設定完了")
    except urllib.error.HTTPError as e:
        log(f"⚠️  サムネイル設定失敗 ({e.code}) → スキップ（YouTube Studioから手動設定可）")


def update_description(video_id: str, title: str, x_url: str):
    """動画の概要欄を更新する"""
    access_token = get_access_token()

    # 現在のスニペットを取得
    req = urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        current = json.loads(r.read())

    snippet = current["items"][0]["snippet"]
    snippet["description"] = (
        f"【{title}】の続きはこちら👇\n"
        f"{x_url}\n\n"
        f"気になった方はXの投稿からアフィリエイトリンクへ！\n\n"
        f"#漫画 #マンガ #Shorts #漫画紹介 #おすすめ漫画"
    )

    body = json.dumps({"id": video_id, "snippet": snippet}).encode()
    req = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/videos?part=snippet",
        data=body, method="PUT",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        log("✅ 概要欄を更新しました")


def post_comment(video_id: str, x_url: str):
    """動画にコメントを投稿する"""
    access_token = get_access_token()

    body = json.dumps({
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {
                    "textOriginal": f"続きはこちら⬇️\n{x_url}"
                }
            }
        }
    }).encode()

    req = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        }
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                log("✅ コメントを投稿しました")
                return
        except urllib.error.HTTPError as e:
            if attempt < 2:
                log(f"  コメント投稿リトライ中... ({attempt+1}/3)")
                time.sleep(5)
            else:
                log(f"⚠️  コメント投稿失敗 ({e.code}) → スキップ（後でYouTube Studioから手動追加可）")


# ── pending コメント管理 ──────────────────────────────────────────────────────
PENDING_FILE = Path.home() / ".config" / "dmm-youtube" / "pending_comments.json"


def save_pending_comment(video_id: str, x_url: str, title: str, manga_title: str = ""):
    """公開待ちコメントをpendingリストに保存"""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    pending = json.loads(PENDING_FILE.read_text()) if PENDING_FILE.exists() else []
    pending.append({
        "video_id":    video_id,
        "x_url":       x_url,
        "title":       title,
        "manga_title": manga_title,
        "added_at":    datetime.now().isoformat(),
    })
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))


def get_video_privacy(video_id: str) -> str:
    """YouTube APIで動画の公開設定を取得"""
    access_token = get_access_token()
    req = urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3/videos?part=status&id={video_id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    items = data.get("items", [])
    if not items:
        return "deleted"
    return items[0]["status"]["privacyStatus"]


def check_and_post_pending():
    """pendingリストをチェックして公開済み動画にコメント投稿"""
    if not PENDING_FILE.exists():
        return

    pending = json.loads(PENDING_FILE.read_text())
    if not pending:
        return

    remaining = []
    for item in pending:
        video_id = item["video_id"]
        x_url    = item["x_url"]
        title    = item.get("title", "")

        privacy = get_video_privacy(video_id)

        if privacy == "public":
            log(f"🎉 公開検知: {title} ({video_id})")
            post_comment(video_id, x_url)
            # カレンダーを「公開済み」に更新
            manga_title = item.get("manga_title", "")
            if manga_title:
                existing_id = find_calendar_entry(manga_title)
                if existing_id:
                    notion("PATCH", f"/pages/{existing_id}", {
                        "properties": {"ステータス": {"select": {"name": "公開済み"}}}
                    })
                    log(f"📅 カレンダー更新: 公開済み ({manga_title})")
        elif privacy == "deleted":
            log(f"🗑  削除済みのためスキップ: {video_id}")
        else:
            remaining.append(item)  # まだ非公開 → 残す

    PENDING_FILE.write_text(json.dumps(remaining, ensure_ascii=False, indent=2))


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts アップローダー")
    parser.add_argument("--auth",          action="store_true", help="初回認証（ブラウザが開きます）")
    parser.add_argument("--check-pending", action="store_true", help="公開待ちコメントをチェックして投稿")
    parser.add_argument("--video",       type=str, default="", help="動画ファイルパス")
    parser.add_argument("--title",       type=str, default="", help="動画タイトル")
    parser.add_argument("--description", type=str, default="", help="動画説明文")
    parser.add_argument("--x-url",       type=str, default="", help="XポストURL（概要欄・コメントに追加）")
    parser.add_argument("--page-id",     type=str, default="", help="NotionページIDから情報を取得")
    parser.add_argument("--privacy",     type=str, default=DEFAULT_PRIVACY,
                        choices=["private", "unlisted", "public"], help="公開設定")
    args = parser.parse_args()

    if args.auth:
        run_auth_flow()
        return

    if args.check_pending:
        check_and_post_pending()
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
        manga_title = props.get("manga_title", "")
        if not title:
            clean_manga = re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩]+$', '', manga_title).strip()
            title = f"続きはコメ欄⬇️【{clean_manga}】 #漫画 #Shorts" if clean_manga else ""
        description = description or (props.get("description") or "") + "\n" + (props.get("affiliate_url") or "")

    if not video_path or not video_path.exists():
        print("❌ 動画ファイルを --video で指定してください")
        sys.exit(1)
    if not title:
        # タイトル未指定の場合はデフォルト
        title = "続きはコメ欄⬇️ #漫画 #Shorts"

    # Notionからpublish_atを取得
    publish_at = None
    props = {}
    if args.page_id and NOTION_TOKEN:
        props = get_notion_page(args.page_id)
        publish_at = props.get("publish_at")

    # publish_atが未来なら予約投稿、過去or未設定なら即公開
    if publish_at:
        from datetime import datetime, timezone
        try:
            pub_dt = datetime.fromisoformat(publish_at)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt <= datetime.now(timezone.utc):
                publish_at = None  # 過去の時刻は即公開
        except Exception:
            publish_at = None

    print(f"\n📺 YouTube投稿開始")
    print(f"   動画: {video_path.name}")
    print(f"   タイトル: {title}")
    if publish_at:
        print(f"   予約公開: {publish_at}")
    else:
        print(f"   公開設定: 即公開")

    video_id, video_url = upload_video(video_path, title, description,
                                        privacy=args.privacy, publish_at=publish_at)

    # X URLが指定されていれば概要欄・コメントに追加
    x_url = args.x_url
    if not x_url:
        x_url = props.get("x_post_url", "")

    # サムネイル設定（動画と同名の _thumb.png があれば自動セット）
    thumbnail_path = video_path.parent / f"{video_path.stem}_thumb.png"
    if thumbnail_path.exists():
        log("🖼  サムネイル設定中（動画処理待機10秒）...")
        time.sleep(10)
        set_thumbnail(video_id, thumbnail_path)
    else:
        log("ℹ️  サムネイルファイルなし → スキップ")

    if x_url:
        log("📝 概要欄を更新中...")
        update_description(video_id, title, x_url)
        if publish_at:
            save_pending_comment(video_id, x_url, title, manga_title=props.get("manga_title", ""))
            log("💬 コメント保存済み（公開後に自動投稿）")
        else:
            log("💬 コメント投稿中...")
            post_comment(video_id, x_url)

    # Notionページを更新 + 投稿カレンダーに記録
    if args.page_id and NOTION_TOKEN:
        update_notion_uploaded(args.page_id, video_url)
        _manga_title = props.get("manga_title", "") if args.page_id else ""
        register_to_calendar(_manga_title, video_url, x_url or "", publish_at=publish_at)
        log("✅ Notion更新 + カレンダー登録完了")

    print(f"""
════════════════════════════════════════════
📺 投稿完了!
   URL: {video_url}
   ID:  {video_id}
   ※ 「{args.privacy}」設定で投稿されました
{"   🐦 XのURL → 概要欄・コメントに追加済み" if x_url else ""}
════════════════════════════════════════════""")


if __name__ == "__main__":
    main()
