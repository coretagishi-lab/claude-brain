#!/bin/zsh
source ~/.zshrc 2>/dev/null
source ~/.zprofile 2>/dev/null

SCRIPT_DIR="$(dirname "$0")/.."
exec /usr/bin/python3 "$SCRIPT_DIR/competitive-analyzer.py"
