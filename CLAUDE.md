---
type: system
title: AI-Brain — マルチプロジェクトOS 運用指示書
updated: 2026-06-01
version: 4.4
---

# AI-Brain: Claude専用マルチプロジェクトOS

---

## 自律判断ルール（最優先で読む）

> **原則: 迷ったら進む。止まる理由は3種類しかない。**

### 確認なしで即実行するもの

以下はすべて黙って実行する。途中報告・事前確認は不要。

| 操作 | 判断 |
|---|---|
| Vault内ファイルの読み書き・作成・更新 | 即実行 |
| GitHub へのコミット・push | 即実行 |
| VPS への scp / SSH コマンド | 即実行 |
| systemd サービスの起動・再起動・確認 | 即実行 |
| `.env` / `/root/.profile` の再生成 | 即実行 |
| スクリプトのデプロイ・更新 | 即実行 |
| 認証エラー検出 → 自己修復フロー | 即実行（後述） |
| ConoHa APIエラー → 後回し処理 | 即実行（後述） |
| セッション開始プロトコル（4ステップ） | 即実行 |
| セッション終了プロトコル（4アクション） | 即実行 |

### 確認が必要な3種類（このフォーマットのみ使う）

```
【案件名】質問
1: OK
2: 待って
```

| 種類 | 例 |
|---|---|
| **不可逆操作** | データ削除・外部公開・課金操作・force push |
| **tagishiの価値判断が必要** | ターゲット設定・価格・コンセプト方向性 |
| **想定外の状態** | ファイルが壊れている・前提が崩れている |

**これ以外で確認するのは禁止。** 「念のため確認」「どうしますか？」は使わない。

---

## ConoHa APIエラーの扱い（後回しルール）

`ai-brain-conoha-monitor.timer` は **APIパスワードのリセットが必要**（tagishi の手動作業）。
Claude はこのエラーを見ても何もしない。

```
✅ やること: ログに「⚠️ ConoHa API: パスワード再設定待ち」と記録するだけ
❌ やらないこと: エラーを理由に作業を止める / tagishiに確認する / 修復しようとする
```

tagishi から「ConoHa直して」と明示されるまで対応しない。

---

## 認証エラーの自己修復フロー

GitHub / Discord / Anthropic / Notion の認証エラー（401・403・Bad credentials 等）が発生したとき：

### 自動修復手順（確認なしで実行）

```bash
# 1. tokens.md から .env + .profile を再生成
python3 /opt/ai-brain/Shared/Workflows/cred-loader.py --update-profile

# 2. 影響サービスを再起動
systemctl restart ai-brain-sync.service
systemctl restart ai-brain-conoha-monitor.service  # ConoHa API以外のエラーの場合のみ

# 3. Discord に修復完了通知（auth-monitor.py が自動送信）
```

### 認証情報の参照先

| 情報 | 場所 |
|---|---|
| 一元管理ファイル | `/opt/ai-brain/.credentials/tokens.md`（VPS・chmod 600） |
| systemd 用 .env | `/opt/ai-brain/.credentials/.env`（自動生成） |
| 更新スクリプト | `Shared/Workflows/cred-loader.py` |
| 自動監視 | `ai-brain-auth-monitor.timer`（5分ごと） |

### tokens.md の更新手順

```bash
# VPS で直接編集
vim /opt/ai-brain/.credentials/tokens.md
# 再適用
python3 /opt/ai-brain/Shared/Workflows/cred-loader.py --update-profile
```

**失敗した場合のみ** tagishi に報告：
```
【インフラ】tokens.mdの値が期限切れです。更新が必要です
1: 今すぐ更新する
2: 後で
```

---

## インフラ状況（2026-06-01更新）

### ConoHa VPS（本番環境）

| 項目 | 値 |
|---|---|
| IP | 133.88.117.175 |
| OS | Ubuntu 24.04.3 LTS |
| AI-Brain パス | `/opt/ai-brain/` |
| SSH | `ssh -i ~/.ssh/conoha_vps root@133.88.117.175` |
| 認証情報 | `/opt/ai-brain/.credentials/tokens.md` |

### 稼働中 systemd サービス

| サービス | 間隔 | 状態 |
|---|---|---|
| `ai-brain-sync.timer` | 30分 | ✅ 稼働中 |
| `ai-brain-memory-monitor.timer` | 60秒 | ✅ 稼働中（800MB超でDiscord通知） |
| `ai-brain-auth-monitor.timer` | 5分 | ✅ 稼働中（修復失敗時 → Notion 待機タスク登録） |
| `ai-brain-conoha-monitor.timer` | 6時間 | ⚠️ ConoHa APIパスワード再設定待ち（後回し） |

### Discord の役割（通知のみ）

Discord は **webhook による一方向通知のみ**。受信・コマンド実行は廃止済み。

| 通知種別 | 送信元スクリプト |
|---|---|
| メモリ警告 | `memory-monitor.py` |
| 認証エラー自動修復完了 | `auth-monitor.py` |
| 残高警告 | `conoha-balance-monitor.py` |
| VPS 待機タスク登録 | `vps-task-reporter.py` |

### 未完了タスク

- VPS 日本語ロケール設定（`locale-gen ja_JP.UTF-8`）
- ConoHa APIパスワード再設定 → 残高監視有効化（tagishi 手動作業）

---

## システム三層構造

```
┌─────────────────────────────────────────┐
│  Notion          人間UI層               │
│  TODO / 進捗 / レビュー / 承認 / 修正依頼 │
└──────────────┬──────────────────────────┘
               │ フィードバック / 指示
┌──────────────▼──────────────────────────┐
│  Claude          実行エンジン層          │
│  生成 / 編集 / 提案 / 記録 / 状態更新    │
└──────────────┬──────────────────────────┘
               │ 読み書き
┌──────────────▼──────────────────────────┐
│  AI-Brain（このVault）  記憶層           │
│  Style / Workflow / Prompts             │
│  Mistakes / Decisions / Status         │
└─────────────────────────────────────────┘
```

---

## 利用可能なMCP統合（確認済み: 2026-05-27）

| MCP | 主な用途 |
|---|---|
| Canva MCP | デザイン作成・編集・ページ追加・画像挿入 |
| Google Drive MCP | ファイル検索・base64ダウンロード |

### 確認済みワークフロー: Google Drive → Canva 画像配置

Googleドライブの画像は非公開のため、Canvaに直接URLを渡せない。以下の手順で対応する:

1. `search_files` でフォルダ内画像一覧取得
2. `download_file_content` でbase64取得 → Bashでローカルに保存
3. `curl`でcatbox.moeに一時アップロード → 公開URL取得
4. `upload-asset-from-url` でCanvaにアセット登録 → `asset_id` 取得
5. `start-editing-transaction` → `insert_fill` → `commit` でページに配置
6. 複数ページ追加は `copy-design` + `update_fill` + `merge-designs` の組み合わせ

### 役割分担（確定: 2026-05-27）

- **Claude Code（ターミナル）**: ファイル操作・API連携・自動処理
- **アプリ（Canvaなど）**: ビジュアル確認・最終調整

---

## セッション開始 — 事前チェック（Step 1〜4 の前に必ず実行）

### チェック① VPS 待機タスク確認

```bash
python3 Shared/Workflows/vps-task-checker.py
```

| 結果 | 対応 |
|---|---|
| `✅ VPS待機タスクなし` | 次のチェックへ進む |
| `⏳ VPS待機タスク N 件` | **その場で処理する**（セッション本来の目的より優先） |

**VPS 待機タスクの処理手順:**
```bash
# 1. 詳細を確認
python3 Shared/Workflows/vps-task-checker.py --detail

# 2. 問題を調査・修正する（Claude Code で対応）

# 3. 解決済みにする
python3 Shared/Workflows/vps-task-checker.py \
  --complete <PAGE_ID> --resolution "解決内容"
```

### チェック② Inbox キュー確認

```bash
python3 Shared/Workflows/queue.py status
```

| 結果 | 対応 |
|---|---|
| pending/wip が 0件 | 通常のセッション開始プロトコル（Step 1〜4）へ進む |
| pending が 1件以上 | 「Inboxに〇件のタスクがあります。処理しますか？」と確認する |
| wip が 1件 | 「処理中タスクあり: [内容]。続けて処理しますか？」と確認する |

### Inbox キュー処理手順

```bash
python3 Shared/Workflows/queue.py next   # 次タスクを取得
# → 処理する
python3 Shared/Workflows/queue.py done "完了メモ"  # 完了マーク
```

**ルール:** `⏳` が存在する間は `next` を実行しない。1タスク完了してから次へ。

---

## セッション開始プロトコル（4ステップ・必須）

### Step 1 — プロジェクト判定

ユーザーの発言から `Projects/` 配下の既存フォルダ名と照合して対象プロジェクトを特定する。

対象プロジェクトが判定できない場合、またはプロジェクトが未登録の場合は「どのプロジェクトですか？新規プロジェクトの場合はNew Project Start Protocolを実行します」と確認する。

### Step 2 — Shared を読む

- `Shared/Preferences/style.md` — 全体制作スタイル
- `Shared/Knowledge/mistakes.md` — 繰り返しミス（毎回確認）

### Step 3 — 対象 Project を読む

- `Projects/[name]/style.md` — プロジェクト固有スタイル
- `Projects/[name]/current-task.md` — 現在タスク状態

### Step 4 — 状態確認 + next_action 提案

- `Projects/[name]/PROJECT_STATUS.md` を読む
- `current_status` / `blockers` / `review_waiting` を確認する
- **ユーザーに next_action を提案して作業開始する**

---

## New Project Start Protocol

### トリガー

ユーザーが「新しい事業を始めたい」「新規プロジェクトを追加したい」と言った時、またはStep 1でプロジェクトが未登録と判定された時。

### 実行手順

#### STEP 1 — ヒアリング

以下を順番にユーザーに確認する:

| # | 質問 | 目的 |
|---|---|---|
| 1 | 事業名（仮でOK） | フォルダ名・slug決定 |
| 2 | 一言で言うと何をする事業か | current_goal の設定 |
| 3 | 誰の何の課題を解くか | ターゲット・訴求の起点 |
| 4 | マネタイズ仮説 | priority 判断の根拠 |
| 5 | 今の状態（アイデアのみ / 検証中 / 動いている） | current_status の初期値 |
| 6 | 最初の30日でやりたいこと | next_action の初期値 |
| 7 | 一番の不確実性 | blocker の初期値 |

#### STEP 2 — フォルダ作成

`Projects/[slug]/` を作成し以下のファイルをすべて生成する:

```
Projects/[slug]/
├── PROJECT_STATUS.md   ← ヒアリング内容をフォーマットに流し込む
├── current-task.md     ← 最初の30日タスク・checkpoint設定
├── review-notes.md     ← 空ファイル（フロントマターのみ）
├── style.md            ← 空ファイル（制作開始時に記入）
├── Knowledge/
├── Workflows/
└── Prompts/
```

#### STEP 3 — ルート PROJECT_STATUS.md 更新

`PROJECT_STATUS.md`（Vault root）のProject Dashboardに新プロジェクトを1行追加する。

#### STEP 4 — 完了サマリー出力

登録内容をユーザーに提示し、「このまま作業を開始しますか？」と確認して作業を開始する。

---

## セッション終了プロトコル（必須）

詳細手順: `Shared/Workflows/session-end-protocol.md`

### 最小実行セット（4アクション）

1. **current-task.md** の `checkpoint` を中断地点に更新し、チェックリストを現状に合わせる
2. **PROJECT_STATUS.md** の `next_action` / `updated_at` を更新する
3. **Log** を `Logs/YYYY/MM/YYYY-MM-DD-session-[番号].md` に書く（意思決定のみ・全文禁止）
4. **Session End Summary** をユーザーへ出力する

### 保存ルール早見表

| ファイル | 毎回 | 条件付き |
|---|---|---|
| `current-task.md` の checkpoint | ✅ | — |
| `PROJECT_STATUS.md` の next_action / updated_at | ✅ | — |
| `PROJECT_STATUS.md` の current_goal | — | ゴール変更時のみ |
| `Logs/` への記録 | — | 意思決定・ブロッカー・ステップ進行時 |

### next_action の書き方

- `○ タスクXをtagishiに確認してSTEP 2へ進む`
- `× 確認する`（動詞＋対象＋目的の形にする）

### blocker の書き方

- `○ tagishiに「ターゲットは20代女性か30代男性か」を確認する必要がある`
- `× ターゲット未定`（問いの形にする）

---

## フィードバック受信プロトコル

フィードバックを受けたら **必ず `review-notes.md` に記録してから対応**する。

| フィードバック | 対応アクション |
|---|---|
| 「修正」 | review-notes.md に記録 → 該当箇所を特定して対応 |
| 「もっとリアル」 | style.md の実写感キーワードを強化 → 再生成 |
| 「感情弱い」 | 転換点の演出強化 → テキスト・BGM・動き見直し |
| 「AI感がある」 | film grain / noise 追加 → 素材再生成 |
| 「訴求が弱い」 | コピー見直し → narration/を更新 |

同じフィードバックが **2回以上** 発生したら `Shared/Knowledge/mistakes.md` に記録する。

---

## Inbox プロトコル

### 運用ルール

- tagishiは**雑に投げるだけでOK**（断片・メモ・日本語OK）
- Claudeが内容を判定して適切なInboxファイルへ保存する
- セッション中に出たアイデア・気づきは**必ずInboxへ記録してから作業を続ける**
- Inboxは溜めるだけでなく、セッション末に整理してProjectsへ昇格判断を行う

### 自動分類ルール

発言内容から以下のキーワードを検出して振り分ける:

| キーワード | 振り分け先 |
|---|---|
| 漫画 / コマ / セリフ / ストーリー / ナレーション | `Inbox/manga-ads.md` |
| AI美女 / 女の子 / キャラ / Flux / Kling / モーション | `Inbox/ai-girls.md` |
| 採用 / LP / ランディング / ペルソナ / 求人 | `Inbox/recruitment.md` |
| 感情 / 共感 / 憧れ / 不安 / 解放 / cinematic | `Inbox/emotional-triggers.md` |
| 構図 / カメラ / 照明 / 動画 / 映像 / カラー | `Inbox/visual-ideas.md` |
| フック / CTA / コピー / キャッチ / ボタン | `Inbox/ad-hooks.md` |
| 再利用 / 横展開 / 共通 / どのProjectでも使える | `Inbox/reuse-candidates.md` |
| 判定不能・複数該当 | `Inbox/raw-ideas.md` |

### Inbox → Project 昇格フロー

```
[Inbox] → 判断 → [Projects/]  または  [Shared/]
```

| 条件 | 昇格先 |
|---|---|
| 特定プロジェクト向けで品質確認済み | `Projects/[name]/Prompts/` or `Workflows/` |
| 2プロジェクト以上で使える汎用素材 | `Shared/Prompts/` or `Workflows/` |
| AI生成ノウハウ・技術知識 | `Shared/Knowledge/` |
| 採用せず・参考保存 | Inboxのまま `status: archived` |

昇格したら元ファイルの `status` を `adopted` に更新し、`moved_to` に昇格先パスを記録する。

### reuse-candidates 判定基準

- **2プロジェクト以上で有効** → `Inbox/reuse-candidates.md` に追加 → `Shared/` 昇格検討
- **特定プロジェクトのみ有効** → 各プロジェクトの `Knowledge/` へ直接昇格
- **★★★（品質高・汎用性あり）** → 即昇格

---

## PROJECT_STATUS.md 標準フォーマット（Notion同期対応・v2）

### 設計思想
- **YAMLフロントマター** = Notion データベースプロパティ（フィルタ・一覧・検索対象）
- **Markdownボディ** = Notion ページコンテンツ（閲覧・編集）
- スカラー値のみYAMLに置く（ネスト禁止 → Notion API互換）

```markdown
---
project_name: [name]
current_status: [idle|active|review|blocked|completed]
priority: [high|medium|low]
due_date: ""
review_waiting: false
updated_at: YYYY-MM-DD
---

## current_goal
-

## next_action
-

## blocker
- なし

## latest_output

| type | name | path | url | updated_at |
|---|---|---|---|---|
| flux | — | — | — | — |
| kling | — | — | — | — |
| capcut | — | — | — | — |
```

### ステータス定義

| 値 | 意味 |
|---|---|
| `idle` | 未着手・待機中 |
| `active` | 制作進行中 |
| `review` | tagishiレビュー待ち |
| `blocked` | ブロッカーあり・進行停止 |
| `completed` | 完了・承認済み |

### Notion同期フィールドマッピング

| YAMLキー | Notionプロパティ型 | 用途 |
|---|---|---|
| `project_name` | Title | プロジェクト名 |
| `current_status` | Select | ステータス管理・フィルタ |
| `priority` | Select | 優先度管理 |
| `due_date` | Date | 締め切り |
| `review_waiting` | Checkbox | レビュー待ちフィルタ |
| `updated_at` | Date | 最終更新日 |

---

## Vault構造（v4.2）

```
AI-Brain/
├── CLAUDE.md                     ← このファイル（毎回ここから始める）
├── PROJECT_STATUS.md             ← 全体ダッシュボード
├── TODO.md
├── Shared/                       ← 全プロジェクト共通
│   ├── Preferences/style.md      ← tagishiの制作スタイル
│   ├── Knowledge/mistakes.md     ← 繰り返しミス（2回以上のみ記録）
│   ├── Workflows/                ← 共通フロー・再利用テンプレート
│   ├── Prompts/                  ← 共通プロンプト
│   └── Decisions/                ← 意思決定記録
├── Inbox/                        ← 思いつき即保存・Claudeが整理・Projectsへ昇格
├── Projects/                     ← New Project Start Protocol で追加・事業別完全分離
└── Logs/
```

各 Project 配下の構成:
```
[name]/
├── PROJECT_STATUS.md   ← 6フィールド必須・Notion API連携前提
├── current-task.md     ← 現在の作業タスク詳細
├── review-notes.md     ← フィードバック記録・パターン蓄積
├── style.md            ← プロジェクト固有スタイル
├── Knowledge/          ← プロジェクト固有の知識・解決済み問題
├── Workflows/          ← 再利用可能な制作フロー
└── Prompts/            ← プロジェクト固有プロンプト
```

---

## ファイル規則

- 全Markdownに YAML frontmatter を付与
- 日付: `YYYY-MM-DD`
- `PROJECT_STATUS.md` は箇条書き中心・シンプル構造（Notion API前提）
- Workflowは再利用可能なテンプレート形式で記述する
