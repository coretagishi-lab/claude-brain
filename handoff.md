---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-18
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

## 作業ルール（確定）
- **1指示1修正**: 「これだけ直して」と言われたら他を触らない
- **動いてるものは変えない**: 指示された修正だけ行う
- **コード差分は非表示**: 結果だけ会話文で簡潔に伝える

---

# システム構成

## 三層アーキテクチャ
Claude.ai（戦略・指示）
  ↓
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

## Canvaテンプレート（確定）
テンプレートID: DAHMbaP-OTo（アカウント①テンプレ・10ページ・クリーン版）
※ 新規案件はこのテンプレから copy-design して使う
※ 旧テンプレ DAHKogY0SBo は直接編集してしまったため廃棄

## ページ構成
  ページ1:  導入（③行目のみ漫画タイトルに書き換え）
  ページ2〜9: コマ画像 + テロップ1行
  ページ10: エンド固定

## element_id（テンプレート固定値）
  ページ1カバー画像:     PBs1sTlCLqHDSG14-LBW9GpN7ycfQ2ptS
  ページ10カバー画像:    PBQRTjML4Gm5msr7-LBB8BKH3dpcWzwx8
  タイトル（3行目）:     PBs1sTlCLqHDSG14-LBLZdZrCsRfxzhFk
  テロップ①: PBG3BLhBZW05Kb0W-LBXt7PvjSgmS6B4V  ← 新テンプレで変更
  テロップ②: PBCSwpnm9S6QVHtJ-LBff234VHn89xWtW
  テロップ③: PBjDNccpBqWtybYQ-LBxsBSg503sFyjyQ
  テロップ④: PBvxHVxQT8c46KWb-LBHJq4nGtPjjtjnV
  テロップ⑤: PBw7ntJLPN1YXxv3-LB7D7v0gRPY16KGC
  テロップ⑥: PBwNd5vms7mw2gXb-LBg46mQW7DYvYrS2
  テロップ⑦: PBkLftpwjtcRJDvs-LB2Dj8TSWKB0CnvR
  テロップ⑧: PBpYZmnGCfCLdFFC-LBzvFjt040LjCkN6
  画像スロット①: PBG3BLhBZW05Kb0W-LBVhh0TMry1xf5t2  ← 新テンプレで変更
  画像スロット②〜⑧: assembler.py の IMAGE_SLOT_IDS 参照

## タイトル行の動的取得（確定方式）
  copy-design後に start-editing-transaction でページ1テキストを取得
  top座標昇順ソートの3番目の element_id を manga_title として使う

## Notion DB
コンテンツ審査DB: 3731cad4aa98810e82f8c0f99a483cbb
タスク確認ボード: 3671cad4aa98813b85b2ed9e3127b913
ステータス: 👀 確認待ち / 🔄 作成中 / ✅ 確認済み

## image_urlプロパティ
Notionのimage_urlはrich_text型（複数URLをスペース区切りで保存）

---

# 確定した全体フロー（3段階確認）

```
1. tagishiがDiscordに漫画画像（複数可）+ タイトル + XのURLを投稿
        ↓ VPS(dmm-discord-watcher) 自動
2. NotionコンテンツDBに「未処理」で登録

3. Mac Claude Codeが台本生成（queue-processor.py）
   - 複数画像を全部読んで8行テロップ作成
   - ♂♀マーカーで男女セリフを分類（掛け合いシーン）
   - タスク確認ボードに「[台本確認]」登録
   - Discordに「台本確認してね」通知を送る
        ↓ tagishi確認
4. tagishiが「✅ 確認済み」にチェック
   やり直し指示があればそちらの台本を使う
        ↓ VPS(dmm-notion-watcher) 30秒以内に検知
5. コンテンツDBをapprovedに更新 → Outboxにタスク登録

6. Mac Claude Codeがassembler.pyを実行
   - VOICEVOX音声生成（♂=青山龍星13、♀=ナースロボ47）
   - 音声頭の丸数字(①②)と♂♀マーカーを除去してから読み上げ
   - ffmpeg WAV→MP4 → catboxアップ
   - Canvaテンプレコピー → タイトル・テロップ・画像差し込み
   - タスク確認ボードに「[Canva確認]」登録
        ↓ tagishi確認（画像トリミング位置の手動調整）
7. tagishiが「✅ 確認済み」にチェック
        ↓ VPS(dmm-notion-watcher) 30秒以内に検知
8. Outboxに「ffmpeg動画生成待ち」タスク登録

9. Mac Claude Codeがffmpegで動画生成
   - Canvaから各ページPNG書き出し
   - 背景動画（ループ）+ PNG + VOICEVOX音声 = 最終MP4
   - タスク確認ボードに「[動画確認]」登録
        ↓ tagishi確認
10. tagishiが「✅ 確認済み」にチェック
    やり直し指示があれば音声・タイミング修正して再生成

11. YouTube Shorts投稿（youtube-uploader.py）
    - 概要欄とコメント欄にXの投稿URLを含めて投稿
```

---

# VOICEVOX設定（確定）
- ポート: localhost:50021
- バージョン: 0.25.2
- ♀デフォルト: speaker=47（ナースロボ＿タイプT ノーマル）
- ♂: speaker=13（青山龍星 ノーマル）
- 台本の行頭に♂/♀マーカーで自動切り替え
- 丸数字(①〜⑩)は音声生成前に除去

---

# 背景動画
パス: /Users/tagishitakuya/Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/アカウント①背景動画.mp4
尺: 20秒（不足時ループ）

---

# VPSスクリプト（稼働中）
| スクリプト | 役割 |
|---|---|
| dmm-discord-watcher.py | Discord投稿を監視→Notion登録 |
| dmm-notion-watcher.py | [台本確認][Canva確認]の✅を30秒監視→Outbox登録 |

---

# 次フェーズ実装ロードマップ

## Phase 2: X連携 + 概要欄・コメント自動化

### ① YouTube概要欄・コメント欄の自動更新（優先）
- YouTubeのOAuthスコープを `youtube.upload` → `youtube` に変更（--authもう1回）
- youtube-uploader.py に `--update-description` `--add-comment` オプション追加
- 投稿後にアフィURL（短縮）を概要欄とコメント欄に自動セット

### ② X自動投稿 + アフィURL短縮
- developer.twitter.comでApp作成（API Key / Access Token）
- x-poster.py 新規作成
  - TinyURLでアフィURLを短縮（登録不要・無料）
  - Xに投稿: 「{タイトル} 続きはこちら → {短縮URL} #漫画 #Shorts\n{youtube_url}」
  - ポストURLを取得 → YouTubeの概要欄・コメント欄に追記

### ③ Discord投稿時の公開時刻指定（±20分ランダム）
- Discord投稿フォーマット:
  「{タイトル} {日付} {時刻}」例: 「あの幼馴染との 明日20:00」
  ※ 時刻省略時 → 即時処理
- VPS(dmm-discord-watcher.py)が時刻を解析してNotionに publish_at を保存
- publish_at ± ランダム(0〜20分) で実際の公開時刻を決定
- youtube-uploader.py: `scheduledPublishTime` で予約投稿（YouTubeが自動公開）
- x-poster.py: VPSのcronが publish_at の時刻に実行（予約X投稿）

## 完成後の完全フロー
```
Discord: 「あの幼馴染との 明日20:00」+ 漫画画像
↓ VPS自動
Notion登録（publish_at = 明日 20:00±20分）
↓ Claude Code（セッション開始時に自動検知）
動画生成 → YouTube予約投稿
         X投稿（VPS cronが publish_at に実行）
         概要欄・コメント欄にアフィURL + XのURL を自動追記
```

---

# 未解決・次回課題

1. **透過PNG問題**（最優先）
   CanvaのAPIで透過PNG書き出しが無料プラン制限。
   UIからの手動書き出しか、有料プランのAPI利用か検討。
   現状: 通常PNGで代替（Canvaデザインがそのまま全面に出る）

2. **[Canva確認]後のffmpeg自動実行** ✅ 実装済み（2026-06-16）
   `video-generator.py` で対応。セッション開始時にVPSタスク検知→実行。
   使い方: セッション開始 → VPSタスク確認 → video-generator.py 実行

3. **[動画確認]フロー**
   完成動画のレビュー → やり直し指示（音声・タイミング修正）→ 再生成

4. **YouTube自動投稿**
   将来実装。

---

# video-generator.py（2026-06-16 追加）

## 実行手順（セッション開始時VPSタスクに「ffmpeg動画生成待ち」が来た場合）

```bash
# Step 1: VPSタスク検知 → VOICEVOX音声生成 → job JSON出力
python3 Projects/dmm-manga-affiliate/Workflows/video-generator.py

# Step 2: Claude CodeがCanva MCPで各ページをPNG書き出し
#   export-design(design_id) → page1.png〜page10.png を canva_pages_dir に保存

# Step 3: ffmpeg組み立て
python3 Projects/dmm-manga-affiliate/Workflows/video-generator.py \
    --assemble --job-file <VIDEO_JOB_FILEのパス>
```

## 動画素材ファイル配置
| ファイル | パス | 備考 |
|---|---|---|
| BGM | `漫画アフィリエイト:動画素材/アカウント①BGM.mp3` | tagishi提供・未配置でスキップ |
| ページめくりSE | `漫画アフィリエイト:動画素材/SE/page-turn.mp3` | tagishi提供・未配置でスキップ |
| 背景動画 | `漫画アフィリエイト:動画素材/アカウント①背景動画.mp4` | ✅ 配置済み |

## 動画構成（確定・変更禁止）
- 画像: 完全静止（Ken Burns / crossfade / アニメ 全て廃止）
- スライド切り替え: ハードカット（音声が終わったら即次へ）← 同期の要、絶対に変えない
- 音声: VOICEVOX ♂/♀ 自動切り替え（テロップ先頭の♂♀マーカーで判定）
- イントロ(page1): youtube_title or manga_title を女性ボイスで読み上げ
- アウトロ(page10): 「続きはプロフィールのリンクから読めます」を女性ボイスで読み上げ
- BGMミックス: ボイスに対して0.15の音量（BGM_PATHにファイルを置くだけで自動ON）
- SEなし（page-turn.mp3を置いても今は未使用）

## ⚠️ 絶対に変えてはいけないもの
- ハードカット方式（`concat_videos`関数のffmpeg concatデモ方式）
- 各スライドの長さ = 音声WAVの長さ（TRANSITION加算禁止）
- スライド順序とpage番号の対応（page1=イントロ, page2-9=コンテンツ①-⑧, page10=アウトロ）

---

# セッション開始時の追加チェック（重要）

## /tmp/ai-brain/ の pending canva_job 確認

launchd デーモン（ai_brain_daemon.py）がタスクの台本確認済み後に
自動でVOICEVOX音声生成・catboxアップロードまで行い canva_job.json を
/tmp/ai-brain/{date}_{title}/ に保存する。

セッション開始時に必ずチェック:
```bash
ls /tmp/ai-brain/*/canva_job.json 2>/dev/null
```

見つかった場合 → design_id が null のものが Canva 作業待ち
→ そのまま Canva MCP 操作を実行（copy-design → edit → finalize）
→ finalize 時は state-file に /tmp のパスを渡す:
```bash
python3 Projects/dmm-manga-affiliate/Workflows/assembler.py \
    --finalize \
    --state-file=/tmp/ai-brain/{date_title}/canva_job.json \
    --design-id=DAHMXXXX \
    --canva-url=https://www.canva.com/d/...
```

## 自動化の現状（2026-06-18 確定）

| ステップ | 自動化 | 方法 |
|---|---|---|
| Discord → Notion登録 | ✅ 常時 | VPS dmm-discord-watcher |
| 台本生成 | ❌ 手動 | queue-processor.py（Desktop TCC制限のため） |
| VOICEVOX音声・catbox | ✅ 2分以内 | launchd ai_brain_daemon.py（/usr/local/bin/） |
| Canva MCP | ❌ 手動 | Claude Codeセッション必要 |
| 動画生成 | ❌ 手動 | video-generator.py |
| YouTube投稿 | ❌ 手動 | youtube-uploader.py |

## TCC制限メモ（macOS 15 Sequoia）
- launchd エージェントは ~/Desktop にアクセス不可（Operation not permitted）
- /tmp / /usr/local/bin / ~/Library は制限なし
- ai_brain_daemon.py はすべて HTTP と /tmp のみ使用 → 問題なし
- queue-processor.py は experience.md（Desktop）を読むため手動のまま

---

# テスト済み案件
- 「幼馴染と」 design_id: DAHMVZDWKgs（テスト用・完成済み）
- 「あの幼馴染との」 design_id: DAHMWHY0X-8
  動画: /Users/tagishitakuya/Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/あの幼馴染との_完成.mp4
  ※ 透過なし・通常PNGで生成したテスト版（100点版は未実行）

---

# Discord webhook 403
tokens.mdのURL期限切れ。tagishi手動更新要。
