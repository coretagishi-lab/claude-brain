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

**運用ルール:**
- Discord投稿時点で即座に「予約済み」でカレンダーに登録される
- 8:00 / 21:00 の空き枠を自動探索 → ±15〜30分ランダムずらしで被りを防止
- tagishiは時刻指定不要。投稿するだけで次の空き枠に自動で入る
- YouTube投稿後に「公開済み」に自動更新

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
page1カバー: PBs1sTlCLqHDSG14-LBsPl21hPyJcffJx
page10カバー: PBQRTjML4Gm5msr7-LBB8BKH3dpcWzwx8
```

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

# 12. 複数アカウント運用時のBANリスク対策【将来実装】

## リスク
同一IPから複数アカウントで短時間に連続投稿するとYouTubeにフラグされる可能性がある。

## 実装済みの対策
- 投稿時刻 ±15〜30分ランダムずらし
- アップロードと公開時刻の分離（YouTubeのscheduledPublishTime）

## 複数アカウント開始時に追加する対策
1. **アカウント間の時間帯を固定分離**
   → アカウント①: 8:00枠のみ / アカウント②: 21:00枠のみ（同じ枠を使わない）
2. **アップロード時刻の強制分散**
   → 同日に複数アカウントをアップロードする場合は最低2〜3時間あける
3. **IPローテーション（アカウント数が3以上になったら検討）**
   → アカウントごとに別のVPN/プロキシ経由でアップロード

## 現状
1アカウントのみ運用中 → BANリスクなし。複数アカウント開始時にこの節を再読して対策を実装すること。

---

# 13. やってはいけないこと

- `assembler.py` でVOICEVOXを実行する
- `xfade`（crossfade）を動画に使う
- Canvaから透過PNGをAPIで書き出す（無料プラン制限）
- VPSで `claude` コマンドを実行する（API課金発生）
- このSPEC.mdの値をtagishiの明示的な許可なく変更する
- セッションログやコードのコメントをSPEC.mdより優先する
