---
type: workflows
title: ワークフロー一覧
updated: 2026-05-22
---

# Workflows

繰り返す制作フロー・手順書を蓄積するフォルダ。

## フォーマット

各ワークフローは独立ファイルで管理:
- `workflow_[名前].md`

## 登録済みワークフロー

| ファイル | 内容 |
|---|---|
| `session-start-protocol.md` | 毎セッション開始時の5ステップ手順（現在地把握→作業開始） |
| `session-end-protocol.md` | 毎セッション終了時の4ステップ手順（現在地保存→Summary出力） |
| `log-template.md` | Logファイル標準テンプレート（意思決定履歴フォーマット） |
| `notion-sync.sh` | AI-Brain → Notion Projects Dashboard 同期スクリプト |
| `gdrive-upload.sh` | ファイルをGoogle Driveにアップロード → 共有URL取得 → Notion作成物URL自動記入 |

---

## notion-sync.sh — 使い方

### 概要

`Projects/` 配下の `PROJECT_STATUS.md` を読み込み、Notion の **タスク確認ボード** に同期する。
デフォルトは `review_waiting: true` のプロジェクトのみ同期。`--all` で全プロジェクトを強制同期。

### 同期フィールドマッピング

| AI-Brain (PROJECT_STATUS.md) | Notion プロパティ | 型 |
|---|---|---|
| `## next_action` の最初の行 | 確認してほしい内容 | Title |
| `project_name` | プロジェクト名 | Select |
| `updated_at` | 提出日時 | Date |
| 常に `false`（tagishiが操作） | 完了 | Checkbox |
| 常に `0`（tagishiが操作） | 確認回数 | Number |
| `## current_goal` の最初の行 | 内容要約 | Text |
| `## latest_output` の最初のURL | 作成物URL | URL |

### 実行コマンド

```bash
export NOTION_TOKEN="ntn_xxxxxxxxxxxxxxxxxxxx"

# review_waiting: true のプロジェクトのみ同期（通常）
./Shared/Workflows/notion-sync.sh

# 全プロジェクトを強制同期
./Shared/Workflows/notion-sync.sh --all

# 書き込まずに確認（推奨: 初回はこちらから）
./Shared/Workflows/notion-sync.sh --dry-run --verbose

# 全オプション組み合わせ可能
./Shared/Workflows/notion-sync.sh --all --dry-run --verbose
```

### 更新ルール

| 状況 | 動作 |
|---|---|
| 同プロジェクトの未完了タスクが存在する | UPDATE（完了・確認回数はtagishi管理なので上書きしない） |
| 未完了タスクが存在しない | CREATE（新規エントリ追加） |
| review_waiting: false かつ --all なし | SKIP |

### 接続先

- **データベース名:** タスク確認ボード
- **データベースID:** `3671cad4-aa98-813b-85b2-ed9e3127b913`
- **NotionページURL:** `https://notion.so/3671cad4aa98813b85b2ed9e3127b913`
- **Notion API version:** 2022-06-28

### ビュー設定（Notion UI で手動設定が必要）

Notion API の制限により、ビューとデフォルトソートは UI での設定が必要:

1. **「未完了」ビュー（デフォルト）**
   - フィルタ: `完了 = チェックなし`
   - ソート: `作成日時 → 昇順（古い順）`

2. **「完了済み」ビュー**
   - フィルタ: `完了 = チェックあり`
   - ソート: `作成日時 → 昇順`

### セットアップ

```bash
# .zshrc に追記しておくと毎回不要
echo 'export NOTION_TOKEN="ntn_xxxx"' >> ~/.zshrc
source ~/.zshrc
```

### セキュリティ注意事項

- `NOTION_TOKEN` は **絶対にスクリプトにハードコードしない**
- トークンが漏洩した場合は Notion Integration 設定画面で即座に再発行する

---

## gdrive-upload.sh — 使い方

### 概要

指定ファイルを Google Drive の `[プロジェクト名]` サブフォルダへアップロードし、
共有URLを取得して Notion タスク確認ボードの **作成物URL** に自動記入する。
サービスアカウント認証を使用するため、ブラウザ操作不要。

### ディレクトリ構成（Drive側）

```
AI-Brain（ルートフォルダ: 1MznW63WBQuKIDbKE1q9KhoLvWybKQGaM）
├── manga-ads/
│   └── reel_001.mp4
├── ai-girls/
│   └── flux_output.png
└── recruitment/
    └── lp_draft_v2.pdf
```

### 実行コマンド

```bash
# 基本（アップロード + Notion更新）
./Shared/Workflows/gdrive-upload.sh [プロジェクト名] [ファイルパス]

# Notion更新なし（Driveにアップロードのみ）
./Shared/Workflows/gdrive-upload.sh [プロジェクト名] [ファイルパス] --no-notion

# 書き込まずに確認（推奨: 初回はこちら）
./Shared/Workflows/gdrive-upload.sh [プロジェクト名] [ファイルパス] --dry-run

# 実例
./Shared/Workflows/gdrive-upload.sh manga-ads output/reel_001.mp4
./Shared/Workflows/gdrive-upload.sh ai-girls flux_20260522.png --no-notion
```

### Notion更新ルール

| 状況 | 動作 |
|---|---|
| 未完了タスクが存在する | `作成物URL` を新URLで上書き |
| 未完了タスクが存在しない | スキップ（ログに表示） |
| `NOTION_TOKEN` 未設定 | スキップ（ログに表示） |

### 自動更新対象

| 更新先 | 更新内容 |
|---|---|
| Notion タスク確認ボード | `作成物URL` フィールド |
| `Projects/[name]/PROJECT_STATUS.md` | `latest_output` テーブル + `updated_at` |

### セットアップ

```bash
# Notion更新を使う場合は NOTION_TOKEN を設定
echo 'export NOTION_TOKEN="ntn_xxxx"' >> ~/.zshrc
source ~/.zshrc

# 初回実行時、不足パッケージを自動インストール
# google-api-python-client, google-auth（pip3 で自動実行）
```

### 必要ファイル

| パス | 内容 |
|---|---|
| `.credentials/gdrive-oauth-client.json` | OAuth2クライアントID（初回セットアップで取得） |
| `.credentials/gdrive-oauth-token.json` | OAuth2アクセストークン（初回認証後に自動生成） |

### 初回セットアップ

```bash
# 1. 手順を確認
./Shared/Workflows/gdrive-upload.sh --setup

# 2. Google Cloud Console で OAuth2 クライアントIDを作成・ダウンロード
#    → .credentials/gdrive-oauth-client.json に配置

# 3. ブラウザ認証（1回のみ）
./Shared/Workflows/gdrive-upload.sh --auth
```

### セキュリティ注意事項

- `.credentials/` は `.gitignore` に必ず追加する
- `gdrive-oauth-client.json` が漏洩した場合は Google Cloud Console で即座に無効化する
- アップロードされたファイルは「リンクを知っている全員が閲覧可能」に設定される
