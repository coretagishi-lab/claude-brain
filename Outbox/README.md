---
type: docs
---

# Outbox

Claudeが生成したコンテンツをNotionに送るための一時置き場。

## ファイル形式

```markdown
---
title: "エントリのタイトル"
type: note|task|decision|log
project: プロジェクト名（省略可）
status: pending
created_at: YYYY-MM-DD
sent_at: ""
notion_url: ""
---

## 本文

Markdownで自由に記述。
- リストも使える
- 見出しも使える
```

## ステータス

| status | 意味 |
|---|---|
| `pending` | 送信待ち（sync.shで自動送信） |
| `sent` | 送信済み（notion_urlにリンクあり） |
| `archived` | 送信しない・保存のみ |

## 送信先

Notion: **AI Outbox** データベース（AI-Brain OS 配下）

## 手動送信

```bash
cd ~/Desktop/ClaudeProjects/AI-Brain
python3 Shared/Workflows/outbox-to-notion.py
```
