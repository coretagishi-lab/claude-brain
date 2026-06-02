#!/usr/bin/env bash
# ============================================================
# notion-sync.sh
# AI-Brain Projects/ → Notion タスク確認ボード 同期スクリプト
#
# 使用方法:
#   NOTION_TOKEN は ~/.zshrc に永続設定済み（手動 export 不要）
#   ./notion-sync.sh              # review_waiting: true のみ同期
#   ./notion-sync.sh --all        # 全プロジェクトを同期
#   ./notion-sync.sh --dry-run    # 書き込みなし・確認のみ
#   ./notion-sync.sh --verbose    # 詳細ログ
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECTS_DIR="$VAULT_ROOT/Projects"
DATABASE_ID="${NOTION_DATABASE_ID:-3671cad4-aa98-813b-85b2-ed9e3127b913}"
DRY_RUN=false
VERBOSE=false
SYNC_ALL=false

for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --verbose) VERBOSE=true ;;
    --all)     SYNC_ALL=true ;;
  esac
done

if [[ -z "${NOTION_TOKEN:-}" ]]; then
  echo "ERROR: NOTION_TOKEN が設定されていません"
  echo "  export NOTION_TOKEN=ntn_xxxx && ./notion-sync.sh"
  exit 1
fi

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 が必要です"; exit 1; }

python3 - "$PROJECTS_DIR" "$DATABASE_ID" "$NOTION_TOKEN" "$DRY_RUN" "$VERBOSE" "$SYNC_ALL" << 'PYTHON'
import sys, os, json, re, glob
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

projects_dir, database_id, token, dry_run_str, verbose_str, all_str = sys.argv[1:7]
DRY_RUN  = dry_run_str == "true"
VERBOSE  = verbose_str == "true"
SYNC_ALL = all_str == "true"

NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
JST = timezone(timedelta(hours=9))

# ────────────────────────────────────────────
# Notion API ヘルパー
# ────────────────────────────────────────────

def notion_req(method, endpoint, data=None):
    url = f"{NOTION_API}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            err = json.loads(err_body)
            print(f"  [ERROR] Notion API {e.code}: {err.get('message', err_body)}")
        except Exception:
            print(f"  [ERROR] Notion API {e.code}: {err_body}")
        raise

def find_open_task(project_name):
    """完了していない同プロジェクトのタスクを検索する"""
    result = notion_req("POST", f"databases/{database_id}/query", {
        "filter": {
            "and": [
                {"property": "プロジェクト名", "select": {"equals": project_name}},
                {"property": "完了", "checkbox": {"equals": False}}
            ]
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1
    })
    results = result.get("results", [])
    return results[0]["id"] if results else None

# ────────────────────────────────────────────
# ファイル解析
# ────────────────────────────────────────────

def parse_frontmatter(content):
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).splitlines():
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val.lower() == "true":
            val = True
        elif val.lower() == "false":
            val = False
        elif val in ("", '""'):
            val = ""
        fm[key] = val
    return fm

def parse_section(content, heading):
    """## heading セクションのテキストを取得する"""
    pattern = rf'## {re.escape(heading)}\n(.*?)(?=\n##|\Z)'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return ""
    lines = [l.lstrip('-').strip() for l in match.group(1).splitlines() if l.strip() and l.strip() != '-']
    return lines[0] if lines else ""

def parse_output_url(content):
    """## latest_output テーブルから最初の有効なURLを取得する"""
    match = re.search(r'## latest_output\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        cols = [c.strip() for c in line.split('|') if c.strip()]
        if len(cols) >= 4:
            url = cols[3]
            if url.startswith('http'):
                return url
    return ""

def format_date(date_str):
    """YYYY-MM-DD → Notion Date フォーマット（JST）"""
    if not date_str or date_str == "—":
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        dt = dt.replace(tzinfo=JST)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    except ValueError:
        return None

# ────────────────────────────────────────────
# プロパティ構築
# ────────────────────────────────────────────

def build_properties(fm, next_action, current_goal, output_url):
    project_name = fm.get("project_name", "Unknown")
    updated_at   = fm.get("updated_at", "")
    review_waiting = fm.get("review_waiting", False)
    if isinstance(review_waiting, str):
        review_waiting = review_waiting.lower() == "true"

    # 確認してほしい内容（Title）
    task_title = next_action if next_action else f"{project_name} — レビュー依頼"

    props = {
        "確認してほしい内容": {
            "title": [{"text": {"content": task_title[:2000]}}]
        },
        "プロジェクト名": {
            "select": {"name": project_name}
        },
        "完了": {
            "checkbox": False  # 新規作成時は必ず未完了
        },
        "確認回数": {
            "number": 0         # 初回は0
        },
    }

    # 提出日時
    date_val = format_date(updated_at)
    if date_val:
        props["提出日時"] = {"date": {"start": date_val}}

    # 内容要約
    if current_goal:
        props["内容要約"] = {
            "rich_text": [{"text": {"content": current_goal[:2000]}}]
        }

    # 作成物URL
    if output_url:
        props["作成物URL"] = {"url": output_url}

    return props

# ────────────────────────────────────────────
# 同期処理
# ────────────────────────────────────────────

def sync_project(status_file):
    with open(status_file, encoding="utf-8") as f:
        content = f.read()

    fm = parse_frontmatter(content)
    project_name   = fm.get("project_name", "").strip()
    review_waiting = fm.get("review_waiting", False)
    if isinstance(review_waiting, str):
        review_waiting = review_waiting.lower() == "true"

    if not project_name:
        print(f"  SKIP (project_name なし)")
        return "skip"

    # --all でない場合、review_waiting: true のみ同期
    if not SYNC_ALL and not review_waiting:
        print(f"  SKIP (review_waiting: false) — --all フラグで強制同期可能")
        return "skip"

    next_action  = parse_section(content, "next_action")
    current_goal = parse_section(content, "current_goal")
    output_url   = parse_output_url(content)
    props        = build_properties(fm, next_action, current_goal, output_url)

    if VERBOSE:
        print(f"  → 確認してほしい内容: {props['確認してほしい内容']['title'][0]['text']['content'][:50]}")
        print(f"  → プロジェクト名:     {project_name}")
        print(f"  → 提出日時:           {props.get('提出日時', {}).get('date', {}).get('start', 'なし')}")
        if '内容要約' in props:
            print(f"  → 内容要約:           {current_goal[:50]}{'...' if len(current_goal)>50 else ''}")
        if '作成物URL' in props:
            print(f"  → 作成物URL:          {output_url}")

    if DRY_RUN:
        print(f"  DRY-RUN → {'UPDATE' if find_open_task(project_name) else 'CREATE'}: {project_name}")
        return "dry-run"

    existing_id = find_open_task(project_name)

    if existing_id:
        # 既存の未完了タスクを更新（完了・確認回数はtagishiが操作するので上書きしない）
        update_props = {k: v for k, v in props.items() if k not in ("完了", "確認回数")}
        notion_req("PATCH", f"pages/{existing_id}", {"properties": update_props})
        print(f"  UPDATE ✓  {project_name}")
        return "update"
    else:
        notion_req("POST", "pages", {
            "parent": {"database_id": database_id},
            "properties": props
        })
        print(f"  CREATE ✓  {project_name}")
        return "create"

# ────────────────────────────────────────────
# エントリポイント
# ────────────────────────────────────────────

status_files = sorted(glob.glob(os.path.join(projects_dir, "*/PROJECT_STATUS.md")))

mode_label = "全プロジェクト" if SYNC_ALL else "review_waiting: true のみ"
print("=" * 54)
print(f"AI-Brain → Notion タスク確認ボード 同期{'（DRY-RUN）' if DRY_RUN else ''}")
print(f"モード:   {mode_label}")
print(f"Vault:    {projects_dir}")
print(f"Database: {database_id}")
print("=" * 54)

if not status_files:
    print("\nProjects/ にプロジェクトが見つかりません。")
    print("New Project Start Protocol でプロジェクトを追加後に実行してください。")
    sys.exit(0)

print(f"{len(status_files)} 件のプロジェクトをスキャン中...\n")

counts = {"create": 0, "update": 0, "skip": 0, "dry-run": 0, "error": 0}

for f in status_files:
    folder = os.path.basename(os.path.dirname(f))
    print(f"[{folder}]")
    try:
        result = sync_project(f)
        counts[result] = counts.get(result, 0) + 1
    except Exception as e:
        print(f"  ERROR: {e}")
        counts["error"] += 1
    print()

print("=" * 54)
if DRY_RUN:
    print(f"DRY-RUN 完了: {counts['dry-run']} 件（実際の書き込みなし）")
else:
    print(f"完了: CREATE {counts['create']} / UPDATE {counts['update']} / SKIP {counts['skip']} / ERROR {counts['error']}")
print("=" * 54)
PYTHON
