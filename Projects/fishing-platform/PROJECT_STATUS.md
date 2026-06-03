---
project_name: fishing-platform
current_status: active
priority: medium
due_date: ""
review_waiting: false
updated_at: 2026-06-03
---

## current_goal
- 釣り特化総合プラットフォーム（AI釣りポイント予測×釣果投稿SNS×遊漁船比較予約×釣具店マップ）をフェーズ別に実装する

## 実装フェーズ

### Phase 1 ✅ 実装中（2026-06-03）
- Leaflet.js（OSM）マップ表示・現在地表示（Google Maps APIキー取得後に切り替え可）
- 釣果投稿フォーム（魚種・サイズ・写真・公開設定3段階）
- 投稿がマップ上にピンで表示
- FastAPI + SQLite バックエンド（VPS: 133.88.117.175:8080）
- PWA対応（スマホホーム画面追加可）

### Phase 2
- ユーザー認証（ログイン・アカウント作成）
- 釣果ヒートマップ（実釣果ベース）
- AIヒートマップ（潮汐・地形・常夜灯・水温・風・底質の公開データから予測）
- 魚種選択で習性ベースのマップ切り替え（シーバス・チヌ・アジ・メバル・根魚）
- 期間フィルター（月間・3ヶ月・1年・累積）
- マップ表示モード4種切替（①AI予測 ②実釣果 ③釣具店 ④遊漁船）

### Phase 3
- AI提案機能（潮汐・天気・水温・風からポイント提案＋理由説明）
- 論文ベース魚の視覚特性・行動生態ルールエンジン
- ベイトサイズ×季節×水温からルアーサイズ提案
- 水の色×光量×季節からルアーカラー提案
- Amazon/楽天アフィリリンク付きタックル提案
- YouTube動画リンク付き

### Phase 4
- 遊漁船データベース・比較・予約（手数料5〜10%）
- 釣具店マップ（OpenStreetMap + スクレイピング）
- 釣りブログ自動更新（SEO）

### Phase 5
- 月額480円課金機能（Stripe）
- B2Bデータ販売機能
- 釣具メーカー広告枠・フィールドテスト

## AIヒートマップ データソース（APIゼロ・無料）
- 潮汐・潮流：気象庁API
- 天気・風：OpenWeatherMap
- 水温：気象庁・JAXA
- 地形・底質：国土地理院
- 常夜灯：OpenStreetMap（highway=street_lamp）
- 小河川水深：航空写真＋画像AI推定

## 場所公開設定（3段階）
- 正確公開：座標そのまま公開
- エリア公開：半径500m〜1kmでぼかして公開（デフォルト）
- 完全非公開：自分のみ表示・ヒートマップカウントには匿名反映

## next_action
- Phase 1 実装をVPS（133.88.117.175:8080）にデプロイして動作確認する

## blocker
- Google Maps APIキー未取得（Phase 1はLeaflet+OSMで代替・取得後に切り替え）

## latest_output

| type | name | path | url | updated_at |
|---|---|---|---|---|
| html | preview/index.html | Projects/fishing-platform/preview/index.html | https://coretagishi-lab.github.io/claude-brain/Projects/fishing-platform/preview/ | 2026-06-03 |
| app | Phase 1 MVP | app/ | http://133.88.117.175:8080 | 2026-06-03 |
