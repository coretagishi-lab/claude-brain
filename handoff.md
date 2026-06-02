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
       ├─ #inbox           タスク・指示・メモ / YouTube・Instagram URL分析
       ├─ #dmm-素材投稿    漫画コマ画像 + タイトル + アフィURL
       └─ #通知            VPS実行結果・Bot返信（読み取り専用）
            │
            ├─ API不要 → VPS Bot 即実行 → #通知 or #inbox にリプライ
            └─ API必要 → Notionキュー（queued） → Mac定時処理（30分おき）
```

**原則: tagishiはDiscordに投げるだけ。GitHubキュー・ファイルInbox廃止。**

---

## Discord チャンネル一覧（確定）

| チャンネル | ID | Bot |
|---|---|---|
| `#inbox` | `1511214415611953214` | discord-inbox-bot ✅ |
| `#dmm-素材投稿` | `1511211307788144650` | dmm-discord-watcher ✅ |
| `#通知` | `1511214417990254664` | 出力専用 |

---

## VPS 稼働中サービス（全7本）

| サービス | 内容 | 状態 |
|---|---|---|
| `ai-brain-sync.timer` | 30分ごとVault→GitHub同期 | ✅ |
| `ai-brain-memory-monitor.timer` | メモリ監視・800MB超でDiscord通知 | ✅ |
| `ai-brain-auth-monitor.timer` | 5分ごと認証エラー検出・自己修復 | ✅ |
| `ai-brain-morning-report.timer` | 毎朝8時 Discord日次レポート | ✅ |
| `ai-brain-discord-responder.service` | 旧Bot（後で統合予定） | ✅ |
| `ai-brain-dmm-discord-watcher.service` | `#dmm-素材投稿`監視→Notionキュー | ✅ |
| `ai-brain-discord-inbox-bot.service` | `#inbox`ルーター・URL分析 | ✅ |

---

## Mac launchd ジョブ（自動実行）

| ジョブ | スケジュール | 役割 |
|---|---|---|
| `com.ai-brain.queue-processor` | 30分おき | Notion queued → Claude API台本生成 → draft |
| `com.ai-brain.canva-instructions` | 30分おき | Notion approved → Canva配置指示 → canva_pending |
| `com.ai-brain.mac-config-sync` | 毎日3:00 | ~/.zshrc をマスクしてVaultに保存 |
| `com.ai-brain.sync-youtube-cookies` | 毎週月曜3:00 | youtube-cookies.txt をVPSに転送 |
| `com.ai-brain.sync` | （Mac側の旧sync・確認要） | — |

---

## discord-inbox-bot の主な機能

| 機能 | コマンド例 | 動作 |
|---|---|---|
| URL分析 | YouTube/Instagram URL貼り付け | yt-dlp で全情報収集→#通知に送信（📋コピーボタン付き） |
| サービス確認 | `status` | VPSサービス一覧を返信 |
| 同期 | `sync` | ai-brain-sync を即時実行 |
| 再起動 | `restart <サービス名>` | systemctl restart |
| ログ確認 | `log <サービス名>` | journalctl 最新20行 |
| メモ保存 | `メモ: <内容>` | Notionに保存 |
| Notionキュー | その他のメッセージ | 次回ターミナル起動時に処理 |

**URL分析の技術スタック:**
- yt-dlp + `--js-runtimes node --remote-components ejs:github`（EJSチャレンジ解決）
- クッキー: `/opt/ai-brain/.credentials/youtube-cookies.txt`（Mac→VPS 週1自動転送）
- 字幕: 日本語優先 → 英語フォールバック
- 取得内容: タイトル・説明文・説明文内ドメイン・チャプター・字幕・上位コメント

---

## dmm-manga-affiliate パイプライン状況

**Notion DB:** `NOTION_CONTENT_DB_ID=3731cad4aa98810e82f8c0f99a483cbb`

**ステータス遷移:**
```
queued → draft → approved → canva_pending → canva_ready → final → uploaded
  ↑         ↑        ↑            ↑              ↑           ↑        ↑
VPS Bot  Mac定時  tagishi     Mac定時          VPS       tagishi  VPS投稿
(済み)   (済み)            (済み)           (未実装)            (未実装)
```

**実装済みスクリプト:**

| ファイル | 役割 | STEP |
|---|---|---|
| `Workflows/dmm-discord-watcher.py` | #dmm-素材投稿 → Notionキュー | 2 ✅ |
| `Workflows/queue-processor.py` | queued → Claude API台本 → draft | 3 ✅ |
| `Workflows/canva-instructions.py` | approved → Canva配置指示 → canva_pending | 5 ✅ |
| `Workflows/vps-assemble-video.py` | 骨格のみ | 6 ⚠️ |
| `Workflows/vps-youtube-upload.py` | 骨格のみ | 8 ⚠️ |

---

## スケールアップ設計（確定 2026-06-03）

| 項目 | 設計 |
|---|---|
| バリエーション | 1素材から **4本** 一括生成（デフォルト） |
| アカウント | **YouTube 4アカウント**で検証スタート |
| 投稿時間 | アカウントごとにずらす（9:00 / 12:00 / 18:00 / 21:00） |
| Canvaテンプレ | アカウントごとに専用テンプレートを使用 |
| IP対策 | 収益が出てから（今は保留） |

詳細設計: `master-context.md` セクション9「スケールアップ設計」参照

---

## 次にやること（優先順）

1. **4バリエーション対応に queue-processor.py を改修**
   - 1素材 → Claude API 1回 → 4バリエーション（タイトル・説明文・台本）一括生成
   - Notion に4件レコード作成（account_id: 1〜4, source_group_id: 同一UUID）

2. **Notion DBにアカウント管理フィールドを追加**
   - `account_id`（select: 1/2/3/4）
   - `variant_num`（number）
   - `source_group_id`（rich_text）
   - `scheduled_time`（date）
   - `canva_template_id`（rich_text）

3. **dmm-canva-assembler.py 実装（STEP 6）**
   - canva_pending → account_idからテンプレートIDを決定 → Canva組立 → canva_ready

4. **パイプライン通し確認**
   - `#dmm-素材投稿` に画像を投稿 → queued → draft → approved → canva_pending まで確認

5. **YouTube OAuth2 認証（4アカウント分）**
   - `python3 vps-youtube-upload.py --auth` を各アカウントで実行

6. **ConoHa APIパスワード再設定**（tagishi手動）→ 残高監視有効化

---

## 認証情報・重要パス

| 項目 | 値 |
|---|---|
| VPS SSH | `ssh -i ~/.ssh/conoha_vps root@133.88.117.175` |
| VPS パス | `/opt/ai-brain/` |
| 認証情報 | `/opt/ai-brain/.credentials/tokens.md`（chmod 600） |
| GitHub リポジトリ | `coretagishi-lab/claude-brain`（main ブランチ） |
| Notion Outbox DB | `36f1cad4-aa98-81fb-93d8-d40bfb95cff9` |
| Notion コンテンツ審査DB | `3731cad4aa98810e82f8c0f99a483cbb` |
| Vault ローカル | `~/Desktop/ClaudeProjects/AI-Brain/` |
| Macクッキー | `~/.config/ai-brain/youtube-cookies.txt` |

---

## セッション開始チェックリスト

```bash
# 1. VPS待機タスク確認（最優先）
python3 Shared/Workflows/vps-task-checker.py

# 2. Notionキュー確認（queued件数）
#    → セッション中に処理する

# 3. このファイルを読んだ → 作業開始
```
