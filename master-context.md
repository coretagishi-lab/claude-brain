---
type: master-context
title: システム全体設計・運用ルール
updated: 2026-06-02
version: 1.6
---

# Master Context — AI-Brain 運用マニュアル

> このファイルは Claude が迷ったときに参照するシステム全体の設計思想と運用ルール。

---

## 1. システム全体像

```
┌─────────────────────────────────────────────────────┐
│  tagishi（人間）                                     │
│  Discord に投げるだけ                                │
└──────────┬──────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────┐
│  Discord（唯一の入出力ハブ）                          │
│  #inbox          タスク・メモ・指示の入口             │
│  #dmm-素材投稿   漫画素材の投稿                       │
│  #通知           VPS実行結果・Bot返信・アラート       │
└──────┬───────────────────────┬──────────────────────┘
       │ API不要 → 即実行       │ API必要 → キュー登録
┌──────▼──────────────────┐   ┌▼──────────────────────┐
│  ConoHa VPS（自動化層）  │   │  Notion（キュー層）    │
│  Bot常駐・即時実行        │   │  次回ターミナル起動待ち│
│  #通知に結果を返信        │   │  status: queued        │
└─────────────────────────┘   └──────────┬─────────────┘
                                          │ セッション開始時に処理
                               ┌──────────▼─────────────┐
                               │  Claude Code（実行層）   │
                               │  生成・判断・API連携      │
                               │  Vault読み書き・承認確認  │
                               └────────────────────────┘
```

### Discord 3チャンネル構成（確定）

| チャンネル | ID | 役割 |
|---|---|---|
| `#inbox` | `1511214415611953214` | tagishiの全タスク入力口。API不要→VPS即実行、API必要→Notionキュー |
| `#dmm-素材投稿` | `1511211307788144650` | 漫画コマ画像+タイトル+アフィURL投稿 → Notionキュー（queued） |
| `#通知` | `1511214417990254664` | VPS実行結果・Bot返信・エラーアラートの出力専用 |

### 各層の責任範囲

| 層 | 誰が操作 | 何をする |
|---|---|---|
| Discord | tagishi | 全入力。投稿するだけ |
| VPS Bot | systemd常駐 | API不要タスクを即実行、結果を`#通知`に返信 |
| Notion | キュー層 | API必要タスクを`queued`で保持 |
| Claude Code | Claude | セッション開始時にNotionキューを処理 |
| AI-Brain Vault | Claude | 記憶の読み書き・状態管理 |

### 廃止したもの

| 廃止 | 代替 |
|---|---|
| GitHub Inbox (`inbox.md`) | Discord `#inbox` |
| ローカルファイルキュー (`queue.py`) | Notion queued status |
| `watch_inbox.sh` / `inbox-sync.py` | Discord Bot常駐 |
| Webhook一方向通知 | `#通知`チャンネルへのBot返信 |

---

## 2. Discord ルーティングルール

### #inbox の処理フロー

```
tagishi が #inbox に投稿
         │
         ▼
    VPS Bot が判定
         │
    ┌────┴────────────────┐
    │ API不要              │ API必要
    ▼                     ▼
VPS即実行             Notionキューに登録
#通知に結果を返信      #inbox に返信:
                      「次回ターミナル起動時に処理します」
```

### API不要タスク（VPS即実行）の例

| 投稿内容 | VPSの動作 |
|---|---|
| `status` / `状態確認` | systemdサービス一覧を`#通知`に送信 |
| `sync` / `同期して` | git sync実行 → 結果を`#通知`に送信 |
| `restart <サービス名>` | systemctl restart → 結果を`#通知`に送信 |
| `log <サービス名>` | journalctl最新20行を`#通知`に送信 |
| `メモ: <内容>` | Notionに保存 → `#inbox`に完了リプライ |

### API必要タスク（次回ターミナル起動時に処理）の例

| 投稿内容 | キュー登録内容 |
|---|---|
| `分析して: <内容>` | Claude APIで分析 → Notion投稿 |
| `台本生成: <漫画名>` | dmm-manga-affiliateパイプラインに流す |
| `改善提案` | experience.md分析 → Notion投稿 |

---

## 3. 「頭はターミナル・実行はVPS」の方針

### 基本設計

```
[Discord]                           [ConoHa VPS]
  tagishi 投稿 ──────────────────▶   Bot常駐（即実行 or キュー）
                                      systemd（定時処理・監視）
                                      #通知に返信

[Claude Code（Mac）]
  セッション開始時にNotionキューを処理
  Vault読み書き・MCP連携（Canva）
```

### 方針の意図

- **入力はDiscordに一本化**: GitHub・ファイルキューを廃止。tagishiはDiscordに投げるだけ。
- **即実行できるものはVPSが即実行**: Botが判定し、API不要なら待たせない。
- **Claudeが必要なものはキューで非同期**: 次回セッション開始時に処理するため遅延が発生するが、コスト最適。
- **Claude はVPSで動かさない**: VPS 上で claude コマンドを実行すると API コストが発生し、コンテキストも共有されない。

### VPSで動かすもの（許可）

- Discord Bot（`#inbox`・`#dmm-素材投稿`を監視）
- `ai-brain-sync.timer` — 定時同期
- `ai-brain-memory-monitor.timer` — メモリ監視
- シェルスクリプト・Python スクリプトの定時実行

### VPSで動かさないもの（禁止）

- `claude` コマンド — API コスト発生・コンテキスト分断
- 判断・生成が必要な処理 — ターミナルで完結させる

---

## 3. コスト設計ルール

### ルール一覧

| ルール | 理由 |
|---|---|
| **VPS上でclaudeを起動しない** | APIコストが発生する。VPSはスクリプト実行のみ。 |
| **モデルはSonnet固定** | Opusは約5倍のコスト。タスクの99%はSonnetで十分。 |
| **離席前に/clearを実行** | コンテキストが長くなるほどトークン消費が増える。区切りで/clearしてリセット。 |
| **長い出力を求めない** | ファイル全文・ログ全量の出力を避ける。必要な部分だけ取得。 |
| **バッチ処理はスクリプト化** | 同じ処理を何度もClaudeに頼まない。一度スクリプトにしてVPSに渡す。 |

### /clear のタイミング

- 別プロジェクトに切り替えるとき
- 長いセッション（1時間超）の節目
- 離席・休憩前
- タスクが完全に完了したとき

---

## 4. やってはいけないこと（禁止事項）

### Claude の行動規則

| 禁止 | 代替 |
|---|---|
| VPS で `claude` コマンドを実行する | ローカルターミナルで実行する |
| Opus モデルに切り替える | Sonnet のまま継続する |
| ファイル全文をそのまま出力する | 必要箇所だけ取得・提示する |
| 同じミスを2回繰り返す | `Shared/Knowledge/mistakes.md` を参照する |
| セッション終了プロトコルをスキップする | 必ず4ステップを実行する |
| `ANTHROPIC_API_KEY` を出力・ログに残す | 環境変数として扱い、表示しない |
| tagishi に確認せずに destructive な操作を実行する | 確認フォーマットで事前に聞く |
| next_action を「確認する」のような曖昧な形で書く | 「動詞 + 対象 + 目的」の形で書く |
| フィードバックを記録せずに対応する | 必ず `review-notes.md` に記録してから対応する |
| 同じフィードバックを受けても `mistakes.md` に記録しない | 2回目以降は必ず記録・仕組み化する |

### システム操作の禁止事項

| 禁止 | 理由 |
|---|---|
| VPS の `/root/.bashrc` に API キーを直書き | セキュリティリスク |
| `git push --force` | 履歴破壊リスク |
| systemd サービスを無断で停止 | 自動処理が止まる |
| Inbox を確認せずにセッション開始 | 未処理タスクが埋もれる |

---

## 5. 各サービスの現状と優先順位

### プロジェクト一覧（2026-06-01時点）

| プロジェクト | ステータス | 優先度 | 状況 |
|---|---|---|---|
| dmm-manga-affiliate | active | high | 動画パイプラインv2完成・Canva連携設計確定 |
| Manga-Ads | active | high | 進行中 |
| AI-Girls | idle | medium | 未着手 |
| Anglers-TCG | idle | medium | 未着手 |
| Recruitment-LP | idle | medium | 未着手 |
| AI-Automation | idle | medium | 未着手 |

### MCP統合（確認済み）

| MCP | 状態 | 用途 |
|---|---|---|
| Canva MCP | ✅ 接続済み | デザイン作成・編集・配置指示実行 |
| Google Drive MCP | ❌ dmm-manga-affiliateでは不使用 | Discord一本化により廃止 |
| Notion MCP | 🔲 次回接続予定 | タスク確認ボード・承認フロー |
| Slack MCP | 🔲 接続可能（未設定） | 通知・連絡 |

### VPS稼働サービス（2026-06-02 時点）

| サービス | 種別 | 間隔/常駐 | 状態 |
|---|---|---|---|
| `ai-brain-sync.timer` | timer | 30分 | ✅ 稼働中・正常確認済み（2026-06-02） |
| `ai-brain-memory-monitor.timer` | timer | 60秒 | ✅ 稼働中（800MB超でDiscord通知） |
| `ai-brain-auth-monitor.timer` | timer | 5分 | ✅ 稼働中（修復失敗→Notion待機タスク） |
| `ai-brain-morning-report.timer` | timer | 毎朝8時 | ✅ 稼働中（Discord日次レポート） |
| `ai-brain-discord-responder.service` | 常駐 | — | ✅ 稼働中（1/2返信受付） |
| `ai-brain-conoha-monitor.timer` | timer | 6時間 | ⚠️ APIパスワード再設定待ち（後回し） |

### VPS スクリプト一覧（Shared/Workflows/）

| スクリプト | 役割 |
|---|---|
| `cred-loader.py` | tokens.md → .env + .profile 自動生成 |
| `auth-monitor.py` | 認証エラー検出・自己修復・失敗時Notion登録 |
| `morning-report.py` | Discord日次レポート（VPS状態・Notion・YouTube・API料金） |
| `discord-responder.py` | 1/2返信受付Bot（APIゼロ・Claude不使用） |
| `discord-ask.py` | VPSから質問送信 + pending登録 |
| `vps-task-reporter.py` | 自己解決不能問題をNotion待機タスクに登録 |
| `vps-task-checker.py` | Mac側でNotion待機タスクを確認・処理 |

### VPS未完了タスク（対応待ち）

- [ ] ConoHa APIパスワード再設定 → 残高監視有効化（tagishi 手動作業）
- [x] VPS 日本語ロケール設定（`locale-gen ja_JP.UTF-8`）— 2026-06-02 完了

### ツールスタック

| ツール | 用途 | 状態 |
|---|---|---|
| Flux | 画像生成 | 運用中 |
| Kling | 動画生成 | 運用中 |
| Seedance | 動画生成（併用） | 運用中 |
| CapCut | 最終仕上げ | 運用中 |
| VOICEVOX 0.25.2 | TTS音声合成 | 運用中 |
| Canva MCP | 動画テンプレート | 接続済み |

---

## 6. 確認フォーマット

tagishi への確認が必要なときは**必ずこのフォーマットを使う**。

### 基本形式

```
【案件名】質問文
1: OK / 続けて
2: 待って / 別の方法で
```

### 使用例

```
【dmm-manga-affiliate】Flux で女性キャラを生成してから動画化する順で進めますか？
1: OK
2: 待って（別の順番で）
```

```
【Vault】session-end-protocol を実行します。ログも書きますか？
1: 書いて
2: 今日はスキップ
```

### ルール

- 確認なしに destructive な操作（ファイル削除・git force push 等）を実行しない
- 複数の選択肢がある場合は 1〜3 で提示する
- 「どうしますか？」だけで終わらない — 推奨案を「1」に置く

---

## 9. 漫画アフィリエイト完全フロー（dmm-manga-affiliate）— 確定版

### 全体方針

| ロール | API使用 | 責任範囲 |
|---|---|---|
| **tagishi** | — | Discord投稿・Notion承認・最終確認 |
| **VPS** | **ゼロ** | Discord監視・Notionキュー積み・Canva組立・YouTube/X投稿 |
| **Mac定時処理** | 台本生成: 1回/本 | Notionキュー→Claude API→Canva配置指示生成 |
| **Notion** | — | 全ステップの共有作業台・ステータス管理 |

```
原則①: 画像ソースは Discord に一本化。Google Drive は使わない。
原則②: VPS は API ゼロ。判断できない問題は Notion キューに積んでMac定時処理待機。
原則③: Mac定時処理は launchd で30分おきに自動実行。1日10件対応を前提とした設計。
原則④: ターミナル → VPS の指示（Canva配置）は詳細に書き、VPS が迷わない状態で渡す。
```

---

### 9ステップ確定フロー

| # | 実行者 | 処理内容 | API |
|---|---|---|---|
| 1 | tagishi | Discord専用チャンネルに**漫画コマ画像 + タイトル + アフィリエイトリンク**を投稿 | — |
| 2 | VPS | Discord Botが投稿を検知 → 画像・テキスト・Discord投稿URLを取得 → Notionキューに登録（status: **queued**） | ❌ ゼロ |
| 3 | Mac定時 | Notionキュー確認 → Discord画像読み込み → Claude APIで台本・タイトル・説明文を生成 → Notion投稿（status: **draft**）+ APIコスト記録 | ✅ 1回/本 |
| 4 | tagishi | Notionで台本確認・修正 → status を **approved** に変更 | — |
| 5 | Mac定時 | Notion承認済みを確認 → Canvaテンプレ指定・コマ画像URL・テロップ内容を詳細生成 → Notionに記録 → VPS実行トリガー | ✅ 1回/本 |
| 6 | VPS | Notionから配置指示取得 → Canvaテンプレコピー → コマ画像・テロップ配置 → 編集URL取得 → Notion記録（status: **canva_ready**） | ❌ ゼロ |
| 7 | tagishi | NotionのCanva URLから動画確認・承認 → status を **final** に変更 | — |
| 8 | VPS | Canvaから動画ダウンロード → YouTube + X（Twitter）に自動投稿 → Notion記録（status: **uploaded**） | ❌ ゼロ |
| 9 | VPS（定期） | YouTube Analytics取得 → Notion記録 | ❌ ゼロ |

---

### フローの流れ図

```
[tagishi] Discord投稿（画像+タイトル+アフィURL）
                    │
                    ▼
    [VPS・APIゼロ] Discord Bot検知
                    │ Notionキュー登録（queued）
                    │ source_discord_url 記録
                    ▼
    [Mac・30分おき] Notionキュー確認
                    │ Discord画像読み込み
                    │ Claude API 1回 → 台本生成
                    │ api_cost_estimate 記録
                    │ Notion投稿（draft）
                    ▼
    [tagishi] Notion確認・修正 → approved
                    │
                    ▼
    [Mac・30分おき] Canva配置指示を詳細生成
                    │ （テンプレID・コマURL・テロップ・VOICEVOX設定）
                    │ VPS実行トリガー（Notionに指示書を記録）
                    ▼
    [VPS・APIゼロ] Canvaテンプレコピー → 配置 → 編集URL取得
                    │ Notion記録（canva_ready）
                    ▼
    [tagishi] Canva URL確認・承認 → final
                    │
                    ▼
    [VPS・APIゼロ] 動画ダウンロード → YouTube + X投稿
                    │ Notion記録（uploaded）
                    ▼
    [VPS・定期・APIゼロ] Analytics取得 → Notion記録
```

---

### Notionコンテンツ審査DB フィールド一覧

DB ID: `3731cad4aa98810e82f8c0f99a483cbb`

| フィールド | 型 | 内容 |
|---|---|---|
| title | Title | `[YYYY-MM-DD] 漫画タイトル` |
| manga_title | rich_text | 漫画タイトル |
| youtube_title | rich_text | YouTube動画タイトル |
| description | rich_text | YouTube説明文 |
| script | rich_text | VOICEVOX用ナレーション台本 |
| affiliate_url | url | DMMアフィリエイトURL |
| source_discord_url | url | 元のDiscord投稿URL |
| api_cost_estimate | rich_text | Claude API推定コスト（例: "$0.07"） |
| status | select | queued → draft → approved → canva_ready → final → uploaded |
| canva_url | url | Canva編集URL |
| video_url | url | YouTube動画URL |
| created_at | date | 投稿日 |

---

### Mac定時処理スクリプト（launchd管理・稼働中）

| スクリプト | launchd Label | 実行間隔 | 役割 |
|---|---|---|---|
| `queue-processor.py` | `com.ai-brain.queue-processor` | 30分おき | queued → Claude API台本生成（画像付き） → draft |
| `canva-instructions.py` | `com.ai-brain.canva-instructions` | 30分おき | approved → Canva配置指示JSON生成 → canva_pending |

### VPS専用スクリプト（dmm-manga-affiliate）

| スクリプト | 役割 | 状態 |
|---|---|---|
| `dmm-discord-watcher.py` | #dmm-素材投稿 監視→Notionキュー登録 | ✅ 稼働中 |
| `dmm-canva-assembler.py` | canva_pending→Canva REST API組立→canva_ready | ❌ 未実装 |
| `dmm-publisher.py` | Canva動画DL→YouTube + X投稿（骨格） | ⚠️ 骨格のみ |
| `dmm-analytics.py` | YouTubeアナリティクス→Notion記録 | ❌ 未実装 |

### #inbox URL分析機能（discord-inbox-bot.py に組み込み済み）

| URL種別 | 収集内容 | ツール |
|---|---|---|
| YouTube | タイトル・説明文・字幕・上位コメント・タグ・視聴数 | yt-dlp |
| Instagram | キャプション・投稿者・いいね数 | yt-dlp / instaloader |

---

### VPS が Notion キューに積む状況

| 発生状況 | キューに積む内容 |
|---|---|
| Discord画像URLが取得できない | 「Discord添付画像の取得失敗。投稿URL: [URL]」 |
| Canvaテンプレが見つからない | 「テンプレ名不一致。取得名一覧: [X, Y, Z]」 |
| YouTube quota超過 | 「YouTube API quota超過。翌日再試行か手動投稿が必要」 |
| X（Twitter）投稿失敗 | 「X投稿失敗。エラー: [詳細]。手動投稿が必要」 |
| Notion APIエラー | 「Notion取得失敗。NOTION_TOKEN を確認してください」 |
| Canva動画DL失敗 | 「Canva export失敗。エラー: [詳細]。手動DLが必要」 |

---

### experience.md の構造

パス: `Projects/dmm-manga-affiliate/Knowledge/experience.md`

```
---
type: knowledge
title: 台本品質改善ログ
updated: YYYY-MM-DD
---

## 改善ルール（蓄積から導出）

- タイトルは疑問形より断言形のほうが CTR 高い
- 台本冒頭に「主人公の不安・葛藤」を入れるとエンゲージメント向上
- テロップは体言止めで統一するとテンポが上がる

## 修正傾向ログ

### YYYY-MM-DD
- [タイトル] tagishi 修正: 「XXX → YYY」
- 検出パターン: 感情演出が弱い / 冒頭が説明的すぎる / など
```

STEP 3（台本生成）時は、この `改善ルール` セクションをシステムプロンプトに含めて参照する。

---

### スケールアップ設計（4アカウント戦略・確定 2026-06-03）

#### 基本方針

| 項目 | 設計 |
|---|---|
| バリエーション数 | 1素材から **4本** の台本を生成（デフォルト） |
| YouTubeアカウント | **4アカウント**で運用開始・各アカウントに1本ずつ投稿 |
| 投稿時間 | アカウントごとにずらす（例: 9:00 / 12:00 / 18:00 / 21:00） |
| Canvaテンプレート | **アカウントごとに専用テンプレート**（同素材でも見た目を変える） |
| IP対策 | 収益が出てから導入（まず4アカウントで検証フェーズ） |

#### バリエーション生成フロー

```
tagishi: #dmm-素材投稿 に画像+タイトル+アフィURL を1回投稿
                    │
                    ▼
    [Mac定時] Claude API 1回 → 4バリエーション一括生成
              各バリエーション: youtube_title / description / script が異なる
              Notionに4件レコード作成（account_id: 1〜4）
                    │
                    ▼ ×4
    [tagishi] Notionで各バリエーション確認・承認
                    │
                    ▼ ×4
    [VPS] 各アカウント用Canvaテンプレートで動画組立
                    │
                    ▼
    [VPS] 4アカウントへ時間差投稿
          account_1: 09:00 / account_2: 12:00
          account_3: 18:00 / account_4: 21:00
```

#### Notion DBへの追加フィールド（設計）

| フィールド | 型 | 内容 |
|---|---|---|
| account_id | select | 1 / 2 / 3 / 4 |
| variant_num | number | バリエーション番号（1〜4） |
| source_group_id | rich_text | 同素材グループのID（UUID）|
| scheduled_time | date | 投稿予定日時 |
| canva_template_id | rich_text | アカウントごとの専用テンプレートID |

#### アカウント・テンプレート管理（tokens.mdに追記予定）

```
## YOUTUBE_ACCOUNTS
ACCOUNT_1_TOKEN: <OAuth2 token path>
ACCOUNT_1_CHANNEL_ID: <channel_id>
ACCOUNT_1_CANVA_TEMPLATE: <canva_design_id>
ACCOUNT_1_POST_HOUR: 9

ACCOUNT_2_TOKEN: ...
...
```

#### 実装上の変更点（未実装・次セッションで着手）

| スクリプト | 変更内容 |
|---|---|
| `queue-processor.py` | 1回のAPI呼び出しで4バリエーション生成 → Notionに4件作成 |
| `canva-instructions.py` | account_idからテンプレートIDを決定 |
| `dmm-publisher.py` | account_idに対応するOAuth2トークン・投稿時刻を使用 |

---

## 10. 競合分析自動化（dmm-manga-affiliate）— 確定 2026-06-03

### 概要

日本語・漫画系YouTube Shortsの競合動画を自動収集・分析してCanvaテンプレ改善に活かす。

### フロー

```
tagishi: #inbox に「競合分析: {ジャンル名}」を投稿
                    │
                    ▼
    [VPS Bot] competitive-search.py を実行
              yt-dlp で YouTube Shorts 最大20本収集
              Notionキューに登録（status: queued）
              #inbox にリプライ:「N本収集。夜中2時に分析します」
                    │ ← Macがオフの間も Notionに待機
                    ▼
    [Mac 毎日2:00] competitive-analyzer.py
              Notion queued を取得
              yt-dlp で各動画の詳細情報取得（コメント・チャプター・サムネイル）
              Claude API 1回で一括分析（サムネイル画像 + 全データ）
              Notion にレポート保存（status: done）
                    │
                    ▼
    [VPS] Discord #通知 に完了通知
          「競合分析完了: {ジャンル名} / N本 / $X.XX」
```

### 分析内容（Claude API への指示）

| 項目 | 内容 |
|---|---|
| タイトル傾向 | 高再生数タイトルの言い回し・感情訴求キーワード |
| 冒頭30秒構成 | チャプター情報から読み取れるオープニングの型 |
| コメント反応 | いいね数上位コメントから見る視聴者が刺さる要素 |
| サムネイルパターン | Claude vision でテキスト配置・色・強調を分析 |
| 課金誘発共通点 | 「続きが気になる」「課金した」コメント多い動画の特徴 |
| TOP5共通点 | 再生数上位5本の絶対条件 |
| Canvaアドバイス | テロップ・サムネイル・冒頭演出の具体的改善策5点以上 |

### Notion 競合分析 DB

DB ID: `3731cad4aa98811383c6f5b4973aee2c`

| フィールド | 型 | 内容 |
|---|---|---|
| title | Title | `[YYYY-MM-DD] 競合分析: ジャンル名` |
| genre | rich_text | ジャンル名 |
| status | select | queued → analyzing → done / error |
| video_count | number | 分析動画数 |
| canva_advice | rich_text | Canva改善アドバイス（要約） |
| created_at | date | 登録日 |

### 実装済みスクリプト

| スクリプト | 場所 | 役割 | 状態 |
|---|---|---|---|
| `competitive-search.py` | Shared/Workflows/ (VPS) | ジャンル検索→Notion登録 | ✅ 稼働中 |
| `competitive-analyzer.py` | dmm-manga-affiliate/Workflows/ (Mac) | Claude一括分析→レポート | ✅ launchd登録済み |
| `com.ai-brain.competitive-analysis` | launchd | 毎日2:00に自動実行 | ✅ 登録済み |

### discord-inbox-bot 競合分析コマンド

```
競合分析: ドキドキ漫画
競合分析: 異世界転生ショート
分析: 大人向け漫画
```

→ VPS が即座に検索・収集して Notion キューに登録
→ 夜中2:00 に Mac が自動分析・レポート作成
→ 朝 Discord #通知 に完了通知

---

## 7. セッション開始チェックリスト

```
□ VPS 待機タスクを確認（vps-task-checker.py）  ← 最優先
□ Inbox キューを確認（queue.py status）
□ CLAUDE.md を読んだ
□ 対象プロジェクトの current-task.md を読んだ
□ PROJECT_STATUS.md の next_action を確認した
□ mistakes.md を確認した
```

## 8. セッション終了チェックリスト

```
□ current-task.md の checkpoint を更新した
□ PROJECT_STATUS.md の next_action / updated_at を更新した
□ Logs/ にセッションログを書いた（意思決定のみ）
□ SESSION END SUMMARY を出力した
□ 必要なら /clear を実行した
```
