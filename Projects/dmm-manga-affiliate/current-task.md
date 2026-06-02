---
project: dmm-manga-affiliate
updated_at: 2026-06-02
checkpoint: STEP 1スクリプト完成・Notion DB作成済み。ANTHROPIC_API_KEY設定後に本番実行可能。
---

## 現在のフェーズ: パイプライン実装（STEP 1完了・STEP 3準備中）

### チェックリスト

- [x] VOICEVOX 0.25.2 インストール・API接続確認
- [x] generate_video_v2.py VOICEVOX対応書き換え
- [x] テロップ・音声同期修正（duration実測値制御）
- [x] OpenCV コマ自動検出スクリプト作成
- [x] Canva MCP を Claude Code に接続（ワンクリック完了）
- [x] Notion「コンテンツ審査」DB作成（ID: 3731cad4aa98810e82f8c0f99a483cbb）
- [x] generate-content.py 実装（STEP 1: 台本生成 → Notion投稿）
- [x] vps-assemble-video.py 実装（STEP 3: VOICEVOX+ffmpeg動画生成）
- [x] vps-youtube-upload.py 実装（STEP 5: YouTube投稿）
- [x] experience.md 初期ファイル作成
- [ ] ANTHROPIC_API_KEY を ~/.zshrc に追加（generate-content.py単体実行のため）
- [ ] 漫画パネル画像を /opt/ai-brain-media/panels/<slug>/ に配置（STEP 3実行のため）
- [ ] YouTube OAuth2 初回認証（vps-youtube-upload.py --auth）
- [ ] 本番1本目を実際に生成・投稿する

## 技術スタック（確定）

| 役割 | ツール |
|---|---|
| 画像ソース | GDrive MCP |
| コマ検出 | OpenCV (detect_panels.py) |
| 動画生成 | generate_video_v2.py + ffmpeg |
| TTS | VOICEVOX localhost:50021 |
| テンプレート | Canva MCP（接続済み） |
| 承認フロー | Notion MCP（次回接続） |
| 動画保存 | GDrive → YouTube |

## ファイル場所

- スクリプト: `/tmp/dmm-manga-video/generate_video_v2.py`
- コマ検出: `/tmp/dmm-manga-video/detect_panels.py`
- 画像inbox: `/tmp/dmm-manga-images/`
- 動画出力: `/tmp/dmm-manga-video/`
