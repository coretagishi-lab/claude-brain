#!/usr/bin/env python3
"""
Mac launchd 毎日2:00: Notionの競合分析キューを処理する

処理フロー:
  1. Notion 競合分析DB から status:queued を取得
  2. yt-dlp で各動画の詳細情報（タイトル・説明文・コメント・サムネ）を収集
  3. Claude API に一括投入して分析レポートを生成
  4. Notion にレポートを保存（status → done）
  5. Discord #通知 に完了通知

分析内容:
  - タイトルの言い回し傾向
  - 冒頭30秒の構成パターン（チャプター情報から推定）
  - コメントで反応が良い要素
  - サムネイルの文字・配置パターン（Claude vision）
  - 「続きが気になる」「課金した」系コメントが多い動画の共通点
  - Canvaテンプレートへの改善アドバイス

環境変数:
  ANTHROPIC_API_KEY, NOTION_TOKEN, NOTION_COMPETITIVE_DB_ID,
  DISCORD_WEBHOOK_URL
"""
import base64, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

ANTHROPIC_API_KEY     = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_TOKEN          = os.environ.get("NOTION_TOKEN", "")
NOTION_COMPETITIVE_DB = os.environ.get("NOTION_COMPETITIVE_DB_ID", "")
DISCORD_WEBHOOK_URL   = os.environ.get("DISCORD_WEBHOOK_URL", "")
NOTION_VERSION        = "2022-06-28"
MODEL                 = "claude-sonnet-4-6"
YTDLP_COOKIES         = str(Path.home() / ".config" / "ai-brain" / "youtube-cookies.txt")

PRICE_IN  = 3.0   # $3/MTok
PRICE_OUT = 15.0  # $15/MTok


# ── Notion ────────────────────────────────────────────────────────────────────

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


def get_queued_jobs():
    _, res = notion("POST", f"/databases/{NOTION_COMPETITIVE_DB}/query", {
        "filter": {"property": "status", "select": {"equals": "queued"}},
        "sorts":  [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def get_page_urls(page_id: str) -> list:
    """ページbodyからURLリストをJSONパース"""
    _, res = notion("GET", f"/blocks/{page_id}/children")
    for block in res.get("results", []):
        if block.get("type") == "code":
            text = "".join(r.get("plain_text", "") for r in block["code"]["rich_text"])
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    return []


def update_status(page_id: str, status: str):
    notion("PATCH", f"/pages/{page_id}", {
        "properties": {"status": {"select": {"name": status}}}
    })


def save_report(page_id: str, report: str, canva_advice: str, cost: float, video_count: int):
    """分析レポートをNotionページに保存"""
    notion("PATCH", f"/pages/{page_id}", {
        "properties": {
            "status":       {"select":    {"name": "done"}},
            "canva_advice": {"rich_text": rt(canva_advice[:2000])},
            "video_count":  {"number":    video_count},
        }
    })
    # レポート本文をblockとして追加
    sections = report.split("\n## ")
    blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "callout",
         "callout": {
             "rich_text": rt(f"分析完了: {datetime.now().strftime('%Y-%m-%d %H:%M')}  コスト: ${cost:.4f}"),
             "icon": {"emoji": "✅"},
         }},
    ]
    for section in sections:
        if not section.strip():
            continue
        header = section.split("\n")[0].strip()
        body   = "\n".join(section.split("\n")[1:]).strip()
        if header:
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": rt(f"## {header}" if not header.startswith("#") else header)},
            })
        for para in body.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": rt(para[:2000])},
            })
    notion("PATCH", f"/blocks/{page_id}/children", {"children": blocks[:100]})


# ── yt-dlp データ収集 ─────────────────────────────────────────────────────────

def ytdlp_cookies_args():
    return ["--cookies", YTDLP_COOKIES] if os.path.exists(YTDLP_COOKIES) else []


def fetch_video_data(url: str, work_dir: str) -> dict:
    """1動画の詳細情報を取得"""
    vid_id = re.search(r"[?&]v=([\w-]+)", url)
    vid_id = vid_id.group(1) if vid_id else url.split("/")[-1]

    ejs = ["--js-runtimes", "node", "--remote-components", "ejs:github"]
    base_cmd = ["yt-dlp", "--dump-json", "--skip-download", "--no-playlist",
                "--no-warnings", "--write-comments",
                "--extractor-args", "youtube:max_comments=50,30,5"] + ejs

    # クッキーありで試行 → 失敗時はなしで再試行
    for cookies in [ytdlp_cookies_args(), []]:
        try:
            proc = subprocess.run(
                base_cmd + cookies + [url],
                capture_output=True, text=True, timeout=60
            )
            data = json.loads(proc.stdout)

            # サムネイル取得（Claude vision用）
            thumb_b64, thumb_type = None, None
            thumb_url = data.get("thumbnail") or ""
            if thumb_url:
                try:
                    req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as res:
                        ct = res.headers.get("content-type", "image/jpeg").split(";")[0]
                        thumb_b64 = base64.b64encode(res.read()).decode()
                        thumb_type = ct
                except Exception:
                    pass

            return {
                "id":          vid_id,
                "url":         url,
                "title":       data.get("title", ""),
                "description": (data.get("description") or "")[:600],
                "view_count":  data.get("view_count") or 0,
                "like_count":  data.get("like_count") or 0,
                "duration":    data.get("duration_string") or "",
                "chapters":    data.get("chapters") or [],
                "tags":        (data.get("tags") or [])[:10],
                "upload_date": data.get("upload_date") or "",
                "comments":    (data.get("comments") or [])[:30],
                "thumb_b64":   thumb_b64,
                "thumb_type":  thumb_type,
            }
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            if not cookies:
                return {"id": vid_id, "url": url, "error": "fetch_failed"}
            continue
    return {"id": vid_id, "url": url, "error": "fetch_failed"}


# ── Claude API 分析 ────────────────────────────────────────────────────────────

def build_video_summary(v: dict, idx: int) -> str:
    """1動画の情報をテキストに整形"""
    if v.get("error"):
        return f"[動画{idx+1}] {v['url']} — 取得失敗\n"

    lines = [
        f"[動画{idx+1}] {v['title']}",
        f"  URL: {v['url']}",
        f"  再生数: {v['view_count']:,}  いいね: {v['like_count']:,}  長さ: {v['duration']}",
        f"  タグ: {', '.join(v['tags'][:6])}",
        f"  説明文: {v['description'][:200]}",
    ]
    if v.get("chapters"):
        chaps = [f"{int(c['start_time'])//60:02d}:{int(c['start_time'])%60:02d} {c['title']}"
                 for c in v["chapters"][:5]]
        lines.append(f"  チャプター: {' / '.join(chaps)}")

    # コメント（いいね数上位 + キーワード検索）
    comments = v.get("comments") or []
    top_cmts = sorted(comments, key=lambda c: c.get("like_count", 0), reverse=True)[:5]
    kw_cmts = [c for c in comments
               if any(kw in (c.get("text") or "")
                      for kw in ["続き", "課金", "購入", "気になる", "泣いた", "最高", "もう一度"])][:3]
    all_cmts = {c.get("id"): c for c in top_cmts + kw_cmts}.values()
    for c in all_cmts:
        lines.append(f"  コメント(👍{c.get('like_count',0)}): {(c.get('text') or '')[:80]}")

    return "\n".join(lines)


def analyze_with_claude(genre: str, videos: list) -> tuple:
    """全動画データをClaudeに一括投入して分析レポートを生成"""

    # テキストサマリー作成
    summaries = [build_video_summary(v, i) for i, v in enumerate(videos)]
    videos_text = "\n\n".join(summaries)

    # サムネイル画像（最大5枚まで）を収集
    thumb_images = []
    for v in videos:
        if v.get("thumb_b64") and len(thumb_images) < 5:
            thumb_images.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": v["thumb_type"],
                    "data": v["thumb_b64"],
                }
            })

    system = """あなたは日本の漫画アフィリエイト動画の競合分析専門家です。
収集したYouTube Shorts動画のデータを分析し、バイラルになる要素を特定します。
分析対象: 漫画系・ドキドキ・続きが気になる系・アダルト寄りコンテンツ"""

    user_content = []
    if thumb_images:
        user_content.append({
            "type": "text",
            "text": f"以下は上位再生動画のサムネイル画像です（最大5枚）:"
        })
        user_content.extend(thumb_images)

    user_content.append({
        "type": "text",
        "text": f"""ジャンル「{genre}」の競合動画{len(videos)}本を分析してください。

## 収集データ
{videos_text}

## 分析レポート（以下の構成でMarkdown形式で出力）

## タイトルの言い回し傾向
（高再生数タイトルに共通するパターン、感情を煽るキーワード等）

## 冒頭30秒の構成パターン
（チャプター情報・説明文から読み取れるオープニングの型）

## コメントで反応が良い要素
（いいね数が多いコメントから読み取れる視聴者が刺さる要素）

## サムネイルの文字・配置パターン
（サムネイル画像から読み取れるテキスト配置・色使い・強調方法）

## 「続きが気になる」「課金した」系コメントが多い動画の共通点
（購買・課金行動を促すコンテンツの特徴）

## 高再生数TOP5の共通点
（再生数上位動画から抽出した絶対条件）

## Canvaテンプレートへの改善アドバイス
（現在のテンプレートに対して具体的に変えるべき要素。
テロップのフォント・サイズ・色・位置、サムネイルのレイアウト、
冒頭の演出など、実装可能な具体的改善策を5点以上）"""
    })

    payload = {
        "model":      MODEL,
        "max_tokens": 4000,
        "system":     system,
        "messages":   [{"role": "user", "content": user_content}],
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        })

    with urllib.request.urlopen(req, timeout=120) as res:
        resp = json.loads(res.read())

    report  = resp["content"][0]["text"]
    usage   = resp.get("usage", {})
    cost    = (usage.get("input_tokens", 0) * PRICE_IN +
               usage.get("output_tokens", 0) * PRICE_OUT) / 1_000_000

    # Canvaアドバイスセクションを抽出
    m = re.search(r"## Canvaテンプレートへの改善アドバイス\n(.*?)(?=\n## |\Z)", report, re.DOTALL)
    canva_advice = m.group(1).strip()[:2000] if m else ""

    return report, canva_advice, cost


# ── Discord通知 ───────────────────────────────────────────────────────────────

def notify_discord(text: str):
    if not DISCORD_WEBHOOK_URL:
        return
    body = json.dumps({"content": text[:2000]}).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    missing = [k for k in ["ANTHROPIC_API_KEY", "NOTION_TOKEN", "NOTION_COMPETITIVE_DB_ID"]
               if not os.environ.get(k)]
    if missing:
        print(f"[competitive-analyzer] ❌ 未設定: {', '.join(missing)}")
        sys.exit(1)

    print(f"[competitive-analyzer] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    jobs = get_queued_jobs()
    if not jobs:
        print("[competitive-analyzer] queued件数: 0  終了")
        return

    print(f"[competitive-analyzer] {len(jobs)}件処理します")
    total_cost = 0.0

    for job in jobs:
        def txt(k):
            parts = job["properties"].get(k, {}).get("rich_text", [])
            return "".join(p.get("plain_text", "") for p in parts)

        page_id = job["id"]
        genre   = txt("genre")
        notion_url = job.get("url", "")
        print(f"\n  ジャンル: {genre}")

        # 処理中に変更
        update_status(page_id, "analyzing")

        # URLリスト取得
        url_list = get_page_urls(page_id)
        if not url_list:
            print(f"  ⚠️ URLリストが空 → スキップ")
            update_status(page_id, "error")
            continue

        print(f"  動画数: {len(url_list)}")

        # 各動画データを収集
        work = tempfile.mkdtemp(prefix="comp-")
        try:
            videos = []
            for i, item in enumerate(url_list):
                url = item.get("url") or item if isinstance(item, str) else ""
                if not url:
                    continue
                print(f"  [{i+1}/{len(url_list)}] {item.get('title','')[:40]}")
                vdata = fetch_video_data(url, work)
                videos.append(vdata)
                time.sleep(1)  # レート制限対策

            # Claude API で一括分析
            print(f"  🤖 Claude API で分析中（{len(videos)}本）...")
            report, canva_advice, cost = analyze_with_claude(genre, videos)
            total_cost += cost
            print(f"  コスト: ${cost:.4f}")

            # Notionに保存
            save_report(page_id, report, canva_advice, cost, len(videos))
            print(f"  ✅ レポート保存完了")

            # Discord通知
            notify_discord(
                f"📊 **競合分析完了**: {genre}\n"
                f"分析動画数: {len(videos)}本  コスト: ${cost:.4f}\n"
                f"→ {notion_url}"
            )

        except Exception as e:
            print(f"  ❌ 失敗: {e}")
            update_status(page_id, "error")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    print(f"\n[competitive-analyzer] 完了  合計コスト: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
