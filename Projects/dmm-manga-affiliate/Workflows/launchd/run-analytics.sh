#!/bin/zsh
source ~/.zshrc 2>/dev/null
source ~/.zprofile 2>/dev/null
SCRIPT="$(dirname "$0")/../youtube-analytics.py"

# 月曜日なら週次レポートをNotionに投稿、それ以外はクイック分析のみ
if [ "$(date +%u)" = "1" ]; then
  exec /usr/bin/python3 "$SCRIPT" --report
else
  exec /usr/bin/python3 "$SCRIPT" --quick
fi
