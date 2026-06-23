#!/usr/bin/env python3
"""
youtube-analytics.py — デイリー YouTube Analytics レポート → Discord 送信

毎朝 10:00 (launchd) に自動実行。
全アカウントの前日比指標を集計して Discord に送る。

レポート形式:
  📊 YouTube Analytics (06-23→06-24)
  ▼ 全アカウント合計（前日比）
    再生 +142  登録者 +3  いいね +18
  ▼ アカウント警告
    0件
  ▼ 動画パフォーマンス（全アカウント合計）
    合計再生 +142  平均継続率 59%

使い方:
  python3 youtube-analytics.py        # デイリーレポート → Discord
  python3 youtube-analytics.py --dry  # ドライラン（Discord送信なし）
"""
import json, os, re, subprocess, sys, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"
DISCORD_WEBHOOK_URL  = os.environ.get("DISCORD_WEBHOOK_URL", "")

BASE_CREDS_DIR = Path.home() / ".config" / "dmm-youtube"
CLIENT_FILE    = BASE_CREDS_DIR / "client_secret.json"
CACHE_FILE     = Path.home() / "Library" / "ai-brain" / "analytics_cache.json"
JST            = timezone(timedelta(hours=9))


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 認証 ─────────────────────────────────────────────────────────────────────

def get_token_file(account: int) -> Path:
    d = BASE_CREDS_DIR / f"account{account}" / "token.json"
    if account == 1 and not d.exists():
        legacy = BASE_CREDS_DIR / "token.json"
        if legacy.exists():
            return legacy
    return d


def refresh_access_token(account: int) -> str:
    token_file = get_token_file(account)
    if not token_file.exists():
        return ""
    if not CLIENT_FILE.exists():
        return ""
    token_data  = json.loads(token_file.read_text())
    client_data = json.loads(CLIENT_FILE.read_text())["installed"]
    result = subprocess.run([
        "curl", "-s", "-X", "POST",
        "-d", urllib.parse.urlencode({
            "client_id":     client_data["client_id"],
            "client_secret": client_data["client_secret"],
            "refresh_token": token_data["refresh_token"],
            "grant_type":    "refresh_token",
        }),
        "https://oauth2.googleapis.com/token"
    ], capture_output=True, text=True, timeout=15)
    new_token = json.loads(result.stdout)
    return new_token.get("access_token", "")


def yt_data(path: str, params: dict, access_token: str) -> dict:
    url = f"https://www.googleapis.com/youtube/v3{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "msg": e.read().decode()[:100]}


def yt_analytics(params: dict, access_token: str) -> dict:
    url = f"https://youtubeanalytics.googleapis.com/v2/reports?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "msg": e.read().decode()[:100]}


# ── キャッシュ ────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


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
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {}


def get_uploaded_video_ids() -> dict:
    """Notionからuploaded動画のvideo_idをアカウント別に取得"""
    if not NOTION_TOKEN or not NOTION_CONTENT_DB_ID:
        return {}
    res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "uploaded"}},
        "page_size": 100,
    })
    result = {}
    for page in res.get("results", []):
        props = page["properties"]
        def txt(k):
            return "".join(p.get("plain_text", "") for p in props.get(k, {}).get("rich_text", []))
        manga_title = txt("manga_title")
        m = re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]$', manga_title)
        account = ((('①②③④⑤⑥⑦⑧⑨⑩'.index(m.group(0))) // 3) + 1) if m else 1
        blocks_res = notion("GET", f"/blocks/{page['id']}/children")
        for block in blocks_res.get("results", []):
            btype = block.get("type", "")
            for rt_item in block.get(btype, {}).get("rich_text", []):
                vm = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]+)", rt_item.get("plain_text", ""))
                if vm:
                    result.setdefault(account, [])
                    if vm.group(1) not in result[account]:
                        result[account].append(vm.group(1))
    return result


# ── Analytics 取得 ────────────────────────────────────────────────────────────

def get_yesterday_stats(access_token: str) -> dict:
    """前日比の指標をAnalytics APIで取得（2日前〜昨日の範囲 / API遅延対応）"""
    yesterday    = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    two_days_ago = (datetime.now(JST) - timedelta(days=2)).strftime("%Y-%m-%d")
    res = yt_analytics({
        "ids":       "channel==MINE",
        "startDate": two_days_ago,
        "endDate":   yesterday,
        "metrics":   "views,likes,subscribersGained,subscribersLost",
    }, access_token)
    if "error" in res or not res.get("rows"):
        return {"views": 0, "likes": 0, "subscribers_net": 0}
    total = {"views": 0, "likes": 0, "subscribers_net": 0}
    for row in res.get("rows", []):
        total["views"]           += int(row[0])
        total["likes"]           += int(row[1])
        total["subscribers_net"] += int(row[2]) - int(row[3])
    return total


def get_avg_view_percentage(access_token: str) -> float:
    """過去30日の平均視聴継続率を取得"""
    end   = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")
    res = yt_analytics({
        "ids":       "channel==MINE",
        "startDate": start,
        "endDate":   end,
        "metrics":   "averageViewPercentage",
    }, access_token)
    if "error" in res or not res.get("rows"):
        return 0.0
    return float(res["rows"][0][0])


def get_channel_status(access_token: str) -> str:
    """チャンネルのlongUploadsStatusを返す"""
    res = yt_data("/channels", {"part": "status", "mine": "true"}, access_token)
    items = res.get("items", [])
    if not items:
        return "unknown"
    return items[0].get("status", {}).get("longUploadsStatus", "unknown")


def check_removed_videos(video_ids: list, access_token: str) -> list:
    """削除/非公開になった動画IDのリストを返す"""
    if not video_ids:
        return []
    removed = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        res = yt_data("/videos", {"part": "status", "id": ",".join(batch)}, access_token)
        returned_ids = {item["id"] for item in res.get("items", [])}
        for vid_id in batch:
            if vid_id not in returned_ids:
                removed.append(vid_id)
    return removed


# ── Discord ───────────────────────────────────────────────────────────────────

def send_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        log("⚠️  DISCORD_WEBHOOK_URL 未設定 → 送信スキップ")
        return
    body = json.dumps({"content": message}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            log("📨 Discord送信完了")
    except Exception as e:
        log(f"⚠️  Discord送信失敗: {e}")


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="ドライラン（Discord送信なし）")
    args = parser.parse_args()

    today_str     = datetime.now(JST).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    log(f"📊 Analytics開始: {today_str}")

    cache = load_cache()

    # Notionから投稿済み動画IDをアカウント別に取得
    uploaded_by_account = get_uploaded_video_ids()
    for k, v in uploaded_by_account.items():
        log(f"account{k}: {len(v)}本")

    total_views       = 0
    total_subscribers = 0
    total_likes       = 0
    avg_pct_list      = []
    warnings          = []  # (account_num, message)

    for account in [1, 2]:
        token_file = get_token_file(account)
        if not token_file.exists():
            log(f"  account{account}: tokenなし → スキップ")
            continue

        log(f"\n  account{account} 取得中...")
        access_token = refresh_access_token(account)
        if not access_token:
            log(f"  account{account}: token取得失敗 → スキップ")
            continue

        # 昨日の指標
        stats = get_yesterday_stats(access_token)
        log(f"  再生{stats['views']:+d} / 登録者{stats['subscribers_net']:+d} / いいね{stats['likes']:+d}")
        total_views       += stats["views"]
        total_subscribers += stats["subscribers_net"]
        total_likes       += stats["likes"]

        # 平均視聴継続率（過去30日）
        avg_pct = get_avg_view_percentage(access_token)
        if avg_pct > 0:
            avg_pct_list.append(avg_pct)
            log(f"  平均継続率: {avg_pct:.1f}%")

        # チャンネル警告チェック
        long_uploads = get_channel_status(access_token)
        if long_uploads not in ("eligible", "allowed", "longUploadsUnspecified"):
            warnings.append((account, f"チャンネル制限: {long_uploads}"))
            log(f"  ⚠️  longUploadsStatus={long_uploads}")

        # 動画削除チェック
        video_ids = uploaded_by_account.get(account, [])
        removed   = check_removed_videos(video_ids, access_token)
        for vid_id in removed:
            warnings.append((account, f"動画削除/制限検知: {vid_id}"))
            log(f"  ⚠️  動画削除: {vid_id}")

    # 全アカウント平均継続率
    avg_pct_all = round(sum(avg_pct_list) / len(avg_pct_list), 1) if avg_pct_list else 0.0

    # レポート生成
    lines = [
        f"📊 YouTube Analytics ({yesterday_str}→{today_str})",
        "",
        "▼ 全アカウント合計（前日比）",
        f"  再生 {total_views:+d}  登録者 {total_subscribers:+d}  いいね {total_likes:+d}  継続率 {avg_pct_all:.0f}%",
        "",
        "▼ アカウント警告",
    ]
    if warnings:
        for account, msg in warnings:
            lines.append(f"  ⚠️ account{account}: {msg}")
    else:
        lines.append("  0件")

    report = "\n".join(lines)
    print(f"\n{report}\n")

    # キャッシュ保存
    cache[today_str] = {
        "total_views":       total_views,
        "total_subscribers": total_subscribers,
        "total_likes":       total_likes,
        "avg_pct":           avg_pct_all,
        "warnings_count":    len(warnings),
    }
    save_cache(cache)

    if not args.dry:
        send_discord(report)
    else:
        log("DRY RUN: Discord送信スキップ")

    log("完了")


if __name__ == "__main__":
    main()
