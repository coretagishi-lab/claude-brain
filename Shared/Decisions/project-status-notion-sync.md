---
type: decision
title: PROJECT_STATUS.md Notion同期フォーマット設計
date: 2026-05-21
status: adopted
---

# Decision: PROJECT_STATUS.md Notion同期フォーマット（v2）

## 決定内容

PROJECT_STATUS.mdを **YAMLフロントマター + Markdownボディ** の2層構造に統一する。

## フォーマット設計

### YAML層（Notionデータベースプロパティ）
スカラー値のみ。ネスト禁止。Notion APIで直接マッピング可能。

```yaml
project_name: [string]       → Notion: Title
current_status: [select]     → Notion: Select
priority: [select]           → Notion: Select
due_date: [YYYY-MM-DD | ""]  → Notion: Date
review_waiting: [bool]       → Notion: Checkbox
updated_at: [YYYY-MM-DD]     → Notion: Date
```

### Markdownボディ層（Notionページコンテンツ）
人間が読む内容。Notionではページ本文として表示。

```
## current_goal     → 現在のゴール（自由記述）
## next_action      → 次のアクション（箇条書き）
## blocker          → ブロッカー（箇条書き）
## latest_output    → 成果物テーブル（type/name/path/url/updated_at）
```

## ステータス定義

| 値 | 意味 | Notionでの用途 |
|---|---|---|
| idle | 未着手・待機中 | Notionでグレー表示 |
| active | 制作進行中 | Notionで青表示 |
| review | tagishiレビュー待ち | Notionで黄表示 |
| blocked | ブロッカーあり | Notionで赤表示 |
| completed | 完了・承認済み | Notionで緑表示 |

## latest_outputテーブル設計

| type | name | path | url | updated_at |
|---|---|---|---|---|
| flux | ファイル名 | ローカルパス | 共有URL | YYYY-MM-DD |
| kling | ファイル名 | ローカルパス | 共有URL | YYYY-MM-DD |
| capcut | ファイル名 | ローカルパス | 共有URL | YYYY-MM-DD |

## Why
- Notion APIはフラットなプロパティ構造を前提とする
- ネストしたYAMLはAPIマッピング時に変換コストが発生する
- Boolean（review_waiting）でNotionのフィルタ・ビューが活用できる
- 成果物（latest_output）はページ本文テーブルとして管理することでURLやパスを柔軟に記録できる

## Notion API同期時の実装メモ
- YAMLフロントマターをパースしてNotionページのプロパティに同期する
- Markdownボディをそのままページコンテンツとして送信する
- `review_waiting: true` のフィルタでレビュービューを作成できる
