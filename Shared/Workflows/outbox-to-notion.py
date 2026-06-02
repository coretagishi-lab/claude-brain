#!/usr/bin/env python3
"""
outboxの内容をNotion AI Outboxデータベースに書き込む

対象1: GitHub outbox.md（ルート）の新規エントリ
       → Claude実行エージェントの報告書

対象2: AI-Brain/Outbox/*.md（ローカル）status: pending のファイル
       → Claude Codeセッションの出力

送信済み追跡: AI-Brain/Outbox/.sent_hashes に送信済みエントリのhashを記録
"""
import os, json, re, hashlib, urllib.request, urllib.error, base64
from pathlib import Path
from datetime import datetime

NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
NOTION_VERSION = "2022-06-28"
OUTBOX_DB_ID   = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"

OWNER = "coretagishi-lab"
REPO  = "claude-brain"

VAULT       = Path(__file__).resolve().parents[2]
OUTBOX_DIR  = VAULT / "Outbox"
HASHES_FILE = OUTBOX_DIR / ".sent_hashes"

# ── Notion API ────────────────────────────────────────────────
def notion(method, path, data=None):
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(
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

# ── GitHub API ────────────────────────────────────────────────
def gh_fetch(path):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "outbox-sync"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            d = json.loads(res.read())
            return base64.b64decode(d["content"].replace("\n", "")).decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

# ── 送信済みhash管理 ─────────────────────────────────────────
def load_hashes():
    if HASHES_FILE.exists():
        return set(HASHES_FILE.read_text().splitlines())
    return set()

def save_hash(h):
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    with HASHES_FILE.open("a") as f:
        f.write(h + "\n")

def entry_hash(text):
    return hashlib.sha1(text.strip().encode()).hexdigest()[:16]

# ── Markdown → Notion blocks ──────────────────────────────────
def md_blocks(body):
    blocks = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            blocks.append({"object":"block","type":"heading_3","heading_3":
                {"rich_text":[{"type":"text","text":{"content":s[4:]}}]}})
        elif s.startswith("## "):
            blocks.append({"object":"block","type":"heading_2","heading_2":
                {"rich_text":[{"type":"text","text":{"content":s[3:]}}]}})
        elif s.startswith("# "):
            blocks.append({"object":"block","type":"heading_1","heading_1":
                {"rich_text":[{"type":"text","text":{"content":s[2:]}}]}})
        elif s.startswith("- "):
            blocks.append({"object":"block","type":"bulleted_list_item","bulleted_list_item":
                {"rich_text":[{"type":"text","text":{"content":s[2:]}}]}})
        elif re.match(r"^\d+\. ", s):
            blocks.append({"object":"block","type":"numbered_list_item","numbered_list_item":
                {"rich_text":[{"type":"text","text":{"content":re.sub(r"^\d+\. ","",s)}}]}})
        else:
            blocks.append({"object":"block","type":"paragraph","paragraph":
                {"rich_text":[{"type":"text","text":{"content":s}}]}})
    return blocks[:100]

# ── Notionページ作成 ──────────────────────────────────────────
def post_to_notion(title, body, entry_type="log", project="", date_str=None):
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    props = {
        "title":      {"title": [{"type":"text","text":{"content": title[:100]}}]},
        "status":     {"select": {"name": "sent"}},
        "created_at": {"date":   {"start": date_str}},
    }
    if entry_type in {"note","task","decision","log"}:
        props["type"] = {"select": {"name": entry_type}}
    if project:
        props["project"] = {"rich_text": [{"type":"text","text":{"content": project}}]}

    s, res = notion("POST", "/pages", {
        "parent":     {"database_id": OUTBOX_DB_ID},
        "properties": props,
        "children":   md_blocks(body),
    })
    return s == 200, res.get("url", "")

# ── frontmatter パース ────────────────────────────────────────
def parse_fm(text):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text.strip()
    fm = {}
    for line in m.group(1).splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, m.group(2).strip()

def update_fm(path, updates):
    text = path.read_text(encoding="utf-8")
    for k, v in updates.items():
        if re.search(rf"^{k}:", text, re.MULTILINE):
            text = re.sub(rf'^{k}:.*$', f'{k}: "{v}"', text, flags=re.MULTILINE)
        else:
            text = re.sub(r'(^---\n)', rf'\1{k}: "{v}"\n', text)
    path.write_text(text, encoding="utf-8")

# ── ① GitHub outbox.md → Notion ──────────────────────────────
def sync_github_outbox(sent_hashes):
    print("  [GitHub outbox.md]")
    content = gh_fetch("outbox.md")
    if not content:
        print("    ℹ️  outbox.md が見つかりません。スキップ。")
        return 0

    # "### YYYY-MM-DD" または "### テキスト — " で分割
    sections = re.split(r'\n(?=### )', content)
    sent = 0
    for sec in sections:
        sec = sec.strip()
        if not sec or sec.startswith("# ") or not sec.startswith("###"):
            continue

        h = entry_hash(sec)
        if h in sent_hashes:
            continue

        # タイトルと日付を抽出
        first_line = sec.splitlines()[0]
        title_m = re.match(r"### (.+)", first_line)
        title   = title_m.group(1) if title_m else first_line[:80]
        date_m  = re.search(r"(\d{4}-\d{2}-\d{2})", title)
        date_str = date_m.group(1) if date_m else datetime.now().strftime("%Y-%m-%d")
        body    = "\n".join(sec.splitlines()[1:]).strip()

        ok, url = post_to_notion(title, body, entry_type="log", project="claude-brain", date_str=date_str)
        if ok:
            save_hash(h)
            sent += 1
            print(f"    ✅ {title[:60]}")
        else:
            print(f"    ❌ 送信失敗: {title[:60]}")

    if sent == 0:
        print("    ℹ️  新規エントリなし")
    return sent

# ── ② ローカル Outbox/*.md → Notion ──────────────────────────
def sync_local_outbox():
    print("  [ローカル Outbox/]")
    pending = sorted(f for f in OUTBOX_DIR.glob("*.md") if f.name != "README.md")
    sent = 0
    for path in pending:
        fm, body = parse_fm(path.read_text(encoding="utf-8"))
        if fm.get("status") != "pending":
            continue

        title   = fm.get("title") or path.stem
        print(f"    → {path.name}: {title}")
        ok, url = post_to_notion(
            title, body,
            entry_type = fm.get("type", "note"),
            project    = fm.get("project", ""),
            date_str   = fm.get("created_at", ""),
        )
        if ok:
            update_fm(path, {
                "status":     "sent",
                "sent_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
                "notion_url": url,
            })
            sent += 1
            print(f"      ✅ {url}")
        else:
            print(f"      ❌ 送信失敗")

    if sent == 0:
        print("    ℹ️  送信待ちなし")
    return sent

# ── メイン ────────────────────────────────────────────────────
def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] outbox-to-notion start")

    if not NOTION_TOKEN:
        print("  ❌ NOTION_TOKEN 未設定")
        return

    sent_hashes = load_hashes()
    total = 0

    total += sync_github_outbox(sent_hashes)
    print("")
    total += sync_local_outbox()

    print(f"\n  outbox-to-notion done. 計 {total} 件送信。")

if __name__ == "__main__":
    main()
