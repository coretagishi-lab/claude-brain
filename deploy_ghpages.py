#!/usr/bin/env python3
"""
Deploy inbox-sender.html to gh-pages branch of coretagishi-lab/claude-brain
Uses the Git Objects API to create an orphan branch (no history baggage)
"""
import json, base64, urllib.request, urllib.error, sys

TOKEN = "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"
OWNER = "coretagishi-lab"
REPO  = "claude-brain"
BASE  = f"https://api.github.com/repos/{OWNER}/{REPO}"

def req(method, url, data=None):
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "inbox-deploy/1.0",
    })
    try:
        with urllib.request.urlopen(r) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

# ── HTML を読み込み ─────────────────────────────────────
with open("inbox-sender.html", "r", encoding="utf-8") as f:
    html = f.read()

html_b64 = base64.b64encode(html.encode("utf-8")).decode()

# index.html = inbox-sender.html にリダイレクト（短いURLでもアクセス可能）
redirect_html = """<!DOCTYPE html>
<html><head>
<meta http-equiv="refresh" content="0;url=inbox-sender.html">
<title>Inbox</title>
</head><body>
<a href="inbox-sender.html">Inbox</a>
</body></html>"""
redirect_b64 = base64.b64encode(redirect_html.encode()).decode()

# ── gh-pages ブランチの存在確認 ──────────────────────────
status, _ = req("GET", f"{BASE}/branches/gh-pages")

if status == 404:
    print("📁 gh-pages ブランチを新規作成中（orphan）...")

    # 1. inbox-sender.html の blob 作成
    s, blob = req("POST", f"{BASE}/git/blobs", {"content": html_b64, "encoding": "base64"})
    print(f"   blob (inbox-sender.html): {blob['sha'][:12]}")

    # 2. index.html の blob 作成
    s, rblob = req("POST", f"{BASE}/git/blobs", {"content": redirect_b64, "encoding": "base64"})
    print(f"   blob (index.html):        {rblob['sha'][:12]}")

    # 3. tree 作成（2ファイル）
    s, tree = req("POST", f"{BASE}/git/trees", {"tree": [
        {"path": "inbox-sender.html", "mode": "100644", "type": "blob", "sha": blob["sha"]},
        {"path": "index.html",        "mode": "100644", "type": "blob", "sha": rblob["sha"]},
    ]})
    print(f"   tree: {tree['sha'][:12]}")

    # 4. commit 作成（親なし = orphan）
    s, commit = req("POST", f"{BASE}/git/commits", {
        "message": "Deploy inbox-sender.html via GitHub Pages",
        "tree": tree["sha"],
    })
    print(f"   commit: {commit['sha'][:12]}")

    # 5. gh-pages ブランチ作成
    s, ref = req("POST", f"{BASE}/git/refs", {
        "ref": "refs/heads/gh-pages",
        "sha": commit["sha"],
    })
    if s == 201:
        print("   ✅ ブランチ gh-pages 作成完了")
    else:
        print(f"   ❌ ブランチ作成失敗: {s} {ref}")
        sys.exit(1)

else:
    print("🔄 gh-pages ブランチが既存 → ファイル更新中...")

    for filename, content_b64 in [
        ("inbox-sender.html", html_b64),
        ("index.html",        redirect_b64),
    ]:
        s, existing = req("GET", f"{BASE}/contents/{filename}?ref=gh-pages")
        body = {
            "message": f"Update {filename}",
            "content": content_b64,
            "branch": "gh-pages",
        }
        if s == 200:
            body["sha"] = existing["sha"]
        s, _ = req("PUT", f"{BASE}/contents/{filename}", body)
        print(f"   {filename}: {'✅' if s in (200,201) else '❌'} ({s})")

# ── GitHub Pages を有効化 ────────────────────────────────
print("\n🌐 GitHub Pages を有効化中...")
s, pages = req("POST", f"{BASE}/pages", {
    "source": {"branch": "gh-pages", "path": "/"}
})
if s == 201:
    print("   ✅ Pages 有効化完了")
elif s == 409:
    print("   ℹ️  Pages は既に有効 → ソース設定を更新中...")
    s, pages = req("PUT", f"{BASE}/pages", {
        "source": {"branch": "gh-pages", "path": "/"}
    })
    print(f"   更新: {s}")
else:
    print(f"   ⚠️  Pages API: {s}")
    print(f"   → GitHubリポジトリのSettings > Pages で手動設定も可能")
    print(f"     Source: gh-pages ブランチ / root")

# ── 結果 ────────────────────────────────────────────────
print()
print("=" * 50)
print("✅ デプロイ完了！")
print()
print("📱 iPhoneでアクセス:")
print(f"   https://{OWNER}.github.io/{REPO}/inbox-sender.html")
print()
print("   （短縮URL）")
print(f"   https://{OWNER}.github.io/{REPO}/")
print()
print("⏱  GitHub Pages の反映には1〜3分かかります")
print("=" * 50)
