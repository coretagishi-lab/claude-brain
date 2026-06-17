#!/bin/zsh
source ~/.zshrc 2>/dev/null
source ~/.zprofile 2>/dev/null
exec /usr/bin/python3 "$(dirname "$0")/../youtube-uploader.py" --check-pending
