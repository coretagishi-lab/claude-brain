#!/usr/bin/env python3
"""
DMMアフィリエイト コンテンツ審査Notion DBを作成する（初回のみ実行）

使用方法:
  python3 setup-notion-db.py

  # 親ページIDを直接指定する場合:
  python3 setup-notion-db.py --parent-page-id <NOTION_PAGE_ID>

完了後: 出力されたDB IDをVPSの tokens.md に追記する
  NOTION_CONTENT_DB_ID=<db_id>
"""
import os, json, urllib.request, urllib.error, argparse

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"


def notion(method, path, data=None):
    body = json.dumps(data).encode() if data else None
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


def find_accessible_pages():
    _, res = notion("POST", "/search", {
        "filter": {"value": "page", "property": "object"},
        "page_size": 10,
    })
    pages = []
    for item in res.get("results", []):
        title_parts = item.get("properties", {}).get("title", {}).get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts) if title_parts else "(無題)"
        pages.append({"id": item["id"], "title": title})
    return pages


def create_db(parent_page_id):
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "DMMアフィリエイト コンテンツ審査"}}],
        "is_inline": False,
        "properties": {
            "title": {"title": {}},
            "manga_title": {"rich_text": {}},
            "youtube_title": {"rich_text": {}},
            "description": {"rich_text": {}},
            "script": {"rich_text": {}},
            "affiliate_url": {"url": {}},
            "status": {
                "select": {
                    "options": [
                        {"name": "draft",    "color": "gray"},
                        {"name": "approved", "color": "green"},
                        {"name": "final",    "color": "blue"},
                        {"name": "uploaded", "color": "purple"},
                    ]
                }
            },
            "video_url": {"url": {}},
            "canva_url": {"url": {}},
            "created_at": {"date": {}},
        },
    }
    return notion("POST", "/databases", payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-page-id", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("❌ NOTION_TOKEN 未設定（source /root/.profile してください）")
        return

    parent_page_id = args.parent_page_id

    if not parent_page_id:
        print("🔍 アクセス可能なNotionページを検索中...")
        pages = find_accessible_pages()
        if not pages:
            print("❌ アクセス可能なページが見つかりません。")
            print("   NotionインテグレーションにページのアクセスをShareしてください。")
            return
        print("\n利用可能なページ:")
        for i, p in enumerate(pages):
            print(f"  {i+1}. {p['title']} (ID: {p['id']})")
        choice = input("\nDBを作成する親ページ番号を入力 (1〜): ").strip()
        try:
            parent_page_id = pages[int(choice) - 1]["id"]
        except (ValueError, IndexError):
            print("❌ 無効な入力")
            return

    print(f"\n📋 コンテンツ審査DBを作成中...")
    status, res = create_db(parent_page_id)

    if status == 200:
        db_id = res["id"].replace("-", "")
        db_url = res.get("url", "")
        print(f"✅ DB作成成功")
        print(f"\nDB ID: {db_id}")
        print(f"URL:   {db_url}")
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"VPS tokens.md に以下を追記してください:")
        print(f"  NOTION_CONTENT_DB_ID={db_id}")
        print(f"その後:")
        print(f"  python3 /opt/ai-brain/Shared/Workflows/cred-loader.py --update-profile")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    else:
        print(f"❌ DB作成失敗 ({status})")
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
