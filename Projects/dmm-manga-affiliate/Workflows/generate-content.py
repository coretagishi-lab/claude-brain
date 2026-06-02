#!/usr/bin/env python3
"""
STEP 1: 台本・タイトル・説明文を1回のAPIで生成 → Notion「コンテンツ審査」に投稿

使用方法:
  python3 generate-content.py \\
    --manga-title "漫画タイトル" \\
    --affiliate-url "https://al.dmm.co.jp/?lurl=..."

環境変数（tokens.md 経由で自動設定）:
  ANTHROPIC_API_KEY       必須
  NOTION_TOKEN            必須
  NOTION_CONTENT_DB_ID    必須（setup-notion-db.py で取得）
"""
import os, json, re, urllib.request, urllib.error, argparse
from pathlib import Path
from datetime import datetime

ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"
MODEL                = "claude-sonnet-4-6"

VAULT           = Path(__file__).resolve().parents[2]
EXPERIENCE_FILE = VAULT / "Knowledge" / "experience.md"


def load_experience_rules():
    if not EXPERIENCE_FILE.exists():
        return ""
    text = EXPERIENCE_FILE.read_text(encoding="utf-8")
    m = re.search(r"## 改善ルール.*?(?=\n## |\Z)", text, re.DOTALL)
    if m:
        rules = m.group(0).strip()
        # 「まだ蓄積なし」なら空扱い
        if "まだ蓄積なし" in rules:
            return ""
        return rules
    return ""


def generate_content(manga_title, affiliate_url, experience_rules):
    system_prompt = """あなたはDMMアフィリエイト漫画動画の台本ライターです。
VOICEVOX音声で読み上げるナレーション台本と、YouTubeタイトル・説明文を生成します。

【スタイルルール】
- 動画フォーマット: 9:16縦型（YouTube Shorts / Instagram向け）
- ナレーション: 感情的・共感型。主人公の葛藤・成長・希望を軸にする
- タイトル: 断言形（疑問形は避ける）。CTRを意識した強いコピー
- テロップは体言止めで統一
- 冒頭に主人公の不安・葛藤を入れる
- 全体を通して感情の起伏を作る（不安 → 転換 → 希望）"""

    if experience_rules:
        system_prompt += f"\n\n【蓄積された改善ルール】\n{experience_rules}"

    user_message = f"""以下の漫画のアフィリエイト動画コンテンツをJSON形式で生成してください。

漫画タイトル: {manga_title}
アフィリエイトURL: {affiliate_url}

出力形式（JSONのみ出力。前後に説明文不要）:
{{
  "youtube_title": "YouTubeタイトル（60文字以内・断言形・【漫画】などタグ付き）",
  "description": "YouTube説明文（250文字以内・魅力的な煽り文 + アフィリエイトURL）",
  "script": [
    "ナレーション1文目（1発話15秒以内）",
    "ナレーション2文目",
    "ナレーション3文目",
    ...
  ]
}}

scriptは10〜15行。各行がVOICEVOX 1発話に対応する。体言止めを多用。"""

    payload = {
        "model": MODEL,
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })

    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read())

    text = data["content"][0]["text"].strip()
    # JSON部分を抽出（```json ... ``` も考慮）
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)

    return json.loads(text)


def notion_req(method, path, data=None):
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


def rich_text(content):
    return [{"type": "text", "text": {"content": content[:2000]}}]


def post_to_notion(manga_title, affiliate_url, content):
    today = datetime.now().strftime("%Y-%m-%d")
    page_title = f"[{today}] {manga_title}"
    script_joined = "\n".join(content["script"])

    props = {
        "title":         {"title": rich_text(page_title)},
        "manga_title":   {"rich_text": rich_text(manga_title)},
        "youtube_title": {"rich_text": rich_text(content["youtube_title"])},
        "description":   {"rich_text": rich_text(content["description"])},
        "script":        {"rich_text": rich_text(script_joined)},
        "affiliate_url": {"url": affiliate_url},
        "status":        {"select": {"name": "draft"}},
        "created_at":    {"date": {"start": today}},
    }

    blocks = [
        {
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": rich_text("status を 'approved' に変更するとVPSが動画制作を開始します"),
                "icon": {"emoji": "📋"},
            }
        },
        {
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": rich_text("🎬 YouTubeタイトル")},
        },
        {
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich_text(content["youtube_title"])},
        },
        {
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": rich_text("📝 台本（VOICEVOX用）")},
        },
    ]
    for i, line in enumerate(content["script"], 1):
        blocks.append({
            "object": "block", "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": rich_text(line)},
        })

    blocks += [
        {
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": rich_text("📣 YouTube説明文")},
        },
        {
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich_text(content["description"])},
        },
    ]

    status, res = notion_req("POST", "/pages", {
        "parent": {"database_id": NOTION_CONTENT_DB_ID},
        "properties": props,
        "children": blocks,
    })
    return status, res


def main():
    parser = argparse.ArgumentParser(description="STEP 1: コンテンツ生成 → Notion投稿")
    parser.add_argument("--manga-title",   required=True, help="漫画タイトル")
    parser.add_argument("--affiliate-url", required=True, help="DMMアフィリエイトURL")
    args = parser.parse_args()

    missing = [v for v in ["ANTHROPIC_API_KEY", "NOTION_TOKEN", "NOTION_CONTENT_DB_ID"]
               if not os.environ.get(v)]
    if missing:
        print(f"❌ 環境変数未設定: {', '.join(missing)}")
        print("   source /root/.profile  または  source ~/.profile")
        return

    print(f"📖 漫画タイトル: {args.manga_title}")

    experience_rules = load_experience_rules()
    if experience_rules:
        print("✅ 改善ルール反映済み")
    else:
        print("ℹ️  改善ルールなし（初回実行）")

    print("\n🤖 Claude APIでコンテンツ生成中...")
    try:
        content = generate_content(args.manga_title, args.affiliate_url, experience_rules)
    except Exception as e:
        print(f"❌ 生成失敗: {e}")
        return

    print(f"\n📝 生成結果:")
    print(f"  タイトル : {content['youtube_title']}")
    print(f"  台本行数 : {len(content['script'])}行")
    print(f"  説明文   : {content['description'][:60]}...")

    print("\n📤 Notion「コンテンツ審査」に投稿中...")
    status, res = post_to_notion(args.manga_title, args.affiliate_url, content)

    if status == 200:
        url = res.get("url", "")
        print(f"✅ 投稿成功")
        print(f"\n👉 Notionで確認・修正したら status を 'approved' に変更してください")
        print(f"   {url}")
    else:
        print(f"❌ 投稿失敗 ({status})")
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
