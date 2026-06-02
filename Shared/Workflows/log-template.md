---
type: template
title: Log ファイル標準テンプレート
updated: 2026-05-21
---

# Log テンプレート

> **原則:** 意思決定の記録のみ。実行操作の列挙は書かない。

---

## 使用方法

ファイル名: `Logs/YYYY/MM/YYYY-MM-DD-session-[番号].md`

以下をコピーして使う:

---

```markdown
---
type: log
date: YYYY-MM-DD
session: 000
project: [プロジェクト名 または "Vault"]
status_after: [idle|active|review|blocked]
---

# Session 000 — [セッションの主題を1行で]

## 意思決定ログ

| # | 決定内容 | 理由 | 却下した選択肢 |
|---|---|---|---|
| 1 | — | — | — |

## ブロッカー（問いの形で）

- [ ] [tagishiに確認すること / 解決すべき問い]

## 現在地（checkpoint）

> [どのステップのどこまで終わったか・1行]

## 次回の first action

> [動詞 + 対象 + 目的・1文]
```

---

## 記入例

```markdown
---
type: log
date: 2026-05-21
session: 008
project: Manga-Ads
status_after: active
---

# Session 008 — STEP 2 感情アーク設計完了

## 意思決定ログ

| # | 決定内容 | 理由 | 却下した選択肢 |
|---|---|---|---|
| 1 | 感情アーク: 共感→葛藤→転換→解放 に決定 | ターゲット（20代女性）の購買心理に合致 | 好奇心型（情報訴求）は採用見送り |
| 2 | 尺を30秒から45秒に変更 | 転換シーンに最低5秒必要と判断 | 30秒は感情アークが圧縮しすぎる |

## ブロッカー（問いの形で）

- [ ] Fluxプロンプトのメインキャラ設定をtagishiに確認（年齢・髪色・雰囲気）

## 現在地（checkpoint）

> STEP 2完了・STEP 3（Flux生成）開始前・感情アーク設計書は current-task.md に記録済み

## 次回の first action

> Fluxでcinematic素材5枚を生成してAI感チェックを実施する
```

---

## 書かないこと（禁止リスト）

- 「〇〇ファイルを作成した」「〇〇を更新した」という操作ログ
- Claude の思考プロセスの全文
- 変更したファイルの一覧
- セッション時間・文字数などのメタ情報
- 「問題なし」「特になし」のような空エントリ
