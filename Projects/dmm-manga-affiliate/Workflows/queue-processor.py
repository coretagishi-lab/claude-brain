#!/usr/bin/env python3
"""
STEP 3: Notionキュー（status:queued）を処理
  - 画像をDiscord CDNからダウンロードしてbase64変換
  - Claude APIで8行テロップ形式の台本を生成
  - Notionをstatus:draftに更新 + api_cost_estimate記録

Mac launchd で30分おき自動実行
"""
import base64, json, os, re, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"
MODEL                = "claude-sonnet-4-6"

PRICE_INPUT_PER_M  = 3.0
PRICE_OUTPUT_PER_M = 15.0

VAULT           = Path(__file__).resolve().parents[2]
EXPERIENCE_FILE = VAULT / "Knowledge" / "experience.md"


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


def update_to_draft(page_id, content, cost_usd):
    script_text = "\n".join([f"{i+1}. {l}" for i, l in enumerate(content["telops"])])
    props = {
        "status":            {"select":    {"name": "draft"}},
        "youtube_title":     {"rich_text": rt(content["youtube_title"])},
        "description":       {"rich_text": rt(content["description"])},
        "script":            {"rich_text": rt(script_text)},
        "api_cost_estimate": {"rich_text": rt(f"${cost_usd:.4f}")},
    }
    notion("PATCH", f"/pages/{page_id}", {"properties": props})

    blocks = [
        {"object": "block", "type": "callout",
         "callout": {
             "rich_text": rt("内容を確認してOKならチェックを入れてください → assemblerが動画を組み立てます"),
             "icon": {"emoji": "📋"},
         }},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("🎬 YouTubeタイトル")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": rt(content["youtube_title"])}},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("📝 テロップ8行（各15文字以内）")}},
    ]
    for i, line in enumerate(content["telops"], 1):
        blocks.append({
            "object": "block", "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": rt(line)},
        })
    blocks += [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": rt("📣 YouTube説明文")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": rt(content["description"])}},
        {"object": "block", "type": "callout",
         "callout": {
             "rich_text": rt(f"APIコスト: ${cost_usd:.4f} | 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
             "icon": {"emoji": "💰"},
         }},
    ]
    notion("PATCH", f"/blocks/{page_id}/children", {"children": blocks})


def fetch_image_b64(url):
    if not url:
        return None, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            content_type = res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            data = res.read()
        return base64.b64encode(data).decode(), content_type
    except Exception as e:
        print(f"  画像取得失敗: {e}")
        return None, None


def load_experience_rules():
    if not EXPERIENCE_FILE.exists():
        return ""
    text = EXPERIENCE_FILE.read_text(encoding="utf-8")
    m = re.search(r"## 改善ルール.*?(?=\n## |\Z)", text, re.DOTALL)
    if m:
        rules = m.group(0).strip()
        return "" if "まだ蓄積なし" in rules else rules
    return ""


def generate_content(manga_title, affiliate_url, image_b64, image_type, experience_rules):
    system = """あなたはDMMアフィリエイト漫画動画のテロップライターです。
漫画画像を読んでストーリーを把握し、8行のテロップ台本を生成します。

【ルール】
- テロップは体言止め・各15文字以内
- ①〜⑧の順で、ストーリーの流れに沿って
- 冒頭①②は主人公の状況・感情（フック）
- ③〜⑥は展開・山場
- ⑦⑧は結末・余韻（続きが気になる終わり方）
- VOICEVOXで読み上げるので自然な日本語で"""

    if experience_rules:
        system += f"\n\n【改善ルール】\n{experience_rules}"

    user_text = f"""漫画タイトル: {manga_title}
アフィリエイトURL: {affiliate_url or "（未設定）"}

この漫画画像を読んでテロップ台本を生成してください。
JSONのみ出力（説明不要）:
{{
  "youtube_title": "（60文字以内・断言形・【漫画】タグ付き）",
  "description": "（250文字以内・煽り文 + アフィURL）",
  "telops": [
    "①テロップ（15文字以内・体言止め）",
    "②テロップ",
    "③テロップ",
    "④テロップ",
    "⑤テロップ",
    "⑥テロップ",
    "⑦テロップ",
    "⑧テロップ"
  ]
}}"""

    user_content = []
    if image_b64:
        user_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": image_type, "data": image_b64},
        })
    user_content.append({"type": "text", "text": user_text})

    payload = {
        "model":      MODEL,
        "max_tokens": 1000,
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

    with urllib.request.urlopen(req) as res:
        resp = json.loads(res.read())

    text  = resp["content"][0]["text"].strip()
    usage = resp.get("usage", {})
    in_tok  = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)

    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    json_text = m.group(1) if m else re.search(r"\{.*\}", text, re.DOTALL).group(0)
    return json.loads(json_text), in_tok, out_tok


def calc_cost(in_tok, out_tok):
    return (in_tok * PRICE_INPUT_PER_M + out_tok * PRICE_OUTPUT_PER_M) / 1_000_000


def main():
    missing = [k for k in ["ANTHROPIC_API_KEY", "NOTION_TOKEN", "NOTION_CONTENT_DB_ID"]
               if not os.environ.get(k)]
    if missing:
        print(f"[queue-processor] 環境変数未設定: {', '.join(missing)}")
        sys.exit(1)

    print(f"[queue-processor] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    pages = get_queued_pages()
    if not pages:
        print("[queue-processor] queued件数: 0  終了")
        return

    print(f"[queue-processor] queued件数: {len(pages)}")
    experience_rules = load_experience_rules()
    total_cost = 0.0

    for page in pages:
        props = extract_props(page)
        print(f"\n  {props['manga_title'] or '(タイトル未設定)'}")

        img_b64, img_type = fetch_image_b64(props["image_url"])
        print(f"  画像: {'OK' if img_b64 else 'NG（テキストのみ）'}")

        try:
            content, in_tok, out_tok = generate_content(
                props["manga_title"], props["affiliate_url"],
                img_b64, img_type, experience_rules,
            )
        except Exception as e:
            print(f"  生成失敗: {e}")
            continue

        cost = calc_cost(in_tok, out_tok)
        total_cost += cost
        print(f"  タイトル: {content['youtube_title']}")
        print(f"  テロップ: {len(content['telops'])}行  コスト: ${cost:.4f}")

        update_to_draft(props["page_id"], content, cost)
        print(f"  Notion: queued -> draft OK")

    print(f"\n[queue-processor] 完了  合計コスト: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
