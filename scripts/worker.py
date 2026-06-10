#!/usr/bin/env python3
"""
brain-worker: Notion キュー監視 + claude 対話モードで自動処理

動作:
  1. POLL_INTERVAL 秒ごとに Notion の queued ページを確認
  2. queued があれば claude tmux ウィンドウに処理を依頼
  3. 結果を Notion に draft 登録 + タスク確認ボードに「👀 確認待ち」登録

新しいジョブを追加する場合:
  1. job_XXX(props) 関数を実装
  2. main() の poll_and_dispatch() に呼び出しを追加
"""
import json, os, re, subprocess, sys, time, uuid
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

TMUX_SESSION     = "brain-worker"
TMUX_CLAUDE_WIN  = "claude"
POLL_INTERVAL    = 30   # seconds
CLAUDE_TIMEOUT   = 180  # seconds per job


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
        "status":        {"select":    {"name": "draft"}},
        "youtube_title": {"rich_text": rt(content["youtube_title"])},
        "description":   {"rich_text": rt(content["description"])},
        "script":        {"rich_text": rt(script_text)},
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


# ── claude tmux ドライバー ─────────────────────────────────────────────────
def _tmux_target():
    return f"{TMUX_SESSION}:{TMUX_CLAUDE_WIN}"


def claude_send(prompt_md: str) -> tuple:
    """
    プロンプトを temp ファイルに書き込み、claude tmux ウィンドウに
    「ファイルを読んで実行してください」という1行指示を送る。
    Returns: (marker, tmp_path)
    """
    marker = "DONE_" + uuid.uuid4().hex[:10]
    tmp = Path(f"/tmp/brain_{marker}.md")
    tmp.write_text(prompt_md, encoding="utf-8")

    # 1行の ASCII-safe 指示（tmux send-keys は日本語も通るが短く安全に）
    instruction = (
        f"{tmp} をReadツールで読んで指示に従い実行してください。"
        f"回答の最後の行に「{marker}」とだけ書いてください。"
    )
    subprocess.run(["tmux", "send-keys", "-t", _tmux_target(), instruction, "Enter"])
    return marker, tmp


def claude_wait(marker: str, tmp: Path, timeout: int = CLAUDE_TIMEOUT) -> str:
    """
    tmux pane を3秒ごとにポーリングし、marker が現れたらペイン内容を返す。
    タイムアウト時は None。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", _tmux_target(), "-p", "-S", "-3000"],
            capture_output=True, text=True
        )
        if marker in result.stdout:
            tmp.unlink(missing_ok=True)
            return result.stdout
    tmp.unlink(missing_ok=True)
    return None


def parse_json_from_pane(pane: str, marker: str) -> dict:
    """ペイン出力の marker より前から JSON を抽出する。"""
    section = pane.split(marker)[0]
    # ```json ブロック優先
    m = re.search(r"```json\s*(\{.*?\})\s*```", section, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # bare JSON フォールバック
    m = re.search(r'\{\s*"youtube_title".*?\}', section, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return None


# ── ジョブ定義 ─────────────────────────────────────────────────────────────
def job_generate_script(props: dict) -> bool:
    """
    DMM 漫画 1件のテロップ台本を生成して Notion に登録する。
    新しいジョブを追加する場合はこの関数をテンプレートにする。
    """
    rules = load_experience_rules()
    rules_section = f"\n\n## 改善ルール\n{rules}" if rules else ""

    prompt = f"""## タスク
以下の漫画作品のYouTube Shorts用テロップ台本を生成してください。

## テロップルール
- 体言止め・各15文字以内
- ①〜⑧でストーリーの流れ: ①②フック → ③〜⑥展開・山場 → ⑦⑧結末・余韻
- VOICEVOXで読み上げるので自然な日本語{rules_section}

## 入力情報
- 漫画タイトル: {props['manga_title']}
- アフィリエイトURL: {props['affiliate_url'] or '（未設定）'}

## 出力形式
JSONのみ出力してください（説明文・前置き不要）:
```json
{{
  "youtube_title": "（60文字以内・断言形・【漫画】タグ付き）",
  "description": "（250文字以内・煽り文 + アフィURL）",
  "telops": ["①...", "②...", "③...", "④...", "⑤...", "⑥...", "⑦...", "⑧..."]
}}
```"""

    marker, tmp = claude_send(prompt)
    pane = claude_wait(marker, tmp)
    if not pane:
        print(f"  [ERROR] タイムアウト ({CLAUDE_TIMEOUT}s): {props['manga_title']}")
        return False

    content = parse_json_from_pane(pane, marker)
    if not content:
        print(f"  [ERROR] JSON解析失敗: {props['manga_title']}")
        return False

    update_to_draft(props["page_id"], content)
    notion_url = f"https://app.notion.com/p/{props['page_id'].replace('-', '')}"
    register_to_task_board(props["manga_title"], content["telops"], notion_url)
    print(f"  [OK] {props['manga_title']} → draft 登録完了")
    return True


# ── ポーリングループ ────────────────────────────────────────────────────────
def poll_and_dispatch():
    """
    1サイクル分の処理。新しいジョブを追加するときはここに追記する。

    例:
      for page in get_approved_pages():
          job_assemble_video(extract_props(page))
    """
    # ジョブ1: queued → テロップ台本生成
    pages = get_queued_pages()
    if pages:
        print(f"\n[{datetime.now().strftime('%H:%M')}] queued: {len(pages)}件")
        for page in pages:
            props = extract_props(page)
            print(f"  処理中: {props['manga_title'] or '(タイトル未設定)'}")
            job_generate_script(props)

    # ジョブ2（将来）: approved → 動画組み立て
    # for page in get_approved_pages():
    #     job_assemble_video(extract_props(page))

    # ジョブ3（将来）: 週次アナリティクス
    # job_weekly_analytics()


def main():
    missing = [k for k in ["NOTION_TOKEN", "NOTION_CONTENT_DB_ID"] if not os.environ.get(k)]
    if missing:
        print(f"[worker] ❌ 環境変数未設定: {', '.join(missing)}")
        sys.exit(1)

    print(f"[brain-worker] 起動: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"[brain-worker] ポーリング間隔: {POLL_INTERVAL}s | claude timeout: {CLAUDE_TIMEOUT}s")
    print(f"[brain-worker] tmux ターゲット: {_tmux_target()}")

    while True:
        try:
            poll_and_dispatch()
        except KeyboardInterrupt:
            print("\n[brain-worker] 停止")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M')}] [ERROR] {e}")

        # queued が 0 件のときだけ待機ログを出す
        pages = get_queued_pages()
        if not pages:
            print(f"[{datetime.now().strftime('%H:%M')}] queued: 0 | 次回確認まで {POLL_INTERVAL}s")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
