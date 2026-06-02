#!/usr/bin/env python3
"""
STEP 5: Notion（status:approved）からCanva配置指示を詳細生成
  - 台本・画像URLをもとにCanvaテンプレ配置指示（JSON）を生成
  - Notionページbodyに指示書を保存
  - status を canva_pending に更新 → VPS(dmm-canva-assembler)が処理

Mac launchd で30分おき自動実行（com.ai-brain.canva-instructions.plist）

環境変数:
  ANTHROPIC_API_KEY       必須
  NOTION_TOKEN            必須
  NOTION_CONTENT_DB_ID    必須
"""
import json, os, re, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"
MODEL                = "claude-sonnet-4-6"

PRICE_INPUT_PER_M  = 3.0
PRICE_OUTPUT_PER_M = 15.0

VAULT      = Path(__file__).resolve().parents[2]
STYLE_FILE = VAULT / "style.md"


# ── Notion API ─────────────────────────────────────────────────────────────────

def notion(method: str, path: str, data: dict = None):
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


def rt(text: str) -> list:
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def get_approved_pages() -> list:
    _, res = notion("POST", f"/databases/{NOTION_CONTENT_DB_ID}/query", {
        "filter": {"property": "status", "select": {"equals": "approved"}},
        "sorts":  [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def extract_props(page: dict) -> dict:
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


def update_to_canva_pending(page_id: str, instructions: dict, cost_usd: float):
    notion("PATCH", f"/pages/{page_id}", {
        "properties": {
            "status":            {"select": {"name": "canva_pending"}},
            "api_cost_estimate": {"rich_text": rt(
                f"${cost_usd:.4f}（canva-instructions）"
            )},
        }
    })
    # Notionページに指示書をコードブロックとして追記
    blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("🎨 Canva配置指示書")}},
        {"object": "block", "type": "callout",
         "callout": {
             "rich_text": rt("VPSがこの指示書を読んでCanvaに自動配置します"),
             "icon": {"emoji": "🤖"},
         }},
        {"object": "block", "type": "code",
         "code": {
             "rich_text": rt(json.dumps(instructions, ensure_ascii=False, indent=2)[:2000]),
             "language": "json",
         }},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": rt(
             f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}  コスト: ${cost_usd:.4f}"
         )}},
    ]
    notion("PATCH", f"/blocks/{page_id}/children", {"children": blocks})


# ── スタイル読み込み ────────────────────────────────────────────────────────────

def load_style() -> str:
    if STYLE_FILE.exists():
        return STYLE_FILE.read_text(encoding="utf-8")[:1000]
    return ""


# ── Claude API ────────────────────────────────────────────────────────────────

def generate_canva_instructions(props: dict, style: str) -> tuple:
    """(instructions_dict, in_tok, out_tok)"""

    script_lines = [l.strip() for l in props["script"].split("\n") if l.strip()]

    system = """あなたはCanva動画テンプレートの配置設計者です。
台本・画像情報をもとに、VPSが自動実行できる詳細なCanva配置指示書をJSON形式で生成します。

配置指示書の要件:
- 各ページに1コマ画像 + テロップ + VOICEVOX設定を対応させる
- テロップは体言止め・上部固定・白文字黒縁取り
- 最終ページのみCTA（「今すぐ読む」黄色テキスト）を追加
- VOICEVOXスピーカー: ナレーション=30, 男性=11, 女性=2
"""
    if style:
        system += f"\n\nプロジェクトスタイル:\n{style}"

    user = f"""以下の台本からCanva配置指示書を生成してください。JSONのみ出力してください。

漫画タイトル: {props['manga_title']}
YouTubeタイトル: {props['youtube_title']}
画像URL（素材）: {props['image_url'] or '（未設定）'}
アフィリエイトURL: {props['affiliate_url'] or '（未設定）'}

台本（{len(script_lines)}行）:
{chr(10).join(f'{i+1}. {l}' for i, l in enumerate(script_lines))}

出力JSON形式:
{{
  "template_name": "（使用するCanvaテンプレ名 — 未設定時は null）",
  "video_size": {{"width": 1080, "height": 1920}},
  "voicevox_speaker": 30,
  "pages": [
    {{
      "index": 0,
      "image_url": "（コマ画像URL — 同一素材を使い回してもよい）",
      "terop": "（テロップテキスト・体言止め・15文字以内）",
      "voicevox_text": "（VOICEVOX読み上げテキスト）",
      "duration_hint": "（推定秒数）"
    }}
  ],
  "cta_page": {{
    "terop": "今すぐ読む",
    "cta_url": "{props['affiliate_url'] or ''}",
    "voicevox_text": "今すぐDMMブックスでチェック！"
  }},
  "notes": "（VPSへの補足メモ）"
}}"""

    payload = {
        "model":      MODEL,
        "max_tokens": 2000,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        })

    with urllib.request.urlopen(req) as res:
        resp = json.loads(res.read())

    text  = resp["content"][0]["text"].strip()
    usage = resp.get("usage", {})
    in_tok  = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)

    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    json_text = m.group(1) if m else re.search(r"\{.*\}", text, re.DOTALL).group(0)
    return json.loads(json_text), in_tok, out_tok


def calc_cost(in_tok: int, out_tok: int) -> float:
    return (in_tok * PRICE_INPUT_PER_M + out_tok * PRICE_OUTPUT_PER_M) / 1_000_000


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    missing = [k for k in ["ANTHROPIC_API_KEY", "NOTION_TOKEN", "NOTION_CONTENT_DB_ID"]
               if not os.environ.get(k)]
    if missing:
        print(f"[canva-instructions] ❌ 環境変数未設定: {', '.join(missing)}")
        sys.exit(1)

    print(f"[canva-instructions] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    pages = get_approved_pages()
    if not pages:
        print("[canva-instructions] approved件数: 0  終了")
        return

    print(f"[canva-instructions] approved件数: {len(pages)}")
    style = load_style()
    total_cost = 0.0

    for page in pages:
        props = extract_props(page)
        print(f"\n  📖 {props['manga_title']}")

        if not props["script"]:
            print(f"     ⚠️ 台本が空です。スキップします。")
            continue

        try:
            instructions, in_tok, out_tok = generate_canva_instructions(props, style)
        except Exception as e:
            print(f"     ❌ 生成失敗: {e}")
            continue

        cost = calc_cost(in_tok, out_tok)
        total_cost += cost
        pages_count = len(instructions.get("pages", []))
        print(f"     ページ数: {pages_count}  コスト: ${cost:.4f}")

        update_to_canva_pending(props["page_id"], instructions, cost)
        print(f"     Notion: approved → canva_pending ✅")
        print(f"     → VPS(dmm-canva-assembler)が配置を実行します")

    print(f"\n[canva-instructions] 完了  合計コスト: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
