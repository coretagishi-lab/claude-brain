---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-18
---

# ⚠️ 最重要ルール（毎回必ず読む）

## コスト判断基準
- APIコスト不要な作業（SSH/curl/git/Notion API）→ Claude.ai から直接指示
- APIコスト発生する作業（台本生成/画像解析）→ Claude Code（サブスク内・追加課金ゼロ）

## 作業ルール
- **1指示1修正**: 「これだけ直して」と言われたら他を触らない
- **動いてるものは変えない**: 変更前に必ず説明・確認する
- **コード差分は非表示**: 結果だけ会話文で簡潔に伝える
- **SPEC.md が最優先**: コードやセッションログよりSPEC.mdが正しい

## 絶対禁止
- Anthropic APIを直接HTTPリクエストで叩くスクリプトをサイレントで実装
- コスト発生の可能性がある実装を事前確認なしに追加

---

# ⚡ セッション開始直後に必ずやること

## 1. CronCreate でVPS自動検知を再登録（毎セッション必須）
セッションが閉じると消えるため毎回再登録が必要。

```
/loop 2m VPSタスクチェック＆自動実行（バックグラウンド・無言動作）:
python3 /Users/tagishitakuya/Desktop/ClaudeProjects/AI-Brain/Shared/Workflows/vps-task-checker.py を実行。
タスクがあれば CLAUDE.md の即実行ルールに従って処理する（assembler実行待ち→assembler.py+Canva MCP、ffmpeg動画生成待ち→video-generator.py+Canva PNG書き出し+assemble、youtube投稿待ち→youtube-uploader.py、動画やり直し待ち→video-generator.py再実行）。
その後 python3 /Users/tagishitakuya/Desktop/ClaudeProjects/AI-Brain/Projects/dmm-manga-affiliate/Workflows/youtube-uploader.py --check-pending を実行。
タスクがない・pendingコメントがない場合は何も出力しない。タスクを処理した場合のみ結果を報告する。
```

## 2. 自動保存Cronも登録（20分ごと）
```
/loop 20m セッション状態の自動保存（20分ごと）:
以下を実行してhandoff.mdとPROJECT_STATUS.mdを最新状態に保ち、git pushする。
1. このセッションで完了したことがあれば handoff.md の「テスト済み案件」と必要な箇所を更新する
2. Projects/dmm-manga-affiliate/PROJECT_STATUS.md の updated_at を今日の日付に更新する
3. git add -A && git commit -m "auto: セッション状態保存 $(date '+%Y-%m-%d %H:%M')" && git push
4. 何も変更がなければ何も出力しない（git commit が「nothing to commit」なら終了）
```
→ コンテキストが突然100%になっても handoff.md は常に最新状態を保つ

## 3. /tmp/ai-brain/ の確認
```bash
ls /tmp/ai-brain/*/canva_job.json 2>/dev/null
```
design_id が null のものがあれば → Canva MCP 作業待ち

---

# システム構成

## 三層アーキテクチャ
```
Claude.ai（戦略・指示）
  ↓
Mac Claude Code（判断・生成）← サブスクリプション・追加課金ゼロ
  ↓
ConoHa VPS 133.88.117.175（実行・APIゼロ）
```

## VPS
- SSH: `ssh -i ~/.ssh/conoha_vps root@133.88.117.175`
- パス: `/opt/ai-brain/`

## Discord
- `#dmm-素材投稿`: 1511211307788144650
- `#inbox`: 1511214415611953214
- `#通知`: 1511214417990254664

---

# 自動化の現状（2026-06-18 確定）

| ステップ | 自動化 | トリガー |
|---|---|---|
| Discord → Notion登録 | ✅ 常時（PC不要） | VPS dmm-discord-watcher |
| 台本確認済み → catbox + canva_job.json | ✅ 常時（PC不要） | launchd ai_brain_daemon.py |
| Canva MCP（テロップ・画像差し替え） | ⚠️ セッション中のみ | assembler.py + Canva MCP |
| ffmpeg動画生成 | ⚠️ セッション中のみ | video-generator.py |
| YouTube投稿（2本/日・2時間間隔） | ⚠️ セッション中のみ | CronCreate経由 |
| 公開後コメント投稿 | ⚠️ セッション中のみ | CronCreate --check-pending |

### TCC制限（macOS 15 Sequoia）
- launchd は ~/Desktop にアクセス不可
- /tmp・/usr/local/bin・~/Library はアクセス可能
- youtube-uploader.py・video-generator.py は Desktop を使うためセッション必須

---

# 全体フロー（最新版）

```
① Discordに漫画画像 + タイトル + X URL を投稿
   ↓ VPS自動（常時）
② Notionに①②2件登録・カレンダーに予約済み登録

③ Claude Codeが台本生成（queue-processor.py）
   → [台本確認] タスク登録 → Discord通知
   ↓ tagishi確認・✅
   ↓ VPS自動（30秒）
④ approved に更新 → ai_brain_daemon がcatboxアップ + canva_job.json 作成

⑤ Claude Code が assembler.py 実行（Canva MCP）
   → テロップ・画像差し替え → [Canva確認] タスク登録
   ↓ tagishi確認・画像トリミング調整・✅
   ↓ VPS自動（30秒）
⑥ Outboxに「ffmpeg動画生成待ち」登録

⑦ Claude Code が video-generator.py 実行
   Step 1: VOICEVOX音声生成 → video_job.json
   Step 2: Canva MCP で PNG書き出し（page1〜10.png）
   Step 3: ffmpeg組み立て → 完成MP4
   → [動画確認] タスク登録
   ↓ tagishi確認・✅
   ↓ VPS自動（30秒）
⑧ Outboxに「youtube投稿待ち」登録

⑨ CronCreate が youtube-uploader.py 実行
   - 1日2本・2時間間隔の制限チェック
   - タイトルは「続きはコメ欄⬇️【漫画タイトル】 #漫画 #Shorts」（①②なし）
   - publish_at が未来 → 予約投稿・コメントは pending 保存
   - publish_at が過去 → 即公開・コメント即投稿
   - サムネイルはpage1.png（アップ後10秒待機してから設定）
   - Notion・カレンダー自動更新
   ↓ 公開時刻になったらYouTubeが自動公開
⑩ CronCreate --check-pending が公開を検知
   → コメント投稿 → カレンダーを「公開済み」に更新
```

---

# YouTube投稿ルール（確定）

- **1日上限**: 2本/アカウント
- **アップロード間隔**: 最低2時間
- **制限に達したら**: VPSタスクを保持したまま翌日以降に自動再試行
- **記録ファイル**: `~/.config/dmm-youtube/upload_history.json`
- **コメント**: 予約投稿は公開後に自動投稿（`~/.config/dmm-youtube/pending_comments.json`）

---

# Canva仕様（確定・変更禁止）

## テンプレート
- ID: `DAHMbaP-OTo`（アカウント①・10ページ・クリーン版）
- 新規案件は必ず copy-design してから使う
- ~~DAHKogY0SBo~~ → 廃棄済み

## element_id（固定値）
```
ページ1タイトル（3行目）: PBs1sTlCLqHDSG14-LBLZdZrCsRfxzhFk
ページ1カバー画像:         PBs1sTlCLqHDSG14-LBsPl21hPyJcffJx
ページ10カバー画像:        PBQRTjML4Gm5msr7-LBB8BKH3dpcWzwx8
テロップ①〜⑧:            assembler.py TELOP_ELEM_IDS 参照
画像スロット①〜⑧:        assembler.py IMAGE_SLOT_IDS 参照
```

## タイトル要素の特定方法
copy-design後に start-editing-transaction → page1テキストをtop座標昇順ソート → 3番目

## ⚠️ Canvaタイトルに①②は含めない
正規表現で除去: `re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩]$', '', manga_title).strip()`

---

# Notion DB

| DB | ID |
|---|---|
| コンテンツ審査DB | 3731cad4aa98810e82f8c0f99a483cbb |
| タスク確認ボード | 3671cad4aa98813b85b2ed9e3127b913 |
| VPS Outbox | 36f1cad4-aa98-81fb-93d8-d40bfb95cff9 |
| 投稿カレンダー | 3831cad4-aa98-81c2-9c66-e7f9ee3597e9 |

ステータス遷移: `queued → draft → approved → canva_ready → video_ready → uploaded`

---

# VOICEVOX設定（確定・変更禁止）

- URL: http://localhost:50021
- ♀: speaker=47（ナースロボ＿タイプT ノーマル）
- ♂: speaker=13（青山龍星 ノーマル）
- イントロ/アウトロ: 女性固定
- テロップ先頭の♂♀マーカーで自動切り替え
- 丸数字(①〜⑩)は読み上げ前に除去

---

# 動画構成（確定・変更禁止）

- **ハードカット**: 音声が終わった瞬間に次のスライド（crossfade/xfade 絶対禁止）
- **スライド長さ = 音声WAV長さ**（TRANSITION加算禁止）
- page1=イントロ, page2-9=コンテンツ①-⑧, page10=アウトロ
- BGM音量: 0.07（ボイスの7%）
- SE音量: 0.5（イントロは決定ボタン固定、コンテンツはランダム）

---

# 動画素材パス

| ファイル | パス |
|---|---|
| BGM | `Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/アカウント①BGM.mp3` |
| 効果音 | `Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/効果音/` |
| 背景動画 | `Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/アカウント①背景動画.mp4` |

---

# テスト済み案件

| タイトル | YouTube URL | 予約日時 |
|---|---|---|
| 幼馴染と | （テスト用・未投稿） | — |
| あの幼馴染との | （テスト用） | — |
| フレンドとの① | https://youtube.com/shorts/2x1EHyACH78 | 2026-06-18 21:24 |
| フレンドとの② | https://youtube.com/shorts/W7LLnwcsJHs | 2026-06-26 08:27 |

---

# 既知の問題・制限

| 問題 | 状況 |
|---|---|
| Discord webhook 403 | tokens.mdのURL期限切れ。tagishi手動更新要 |
| サムネイル設定失敗（403） | チャンネル未認証の可能性。10秒待機で改善試み中（次回投稿で確認） |
| launchd から Desktop アクセス不可 | TCC制限。youtube-uploader/video-generator はセッション必須 |
