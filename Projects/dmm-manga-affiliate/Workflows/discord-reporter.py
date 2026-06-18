#!/usr/bin/env python3
"""
discord-reporter.py — 毎日Discordに日次レポートを送信

内容:
  - 全アカウントの総再生数・いいね数
  - 気になる改善ポイント（離脱率が高い動画など）
  - DMM売上（CSVがあれば自動集計、なければ前回値を表示）

実行タイミング: 毎日21:00（launchd経由）
"""
import json, os, re, sys, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from pathlib import Path

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
TOKEN_FILE      = Path.home() / ".config" / "dmm-youtube" / "token.json"
VAULT           = Path(__file__).resolve().parents[3]
ANALYTICS_CACHE = VAULT / "Projects" / "dmm-manga-affiliate" / "Knowledge" / "analytics_cache.json"
DMM_CSV_DIR     = Path.home() / "Desktop" / "ClaudeProjects" / "漫画アフィリエイト:売上レポート"

# 複数アカウントのtokenファイル
TOKEN_FILES = {
    "アカウント①": Path.home() / ".config" / "dmm-youtube" / "token.json",
    # アカウント追加時: "アカウント②": Path.home() / ".config" / "dmm-youtube" / "token_2.json",
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_access_token(token_file: Path) -> str:
    token = json.loads(token_file.read_text())
    body = urllib.parse.urlencode({
        "client_id":     token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    with urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST"),
        timeout=30
    ) as r:
        return json.loads(r.read())["access_token"]


def check_video_health(token_file: Path) -> list:
    """投稿済み動画の異常を検知してアラートを返す"""
    alerts = []
    try:
        access_token = get_access_token(token_file)
        # 直近10本の動画を取得
        req = urllib.request.Request(
            "https://www.googleapis.com/youtube/v3/search"
            "?part=id&forMine=true&type=video&maxResults=10&order=date",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        video_ids = [item["id"]["videoId"] for item in data.get("items", [])]
        if not video_ids:
            return alerts

        # 各動画のステータスを確認
        ids_param = ",".join(video_ids)
        req2 = urllib.request.Request(
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=status,statistics,contentDetails&id={ids_param}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            vdata = json.loads(r.read())

        for item in vdata.get("items", []):
            status = item.get("status", {})
            stats  = item.get("statistics", {})
            vid_id = item["id"]
            views  = int(stats.get("viewCount", 0))
            upload = status.get("uploadStatus", "")
            privacy = status.get("privacyStatus", "")

            # 異常検知
            if upload == "failed":
                alerts.append(f"🚨 動画アップロード失敗: https://youtube.com/shorts/{vid_id}")
            elif upload == "rejected":
                alerts.append(f"🚨 動画が拒否されました: https://youtube.com/shorts/{vid_id}")
            elif privacy == "public" and views < 10:
                # 公開から48時間以上経っているのに10未満の場合のみ警告
                # (投稿直後は正常)
                pass  # Analytics APIで投稿日時チェックは別途

    except Exception as e:
        log(f"  ⚠️  ヘルスチェック失敗: {e}")

    return alerts


def get_channel_daily_stats(token_file: Path) -> dict:
    """1アカウントの昨日の再生数・いいねを取得"""
    try:
        access_token = get_access_token(token_file)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        url = (
            "https://youtubeanalytics.googleapis.com/v2/reports"
            f"?ids=channel==MINE"
            f"&startDate={yesterday}&endDate={yesterday}"
            f"&metrics=views,likes,estimatedMinutesWatched,averageViewPercentage"
        )
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())

        rows = data.get("rows", [])
        if not rows:
            return {"views": 0, "likes": 0, "minutes": 0, "avg_pct": 0}
        row = rows[0]
        return {
            "views":   int(row[0]),
            "likes":   int(row[1]),
            "minutes": float(row[2]),
            "avg_pct": float(row[3]),
        }
    except Exception as e:
        log(f"  ⚠️  Analytics取得失敗: {e}")
        return {"views": 0, "likes": 0, "minutes": 0, "avg_pct": 0}


def get_notable_insights() -> list:
    """analyticsキャッシュから気になる点を抽出"""
    if not ANALYTICS_CACHE.exists():
        return []
    cache = json.loads(ANALYTICS_CACHE.read_text())
    insights = []
    for video_id, data in cache.items():
        stats = data.get("stats", {})
        title = data.get("manga_title", video_id)
        avg_pct = stats.get("avg_view_percentage", 0)
        views   = stats.get("views", 0)
        if views > 0 and avg_pct < 30:
            insights.append(f"「{title}」平均視聴率 {avg_pct:.0f}% → 引きを改善")
        elif views > 100 and avg_pct > 60:
            insights.append(f"「{title}」好調 視聴率 {avg_pct:.0f}% 🔥")
    return insights[:3]


def parse_dmm_csv() -> dict:
    """DMMアフィリエイトのCSVから売上を集計（ファイルがあれば）"""
    if not DMM_CSV_DIR.exists():
        return {}
    csv_files = sorted(DMM_CSV_DIR.glob("*.csv"), reverse=True)
    if not csv_files:
        return {}

    latest = csv_files[0]
    total_revenue = 0
    total_clicks  = 0
    try:
        text = latest.read_text(encoding="utf-8-sig")
        for line in text.splitlines()[1:]:  # ヘッダー除く
            cols = line.split(",")
            if len(cols) >= 4:
                try:
                    total_clicks  += int(cols[2]) if cols[2].strip() else 0
                    total_revenue += int(cols[3].replace("¥", "").replace(",", "").strip()) if cols[3].strip() else 0
                except ValueError:
                    pass
        return {
            "revenue": total_revenue,
            "clicks":  total_clicks,
            "file":    latest.name,
        }
    except Exception:
        return {}


def send_discord(message: str):
    if not DISCORD_WEBHOOK:
        log("❌ DISCORD_WEBHOOK_URL 未設定")
        return
    body = json.dumps({"content": message}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (ai-brain, 1.0)",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            log(f"✅ Discord送信完了 ({r.status})")
    except Exception as e:
        log(f"❌ Discord送信失敗: {e}")


def build_report() -> str:
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
    lines = [f"📊 **デイリーレポート {yesterday}**", ""]

    # 全アカウントの合算
    total_views = 0
    total_likes = 0
    account_lines = []

    for account_name, token_file in TOKEN_FILES.items():
        if not token_file.exists():
            continue
        log(f"  {account_name} の集計中...")
        stats = get_channel_daily_stats(token_file)
        total_views += stats["views"]
        total_likes += stats["likes"]
        if stats["views"] > 0:
            account_lines.append(
                f"  {account_name}: {stats['views']:,}回 / いいね{stats['likes']:,} / 視聴率{stats['avg_pct']:.0f}%"
            )

    lines.append(f"▶️ **総再生数: {total_views:,}回**")
    lines.append(f"👍 総いいね: {total_likes:,}")
    if len(account_lines) > 1:
        lines += account_lines
    lines.append("")

    # DMM売上
    dmm = parse_dmm_csv()
    if dmm:
        lines.append(f"💰 **DMM売上: ¥{dmm['revenue']:,}**（クリック: {dmm['clicks']:,}）")
        lines.append(f"   ファイル: {dmm['file']}")
    else:
        lines.append("💰 DMM売上: CSVをここに置いてください")
        lines.append(f"   → `{DMM_CSV_DIR}`")
    lines.append("")

    # 異常検知アラート
    for token_file in TOKEN_FILES.values():
        if token_file.exists():
            alerts = check_video_health(token_file)
            if alerts:
                lines.append("🚨 **アラート**")
                for a in alerts:
                    lines.append(f"  {a}")
                lines.append("")

    # 気になる点
    insights = get_notable_insights()
    if insights:
        lines.append("💡 **気になる点**")
        for i in insights:
            lines.append(f"  → {i}")
    else:
        lines.append("✅ 特に気になる点なし")

    return "\n".join(lines)


def main():
    log("Discord日次レポート生成中...")
    report = build_report()
    print(report)
    send_discord(report)


if __name__ == "__main__":
    main()
