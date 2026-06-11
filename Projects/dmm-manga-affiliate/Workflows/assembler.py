#!/usr/bin/env python3
"""
assembler.py — Notion approved → Canva 組み立て + VOICEVOX 音声生成

フロー:
  1. Notion status=approved を取得
  2. 画像を catbox.moe にアップロード（Canva 用公開 URL 取得）
  3. claude サブプロセスで Canva MCP 操作:
       テンプレコピー → タイトル書き換え → 画像挿入 → テロップ書き換え
  4. VOICEVOX（localhost:50021）でめたん音声生成 → audio/ に保存
  5. Notion: status=canva_ready、canva_url を記録
  6. タスク確認ボードに「👀 確認待ち」+ Canva URL 登録
  7. Discord #通知 に完成通知

使い方:
  python3 assembler.py          # approved を全件処理
  python3 assembler.py --dry    # Notion 更新せずに確認

環境変数（必須）:
  NOTION_TOKEN
  NOTION_CONTENT_DB_ID

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

VAULT      = Path(__file__).resolve().parents[2]
AUDIO_DIR  = VAULT / "Projects" / "dmm-manga-affiliate" / "audio"

VOICEVOX_URL = "http://localhost:50021"
VOICEVOX_SPEAKER = 47  # ナースロボ＿タイプT ノーマル（アカウントごとに変更可）

CLAUDE_TIMEOUT = 600   # Canva 操作は時間がかかるため長めに設定

# ── Canva テンプレート情報（handoff.md より） ──────────────────────────────
TEMPLATE_ID = "DAHKogY0SBo"

ELEM_MANGA_TITLE = "PBs1sTlCLqHDSG14-LBrqdhnZYLPRPyJX"  # ページ1「男の漫画」プレースホルダ行

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

IMAGE_SLOT_P2 = "PBG3BLhBZW05Kb0W-LBLG8GxWtKLtPZcZ"  # ページ2 画像スロット
# ページ3〜9 の画像スロット ID は Canva 操作時に get-design-pages で動的取得


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
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def rt(text):
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


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
        "image_url":     (page["properties"].get("image_url") or {}).get("url") or "",
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


def generate_all_voices(manga_title: str, telops: list) -> Path:
    """
    テロップ全行の音声を生成して audio/{safe_title}/ ディレクトリに保存。
    各 WAV の前後に無音（前0.3秒・後0.5秒）を挿入する。
    Returns: 保存先ディレクトリ
    """
    safe = re.sub(r'[^\w\-_]', '_', manga_title)[:40]
    date = datetime.now().strftime("%Y%m%d")
    out_dir = AUDIO_DIR / f"{date}_{safe}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, telop in enumerate(telops, 1):
        path = out_dir / f"telop_{i:02d}.wav"
        try:
            wav = generate_voice(telop)
            path.write_bytes(wav)
            add_silence_padding(path)
            log(f"  🎙 telop_{i:02d}.wav 生成完了 ({len(telop)}文字、前0.3s+後0.5s無音挿入)")
        except Exception as e:
            log(f"  ⚠️  telop_{i:02d} 音声生成失敗: {e}")

    return out_dir


# ── Claude サブプロセス: Canva MCP 操作 ───────────────────────────────────
def invoke_claude(prompt: str) -> str:
    """claude をサブプロセスで起動し stdin にプロンプトを渡す。"""
    result = subprocess.run(
        ["claude"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
    )
    log(f"  claude exit={result.returncode} | "
        f"stdout={len(result.stdout)}文字 | stderr={result.stderr[:80]!r}")
    if result.returncode != 0:
        raise RuntimeError(
            f"claude failed (exit {result.returncode})\n"
            f"stdout: {result.stdout[:400]!r}\n"
            f"stderr: {result.stderr[:200]!r}"
        )
    return result.stdout.strip()


def build_canva_prompt(props: dict, public_image_url: str, telops: list,
                       audio_dir: Path = None) -> str:
    """Canva MCP 操作の詳細指示を作成する。"""

    telop_ops = "\n".join(
        f"  - element_id: {eid}  →  テキスト: 「{t}」"
        for eid, t in zip(TELOP_ELEM_IDS, telops)
    )

    telops_per_page = "\n".join(
        f"  ページ{i+2}: {t}"
        for i, t in enumerate(telops)
    )

    audio_section = ""
    if audio_dir and audio_dir.exists():
        wav_lines = "\n".join(
            f"  telop_{i+1:02d}.wav → {audio_dir / f'telop_{i+1:02d}.wav'}"
            for i in range(len(telops))
        )
        audio_section = f"""
## 音声ファイル（VOICEVOX 生成済み）
保存先: {audio_dir}
{wav_lines}
（各ファイルは前0.3秒・後0.5秒の無音を含む）
"""

    return f"""以下の手順で Canva デザインを組み立ててください。
Canva MCP ツール（mcp__claude_ai_Canva__ 系）を使用してください。

## 作業データ
- テンプレートID: {TEMPLATE_ID}
- 漫画タイトル: {props['manga_title']}
- 画像URL（公開済み）: {public_image_url}
- テロップ ({len(telops)}行):
{telops_per_page}

## 漫画画像のコマ構成
元画像サイズ: 1000×1399px（2列×3行 = 6コマ）
スロットサイズ: 954×837px

コマ位置（元画像内の座標）:
  コマ1(左上):  x=0,   y=0,    w=500, h=466
  コマ2(右上):  x=500, y=0,    w=500, h=466
  コマ3(左中):  x=0,   y=466,  w=500, h=466
  コマ4(右中):  x=500, y=466,  w=500, h=466
  コマ5(左下):  x=0,   y=932,  w=500, h=466
  コマ6(右下):  x=500, y=932,  w=500, h=466

各ページのテロップ内容に合ったコマを選んでズーム表示してください（同コマの複数使用可）。
ズーム方法: update_fill → resize_element でスロット全体を覆うようにスケール → position_element でコマ中心を合わせる

---

## 手順 1: テンプレートをコピー
`copy-design` ツールで design_id={TEMPLATE_ID} をコピーしてください。
取得した新しい design_id を以降の手順で使用します。

## 手順 2: 編集トランザクション開始
`start-editing-transaction` で新しい design_id のトランザクションを開始してください。

## 手順 3: ページ構成確認
`get-design-pages` でページ一覧を取得してください。

## 手順 4: タイトル書き換え（ページ1）
`perform-editing-operations` で以下を実行してください。
element_id は必ず以下の固定値を使用し、自分でページを探して別のIDを使わないでください:
- element_id: {ELEM_MANGA_TITLE}
- 操作: update_text
- テキスト: "{props['manga_title']}"
（このスロットには現在「男の漫画」というテキストが入っています）

## 手順 5: 画像を Canva にアップロード
`upload-asset-from-url` で以下の URL から画像をアップロードし asset_id を取得:
URL: {public_image_url}

## 手順 6: ページ1のトップ画像スロットに画像を差し込む
`get-design-content` でページ1の要素を確認し、画像スロット（image要素）の element_id を特定してください。
その後 `perform-editing-operations` で:
- 操作: update_fill (fill_type: IMAGE, asset_id: <取得したasset_id>)
ページ1は導入スライドのため、画像全体（ズームなし）を表示してください。

## 手順 7: ページ2〜9に画像を差し込む（コマ別ズーム）
各ページのテロップに合った適切なコマを選択し、ズーム表示してください。

ページ2の既知スロット ID: {IMAGE_SLOT_P2}
ページ3〜9: `get-design-pages` で各ページの画像スロット element_id を取得してください。

各スロットに対して:
- `update_fill` で asset_id を設定
- `resize_element` + `position_element` で選択したコマにズーム

## 手順 8: テロップ書き換え（ページ2〜9）
`perform-editing-operations` で以下を順番に実行:
{telop_ops}

各テロップの操作: update_text

## 手順 9: トランザクションをコミット
`commit-editing-transaction` でトランザクションをコミットしてください。

## 手順 10: Canva URL を取得
`get-design` で新しい design_id のデザイン情報を取得し、URL を確認してください。

---

## 完了後の出力（必須）
全手順が完了したら、以下の形式で結果を返してください:

DESIGN_ID=<新しいdesign_id>
CANVA_URL=<CanvaデザインのURL>
STATUS=success

エラーが発生した場合:
STATUS=error
ERROR=<エラーの詳細>
{audio_section}"""


def run_canva_assembly(props: dict, public_image_url: str, telops: list,
                       audio_dir: Path = None) -> tuple:
    """
    claude subprocess で Canva 組み立てを実行。
    Returns: (design_id, canva_url)
    """
    prompt = build_canva_prompt(props, public_image_url, telops, audio_dir=audio_dir)
    output = invoke_claude(prompt)

    design_id = ""
    canva_url  = ""

    m = re.search(r"DESIGN_ID=(\S+)", output)
    if m:
        design_id = m.group(1).strip()

    m = re.search(r"CANVA_URL=(https://\S+)", output)
    if m:
        canva_url = m.group(1).strip().rstrip(".,")

    if not canva_url:
        # フォールバック: canva.com URL を探す
        m = re.search(r"https://www\.canva\.com/design/\S+", output)
        if m:
            canva_url = m.group(0).rstrip(".,)")

    if not canva_url and not design_id:
        raise RuntimeError(f"Canva URL が取得できませんでした。\n出力末尾: {output[-400:]!r}")

    # design_id から URL を構築（canva_url が取れなかった場合のフォールバック）
    if not canva_url and design_id:
        canva_url = f"https://www.canva.com/design/{design_id}/edit"

    return design_id, canva_url


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

    # ── 画像アップロード ──────────────────────────────────────────────────
    public_image_url = ""
    if props["image_url"]:
        log(f"  📥 画像ダウンロード: {props['image_url'][:60]}...")
        img_bytes, img_type = download_image(props["image_url"])
        if img_bytes:
            log(f"  📤 catbox.moe にアップロード中...")
            public_image_url = upload_to_catbox(img_bytes, img_type or "image/jpeg")
            if public_image_url:
                log(f"  ✅ 公開URL: {public_image_url}")
            else:
                log("  ⚠️  アップロード失敗 → 画像なしで続行")
        else:
            log("  ⚠️  画像取得失敗 → 画像なしで続行")
    else:
        log("  ℹ️  image_url なし → 画像挿入スキップ")

    # ── VOICEVOX 音声生成 ─────────────────────────────────────────────────
    if voicevox_available():
        log(f"  🎙 VOICEVOX 音声生成開始 (speaker={VOICEVOX_SPEAKER})")
        audio_dir = generate_all_voices(manga_title, [t for t in telops if t])
        log(f"  ✅ 音声保存先: {audio_dir}")
    else:
        log(f"  ⚠️  VOICEVOX ({VOICEVOX_URL}) に接続できません → 音声生成スキップ")
        audio_dir = None

    # ── Canva 組み立て（claude subprocess） ──────────────────────────────
    if dry:
        log("  [DRY] Canva 操作スキップ")
        log(f"  [DRY] 送信予定プロンプト先頭:\n{build_canva_prompt(props, public_image_url, telops, audio_dir=audio_dir)[:300]}")
        return True

    log("  🎨 Canva 組み立て開始（claude subprocess）...")
    design_id, canva_url = run_canva_assembly(props, public_image_url, telops, audio_dir=audio_dir)
    log(f"  ✅ design_id: {design_id}")
    log(f"  ✅ canva_url: {canva_url}")

    # ── Notion 更新 ───────────────────────────────────────────────────────
    notion_url = f"https://app.notion.com/p/{props['page_id'].replace('-', '')}"
    update_to_canva_ready(props["page_id"], canva_url, design_id, dry=dry)
    log("  ✅ Notion: approved → canva_ready")

    # ── タスク確認ボード ───────────────────────────────────────────────────
    register_to_task_board(manga_title, canva_url, notion_url, dry=dry)
    log("  ✅ タスク確認ボード登録完了")

    # ── Discord 通知 ───────────────────────────────────────────────────────
    notify_discord(manga_title, canva_url, notion_url)

    return True


def main():
    dry = "--dry" in sys.argv

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
            success = process_page(props, dry=dry)
            if success:
                ok += 1
            else:
                ng += 1
        except Exception as e:
            log(f"  ❌ 処理失敗: {e}")
            ng += 1

    log(f"\n完了: ✅ {ok}件 / ❌ {ng}件")


if __name__ == "__main__":
    main()
