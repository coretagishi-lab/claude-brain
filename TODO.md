---
type: todo
title: TODOリスト
updated: 2026-06-01
---

# TODO

## 次のアクション（優先順）

- [ ] DMM manga affiliate パイプライン実装（台本生成→Notion投稿→VPS自動組み立て→YouTube投稿）
- [ ] ConoHa API パスワード再設定 → 残高監視有効化（tagishi 手動作業）
- [ ] VPS 日本語ロケール設定（`locale-gen ja_JP.UTF-8`）
- [ ] YouTube API セットアップ（CHANNEL_ID・OAuth スコープ設定 → tokens.md に追記）

## 優先度: 高

- [ ] iPhoneショートカット設定（Claudeアプリ → inbox.md → ターミナル自動実行）
- [ ] `Prompts/` に台本生成プロンプトを蓄積する（experience.md と連動）
- [ ] Notionやり直しチェックボックス自動検知の実装
- [ ] Canva テンプレート ID を tokens.md / CLAUDE.md に記録する

## 優先度: 中

- [ ] `Workflows/` に動画生成フローを追加する
- [ ] コマ自動検出スクリプトをパイプラインに統合
- [ ] 音声アップ・URL → Notion 自動化（Canva連携の残タスク）
- [ ] Notion MCP 接続（コンテンツ審査・承認フローの Notion 操作自動化）

## 優先度: 低

- [ ] Canva Pro 契約（必要に応じて）
- [ ] Canvaベーステンプレートを作る
- [ ] NGワードリスト作成（`Projects/dmm-manga-affiliate/Knowledge/ng-words.md`）
- [ ] `Knowledge/` に技術メモを移行する

---

## 完了済み

### インフラ・VPS（2026-06-01）

- [x] ConoHa VPS セットアップ・SSH 接続確認（133.88.117.175）
- [x] tmux インストール・永続セッション設定
- [x] systemd タイマー4本稼働（sync / memory-monitor / auth-monitor / conoha-monitor）
- [x] `/opt/ai-brain/.credentials/tokens.md` 一元認証管理システム構築
- [x] `cred-loader.py` 実装（tokens.md → .env + .profile 自動生成）
- [x] `auth-monitor.py` 実装（認証エラー自動検出 → tokens.md 参照 → 自己修復）
- [x] 既存サービスの EnvironmentFile を .profile（無効）から .env（systemd 対応）に修正
- [x] 毎朝8時 Discord 日次レポート実装（`morning-report.py` + systemd timer）
- [x] Discord 双方向通信 Bot を廃止 → webhook 通知のみに変更（API コスト削減）

### VPS 待機タスクシステム（2026-06-01）

- [x] `vps-task-reporter.py` 実装（VPS 自己解決不能 → Notion 待機タスク登録 + Discord 通知）
- [x] `vps-task-checker.py` 実装（Mac Claude Code がセッション開始時に Notion 確認・処理）
- [x] auth-monitor と vps-task-reporter を連携（修復失敗時に自動登録）

### ドキュメント整備（2026-06-01）

- [x] `master-context.md` 作成（システム全体設計・運用ルール・確認フォーマット）
- [x] `CLAUDE.md` v4.4 整備（自律判断ルール・ConoHa後回しルール・認証自己修復フロー）
- [x] 漫画アフィリエイト完全フロー設計・記録（8ステップ・VPS APIゼロ・experience.md 構造）
- [x] `.gitignore` 作成（`.credentials/` を GitHub から除外）

### 既存完了（〜2026-05-27）

- [x] Vault初期構造の構築（2026-05-21）
- [x] `Preferences/style.md` に制作スタイル・好みを記入（2026-05-21）
- [x] dmm-manga-affiliate プロジェクト登録（2026-05-22）
- [x] Google Drive inbox フォルダ構造作成（2026-05-22）
- [x] Notionタスク確認ボード構築・2段階承認フロー確認（2026-05-22）
- [x] VOICEVOX 0.25.2 インストール・API接続確認 localhost:50021（2026-05-22）
- [x] VOICEVOX話者設定（female=四国めたんID:2 / male=玄野武宏ID:11 / narration=No.7 ID:30）（2026-05-22）
- [x] generate_video_v2.py を VOICEVOX API 対応に書き換え（2026-05-22）
- [x] テロップ・音声同期修正（2026-05-22）
- [x] OpenCV 4.13.0 インストール・コマ自動検出スクリプト作成（2026-05-22）
- [x] Claude Code × Canva MCP 接続設定完了（2026-05-27）
- [x] Claude Code × Google Drive MCP 接続設定完了（2026-05-27）
- [x] Google Drive → Canva 画像自動配置ワークフロー動作確認（2026-05-27）
- [x] claude-brain GitHubリポジトリ構築・監視スクリプト完成（2026-05-27）
- [x] Discord Webhook通知設定完了（2026-05-27）
- [x] GitHub Personal Access Token設定（2026-05-27）
