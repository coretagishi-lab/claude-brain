#!/usr/bin/env python3
"""
assembler.py — Notion approved → VOICEVOX 音声生成 → Canva ジョブ出力

フロー:
  1. Notion status=approved を取得
  2. 画像を catbox.moe にアップロード（Canva 用公開 URL 取得）
  3. VOICEVOX（localhost:50021）で音声生成 → WAV → MP4 → catbox.moe
  4. canva_job.json に組み立てデータを保存し CANVA_JOB_FILE= を出力
       → Claude Code セッションが Canva MCP を直接操作する
       → comic_frames は Claude Code セッションが画像+テロップを見てAI判断で割り当てる
  5. Canva 完了後: --finalize で Notion 更新 / タスクボード / Discord 通知

Canva MCP 操作でのコマズーム（Claude Code セッションが実行）:
  各ページの image_slot に対して 3 操作を実行する:
    1. update_fill   : asset_id をセット
    2. resize_element: scaled_img_w × scaled_img_h（comic_frames → frame_zoom_params 参照）
    3. position_element: elem_left, elem_top（同上）

使い方:
  python3 assembler.py          # approved を全件処理（ステップ 1〜4）
  python3 assembler.py --dry    # Notion 更新せずに確認

  # Canva 操作完了後の後処理（Claude Code セッションから呼ぶ）:
  python3 assembler.py --finalize \\
      --state-file=<canva_job.json のパス> \\
      --design-id=<新しい design_id> \\
      --canva-url=<Canva URL>

環境変数（必須）:
  NOTION_TOKEN
  NOTION_CONTENT_DB_ID（--finalize 時は不要）

環境変数（任意）:
  DISCORD_WEBHOOK_URL     # 未設定時は通知スキップ
"""
import json, os, re, subprocess, sys, time, wave, urllib.parse, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────────────────────────
NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_TASK_BOARD_ID = "3671cad4aa98813b85b2ed9e3127b913"
NOTION_VERSION       = "2022-06-28"
DISCORD_WEBHOOK_URL  = os.environ.get("DISCORD_WEBHOOK_URL", "")

VAULT      = Path(__file__).resolve().parents[3]   # AI-Brain/
AUDIO_DIR  = VAULT / "Projects" / "dmm-manga-affiliate" / "audio"

VOICEVOX_URL            = "http://localhost:50021"
VOICEVOX_SPEAKER_FEMALE = 47  # ナースロボ＿タイプT ノーマル（♀ or マーカーなし）
VOICEVOX_SPEAKER_MALE   = 13  # 青山龍星 ノーマル（♂）

# ── Canva テンプレート情報（handoff.md より） ──────────────────────────────
TEMPLATE_ID = "DAHKogY0SBo"

TELOP_ELEM_IDS = [
    "PBG3BLhBZW05Kb0W-LBhlvQNP9s6Wmwvr",  # ① ページ2
    "PBCSwpnm9S6QVHtJ-LBff234VHn89xWtW",  # ② ページ3
    "PBjDNccpBqWtybYQ-LBxsBSg503sFyjyQ",  # ③ ページ4
    "PBvxHVxQT8c46KWb-LBHJq4nGtPjjtjnV",  # ④ ページ5
    "PBw7ntJLPN1YXxv3-LB7D7v0gRPY16KGC",  # ⑤ ページ6
    "PBwNd5vms7mw2gXb-LBg46mQW7DYvYrS2",  # ⑥ ページ7
    "PBkLftpwjtcRJDvs-LB2Dj8TSWKB0CnvR",  # ⑦ ページ8
    "PBpYZmnGCfCLdFFC-LBzvFjt040LjCkN6",  # ⑧ ページ9
]

IMAGE_SLOT_IDS = [
    "PBG3BLhBZW05Kb0W-LBLG8GxWtKLtPZcZ",  # ページ2（コマ画像スロット）
    "PBCSwpnm9S6QVHtJ-LBdQhQ9QLg702226",  # ページ3
    "PBjDNccpBqWtybYQ-LBDvNMjX4StVB5GM",  # ページ4
    "PBvxHVxQT8c46KWb-LBH6QJ9htKbKFffb",  # ページ5
    "PBw7ntJLPN1YXxv3-LB51rhY8PMFFZ0yM",  # ページ6
    "PBwNd5vms7mw2gXb-LB5vg7qKZDrynCgY",  # ページ7
    "PBkLftpwjtcRJDvs-LBbb8hbVDTZV2dnn",  # ページ8
    "PBpYZmnGCfCLdFFC-LBlSnf96nnXyTVR8",  # ページ9
]

# ページ1（トップページ）カバー画像スロット
PAGE1_COVER_SLOT_ID = "PBs1sTlCLqHDSG14-LBW9GpN7ycfQ2ptS"

# ページ10（エンドページ）カバー画像スロット
END_PAGE_COVER_SLOT_ID = "PBQRTjML4Gm5msr7-LBB8BKH3dpcWzwx8"


# ── ユーティリティ ────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(msg: str):
    print(f"[{ts()}] {msg}", flush=True)


# ── Notion ────────────────────────────────────────────────────────────────
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
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def sync_task_board_approvals(dry: bool = False) -> dict:
    """
    タスクボードで「✅ 確認済み」になった[台本確認]アイテムを検出し、
    コンテンツDBを approved に更新する。
    Returns: {page_id: yarinaoshi_text} — やり直し指示がない場合は空文字
    """
    _, res = notion("POST", f"/databases/{NOTION_TASK_BOARD_ID}/query", {
        "filter": {
            "and": [
                {"property": "ステータス", "select": {"equals": "✅ 確認済み"}},
                {"property": "タスク名",   "title":  {"contains": "[台本確認]"}},
            ]
        }
    })
    items = res.get("results", [])
    if not items:
        return {}

    overrides = {}
    for item in items:
        summary = "".join(
            p.get("plain_text", "")
            for p in item["properties"].get("内容要約", {}).get("rich_text", [])
        )
        m = re.search(r"page_id:([0-9a-f\-]{32,36})", summary)
        if not m:
            log(f"  ⚠️  page_id 抽出失敗（内容要約に page_id: がない）: {summary[:80]}")
            continue

        raw = m.group(1).replace("-", "")
        page_id = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"

        yarinaoshi = "".join(
            p.get("plain_text", "")
            for p in item["properties"].get("やり直し指示", {}).get("rich_text", [])
        ).strip()

        if not dry:
            content_props = {"status": {"select": {"name": "approved"}}}
            notion("PATCH", f"/pages/{page_id}", {"properties": content_props})
            notion("PATCH", f"/pages/{item['id']}", {
                "properties": {"ステータス": {"select": {"name": "🔄 作成中"}}}
            })
            if yarinaoshi:
                log(f"  📝 やり直し指示あり → script を直接上書き: {yarinaoshi[:50]}...")
            log(f"  ✅ タスクボード→コンテンツDB approved: {page_id[:8]}...")
        else:
            if yarinaoshi:
                log(f"  [DRY] やり直し指示あり → script 上書きするはず: {yarinaoshi[:50]}...")
            log(f"  [DRY] approved に更新するはず: {page_id[:8]}...")
        overrides[page_id] = yarinaoshi

    return overrides


def get_approved_pages():
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "approved"}},
        "sorts":  [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def extract_props(page):
    def txt(k):
        parts = page["properties"].get(k, {}).get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts)
    return {
        "page_id":       page["id"],
        "manga_title":   txt("manga_title"),
        "youtube_title": txt("youtube_title"),
        "description":   txt("description"),
        "script":        txt("script"),
        "image_url":     "".join(p.get("plain_text", "") for p in (page["properties"].get("image_url") or {}).get("rich_text", [])),
        "affiliate_url": (page["properties"].get("affiliate_url") or {}).get("url") or "",
    }


def parse_telops(script_text: str) -> list:
    """
    "1. テロップ1\n2. テロップ2\n..." 形式を ["テロップ1", "テロップ2", ...] に変換。
    先頭の番号（①②③ / 1. 形式）と「」を除去して本文のみ返す。
    """
    lines = []
    for line in script_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 「」除去 → "N." 除去 → 丸数字除去（"1. ①テキスト" 形式に対応）
        text = line.replace("「", "").replace("」", "").strip()
        text = re.sub(r'^\d+\.\s*', '', text).strip()
        text = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]', '', text).strip()
        lines.append(text)
    return lines[:8]


def update_to_canva_ready(page_id: str, canva_url: str, design_id: str, dry: bool = False):
    if dry:
        log(f"  [DRY] Notion 更新スキップ: canva_ready / {canva_url}")
        return
    notion("PATCH", f"/pages/{page_id}", {"properties": {
        "status":    {"select": {"name": "canva_ready"}},
        "canva_url": {"url": canva_url},
    }})
    blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("🎨 Canva 組み立て完了")}},
        {"object": "block", "type": "callout", "callout": {
            "rich_text": rt(f"Canva URL: {canva_url}\nDesign ID: {design_id}"),
            "icon": {"emoji": "✅"},
        }},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": rt(
             f"組み立て日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
         )}},
    ]
    notion("PATCH", f"/blocks/{page_id}/children", {"children": blocks})


def register_to_task_board(manga_title: str, canva_url: str, notion_url: str, dry: bool = False):
    if dry:
        log(f"  [DRY] タスクボード登録スキップ")
        return
    notion("POST", "/pages", {
        "parent": {"database_id": NOTION_TASK_BOARD_ID},
        "properties": {
            "タスク名":       {"title": rt(f"[Canva確認] {manga_title}")},
            "プロジェクト名": {"select": {"name": "DMM漫画アフィリエイト"}},
            "ステータス":     {"select": {"name": "👀 確認待ち"}},
            "作成物":         {"rich_text": rt(canva_url)},
            "内容要約":       {"rich_text": rt(f"Notion: {notion_url}")},
            "提出日時":       {"date": {"start": datetime.now().strftime("%Y-%m-%d")}},
        }
    })


# ── 画像: Discord CDN → catbox.moe ────────────────────────────────────────
def download_image(url: str) -> tuple:
    """URL から画像をダウンロードして (bytes, content_type) を返す。"""
    if not url:
        return None, None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.read(), res.headers.get("Content-Type", "image/jpeg").split(";")[0]
    except Exception as e:
        log(f"  ⚠️  画像ダウンロード失敗: {e}")
        return None, None


def upload_to_catbox(image_bytes: bytes, content_type: str) -> str:
    """
    catbox.moe に画像をアップロードして公開 URL を返す。
    Canva upload-asset-from-url に渡す公開 URL として使用。
    """
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    tmp = Path(f"/tmp/assembler_img_{int(time.time())}.{ext}")
    tmp.write_bytes(image_bytes)
    try:
        result = subprocess.run(
            ["curl", "-s",
             "-F", f"fileToUpload=@{tmp}",
             "-F", "reqtype=fileupload",
             "https://catbox.moe/user/api.php"],
            capture_output=True, text=True, timeout=60
        )
        url = result.stdout.strip()
        if url.startswith("https://"):
            return url
        log(f"  ⚠️  catbox.moe 応答: {url!r}")
        return ""
    finally:
        tmp.unlink(missing_ok=True)


# ── VOICEVOX ─────────────────────────────────────────────────────────────
def ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def voicevox_available() -> bool:
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/version", timeout=3):
            return True
    except Exception:
        return False


def generate_voice(text: str, speaker: int = VOICEVOX_SPEAKER) -> bytes:
    """VOICEVOX で音声を生成して WAV バイト列を返す。"""
    # Step 1: audio_query
    query_url = f"{VOICEVOX_URL}/audio_query?text={urllib.parse.quote(text)}&speaker={speaker}"
    req = urllib.request.Request(query_url, method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        query_data = res.read()

    # Step 2: synthesis
    synth_url = f"{VOICEVOX_URL}/synthesis?speaker={speaker}"
    req = urllib.request.Request(
        synth_url, data=query_data, method="POST",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()


def add_silence_padding(wav_path: Path, pre_sec: float = 0.3, post_sec: float = 0.5):
    """WAV の前後に無音を挿入して上書き保存する（前0.3秒・後0.5秒）。"""
    with wave.open(str(wav_path), 'rb') as r:
        params   = r.getparams()
        pcm_data = r.readframes(r.getnframes())
    bytes_per_frame = params.nchannels * params.sampwidth
    pre  = bytes(int(pre_sec  * params.framerate) * bytes_per_frame)
    post = bytes(int(post_sec * params.framerate) * bytes_per_frame)
    with wave.open(str(wav_path), 'wb') as w:
        w.setparams(params)
        w.writeframes(pre + pcm_data + post)


def parse_gender_prefix(telop: str) -> tuple:
    """♂/♀プレフィックスを検出してspeaker IDとクリーンテキストを返す。"""
    if telop.startswith("♂"):
        return VOICEVOX_SPEAKER_MALE, telop[1:].lstrip()
    if telop.startswith("♀"):
        return VOICEVOX_SPEAKER_FEMALE, telop[1:].lstrip()
    return VOICEVOX_SPEAKER_FEMALE, telop


def generate_all_voices(manga_title: str, telops: list) -> Path:
    """
    テロップ全行の音声を生成して audio/{safe_title}/ ディレクトリに保存。
    ♂/♀プレフィックスで話者を切り替え、前後に無音を挿入する。
    Returns: 保存先ディレクトリ
    """
    safe = re.sub(r'[^\w\-_]', '_', manga_title)[:40]
    date = datetime.now().strftime("%Y%m%d")
    out_dir = AUDIO_DIR / f"{date}_{safe}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, telop in enumerate(telops, 1):
        speaker, text = parse_gender_prefix(telop)
        if not text:
            continue
        path = out_dir / f"telop_{i:02d}.wav"
        gender_label = "♂" if speaker == VOICEVOX_SPEAKER_MALE else "♀"
        try:
            wav = generate_voice(text, speaker)
            path.write_bytes(wav)
            add_silence_padding(path)
            log(f"  🎙 telop_{i:02d}.wav 生成完了 {gender_label}({len(text)}文字)")
        except Exception as e:
            log(f"  ⚠️  telop_{i:02d} 音声生成失敗: {e}")

    return out_dir


def get_all_durations(audio_dir: Path, telop_count: int) -> list:
    """各テロップ WAV の再生時間（前後無音込み）を秒単位で返す。"""
    durations = []
    for i in range(1, telop_count + 1):
        path = audio_dir / f"telop_{i:02d}.wav"
        if path.exists():
            with wave.open(str(path), 'rb') as r:
                duration = round(r.getnframes() / r.getframerate(), 2)
            durations.append(duration)
        else:
            durations.append(None)
    return durations


def wav_to_transparent_mp4(wav_path: Path) -> Path:
    """
    WAV の正確な長さに合わせた 1080x1920px 黒フレーム MP4 を生成する。
    ffprobe で音声秒数を取得し、その秒数ぴったりの動画を生成する。
    """
    mp4_path = wav_path.with_suffix(".mp4")

    probe = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(wav_path),
    ], capture_output=True, text=True, check=True, timeout=10)
    duration = probe.stdout.strip()

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=black:size=1080x1920:rate=30:duration={duration}",
        "-i", str(wav_path),
        "-t", duration,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "128k",
        str(mp4_path),
    ], capture_output=True, check=True, timeout=60)
    return mp4_path


def convert_all_to_mp4(audio_dir: Path, telop_count: int) -> list:
    """audio_dir 内の telop_NN.wav を MP4 に変換し、Path リストを返す。"""
    paths = []
    for i in range(1, telop_count + 1):
        wav = audio_dir / f"telop_{i:02d}.wav"
        if not wav.exists():
            paths.append(None)
            continue
        try:
            mp4 = wav_to_transparent_mp4(wav)
            paths.append(mp4)
            log(f"  🎬 telop_{i:02d}.mp4 変換完了 ({mp4.stat().st_size // 1024}KB)")
        except Exception as e:
            log(f"  ⚠️  telop_{i:02d} MP4変換失敗: {e}")
            paths.append(None)
    return paths


def upload_all_video(audio_dir: Path, mp4_paths: list) -> list:
    """MP4 ファイルを catbox.moe にアップロードし公開 URL リストを返す。"""
    urls = []
    for i, mp4 in enumerate(mp4_paths, 1):
        if mp4 is None or not mp4.exists():
            urls.append("")
            continue
        try:
            url = upload_to_catbox(mp4.read_bytes(), "video/mp4")
            urls.append(url)
            log(f"  📤 telop_{i:02d}.mp4 → {url}")
        except Exception as e:
            log(f"  ⚠️  telop_{i:02d}.mp4 アップロード失敗: {e}")
            urls.append("")
    return urls


def cleanup_media_files(audio_dir: Path):
    """audio_dir 内の WAV / MP4 ファイルを削除し、空になったディレクトリも削除する。"""
    if not audio_dir or not audio_dir.exists():
        return
    deleted = 0
    for f in audio_dir.iterdir():
        if f.suffix in (".wav", ".mp4"):
            f.unlink()
            deleted += 1
    try:
        audio_dir.rmdir()  # 空ならディレクトリごと削除
    except OSError:
        pass
    log(f"  🗑  メディアファイル削除: {deleted}件 ({audio_dir.name})")


# ── Canva ジョブ管理 ──────────────────────────────────────────────────────

def save_canva_job(props: dict, image_urls: list, telops: list,
                   durations: list, video_urls: list, audio_dir) -> Path:
    """
    Canva 組み立てに必要なデータを JSON ファイルに保存する。
    Claude Code セッションがこのファイルを読み、Canva MCP を直接操作する。

    Claude Code セッションの実行手順:
      1. copy-design(template_id) → 新 design_id を取得
      2. start-editing-transaction → top昇順ソートで title_line_from_top 番目の
         element_id を manga_title_elem_id として特定 → replace_text → commit
      3. image_assignments を決定:
         - image_urls の各画像をダウンロードして内容確認
         - telops[i] に最も対応する image_url を選び image_assignments[i] に記録
         - image_assignments は長さ8のリスト（テロップ①〜⑧に対応）
      4. 各スロットで upload-asset-from-url → update_fill のみ（ズーム不要）
      5. page1_cover_slot_id・end_page_cover_slot_id にも同様に差し込む

    Returns: 保存した JSON ファイルのパス
    """
    out_dir    = Path(audio_dir) if audio_dir else AUDIO_DIR
    state_file = out_dir / "canva_job.json"
    state = {
        "page_id":               props["page_id"],
        "manga_title":           props["manga_title"],
        "image_urls":            image_urls,        # 利用可能な漫画画像URL一覧
        "image_assignments":     None,              # Claude Codeが各スロットへの対応を決定
        "telops":                [parse_gender_prefix(t)[1] for t in telops],
        "durations":             durations,
        "video_urls":            video_urls,
        "audio_dir":             str(out_dir),
        "template_id":           TEMPLATE_ID,
        "design_id":             None,
        "manga_title_elem_id":   None,
        "title_line_from_top":   3,
        "telop_elem_ids":        TELOP_ELEM_IDS,
        "image_slot_ids":        IMAGE_SLOT_IDS,
        "page1_cover_slot_id":   PAGE1_COVER_SLOT_ID,
        "end_page_cover_slot_id": END_PAGE_COVER_SLOT_ID,
    }
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return state_file


def finalize_canva(state_file: Path, design_id: str, canva_url: str, dry: bool = False):
    """
    Claude Code が Canva MCP 操作を完了した後に呼ぶ後処理。
    Notion 更新 / タスクボード登録 / Discord 通知 / メディアファイル削除
    """
    state       = json.loads(state_file.read_text())
    page_id     = state["page_id"]
    manga_title = state["manga_title"]
    audio_dir   = Path(state["audio_dir"]) if state.get("audio_dir") else None

    notion_url = f"https://app.notion.com/p/{page_id.replace('-', '')}"
    update_to_canva_ready(page_id, canva_url, design_id, dry=dry)
    log("  ✅ Notion: approved → canva_ready")

    register_to_task_board(manga_title, canva_url, notion_url, dry=dry)
    log("  ✅ タスク確認ボード登録完了")

    notify_discord(manga_title, canva_url, notion_url)

    if audio_dir and audio_dir.exists():
        cleanup_media_files(audio_dir)


# ── Discord 通知 ──────────────────────────────────────────────────────────
def notify_discord(manga_title: str, canva_url: str, notion_url: str):
    if not DISCORD_WEBHOOK_URL:
        log("  ℹ️  DISCORD_WEBHOOK_URL 未設定のため通知スキップ")
        return
    body = json.dumps({
        "content": (
            f"🎨 Canva 組み立て完了: {manga_title}\n"
            f"👀 確認: {notion_url}\n"
            f"🎬 Canva: {canva_url}"
        )
    }).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
        log("  📨 Discord 通知送信")
    except Exception as e:
        log(f"  ⚠️  Discord 通知失敗: {e}")


# ── メイン処理 ─────────────────────────────────────────────────────────────
def process_page(props: dict, dry: bool = False) -> bool:
    """approved ページ 1件を処理する。"""
    manga_title = props["manga_title"] or "(タイトル未設定)"
    log(f"\n📖 処理開始: {manga_title}")

    # ── テロップ解析 ──────────────────────────────────────────────────────
    telops = parse_telops(props["script"])
    if len(telops) < 8:
        log(f"  ⚠️  テロップが {len(telops)} 行しかありません（8行必要）")
        if len(telops) == 0:
            log("  ❌ 台本が空のためスキップ")
            return False
        # 不足分は空文字で埋める
        telops += [""] * (8 - len(telops))
    log(f"  テロップ: {telops}")

    # ── 画像アップロード（複数対応） ─────────────────────────────────────
    image_urls = []
    raw_urls = props.get("image_url", "")
    url_list = [u.strip() for u in raw_urls.split() if u.strip()] if raw_urls else []
    for i, url in enumerate(url_list, 1):
        log(f"  📥 画像{i}ダウンロード: {url[:60]}...")
        img_bytes, img_type = download_image(url)
        if img_bytes:
            log(f"  📤 catbox.moe にアップロード中...")
            pub_url = upload_to_catbox(img_bytes, img_type or "image/jpeg")
            if pub_url:
                image_urls.append(pub_url)
                log(f"  ✅ 公開URL: {pub_url}")
            else:
                log(f"  ⚠️  画像{i}アップロード失敗 → スキップ")
        else:
            log(f"  ⚠️  画像{i}取得失敗 → スキップ")
    if not image_urls:
        log("  ℹ️  利用可能な画像なし → 画像挿入スキップ")

    # ── VOICEVOX 音声生成 + ffmpeg MP4変換 ───────────────────────────────
    audio_dir  = None
    video_urls = None
    durations  = None
    if voicevox_available():
        log(f"  🎙 VOICEVOX 音声生成開始 (speaker={VOICEVOX_SPEAKER})")
        audio_dir = generate_all_voices(manga_title, [t for t in telops if t])
        log(f"  ✅ 音声保存先: {audio_dir}")
        durations = get_all_durations(audio_dir, len(telops))
        log(f"  ⏱  ページ表示時間: {durations}")
        if ffmpeg_available():
            log(f"  🎬 ffmpeg: WAV → 透明MP4 変換中...")
            mp4_paths = convert_all_to_mp4(audio_dir, len(telops))
            log(f"  📤 MP4 を catbox.moe にアップロード中...")
            video_urls = upload_all_video(audio_dir, mp4_paths)
            log(f"  ✅ 動画アップロード完了: {sum(1 for u in video_urls if u)}/{len(telops)} 件")
        else:
            log(f"  ⚠️  ffmpeg が見つかりません → MP4変換スキップ")
    else:
        log(f"  ⚠️  VOICEVOX ({VOICEVOX_URL}) に接続できません → 音声生成スキップ")

    # ── Canva ジョブ保存 ──────────────────────────────────────────────────
    if dry:
        log("  [DRY] Canva ジョブ保存スキップ")
        return True

    state_file = save_canva_job(
        props, image_urls, telops, durations or [], video_urls or [], audio_dir
    )
    log(f"  📋 Canvaジョブ保存: {state_file}")
    print(f"\nCANVA_JOB_FILE={state_file}", flush=True)
    print("  ↑ このファイルを Claude Code セッションに渡して:", flush=True)
    print("    1. image_urls の各画像を確認し telops との対応を決定（image_assignments）", flush=True)
    print("    2. 各スロットに upload-asset-from-url → update_fill のみ", flush=True)
    return state_file


def main():
    dry = "--dry" in sys.argv

    # ── --finalize モード: Claude Code が Canva 完了後に呼ぶ ──────────────
    if "--finalize" in sys.argv:
        def _arg(name):
            for a in sys.argv:
                if a.startswith(f"--{name}="):
                    return a.split("=", 1)[1]
            return ""

        state_file = Path(_arg("state-file"))
        design_id  = _arg("design-id")
        canva_url  = _arg("canva-url")

        if not state_file.exists():
            print(f"❌ state-file が見つかりません: {state_file}")
            sys.exit(1)
        if not design_id or not canva_url:
            print("❌ --design-id と --canva-url が必要です")
            sys.exit(1)
        if not os.environ.get("NOTION_TOKEN"):
            print("❌ 環境変数未設定: NOTION_TOKEN")
            sys.exit(1)

        log(f"finalize 起動: design_id={design_id}")
        finalize_canva(state_file, design_id, canva_url, dry=dry)
        log("完了")
        return

    # ── 通常モード: Notion approved → VOICEVOX → canva_job.json 出力 ─────
    missing = [k for k in ["NOTION_TOKEN", "NOTION_CONTENT_DB_ID"] if not os.environ.get(k)]
    if missing:
        print(f"❌ 環境変数未設定: {', '.join(missing)}")
        sys.exit(1)

    if dry:
        log("⚠️  DRY RUN モード: Notion 更新・Discord 通知はスキップします")

    log(f"assembler 起動: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    pages = get_approved_pages()
    if not pages:
        log("approved: 0件 → 終了")
        return

    log(f"approved: {len(pages)}件")
    ok = ng = 0

    for page in pages:
        props = extract_props(page)
        try:
            result = process_page(props, dry=dry)
            if result is not False:
                ok += 1
            else:
                ng += 1
        except Exception as e:
            log(f"  ❌ 処理失敗: {e}")
            ng += 1

    log(f"\n準備完了: ✅ {ok}件 / ❌ {ng}件")
    log("ℹ️  CANVA_JOB_FILE のパスを Claude Code セッションに渡して Canva MCP 操作を実行してください")
    log("    完了後: python3 assembler.py --finalize --state-file=<path> --design-id=<id> --canva-url=<url>")


if __name__ == "__main__":
    main()
