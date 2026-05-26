#!/bin/bash
# watch_inbox.sh — inbox.mdの変更を監視してClaude Codeに実行させる

REPO_DIR="$HOME/Desktop/ClaudeProjects/claude-brain"
INBOX="$REPO_DIR/inbox.md"
OUTBOX="$REPO_DIR/outbox.md"
APPROVAL="$REPO_DIR/approval.md"
LAST_HASH=""

# ntfy.sh通知トピック（approval.md更新時に使用）
# スマホでntfyアプリを入れてこのトピックを購読する
NTFY_TOPIC="claude-brain-$(cat $REPO_DIR/.ntfy_topic 2>/dev/null || echo 'setup-required')"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

notify_approval() {
  local message="$1"
  if [ -f "$REPO_DIR/.ntfy_topic" ]; then
    curl -s -d "$message" "ntfy.sh/$NTFY_TOPIC" > /dev/null 2>&1
    log "通知送信: $message"
  fi
}

check_approval_update() {
  local current_hash=$(md5 -q "$APPROVAL" 2>/dev/null)
  local stored_hash_file="$REPO_DIR/.approval_hash"
  local stored_hash=$(cat "$stored_hash_file" 2>/dev/null)

  if [ "$current_hash" != "$stored_hash" ]; then
    echo "$current_hash" > "$stored_hash_file"
    if [ -n "$stored_hash" ]; then
      notify_approval "承認が必要な案件があります。approval.mdを確認してください。"
    fi
  fi
}

process_inbox() {
  log "inbox.mdに変更を検知。Claude Codeで実行します..."

  cd "$REPO_DIR" || exit 1

  # 最新をpull
  git pull origin main --quiet 2>&1 | log "git pull: $(cat)"

  # Claude Codeに実行させる（dangerously-skip-permissions + stdin /dev/nullで自律実行）
  claude --dangerously-skip-permissions --print "
あなたは統括AIです。CLAUDE.mdのルールに従って動いてください。

inbox.mdを読んで、未実行の指示（[完了]マークがないもの）を実行してください。
実行したらoutbox.mdに結果を報告し、inbox.mdの指示に [完了] マークをつけてください。
すべての変更はgit commitしてpushしてください。

作業ディレクトリ: $REPO_DIR
" < /dev/null 2>&1 | tee -a "$OUTBOX"

  check_approval_update
}

log "=== inbox監視スクリプト起動 ==="
log "監視対象: $INBOX"
log "リポジトリ: $REPO_DIR"

# fswatch（macOS）でinbox.mdを監視
if command -v fswatch &> /dev/null; then
  log "fswatch モードで監視開始"
  fswatch -o "$INBOX" | while read event; do
    CURRENT_HASH=$(md5 -q "$INBOX")
    if [ "$CURRENT_HASH" != "$LAST_HASH" ]; then
      LAST_HASH="$CURRENT_HASH"
      process_inbox
    fi
  done
else
  # フォールバック: 60秒ごとにGitHubをポーリング
  log "fswatch未インストール。ポーリングモードで監視開始（60秒間隔）"
  while true; do
    cd "$REPO_DIR" && git fetch origin --quiet 2>/dev/null
    REMOTE_HASH=$(git rev-parse origin/main 2>/dev/null)
    LOCAL_HASH=$(git rev-parse HEAD 2>/dev/null)

    if [ "$REMOTE_HASH" != "$LOCAL_HASH" ]; then
      git pull origin main --quiet 2>/dev/null
      CURRENT_HASH=$(md5 -q "$INBOX")
      if [ "$CURRENT_HASH" != "$LAST_HASH" ]; then
        LAST_HASH="$CURRENT_HASH"
        process_inbox
      fi
    fi

    check_approval_update
    sleep 60
  done
fi
