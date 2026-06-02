---
type: reference
title: Mac ~/.zshrc 設定スナップショット（シークレット値マスク済み）
updated: 2026-06-02 16:45
source: ~/.zshrc
---

# Mac 環境変数設定（~/.zshrc）

> 自動生成: launchd com.ai-brain.mac-config-sync が毎日午前3時に更新
> シークレット値（KEY/TOKEN/PASSWORD等）はマスク済み

```zsh
# Notion API Token
export NOTION_TOKEN="****"

# GitHub Personal Access Token（claude-brain repo 用）
export GITHUB_TOKEN="****"

# claude-brain: inbox監視スクリプト（Terminal起動時に自動開始）
CLAUDE_BRAIN_DIR="$HOME/Desktop/ClaudeProjects/claude-brain"
CLAUDE_BRAIN_LOG="$CLAUDE_BRAIN_DIR/logs/watch.log"
if [ -f "$CLAUDE_BRAIN_DIR/watch_inbox.sh" ] && ! pgrep -f "watch_inbox.sh" > /dev/null 2>&1; then
  mkdir -p "$CLAUDE_BRAIN_DIR/logs"
  nohup bash "$CLAUDE_BRAIN_DIR/watch_inbox.sh" >> "$CLAUDE_BRAIN_LOG" 2>&1 &
  echo "[claude-brain] inbox監視開始 (PID: $!)"
fi
export DISCORD_WEBHOOK_URL="****"

# ConoHa Balance Monitor
# 管理画面 → 右上アカウント名 → API情報 で確認
export CONOHA_USERNAME="gncu74102211"
export CONOHA_PASSWORD="****"
export CONOHA_TENANT_ID="b35e91ae16dd49bd90b37cc8231b8992"
export CONOHA_REGION="tyo2"
# export CONOHA_BALANCE_THRESHOLD="500" # デフォルトは500円

# Anthropic API Key（generate-content.py 等で使用）
export ANTHROPIC_API_KEY="****"
```
