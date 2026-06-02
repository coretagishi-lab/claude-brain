#!/usr/bin/env bash
# AI-Brain 同期マスタースクリプト
# 1. GitHub Inbox/inbox.md → ローカル AI-Brain/Inbox/inbox.md
# 2. ローカル Outbox/*.md (pending) → Notion AI Outbox DB
#
# 使い方:
#   ./sync.sh             # 両方実行
#   ./sync.sh --inbox     # Inbox同期のみ
#   ./sync.sh --outbox    # Outbox送信のみ
#   ./sync.sh --dry-run   # 実行せずに確認のみ（未実装、将来用）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ~/.zshrc の env を読み込む（launchd から起動されたとき用）
# shellcheck disable=SC1090
[[ -f "$HOME/.zshrc" ]] && source "$HOME/.zshrc" 2>/dev/null || true

RUN_INBOX=true
RUN_OUTBOX=true

for arg in "$@"; do
  case "$arg" in
    --inbox)  RUN_OUTBOX=false ;;
    --outbox) RUN_INBOX=false  ;;
  esac
done

echo "======================================"
echo " AI-Brain Sync  $(date '+%Y-%m-%d %H:%M')"
echo "======================================"

if $RUN_INBOX; then
  python3 "$SCRIPT_DIR/inbox-sync.py"
fi

echo ""

if $RUN_OUTBOX; then
  python3 "$SCRIPT_DIR/outbox-to-notion.py"
fi

echo ""
echo "────── Inbox Queue ───────────────────"
python3 "$SCRIPT_DIR/queue.py" status

echo ""
echo "======================================"
echo " Done."
echo "======================================"
