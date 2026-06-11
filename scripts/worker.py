#!/usr/bin/env python3
"""
brain-worker: Notion キュー監視 + Claude サブプロセスで自動処理

フロー:
  1. 30秒ごとに Notion の queued を確認
  2. queued が 0件 → Claude を呼ばない、ログだけ出して待機
  3. queued が 1件以上 → Claude を subprocess で1回起動して1件処理
  4. Claude 終了 → 次のポーリングまで待機

Claude の呼び方:
  subprocess.run(["claude"], input=prompt, ...)
  - claude -p は使わない
  - stdin にプロンプトを渡す対話モード起動
  - 処理が終わったら Claude プロセスは終了

新しいジョブを追加する場合:
  1. job_XXX(props) 関数を実装
  2. poll_once() に呼び出しを追記
"""
import json, os, re, subprocess, sys, time
import urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────────────────────────
NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_TASK_BOARD_ID = "3671cad4aa98813b85b2ed9e3127b913"
NOTION_VERSION       = "2022-06-28"
DISCORD_WEBHOOK_URL  = os.environ.get("DISCORD_WEBHOOK_URL", "")
JPY_PER_USD          = 155

VAULT           = Path(__file__).resolve().parent.parent
EXPERIENCE_FILE = VAULT / "Projects" / "dmm-manga-affiliate" / "Knowledge" / "experience.md"
AUDIO_DIR       = VAULT / "Projects" / "dmm-manga-affiliate" / "audio"

POLL_INTERVAL  = 30   # 秒
CLAUDE_TIMEOUT = 300  # 秒（Claude の応答待ち上限）

# 送信済みページID（セッション中に同じページを再送しない）
# 成功時: Notion status が変わるため自然にクエリから外れる
# 失敗時: _in_flight に残すことで連続再送を防ぐ（再試行は brain-worker 再起動で）
_in_flight: set          = set()   # queued → 台本生成
_in_flight_assembly: set = set()   # approved → Canva組み立て
_in_flight_cleanup: set  = set()   # youtube_done → メディア削除


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


def get_queued_pages():
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "queued"}},
        "sorts":  [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def get_approved_pages():
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "approved"}},
        "sorts":  [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def get_youtube_done_pages():
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "youtube_done"}},
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
        "affiliate_url": (page["properties"].get("affiliate_url") or {}).get("url") or "",
        "image_url":     (page["properties"].get("image_url") or {}).get("url") or "",
    }


def update_to_draft(page_id, content, cost_usd: float):
    jpy = int(cost_usd * JPY_PER_USD)
    cost_str = f"¥{jpy}円（${cost_usd:.4f}）消費 / 残高 $10.00から逆算"
    script_text = "\n".join(f"{i+1}. {l}" for i, l in enumerate(content["telops"]))
    notion("PATCH", f"/pages/{page_id}", {"properties": {
        "status":            {"select":    {"name": "draft"}},
        "youtube_title":     {"rich_text": rt(content["youtube_title"])},
        "description":       {"rich_text": rt(content["description"])},
        "script":            {"rich_text": rt(script_text)},
        "api_cost_estimate": {"rich_text": rt(cost_str)},
        "フィードバック":     {"rich_text": rt("")},
    }})
    blocks = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": rt("タスク確認ボードで確認してOKなら承認してください"),
            "icon": {"emoji": "📋"},
        }},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("🎬 YouTubeタイトル")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": rt(content["youtube_title"])}},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("📝 テロップ8行")}},
    ]
    for i, line in enumerate(content["telops"], 1):
        blocks.append({"object": "block", "type": "numbered_list_item",
                        "numbered_list_item": {"rich_text": rt(line)}})
    blocks += [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("📣 YouTube説明文")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": rt(content["description"])}},
        {"object": "block", "type": "callout", "callout": {
            "rich_text": rt(f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {cost_str}"),
            "icon": {"emoji": "💰"},
        }},
    ]
    notion("PATCH", f"/blocks/{page_id}/children", {"children": blocks})


def register_to_task_board(manga_title, telops, notion_url):
    telop_text = "\n".join(f"{i+1}. {l}" for i, l in enumerate(telops))
    notion("POST", "/pages", {
        "parent": {"database_id": NOTION_TASK_BOARD_ID},
        "properties": {
            "タスク名":       {"title": rt(f"[台本確認] {manga_title}")},
            "プロジェクト名": {"select": {"name": "DMM漫画アフィリエイト"}},
            "ステータス":     {"select": {"name": "👀 確認待ち"}},
            "作成物":         {"rich_text": rt(telop_text)},
            "内容要約":       {"rich_text": rt(f"詳細: {notion_url}")},
            "提出日時":       {"date": {"start": datetime.now().strftime("%Y-%m-%d")}},
        }
    })


def load_experience_rules():
    if not EXPERIENCE_FILE.exists():
        return ""
    text = EXPERIENCE_FILE.read_text(encoding="utf-8")
    m = re.search(r"## 改善ルール.*?(?=\n## |\Z)", text, re.DOTALL)
    if m:
        rules = m.group(0).strip()
        return "" if "まだ蓄積なし" in rules else rules
    return ""


def load_recent_feedback(limit: int = 5) -> str:
    """draft ページのうち「フィードバック」フィールドが記入済みのものを取得する。"""
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {
            "and": [
                {"property": "status", "select": {"equals": "draft"}},
                {"property": "フィードバック", "rich_text": {"is_not_empty": True}},
            ]
        },
        "sorts":  [{"property": "created_at", "direction": "descending"}],
        "page_size": limit,
    })
    pages = res.get("results", [])
    if not pages:
        return ""
    lines = []
    for page in pages:
        def txt(k):
            parts = page["properties"].get(k, {}).get("rich_text", [])
            return "".join(p.get("plain_text", "") for p in parts)
        title = txt("manga_title") or "(タイトル不明)"
        fb    = txt("フィードバック")
        if fb:
            lines.append(f"- 「{title}」: {fb}")
    if not lines:
        return ""
    return "## 過去のフィードバック（参考）\n" + "\n".join(lines)


def estimate_cost(prompt: str, output: str) -> float:
    """
    文字数からトークン数を推計してコストを計算する（概算）。
    日英混在テキスト: 約1.5文字 = 1トークン。
    claude-sonnet-4-6 料金: 入力 $3 / 出力 $15 (per million tokens)。
    """
    in_tok  = len(prompt) / 1.5
    out_tok = len(output) / 1.5
    return (in_tok * 3.0 + out_tok * 15.0) / 1_000_000


def notify_discord(manga_title: str, notion_url: str, cost_jpy: int):
    """台本完成を Discord #通知 チャンネルに webhook で通知する。"""
    if not DISCORD_WEBHOOK_URL:
        log("  ℹ️  DISCORD_WEBHOOK_URL 未設定のため通知スキップ")
        return
    body = json.dumps({
        "content": (
            f"✅ 台本完成: {manga_title}\n"
            f"👀 確認: {notion_url}\n"
            f"💰 消費: ¥{cost_jpy}円"
        )
    }).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        log(f"  ⚠️  Discord通知失敗: {e}")


# ── Claude サブプロセス ───────────────────────────────────────────────────
def invoke_claude(prompt: str) -> str:
    """
    claude コマンドをサブプロセスで起動し、stdin にプロンプトを渡す。
    claude -p は使わない。対話モードで起動し、処理完了後にプロセスを終了させる。
    """
    result = subprocess.run(
        ["claude"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
    )
    log(f"  claude exit={result.returncode} | "
        f"stdout={len(result.stdout)}文字 | stderr={result.stderr[:100]!r}")
    if result.returncode != 0:
        raise RuntimeError(
            f"claude failed (exit {result.returncode})\n"
            f"  stdout: {result.stdout[:300]!r}\n"
            f"  stderr: {result.stderr[:300]!r}"
        )
    return result.stdout.strip()


def extract_json(text: str) -> dict:
    """Claude の出力から JSON を抽出する。"""
    # ```json ブロック優先
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # bare JSON フォールバック
    m = re.search(r'\{\s*"youtube_title".*?\}', text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"JSON が見つかりません (出力の末尾: {text[-200:]!r})")


# ── ジョブ定義 ─────────────────────────────────────────────────────────────
def job_generate_script(props: dict) -> bool:
    """queued ページのテロップ台本を生成して Notion に draft 登録する。"""
    rules           = load_experience_rules()
    recent_feedback = load_recent_feedback()

    rules_section    = f"\n\n## 改善ルール（experience.mdより）\n{rules}" if rules else ""
    feedback_section = f"\n\n{recent_feedback}" if recent_feedback else ""

    prompt = f"""以下の漫画作品のYouTube Shorts用テロップ台本を生成してください。

## テロップルール
- 体言止め・各15文字以内
- トーン: 短編CM・短編小説風。見ている人がドキドキするような内容にする
- 直接的な性表現・官能的な言葉はNG（YouTube規約に引っかかるため絶対禁止）
- 間接的に「エッチな雰囲気」が伝わる表現にする
  例: 「秘密の関係」「禁断の夜」「熱い視線」「触れたい衝動」「甘い罠」
- ①〜⑧でストーリーの流れ: ①②フック → ③〜⑥展開・山場 → ⑦⑧結末（続きが読みたくなる余韻）
- VOICEVOXで読み上げるので自然な日本語{rules_section}{feedback_section}

## 入力
- 漫画タイトル: {props['manga_title']}
- アフィリエイトURL: {props['affiliate_url'] or '（未設定）'}

## 出力形式（JSONのみ・説明不要）
```json
{{
  "youtube_title": "（60文字以内・断言形・【漫画】タグ付き）",
  "description": "（250文字以内・煽り文 + アフィURL）",
  "telops": ["①...", "②...", "③...", "④...", "⑤...", "⑥...", "⑦...", "⑧..."]
}}
```"""

    raw      = invoke_claude(prompt)
    content  = extract_json(raw)
    cost_usd = estimate_cost(prompt, raw)
    cost_jpy = int(cost_usd * JPY_PER_USD)

    update_to_draft(props["page_id"], content, cost_usd)
    notion_url = f"https://app.notion.com/p/{props['page_id'].replace('-', '')}"
    register_to_task_board(props["manga_title"], content["telops"], notion_url)
    notify_discord(props["manga_title"], notion_url, cost_jpy)

    log(f"  ✅ {props['manga_title']} → draft 登録完了 (¥{cost_jpy}円 / ${cost_usd:.4f})")
    return True


def job_assemble_video(props: dict) -> bool:
    """approved ページを assembler.py に渡して Canva 組み立てを実行する。"""
    assembler = VAULT / "Projects" / "dmm-manga-affiliate" / "Workflows" / "assembler.py"
    env = os.environ.copy()
    env["NOTION_CONTENT_DB_ID"] = NOTION_CONTENT_DB_ID
    log(f"  🎨 assembler.py 起動: {props['manga_title']}")
    result = subprocess.run(
        [sys.executable, str(assembler)],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    for line in result.stdout.splitlines():
        log(f"  [assembler] {line}")
    if result.returncode != 0:
        for line in result.stderr.splitlines():
            log(f"  [assembler ERR] {line}")
        raise RuntimeError(f"assembler.py 失敗 (exit {result.returncode})")
    log(f"  ✅ {props['manga_title']} → Canva組み立て完了")
    return True


def job_cleanup_media(props: dict) -> bool:
    """
    youtube_done ページに対応するローカルの WAV / MP4 ファイルを削除する。
    audio_dir は manga_title から再構築してグロブで特定する。
    """
    if not AUDIO_DIR.exists():
        return True
    safe = re.sub(r'[^\w\-_]', '_', props["manga_title"])[:40]
    matched = list(AUDIO_DIR.glob(f"*_{safe}"))
    if not matched:
        log(f"  ℹ️  削除対象ディレクトリなし: {safe}")
        return True
    for d in matched:
        deleted = 0
        for f in d.iterdir():
            if f.suffix in (".wav", ".mp4"):
                f.unlink()
                deleted += 1
        try:
            d.rmdir()
        except OSError:
            pass
        log(f"  🗑  メディア削除: {deleted}件 ({d.name})")
    return True


# ── ポーリングループ ────────────────────────────────────────────────────────
def poll_once():
    """1サイクル分の処理。"""
    # ── ジョブ1: queued → テロップ台本生成 ──────────────────────────────
    all_queued = get_queued_pages()
    pending_scripts = [p for p in all_queued if p["id"] not in _in_flight]

    if pending_scripts:
        page  = pending_scripts[0]
        props = extract_props(page)
        remaining = len(pending_scripts) - 1
        log(f"queued: {len(all_queued)}件 | 処理開始: 「{props['manga_title'] or '(タイトル未設定)'}」"
            + (f" | 残り {remaining}件は次回" if remaining else ""))
        _in_flight.add(props["page_id"])
        try:
            job_generate_script(props)
        except Exception as e:
            log(f"  ❌ 失敗: {e}")
            log("  → Notion の該当ページを確認してください。再試行は brain-worker 再起動で。")
    elif all_queued:
        log(f"queued: {len(all_queued)}件 (すべて送信済み) | スキップ")
    else:
        log("queued: 0件 | 待機")

    # ── ジョブ2: approved → Canva 組み立て ──────────────────────────────
    all_approved = get_approved_pages()
    pending_assembly = [p for p in all_approved if p["id"] not in _in_flight_assembly]

    if pending_assembly:
        page  = pending_assembly[0]
        props = extract_props(page)
        remaining = len(pending_assembly) - 1
        log(f"approved: {len(all_approved)}件 | 組み立て開始: 「{props['manga_title'] or '(タイトル未設定)'}」"
            + (f" | 残り {remaining}件は次回" if remaining else ""))
        _in_flight_assembly.add(props["page_id"])
        try:
            job_assemble_video(props)
        except Exception as e:
            log(f"  ❌ 組み立て失敗: {e}")
    elif all_approved:
        log(f"approved: {len(all_approved)}件 (すべて処理中) | スキップ")

    # ── ジョブ3: youtube_done → ローカルメディア削除 ─────────────────────
    all_done = get_youtube_done_pages()
    pending_cleanup = [p for p in all_done if p["id"] not in _in_flight_cleanup]

    if pending_cleanup:
        page  = pending_cleanup[0]
        props = extract_props(page)
        log(f"youtube_done: {len(all_done)}件 | メディア削除: 「{props['manga_title'] or '(タイトル未設定)'}」")
        _in_flight_cleanup.add(props["page_id"])
        try:
            job_cleanup_media(props)
        except Exception as e:
            log(f"  ❌ メディア削除失敗: {e}")


def main():
    missing = [k for k in ["NOTION_TOKEN", "NOTION_CONTENT_DB_ID"] if not os.environ.get(k)]
    if missing:
        print(f"❌ 環境変数未設定: {', '.join(missing)}")
        sys.exit(1)

    log(f"brain-worker 起動 | ポーリング: {POLL_INTERVAL}s | Claude timeout: {CLAUDE_TIMEOUT}s")

    while True:
        try:
            poll_once()
        except KeyboardInterrupt:
            log("停止")
            break
        except Exception as e:
            log(f"❌ {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
