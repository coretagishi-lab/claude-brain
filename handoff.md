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
