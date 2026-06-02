---
type: workflow
title: セッション開始プロトコル
updated: 2026-05-21
version: 1.0
trigger: 毎セッション開始時に必ず実行
---

# セッション開始プロトコル

> Claude が毎回「現在地を理解した状態」で作業を開始するための手順書。
> 環境: VSCode + Claude Code ↔ AI-Brain（Obsidian Vault）記憶接続フェーズ

---

## 実行手順（順番厳守・全5ステップ）

---

### STEP 0 — 自己確認（30秒）

以下を声に出して（コメントとして）確認する:

```
- 今日の日付: YYYY-MM-DD
- セッション番号: PROJECT_STATUS.md の session + 1
- 作業環境: VSCode + Claude Code / AI-Brain Vault
```

---

### STEP 1 — 全体ダッシュボード読み込み（必須）

読むファイル:
1. `CLAUDE.md` — システムルール・プロトコル
2. `PROJECT_STATUS.md` — 全プロジェクトの現在地

確認ポイント:
- `current_status: active` のプロジェクトを特定
- `review_waiting: true` のプロジェクトを特定（最優先で対応）
- `priority: high` のプロジェクトを確認

---

### STEP 2 — 対象プロジェクト特定

**ユーザーが明示した場合** → そのプロジェクトへ
**ユーザーが明示しない場合** → 以下の優先順位で判断:

```
1. review_waiting: true  → レビュー対応が最優先
2. current_status: active かつ priority: high
3. current_status: active（複数あれば最終更新が古い方）
4. 判断不能 → ユーザーに「どのプロジェクトで作業しますか？」と確認
```

---

### STEP 3 — プロジェクト状態の深読み（必須）

対象プロジェクトの以下3ファイルを読む:

| ファイル | 確認ポイント |
|---|---|
| `Projects/[name]/PROJECT_STATUS.md` | `next_action` / `blocker` / `review_waiting` |
| `Projects/[name]/current-task.md` | 現在ステップ / 残チェックリスト / 未決定事項 |
| `Projects/[name]/style.md` | 制作スタイル・禁止事項（毎回リフレッシュ） |

加えて:
- `Shared/Preferences/style.md` — 全体スタイル確認
- `Shared/Knowledge/mistakes.md` — 前回ミスの確認（必須）

---

### STEP 4 — Inbox スキャン

`Inbox/raw-ideas.md` の未処理アイデアを確認する:
- 対象プロジェクトに関連するものがあれば、このセッションで処理予定として把握
- `status: inbox` のものが5件以上あれば整理を提案する

---

### STEP 5 — 現在地サマリーをユーザーへ提示

以下のフォーマットで出力する:

```
## セッション開始 — [日付] #[セッション番号]

**対象プロジェクト:** [name]
**現在の状態:** [current_status]
**現在のゴール:** [current_goal]
**ブロッカー:** [blocker または「なし」]
**レビュー待ち:** [review_waiting または「なし」]

**今日の next_action:**
- [next_actionの内容]

**Inbox 未処理:** [件数]件

---
作業を開始します。まず[具体的な最初のアクション]から始めます。
```

---

## セッション終了時（参照: CLAUDE.md のセッション終了プロトコル）

1. `Projects/[name]/PROJECT_STATUS.md` を6フィールドで更新
2. `Projects/[name]/current-task.md` のチェックリストを更新
3. `Inbox/` の処理済みアイデアの `status` を更新
4. `PROJECT_STATUS.md`（全体）の Session History に追記
5. `Logs/YYYY/MM/YYYY-MM-DD-session-[番号].md` を作成

---

## トラブルシューティング

| 状況 | 対応 |
|---|---|
| PROJECT_STATUS.md が古い（7日以上更新なし） | ユーザーに確認してから作業開始 |
| current-task.md の `status` が `active` のまま長期停止 | blocker を確認してユーザーに報告 |
| 複数プロジェクトが `review_waiting: true` | 全件をユーザーに提示して優先度を確認 |
| Inbox に未処理アイデアが10件以上 | セッション冒頭で整理タイムを提案する |
