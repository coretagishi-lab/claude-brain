---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-02
---

# 引き継ぎ — AI-Brain セッション 2026-06-02

このファイルを次のチャットの冒頭に貼り付けて使う。

---

## システム全体像

```
tagishi（Mac）
  │
  ├─ Claude Code（ターミナル）  ← 思考・生成・判断・API呼び出し
  │    └─ AI-Brain Vault（~/Desktop/ClaudeProjects/AI-Brain/）← 記憶層
  │
  ├─ Notion  ← 人間UIとClaudeの共有作業台（承認・レビュー・タスク確認）
  │
  └─ ConoHa VPS 133.88.117.175  ← 自動化層（APIゼロ・判断しない）
       └─ /opt/ai-brain/Shared/Workflows/
```

**原則: 頭はターミナル・実行はVPS。VPSはAPIゼロ。判断が必要な場合はNotionキューに積んでターミナル待機。**

---

## 今日（2026-06-02）完成したもの

### VPS 稼働中サービス（全5本）

| サービス | 内容 |
|---|---|
| `ai-brain-sync.timer` | 30分ごとVault→GitHub同期 ✅ 正常確認済み |
| `ai-brain-memory-monitor.timer` | メモリ監視・800MB超でDiscord通知 |
| `ai-brain-auth-monitor.timer` | 5分ごと認証エラー検出・自己修復 |
| `ai-brain-morning-report.timer` | 毎朝8時 Discord日次レポート |
| `ai-brain-discord-responder.service` | 常駐Bot（1/2返信受付のみ・APIゼロ） |

### インフラ整備（2026-06-02 完了）

| 項目 | 状態 |
|---|---|
| VPS 日本語ロケール（ja_JP.UTF-8） | ✅ 設定済み |
| GitHub token（inbox-mobile・有効期限なし） | ✅ 更新済み |
| VPS sync 正常確認 | ✅ |
| スマホ Inbox アプリ接続 | ✅ iPhone → GitHub 投稿フロー確認済み |
| ConoHa エラーログクリア | ✅ |

### dmm-manga-affiliate パイプライン実装（2026-06-02 完了）

| ファイル | 役割 |
|---|---|
| `Projects/dmm-manga-affiliate/Workflows/generate-content.py` | STEP 1: Claude API 1回 → 台本・タイトル・説明文生成 → Notion投稿 |
| `Projects/dmm-manga-affiliate/Workflows/setup-notion-db.py` | Notionコンテンツ審査DB作成（初回のみ） |
| `Projects/dmm-manga-affiliate/Workflows/vps-assemble-video.py` | STEP 3: Notion approved → VOICEVOX + ffmpeg 動画生成 |
| `Projects/dmm-manga-affiliate/Workflows/vps-youtube-upload.py` | STEP 5: YouTube Data API 自動投稿 |
| `Projects/dmm-manga-affiliate/Knowledge/experience.md` | 台本品質改善ログ |

**Notion コンテンツ審査 DB:**  
`NOTION_CONTENT_DB_ID=3731cad4aa98810e82f8c0f99a483cbb`（ローカル・VPS設定済み）

---

## フロー確定（2026-06-02）

**9ステップ確定フロー（詳細は master-context.md セクション9参照）:**

```
tagishi Discord投稿（画像+タイトル+アフィURL）
  → VPS Discord Bot → Notionキュー（queued）
  → Mac定時処理 → Claude API台本生成 → Notion（draft）
  → tagishi Notion承認（approved）
  → Mac定時処理 → Canva配置指示生成 → VPSトリガー
  → VPS Canva組立 → Notion（canva_ready）
  → tagishi 確認（final）
  → VPS YouTube + X投稿（uploaded）
  → VPS Analytics → Notion記録
```

**Notion追加フィールド:** `source_discord_url`・`api_cost_estimate`

---

## 次にやること（優先順）

1. **VPS Discord Botを実装する（STEP 2）**
   - `Projects/dmm-manga-affiliate/Workflows/dmm-discord-watcher.py` を作成
   - Discord専用チャンネルの画像+テキスト+投稿URLを取得→Notionキュー登録
   - systemdサービスとして常駐: `ai-brain-dmm-discord-watcher.service`

2. **Mac定時処理スクリプトを実装する（STEP 3・5）**
   - `queue-processor.py`: queued → Claude API台本生成 → draft
   - `canva-instructions.py`: approved → Canva配置指示生成 → VPSトリガー
   - launchd plistで30分おき自動実行

3. **Notion DBにフィールド追加**
   - `source_discord_url`（url型）
   - `api_cost_estimate`（rich_text型）

4. **VPS Canva組立・投稿スクリプト実装（STEP 6・8）**
   - `dmm-canva-assembler.py`・`dmm-publisher.py`

5. **ANTHROPIC_API_KEY 更新**（現在のキーが401エラー）
   - console.anthropic.com で新しいキーを発行
   - VPS tokens.md + ローカル ~/.zshrc を更新

6. **ConoHa APIパスワード再設定**（tagishi手動）→ 残高監視有効化

---

## 運用ルール

### 確認フォーマット（これ以外で確認しない）
```
【案件名】質問
1: OK
2: 待って
```

### APIゼロ原則
- VPS は Claude API を一切使わない
- VPS が判断できない問題 → `discord-ask.py` で質問 or `vps-task-reporter.py` でNotionキュー登録
- ターミナルからVPSへの指示は詳細に書いて判断不要な状態で渡す

### コスト設計
- モデルは Sonnet 固定（Opus 禁止）
- 漫画アフィリエイト: API使用は台本生成1回/本 + 分析週1回のみ
- 離席前に `/clear`

### ファイル・フォーマットの自律判断
ファイルの構造・番号・順番・フォーマットに関する判断は全て自律で行う。tagishiに確認しない。

---

## 重要パス・接続情報

| 項目 | 値 |
|---|---|
| VPS SSH | `ssh -i ~/.ssh/conoha_vps root@133.88.117.175` |
| VPS パス | `/opt/ai-brain/` |
| 認証情報 | `/opt/ai-brain/.credentials/tokens.md`（chmod 600） |
| GitHub リポジトリ | `coretagishi-lab/claude-brain`（main ブランチ） |
| Notion Outbox DB | `36f1cad4-aa98-81fb-93d8-d40bfb95cff9` |
| Vault ローカル | `~/Desktop/ClaudeProjects/AI-Brain/` |

---

## セッション開始チェックリスト

```bash
# 1. VPS待機タスク確認（最優先）
python3 Shared/Workflows/vps-task-checker.py

# 2. Inboxキュー確認
python3 Shared/Workflows/queue.py status

# 3. このファイルを読んだ → 作業開始
```
