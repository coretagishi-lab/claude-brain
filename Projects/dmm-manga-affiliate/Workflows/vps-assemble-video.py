#!/usr/bin/env python3
"""
STEP 3 (VPS): Notionから承認済みコンテンツを取得 → VOICEVOX + ffmpeg で動画生成

- Notionで status=approved のページを取得
- VOICEVOX でナレーション音声を生成
- ffmpeg で動画アセンブル
- 完成後 status を "final" に更新（tagishiが最終確認）

実行方法:
  python3 vps-assemble-video.py                # 全承認済みを処理
  python3 vps-assemble-video.py --page-id <ID> # 特定ページのみ

依存:
  - NOTION_TOKEN, NOTION_CONTENT_DB_ID (環境変数)
  - VOICEVOX localhost:50021 (systemdサービス)
  - ffmpeg, ImageMagick (apt install)
  - 漫画パネル画像: /opt/ai-brain-media/panels/<manga_slug>/
"""
import os, json, re, subprocess, urllib.request, urllib.error, argparse, shutil
from pathlib import Path
from datetime import datetime

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"
VOICEVOX_URL         = "http://localhost:50021"
VOICEVOX_SPEAKER     = 30  # No.7アナウンス（ナレーション用）

OUTPUT_DIR  = Path("/tmp/dmm-manga-output")
MEDIA_DIR   = Path("/opt/ai-brain-media/panels")
VIDEO_W, VIDEO_H = 1080, 1920  # 9:16


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


def get_approved_pages():
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "approved"}},
        "sorts": [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def get_page(page_id):
    _, res = notion("GET", f"/pages/{page_id}")
    return res


def extract_props(page):
    def text(prop_name):
        parts = page["properties"].get(prop_name, {}).get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts)

    script_raw = text("script")
    script_lines = [l.strip() for l in script_raw.splitlines() if l.strip()]

    return {
        "page_id":       page["id"],
        "manga_title":   text("manga_title"),
        "youtube_title": text("youtube_title"),
        "description":   text("description"),
        "script":        script_lines,
        "affiliate_url": page["properties"].get("affiliate_url", {}).get("url", ""),
    }


def voicevox_synthesize(text, speaker, out_path):
    # 1. audio_query
    encoded = urllib.request.quote(text)
    req = urllib.request.Request(
        f"{VOICEVOX_URL}/audio_query?text={encoded}&speaker={speaker}",
        method="POST")
    with urllib.request.urlopen(req) as res:
        query = json.loads(res.read())

    # 2. synthesis
    body = json.dumps(query).encode()
    req = urllib.request.Request(
        f"{VOICEVOX_URL}/synthesis?speaker={speaker}",
        data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        out_path.write_bytes(res.read())


def get_audio_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    return float(result.stdout.strip())


def find_panels(manga_title):
    slug = re.sub(r"[^\w\-]", "_", manga_title).lower()
    panel_dir = MEDIA_DIR / slug
    if not panel_dir.exists():
        return []
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(p for p in panel_dir.iterdir() if p.suffix.lower() in exts)


def make_slide(image_path, audio_path, duration, out_path):
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
               f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:black",
        "-t", str(duration + 0.3),
        "-shortest", str(out_path),
    ], check=True, capture_output=True)


def concat_videos(video_paths, out_path):
    list_file = out_path.parent / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p}'" for p in video_paths), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_path),
    ], check=True, capture_output=True)
    list_file.unlink()


def update_notion_status(page_id, status, video_path=None):
    props = {"status": {"select": {"name": status}}}
    notion("PATCH", f"/pages/{page_id}", {"properties": props})


def process_page(props):
    slug = re.sub(r"[^\w\-]", "_", props["manga_title"]).lower()
    ts   = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = OUTPUT_DIR / f"{slug}-{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n📖 {props['manga_title']}")
    print(f"   台本: {len(props['script'])}行")

    panels = find_panels(props["manga_title"])
    if not panels:
        print(f"   ⚠️  パネル画像なし: {MEDIA_DIR / slug}")
        print(f"   → Notionキューに積みます")
        update_notion_status(props["page_id"], "approved")  # statusを戻す
        # vps-task-reporter.py 呼び出し（存在する場合）
        reporter = Path("/opt/ai-brain/Shared/Workflows/vps-task-reporter.py")
        if reporter.exists():
            subprocess.run([
                "python3", str(reporter),
                "--title", f"パネル画像なし: {props['manga_title']}",
                "--detail", f"パス {MEDIA_DIR / slug} に画像ファイルがありません。"
                            f"Googleドライブから手動配置が必要です。",
                "--project", "dmm-manga-affiliate",
            ])
        return None

    # 音声生成 + スライド動画生成
    slide_videos = []
    num_slides = min(len(props["script"]), len(panels))

    for i in range(num_slides):
        line  = props["script"][i]
        panel = panels[i % len(panels)]

        print(f"   [{i+1}/{num_slides}] VOICEVOX合成: {line[:30]}...")
        audio_path = work_dir / f"audio_{i:02d}.wav"
        try:
            voicevox_synthesize(line, VOICEVOX_SPEAKER, audio_path)
        except Exception as e:
            print(f"   ❌ VOICEVOX失敗: {e}")
            continue

        duration = get_audio_duration(audio_path)
        video_path = work_dir / f"slide_{i:02d}.mp4"
        make_slide(panel, audio_path, duration, video_path)
        slide_videos.append(video_path)

    if not slide_videos:
        print("   ❌ スライド生成失敗")
        return None

    # 結合
    final_path = work_dir / f"{slug}-{ts}-final.mp4"
    print(f"   🎬 動画を結合中 ({len(slide_videos)}スライド)...")
    concat_videos(slide_videos, final_path)

    print(f"   ✅ 完成: {final_path}")
    return final_path


def main():
    parser = argparse.ArgumentParser(description="STEP 3: 承認済みコンテンツを動画化")
    parser.add_argument("--page-id", default="", help="特定ページIDのみ処理")
    args = parser.parse_args()

    missing = [v for v in ["NOTION_TOKEN", "NOTION_CONTENT_DB_ID"]
               if not os.environ.get(v)]
    if missing:
        print(f"❌ 環境変数未設定: {', '.join(missing)}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.page_id:
        pages = [get_page(args.page_id)]
    else:
        print("🔍 Notionから承認済みコンテンツを取得中...")
        pages = get_approved_pages()

    if not pages:
        print("✅ 承認済みコンテンツなし")
        return

    print(f"📋 {len(pages)}件の承認済みコンテンツを処理します")

    for page in pages:
        props = extract_props(page)
        final_path = process_page(props)

        if final_path:
            # Notionステータスを "final" に更新（tagishi最終確認待ち）
            update_notion_status(props["page_id"], "final")
            print(f"   📤 Notionステータス → final（tagishi最終確認待ち）")
            print(f"   動画パス: {final_path}")


if __name__ == "__main__":
    main()
