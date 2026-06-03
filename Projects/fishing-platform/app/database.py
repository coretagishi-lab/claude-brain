import sqlite3, random, math, os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "fishing.db"

FISH_LIST = [
    {"id": "seabass",  "name": "シーバス",  "emoji": "🐟"},
    {"id": "chinu",    "name": "チヌ",      "emoji": "🐠"},
    {"id": "aji",      "name": "アジ",      "emoji": "🐡"},
    {"id": "mebaru",   "name": "メバル",    "emoji": "🐟"},
    {"id": "rockfish", "name": "根魚",      "emoji": "🪸"},
    {"id": "flounder", "name": "ヒラメ",    "emoji": "🐋"},
    {"id": "yellowtail","name": "ブリ",     "emoji": "🐟"},
    {"id": "squid",    "name": "イカ",      "emoji": "🦑"},
    {"id": "octopus",  "name": "タコ",      "emoji": "🐙"},
    {"id": "other",    "name": "その他",    "emoji": "🎣"},
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catches (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                fish_species  TEXT    NOT NULL,
                fish_emoji    TEXT    DEFAULT '🐟',
                size_cm       REAL,
                weight_g      REAL,
                lure_name     TEXT,
                memo          TEXT,
                exact_lat     REAL    NOT NULL,
                exact_lng     REAL    NOT NULL,
                display_lat   REAL,
                display_lng   REAL,
                privacy       TEXT    DEFAULT 'area'
                                CHECK(privacy IN ('exact','area','private')),
                photo_filename TEXT,
                caught_at     TEXT    DEFAULT (datetime('now','localtime')),
                user_id       TEXT    DEFAULT 'anonymous'
            )
        """)
        conn.commit()

def _blur(lat: float, lng: float, radius_km: float = 0.6) -> tuple[float, float]:
    """ランダムオフセットで座標をぼかす（デフォルト半径600m）"""
    r = radius_km / 111.0  # 緯度1度≒111km
    angle = random.uniform(0, 2 * math.pi)
    d = random.uniform(0.3, 1.0) * r
    return lat + d * math.cos(angle), lng + d * math.sin(angle) / math.cos(math.radians(lat))

def create_catch(data: dict) -> dict:
    lat, lng = data["lat"], data["lng"]
    privacy = data.get("privacy", "area")

    if privacy == "exact":
        dlat, dlng = lat, lng
    elif privacy == "area":
        dlat, dlng = _blur(lat, lng)
    else:  # private
        dlat, dlng = None, None

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO catches
               (fish_species, fish_emoji, size_cm, weight_g, lure_name, memo,
                exact_lat, exact_lng, display_lat, display_lng, privacy, photo_filename, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data["fish_species"], data.get("fish_emoji","🐟"),
             data.get("size_cm"), data.get("weight_g"),
             data.get("lure_name"), data.get("memo"),
             lat, lng, dlat, dlng, privacy,
             data.get("photo_filename"), data.get("user_id","anonymous"))
        )
        conn.commit()
        return get_catch(cur.lastrowid)

def get_catch(catch_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM catches WHERE id=?", (catch_id,)).fetchone()
        return dict(row) if row else None

def get_public_catches(bounds: dict | None = None, limit: int = 200) -> list[dict]:
    """publicなcatch（exact/area）を返す。private は除外。"""
    sql = """
        SELECT id, fish_species, fish_emoji, size_cm, lure_name, memo,
               display_lat AS lat, display_lng AS lng, privacy, photo_filename, caught_at
        FROM catches
        WHERE privacy != 'private'
          AND display_lat IS NOT NULL
    """
    params: list = []
    if bounds:
        sql += " AND display_lat BETWEEN ? AND ? AND display_lng BETWEEN ? AND ?"
        params += [bounds["s"], bounds["n"], bounds["w"], bounds["e"]]
    sql += " ORDER BY caught_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def get_heatmap_stats() -> list[dict]:
    """全投稿（private含む）をグリッド集計してヒートマップ用データを返す"""
    sql = """
        SELECT
            ROUND(exact_lat * 100) / 100 AS grid_lat,
            ROUND(exact_lng * 100) / 100 AS grid_lng,
            COUNT(*) AS count,
            fish_species
        FROM catches
        GROUP BY grid_lat, grid_lng, fish_species
    """
    with get_db() as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

def get_catch_counts() -> dict:
    """魚種別の総釣果数"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT fish_species, fish_emoji, COUNT(*) as cnt FROM catches GROUP BY fish_species ORDER BY cnt DESC"
        ).fetchall()
        return {r["fish_species"]: {"count": r["cnt"], "emoji": r["fish_emoji"]} for r in rows}
