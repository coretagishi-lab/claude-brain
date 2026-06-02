---
type: decision
title: Notion + AI-Brain デュアルシステム採用
date: 2026-05-21
status: adopted
---

# Decision: Notion + AI-Brain デュアルシステム

## 決定内容
- AI-Brain = Claude専用長期記憶（内部知識・workflow・prompts・mistakes・decisions）
- Notion = 人間用UI（TODO・進捗・レビュー・修正依頼・承認管理）

## Why
- Claudeが記憶・実行、人間がレビュー・承認という役割分担を明確化
- Notion APIで将来的にAI-BrainとNotion間のデータ同期が可能
- PROJECT_STATUS.mdをシンプル構造にすることでNotion API連携を容易に

## How to apply
- PROJECT_STATUS.mdはNotion APIで読み書きできるシンプル・箇条書き構造を維持
- 成果物作成後は必ず「レビュー待ち」状態をPROJECT_STATUS.mdに明記
- フィードバックはreview-notes.mdに蓄積し、パターン化する
