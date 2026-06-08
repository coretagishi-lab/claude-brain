---
project_name: fishing-platform
current_status: active
priority: medium
due_date: ""
review_waiting: false
updated_at: 2026-06-09
---

## current_goal
- 釣り特化総合プラットフォーム（川ヒートマップ×釣果投稿SNS×フレンド・マッチング×遊漁船×釣具店）Phase 4 完了 → Phase 5（課金・SEO・B2B）へ進む

## 実装フェーズ

### Phase 1 ✅ 完了（2026-06-03）
- Leaflet.jsマップ表示・現在地表示
- 釣果投稿フォーム（魚種・サイズ・写真・公開設定3段階）
- FastAPI + SQLite バックエンド（VPS: 133.88.117.175）
- PWA対応

### Phase 2 ✅ 完了（2026-06-03）
- CartoDB Darkマップ（純黒・日本語ラベル維持）
- 起動時現在地自動取得（東京デフォルト）
- 釣具店表示（Overpass API）・遊漁船表示（HP確認済み7艘）
- 潮汐情報表示（月齢・干満）・AI釣りポイント提案（ルールベース・APIゼロ）

### Phase 3 ✅ 完了（2026-06-03）
- ユーザー認証（メール+パスワード・JWT・7日間トークン）
- 釣行中ステータス・釣りとも募集（半径50km）
- フレンド登録・プライベートルーム（集合場所マップ共有）
- ペアランク（ELOレーティング）・写真EXIFチェック

### Phase 4 ✅ 完了（2026-06-05）
- ✅ 生態データ9魚種（水温レンジ・活性時間・季節ピーク・ベイトパターン・生息地）
- ✅ 潮汐×月齢×時間帯×季節×水温の統合スコアリング
- ✅ 川ヒートマップ: pre-generated PNG タイル方式（/river-tiles/{z}/{x}/{y}.png、z13〜15）
- ✅ データソース: 国土数値情報API（国交省公式）→ kanto_rivers.geojson 自動更新
- ✅ VPS メモリ最適化: SQLite 川キャッシュ（-200MB）
- ✅ タイル URL バグ修正: /static/river-tiles/ → /river-tiles/（2026-06-05）
- 🔲 遊漁船DB本格化（手数料5〜10%）

### Phase 5（次フェーズ）
- 釣りブログ自動更新（SEO）
- 月額480円課金（Stripe）
- B2Bデータ販売
- 釣具メーカー広告枠

### Phase 6（長期）
- HTTPS化（Let's Encrypt）
- 全国タイル拡張・月額課金深化・B2B本格展開

## 技術スタック
- Backend: FastAPI + SQLite（VPS: 133.88.117.175）
- Frontend: Leaflet.js + Vanilla JS（PWA）
- ヒートマップ: L.tileLayer + pre-generated PNG tiles（z13〜15）
- 川データ: 国土数値情報API → kanto_rivers.geojson（起動時自動更新）
- Auth: JWT（PyJWT）+ bcrypt
- Nginx: ポート80リバースプロキシ → 8080

## next_action
- ブラウザでヒートマップボタンをタップして川GeoJSON描画を目視確認 → OKならPhase 5（課金・SEO・B2B）に進む

## blocker
- 遊漁船は現在ハードコード7艘のみ（本格DB化は Phase 5 以降）
- ヒートマップタイルは関東域（z13〜15）のみ生成済み。全国化は未着手

## latest_output

| type | name | path | url | updated_at |
|---|---|---|---|---|
| app | Phase 4 完了 | app/ | http://133.88.117.175 | 2026-06-05 |
| feature | 川ヒートマップタイル | /river-tiles/{z}/{x}/{y}.png | http://133.88.117.175 | 2026-06-05 |
| devlog | 開発全記録 | Projects/fishing-platform/DEVLOG.md | — | 2026-06-05 |
