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

VAULT           = Path(__file__).resolve().parent.parent
EXPERIENCE_FILE = VAULT / "Projects" / "dmm-manga-affiliate" / "Knowledge" / "experience.md"

POLL_INTERVAL  = 30   # 秒
CLAUDE_TIMEOUT = 300  # 秒（Claude の応答待ち上限）

# 送信済みページID（セッション中に同じページを再送しない）
# 成功時: Notion status が "draft" になるため自然に queued クエリから外れる
# 失敗時: _in_flight に残すことで連続再送を防ぐ（再試行は brain-worker 再起動で）
_in_flight: set = set()


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


def update_to_draft(page_id, content):
    script_text = "\n".join(f"{i+1}. {l}" for i, l in enumerate(content["telops"]))
    notion("PATCH", f"/pages/{page_id}", {"properties": {
        "status":            {"select":    {"name": "draft"}},
        "youtube_title":     {"rich_text": rt(content["youtube_title"])},
        "description":       {"rich_text": rt(content["description"])},
        "script":            {"rich_text": rt(script_text)},
        "api_cost_estimate": {"rich_text": rt("claude Code (無料)")},
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
            "rich_text": rt(f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | claude Code (無料)"),
            "icon": {"emoji": "🤖"},
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
    rules = load_experience_rules()
    rules_section = f"\n\n## 改善ルール\n{rules}" if rules else ""

    prompt = f"""以下の漫画作品のYouTube Shorts用テロップ台本を生成してください。

## テロップルール
- 体言止め・各15文字以内
- ①〜⑧でストーリーの流れ: ①②フック → ③〜⑥展開・山場 → ⑦⑧結末・余韻
- VOICEVOXで読み上げるので自然な日本語{rules_section}

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

    raw = invoke_claude(prompt)
    content = extract_json(raw)

    update_to_draft(props["page_id"], content)
    notion_url = f"https://app.notion.com/p/{props['page_id'].replace('-', '')}"
    register_to_task_board(props["manga_title"], content["telops"], notion_url)
    log(f"  ✅ {props['manga_title']} → draft 登録完了")
    return True


# ── ポーリングループ ────────────────────────────────────────────────────────
def poll_once():
    """
    1サイクル分の処理。新しいジョブを追加するときはここに追記する。

    追加例（将来）:
      approved = get_approved_pages()
      if approved:
          pending = [p for p in approved if p["id"] not in _in_flight]
          if pending:
              _in_flight.add(pending[0]["id"])
              job_assemble_video(extract_props(pending[0]))
    """
    # ── ジョブ1: queued → テロップ台本生成 ──────────────────────────────
    all_queued = get_queued_pages()

    if not all_queued:
        log("queued: 0件 | Claude を呼ばずに待機")
        return

    pending = [p for p in all_queued if p["id"] not in _in_flight]
    if not pending:
        log(f"queued: {len(all_queued)}件 (すべて送信済み) | スキップ")
        return

    page = pending[0]
    props = extract_props(page)
    remaining = len(pending) - 1

    log(f"queued: {len(all_queued)}件 | 処理開始: 「{props['manga_title'] or '(タイトル未設定)'}」"
        + (f" | 残り {remaining}件は次回" if remaining else ""))

    # 送信前に登録（失敗時も再送しない）
    _in_flight.add(props["page_id"])

    try:
        job_generate_script(props)
    except Exception as e:
        log(f"  ❌ 失敗: {e}")
        log("  → Notion の該当ページを確認してください。再試行は brain-worker 再起動で。")


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
