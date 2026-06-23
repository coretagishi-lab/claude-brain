#!/usr/bin/env python3
"""
upload-scheduler.py — 公開3日前の動画を自動アップロード

launchd から毎日 6:00 に実行される。
VPS Outbox の "youtube投稿待ち" タスクを確認し、
publish_at - 3日 <= 今日 のものを youtube-uploader.py で投稿する。

動画ファイルパス: ~/Library/ai-brain/videos/{manga_title}_完成.mp4
"""
import json, os, re, subprocess, sys, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOTION_TOKEN         = os.environ.get("NOTION_TOKEN", "")
NOTION_CONTENT_DB_ID = os.environ.get("NOTION_CONTENT_DB_ID", "")
NOTION_VERSION       = "2022-06-28"
OUTBOX_DB_ID         = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"
JST                  = timezone(timedelta(hours=9))
UPLOAD_DAYS_BEFORE   = 3  # 公開何日前にアップロードするか

VIDEOS_DIR   = Path.home() / "Library" / "ai-brain" / "videos"
SCRIPT_DIR   = Path(__file__).resolve().parent
UPLOADER     = SCRIPT_DIR / "youtube-uploader.py"
LOG_FILE     = Path.home() / "Library" / "Logs" / "ai-brain" / "upload-scheduler.log"


def log(msg: str):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def notion(method: str, path: str, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=body, method=method,
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get_pending_upload_tasks() -> list:
    """VPS Outboxから "youtube投稿待ち" タスクを取得"""
    _, res = notion("POST", f"/databases/{OUTBOX_DB_ID}/query", {
        "filter": {"and": [
            {"property": "type",   "select": {"equals": "vps-task"}},
            {"property": "status", "select": {"equals": "pending"}},
            {"property": "title",  "title":  {"contains": "youtube投稿待ち"}},
        ]},
        "sorts": [{"property": "created_at", "direction": "ascending"}],
    })
    return res.get("results", [])


def get_task_content(task_id: str) -> str:
    """タスクページのブロックをテキストとして返す"""
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
    m = re.search(r"/p/([0-9a-f]{32})", content)
    if m:
        raw = m.group(1)
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    m = re.search(r"page_id:([0-9a-f\-]{32,36})", content)
    if m:
        raw = m.group(1).replace("-", "")
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return ""


def get_content_page(page_id: str) -> dict:
    _, res = notion("GET", f"/pages/{page_id}")
    props = res.get("properties", {})
    def text(k):
        return "".join(p.get("plain_text", "")
                       for p in props.get(k, {}).get("rich_text", []))
    publish_at_raw = props.get("publish_at", {}).get("date", {})
    return {
        "page_id":     page_id,
        "manga_title": text("manga_title"),
        "publish_at":  publish_at_raw.get("start") if publish_at_raw else None,
    }


TASK_BOARD_ID = "3671cad4aa98813b85b2ed9e3127b913"

def update_review_task_status(manga_title: str, new_status: str):
    """タスクボードの[動画確認]エントリをステータス更新"""
    _, res = notion("POST", f"/databases/{TASK_BOARD_ID}/query", {
        "filter": {"property": "タスク名", "title": {"contains": "[動画確認]"}},
        "page_size": 20,
    })
    for item in res.get("results", []):
        name = "".join(p.get("plain_text", "") for p in item["properties"]["タスク名"]["title"])
        if manga_title in name:
            notion("PATCH", f"/pages/{item['id']}", {
                "properties": {"ステータス": {"select": {"name": new_status}}}
            })
            log(f"  ✅ タスクボード更新: [動画確認] {manga_title} → {new_status}")
            return
    log(f"  ⚠️  タスクボードエントリ未検出: [動画確認] {manga_title}")


def mark_task_done(task_id: str, resolution: str):
    notion("PATCH", f"/pages/{task_id}", {
        "properties": {"status": {"select": {"name": "completed"}}}
    })
    notion("PATCH", f"/blocks/{task_id}/children", {"children": [{
        "object": "block", "type": "callout", "callout": {
            "rich_text": [{"type": "text", "text": {
                "content": f"✅ upload-scheduler が処理 [{datetime.now(JST).strftime('%Y-%m-%d %H:%M')}]\n{resolution}"
            }}],
            "icon": {"type": "emoji", "emoji": "✅"},
            "color": "green_background",
        }
    }]})


def should_upload_now(publish_at_str: str) -> bool:
    """publish_at - UPLOAD_DAYS_BEFORE日 <= 今日 なら True"""
    if not publish_at_str:
        return True  # publish_at未設定なら即アップロード
    try:
        pub_dt = datetime.fromisoformat(publish_at_str)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=JST)
        upload_date = pub_dt - timedelta(days=UPLOAD_DAYS_BEFORE)
        return datetime.now(JST) >= upload_date
    except Exception:
        return True


def main():
    if not NOTION_TOKEN:
        log("❌ NOTION_TOKEN 未設定")
        sys.exit(1)

    log("upload-scheduler 起動")
    tasks = get_pending_upload_tasks()

    if not tasks:
        log("✅ youtube投稿待ちタスクなし")
        return

    log(f"📋 youtube投稿待ち: {len(tasks)}件")

    for task in tasks:
        task_id    = task["id"]
        task_title = "".join(p.get("plain_text", "")
                             for p in task["properties"]["title"]["title"])
        log(f"\n  タスク: {task_title}")

        content = get_task_content(task_id)
        page_id = extract_page_id(content)
        if not page_id:
            log("  ⚠️  page_id 抽出失敗 → スキップ")
            continue

        props       = get_content_page(page_id)
        manga_title = props["manga_title"]
        publish_at  = props["publish_at"]

        log(f"  漫画: {manga_title} / 公開予定: {publish_at or '未設定'}")

        # 投稿待ちステータスに更新（アップロード前も含め全件）
        update_review_task_status(manga_title, "投稿待ち")

        if not should_upload_now(publish_at):
            pub_dt    = datetime.fromisoformat(publish_at)
            upload_dt = pub_dt - timedelta(days=UPLOAD_DAYS_BEFORE)
            log(f"  ⏳ アップロード予定日まで待機: {upload_dt.strftime('%Y-%m-%d')} 以降")
            continue

        # 動画ファイルを探す
        video_path = VIDEOS_DIR / f"{manga_title}_完成.mp4"
        if not video_path.exists():
            log(f"  ⚠️  動画ファイルが見つかりません: {video_path}")
            log("  → video-generator.py --assemble が完了しているか確認してください")
            continue

        log(f"  📤 アップロード開始: {video_path.name}")
        result = subprocess.run(
            ["python3", str(UPLOADER),
             "--video",   str(video_path),
             "--page-id", page_id],
            capture_output=True, text=True, timeout=600
        )

        if result.returncode == 0:
            log(f"  ✅ アップロード完了")
            log(result.stdout[-500:] if result.stdout else "")
            update_review_task_status(manga_title, "投稿済")
            mark_task_done(task_id, f"upload-scheduler が自動アップロード完了\n動画: {video_path.name}")
        else:
            log(f"  ❌ アップロード失敗 (exit {result.returncode})")
            log(result.stderr[-300:] if result.stderr else "")

    log("upload-scheduler 終了")


if __name__ == "__main__":
    main()
