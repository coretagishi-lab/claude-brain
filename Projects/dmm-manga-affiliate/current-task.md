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

---
## 2026-06-10 セッション記録

### 確定した技術スタック
- テンプレート: DAHKogY0SBo（②ナレーション・10ページ構成）
- 画像フロー: Discord CDN → VPS(PNG変換) → tmpfiles.org → Canva upload → スロット差し込み
- テキスト書き換え: Canva MCP `replace_text` で element_id 指定
- 画像ズーム: `update_fill` + `resize_element` + `position_element` の組み合わせ
- コマ座標計算: 漫画1000×1399px、2列3行、スロット954×837px

### ページ構成（確定）
- ページ1: 導入（タイトル・煽り）→ ③行目のみ漫画タイトルに書き換え
- ページ2〜9: コマ画像 + テロップ1行（台本①〜⑧）
- ページ10: エンド固定

### element_id マッピング
タイトル3行目: PBs1sTlCLqHDSG14-LBrqdhnZYLPRPyJX（「男の漫画」）
テロップ①: PBG3BLhBZW05Kb0W-LBhlvQNP9s6Wmwvr
テロップ②: PBCSwpnm9S6QVHtJ-LBff234VHn89xWtW
テロップ③: PBjDNccpBqWtybYQ-LBxsBSg503sFyjyQ
テロップ④: PBvxHVxQT8c46KWb-LBHJq4nGtPjjtjnV
テロップ⑤: PBw7ntJLPN1YXxv3-LB7D7v0gRPY16KGC
テロップ⑥: PBwNd5vms7mw2gXb-LBg46mQW7DYvYrS2
テロップ⑦: PBkLftpwjtcRJDvs-LB2Dj8TSWKB0CnvR
テロップ⑧: PBpYZmnGCfCLdFFC-LBzvFjt040LjCkN6
画像スロット（ページ2）: PBG3BLhBZW05Kb0W-LBLG8GxWtKLtPZcZ

### 次のフロー（確定）
1. Discordに漫画4ページ投稿（タイトル・アフィURL付き）
2. queue-processor.py が台本生成 → Notionにdraft
   - 出力形式: ①〜⑧の8行テロップ（1テロップ=文字数上限TBD）
3. tagishiがNotionで確認・チェックOK → approved
4. assembler.pyがCanva動画組み立て
   - テンプレコピー → タイトル書き換え → コマ画像差し込み(ズーム付き) → テロップ書き換え
   - VOICEVOXはデフォルト四国めたん(speaker=2)で生成
5. Canva URLをNotionに返す → tagishiが確認
6. ナレーター変更指示があれば対応可能な設計にする

### 未決定事項
- 1テロップ何文字まで（tagishiが実際のデザインを見て決める）
- VOICEVOXキャラ（デフォルト=めたん、後から変更可）

### VPS確認済みスクリプト
- manga-crop.py: /opt/ai-brain/Projects/dmm-manga-affiliate/Workflows/
- 画像アップロード: tmpfiles.org経由（HTTPS、curl対応）
