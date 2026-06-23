---
type: spec
title: DMMマンガアフィリエイト 仕様書（単一の真実のソース）
updated: 2026-06-18
version: 1.1
---

# ⚠️ このファイルの使い方

**このファイルはこのビジネスの憲法。**

## Claude への強制ルール
- `dmm-manga-affiliate/` 配下のファイルを**変更する前に必ずこのファイルを読む**
- ここに書かれた内容と矛盾する実装をしてはいけない
- ここに書かれた値を変更する場合は**必ずtagishiに確認してからにする**
- 「前の実装がこうなってた」「コードにこう書いてあった」はこのファイルより優先されない
- 不明な点があれば実装前に質問する

---

# 1. ビジネス全体フロー

```
【tagishiがやること】
① Discordの #dmm-素材投稿 に投稿
   内容: 漫画画像（複数可）+ タイトル + XのURL（投稿URL）

【VPS自動】
② dmm-discord-watcher.py が検知
   → Notionコンテンツ審査DB に status:queued で登録

【Claude Code（手動 or launchd）】
③ queue-processor.py を実行
   → 画像を読んで8行テロップ台本を生成
   → Notionに status:draft で保存
   → タスク確認ボードに「[台本確認]」登録
   → Discordに通知（tagishiへ確認依頼）

【tagishiがやること】
④ Notionでテロップ確認 → ✅ 確認済み にチェック
   ※ 修正がある場合は「やり直し指示」欄に正しい台本を書く → そちらを採用

【VPS自動】
⑤ dmm-notion-watcher.py が検知
   → status を queued → approved に更新

【Claude Code（手動 or launchd ai_brain_daemon.py）】
⑥ assembler.py を実行
   → 漫画画像をDiscord CDNからダウンロード → catbox.moeに公開URLで再アップ
   → Canvaテンプレ(DAHMbaP-OTo)をコピー
   → タイトル差し替え + テロップ8行差し替え + 画像差し替え（10P）
   ※ VOICEVOX・音声・動画はここでは一切使わない
   → タスク確認ボードに「[Canva確認]」登録

【tagishiがやること】
⑦ Canvaを開いて画像のトリミング位置を手動調整
   → Notionで ✅ 確認済み にチェック

【VPS自動】
⑧ dmm-notion-watcher.py が検知
   → VPS Outboxに「ffmpeg動画生成待ち」タスクを登録

【Claude Code（手動）】
⑨ video-generator.py を実行（Step 1）
   → VPSタスクからページIDを取得
   → VOICEVOXで全テロップ + イントロ + アウトロ の音声を生成
   → video_job.json を出力

⑩ Claude Code が Canva MCP で各ページをPNGとして書き出し
   → page1.png 〜 page10.png を canva_pages_dir/ に保存

⑪ video-generator.py --assemble を実行（Step 3）
   → PNG10枚 + VOICEVOX音声 + 効果音 + BGM → 最終MP4
   → catbox.moeにアップロード
   → Notionに status:video_ready で登録
   → タスク確認ボードに「[動画確認]」登録

【tagishiがやること】
⑫ 動画を確認 → ✅ 確認済み

【Claude Code（手動）】
⑬ youtube-uploader.py を実行
   → YouTube Shortsに即公開で投稿（Notionで動画確認済みのため）
   → サムネイルを page1.png（Canvaの1枚目）に自動設定
   → 概要欄に XのURL を追記
   → コメントは投稿直後に投稿（x_url付き）
   ※ 予約投稿: Notionの publish_at を読んで自動で scheduledPublishTime をセット（実装済み）
```

---

# 2. Notionステータス遷移

```
queued → draft → approved → canva_ready → video_ready → uploaded
  ↑         ↑        ↑            ↑              ↑           ↑
VPS      Claude    tagishi      Claude        Claude      Claude
Bot      Code       確認         Code          Code        Code
```

**Notion DB ID:**
- コンテンツ審査DB: `3731cad4aa98810e82f8c0f99a483cbb`
- タスク確認ボード: `3671cad4aa98813b85b2ed9e3127b913`
- VPS Outbox DB: `36f1cad4-aa98-81fb-93d8-d40bfb95cff9`
- **投稿カレンダー: `3831cad4-aa98-81c2-9c66-e7f9ee3597e9`**（タスク確認ボードと同階層）

**投稿カレンダーのプロパティ:**
- 動画タイトル（タイトル）
- アカウント（セレクト: アカウント①〜④）
- 公開日時（日付）← カレンダービューの軸
- ステータス（セレクト: 予約済み / 公開済み / キャンセル）
- YouTube URL
- X URL
- 漫画タイトル

**運用ルール【確定・変更禁止】:**
- Discord投稿1回で**バリエーション①②の2本**が自動生成される
  - `女上司と` → `女上司と①`（今週の枠）+ `女上司と②`（7日後の枠）
- 8:00 / 21:00 の空き枠を自動探索 → ±15〜30分ランダムずらし
- tagishiは時刻指定不要。カレンダーを見れば空き状況が一目瞭然
- X URLは①②**両方とも同じDiscord投稿のURL**を使う（ずれない設計）
- YouTube投稿後に「予約済み」→「公開済み」に自動更新

---

# 3. Canva仕様【変更禁止】

## Canva作業でやること（assembler.py）
1. **page1カバー画像**: 漫画画像から最も目を引くコマを1枚選んで差し込む
2. **page2〜9**: 各テロップの内容に合ったコマを選んで差し込む（画像とテロップが対応するように）
3. **page10**: エンド固定 → 変更しない
4. tagishiが⑥でCanvaを開いて画像のトリミング（見せたい部分）を手動調整する

**画像の選び方のルール:**
- テロップ①の内容に合う場面 → page2に配置
- テロップ②の内容に合う場面 → page3に配置 … 以下同様
- 1枚の画像を複数ページに使い回してもOK

---

## テンプレート
- **使用テンプレ: `DAHMbaP-OTo`（アカウント①・クリーン版）**
- ~~DAHKogY0SBo~~ → 廃棄（直接編集してしまったため使用禁止）
- 新規案件は必ずこのテンプレを `copy-design` してから使う

## ページ構成
| ページ | 内容 |
|---|---|
| page 1 | 導入カバー（タイトル + 漫画画像） |
| page 2〜9 | コンテンツ（テロップ1行 + 漫画画像） |
| page 10 | エンド固定（変更不可） |

## Element ID（確定・変更禁止）

**ページ1 テキスト要素（top座標昇順）:**
```
1位(top≈71)   : PBs1sTlCLqHDSG14-LBLkqYq8c9F9Vz1L  「秒で」（固定）
2位(top≈246)  : PBs1sTlCLqHDSG14-LBJcqsXQPp6DsRGK  「出しちゃった」（固定）
3位(top≈426)  : PBs1sTlCLqHDSG14-LBLZdZrCsRfxzhFk  ← 漫画タイトル書き換え先
4位(top≈601)  : PBs1sTlCLqHDSG14-LBrqdhnZYLPRPyJX  「男の漫画」（固定）
```
> **タイトル要素の特定方法**: copy-design後にstart-editing-transactionを実行し、page1のテキスト要素をtop座標昇順ソートして3番目のelement_idを使う

> ⚠️ **①②③などのバリエーション番号はCanvaタイトルに含めない**
> Notionのmanga_titleが「フレンドとの①」でも、Canvaには「フレンドとの」だけ書く
> 正規表現で末尾の丸数字を除去: `re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩]$', '', manga_title).strip()`

**テロップ（pages 2〜9）:**
```
① page2: PBG3BLhBZW05Kb0W-LBXt7PvjSgmS6B4V
② page3: PBCSwpnm9S6QVHtJ-LBff234VHn89xWtW
③ page4: PBjDNccpBqWtybYQ-LBxsBSg503sFyjyQ
④ page5: PBvxHVxQT8c46KWb-LBHJq4nGtPjjtjnV
⑤ page6: PBw7ntJLPN1YXxv3-LB7D7v0gRPY16KGC
⑥ page7: PBwNd5vms7mw2gXb-LBg46mQW7DYvYrS2
⑦ page8: PBkLftpwjtcRJDvs-LB2Dj8TSWKB0CnvR
⑧ page9: PBpYZmnGCfCLdFFC-LBzvFjt040LjCkN6
```

**画像スロット（pages 2〜9）:**
```
① page2: PBG3BLhBZW05Kb0W-LBVhh0TMry1xf5t2
② page3: PBCSwpnm9S6QVHtJ-LBdQhQ9QLg702226
③ page4: PBjDNccpBqWtybYQ-LBDvNMjX4StVB5GM
④ page5: PBvxHVxQT8c46KWb-LBH6QJ9htKbKFffb
⑤ page6: PBw7ntJLPN1YXxv3-LB51rhY8PMFFZ0yM
⑥ page7: PBwNd5vms7mw2gXb-LB5vg7qKZDrynCgY
⑦ page8: PBkLftpwjtcRJDvs-LBbb8hbVDTZV2dnn
⑧ page9: PBpYZmnGCfCLdFFC-LBlSnf96nnXyTVR8
```

**カバー画像スロット:**
```
page1カバー: PBs1sTlCLqHDSG14-LBsPl21hPyJcffJx   ← 必ず差し替える
page10カバー: PBQRTjML4Gm5msr7-LBB8BKH3dpcWzwx8  ← 必ず差し替える（忘れやすい）
```
> ⚠️ **page10カバーを忘れないこと** — エンドページのCTA画像も漫画画像に差し替える

---

# 4. 動画仕様【変更禁止】

## 構成
| 区間 | 内容 | 音声 |
|---|---|---|
| page1（イントロ） | カバー画像 静止 | 「秒で出しちゃった{manga_title}男の漫画」女性ボイス + 決定ボタンSE |
| page2〜9（コンテンツ） | 漫画コマ 静止 | VOICEVOXテロップ読み上げ ♂/♀ + ランダムSE |
| page10（アウトロ） | エンド画像 静止 | 「続きは動画の概要欄かコメント欄」女性ボイス |

## 絶対に変えてはいけないルール
- **ハードカット** → 音声が終わった瞬間に次のスライドへ切り替え（crossfade/xfade 禁止）
  理由: xfadeを使うと0.3秒×N回分のずれが累積して音声と映像がズレる
- **スライド長さ = 音声WAV長さ** → TRANSITION加算禁止
- **スライド順序** → page1=イントロ, page2-9=コンテンツ①-⑧, page10=アウトロ

## 解像度
- 1080 × 1920px（縦型 / YouTube Shorts）
- FPS: 30

---

# 5. 音声仕様【変更禁止】

## VOICEVOXキャラクター
- **♀（女性）: speaker=47 → ナースロボ＿タイプT ノーマル**
- **♂（男性）: speaker=13 → 青山龍星 ノーマル**
- イントロ/アウトロ: 女性（47）固定

## テロップの♂/♀マーカー
- 台本の行頭に `♂` または `♀` をつけて自動切り替え
- 例: `♂ あの人、気になってた…` → 青山龍星で読み上げ

## 無音パディング（音声前後の余白）
- テロップ通常: 前0.3秒 / 後0.5秒
- イントロ: 前0.5秒 / 後0.8秒
- アウトロ: 前0.3秒 / 後1.0秒

## VOICEVOX接続
- URL: http://localhost:50021
- バージョン: 0.25.2

---

# 6. BGM・効果音仕様【変更禁止】

## BGM
- ファイル: `/Users/tagishitakuya/Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/アカウント①BGM.mp3`
- 楽曲: 8-bit Aggressive1（DOVA-SYNDROME / もっぴーさうんど）著作権フリー
- **音量: 0.07（ボイスの7%）**

## 効果音（SE）
- フォルダ: `漫画アフィリエイト:動画素材/効果音/`
- 現在のファイル（4種類）:
  - `決定ボタンを押す13.mp3`
  - `スイッチを押す.mp3`
  - `ニュッ3.mp3`
  - `食べ物をパクッ.mp3`
- **イントロSE: `決定ボタンを押す13.mp3` 固定**
- コンテンツスライドSE: 4ファイルからランダム選択
- SE音量: 0.5

---

# 7. テロップ生成ルール（queue-processor.py）

## 形式
- 8行、女の子の心境をセリフ形式
- 行頭に ♂/♀ マーカー（掛け合いシーンは ♂ を使う）
- 「」鍵括弧なし
- 番号（①②）なし（生成時はつけてもOK、音声生成前に除去）
- 「た」で終わる体言止め・機械的表現は禁止

## 構成の流れ
```
①②: 日常のドキドキ・意識し始める
③④: 物理的接触・感情が溢れる瞬間
⑤⑥: 理性と欲望の葛藤
⑦: 後戻りできないと気づく
⑧: 欲望が決壊する締め
```

## 必須条件
- 漫画のコマ画像を読んで内容を反映させる
- 視聴者（男性）が「続きを見たい」と思う引きを作る
- 恥ずかしさや照れは `///` で表現可（例: もっと…して・・・///）

---

# 8. VPS ↔ Mac の連携ポイント（確定）

| タスク | VPS検知タイミング | VPSが登録するタスク | Mac がやること |
|---|---|---|---|
| [台本確認] ✅ | 30秒以内 | `assembler実行待ち` | assembler.py実行 |
| [Canva確認] ✅ | 30秒以内 | `ffmpeg動画生成待ち` | video-generator.py実行 |
| [動画確認] ✅ やり直しなし | 30秒以内 | `youtube投稿待ち` | youtube-uploader.py実行 |
| [動画確認] ✅ やり直しあり | 30秒以内 | `動画やり直し待ち` | video-generator.py再実行 |

**やり直し指示の判定ルール:**
- Notionタスクの「やり直し指示」欄に何か書いてある → 作り直し
- 「やり直し指示」欄が空 + ✅ → そのままYouTube投稿（コメントは投稿5分後）

---

# 9. スクリプト役割分担

| スクリプト | 場所 | やること | やらないこと |
|---|---|---|---|
| `dmm-discord-watcher.py` | VPS常駐 | Discord監視→Notion登録 | |
| `dmm-notion-watcher.py` | VPS常駐 | ステータス変化検知→タスク登録 | |
| `queue-processor.py` | Mac（手動） | 台本生成（Claude API） | 音声・動画 |
| `assembler.py` | Mac（手動/launchd） | 画像catboxアップ+Canva差し替え | **VOICEVOX・音声・動画** |
| `ai_brain_daemon.py` | /usr/local/bin（launchd） | 画像catboxアップ+canva_job.json作成 | **VOICEVOX・音声・動画** |
| `video-generator.py` | Mac（手動） | VOICEVOX+Canva PNG書き出し+ffmpeg | |
| `youtube-uploader.py` | Mac（手動） | YouTube投稿+概要欄/コメントにXのURL | |

**⚠️ assembler.pyでVOICEVOXを実行してはいけない**
理由: VOICEVOXはvideo-generator.pyで一度だけ実行する設計。assemblerでやると二重になる。

---

# 10. インフラ・認証情報の参照先

## Discord チャンネルID
- `#dmm-素材投稿`: 1511211307788144650
- `#inbox`: 1511214415611953214
- `#通知`: 1511214417990254664

## ファイルパス
- 動画素材フォルダ: `/Users/tagishitakuya/Desktop/ClaudeProjects/漫画アフィリエイト:動画素材/`
- 背景動画（未使用）: `アカウント①背景動画.mp4`
- BGM: `アカウント①BGM.mp3`
- 効果音: `効果音/`
- YouTube認証: `~/.config/dmm-youtube/`（client_secret.json, token.json）

## VPS
- IP: 133.88.117.175
- SSH: `ssh -i ~/.ssh/conoha_vps root@133.88.117.175`
- パス: `/opt/ai-brain/`

---

# 11. 既知の問題・制限事項

| 問題 | 状況 | 対応 |
|---|---|---|
| Canva短縮URL（`/d/`形式）からdesign_idが取れない | 常時 | `--design-id` で手動指定 |
| Discord webhook 403 | tokens.md更新待ち | tagishi手動更新が必要 |
| launchd が ~/Desktop にアクセスできない（macOS TCC制限） | macOS 15 Sequoia | ai_brain_daemon.pyは/usr/local/bin/に配置で回避 |

---

# 12. 投稿スケジュール設計【確定 2026-06-22更新】

## 1投稿あたりのバリエーション数
- **1 Discord投稿 → 6本（アカウントごとに3本）を自動生成**
- ①②③ → アカウント① に割り当て
- ④⑤⑥ → アカウント② に割り当て
- アカウント判定: 丸数字インデックス // 3 + 1（①②③→1、④⑤⑥→2）

## スケジュール計算ルール【重要】

**アカウントごとに独立して管理する。アカウント間でスロットを共有しない。**

| バリエーション | スケジュール |
|---|---|
| ①（account①の1本目） | account①カレンダーの直近空き枠 |
| ②（account①の2本目） | ①の公開日 +7日 の account①空き枠 |
| ③（account①の3本目） | ①の公開日 +14日 の account①空き枠 |
| ④（account②の1本目） | account②カレンダーの直近空き枠 |
| ⑤（account②の2本目） | ④の公開日 +7日 の account②空き枠 |
| ⑥（account②の3本目） | ④の公開日 +14日 の account②空き枠 |

例: account①の8:00が埋まっていれば → 同日21:00 → 翌日8:00 と探す（account②の状況は無関係）

## 投稿スロット
- **8:00 JST と 21:00 JST の2枠/日/アカウント**
- 毎回 ±15〜30分のランダムずらし（パターン検知回避）

## アップロードタイミング
- **公開予定日の3日前に自動アップロード**
- launchd で毎日チェック・自動実行（セッション不要）
- 動画ファイル保存先: `~/Library/ai-brain/videos/`（launchd TCC制限回避）
- 上限: 1日2本/アカウント（現行維持）

## 台本生成ルール
- 6本すべて異なる台本（同じ漫画・同じ画像セット・異なる視点/コマ）
- 共通原則: 視聴者がムラムラする内容・直接的表現はNG・漫画にないセリフもOK

## BANリスク対策
1. **コンテンツの差別化**（最重要）: 台本・声・サムネイルを変える
2. **投稿タイミングの分散**: 7日間隔・スロットのランダムずらし
3. **アップロードと公開を分離**: 3日前アップロード → YouTube側で予約公開

---

# 13. 複数アカウント運用【確定 2026-06-22】

アカウント①②同時運用中。各アカウントのスケジュール・アップロード履歴は完全独立。

## 現状
- アカウント①②運用中（2026-06-20〜）
- 1 Discord投稿 → 6動画生成フローを実装中（2026-06-22〜）

---

# 14. アカウント別仕様【変更禁止】

## アカウント① （既存）

| 項目 | 値 |
|---|---|
| Canvaテンプレ | `DAHMbaP-OTo`（①テンプレ） |
| イントロセリフ | `秒で出しちゃった{manga_title}男の漫画` |
| BGM | `アカウント①BGM.mp3` |
| 投稿スロット | 8:00・21:00（account①カレンダー内で空き枠を探す） |
| token保存先 | `~/.config/dmm-youtube/account1/token.json` |

## アカウント② （2026-06-20 追加）

| 項目 | 値 |
|---|---|
| Canvaテンプレ | `DAHNHHjLSWE`（②テンプレ） |
| イントロセリフ | `秒で出しちゃった{manga_title}叡智な漫画` |
| 背景 | 青（テンプレ内で完結・コード変更不要） |
| BGM | TBD（アカウント①と同じか別ファイルかtagishiが決める） |
| 投稿スロット | 8:00・21:00（account②カレンダー内で空き枠を探す） |
| YouTubeチャンネル | `UC761wKgnWTX1bLXTcq1Jqsg` |
| token保存先 | `~/.config/dmm-youtube/account2/token.json` |

### ⚠️ アカウント②のpage1制限【重要】

Canva MCP（start-editing-transaction）でアカウント②テンプレのコピーを開くと、**page1が `is_empty: true` として返却され、テキスト要素・画像スロットとも編集不可**。

| 影響 | 対応 |
|---|---|
| page1タイトル（漫画タイトル）が差し替えられない | tagishiがCanvaで手動入力 |
| page1カバー画像が差し替えられない | tagishiがCanvaで手動差し替え |
| VOICEVOX読み上げ（イントロ音声）への影響 | なし（video-generator.pyはNotionのmanga_titleから独立して計算） |

→ page2〜10（テロップ・画像・page10カバー）の編集は正常に動作する。

---

# 13. やってはいけないこと

- `assembler.py` でVOICEVOXを実行する
- `xfade`（crossfade）を動画に使う
- Canvaから透過PNGをAPIで書き出す（無料プラン制限）
- VPSで `claude` コマンドを実行する（API課金発生）
- このSPEC.mdの値をtagishiの明示的な許可なく変更する
- セッションログやコードのコメントをSPEC.mdより優先する
