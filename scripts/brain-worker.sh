#!/bin/bash
# brain-worker.sh — バックグラウンド監視ループ起動スクリプト
#
# 使い方:
#   bash scripts/brain-worker.sh          # 起動
#   bash scripts/brain-worker.sh stop     # 停止
#   bash scripts/brain-worker.sh attach   # ログ確認
#   bash scripts/brain-worker.sh status   # 状態確認

SESSION="brain-worker"
VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKER_PY="$VAULT_DIR/scripts/worker.py"

case "${1:-start}" in

  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "✅ 停止" || echo "⚠️  未起動"
    exit 0 ;;

  attach)
    tmux attach -t "$SESSION"
    exit 0 ;;

  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "✅ 稼働中"
      tmux list-windows -t "$SESSION"
    else
      echo "⚪ 停止中"
    fi
    exit 0 ;;

esac

# ── start ─────────────────────────────────────────────────────────────────

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "⚠️  既に起動中 → bash scripts/brain-worker.sh stop で停止してから再起動"
  exit 0
fi

if [ -z "$NOTION_TOKEN" ] || [ -z "$NOTION_CONTENT_DB_ID" ]; then
  echo "❌ NOTION_TOKEN / NOTION_CONTENT_DB_ID が未設定"
  exit 1
fi

tmux new-session -d -s "$SESSION" -n "monitor" -x 200 -y 50
tmux send-keys -t "$SESSION:monitor" "cd '$VAULT_DIR' && python3 '$WORKER_PY'" Enter

echo "✅ brain-worker 起動"
echo "   ログ確認: bash scripts/brain-worker.sh attach"
echo "   停止:     bash scripts/brain-worker.sh stop"
