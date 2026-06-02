#!/usr/bin/env bash
# ============================================================
# gdrive-upload.sh
# 指定ファイルを Google Drive の [プロジェクト名] サブフォルダへ
# アップロードし、共有URLをNotionタスク確認ボードに書き込む
#
# 使い方:
#   ./Shared/Workflows/gdrive-upload.sh [プロジェクト名] [ファイルパス]
#   ./Shared/Workflows/gdrive-upload.sh [プロジェクト名] [ファイルパス] --no-notion
#   ./Shared/Workflows/gdrive-upload.sh [プロジェクト名] [ファイルパス] --dry-run
#
# 事前条件:
#   .credentials/gdrive-oauth-client.json が必要（初回のみ設定）
#   → 取得手順: ./Shared/Workflows/gdrive-upload.sh --setup
#
# NOTION_TOKEN は ~/.zshrc に永続設定済み（手動 export 不要）
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OAUTH_CLIENT_FILE="$VAULT_ROOT/.credentials/gdrive-oauth-client.json"
OAUTH_TOKEN_FILE="$VAULT_ROOT/.credentials/gdrive-oauth-token.json"
ROOT_FOLDER_ID="1MznW63WBQuKIDbKE1q9KhoLvWybKQGaM"
DATABASE_ID="${NOTION_DATABASE_ID:-3671cad4-aa98-813b-85b2-ed9e3127b913}"

# --setup フラグで手順を表示
if [[ "${1:-}" == "--setup" ]]; then
  echo "================================================"
  echo " gdrive-upload.sh セットアップ手順"
  echo "================================================"
  echo ""
  echo "【ステップ1】Google Cloud Console でOAuth2クライアントIDを作成"
  echo ""
  echo "  1. https://console.cloud.google.com/apis/credentials"
  echo "     プロジェクト: ai-brain-497108 を選択"
  echo ""
  echo "  2. 「+認証情報を作成」→「OAuth クライアント ID」"
  echo "     アプリケーションの種類: 「デスクトップ アプリ」"
  echo "     名前: gdrive-uploader（任意）"
  echo ""
  echo "  3. 作成後「JSONをダウンロード」をクリック"
  echo ""
  echo "  4. ダウンロードしたファイルをこのパスに配置:"
  echo "     $OAUTH_CLIENT_FILE"
  echo ""
  echo "【ステップ2】初回認証（ブラウザが自動で開きます）"
  echo ""
  echo "  ./Shared/Workflows/gdrive-upload.sh --auth"
  echo ""
  echo "  ブラウザでGoogleアカウントにログイン → アクセスを許可"
  echo "  完了後、以降は認証不要でアップロードできます"
  echo ""
  echo "【ステップ3】テスト実行"
  echo ""
  echo "  ./Shared/Workflows/gdrive-upload.sh test /tmp/test.txt --no-notion"
  echo "================================================"
  exit 0
fi

PROJECT_NAME=""
FILE_PATH=""
DRY_RUN=false
NO_NOTION=false
AUTH_ONLY=false

for arg in "$@"; do
  case $arg in
    --dry-run)   DRY_RUN=true ;;
    --no-notion) NO_NOTION=true ;;
    --auth)      AUTH_ONLY=true ;;
    *)
      if [[ -z "$PROJECT_NAME" ]]; then
        PROJECT_NAME="$arg"
      elif [[ -z "$FILE_PATH" ]]; then
        FILE_PATH="$arg"
      fi
      ;;
  esac
done

# --auth: 認証のみ実行
if [[ "$AUTH_ONLY" == "true" ]]; then
  if [[ ! -f "$OAUTH_CLIENT_FILE" ]]; then
    echo "ERROR: OAuth2クライアントファイルが見つかりません"
    echo "  → ./Shared/Workflows/gdrive-upload.sh --setup で手順を確認"
    exit 1
  fi
  python3 -c "import google_auth_oauthlib" 2>/dev/null || pip3 install --quiet google-auth-oauthlib google-api-python-client google-auth
  python3 - "$OAUTH_CLIENT_FILE" "$OAUTH_TOKEN_FILE" << 'PYAUTH'
import sys, json
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPES = ["https://www.googleapis.com/auth/drive"]
client_file, token_file = sys.argv[1], sys.argv[2]
flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
creds = flow.run_local_server(port=0)
with open(token_file, "w") as f:
    f.write(creds.to_json())
print(f"認証完了。トークンを保存しました: {token_file}")
PYAUTH
  exit 0
fi

if [[ -z "$PROJECT_NAME" || -z "$FILE_PATH" ]]; then
  echo "使い方: $0 [プロジェクト名] [ファイルパス] [--dry-run] [--no-notion]"
  echo "       $0 --setup    # セットアップ手順を表示"
  echo "       $0 --auth     # 初回OAuth認証"
  echo ""
  echo "例:"
  echo "  $0 manga-ads output/reel_001.mp4"
  echo "  $0 ai-girls flux_output.png --no-notion"
  exit 1
fi

if [[ ! -f "$FILE_PATH" ]]; then
  echo "ERROR: ファイルが見つかりません: $FILE_PATH"
  exit 1
fi

if [[ ! -f "$OAUTH_CLIENT_FILE" && "$DRY_RUN" == "false" ]]; then
  echo "ERROR: OAuth2クライアントファイルが見つかりません"
  echo "  → ./Shared/Workflows/gdrive-upload.sh --setup で手順を確認"
  exit 1
fi

# ── 依存パッケージの確認・自動インストール ──
python3 -c "import googleapiclient, google.oauth2, google_auth_oauthlib" 2>/dev/null || {
  echo "必要なPythonパッケージをインストール中..."
  pip3 install --quiet google-api-python-client google-auth google-auth-oauthlib 2>&1 | grep -v "^$" | tail -3
  echo "インストール完了"
}

NOTION_TOKEN="${NOTION_TOKEN:-}"

python3 - \
  "$OAUTH_CLIENT_FILE" \
  "$OAUTH_TOKEN_FILE" \
  "$ROOT_FOLDER_ID" \
  "$PROJECT_NAME" \
  "$FILE_PATH" \
  "$DATABASE_ID" \
  "$NOTION_TOKEN" \
  "$DRY_RUN" \
  "$NO_NOTION" \
  "$VAULT_ROOT" \
<< 'PYTHON'

import sys, os, json, re, mimetypes, glob
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

(oauth_client_file, oauth_token_file, root_folder_id, project_name,
 file_path, database_id, notion_token, dry_run_str, no_notion_str, vault_root) = sys.argv[1:11]

DRY_RUN   = dry_run_str  == "true"
NO_NOTION = no_notion_str == "true"

JST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────
# Google OAuth2 認証
# ──────────────────────────────────────────

import warnings
warnings.filterwarnings("ignore")  # Python 3.9 deprecation warnings を抑制

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_credentials():
    creds = None
    if os.path.exists(oauth_token_file):
        creds = Credentials.from_authorized_user_file(oauth_token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(oauth_token_file, "w") as f:
                f.write(creds.to_json())
        else:
            print("  ブラウザで認証が必要です。自動的にブラウザが開きます...")
            flow = InstalledAppFlow.from_client_secrets_file(oauth_client_file, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(oauth_token_file, "w") as f:
                f.write(creds.to_json())
            print("  認証完了")
    return creds

def get_drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)

# ──────────────────────────────────────────
# Google Drive ヘルパー
# ──────────────────────────────────────────

def is_shared_drive(service, folder_id):
    try:
        f = service.files().get(
            fileId=folder_id, fields="driveId", supportsAllDrives=True
        ).execute()
        return bool(f.get("driveId"))
    except Exception:
        return False

def find_folder(service, name, parent_id, shard):
    q = (
        f"name = '{name}' "
        f"and '{parent_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    result = service.files().list(
        q=q, fields="files(id, name)", pageSize=1,
        supportsAllDrives=shard, includeItemsFromAllDrives=shard
    ).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None

def create_folder(service, name, parent_id, shard):
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(
        body=meta, fields="id", supportsAllDrives=shard
    ).execute()
    return folder["id"]

def upload_file(service, local_path, parent_id, shard):
    filename = os.path.basename(local_path)
    mime_type, _ = mimetypes.guess_type(local_path)
    mime_type = mime_type or "application/octet-stream"
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    meta  = {"name": filename, "parents": [parent_id]}
    return service.files().create(
        body=meta, media_body=media, fields="id, name, webViewLink",
        supportsAllDrives=shard
    ).execute()

def make_public(service, file_id, shard):
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        supportsAllDrives=shard
    ).execute()

def get_shareable_link(service, file_id, shard):
    f = service.files().get(
        fileId=file_id, fields="webViewLink", supportsAllDrives=shard
    ).execute()
    return f.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

# ──────────────────────────────────────────
# Notion API
# ──────────────────────────────────────────

NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

def notion_req(method, endpoint, data=None):
    url = f"{NOTION_API}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            err = json.loads(err_body)
            print(f"  [Notion ERROR] {e.code}: {err.get('message', err_body)}")
        except Exception:
            print(f"  [Notion ERROR] {e.code}: {err_body}")
        raise

def find_open_task(proj_name):
    result = notion_req("POST", f"databases/{database_id}/query", {
        "filter": {
            "and": [
                {"property": "プロジェクト名", "select": {"equals": proj_name}},
                {"property": "完了", "checkbox": {"equals": False}},
            ]
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1,
    })
    results = result.get("results", [])
    return results[0]["id"] if results else None

def update_notion_url(proj_name, url):
    if not notion_token:
        print("  [Notion] NOTION_TOKEN 未設定のためスキップ")
        return False
    task_id = find_open_task(proj_name)
    if not task_id:
        print(f"  [Notion] '{proj_name}' の未完了タスクが見つかりません → スキップ")
        return False
    notion_req("PATCH", f"pages/{task_id}", {
        "properties": {"作成物URL": {"url": url}}
    })
    return task_id

def update_project_status(proj_name, url):
    status_path = os.path.join(vault_root, "Projects", proj_name, "PROJECT_STATUS.md")
    if not os.path.exists(status_path):
        proj_dirs = [d for d in glob.glob(os.path.join(vault_root, "Projects", "*"))
                     if os.path.isdir(d) and os.path.basename(d).lower() == proj_name.lower()]
        if proj_dirs:
            status_path = os.path.join(proj_dirs[0], "PROJECT_STATUS.md")
        else:
            print(f"  [Status] Projects/{proj_name}/PROJECT_STATUS.md が見つかりません → スキップ")
            return

    with open(status_path, encoding="utf-8") as f:
        content = f.read()

    today    = datetime.now(JST).strftime("%Y-%m-%d")
    filename = os.path.basename(file_path)
    ext      = os.path.splitext(filename)[1].lower()

    if ext in (".mp4", ".mov", ".avi"):
        ftype = "kling"
    elif ext in (".png", ".jpg", ".jpeg", ".webp"):
        ftype = "flux"
    elif ext in (".pdf", ".docx", ".xlsx", ".pptx"):
        ftype = "doc"
    else:
        ftype = "file"

    new_row = f"| {ftype} | {filename} | {file_path} | {url} | {today} |"

    if re.search(r'\| flux \| — \|', content):
        updated = re.sub(r'\| flux \| — \| — \| — \| — \|', new_row, content, count=1)
    elif re.search(r'\| kling \| — \|', content) and ftype == "kling":
        updated = re.sub(r'\| kling \| — \| — \| — \| — \|', new_row, content, count=1)
    else:
        updated = re.sub(
            r'(## latest_output\n.*?)((?=\n##)|\Z)',
            lambda m: m.group(1) + "\n" + new_row + "\n",
            content, flags=re.DOTALL
        )

    updated = re.sub(r'(updated_at:\s*)[\d-]+', rf'\g<1>{today}', updated)

    with open(status_path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"  [Status] PROJECT_STATUS.md 更新 → {today}")

# ──────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────

filename = os.path.basename(file_path)
size_mb  = os.path.getsize(file_path) / (1024 * 1024)

print("=" * 54)
print(f"Google Drive アップロード{'（DRY-RUN）' if DRY_RUN else ''}")
print(f"プロジェクト: {project_name}")
print(f"ファイル:     {filename} ({size_mb:.1f} MB)")
print(f"保存先:       Drive/{project_name}/")
print("=" * 54)

if DRY_RUN:
    print(f"\nDRY-RUN: 以下の処理を実行します")
    print(f"  1. フォルダ '{project_name}' を確認（なければ作成）")
    print(f"  2. '{filename}' をアップロード")
    print(f"  3. 共有リンクを取得（リンクを知っている全員が閲覧可能）")
    if not NO_NOTION:
        print(f"  4. Notionタスク '{project_name}' の作成物URLを更新")
        print(f"  4. PROJECT_STATUS.md の latest_output を更新")
    print(f"\nDRY-RUN 完了（実際のアップロードは行われていません）")
    sys.exit(0)

print("\n[1/4] Google Drive に接続中...")
service  = get_drive_service()
shard    = is_shared_drive(service, root_folder_id)
dtype    = "Shared Drive" if shard else "My Drive"
print(f"      接続成功 ({dtype})")

print(f"[2/4] フォルダ '{project_name}' を確認中...")
folder_id = find_folder(service, project_name, root_folder_id, shard)
if folder_id:
    print(f"      既存フォルダを使用: {folder_id}")
else:
    print(f"      フォルダが存在しないため作成中...")
    folder_id = create_folder(service, project_name, root_folder_id, shard)
    print(f"      フォルダ作成完了: {folder_id}")

print(f"[3/4] '{filename}' をアップロード中...")
uploaded  = upload_file(service, file_path, folder_id, shard)
file_id   = uploaded["id"]
print(f"      アップロード完了: {file_id}")
make_public(service, file_id, shard)
share_url = get_shareable_link(service, file_id, shard)
print(f"      共有URL: {share_url}")

if not NO_NOTION:
    print(f"[4/4] Notion タスク確認ボードを更新中...")
    task_id = update_notion_url(project_name, share_url)
    if task_id:
        print(f"      更新完了: task_id={task_id}")
    update_project_status(project_name, share_url)
else:
    print(f"[4/4] --no-notion: Notion・STATUS更新をスキップ")

print("\n" + "=" * 54)
print(f"完了!")
print(f"ファイル: {filename}")
print(f"URL: {share_url}")
print("=" * 54)
print(f"\nGDRIVE_URL={share_url}")

PYTHON
