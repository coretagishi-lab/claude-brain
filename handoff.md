---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-02
---

# 引き継ぎ — AI-Brain セッション 2026-06-02

このファイルを次のチャットの冒頭に貼り付けて使う。

---

## システム全体像（確定版）

```
tagishi
  └─ Discord に投げるだけ
       │
       ├─ #inbox           タスク・指示・メモ
       ├─ #dmm-素材投稿    漫画コマ画像 + タイトル + アフィURL
       └─ #通知            VPS実行結果・Bot返信（読み取り専用）
            │
            ├─ API不要 → VPS Bot 即実行 → #通知に返信
            │
            └─ API必要 → Notionキュー（queued）
                              └─ 次回 Claude Code セッションで処理
```

**原則: tagishiはDiscordに投げるだけ。GitHubキュー・ファイルInbox廃止。**

---

## Discord チャンネル一覧（確定）

| チャンネル | ID | 用途 |
|---|---|---|
| `#inbox` | `1511214415611953214` | 全入力。API不要→即実行、API必要→Notionキュー |
| `#dmm-素材投稿` | `1511211307788144650` | 漫画素材投稿→Notionキュー（queued） |
| `#通知` | `1511214417990254664` | VPS実行結果・アラート出力専用 |

---

## 2026-06-02 完成したもの

### VPS 稼働中サービス（全6本）

| サービス | 内容 | 状態 |
|---|---|---|
| `ai-brain-sync.timer` | 30分ごとVault→GitHub同期 | ✅ |
| `ai-brain-memory-monitor.timer` | メモリ監視・800MB超でDiscord通知 | ✅ |
| `ai-brain-auth-monitor.timer` | 5分ごと認証エラー検出・自己修復 | ✅ |
| `ai-brain-morning-report.timer` | 毎朝8時 Discord日次レポート | ✅ |
| `ai-brain-discord-responder.service` | 旧Bot（1/2返信受付・後で統合予定） | ✅ |
| `ai-brain-dmm-discord-watcher.service` | `#dmm-素材投稿`監視→Notionキュー登録 | ✅ 稼働中 |

### 実装済みスクリプト（dmm-manga-affiliate）

| ファイル | 役割 |
|---|---|
| `Workflows/dmm-discord-watcher.py` | STEP 2: #dmm-素材投稿 監視→Notionキュー登録 |
| `Workflows/generate-content.py` | STEP 3: Claude API→台本・タイトル・説明文→Notion |
| `Workflows/vps-assemble-video.py` | STEP 6: VOICEVOX+ffmpeg動画生成（骨格） |
| `Workflows/vps-youtube-upload.py` | STEP 8: YouTube自動投稿（骨格） |
| `Knowledge/experience.md` | 台本品質改善ログ |

### Notion コンテンツ審査 DB

`NOTION_CONTENT_DB_ID=3731cad4aa98810e82f8c0f99a483cbb`（VPS・ローカル設定済み）

ステータス遷移: `queued → draft → approved → canva_ready → final → uploaded`

---

## dmm-manga-affiliate 9ステップフロー（詳細はmaster-context.md セクション9）

```
tagishi: #dmm-素材投稿 に画像+タイトル+アフィURL投稿
  → [VPS] Bot検知 → Notion（queued）
  → [Mac定時] Claude API台本生成 → Notion（draft）
  → [tagishi] Notion承認（approved）
  → [Mac定時] Canva配置指示生成 → VPSトリガー
  → [VPS] Canva組立 → Notion（canva_ready）
  → [tagishi] Canva確認（final）
  → [VPS] YouTube + X投稿（uploaded）
  → [VPS定期] Analytics → Notion記録
```

---

## 次にやること（優先順）

1. **`#inbox` Bot実装**（API不要即実行 / API必要キュー登録のルーター）
   - `Shared/Workflows/discord-inbox-bot.py` を新規作成
   - `ai-brain-discord-inbox-bot.service` でVPS常駐
   - `#通知` チャンネルへの送信ヘルパーも同スクリプト内に実装

2. **Mac定時処理スクリプト実装（STEP 3・5）**
   - `queue-processor.py`: Notion queued → Claude API台本生成 → draft
   - `canva-instructions.py`: Notion approved → Canva配置指示 → VPSトリガー
   - launchd plistで30分おき自動実行

3. **ANTHROPIC_API_KEY 更新**（現在401エラー）
   - console.anthropic.com で新しいキーを発行
   - VPS tokens.md + ローカル ~/.zshrc を更新

4. **ConoHa APIパスワード再設定**（tagishi手動）→ 残高監視有効化

---

## 運用ルール

### 確認フォーマット（これ以外で確認しない）
```
【案件名】質問
1: OK
2: 待って
```

### Discord一本化原則
- tagishiはDiscordに投げるだけ。GitHubキュー・ファイルInboxは廃止済み
- API不要タスク → VPS Bot即実行 → `#通知`に結果
- API必要タスク → Notionキュー → 次回セッション開始時に処理

### コスト設計
- モデルはSonnet固定（Opus禁止）
- 漫画アフィリエイト: API使用は台本生成1回/本 + 分析週1回のみ
- 離席前に `/clear`

---

## 重要パス・接続情報

| 項目 | 値 |
|---|---|
| VPS SSH | `ssh -i ~/.ssh/conoha_vps root@133.88.117.175` |
| VPS パス | `/opt/ai-brain/` |
| 認証情報 | `/opt/ai-brain/.credentials/tokens.md`（chmod 600） |
| GitHub リポジトリ | `coretagishi-lab/claude-brain`（main ブランチ） |
| Notion Outbox DB | `36f1cad4-aa98-81fb-93d8-d40bfb95cff9` |
| Notion コンテンツ審査DB | `3731cad4aa98810e82f8c0f99a483cbb` |
| Vault ローカル | `~/Desktop/ClaudeProjects/AI-Brain/` |

---

## セッション開始チェックリスト

```bash
# 1. VPS待機タスク確認（最優先）
python3 Shared/Workflows/vps-task-checker.py

# 2. Notionキュー確認（queued件数）
#    → セッション中に処理する

# 3. このファイルを読んだ → 作業開始
```
