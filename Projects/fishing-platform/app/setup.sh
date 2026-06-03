#!/bin/bash
set -e
APP_DIR=/opt/ai-brain/Projects/fishing-platform/app
cd "$APP_DIR"

echo "=== Installing dependencies ==="
pip3 install -r requirements.txt -q

echo "=== Creating uploads dir ==="
mkdir -p static/uploads

echo "=== Creating systemd service ==="
cat > /etc/systemd/system/fishing-platform.service << 'EOF'
[Unit]
Description=Angler's Map - Fishing Platform API
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ai-brain/Projects/fishing-platform/app
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8080 --workers 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable fishing-platform
systemctl restart fishing-platform

sleep 2
systemctl is-active fishing-platform && echo "=== Service started OK ===" || echo "=== Service failed ==="
