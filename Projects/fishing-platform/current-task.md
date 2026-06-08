---
type: task
status: idle
checkpoint: /river-tiles オンデマンド生成エンドポイント追加・VPSデプロイ完了
updated_at: 2026-06-08
---

## checkpoint
FastAPIに `GET /river-tiles/{z}/{x}/{y}.png` エンドポイントを追加。ファイル存在→即FileResponse、未生成→CartoDB Darkダウンロード→川ピクセル検出→PNG生成→キャッシュ保存して返す。既存のgenerate_river_tiles.pyは未変更。ocean exclusionは単タイル生成では未適用（海岸部タイルは全面青になる仕様）。venvにPillow/numpy/scipy/requestsをインストール済み。

## checklist
- [x] PROJECT_STATUS.md 作成
- [x] Phase 1〜3 実装完了
- [x] Phase 4: 生態AIヒートマップ実装
- [x] 川データSQLite化（メモリ使用量 254MB→50MB）
- [x] ズーム別川表示フィルタ（関東全域半径制限撤廃）
- [x] GZip圧縮配信
- [x] SW v2（CDNキャッシュ強化）
- [x] 釣具店・遊漁船: タップでポップアップ修正
- [x] ヒートマップ橋下補完（waterway=river中心線ポリゴン二重レイヤー・SW v5）
- [x] ヒートマップ: ピクセル検出方式（CartoDB Darkタイル直接解析・SW v7）
- [ ] 遊漁船DB本格化（手数料5〜10%）
- [ ] HTTPS化（Let's Encrypt）
