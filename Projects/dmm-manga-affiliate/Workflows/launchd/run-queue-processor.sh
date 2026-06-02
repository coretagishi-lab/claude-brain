#!/bin/zsh
# launchd ラッパー: 環境変数を読み込んでqueue-processor.pyを実行
source ~/.zshrc 2>/dev/null
source ~/.zprofile 2>/dev/null

SCRIPT_DIR="$(dirname "$0")/.."
exec /usr/bin/python3 "$SCRIPT_DIR/queue-processor.py"
