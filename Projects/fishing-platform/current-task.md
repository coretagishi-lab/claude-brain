---
type: task
status: idle
checkpoint: ヒートマップ: ピクセル検出方式（SW v7）
updated_at: 2026-06-05
---

## checkpoint
CartoDB Darkタイルのピクセル色を読み取り水面(R<40,B>R,G<60)を検出してrgba(0,100,255,0.6)で塗る方式に変更完了。GeoJSON/Overpass依存をゼロにしてオフライン動作可能になった。

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
