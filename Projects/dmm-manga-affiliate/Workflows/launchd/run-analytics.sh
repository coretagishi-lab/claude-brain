#!/bin/zsh
source ~/.zshrc 2>/dev/null
source ~/.zprofile 2>/dev/null
SCRIPT="$(dirname "$0")/../youtube-analytics.py"
exec /usr/bin/python3 "$SCRIPT"
