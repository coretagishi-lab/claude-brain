---
type: handoff
title: 次チャットへの引き継ぎ
updated: 2026-06-05
---

# 引き継ぎ — AI-Brain セッション 2026-06-05

このファイルを次のチャットの冒頭に貼り付けて使う。

---

## システム全体像（確定版）

```
tagishi
  └─ Discord に投げるだけ
       │
       ├─ #inbox           タスク・指示・メモ / YouTube・Instagram URL分析
       ├─ #dmm-素材投稿    漫画コマ画像 + タイトル + アフィURL
       └─ #通知            VPS実行結果・Bot返信（読み取り専用）
            │
            ├─ API不要 → VPS Bot 即実行 → #通知 or #inbox にリプライ
            └─ API必要 → Notionキュー（queued） → Mac定時処理（30分おき）
```

**原則: tagishiはDiscordに投げるだけ。GitHubキュー・ファイルInbox廃止。**

---

## Discord チャンネル一覧（確定）

| チャンネル | ID | Bot |
|---|---|---|
| `#inbox` | `1511214415611953214` | discord-inbox-bot ✅ |
| `#dmm-素材投稿` | `1511211307788144650` | dmm-discord-watcher ✅ |
| `#通知` | `1511214417990254664` | 出力専用 |

---

## VPS 稼働中サービス（全8本）

| サービス | 内容 | 状態 |
|---|---|---|
| `ai-brain-sync.timer` | 30分ごとVault→GitHub同期 | ✅ |
| `ai-brain-memory-monitor.timer` | メモリ監視・800MB超でDiscord通知 | ✅ |
| `ai-brain-auth-monitor.timer` | 5分ごと認証エラー検出・自己修復 | ✅ |
| `ai-brain-morning-report.timer` | 毎朝8時 Discord日次レポート | ✅ |
| `ai-brain-discord-responder.service` | 旧Bot（後で統合予定） | ✅ |
| `ai-brain-dmm-discord-watcher.service` | `#dmm-素材投稿`監視→Notionキュー | ✅ |
| `ai-brain-discord-inbox-bot.service` | `#inbox`ルーター・URL分析 | ✅ |
| `fishing-platform.service` | 釣りマップAPI (uvicorn port 8080) | ✅ |

**VPS メモリ（2026-06-05確認）:** 586MB / 1.9GB 使用 、1.3GB 利用可能、Swap未使用

---

## Mac launchd ジョブ（自動実行）

| ジョブ | スケジュール | 役割 |
|---|---|---|
| `com.ai-brain.queue-processor` | 30分おき | Notion queued → Claude API台本生成 → draft |
| `com.ai-brain.canva-instructions` | 30分おき | Notion approved → Canva配置指示 → canva_pending |
| `com.ai-brain.mac-config-sync` | 毎日3:00 | ~/.zshrc をマスクしてVaultに保存 |
| `com.ai-brain.sync-youtube-cookies` | 毎週月曜3:00 | youtube-cookies.txt をVPSに転送 |

---

## 🆕 fishing-platform — 今日の作業まとめ（2026-06-05）

**URL:** http://133.88.117.175  
**VPS パス:** `/opt/ai-brain/Projects/fishing-platform/app/`

### 完了した変更（全コミット済み・デプロイ済み）

| # | 内容 | コミット |
|---|---|---|
| 1 | ヒートマップ全点赤バグ修正（OSM街灯スタッキング→max化・65点キャップ） | d75da7a |
| 2 | 関東全域ヒートマップ（viewport bounds渡し・半径制限撤廃・moveend自動更新） | d019f48 |
| 3 | ヒートマップ色濃化・タイル方式（pad±0.02°・canvas opacity 0.92） | f81d3c6 |
| 4 | ポリゴン方式導入（natural=water岸→中央グラデーション点列） | 554a640 |
| 5 | Overpass廃止→SQLite中心線からポリゴン生成 | bb74f8d |
| 6 | kanto_rivers.geojson（2.2MB・4476ポリゴン）をローカルから取得して静的配置 | 28f4d46 |
| 7 | ズームボタン5段階（right:70px・黒背景60%透過・白文字・🗾z8/z10/z13/z15/z17） | 28f4d46 |
| 8 | サーモグラフィー配色（青→水色→緑→黄緑→黄→橙→赤）・期間フィルター削除 | bdb322c |
| 9 | **SW v3更新（グラデーション未反映の根本修正）**・静的JSON化・ptトースト削除 | edb891d |

### 技術的決断と学び

| 件 | 内容 |
|---|---|
| Overpassタイムアウト | `natural=water`+`out geom`は東京圏でも55秒以上かかる。ローカルから取得→静的GeoJSON方式に切り替え |
| SW stale-while-revalidate | キャッシュバージョン更新（v2→v3）しないと新コードが反映されない。グラデーション未反映の根本原因だった |
| 釣具店Overpass廃止 | `/data/tackle_shops.json`（18件）から即座読み込みに統一 |
| 遊漁船 | `/data/boats.json`（10件）から読み込み・BOATS_DATA定数廃止 |

### 現在のヒートマップ構造

```
ブラウザ → /api/heatmap → get_river_heatmap()
              ↓
          get_water_polygon_data() ← SQLite osm_rivers (26,282件)
              ↓
          _centerline_to_polygon() ← 川幅推定してポリゴン生成
              ↓
          _build_shore_gradient_points()
              ↓ 点列（スコア0.07〜0.92）
          Canvas サーモグラフィー描画
          scoreToRgb: 0.15未満=透明 → 深青→水色→緑→黄緑→黄→橙→赤
```

### 静的データファイル

| ファイル | 中身 | パス |
|---|---|---|
| `kanto_rivers.geojson` | 4,476水域ポリゴン（2.2MB） | `/static/data/` |
| `tackle_shops.json` | 釣具店18件 | `/static/data/` |
| `boats.json` | 遊漁船10件 | `/static/data/` |

---

## 🆕 fishing-platform — 次のアクション

1. **http://133.88.117.175 を実機確認（最優先）**
   - `🌡 ヒートマップ` ON → 岸=赤橙・中央=青のサーモグラフィーが出るか
   - 釣具店・遊漁船が即座に表示されるか（Overpass検索なし）
   - ズームボタン右端70pxに表示されるか
   - SW v3が当たってブラウザキャッシュがクリアされているか（Ctrl+F5 or Dev Toolsで確認）

2. **Phase 5 開始判断**（tagishiの確認後）
   - 月額480円課金（Stripe）
   - 釣りブログ自動更新（SEO）
   - B2Bデータ販売
   - 遊漁船DB本格化（手数料5〜10%）

---

## dmm-manga-affiliate パイプライン状況

**Notion DB:** `NOTION_CONTENT_DB_ID=3731cad4aa98810e82f8c0f99a483cbb`

**ステータス遷移:**
```
queued → draft → approved → canva_pending → canva_ready → final → uploaded
  ↑         ↑        ↑            ↑              ↑           ↑        ↑
VPS Bot  Mac定時  tagishi     Mac定時          VPS       tagishi  VPS投稿
(済み)   (済み)            (済み)           (未実装)            (未実装)
```

**次にやること（dmm-manga-affiliate）:**
1. 4バリエーション対応に queue-processor.py を改修（1素材→4本）
2. Notion DBにアカウント管理フィールド追加（account_id・variant_num・source_group_id）
3. dmm-canva-assembler.py 実装（STEP 6: canva_pending → canva_ready）

---

## 認証情報・重要パス

| 項目 | 値 |
|---|---|
| VPS SSH | `ssh -i ~/.ssh/conoha_vps root@133.88.117.175` |
| VPS パス | `/opt/ai-brain/` |
| 認証情報 | `/opt/ai-brain/.credentials/tokens.md`（chmod 600） |
| GitHub リポジトリ | `coretagishi-lab/claude-brain`（main ブランチ） |
| Notion Outbox DB | `36f1cad4-aa98-81fb-93d8-d40bfb95cff9` |
| Notion コンテンツ審査DB | `3731cad4aa98810e82f8c0f99a483cbb` |
| Vault ローカル | `~/Desktop/ClaudeProjects/AI-Brain/` |
| 釣りマップ | http://133.88.117.175 |

---

## セッション開始チェックリスト

```bash
# 1. VPS待機タスク確認（最優先）
python3 Shared/Workflows/vps-task-checker.py

# 2. Inboxキュー確認
python3 Shared/Workflows/queue.py status

# 3. このファイルを読んだ → 作業開始
```
