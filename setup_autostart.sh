#!/bin/bash
# setup_autostart.sh — バックグラウンド自動起動の設定

REPO_DIR="$HOME/Desktop/ClaudeProjects/claude-brain"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.claude-brain.watch.plist"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$LOG_DIR" "$PLIST_DIR"
chmod +x "$REPO_DIR/watch_inbox.sh"

# ntfy.shトピックの設定
NTFY_TOPIC="claude-brain-$(openssl rand -hex 6)"
echo "$NTFY_TOPIC" > "$REPO_DIR/.ntfy_topic"
echo ".ntfy_topic" >> "$REPO_DIR/.gitignore" 2>/dev/null || true

# launchd plist生成
cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-brain.watch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$REPO_DIR/watch_inbox.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/watch.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/watch.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>
</dict>
</plist>
PLIST

# launchd登録
launchctl unload "$PLIST_FILE" 2>/dev/null
launchctl load "$PLIST_FILE"

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "【スマホ通知の設定】"
echo "1. スマホに「ntfy」アプリをインストール（iOS/Android 無料）"
echo "   iOS: https://apps.apple.com/app/ntfy/id1625396347"
echo "   Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy"
echo ""
echo "2. アプリを開いて「+」ボタンでトピックを追加："
echo "   トピック名: $NTFY_TOPIC"
echo "   サーバー: ntfy.sh（デフォルト）"
echo ""
echo "3. これでapproval.mdが更新されるとスマホに通知が来ます"
echo ""
echo "【動作確認】"
echo "launchctl list | grep claude-brain  で起動確認"
echo "tail -f $LOG_DIR/watch.log  でログ確認"
