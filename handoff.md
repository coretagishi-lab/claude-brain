---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-10
---

# ⚠️ 最重要ルール（毎回必ず読む）

## コスト判断基準
APIコスト不要な作業（SSH/curl/git/ファイル操作/Notion API）
  → Claude.aiから直接Macターミナルに指示

APIコスト発生する作業（台本生成/画像解析/テキスト生成）
  → Claude.aiからClaude Codeターミナルに指示（サブスク内・追加課金ゼロ）

## 絶対禁止
- Anthropic APIを直接HTTPリクエストで叩くスクリプトをサイレントで実装しない
- コスト発生の可能性がある実装は必ず事前にtagishiに確認する
- この確認を怠ったことで2026-06-10に無断コスト発生の実装をしてしまった

---

# システム構成

## 三層アーキテクチャ
Claude.ai（戦略・指示）
  ↓ APIコスト不要 → Macターミナルに直接指示
  ↓ APIコスト発生 → Claude Codeターミナルに指示
Mac Claude Code（判断・生成）← サブスクリプション・追加課金ゼロ
  ↓
ConoHa VPS 133.88.117.175（実行・APIゼロ）

## Discord
#inbox          ID: 1511214415611953214
#dmm-素材投稿   ID: 1511211307788144650
#通知           ID: 1511214417990254664

## VPS
SSH: ssh -i ~/.ssh/conoha_vps root@133.88.117.175
パス: /opt/ai-brain/

---

# dmm-manga-affiliate 現在の状態

## Canvaテンプレート
デザインID: DAHKogY0SBo（②ナレーション・10ページ）

ページ構成:
  ページ1:  導入（③行目のみ漫画タイトルに書き換え）
  ページ2〜9: コマ画像（ズーム済み）+ テロップ1行
  ページ10: エンド固定

element_id:
  タイトル③: PBs1sTlCLqHDSG14-LBrqdhnZYLPRPyJX
  テロップ①: PBG3BLhBZW05Kb0W-LBhlvQNP9s6Wmwvr
  テロップ②: PBCSwpnm9S6QVHtJ-LBff234VHn89xWtW
  テロップ③: PBjDNccpBqWtybYQ-LBxsBSg503sFyjyQ
  テロップ④: PBvxHVxQT8c46KWb-LBHJq4nGtPjjtjnV
  テロップ⑤: PBw7ntJLPN1YXxv3-LB7D7v0gRPY16KGC
  テロップ⑥: PBwNd5vms7mw2gXb-LBg46mQW7DYvYrS2
  テロップ⑦: PBkLftpwjtcRJDvs-LB2Dj8TSWKB0CnvR
  テロップ⑧: PBpYZmnGCfCLdFFC-LBzvFjt040LjCkN6
  画像スロット(p2): PBG3BLhBZW05Kb0W-LBLG8GxWtKLtPZcZ

## 画像フロー（確定）
Discord CDN → VPS(webp→PNG変換) → tmpfiles.org → Canva upload → スロット差し込み
コマズーム: update_fill + resize_element + position_element
漫画サイズ: 1000x1399px、2列3行、スロット: 954x837px

## Notion DB
コンテンツ審査DB: 3731cad4aa98810e82f8c0f99a483cbb
タスク確認ボード: 3671cad4aa98813b85b2ed9e3127b913
ステータス: 👀 確認待ち / 🔄 作成中 / ✅ 確認済み

## VPSスクリプト
manga-crop.py: /opt/ai-brain/Projects/dmm-manga-affiliate/Workflows/

---

# 次にやること（優先順）

## 1. queue-processor.py修正（最優先）
問題: Anthropic APIを直接叩いている → クレジット必要
修正: Claude Codeのサブプロセス呼び出しに変更 → 追加課金ゼロ
場所: ~/Desktop/ClaudeProjects/AI-Brain/Projects/dmm-manga-affiliate/Workflows/queue-processor.py
作業: Claude Codeターミナルで「generate_content関数をclaudeコマンド経由に変更」

## 2. assembler.py実装
Notionのapprovedページを取得して以下を自動実行:
  1. テンプレ(DAHKogY0SBo)をコピーして新デザイン作成
  2. タイトル書き換え（ページ1・③行目）
  3. 漫画画像を各ページに差し込み（ズーム付き）
  4. テロップ8行を書き換え
  5. VOICEVOXでめたん(speaker=2)の音声生成
  6. Canva URLをNotionに記録
  7. タスク確認ボードに「👀 確認待ち」+ Canva URL登録

## 3. 本番フロー
Discord漫画投稿 → queue-processor → タスク確認ボードに台本届く
→ tagishi確認・approved → assembler → タスク確認ボードにCanva URL届く
→ tagishi確認・承認 → YouTube投稿

---

## 2026-06-10 セッション終了時の状態

### 完了したこと
- Canvaテンプレ確定（DAHKogY0SBo）
- テキスト書き換え・画像差し込み・コマズーム 動作確認済み
- Discord→Notion登録フロー 動作確認済み
- queue-processor.py（brain-worker経由）台本生成 動作確認済み
- assembler.py Canva動画組み立て 動作確認済み（6割完成度）
- VOICEVOX 0.25.2 インストール・起動確認済み

### 次回やること（優先順）
1. VOICEVOX音声生成をassembler.pyに組み込む
2. Discordのwebhook URL修正（403エラー）
3. Notion設計変更（handoff.mdに詳細記載済み）
4. 効果音3種類・アニメーション設計

### VOICEVOX
- バージョン: 0.25.2
- ポート: localhost:50021
- 起動方法: /Applications/VOICEVOX.app
- assembler.py実行時だけ起動すればOK
- デフォルトキャラ: 四国めたん（speaker=2）

---

## 2026-06-11 セッション途中状態

### 完了
- VOICEVOX→ffmpeg→catbox→Canva パイプライン実装済み
- Canvaサブプロセスを2回に分割（タイムアウト対策）push済み

### 次のアクション
- NotionをapprovedにしてからMacのターミナルで実行:
  cd ~/Desktop/ClaudeProjects/AI-Brain && git pull && source ~/.zshrc && source ~/.zprofile && python3 Projects/dmm-manga-affiliate/Workflows/assembler.py
- 音声付き動画がCanvaに差し込まれるか確認
- 確認できたらNotion設計変更に進む

### Discord webhook 403エラー
未修正。tokens.mdのURLが古い可能性あり。

---

## 2026-06-11 Canva subprocess → Claude Code直接操作に変更

### 完了
- 音声尺確認済み: WAV/MP4の差分が最大0.011秒（フレーム境界精度）→ 正常
- assembler.pyをリファクタリング（b4d4bde）:
  - 削除: invoke_claude / build_canva_prompt / run_canva_assembly 等
  - 追加: save_canva_job（canva_job.json出力）/ finalize_canva（後処理）

### 新しい実行手順（重要）

**ステップ1**: assembler.pyを実行（VOICEVOX起動必要）
```bash
source ~/.zshrc && source ~/.zprofile
python3 Projects/dmm-manga-affiliate/Workflows/assembler.py
# → CANVA_JOB_FILE=/path/to/canva_job.json が出力される
```

**ステップ2**: Claude CodeセッションでcanvaジョブJSONを読み、Canva MCPを直接操作
- canva_job.jsonにテンプレID・テロップ・音声URL・durations等がすべて入っている
- このセッションのCanva MCP（mcp__claude_ai_Canva__）を使って組み立て

**ステップ3**: Canva完了後にfinalizeを実行
```bash
python3 Projects/dmm-manga-affiliate/Workflows/assembler.py --finalize \
  --state-file=<canva_job.jsonのパス> \
  --design-id=<新しいdesign_id> \
  --canva-url=<CanvaのURL>
```
→ Notion更新・タスクボード登録・Discord通知・メディアファイル削除

### 通しテスト結果（2026-06-11）
✅ 新フロー全工程動作確認済み
- design_id: DAHMPmDAskw
- Canva編集URL: https://www.canva.com/d/Y5zwevqMNOw8SNZ
- Notion: canva_ready更新済み / タスク確認ボード登録済み
- ⚠️ Discord webhook 403エラー（tokens.mdのURL期限切れ）

### 次のアクション
1. Canvaで音声が実際に再生されるか確認（ミュート問題の検証）
2. Discord webhook URLを更新（tokens.mdを修正）
3. Notion設計変更（タスク確認ボード集約）

---

## 2026-06-11 音声問題の現状（未解決）

### 問題
Canvaに透明MP4（VOICEVOX音声入り）をinsert_fillで差し込むと音声が出ない。
opacity=0.01にしても出ない。透明度100%にしても出ない。
オーディオツールで音声抽出すると聞こえる→音声データは正常に入っている。

### 試したこと
- insert_fill + opacity=0 → 音声なし
- insert_fill + opacity=0.01 → 音声なし
- WAV直接アップロード → Canva MCP非対応
- MP3直接アップロード → Canva MCP非対応

### 未調査（次のチャットで必ずやること）
- insert_fillで差し込んだ動画がなぜCanvaでミュート扱いになるのか根本原因を調査
- ffmpegで生成したMP4の形式・コーデックが問題の可能性（AAC/H.264の設定）
- Canvaが動画をミュートで読み込む条件を調査（自動再生ポリシー等）
- 解決策を見つけるまで諦めない

### 現在の自動化の完成度
✅ 台本生成（brain-worker）
✅ テロップ書き換え
✅ 画像差し込み・コマズーム
✅ 透明MP4差し込み（音声は出ていない状態）
✅ Notion更新・タスク確認ボード登録
⚠️ Discord webhook 403（tokens.md更新が必要）
❌ 音声再生（未解決）
❌ ページ表示時間の自動調整（Canva MCP非対応）

### 次のチャットの最初にやること
1. insert_fillで差し込んだ動画がミュートになる原因をネットで徹底調査
2. 原因を特定してffmpegのMP4生成設定を修正
3. 解決できたらDiscord webhook修正
4. その後Notion設計変更
