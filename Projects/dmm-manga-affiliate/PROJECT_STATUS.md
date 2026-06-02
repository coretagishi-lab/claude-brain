---
project_name: dmm-manga-affiliate
current_status: active
priority: high
due_date: ""
review_waiting: false
updated_at: 2026-06-02
---

## current_goal
- DMMアフィリエイト漫画動画を「台本生成→Notion承認→動画組立→YouTube投稿」の8ステップパイプラインで自動化する

## next_action
- ANTHROPIC_API_KEY を ~/.zshrc に追加して generate-content.py を単体実行できる状態にする
- 本番1本目の漫画タイトル・アフィリエイトURLを決定してSTEP 1を実行する

## blocker
- ANTHROPIC_API_KEY が Bash 環境変数に未設定（generate-content.py 単体実行には必要）
- 漫画パネル画像が VPS にない（STEP 3 実行前に配置が必要: /opt/ai-brain-media/panels/<slug>/）

## latest_output

| type | name | path | url | updated_at |
|---|---|---|---|---|
| mp4 | dmm-manga-A-2026-05-22-01-v2.mp4 | /tmp/dmm-manga-video/ | https://drive.google.com/file/d/1ZoQWAu-4XcRSRlrU_yHx1jUBwLgK51xP/view?usp=drivesdk | 2026-05-22 |
