#!/usr/bin/env python3
"""
video-generator.py — [Canva確認] ✅後 の最終動画生成（100点バージョン）

使い方:
  python3 video-generator.py                              # VPSタスク検知 → 音声生成 → job出力
  python3 video-generator.py --assemble --job-file <path> # PNG取得後のffmpeg組み立て
  python3 video-generator.py --task-id <id>              # 特定VPSタスクを指定

フロー（Claude Code セッション内で実行）:
  Step 1. python3 video-generator.py を実行
     → VPSタスクから page_id を取得
     → Notionから manga_title / script / canva_url を取得
     → VOICEVOX で 8行音声を再生成
     → video_job.json を出力
     → CanvaページPNG書き出しの指示を出力

  Step 2. Claude Code が Canva MCP で各ページを PNG 書き出し
     → canva_pages_dir/page1.png ... page10.png に保存

  Step 3. python3 video-generator.py --assemble --job-file <path>
     → Ken Burns + xfade crossfade + SE + BGM で最終MP4生成
     → [動画確認] タスクをNotionに登録
     → VPSタスクを解決済みに

動画構成（100点バージョン）:
  ・page1.png : イントロ 3秒 (Ken Burns)
  ・page2-9.png: コンテンツ 音声長sec (Ken Burns + VOICEVOX + ページめくりSE)
  ・page10.png : エンド 3秒 (Ken Burns)
  ・スライド間 crossfade 0.3秒
  ・BGM ミックス (BGM_PATH に配置したファイル)

環境変数:
  NOTION_TOKEN（必須）
  NOTION_CONTENT_DB_ID（通常モードで必要）
"""
import argparse, json, os, random, re, subprocess, sys, tempfile, time, wave
import urllib.parse, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────────────────────────────
NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_TASK_BOARD_ID = "3671cad4aa98813b85b2ed9e3127b913"
NOTION_VERSION       = "2022-06-28"
OUTBOX_DB_ID         = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"

VAULT      = Path(__file__).resolve().parents[3]
AUDIO_BASE = VAULT / "Projects" / "dmm-manga-affiliate" / "audio"

VOICEVOX_URL            = "http://localhost:50021"
VOICEVOX_SPEAKER_FEMALE = 47  # ナースロボ＿タイプT ノーマル
VOICEVOX_SPEAKER_MALE   = 13  # 青山龍星 ノーマル

MEDIA_BASE = Path("/Users/tagishitakuya/Desktop/ClaudeProjects/漫画アフィリエイト:動画素材")
BGM_PATH   = MEDIA_BASE / "アカウント①BGM.mp3"
SE_DIR     = MEDIA_BASE / "効果音"


def pick_se():
    """効果音フォルダからランダムに1ファイルを返す"""
    if not SE_DIR.exists():
        return None
    files = [f for f in SE_DIR.iterdir() if f.suffix.lower() in (".mp3", ".wav", ".ogg")]
    return random.choice(files) if files else None

VIDEO_W        = 1080
VIDEO_H        = 1920
FPS            = 30
TRANSITION     = 0.3   # xfade crossfade 秒
INTRO_DURATION = 3.0   # page1 秒
OUTRO_DURATION = 3.0   # page10 秒
BGM_VOLUME     = 0.07  # ボイスに対するBGM音量比
SE_VOLUME      = 0.5   # SE音量


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(msg: str):
    print(f"[{ts()}] {msg}", flush=True)


# ── Notion ────────────────────────────────────────────────────────────────────
def notion(method: str, path: str, data=None):
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


def rt(text: str) -> list:
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def get_pending_ffmpeg_tasks() -> list:
    """VPS Outboxから「ffmpeg動画生成待ち」タスクを取得"""
    _, res = notion("POST", f"/databases/{OUTBOX_DB_ID}/query", {
        "filter": {"and": [
            {"property": "type",   "select":  {"equals": "vps-task"}},
            {"property": "status", "select":  {"equals": "pending"}},
            {"property": "title",  "title":   {"contains": "ffmpeg動画生成待ち"}},
        ]},
        "sorts": [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def get_task_content(task_id: str) -> str:
    """NotionタスクページのブロックをテキストとしてまとめてReturn"""
    _, res = notion("GET", f"/blocks/{task_id}/children")
    lines = []
    for block in res.get("results", []):
        btype = block.get("type", "")
        rich  = block.get(btype, {}).get("rich_text", [])
        text  = "".join(r.get("text", {}).get("content", "") for r in rich)
        if text:
            lines.append(text)
    return "\n".join(lines)


def extract_page_id(content: str) -> str:
    """タスク本文から Notion ページ ID を抽出"""
    # "Notion: https://app.notion.com/p/XXXXXXXX32CHARS"
    m = re.search(r"/p/([0-9a-f]{32})", content)
    if m:
        raw = m.group(1)
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    # "page_id:XXXX" 形式 (旧形式)
    m = re.search(r"page_id:([0-9a-f\-]{32,36})", content)
    if m:
        raw = m.group(1).replace("-", "")
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return ""


def get_content_page(page_id: str) -> dict:
    """コンテンツDBのページ情報を取得"""
    _, res = notion("GET", f"/pages/{page_id}")
    props = res.get("properties", {})

    def text(k):
        return "".join(p.get("plain_text", "")
                       for p in props.get(k, {}).get("rich_text", []))
    def title_text(k):
        return "".join(p.get("plain_text", "")
                       for p in props.get(k, {}).get("title", []))

    return {
        "page_id":       page_id,
        "manga_title":   text("manga_title") or title_text("manga_title"),
        "youtube_title": text("youtube_title"),
        "script":        text("script"),
        "canva_url":     props.get("canva_url", {}).get("url", ""),
        "image_url":     text("image_url"),
    }


def extract_design_id(canva_url: str) -> str:
    """https://www.canva.com/design/{id}/... から design_id を抽出"""
    m = re.search(r"/design/([A-Za-z0-9_-]+)/", canva_url)
    return m.group(1) if m else ""


def mark_vps_task_done(task_id: str, resolution: str):
    notion("PATCH", f"/pages/{task_id}", {
        "properties": {"status": {"select": {"name": "completed"}}},
    })
    notion("PATCH", f"/blocks/{task_id}/children", {"children": [{
        "object": "block", "type": "callout", "callout": {
            "rich_text": rt(f"✅ 解決済み [{datetime.now().strftime('%Y-%m-%d %H:%M')}]\n{resolution}"),
            "icon": {"type": "emoji", "emoji": "✅"},
            "color": "green_background",
        },
    }]})


def register_review_task(manga_title: str, video_path: str, catbox_url: str, page_id: str):
    """タスク確認ボードに [動画確認] タスクを登録"""
    notion_url = f"https://app.notion.com/p/{page_id.replace('-', '')}" if page_id else ""
    notion("POST", "/pages", {
        "parent": {"database_id": NOTION_TASK_BOARD_ID},
        "properties": {
            "タスク名":       {"title": rt(f"[動画確認] {manga_title}")},
            "プロジェクト名": {"select": {"name": "DMM漫画アフィリエイト"}},
            "ステータス":     {"select": {"name": "👀 確認待ち"}},
            "作成物":         {"rich_text": rt(catbox_url or str(video_path))},
            "内容要約":       {"rich_text": rt(f"動画: {catbox_url}\n確認: {notion_url}")},
            "提出日時":       {"date": {"start": datetime.now().strftime("%Y-%m-%d")}},
        }
    })


def update_notion_status(page_id: str, video_url: str):
    """コンテンツDBのステータスをvideo_readyに更新"""
    notion("PATCH", f"/pages/{page_id}", {
        "properties": {"status": {"select": {"name": "video_ready"}}},
    })
    if video_url:
        notion("PATCH", f"/blocks/{page_id}/children", {"children": [{
            "object": "block", "type": "callout", "callout": {
                "rich_text": rt(f"🎬 動画生成完了\nURL: {video_url}\n生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
                "icon": {"type": "emoji", "emoji": "🎬"},
                "color": "blue_background",
            },
        }]})


# ── VOICEVOX ─────────────────────────────────────────────────────────────────
def voicevox_available() -> bool:
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/version", timeout=3):
            return True
    except Exception:
        return False


def parse_gender_prefix(telop: str) -> tuple:
    """♂/♀プレフィックスでspeaker IDとクリーンテキストを返す"""
    if telop.startswith("♂"):
        return VOICEVOX_SPEAKER_MALE, re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', telop[1:].lstrip())
    elif telop.startswith("♀"):
        return VOICEVOX_SPEAKER_FEMALE, re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', telop[1:].lstrip())
    return VOICEVOX_SPEAKER_FEMALE, re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', telop)


def generate_voice(text: str, speaker: int) -> bytes:
    query_url = f"{VOICEVOX_URL}/audio_query?text={urllib.parse.quote(text)}&speaker={speaker}"
    req = urllib.request.Request(query_url, method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        query_data = res.read()
    synth_url = f"{VOICEVOX_URL}/synthesis?speaker={speaker}"
    req = urllib.request.Request(synth_url, data=query_data, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()


def add_silence_padding(wav_path: Path, pre_sec: float = 0.3, post_sec: float = 0.5):
    with wave.open(str(wav_path), "rb") as r:
        params   = r.getparams()
        pcm_data = r.readframes(r.getnframes())
    bpf = params.nchannels * params.sampwidth
    pre  = bytes(int(pre_sec  * params.framerate) * bpf)
    post = bytes(int(post_sec * params.framerate) * bpf)
    with wave.open(str(wav_path), "wb") as w:
        w.setparams(params)
        w.writeframes(pre + pcm_data + post)


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as r:
        return round(r.getnframes() / r.getframerate(), 2)


def generate_all_voices(manga_title: str, telops: list, out_dir: Path) -> list:
    """8行分の音声を生成 → out_dir/telop_NN.wav, 各WAV尺(秒)のリストを返す"""
    out_dir.mkdir(parents=True, exist_ok=True)
    durations = []
    for i, telop in enumerate(telops, 1):
        speaker, text = parse_gender_prefix(telop)
        if not text:
            durations.append(2.0)
            continue
        path = out_dir / f"telop_{i:02d}.wav"
        gender = "♂" if speaker == VOICEVOX_SPEAKER_MALE else "♀"
        wav = generate_voice(text, speaker)
        path.write_bytes(wav)
        add_silence_padding(path)
        dur = get_wav_duration(path)
        durations.append(dur)
        log(f"  🎙 telop_{i:02d}.wav {gender} {dur:.1f}s [{text[:20]}]")
    return durations


def parse_telops(script: str) -> list:
    """スクリプト文字列から最大8行のテロップを抽出
    「1. ♂①...」形式の先頭番号を除去して「♂①...」に正規化する"""
    lines = [l.strip() for l in script.splitlines() if l.strip()]
    result = []
    for line in lines:
        # "1. ♂①..." → "♂①..."  （先頭の「数字.」を除去）
        clean = re.sub(r'^\d+\.\s*', '', line).strip()
        if clean:
            result.append(clean)
    return result[:8]


# ── catbox.moe ───────────────────────────────────────────────────────────────
def upload_to_catbox(file_path: Path) -> str:
    result = subprocess.run(
        ["curl", "-s", "-F", f"fileToUpload=@{file_path}",
         "-F", "reqtype=fileupload", "https://catbox.moe/user/api.php"],
        capture_output=True, text=True, timeout=180
    )
    url = result.stdout.strip()
    return url if url.startswith("https://") else ""


# ── ffmpeg ────────────────────────────────────────────────────────────────────
def ffmpeg_check():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5)
    except Exception:
        log("❌ ffmpeg が見つかりません。インストールしてください: brew install ffmpeg")
        sys.exit(1)


def make_slide_video(png_path: Path, duration: float, out_path: Path):
    """PNG → 完全静止画ビデオ（音声なし）。xfade用に duration+TRANSITION 分生成"""
    result = subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
        "-i", str(png_path),
        "-vf", (f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
                f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=white,format=yuv420p"),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-t", str(duration), str(out_path),
    ], capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"スライドビデオ生成失敗: {result.stderr[-200:]}")


def concat_videos(slide_paths: list, tmp_dir: Path) -> Path:
    """全スライドを単純結合（音声と完全同期するためハードカット）"""
    video_only  = tmp_dir / "video_only.mp4"
    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p}'" for p in slide_paths)
    )
    result = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        str(video_only),
    ], capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"concat 失敗: {result.stderr[-400:]}")
    return video_only


def make_audio_track(audio_dir: Path, durations: list, tmp_dir: Path,
                     intro_wav: Path = None, outro_wav: Path = None) -> Path:
    """
    音声トラックを組み立て:
      イントロ音声(or無音) + [SE+voice] × 8 + アウトロ音声(or無音)
    Returns: voice_track.wav
    """
    sr = 48000

    def silence(out: Path, dur: float):
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r={sr}:cl=stereo",
            "-t", str(dur), "-c:a", "pcm_s16le", str(out)
        ], capture_output=True, check=True, timeout=15)

    def resample(src: Path, dst: Path):
        subprocess.run([
            "ffmpeg", "-y", "-i", str(src),
            "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)
        ], capture_output=True, check=True, timeout=30)

    segments = []

    # ① イントロ音声（決定ボタンSE固定 + 女性ボイス）
    intro_seg    = tmp_dir / "seg_00_intro.wav"
    intro_se     = SE_DIR / "決定ボタンを押す13.mp3"
    intro_src    = tmp_dir / "seg_00_voice_raw.wav"

    if intro_wav and intro_wav.exists():
        resample(intro_wav, intro_src)
    else:
        silence(intro_src, 3.0)

    if intro_se.exists():
        intro_dur_s = get_wav_duration(intro_src) if intro_wav and intro_wav.exists() else 3.0
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(intro_se),
            "-i", str(intro_src),
            "-filter_complex",
            (
                f"[0:a]aresample={sr},volume={SE_VOLUME}[se];"
                f"[1:a]aresample={sr}[v];"
                f"[se][v]amix=inputs=2:duration=longest,atrim=0:{intro_dur_s}[aout]"
            ),
            "-map", "[aout]",
            "-c:a", "pcm_s16le", str(intro_seg)
        ], capture_output=True, check=True, timeout=30)
    else:
        intro_seg = intro_src  # SEなければそのまま

    segments.append(intro_seg)

    # ② 各コンテンツスライド音声
    for i, dur in enumerate(durations, 1):
        voice_wav = audio_dir / f"telop_{i:02d}.wav"
        seg_out   = tmp_dir / f"seg_{i:02d}_voice.wav"

        se_file = pick_se()

        if not voice_wav.exists() or dur == 0.0:
            silence(seg_out, max(dur, 1.5))

        elif se_file:
            # SE + voice を同時再生（amix）
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(se_file),
                "-i", str(voice_wav),
                "-filter_complex",
                (
                    f"[0:a]aresample={sr},volume={SE_VOLUME}[se];"
                    f"[1:a]aresample={sr}[v];"
                    f"[se][v]amix=inputs=2:duration=longest,atrim=0:{dur}[aout]"
                ),
                "-map", "[aout]",
                "-c:a", "pcm_s16le", str(seg_out)
            ], capture_output=True, check=True, timeout=30)

        else:
            # voice のみ（サンプルレート統一）
            subprocess.run([
                "ffmpeg", "-y", "-i", str(voice_wav),
                "-ar", str(sr), "-c:a", "pcm_s16le", str(seg_out)
            ], capture_output=True, check=True, timeout=30)

        segments.append(seg_out)

    # ③ アウトロ音声（提供されていれば使用、なければ無音3s）
    outro_seg = tmp_dir / "seg_09_outro.wav"
    if outro_wav and outro_wav.exists():
        resample(outro_wav, outro_seg)
    else:
        silence(outro_seg, 3.0)
    segments.append(outro_seg)

    # ④ 全セグメントを concat
    n = len(segments)
    voice_track = tmp_dir / "voice_track.wav"
    filter_in   = "".join(f"[{i}:a]" for i in range(n))

    cmd = ["ffmpeg", "-y"]
    for s in segments:
        cmd += ["-i", str(s)]
    cmd += [
        "-filter_complex",
        f"{filter_in}concat=n={n}:v=0:a=1[aout]",
        "-map", "[aout]",
        "-c:a", "pcm_s16le", str(voice_track),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=120)

    return voice_track


def mix_with_bgm(voice_track: Path, total_duration: float, tmp_dir: Path) -> Path:
    """BGM をミックスした最終音声トラック (AAC) を生成"""
    mixed = tmp_dir / "audio_mixed.aac"

    if BGM_PATH.exists():
        log(f"  🎵 BGMミックス: {BGM_PATH.name}")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(voice_track),
            "-stream_loop", "-1", "-i", str(BGM_PATH),
            "-filter_complex",
            (
                f"[0:a]apad[voice];"
                f"[voice][1:a]amix=inputs=2:duration=first:weights='1 {BGM_VOLUME}'"
                f"[aout]"
            ),
            "-map", "[aout]",
            "-t", str(total_duration),
            "-c:a", "aac", "-b:a", "192k", str(mixed),
        ], capture_output=True, check=True, timeout=120)
    else:
        log(f"  ⚠️  BGMファイル未配置 ({BGM_PATH}) → BGMなしで生成")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(voice_track),
            "-t", str(total_duration),
            "-c:a", "aac", "-b:a", "192k", str(mixed),
        ], capture_output=True, check=True, timeout=60)

    return mixed


def mux_video_audio(video_path: Path, audio_path: Path, output_path: Path):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "copy",
        "-shortest", str(output_path),
    ], capture_output=True, check=True, timeout=180)


def assemble_video(job: dict, output_path: Path) -> Path:
    """video_job.json を読んで最終 MP4 を組み立てる"""
    ffmpeg_check()

    canva_pages_dir = Path(job["canva_pages_dir"])
    audio_dir       = Path(job["audio_dir"])
    durations       = job["durations"]  # 8要素（コンテンツスライド）

    intro_wav = Path(job["intro_wav"]) if job.get("intro_wav") else None
    outro_wav = Path(job["outro_wav"]) if job.get("outro_wav") else None
    intro_dur = job.get("intro_duration", 3.0)
    outro_dur = job.get("outro_duration", 3.0)

    tmp_dir = Path(tempfile.mkdtemp(prefix="vgen-"))

    all_durations = [intro_dur] + durations + [outro_dur]
    n = len(all_durations)  # 10
    total_steps = 4

    # ── 1/4 スライド動画生成 ───────────────────────────────────────────
    print(f"  ⏳ 1/{total_steps}  スライド画像生成中...", flush=True)
    slide_videos = []
    for i in range(n):
        png = canva_pages_dir / f"page{i + 1}.png"
        out = tmp_dir / f"slide_{i:02d}.mp4"
        if not png.exists():
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=black:size={VIDEO_W}x{VIDEO_H}:rate={FPS}",
                "-t", str(all_durations[i] + TRANSITION),
                "-c:v", "libx264", str(out),
            ], capture_output=True, check=True, timeout=30)
        else:
            make_slide_video(png, all_durations[i], out)
        slide_videos.append(out)
        print(f"  ⏳ 1/{total_steps}  スライド画像生成中... {i+1}/{n}", flush=True)

    # ── 2/4 結合（ハードカット・音声と完全同期）─────────────────────
    print(f"  ⏳ 2/{total_steps}  スライド結合中...", flush=True)
    video_only     = concat_videos(slide_videos, tmp_dir)
    total_duration = sum(all_durations)

    # ── 3/4 音声トラック組み立て + BGM ────────────────────────────────
    print(f"  ⏳ 3/{total_steps}  音声トラック組み立て中...", flush=True)
    voice_track = make_audio_track(audio_dir, durations, tmp_dir,
                                   intro_wav=intro_wav, outro_wav=outro_wav)
    audio_mixed = mix_with_bgm(voice_track, total_duration, tmp_dir)

    # ── 4/4 最終書き出し ──────────────────────────────────────────────
    print(f"  ⏳ 4/{total_steps}  最終書き出し中...", flush=True)
    mux_video_audio(video_only, audio_mixed, output_path)
    mb = output_path.stat().st_size // (1024 * 1024)
    print(f"  ✅ 完成!  {output_path.name}  ({mb}MB / 約{total_duration:.0f}秒)", flush=True)

    # 作業ファイルを削除
    for f in tmp_dir.iterdir():
        try:
            f.unlink()
        except Exception:
            pass
    try:
        tmp_dir.rmdir()
    except Exception:
        pass

    return output_path


# ── メイン処理 ────────────────────────────────────────────────────────────────
def setup_mode(task_id: str = "", design_id_override: str = ""):
    """
    通常モード: VPSタスク検知 → Notion情報取得 → VOICEVOX音声生成 → job JSON出力
    """
    if not NOTION_TOKEN:
        log("❌ 環境変数 NOTION_TOKEN が未設定です")
        sys.exit(1)

    # ── VPS タスク取得 ───────────────────────────────────────────────────
    if task_id:
        tasks = [{"id": task_id, "properties": {
            "title": {"title": [{"text": {"content": f"ffmpeg動画生成待ち (指定ID)"}}]}
        }}]
    else:
        tasks = get_pending_ffmpeg_tasks()

    if not tasks:
        log("✅ 処理待ちの「ffmpeg動画生成待ち」タスクはありません")
        return

    log(f"📋 ffmpeg動画生成待ち: {len(tasks)}件")

    for task in tasks:
        task_id     = task["id"]
        task_title  = "".join(p.get("plain_text", "")
                              for p in task["properties"]["title"]["title"])
        log(f"\n━━ タスク: {task_title}")

        # ── タスク本文からページID抽出 ──────────────────────────────────
        content = get_task_content(task_id)
        page_id = extract_page_id(content)

        if not page_id:
            log(f"  ❌ Notion ページ ID が抽出できませんでした\n  本文:\n{content[:200]}")
            continue

        log(f"  📄 page_id: {page_id}")

        # ── Notion からページ情報取得 ────────────────────────────────────
        props = get_content_page(page_id)
        manga_title = props["manga_title"] or "(タイトル不明)"
        canva_url   = props["canva_url"]
        script      = props["script"]
        design_id   = design_id_override or extract_design_id(canva_url)

        log(f"  📖 漫画タイトル: {manga_title}")
        log(f"  🎨 Canva URL: {canva_url}")
        log(f"  🆔 Design ID: {design_id}")

        if not design_id:
            log("  ❌ design_id が取得できませんでした")
            log(f"  💡 再実行: python3 video-generator.py --design-id <ID>")
            continue

        # ── テロップ解析 ─────────────────────────────────────────────────
        telops = parse_telops(script)
        if len(telops) < 8:
            log(f"  ⚠️  テロップ {len(telops)} 行（8行推奨）。不足分は無音で補完します")
            telops += [""] * (8 - len(telops))
        log(f"  📝 テロップ: {telops}")

        # ── VOICEVOX 音声生成 ───────────────────────────────────────────
        if not voicevox_available():
            log(f"  ❌ VOICEVOX ({VOICEVOX_URL}) に接続できません。起動してから再実行してください")
            continue

        safe_title = re.sub(r"[^\w\-_]", "_", manga_title)[:40]
        date_str   = datetime.now().strftime("%Y%m%d")
        audio_dir  = AUDIO_BASE / f"{date_str}_{safe_title}_video"

        log(f"  🎙 VOICEVOX 音声生成中...")
        durations = generate_all_voices(manga_title, telops, audio_dir)
        log(f"  ✅ 音声生成完了 → {audio_dir}")

        # ── イントロ / アウトロ音声生成（女性ボイス固定）──────────────
        base_title = re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩]+$', '', manga_title).strip()
        intro_text = f"秒で出しちゃった{base_title}男の漫画"
        outro_text = "続きは動画の概要欄かコメント欄"

        intro_wav_path = audio_dir / "intro.wav"
        outro_wav_path = audio_dir / "outro.wav"

        log(f"  🎙 イントロ音声生成: {intro_text[:30]}")
        intro_wav_path.write_bytes(generate_voice(intro_text, VOICEVOX_SPEAKER_FEMALE))
        add_silence_padding(intro_wav_path, pre_sec=0.5, post_sec=0.8)
        intro_dur = get_wav_duration(intro_wav_path)

        log(f"  🎙 アウトロ音声生成: {outro_text}")
        outro_wav_path.write_bytes(generate_voice(outro_text, VOICEVOX_SPEAKER_FEMALE))
        add_silence_padding(outro_wav_path, pre_sec=0.3, post_sec=1.0)
        outro_dur = get_wav_duration(outro_wav_path)

        log(f"  ⏱  イントロ {intro_dur:.1f}s / アウトロ {outro_dur:.1f}s")

        # ── Canva ページ書き出し先ディレクトリ ─────────────────────────
        canva_pages_dir = audio_dir / "canva_pages"
        canva_pages_dir.mkdir(parents=True, exist_ok=True)

        # ── 出力パス ─────────────────────────────────────────────────────
        output_path = MEDIA_BASE / f"{manga_title}_完成.mp4"

        # ── video_job.json 保存 ─────────────────────────────────────────
        job = {
            "vps_task_id":      task_id,
            "page_id":          page_id,
            "manga_title":      manga_title,
            "design_id":        design_id,
            "canva_url":        canva_url,
            "telops":           [parse_gender_prefix(t)[1] for t in telops],
            "durations":        durations,
            "intro_wav":        str(intro_wav_path),
            "intro_duration":   intro_dur,
            "outro_wav":        str(outro_wav_path),
            "outro_duration":   outro_dur,
            "audio_dir":        str(audio_dir),
            "canva_pages_dir":  str(canva_pages_dir),
            "output_path":      str(output_path),
        }
        job_file = audio_dir / "video_job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2))
        log(f"  📋 video_job.json 保存: {job_file}")

        # ── Claude Code への指示出力 ─────────────────────────────────────
        print("\n" + "═" * 60)
        print(f"VIDEO_JOB_FILE={job_file}")
        print("═" * 60)
        print(f"""
【Claude Code への指示】

以下の手順で Canva ページを PNG 書き出しし、動画を組み立ててください。

■ design_id: {design_id}
■ canva_pages_dir: {canva_pages_dir}

Step A: Canva MCP でデザインの各ページを PNG 書き出し

  1. export-design ツールで design_id={design_id} の全ページを PNG エクスポート
  2. 取得した PNG を以下のパスに保存:
       page1.png  → page10.png を {canva_pages_dir}/ に保存
  3. 確認: ls {canva_pages_dir}/

Step B: ffmpeg 動画組み立て

  python3 {Path(__file__).resolve()} \\
      --assemble \\
      --job-file {job_file}
""")


def assemble_mode(job_file: Path):
    """
    --assemble モード: PNG 準備済み → ffmpeg 組み立て → Notion 登録
    """
    if not job_file.exists():
        log(f"❌ job-file が見つかりません: {job_file}")
        sys.exit(1)

    job = json.loads(job_file.read_text())
    manga_title = job["manga_title"]
    page_id     = job["page_id"]
    vps_task_id = job["vps_task_id"]
    output_path = Path(job["output_path"])

    if not NOTION_TOKEN:
        log("❌ 環境変数 NOTION_TOKEN が未設定です")
        sys.exit(1)

    ffmpeg_check()

    log(f"\n🎬 動画組み立て開始: {manga_title}")

    # canva_pages_dir チェック
    canva_pages_dir = Path(job["canva_pages_dir"])
    missing_pages = [i for i in range(1, 11) if not (canva_pages_dir / f"page{i}.png").exists()]
    if missing_pages:
        log(f"  ⚠️  不足PNG: page{missing_pages} → 黒フレームで代替します")

    # ffmpeg 組み立て
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assemble_video(job, output_path)

    # サムネイル用に page1.png をコピー（youtube-uploader.pyが使う）
    page1 = canva_pages_dir / "page1.png"
    thumbnail_path = output_path.parent / f"{output_path.stem}_thumb.png"
    if page1.exists():
        import shutil
        shutil.copy2(page1, thumbnail_path)
        log(f"  🖼  サムネイル保存: {thumbnail_path.name}")

    # catbox アップロード
    log("📤 catbox.moe にアップロード中...")
    catbox_url = upload_to_catbox(output_path)
    if catbox_url:
        log(f"  ✅ catbox URL: {catbox_url}")
    else:
        log("  ⚠️  アップロード失敗 → ローカルパスを使用")
        catbox_url = ""

    # Notion 更新
    log("📝 Notion 更新中...")
    update_notion_status(page_id, catbox_url or str(output_path))
    register_review_task(manga_title, str(output_path), catbox_url, page_id)
    log("  ✅ [動画確認] タスク登録完了")

    # VPS タスクを解決済みに
    if vps_task_id:
        mark_vps_task_done(
            vps_task_id,
            f"ffmpeg動画生成完了\n動画: {catbox_url or str(output_path)}"
        )
        log("  ✅ VPSタスク解決済み")

    print("\n" + "═" * 60)
    print(f"🎬 完成: {output_path}")
    if catbox_url:
        print(f"🔗 URL:  {catbox_url}")
    print(f"📋 Notionタスクボードで [動画確認] を確認してください")
    print("═" * 60)


def main():
    parser = argparse.ArgumentParser(description="video-generator.py — 最終動画生成")
    parser.add_argument("--assemble",   action="store_true", help="ffmpeg 組み立てモード")
    parser.add_argument("--job-file",   type=str, default="", help="video_job.json のパス")
    parser.add_argument("--task-id",    type=str, default="", help="特定 VPS タスク ID を指定")
    parser.add_argument("--design-id",  type=str, default="", help="Canva design_id を直接指定（URL解決失敗時）")
    args = parser.parse_args()

    if args.assemble:
        if not args.job_file:
            parser.error("--assemble には --job-file が必要です")
        assemble_mode(Path(args.job_file))
    else:
        setup_mode(task_id=args.task_id, design_id_override=args.design_id)


if __name__ == "__main__":
    main()
