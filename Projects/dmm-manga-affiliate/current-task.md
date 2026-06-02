---
project: dmm-manga-affiliate
updated_at: 2026-06-02
checkpoint: 9ステップ確定フローに更新。Discord Bot実装が次のステップ。
---

## 現在のフェーズ: パイプライン実装（確定フロー v2）

### チェックリスト

**基盤（完了）**
- [x] VOICEVOX 0.25.2 インストール・API接続確認
- [x] Canva MCP を Claude Code に接続
- [x] Notion「コンテンツ審査」DB作成（ID: 3731cad4aa98810e82f8c0f99a483cbb）
- [x] experience.md 初期ファイル作成

**STEP 2: Discord Bot（VPS）**
- [ ] `dmm-discord-watcher.py` 実装（画像+テキスト+投稿URL → Notionキュー登録）
- [ ] systemdサービス登録: `ai-brain-dmm-discord-watcher.service`
- [ ] Notion DBに `source_discord_url`・`api_cost_estimate` フィールド追加
- [ ] statusに `queued` を追加

**STEP 3・5: Mac定時処理（launchd）**
- [ ] `queue-processor.py` 実装（queued → Claude API → draft + コスト記録）
- [ ] `canva-instructions.py` 実装（approved → Canva配置指示詳細生成 → VPSトリガー）
- [ ] launchd plist 作成（30分おき実行）

**STEP 6: VPS Canva組立**
- [ ] `dmm-canva-assembler.py` 実装（Notionから指示取得 → Canva配置 → 編集URL記録）
- [ ] Canvaテンプレート1本を手動で準備

**STEP 8: VPS 投稿**
- [ ] `dmm-publisher.py` 実装（Canva動画DL → YouTube + X投稿）
- [ ] YouTube OAuth2 初回認証（`--auth` オプション）
- [ ] X（Twitter）API token を tokens.md に追記

**STEP 9: Analytics**
- [ ] `dmm-analytics.py` 実装（YouTube Analytics → Notion）

**認証**
- [ ] ANTHROPIC_API_KEY 更新（現在401エラー）→ console.anthropic.com で再発行

## 技術スタック（確定 v2）

| 役割 | ツール |
|---|---|
| 画像ソース | Discord（一本化・GDrive廃止） |
| Discord監視 | `dmm-discord-watcher.py`（VPS常駐） |
| 台本生成 | Claude API（Mac定時処理・1回/本） |
| Canva配置指示 | Claude API（Mac定時処理・1回/本） |
| 動画組立 | Canva（VPS Canva REST API） |
| TTS | VOICEVOX（Canva組込み or VPS生成） |
| YouTube投稿 | YouTube Data API v3（VPS） |
| X投稿 | X API v2（VPS） |
| 承認フロー | Notion（全ステップのハブ） |
| 定時処理 | launchd（Mac）+ systemd（VPS） |

## Notionステータス遷移

```
queued → draft → approved → canva_ready → final → uploaded
  ↑         ↑        ↑            ↑           ↑        ↑
VPS Bot   Mac定時  tagishi     VPS Canva   tagishi  VPS投稿
```
