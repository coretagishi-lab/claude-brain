---
project: dmm-manga-affiliate
updated_at: 2026-06-02
checkpoint: STEP 1-5スクリプト完成・ANTHROPIC_API_KEY更新済み。通し確認が次のステップ。
---

## 現在のフェーズ: パイプライン動作確認（STEP 2→3実行待ち）

### チェックリスト

**基盤（完了）**
- [x] VOICEVOX 0.25.2 インストール・API接続確認
- [x] Canva MCP を Claude Code に接続
- [x] Notion「コンテンツ審査」DB作成（ID: 3731cad4aa98810e82f8c0f99a483cbb）
- [x] experience.md 初期ファイル作成
- [x] ANTHROPIC_API_KEY 更新（no-expiry・VPS+ローカル反映済み）

**Discord チャンネル構成（完了）**
- [x] #inbox（1511214415611953214）: タスク入力・URL分析・即実行ルーター
- [x] #dmm-素材投稿（1511211307788144650）: 漫画素材投稿→Notionキュー
- [x] #通知（1511214417990254664）: VPS実行結果・Bot返信

**VPS Bot（完了）**
- [x] `dmm-discord-watcher.py` 実装・稼働（STEP 2）
- [x] `discord-inbox-bot.py` 実装・稼働（URL分析・📋コピーボタン付き）

**Mac 定時処理（launchd 登録済み・30分おき）**
- [x] `queue-processor.py` – queued → Claude API → draft
- [x] `canva-instructions.py` – approved → Canva配置指示 → canva_pending

**未実装（残タスク）**
- [ ] `dmm-canva-assembler.py`（VPS: canva_pending → Canva API → canva_ready）
- [ ] `dmm-publisher.py`（VPS: final → YouTube + X投稿・OAuth2認証必要）
- [ ] `dmm-analytics.py`（VPS: YouTube Analytics → Notion）
- [ ] パイプライン通し確認（#dmm-素材投稿 → Notion queued → draft → approved → canva_pending）

## 技術スタック（確定 v2）

| 役割 | ツール |
|---|---|
| 画像ソース | Discord（#dmm-素材投稿） |
| Discord監視 | `dmm-discord-watcher.py`（VPS常駐） |
| 台本生成 | Claude API（Mac定時処理・1回/本） |
| Canva配置指示 | Claude API（Mac定時処理・1回/本） |
| 動画組立 | Canva REST API（VPS・未実装） |
| YouTube投稿 | YouTube Data API v3（VPS・未実装） |
| X投稿 | X API v2（VPS・未実装） |
| 承認フロー | Notion（全ステップのハブ） |

## Notionステータス遷移

```
queued → draft → approved → canva_pending → canva_ready → final → uploaded
  ↑         ↑        ↑            ↑              ↑           ↑        ↑
VPS Bot  Mac定時  tagishi     Mac定時          VPS       tagishi  VPS投稿
(済み)   (済み)            (済み)           (未実装)            (未実装)
```
