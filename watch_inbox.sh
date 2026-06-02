#!/bin/bash
# watch_inbox.sh — inbox.mdの変更を監視してClaude Codeに実行させる

REPO_DIR="$HOME/Desktop/ClaudeProjects/claude-brain"
INBOX="$REPO_DIR/inbox.md"
OUTBOX="$REPO_DIR/outbox.md"
APPROVAL="$REPO_DIR/approval.md"
WEBHOOK_FILE="$REPO_DIR/.discord_webhook"
LAST_HASH=""
LAST_OUTBOX_HASH=""
LAST_APPROVAL_HASH=""

# GitHub認証（キーチェーンにない環境でも動くようにURLにトークンを埋め込む）
GITHUB_TOKEN="${GITHUB_TOKEN:-$(git config --global github.token 2>/dev/null)}"
if [ -n "$GITHUB_TOKEN" ]; then
  git -C "$REPO_DIR" remote set-url origin \
    "https://${GITHUB_TOKEN}@github.com/coretagishi-lab/claude-brain.git" 2>/dev/null
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Discord通知（approval.md・outbox.md更新時に送信）
discord_notify() {
  local message="$1"
  if [ -f "$WEBHOOK_FILE" ]; then
    local webhook_url
    webhook_url=$(cat "$WEBHOOK_FILE")
    curl -s -H "Content-Type: application/json" \
      -d "{\"content\": \"$message\"}" \
      "$webhook_url" > /dev/null 2>&1
    log "Discord通知送信: $message"
  else
    log "警告: .discord_webhookが未設定。通知をスキップ"
  fi
}

# approval.md・outbox.mdの変更を検知して通知
check_file_updates() {
  # approval.md 監視
  local approval_hash
  approval_hash=$(md5 -q "$APPROVAL" 2>/dev/null)
  if [ "$approval_hash" != "$LAST_APPROVAL_HASH" ] && [ -n "$LAST_APPROVAL_HASH" ]; then
    discord_notify "⚠️ 【承認が必要】approval.mdを確認してください。\\nhttps://github.com/coretagishi-lab/claude-brain/blob/main/approval.md"
  fi
  LAST_APPROVAL_HASH="$approval_hash"

  # outbox.md 監視
  local outbox_hash
  outbox_hash=$(md5 -q "$OUTBOX" 2>/dev/null)
  if [ "$outbox_hash" != "$LAST_OUTBOX_HASH" ] && [ -n "$LAST_OUTBOX_HASH" ]; then
    discord_notify "📋 【報告あり】outbox.mdに新しい報告があります。\\nhttps://github.com/coretagishi-lab/claude-brain/blob/main/outbox.md"
  fi
  LAST_OUTBOX_HASH="$outbox_hash"
}

process_inbox() {
  log "inbox.mdに変更を検知。Claude Codeで実行します..."

  cd "$REPO_DIR" || exit 1

  # 最新をpull
  git pull origin main --quiet 2>&1 | log "git pull: $(cat)"

  # Claude Codeに実行させる
  claude --dangerously-skip-permissions --print "
あなたは統括AIです。CLAUDE.mdのルールに従って動いてください。

inbox.mdを読んで、未実行の指示（[完了]マークがないもの）を実行してください。
実行したらoutbox.mdに結果を報告し、inbox.mdの指示に [完了] マークをつけてください。
すべての変更はgit commitしてpushしてください。

作業ディレクトリ: $REPO_DIR
" < /dev/null 2>&1 | tee -a "$OUTBOX"

  check_file_updates
}

# 初期ハッシュを設定（起動直後の誤通知を防ぐ）
LAST_APPROVAL_HASH=$(md5 -q "$APPROVAL" 2>/dev/null)
LAST_OUTBOX_HASH=$(md5 -q "$OUTBOX" 2>/dev/null)
LAST_HASH=$(md5 -q "$INBOX" 2>/dev/null)

log "=== inbox監視スクリプト起動 ==="
log "監視対象: $INBOX"
log "リポジトリ: $REPO_DIR"
if [ -f "$WEBHOOK_FILE" ]; then
  log "Discord通知: 有効"
else
  log "Discord通知: 未設定（.discord_webhookファイルを作成してください）"
fi

# fswatch（macOS）でinbox.md・outbox.md・approval.mdを同時監視
if command -v fswatch &> /dev/null; then
  log "fswatch モードで監視開始"
  fswatch -o "$INBOX" "$OUTBOX" "$APPROVAL" | while read event; do
    # inbox.md の変更チェック
    CURRENT_HASH=$(md5 -q "$INBOX")
    if [ "$CURRENT_HASH" != "$LAST_HASH" ]; then
      LAST_HASH="$CURRENT_HASH"
      process_inbox
    else
      # inbox以外（outbox/approval）の変更をチェック
      check_file_updates
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
      else
        check_file_updates
      fi
    fi
    sleep 60
  done
fi
