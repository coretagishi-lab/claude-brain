---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-02
---

# 引き継ぎ — AI-Brain セッション 2026-06-02

このファイルを次のチャットの冒頭に貼り付けて使う。

---

## システム全体像

```
tagishi（Mac）
  │
  ├─ Claude Code（ターミナル）  ← 思考・生成・判断・API呼び出し
  │    └─ AI-Brain Vault（~/Desktop/ClaudeProjects/AI-Brain/）← 記憶層
  │
  ├─ Notion  ← 人間UIとClaudeの共有作業台（承認・レビュー・タスク確認）
  │
  └─ ConoHa VPS 133.88.117.175  ← 自動化層（APIゼロ・判断しない）
       └─ /opt/ai-brain/Shared/Workflows/
```

**原則: 頭はターミナル・実行はVPS。VPSはAPIゼロ。判断が必要な場合はNotionキューに積んでターミナル待機。**

---

## 今日（2026-06-02）完成したもの

### VPS 稼働中サービス（全5本）

| サービス | 内容 |
|---|---|
| `ai-brain-sync.timer` | 30分ごとVault→GitHub同期 |
| `ai-brain-memory-monitor.timer` | メモリ監視・800MB超でDiscord通知 |
| `ai-brain-auth-monitor.timer` | 5分ごと認証エラー検出・自己修復 |
| `ai-brain-morning-report.timer` | 毎朝8時 Discord日次レポート |
| `ai-brain-discord-responder.service` | 常駐Bot（1/2返信受付のみ・APIゼロ） |

### 実装済みスクリプト

| ファイル | 役割 |
|---|---|
| `cred-loader.py` | `/opt/ai-brain/.credentials/tokens.md` → `.env` + `.profile` 自動生成 |
| `auth-monitor.py` | 認証エラー検出 → tokens.md参照 → 自己修復 → 失敗時Notion登録 |
| `morning-report.py` | VPS状態・Notion承認待ち・YouTube再生数・API料金 → Discord通知 |
| `discord-responder.py` | 「1」「2」の返信のみ受付。1=即実行orNotion登録、2=保留 |
| `discord-ask.py` | VPSから質問送信 + pendingファイル登録 |
| `vps-task-reporter.py` | VPS自己解決不能 → Notion待機タスク登録 + Discord通知 |
| `vps-task-checker.py` | セッション開始時にNotionの待機タスクを確認・処理 |

### ドキュメント

- `master-context.md` v1.2 — システム全体設計・漫画アフィリエイトフロー・スクリプト一覧
- `CLAUDE.md` v4.4 — 自律判断ルール・確認ゼロ化・ConoHa後回し・認証自己修復
- `TODO.md` — 完了/次タスク管理
- `tokens.md`（VPS `/opt/ai-brain/.credentials/`） — 全認証情報一元管理（gitignore済み）

---

## 次にやること（優先順）

1. **DMM manga affiliate パイプライン実装**
   - STEP 1: ターミナルが台本・タイトル・説明文を1回のAPIで生成 → Notionに投稿
   - STEP 3: VPSがCanva MCPでテンプレコピー → 画像・テロップ・VOICEVOX配置 → 動画書き出し
   - STEP 5: VPSがYouTubeに自動投稿
   - 詳細フローは `master-context.md` セクション9参照

2. **ConoHa APIパスワード再設定**（tagishi手動）→ 残高監視有効化

3. **VPS日本語ロケール設定**
   ```bash
   ssh -i ~/.ssh/conoha_vps root@133.88.117.175
   locale-gen ja_JP.UTF-8
   ```

4. **YouTube APIセットアップ**
   - YOUTUBE_CHANNEL_ID と YOUTUBE_API_KEY を tokens.md に追記
   - `python3 /opt/ai-brain/Shared/Workflows/cred-loader.py --update-profile`

---

## 運用ルール

### 確認フォーマット（これ以外で確認しない）
```
【案件名】質問
1: OK
2: 待って
```

### APIゼロ原則
- VPS は Claude API を一切使わない
- VPS が判断できない問題 → `discord-ask.py` で質問 or `vps-task-reporter.py` でNotionキュー登録
- ターミナルからVPSへの指示は詳細に書いて判断不要な状態で渡す

### コスト設計
- モデルは Sonnet 固定（Opus 禁止）
- 漫画アフィリエイト: API使用は台本生成1回/本 + 分析週1回のみ
- 離席前に `/clear`

### ファイル・フォーマットの自律判断
ファイルの構造・番号・順番・フォーマットに関する判断は全て自律で行う。tagishiに確認しない。

---

## 重要パス・接続情報

| 項目 | 値 |
|---|---|
| VPS SSH | `ssh -i ~/.ssh/conoha_vps root@133.88.117.175` |
| VPS パス | `/opt/ai-brain/` |
| 認証情報 | `/opt/ai-brain/.credentials/tokens.md`（chmod 600） |
| GitHub リポジトリ | `coretagishi-lab/claude-brain`（main ブランチ） |
| Notion Outbox DB | `36f1cad4-aa98-81fb-93d8-d40bfb95cff9` |
| Vault ローカル | `~/Desktop/ClaudeProjects/AI-Brain/` |

---

## セッション開始チェックリスト

```bash
# 1. VPS待機タスク確認（最優先）
python3 Shared/Workflows/vps-task-checker.py

# 2. Inboxキュー確認
python3 Shared/Workflows/queue.py status

# 3. このファイルを読んだ → 作業開始
```
