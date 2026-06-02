#!/bin/zsh
# Macのyoutube-cookies.txtを週1回VPSに転送してBot再起動する
#
# Mac側クッキーファイルのパス:
#   ~/.config/ai-brain/youtube-cookies.txt
#
# クッキーの更新方法:
#   1. ChromeでYouTubeにログイン
#   2. 拡張機能「Get cookies.txt LOCALLY」でyoutube.comのクッキーをエクスポート
#   3. ~/.config/ai-brain/youtube-cookies.txt に保存
#   4. launchd が毎週月曜 3:00 に自動転送（または本スクリプトを手動実行）

COOKIES_SRC="$HOME/.config/ai-brain/youtube-cookies.txt"
COOKIES_DST="root@133.88.117.175:/opt/ai-brain/.credentials/youtube-cookies.txt"
SSH_KEY="$HOME/.ssh/conoha_vps"
LOG="/tmp/ai-brain-sync-youtube-cookies.log"
NOW=$(date '+%Y-%m-%d %H:%M')

echo "[$NOW] sync-youtube-cookies 開始" >> "$LOG"

# ── クッキーファイルの存在確認 ─────────────────────────────────────────────
if [[ ! -f "$COOKIES_SRC" ]]; then
  MSG="[$NOW] ❌ クッキーファイルが見つかりません: $COOKIES_SRC"
  echo "$MSG" >> "$LOG"
  echo "$MSG"
  echo ""
  echo "更新手順:"
  echo "  1. ChromeでYouTubeにログイン"
  echo "  2. 拡張機能「Get cookies.txt LOCALLY」でエクスポート"
  echo "  3. 保存先: $COOKIES_SRC"
  exit 1
fi

# ── 鮮度チェック: 7日以上古ければ警告 ──────────────────────────────────────
MTIME=$(stat -f "%m" "$COOKIES_SRC" 2>/dev/null || stat -c "%Y" "$COOKIES_SRC" 2>/dev/null)
NOW_EPOCH=$(date +%s)
AGE_DAYS=$(( (NOW_EPOCH - MTIME) / 86400 ))

if (( AGE_DAYS > 7 )); then
  echo "[$NOW] ⚠️ クッキーファイルが ${AGE_DAYS}日 更新されていません（期限切れの可能性）" >> "$LOG"
fi

# ── VPSに転送 ──────────────────────────────────────────────────────────────
echo "[$NOW] VPSに転送中: $COOKIES_SRC → $COOKIES_DST" >> "$LOG"

scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$COOKIES_SRC" "$COOKIES_DST" >> "$LOG" 2>&1
SCP_STATUS=$?

if [[ $SCP_STATUS -ne 0 ]]; then
  echo "[$NOW] ❌ scp失敗 (exit $SCP_STATUS)" >> "$LOG"
  exit $SCP_STATUS
fi

# ── VPS側でパーミッション設定 ────────────────────────────────────────────────
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no root@133.88.117.175 \
  "chmod 600 /opt/ai-brain/.credentials/youtube-cookies.txt" >> "$LOG" 2>&1

# ── discord-inbox-bot を再起動（クッキー読み込みのため） ─────────────────────
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no root@133.88.117.175 \
  "systemctl restart ai-brain-discord-inbox-bot.service && \
   sleep 3 && \
   systemctl is-active ai-brain-discord-inbox-bot.service" >> "$LOG" 2>&1
RESTART_STATUS=$?

if [[ $RESTART_STATUS -eq 0 ]]; then
  echo "[$NOW] ✅ 転送完了・Bot再起動済み" >> "$LOG"
  echo "✅ youtube-cookies.txt を転送しました（${AGE_DAYS}日前のファイル）"
else
  echo "[$NOW] ⚠️ 転送完了・Bot再起動失敗" >> "$LOG"
  echo "⚠️ 転送は完了しましたがBot再起動に失敗しました"
fi
