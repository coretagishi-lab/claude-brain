#!/usr/bin/env python3
"""
STEP 3: Notionキュー（status:queued）を処理
  - 画像をDiscord CDNからダウンロードしてbase64変換
  - Claude APIで8行テロップ形式の台本を生成
  - Notionをstatus:draftに更新
  - タスク確認ボードに「👀 確認待ち」で登録
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_TASK_BOARD_ID = "3671cad4aa98813b85b2ed9e3127b913"
NOTION_VERSION       = "2022-06-28"
DISCORD_WEBHOOK_URL  = os.environ.get("DISCORD_WEBHOOK_URL", "")

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
        with urllib.request.urlopen(req, timeout=30) as res:
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
        "image_url":     "".join(p.get("plain_text", "") for p in (page["properties"].get("image_url") or {}).get("rich_text", [])),
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
    status_code, resp = notion("PATCH", f"/pages/{page_id}", {"properties": props})
    if status_code not in (200, 204):
        raise RuntimeError(f"Notion status更新失敗 (HTTP {status_code}): {resp}")

    blocks = [
        {"object": "block", "type": "callout",
         "callout": {
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


def task_board_entry_exists(page_id):
    """同じ page_id の [台本確認] エントリがタスクボードに既存かチェック"""
    _, res = notion("POST", f"/databases/{NOTION_TASK_BOARD_ID}/query", {
        "filter": {
            "and": [
                {"property": "タスク名",   "title":     {"contains": "[台本確認]"}},
                {"property": "内容要約",   "rich_text": {"contains": f"page_id:{page_id}"}},
            ]
        },
        "page_size": 1,
    })
    return len(res.get("results", [])) > 0


def register_to_task_board(manga_title, telops, notion_url, cost_usd, page_id):
    """台本完成をタスク確認ボードに「👀 確認待ち」で登録（重複防止付き）"""
    if task_board_entry_exists(page_id):
        print(f"  ⚠️  タスクボード登録スキップ（page_id:{page_id[:8]}... は既存）")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    telop_text = "\n".join([f"{i+1}. {l}" for i, l in enumerate(telops)])
    notion("POST", "/pages", {
        "parent": {"database_id": NOTION_TASK_BOARD_ID},
        "properties": {
            "タスク名":           {"title": rt(f"[台本確認] {manga_title}")},
            "プロジェクト名":     {"select": {"name": "DMM漫画アフィリエイト"}},
            "ステータス":         {"select": {"name": "👀 確認待ち"}},
            "作成物":             {"rich_text": rt(telop_text)},
            "内容要約":           {"rich_text": rt(f"page_id:{page_id}\nコスト: ${cost_usd:.4f}\n詳細: {notion_url}")},
            "提出日時":           {"date": {"start": today}},
        }
    })


def notify_discord(manga_title, page_id, script=""):
    if not DISCORD_WEBHOOK_URL:
        return
    notion_url    = f"https://app.notion.com/p/{page_id.replace('-', '')}"
    task_board_url = f"https://app.notion.com/p/{NOTION_TASK_BOARD_ID.replace('-', '')}"

    # 台本プレビュー（最初の3行）
    preview = ""
    if script:
        lines = [l.strip() for l in script.strip().splitlines() if l.strip()][:3]
        preview = "\n".join(f"> {l}" for l in lines)
        if len([l for l in script.strip().splitlines() if l.strip()]) > 3:
            preview += "\n> ..."

    content = (
        f"📝 **台本生成完了：{manga_title}**\n"
        f"{preview}\n\n"
        f"✅ タスクボードで確認してください👇\n"
        f"https://www.notion.so/{NOTION_TASK_BOARD_ID.replace('-', '')}"
    )
    body = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (ai-brain, 1.0)",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
        print(f"  Discord通知送信OK")
    except Exception as e:
        print(f"  ⚠️  Discord通知失敗: {e}")


def fetch_images_to_dir(image_url_str, tmp_dir):
    """スペース区切りのURL群を全てダウンロードしてtmp_dirに保存。保存パスのリストを返す。"""
    urls = [u.strip() for u in image_url_str.split() if u.strip()]
    paths = []
    for i, url in enumerate(urls, 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as res:
                ct = res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                data = res.read()
            ext = ct.split("/")[-1].replace("jpeg", "jpg")
            path = os.path.join(tmp_dir, f"manga_{i:02d}.{ext}")
            with open(path, "wb") as f:
                f.write(data)
            paths.append(path)
            print(f"  画像{i}取得OK: manga_{i:02d}.{ext}")
        except Exception as e:
            print(f"  画像{i}取得失敗: {e}")
    return paths


def load_experience_rules():
    """experience.md からテロップ生成ルール＋改善ルールを読み込む"""
    if not EXPERIENCE_FILE.exists():
        return "", ""
    text = EXPERIENCE_FILE.read_text(encoding="utf-8")

    # テロップ生成ルール（確定ルール）
    m_telop = re.search(r"## テロップ生成ルール.*?(?=\n## |\Z)", text, re.DOTALL)
    telop_rules = m_telop.group(0).strip() if m_telop else ""

    # 改善ルール（週次分析で蓄積）
    m_improve = re.search(r"## 改善ルール（蓄積から導出）.*?(?=\n## |\Z)", text, re.DOTALL)
    improve_rules = ""
    if m_improve:
        r = m_improve.group(0).strip()
        improve_rules = "" if "まだ蓄積なし" in r else r

    return telop_rules, improve_rules


def get_variation_number(manga_title: str) -> int:
    """manga_titleの末尾丸数字からバリエーション番号（1〜6）を返す"""
    m = re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]$', manga_title)
    if m:
        return '①②③④⑤⑥⑦⑧⑨⑩'.index(m.group(0)) + 1
    return 1


def generate_content(manga_title, affiliate_url, img_paths, experience_rules):
    telop_rules, improve_rules = experience_rules
    variation_num = get_variation_number(manga_title)
    total_variations = 6

    # バリエーションごとに異なる視点を指示
    variation_hints = {
        1: "登場人物の内面の葛藤・躊躇い・ドキドキする瞬間にフォーカス",
        2: "身体的な接触・距離感・触れる瞬間の緊張感にフォーカス",
        3: "欲望が決壊する寸前・理性と本能の狭間にフォーカス",
        4: "相手への独占欲・嫉妬・「もっと」という衝動にフォーカス",
        5: "禁断感・後ろめたさ・それでも止められない感情にフォーカス",
        6: "クライマックス直前の高揚感・「もう戻れない」という決壊にフォーカス",
    }
    hint = variation_hints.get(variation_num, variation_hints[1])

    system_prompt = f"""あなたはDMMアフィリエイト漫画動画のテロップライターです。
漫画画像を読んでコマの内容・状況・感情を把握し、8行のテロップ台本を生成します。

{telop_rules}

【このバリエーションの指針】
これは同じ漫画の{total_variations}バリエーション中の{variation_num}番目です。
他のバリエーションと重複しないよう、以下の視点を特に強調してください：
「{hint}」

視聴者（男性）がムラムラする内容にすること。直接的・露骨な表現は禁止。
漫画に描かれていない心理・セリフを想像して補足してもOK。

【出力形式】
- telops はセリフ形式・①〜⑧の番号付き・「」不要
- 各テロップは20文字以内・VOICEVOXで自然に読める日本語
- 男女の掛け合いシーンは行頭に♂（男性）または♀（女性）を付ける
  例: ♂ お前のこと、ずっと好きだった / ♀ えっ…急にどうしたの
  一人語りシーンはマーカー不要
- youtube_title は60文字以内・断言形・【漫画】タグ付き
- description は250文字以内・煽り文 + アフィURL"""

    if improve_rules:
        system_prompt += f"\n\n【週次改善ルール】\n{improve_rules}"

    files_desc = "\n".join(f"- {p}" for p in img_paths) if img_paths else "（画像なし）"
    user_text = f"""漫画タイトル: {manga_title}
アフィリエイトURL: {affiliate_url or "（未設定）"}
バリエーション: {variation_num}/{total_variations}（{hint}）

以下の漫画画像ファイルを全て読み込んで、コマの状況・感情を各行に反映したテロップを生成してください。
{files_desc}

JSONのみ出力（説明不要）:
{{
  "youtube_title": "（60文字以内・断言形・【漫画】タグ付き）",
  "description": "（250文字以内・煽り文 + アフィURL）",
  "telops": [
    "①セリフ",
    "②セリフ",
    "③セリフ",
    "④セリフ",
    "⑤セリフ",
    "⑥セリフ",
    "⑦セリフ",
    "⑧セリフ"
  ]
}}"""

    try:
        if img_paths:
            tmp_dir = os.path.dirname(img_paths[0])
            cmd = [
                "claude", "-p",
                "--system-prompt", system_prompt,
                "--add-dir", tmp_dir,
                "--allowedTools", "Read",
            ]
        else:
            cmd = ["claude", "-p", "--system-prompt", system_prompt]

        result = subprocess.run(cmd, input=user_text, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"claude failed (exit {result.returncode}): {result.stderr[:200]}")
        text = result.stdout.strip()
    finally:
        pass

    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    json_text = m.group(1) if m else re.search(r"\{.*\}", text, re.DOTALL).group(0)
    return json.loads(json_text), 0, 0


def calc_cost(in_tok, out_tok):
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="Notionキュー処理スクリプト")
    parser.add_argument("--dry", action="store_true", help="ドライラン: Notion更新・Claude呼び出しを行わず対象件数だけ表示")
    args = parser.parse_args()

    missing = [k for k in ["NOTION_TOKEN", "NOTION_CONTENT_DB_ID"]
               if not os.environ.get(k)]
    if missing:
        print(f"[queue-processor] 環境変数未設定: {', '.join(missing)}")
        sys.exit(1)

    if args.dry:
        print(f"[queue-processor] DRY RUN モード（Notion更新・Claude呼び出しなし）")
    print(f"[queue-processor] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    pages = get_queued_pages()
    if not pages:
        print("[queue-processor] queued件数: 0  終了")
        return

    print(f"[queue-processor] queued件数: {len(pages)}")

    if args.dry:
        for page in pages:
            props = extract_props(page)
            print(f"  - {props['manga_title'] or '(タイトル未設定)'}  画像: {props['image_url'] or 'なし'}")
        print("[queue-processor] DRY RUN 終了（何も変更していません）")
        return

    experience_rules = load_experience_rules()
    total_cost = 0.0

    for page in pages:
        props = extract_props(page)
        print(f"\n  {props['manga_title'] or '(タイトル未設定)'}")

        tmp_dir = tempfile.mkdtemp(prefix="queue_imgs_")
        img_paths = fetch_images_to_dir(props["image_url"], tmp_dir) if props["image_url"] else []
        print(f"  画像: {len(img_paths)}枚取得")

        try:
            content, in_tok, out_tok = generate_content(
                props["manga_title"], props["affiliate_url"],
                img_paths, experience_rules,
            )
        except Exception as e:
            print(f"  生成失敗: {e}")
            continue
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

        cost = calc_cost(in_tok, out_tok)
        total_cost += cost
        print(f"  タイトル: {content['youtube_title']}")
        print(f"  テロップ: {len(content['telops'])}行  コスト: ${cost:.4f}")

        update_to_draft(props["page_id"], content, cost)

        notion_url = f"https://app.notion.com/p/{props['page_id'].replace('-', '')}"
        register_to_task_board(props["manga_title"], content["telops"], notion_url, cost, props["page_id"])
        print(f"  Notion: queued -> draft OK")
        print(f"  タスク確認ボード: 登録OK")
        notify_discord(props["manga_title"], props["page_id"])

    print(f"\n[queue-processor] 完了  合計コスト: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
