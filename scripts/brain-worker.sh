#!/bin/bash
# brain-worker.sh — バックグラウンド自動処理 tmux セッション起動スクリプト
#
# 使い方:
#   bash scripts/brain-worker.sh          # 起動
#   bash scripts/brain-worker.sh stop     # 停止
#   bash scripts/brain-worker.sh attach   # アタッチ
#   bash scripts/brain-worker.sh status   # 状態確認

SESSION="brain-worker"
VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKER_PY="$VAULT_DIR/scripts/worker.py"

case "${1:-start}" in

  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "✅ brain-worker 停止" || echo "⚠️  セッション未起動"
    exit 0
    ;;

  attach)
    tmux attach -t "$SESSION"
    exit 0
    ;;

  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "✅ brain-worker 稼働中"
      tmux list-windows -t "$SESSION"
    else
      echo "⚪ brain-worker 停止中"
    fi
    exit 0
    ;;

esac

# ── start ─────────────────────────────────────────────────────────────────

# 既存セッションがあればそのまま使う
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "⚠️  brain-worker は既に起動中です"
  echo "   再起動: bash scripts/brain-worker.sh stop && bash scripts/brain-worker.sh"
  echo "   アタッチ: bash scripts/brain-worker.sh attach"
  exit 0
fi

# 環境変数チェック
if [ -z "$NOTION_TOKEN" ] || [ -z "$NOTION_CONTENT_DB_ID" ]; then
  echo "❌ 環境変数未設定: NOTION_TOKEN, NOTION_CONTENT_DB_ID が必要です"
  echo "   ~/.profile または /opt/ai-brain/.credentials/.env を確認してください"
  exit 1
fi

# tmux セッション作成（monitor ウィンドウ）
tmux new-session -d -s "$SESSION" -n "monitor" -x 220 -y 50

# monitor ウィンドウ: Python 監視ループ
tmux send-keys -t "$SESSION:monitor" \
  "cd '$VAULT_DIR' && python3 '$WORKER_PY'" \
  Enter

# claude ウィンドウ: インタラクティブ claude セッション（Readツール事前許可）
tmux new-window -t "$SESSION" -n "claude"
tmux send-keys -t "$SESSION:claude" \
  "cd '$VAULT_DIR' && claude --allowedTools Read" \
  Enter

echo "✅ brain-worker 起動完了"
echo ""
echo "  全体確認:   tmux attach -t $SESSION"
echo "  監視ログ:   tmux attach -t ${SESSION}:monitor"
echo "  claudeセッション: tmux attach -t ${SESSION}:claude"
echo "  停止:       bash scripts/brain-worker.sh stop"
