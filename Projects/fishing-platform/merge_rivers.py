#!/usr/bin/env python3
"""
国土数値情報 W09 湖沼 SHP + OSM Overpass GeoJSON を統合して
tokyo_rivers_combined.geojson を生成する。
"""
import json, os, shapefile

SHP_PATH  = '/opt/ai-brain/Projects/fishing-platform/data/W09-05-g_Lake.shp'
OSM_PATH  = '/opt/ai-brain/Projects/fishing-platform/app/static/data/osm_rivers_tokyo.geojson'
OUT_PATH  = '/opt/ai-brain/Projects/fishing-platform/app/static/data/tokyo_rivers_combined.geojson'

# 取り込み範囲：東京＋近郊（釣り場として意味のあるエリア）
LAT_MIN, LAT_MAX = 35.2, 36.1
LON_MIN, LON_MAX = 139.3, 140.1


def shp_to_features():
    sf = shapefile.Reader(SHP_PATH, encoding='cp932')
    field_names = [f[0] for f in sf.fields[1:]]
    features = []
    for sr in sf.iterShapeRecords():
        shape = sr.shape
        if not shape.points:
            continue
        lons = [p[0] for p in shape.points]
        lats = [p[1] for p in shape.points]
        # bboxフィルタ
        if max(lons) < LON_MIN or min(lons) > LON_MAX:
            continue
        if max(lats) < LAT_MIN or min(lats) > LAT_MAX:
            continue

        # parts → リング配列
        pts   = shape.points
        parts = list(shape.parts) + [len(pts)]
        rings = []
        for i in range(len(shape.parts)):
            ring = [[round(p[0], 5), round(p[1], 5)]
                    for p in pts[parts[i]:parts[i+1]]]
            if len(ring) >= 4:
                rings.append(ring)
        if not rings:
            continue

        rec = dict(zip(field_names, sr.record))
        features.append({
            'type': 'Feature',
            'properties': {
                'name':   rec.get('W09_001', ''),
                'source': 'ksj',          # 国土数値情報
                'natural': 'water',
            },
            'geometry': {
                'type': 'Polygon',
                'coordinates': rings,
            }
        })
    return features


def main():
    # 1. 国土数値情報 SHP → features
    ksj_features = shp_to_features()
    print(f'国土数値情報 (KSJ) フィーチャー数: {len(ksj_features)}')
    for f in ksj_features:
        print(f'  {f["properties"]["name"]}')

    # 2. OSM GeoJSON 読み込み
    with open(OSM_PATH, encoding='utf-8') as fp:
        osm = json.load(fp)
    osm_features = osm.get('features', [])
    # sourceタグを付与
    for f in osm_features:
        f.setdefault('properties', {})['source'] = 'osm'
    print(f'OSM フィーチャー数: {len(osm_features)}')

    # 3. KSJ を先頭に統合（KSJはポリゴンのみなので下レイヤーとして描画）
    combined = ksj_features + osm_features

    geojson = {
        'type': 'FeatureCollection',
        'features': combined,
        'metadata': {
            'sources': ['osm', 'ksj-w09-lake'],
            'ksj_count': len(ksj_features),
            'osm_count': len(osm_features),
            'total':     len(combined),
        }
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as fp:
        json.dump(geojson, fp, separators=(',', ':'), ensure_ascii=False)

    kb = os.path.getsize(OUT_PATH) // 1024
    print(f'\n統合完了: {OUT_PATH}')
    print(f'  KSJ: {len(ksj_features)} + OSM: {len(osm_features)} = 合計 {len(combined)} フィーチャー')
    print(f'  ファイルサイズ: {kb} KB')
    return len(ksj_features), len(osm_features)


if __name__ == '__main__':
    main()
