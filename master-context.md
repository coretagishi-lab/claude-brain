---
type: master-context
title: システム全体設計・運用ルール
updated: 2026-06-02
version: 1.2
---

# Master Context — AI-Brain 運用マニュアル

> このファイルは Claude が迷ったときに参照するシステム全体の設計思想と運用ルール。

---

## 1. システム全体像

```
┌─────────────────────────────────────────────────────┐
│  tagishi（人間）                                     │
│  指示・フィードバック・承認                           │
└──────────┬──────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────┐
│  Notion（人間UI層）                                  │
│  タスク確認ボード / レビュー / 承認フロー             │
└──────────┬──────────────────────────────────────────┘
           │ フィードバック / 指示
┌──────────▼──────────────────────────────────────────┐
│  Claude Code（実行エンジン層）                       │
│  ローカルターミナルで起動                             │
│  生成 / 編集 / 提案 / API連携 / 状態更新             │
└──────────┬──────────────────────────────────────────┘
           │ 読み書き
┌──────────▼──────────────────────────────────────────┐
│  AI-Brain Vault（記憶層）                            │
│  Style / Workflow / Prompts / Mistakes / Status      │
└──────────┬──────────────────────────────────────────┘
           │ 自動実行
┌──────────▼──────────────────────────────────────────┐
│  ConoHa VPS（自動化層）                              │
│  systemd タイマー / 定時処理 / Discord通知           │
│  IP: 133.88.117.175 / Ubuntu 24.04.3 LTS            │
│  パス: /opt/ai-brain/                               │
└─────────────────────────────────────────────────────┘
```

### 各層の責任範囲

| 層 | 誰が操作 | 何をする |
|---|---|---|
| Notion | tagishi | レビュー・承認・タスク確認 |
| Claude Code | Claude | 生成・判断・ファイル操作・API呼び出し |
| AI-Brain Vault | Claude | 記憶の読み書き・状態管理 |
| ConoHa VPS | systemd | 定時処理・自動同期・監視通知 |

---

## 2. 「頭はターミナル・実行はVPS」の方針

### 基本設計

```
[tagishi の Mac]                    [ConoHa VPS]
  Claude Code（思考・判断）    →      systemd（定時実行）
  AI-Brain Vault（記憶）       ←      git sync（30分ごと）
  MCP連携（Canva / GDrive）          Discord通知（監視）
```

### 方針の意図

- **思考・判断はローカル**: Claude Code は tagishi の Mac のターミナルで動かす。コンテキストを持ち、Vaultを直接読み書きできる。
- **定型処理はVPS**: ループ・同期・監視など「決まった処理を定時実行」するものだけVPSに置く。
- **Claude はVPSで動かさない**: VPS 上で claude コマンドを実行すると API コストが発生し、コンテキストも共有されない。

### VPSで動かすもの（許可）

- `ai-brain-sync.timer` — Vault を GitHub に30分ごと同期
- `ai-brain-memory-monitor.timer` — メモリ監視・800MB超でDiscord通知
- シェルスクリプト・Python スクリプトの定時実行

### VPSで動かさないもの（禁止）

- `claude` コマンド — API コスト発生・コンテキスト分断
- 対話的な処理 — ターミナルで完結させる

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
| Canva MCP | ✅ 接続済み | デザイン作成・編集・ページ追加 |
| Google Drive MCP | ✅ 接続済み | ファイル検索・base64ダウンロード |
| Notion MCP | 🔲 次回接続予定 | タスク確認ボード・承認フロー |
| Slack MCP | 🔲 接続可能（未設定） | 通知・連絡 |

### VPS稼働サービス（2026-06-02 時点）

| サービス | 種別 | 間隔/常駐 | 状態 |
|---|---|---|---|
| `ai-brain-sync.timer` | timer | 30分 | ✅ 稼働中 |
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
- [ ] VPS 日本語ロケール設定（`locale-gen ja_JP.UTF-8`）

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

## 9. 漫画アフィリエイト完全フロー（dmm-manga-affiliate）

### 全体方針

| ロール | API使用 | 責任範囲 |
|---|---|---|
| **ターミナル（Claude Code）** | 生成: 1回/本、分析: 週1回 | 思考・生成・フィードバック解釈 |
| **VPS** | **ゼロ** | 機械的実行のみ（判断しない） |
| **Notion** | — | tagishi ↔ ターミナルの共有作業台 |
| **tagishi** | — | 確認・承認・最終仕上げ |

```
原則①: VPS は API ゼロ。判断が必要な状況は Notion キューに積んでターミナル待機。
原則②: ターミナル → VPS の指示は詳細に書き、VPS が迷わない状態で渡す。
原則③: Notion フィードバックはターミナルが API で 1次確認してから VPS に指示。
```

---

### 8ステップ完全フロー

| # | 実行者 | 処理内容 | API |
|---|---|---|---|
| 1 | ターミナル | 台本・タイトル・説明文を **1回の API** で生成 → Notion「コンテンツ審査」に投稿 | ✅ 1回 |
| 2 | tagishi | Notion で確認・直接修正 → status を `approved` に変更（Go サイン） | — |
| 3 | VPS | Notion から承認済みコンテンツ取得 → Canva テンプレコピー → 画像・テロップ・VOICEVOX 音声を配置 → 動画書き出し | ❌ ゼロ |
| 4 | tagishi | Canva で最終仕上げ → status を `final` に変更（Go サイン） | — |
| 5 | VPS | YouTube Data API で自動投稿 → Notion に動画 URL を記録 | ❌ ゼロ |
| 6 | VPS（定期） | YouTube Analytics を取得 → Notion「アナリティクス」に記録 | ❌ ゼロ |
| 7 | ターミナル | **週1回**: Notion 修正履歴を分析 → 改善案を Notion「改善提案」に投稿 | ✅ 週1回 |
| 8 | ターミナル | 分析結果を `experience.md` に蓄積 → 次回 STEP 1 の台本生成に反映 | — |

---

### フローの流れ図

```
[ターミナル] ──API 1回──▶ 台本・タイトル・説明文生成
                                    │ Notion 投稿
                                    ▼
                          [tagishi] Notion 確認・修正・Go
                                    │ status: approved
                                    ▼
                [VPS・APIゼロ] Canva 組み立て → 動画書き出し
                                    │
                                    ▼
                          [tagishi] Canva 最終仕上げ・Go
                                    │ status: final
                                    ▼
                [VPS・APIゼロ] YouTube 自動投稿
                                    │
                                    ▼
                [VPS・定期・APIゼロ] Analytics 取得 → Notion 記録
                                    │
                          ┌─────────▼──────────┐
                          │  [ターミナル] 週1回  │
                          │  修正傾向を API 分析  │
                          │  → 改善案を Notion  │
                          │  → experience.md 蓄積│
                          └──────────┬──────────┘
                                     │ 次回台本生成に反映
                                     ▼
                          [ターミナル] STEP 1 へ戻る
```

---

### VPS が Notion キューに積む状況（漫画アフィリエイト）

VPS が自己解決できない問題は `vps-task-reporter.py` で即座に Notion 待機タスクに登録する。

| 発生状況 | キューに積む内容 |
|---|---|
| Canva テンプレが見つからない | 「テンプレ名を確認。取得名一覧: [X, Y, Z]」 |
| YouTube quota 超過 | 「YouTube API quota 超過。翌日再試行か手動投稿が必要」 |
| VOICEVOX キャラ ID 不明 | 「ID [X] が存在しない。使用可能 ID を確認してください」 |
| Notion API エラー | 「Notion 取得失敗。NOTION_TOKEN を確認してください」 |
| 動画書き出し失敗 | 「Canva export 失敗。エラー内容: [詳細]。手動で書き出してください」 |

ターミナルはセッション開始時に `vps-task-checker.py` で確認し、順番に処理する。

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

STEP 1 の台本生成時は、この `改善ルール` セクションをシステムプロンプトに含めて参照する。

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
