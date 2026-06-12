---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-12
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

## 作業ルール（確定）
- **1指示1修正**: 「これだけ直して」と言われたら他を触らない
- **動いてるものは変えない**: 別の改善アイデアが浮かんでも、指示された修正だけ行う

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
テンプレートID: DAHKogY0SBo（②ナレーション・10ページ）
※ 新規案件はこのテンプレから copy-design して使う

### 最新テスト案件
「幼馴染と」 design_id: DAHMVZDWKgs
編集URL: https://www.canva.com/d/pmLab5K78AhfnbJ
※ この案件はこのデザインのまま完成させる

## ページ構成
  ページ1:  導入（③行目のみ漫画タイトルに書き換え）
  ページ2〜9: コマ画像（ズーム済み）+ テロップ1行
  ページ10: エンド固定

## element_id（テンプレート固定値）
  ページ1カバー画像:     PBs1sTlCLqHDSG14-LBW9GpN7ycfQ2ptS
  ページ10カバー画像:    PBQRTjML4Gm5msr7-LBB8BKH3dpcWzwx8
  テロップ①: PBG3BLhBZW05Kb0W-LBhlvQNP9s6Wmwvr
  テロップ②: PBCSwpnm9S6QVHtJ-LBff234VHn89xWtW
  テロップ③: PBjDNccpBqWtybYQ-LBxsBSg503sFyjyQ
  テロップ④: PBvxHVxQT8c46KWb-LBHJq4nGtPjjtjnV
  テロップ⑤: PBw7ntJLPN1YXxv3-LB7D7v0gRPY16KGC
  テロップ⑥: PBwNd5vms7mw2gXb-LBg46mQW7DYvYrS2
  テロップ⑦: PBkLftpwjtcRJDvs-LB2Dj8TSWKB0CnvR
  テロップ⑧: PBpYZmnGCfCLdFFC-LBzvFjt040LjCkN6
  画像スロット(p2-p9): IMAGE_SLOT_IDS（assembler.py参照）

## タイトル行の動的取得（確定方式）
  copy-design後に get-design-content または start-editing-transaction で
  ページ1のテキスト要素を top 座標昇順ソートし、
  title_line_from_top 番目（デフォルト3）の element_id を使う。
  → canva_job.json の manga_title_elem_id フィールドに書き込む

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

# 漫画アフィリエイトの虎の巻（フロー仕様書・確定）

## 全体フロー

1. **tagishiが漫画画像をDiscordに投稿**
   画像（何枚でもOK）＋タイトル＋アフィリエイトURLを貼る

2. **VPSが自動でNotionに記録**
   30秒ごとに監視。投稿があったらコンテンツ審査DBに「未処理」として登録

3. **Macが台本（テロップ）を作る**
   Macが起動していれば、画像を見て8行のテロップ①〜⑧を自動生成。
   タスク確認ボードに「[台本確認]」として出てくる

4. **tagishiが台本を確認**
   - そのままOK → 「完了」にチェック
   - 直したい → 「やり直し指示」に修正台本を書いて「完了」にチェック

5. **Macが動画を組み立てる**（assembler.py + Claude Code Canva MCP）
   - テンプレ（DAHKogY0SBo）をコピーして新しいデザインを作成
   - テロップをVOICEVOXで音声化 → ffmpegで動画化 → catbox.moeにアップ
   - 各ページにテロップ・コマ画像（ズーム）を差し込む
   - ページ1のタイトル行（3行目・動的取得）を書き換える
   - ページ1・10のカバー画像スロットに漫画画像を差し込む
   - タスク確認ボードに「[Canva確認]」として出てくる

6. **tagishiがCanvaで最終確認・音声処理**
   Canvaを開いて、動画の透明化・長さ調整・最終チェック。OKなら「完了」にチェック。
   ※ 音声のCanva自動差し込みは断念。手動対応。

7. **（将来）YouTubeに自動投稿**
   今はまだ未実装。完了チェックが入ったら自動でYouTubeに上がるようにする予定。

---

# 現在の自動化の完成度

✅ 台本生成（queue-processor.py / brain-worker経由）
✅ テロップ書き換え（8行）
✅ 画像差し込み・コマズーム（update_fill + resize + position）
✅ タイトル行動的取得（top昇順ソート・3行目）
✅ ページ1・10のカバー画像差し込み（page1_cover_slot_id / end_page_cover_slot_id）
✅ Notion更新・タスク確認ボード登録
✅ Discord webhook（VPS・Mac両方確認済み）
✅ --dry オプション（queue-processor.py・assembler.py両方対応済み）
✅ やり直し指示の優先使用（タスクボードのやり直し指示欄 → script上書き）
⚠️ 音声: Canvaで手動対応（自動化対象外）
❌ ページ表示時間の自動調整（Canva MCP非対応・対応予定なし）

---

# 未解決・次回すり合わせ事項

1. **各ページへの音声動画クリップ挿入方法**（次回tagishiとすり合わせ）
   catboxにアップしたMP4をCanvaに差し込む方法が未確定
2. **Discord webhook 403**（tokens.mdのURL期限切れ・tagishi手動更新要）
3. **複数画像対応**（現在1枚のみ。複数コマ画像の扱い未設計）
4. **VOICEVOX/VPS移行**（現在Macで実行・VPSヘッドレスインストール未実施）

---

# 次のチャットでやること

### 優先: 音声動画クリップ挿入の方針決め
tagishiと「各ページのMP4をどうCanvaに入れるか」をすり合わせてから実装

### その後: 通しテスト2本目
1. Discordの #dmm-素材投稿 に別の漫画画像を投稿
2. Notionに登録されたことを確認（status: queued）
3. `python3 Projects/dmm-manga-affiliate/Workflows/queue-processor.py` で台本生成
4. タスク確認ボードで台本を確認・「✅ 確認済み」に変更
5. `python3 Projects/dmm-manga-affiliate/Workflows/assembler.py` でCanvaジョブ出力
6. Canva MCP でテンプレ組み立て（新規コピーから）→ 音声は手動で追加
7. `python3 assembler.py --finalize ...` でNotion・タスクボード更新

---

## 2026-06-12 本日の作業まとめ

### 完了した修正
1. **canva-instructions.pyのlaunchd競合を停止**
2. **テンプレコピー方式 + タイトル3行目動的取得を実装・動作確認**
   - copy-design(DAHKogY0SBo) → start-editing-transaction → top昇順ソート3番目
   - manga_title_elem_idをcanva_job.jsonに記録
3. **comic_frames（コマズーム）通しテスト動作確認**
   - update_fill + resize_element + position_elementで正常動作
4. **ページ1・10のカバー画像挿入を修正**
   - page1_cover_slot_id（PBs1sTlCLqHDSG14-LBW9GpN7ycfQ2ptS）をassembler.pyに追加
   - canva_job.jsonにも出力するよう追加
5. **「漫画アフィリエイトの虎の巻」を仕様書として確定**
6. **作業ルール（1指示1修正・動いてるものは変えない）を確定**

### 通しテスト結果（2026-06-12）
✅ 新フロー全工程動作確認済み
- design_id: DAHMVZDWKgs
- Canva編集URL: https://www.canva.com/d/pmLab5K78AhfnbJ
- Notion: canva_ready更新済み / タスク確認ボード登録済み
- ⚠️ Discord webhook 403エラー（tokens.mdのURL期限切れ・既知問題）
