#!/usr/bin/env python3
"""
youtube-analytics.py — YouTube動画の分析 + Notionへのレポート投稿

フロー:
  1. Notionから投稿済み動画一覧を取得
  2. YouTube Analytics APIで各動画の指標を取得
     - 視聴回数・平均視聴率・視聴維持率（秒単位）
  3. video_job.jsonと照合して「テロップ何行目で何%が離脱したか」を特定
  4. 週次分析レポートをNotionに投稿
  5. 改善点を experience.md に反映

使い方:
  python3 youtube-analytics.py           # 全動画を分析してNotionにレポート
  python3 youtube-analytics.py --quick   # 最新5本だけ（デイリー用）
"""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from pathlib import Path

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_TASK_BOARD_ID = "3671cad4aa98813b85b2ed9e3127b913"
NOTION_VERSION       = "2022-06-28"
TOKEN_FILE           = Path.home() / ".config" / "dmm-youtube" / "token.json"
VAULT                = Path(__file__).resolve().parents[3]
EXPERIENCE_FILE      = VAULT / "Projects" / "dmm-manga-affiliate" / "Knowledge" / "experience.md"
ANALYTICS_CACHE      = VAULT / "Projects" / "dmm-manga-affiliate" / "Knowledge" / "analytics_cache.json"


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 認証 ─────────────────────────────────────────────────────────────────────
def get_access_token() -> str:
    token = json.loads(TOKEN_FILE.read_text())
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


def yt_get(path: str, params: dict) -> dict:
    access_token = get_access_token()
    url = f"https://youtubeanalytics.googleapis.com/v2{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}


def yt_data_get(path: str, params: dict) -> dict:
    access_token = get_access_token()
    url = f"https://www.googleapis.com/youtube/v3{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


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


def get_uploaded_videos(limit: int = 0) -> list:
    """Notionからuploaded状態の動画一覧を取得"""
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "uploaded"}},
        "sorts":  [{"property": "created_at", "direction": "descending"}],
        "page_size": limit if limit else 100,
    })
    pages = res.get("results", [])
    videos = []
    for page in pages:
        props = page["properties"]
        def text(k):
            return "".join(p.get("plain_text", "") for p in props.get(k, {}).get("rich_text", []))
        def title_text(k):
            return "".join(p.get("plain_text", "") for p in props.get(k, {}).get("title", []))

        # video_urlからYouTube IDを抽出
        blocks_content = ""
        _, blocks = notion("GET", f"/blocks/{page['id']}/children")
        for block in blocks.get("results", []):
            btype = block.get("type", "")
            for rt_item in block.get(btype, {}).get("rich_text", []):
                blocks_content += rt_item.get("plain_text", "") + "\n"

        video_id = ""
        m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]+)", blocks_content)
        if m:
            video_id = m.group(1)

        if video_id:
            videos.append({
                "page_id":     page["id"],
                "manga_title": text("manga_title") or title_text("title"),
                "video_id":    video_id,
                "script":      text("script"),
            })
    return videos


# ── YouTube Analytics ─────────────────────────────────────────────────────────
def get_video_stats(video_id: str) -> dict:
    """基本指標（視聴回数、平均視聴率など）を取得"""
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    res = yt_get("/reports", {
        "ids":        "channel==MINE",
        "startDate":  start,
        "endDate":    today,
        "metrics":    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments",
        "filters":    f"video=={video_id}",
    })
    if "error" in res:
        return {}

    rows = res.get("rows", [])
    if not rows:
        return {}

    row = rows[0]
    return {
        "views":                  int(row[0]),
        "estimated_minutes":      float(row[1]),
        "avg_view_duration_sec":  float(row[2]),
        "avg_view_percentage":    float(row[3]),
        "likes":                  int(row[4]),
        "comments":               int(row[5]),
    }


def get_retention_data(video_id: str) -> list:
    """視聴維持率データを取得（0.0〜1.0の各点での残存率）"""
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    res = yt_get("/reports", {
        "ids":        "channel==MINE",
        "startDate":  start,
        "endDate":    today,
        "metrics":    "audienceWatchRatio",
        "dimensions": "elapsedVideoTimeRatio",
        "filters":    f"video=={video_id}",
    })
    if "error" in res:
        return []

    return [[float(row[0]), float(row[1])] for row in res.get("rows", [])]


def get_video_duration(video_id: str) -> float:
    """YouTube APIで動画の総尺を取得（秒）"""
    res = yt_data_get("/videos", {"part": "contentDetails", "id": video_id})
    items = res.get("items", [])
    if not items:
        return 0.0
    duration_str = items[0]["contentDetails"]["duration"]
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    minutes = int(m.group(1) or 0)
    seconds = int(m.group(2) or 0)
    return float(minutes * 60 + seconds)


# ── 分析ロジック ──────────────────────────────────────────────────────────────
def parse_telops_from_script(script: str) -> list:
    """台本から8行のテロップを抽出"""
    lines = [l.strip() for l in script.splitlines() if l.strip()]
    result = []
    for line in lines:
        clean = re.sub(r'^\d+\.\s*', '', line).strip()
        clean = re.sub(r'^[♂♀]', '', clean).strip()
        clean = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', clean).strip()
        if clean:
            result.append(clean)
    return result[:8]


def find_video_job(manga_title: str) -> dict:
    """audio/ディレクトリからvideo_job.jsonを検索"""
    audio_base = VAULT / "Projects" / "dmm-manga-affiliate" / "audio"
    if not audio_base.exists():
        return {}
    safe = re.sub(r'[^\w\-_]', '_', manga_title)[:20]
    for d in sorted(audio_base.iterdir(), reverse=True):
        if safe in d.name or manga_title[:5] in d.name:
            job_file = d / "video_job.json"
            if job_file.exists():
                return json.loads(job_file.read_text())
    return {}


def analyze_retention(retention: list, durations: list, total_sec: float) -> list:
    """
    視聴維持率データとスライド尺から
    「テロップ何行目で何%が離脱したか」を特定する
    """
    if not retention or not durations or total_sec == 0:
        return []

    # スライドの開始・終了時刻を計算
    # [intro(dur0), telop1..8, outro] → telop が durations[0..7]
    INTRO_DUR = 3.0
    OUTRO_DUR = 3.0
    slides = []
    t = 0.0
    slides.append({"name": "イントロ", "start": t, "end": t + INTRO_DUR})
    t += INTRO_DUR
    for i, d in enumerate(durations, 1):
        slides.append({"name": f"テロップ{['①','②','③','④','⑤','⑥','⑦','⑧'][i-1]}", "start": t, "end": t + d})
        t += d
    slides.append({"name": "アウトロ", "start": t, "end": t + OUTRO_DUR})

    results = []
    for slide in slides:
        start_ratio = slide["start"] / total_sec
        end_ratio   = slide["end"] / total_sec

        # 開始・終了時点の視聴率を補間
        def get_ratio_at(time_ratio):
            for j in range(len(retention) - 1):
                r0, w0 = retention[j]
                r1, w1 = retention[j + 1]
                if r0 <= time_ratio <= r1:
                    if r1 == r0:
                        return w0
                    return w0 + (w1 - w0) * (time_ratio - r0) / (r1 - r0)
            return retention[-1][1] if retention else 0.0

        watch_start = get_ratio_at(min(start_ratio, 1.0))
        watch_end   = get_ratio_at(min(end_ratio,   1.0))
        drop        = watch_start - watch_end

        results.append({
            "name":        slide["name"],
            "start_sec":   round(slide["start"], 1),
            "end_sec":     round(slide["end"], 1),
            "watch_start": round(watch_start * 100, 1),
            "watch_end":   round(watch_end   * 100, 1),
            "drop_pct":    round(drop * 100, 1),
        })

    return results


def format_retention_report(manga_title: str, stats: dict, slide_analysis: list, telops: list) -> str:
    """分析結果をテキストにまとめる"""
    lines = [f"## 📊 {manga_title}"]
    lines.append("")

    if stats:
        lines.append(f"- 視聴回数: {stats.get('views', 0):,}")
        lines.append(f"- 平均視聴率: {stats.get('avg_view_percentage', 0):.1f}%")
        lines.append(f"- 平均視聴時間: {stats.get('avg_view_duration_sec', 0):.1f}秒")
        lines.append(f"- いいね: {stats.get('likes', 0):,} / コメント: {stats.get('comments', 0):,}")
        lines.append("")

    if slide_analysis:
        lines.append("### 離脱分析")
        for s in slide_analysis:
            bar = "🔴" if s["drop_pct"] > 10 else "🟡" if s["drop_pct"] > 5 else "🟢"
            lines.append(
                f"{bar} {s['name']}: {s['watch_start']}% → {s['watch_end']}% "
                f"（離脱 {s['drop_pct']}%）"
            )

        # 最も離脱が多いスライドを特定
        if slide_analysis:
            worst = max(slide_analysis, key=lambda x: x["drop_pct"])
            if worst["drop_pct"] > 5 and telops:
                telop_idx = next(
                    (i for i, s in enumerate(slide_analysis) if s["name"] == worst["name"]),
                    None
                )
                if telop_idx and 0 < telop_idx <= len(telops):
                    lines.append("")
                    lines.append(f"⚠️ 最大離脱: {worst['name']} ({worst['drop_pct']}%離脱)")
                    lines.append(f"   テキスト: 「{telops[telop_idx - 1]}」")

    return "\n".join(lines)


# ── Notion レポート投稿 ───────────────────────────────────────────────────────
def post_analytics_report(report_text: str):
    """週次分析レポートをNotionタスクボードに投稿"""
    today = datetime.now().strftime("%Y-%m-%d")
    notion("POST", "/pages", {
        "parent": {"database_id": NOTION_TASK_BOARD_ID},
        "properties": {
            "タスク名":       {"title": rt(f"[分析レポート] {today}")},
            "プロジェクト名": {"select": {"name": "DMM漫画アフィリエイト"}},
            "ステータス":     {"select": {"name": "👀 確認待ち"}},
            "提出日時":       {"date": {"start": today}},
        },
        "children": [
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": rt(report_text[:2000])}},
        ]
    })


def update_experience(insights: list):
    """発見した改善点を experience.md に追記"""
    if not insights or not EXPERIENCE_FILE.exists():
        return
    content = EXPERIENCE_FILE.read_text()
    date_str = datetime.now().strftime("%Y-%m-%d")
    new_entries = f"\n\n## 分析結果 ({date_str})\n"
    for insight in insights:
        new_entries += f"- {insight}\n"
    # 「修正傾向ログ」セクションに追記
    if "## 修正傾向ログ" in content:
        content = content.replace(
            "（まだ記録なし）",
            new_entries
        ) if "（まだ記録なし）" in content else content + new_entries
    EXPERIENCE_FILE.write_text(content)
    log(f"✅ experience.md 更新: {len(insights)}件の知見")


# ── キャッシュ管理 ─────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if ANALYTICS_CACHE.exists():
        return json.loads(ANALYTICS_CACHE.read_text())
    return {}


def save_cache(cache: dict):
    ANALYTICS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ANALYTICS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="YouTube Analytics 分析スクリプト")
    parser.add_argument("--quick",  action="store_true", help="最新5本だけ分析（デイリー用）")
    parser.add_argument("--report", action="store_true", help="週次レポートをNotionに投稿")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        log("❌ NOTION_TOKEN 未設定")
        sys.exit(1)

    limit = 5 if args.quick else 0
    log(f"📊 投稿済み動画を取得中{'（最新5本）' if args.quick else ''}...")
    videos = get_uploaded_videos(limit=limit)
    log(f"  対象: {len(videos)}本")

    cache    = load_cache()
    all_reports = []
    insights    = []

    for video in videos:
        video_id    = video["video_id"]
        manga_title = video["manga_title"]
        log(f"\n📹 分析中: {manga_title} ({video_id})")

        # 基本指標
        stats = get_video_stats(video_id)
        if not stats:
            log("  ⚠️  データなし（まだ48時間経っていない可能性）")
            continue
        log(f"  視聴: {stats.get('views',0):,}回 / 平均視聴率: {stats.get('avg_view_percentage',0):.1f}%")

        # 視聴維持率
        retention   = get_retention_data(video_id)
        total_sec   = get_video_duration(video_id)
        telops      = parse_telops_from_script(video.get("script", ""))

        # video_job.jsonから尺情報を取得
        job         = find_video_job(manga_title)
        durations   = job.get("durations", [])

        slide_analysis = []
        if retention and durations and total_sec > 0:
            slide_analysis = analyze_retention(retention, durations, total_sec)

        # レポート生成
        report = format_retention_report(manga_title, stats, slide_analysis, telops)
        all_reports.append(report)
        log(f"  レポート生成完了")

        # 改善ポイントを抽出
        if slide_analysis:
            worst = max(slide_analysis, key=lambda x: x["drop_pct"])
            if worst["drop_pct"] > 15:
                idx = next((i for i, s in enumerate(slide_analysis) if s["name"] == worst["name"]), None)
                if idx and 0 < idx <= len(telops):
                    insights.append(
                        f"「{telops[idx-1]}」({worst['name']})で{worst['drop_pct']:.0f}%離脱 → "
                        f"このセリフの引きを強くする"
                    )
            avg_pct = stats.get("avg_view_percentage", 0)
            if avg_pct < 30:
                insights.append(f"平均視聴率{avg_pct:.0f}% → イントロの掴みを改善する必要あり")

        # キャッシュ更新
        cache[video_id] = {
            "manga_title":  manga_title,
            "stats":        stats,
            "updated_at":   datetime.now().isoformat(),
        }
        time.sleep(0.5)  # API制限対策

    save_cache(cache)

    # 週次レポートをNotionに投稿
    if args.report and all_reports:
        full_report = f"# YouTube分析レポート {datetime.now().strftime('%Y-%m-%d')}\n\n"
        full_report += "\n\n---\n\n".join(all_reports)
        if insights:
            full_report += "\n\n---\n\n## 🔧 改善提案\n"
            for i in insights:
                full_report += f"- {i}\n"
        post_analytics_report(full_report)
        log("✅ Notionにレポート投稿完了")

    # experience.md 更新
    if insights:
        update_experience(insights)
        log(f"\n💡 改善提案: {len(insights)}件")
        for i in insights:
            log(f"  → {i}")
    else:
        log("\n✅ 大きな改善ポイントなし")

    print(f"\n{'='*50}")
    print(f"分析完了: {len(videos)}本 / 改善提案: {len(insights)}件")
    print('='*50)


if __name__ == "__main__":
    main()
