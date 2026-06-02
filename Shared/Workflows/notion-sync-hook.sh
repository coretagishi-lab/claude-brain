#!/usr/bin/env bash
# notion-sync-hook.sh — Claude Code Stop hook
# PROJECT_STATUS.md が直近120秒以内に更新されていたら Notion に同期する

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# launchd から呼ばれた場合に備えて env を読み込む
[[ -f "$HOME/.zshrc" ]] && source "$HOME/.zshrc" 2>/dev/null || true

NOW=$(date +%s)
RECENT=""

for f in "$VAULT"/Projects/*/PROJECT_STATUS.md; do
  [[ -f "$f" ]] || continue
  MOD=$(stat -f %m "$f" 2>/dev/null || echo 0)
  AGE=$(( NOW - MOD ))
  if [[ $AGE -lt 120 ]]; then
    RECENT="$f"
    break
  fi
done

if [[ -n "$RECENT" ]]; then
  python3 "$SCRIPT_DIR/notion-project-sync.py" --quiet
fi
