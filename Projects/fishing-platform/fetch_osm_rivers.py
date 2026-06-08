#!/usr/bin/env python3
"""Fetch Tokyo 23-ward river/water data from Overpass API and save as GeoJSON."""
import json
import sys
import urllib.request
import urllib.parse
import os

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUT_PATH = "/opt/ai-brain/Projects/fishing-platform/app/static/data/osm_rivers_tokyo.geojson"

# Tokyo 23 wards bounding box (south,west,north,east)
BBOX = "35.53,139.57,35.82,139.92"

QUERY = f"""[out:json][timeout:180];
(
  way["waterway"~"^(river|canal|stream|drain)$"]({BBOX});
  way["waterway"="riverbank"]({BBOX});
  way["natural"="water"]({BBOX});
  relation["natural"="water"]["type"="multipolygon"]({BBOX});
  relation["waterway"="riverbank"]({BBOX});
);
out geom;
"""


def way_to_feature(el):
    geom = el.get("geometry", [])
    if not geom:
        return None
    coords = [[n["lon"], n["lat"]] for n in geom]
    tags = el.get("tags", {})
    natural = tags.get("natural", "")
    waterway = tags.get("waterway", "")

    is_area = (
        natural == "water" or
        waterway in ("riverbank", "dock", "basin") or
        (len(coords) >= 4 and coords[0] == coords[-1])
    )

    if is_area:
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        geometry = {"type": "Polygon", "coordinates": [coords]}
    else:
        geometry = {"type": "LineString", "coordinates": coords}

    return {"type": "Feature", "properties": tags, "geometry": geometry}


def relation_to_feature(el):
    outer_rings, inner_rings = [], []

    for m in el.get("members", []):
        if m.get("type") != "way":
            continue
        geom = m.get("geometry", [])
        if not geom:
            continue
        coords = [[n["lon"], n["lat"]] for n in geom]
        if len(coords) >= 3 and coords[0] != coords[-1]:
            coords.append(coords[0])
        if len(coords) < 4:
            continue
        if m.get("role") == "inner":
            inner_rings.append(coords)
        else:
            outer_rings.append(coords)

    if not outer_rings:
        return None

    rings = [outer_rings[0]] + inner_rings
    return {
        "type": "Feature",
        "properties": el.get("tags", {}),
        "geometry": {"type": "Polygon", "coordinates": rings}
    }


def osm_to_geojson(data):
    features = []
    for el in data.get("elements", []):
        if el["type"] == "way":
            f = way_to_feature(el)
            if f:
                features.append(f)
        elif el["type"] == "relation":
            f = relation_to_feature(el)
            if f:
                features.append(f)
    return {"type": "FeatureCollection", "features": features}


def main():
    print("Querying Overpass API for Tokyo 23-ward water features...")
    encoded = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(
        OVERPASS_URL, data=encoded,
        headers={"User-Agent": "fishing-platform/1.0"}
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        raw = json.loads(resp.read())

    n_elements = len(raw.get("elements", []))
    print(f"  Raw elements: {n_elements}")

    geojson = osm_to_geojson(raw)
    n_features = len(geojson["features"])
    print(f"  GeoJSON features: {n_features}")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(geojson, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUT_PATH) // 1024
    lines = sum(1 for feat in geojson["features"] if feat["geometry"]["type"] == "LineString")
    polys = sum(1 for feat in geojson["features"] if feat["geometry"]["type"] in ("Polygon", "MultiPolygon"))
    print(f"  Saved: {OUT_PATH} ({size_kb} KB)")
    print(f"  Lines: {lines}, Polygons: {polys}")
    return n_features, size_kb


if __name__ == "__main__":
    n, kb = main()
    print(f"\n✅ Done: {n} features, {kb} KB")
