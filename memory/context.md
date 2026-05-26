# context.md — 直近の会話サマリー

## 最終更新
2026-05-27

## システム構成（完成）

```
スマホのClaudeアプリ（戦略・指示）
    ↕
GitHub claude-brainリポジトリ（橋）
    ↕
PCのターミナル（自動実行）
    ↓
Discord通知（スマホに報告）
```

## 完成済み設定

| 項目 | 詳細 |
|---|---|
| GitHubリポジトリ | github.com/coretagishi-lab/claude-brain（プライベート） |
| inbox.md | 指示を書くとターミナルが自動実行 |
| outbox.md | ターミナルからの報告（更新時Discord通知） |
| approval.md | 承認が必要な時のみ使用（更新時Discord通知） |
| 監視スクリプト | fswatch常時監視・Terminal起動時に自動スタート |
| Discord通知 | Webhook設定済み・動作確認済み |
| GitHub Token | macOSキーチェーンに保存済み・.zshrcにも設定 |

## 残タスク

### iPhoneショートカットの設定
Claudeアプリで話した内容を自動でinbox.mdに送る仕組み。

手順概要：
1. iPhoneの「ショートカット」アプリで新規作成
2. 「テキストを入力」→「URLの内容を取得」でGitHub APIに送信
3. GitHub API: `https://api.github.com/repos/coretagishi-lab/claude-brain/contents/inbox.md`
4. Personal Access Token（macOSキーチェーン保存済みのもの）で認証

## 重要情報

- GitHubアカウント：coretagishi-lab
- リポジトリ：claude-brain（プライベート）
- Discord通知先：claude-brainサーバー
- トークン：macOSキーチェーン保存（ファイルには書いていない）
