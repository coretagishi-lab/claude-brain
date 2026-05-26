#!/bin/bash
# setup_autostart.sh — バックグラウンド自動起動の設定

REPO_DIR="$HOME/Desktop/ClaudeProjects/claude-brain"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.claude-brain.watch.plist"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$LOG_DIR" "$PLIST_DIR"
chmod +x "$REPO_DIR/watch_inbox.sh"

# Discord Webhook URLの設定
echo ""
echo "=== Discord Webhook URL の設定 ==="
echo ""
echo "以下の手順でWebhook URLを取得してください："
echo "1. Discordで通知を受けたいチャンネルを開く"
echo "2. チャンネル設定 → 連携サービス → ウェブフック → 新しいウェブフック"
echo "3. URLをコピー"
echo ""
read -p "Discord Webhook URLを貼り付けてください: " WEBHOOK_URL

if [ -z "$WEBHOOK_URL" ]; then
  echo "警告: Webhook URLが未入力です。後で設定する場合："
  echo "  echo 'YOUR_WEBHOOK_URL' > $REPO_DIR/.discord_webhook"
else
  echo "$WEBHOOK_URL" > "$REPO_DIR/.discord_webhook"
  echo "Webhook URL を保存しました（.discord_webhook）"

  # 接続テスト
  curl -s -H "Content-Type: application/json" \
    -d '{"content": "✅ claude-brain セットアップ完了。このチャンネルで通知を受け取ります。"}' \
    "$WEBHOOK_URL" > /dev/null 2>&1
  echo "Discordにテスト通知を送信しました"
fi

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

launchctl unload "$PLIST_FILE" 2>/dev/null
launchctl load "$PLIST_FILE"

echo ""
echo "=== セットアップ完了 ==="
echo "launchctl list | grep claude-brain  で起動確認"
echo "tail -f $LOG_DIR/watch.log  でログ確認"
