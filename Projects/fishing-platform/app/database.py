import sqlite3, random, math, time as _time, threading
import bcrypt as _bcrypt
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "fishing.db"

FISH_LIST = [
    {"id": "seabass",    "name": "シーバス",  "emoji": "🐟"},
    {"id": "chinu",      "name": "チヌ",      "emoji": "🐠"},
    {"id": "aji",        "name": "アジ",      "emoji": "🐡"},
    {"id": "mebaru",     "name": "メバル",    "emoji": "🐟"},
    {"id": "rockfish",   "name": "根魚",      "emoji": "🪸"},
    {"id": "flounder",   "name": "ヒラメ",    "emoji": "🐋"},
    {"id": "yellowtail", "name": "ブリ",      "emoji": "🐟"},
    {"id": "squid",      "name": "イカ",      "emoji": "🦑"},
    {"id": "octopus",    "name": "タコ",      "emoji": "🐙"},
    {"id": "other",      "name": "その他",    "emoji": "🎣"},
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catches (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                fish_species   TEXT    NOT NULL,
                fish_emoji     TEXT    DEFAULT '🐟',
                size_cm        REAL,
                weight_g       REAL,
                lure_name      TEXT,
                memo           TEXT,
                exact_lat      REAL    NOT NULL,
                exact_lng      REAL    NOT NULL,
                display_lat    REAL,
                display_lng    REAL,
                privacy        TEXT    DEFAULT 'area'
                                  CHECK(privacy IN ('exact','area','private')),
                photo_filename TEXT,
                caught_at      TEXT    DEFAULT (datetime('now','localtime')),
                user_id        TEXT    DEFAULT 'anonymous'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT    UNIQUE NOT NULL,
                username        TEXT    NOT NULL,
                password_hash   TEXT    NOT NULL,
                bio             TEXT    DEFAULT '',
                instagram_id    TEXT    DEFAULT '',
                avatar_filename TEXT,
                is_fishing      INTEGER DEFAULT 0,
                last_lat        REAL,
                last_lng        REAL,
                rank_points     INTEGER DEFAULT 1000,
                created_at      TEXT    DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_id INTEGER NOT NULL,
                addressee_id INTEGER NOT NULL,
                status       TEXT DEFAULT 'pending' CHECK(status IN ('pending','accepted','declined')),
                created_at   TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (requester_id) REFERENCES users(id),
                FOREIGN KEY (addressee_id) REFERENCES users(id),
                UNIQUE(requester_id, addressee_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id     INTEGER NOT NULL,
                user2_id     INTEGER NOT NULL,
                meeting_lat  REAL,
                meeting_lng  REAL,
                meeting_label TEXT,
                status       TEXT DEFAULT 'active',
                created_at   TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (user1_id) REFERENCES users(id),
                FOREIGN KEY (user2_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rank_matches (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id      INTEGER,
                winner_id    INTEGER NOT NULL,
                loser_id     INTEGER NOT NULL,
                winner_fish  TEXT,
                loser_fish   TEXT,
                winner_size  REAL,
                loser_size   REAL,
                catch_photo  TEXT,
                exif_valid   INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (winner_id) REFERENCES users(id),
                FOREIGN KEY (loser_id)  REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS osm_rivers (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT    DEFAULT '',
                width     REAL,
                length_km REAL    DEFAULT 0,
                nodes_json TEXT   NOT NULL,
                min_lat   REAL    NOT NULL,
                max_lat   REAL    NOT NULL,
                min_lng   REAL    NOT NULL,
                max_lng   REAL    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rivers_bbox ON osm_rivers(min_lat, max_lat, min_lng, max_lng)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS osm_weirs (
                id  INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL,
                lng REAL NOT NULL
            )
        """)
        conn.commit()

# ── Catches ───────────────────────────────────────────────────
def _blur(lat: float, lng: float, radius_km: float = 0.6) -> tuple:
    r = radius_km / 111.0
    angle = random.uniform(0, 2 * math.pi)
    d = random.uniform(0.3, 1.0) * r
    return lat + d * math.cos(angle), lng + d * math.sin(angle) / math.cos(math.radians(lat))

def create_catch(data: dict) -> dict:
    lat, lng = data["lat"], data["lng"]
    privacy = data.get("privacy", "area")
    dlat, dlng = (lat, lng) if privacy == "exact" else (_blur(lat, lng) if privacy == "area" else (None, None))
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO catches (fish_species, fish_emoji, size_cm, weight_g, lure_name, memo,
               exact_lat, exact_lng, display_lat, display_lng, privacy, photo_filename, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data["fish_species"], data.get("fish_emoji","🐟"), data.get("size_cm"), data.get("weight_g"),
             data.get("lure_name"), data.get("memo"), lat, lng, dlat, dlng, privacy,
             data.get("photo_filename"), data.get("user_id","anonymous"))
        )
        conn.commit()
        return get_catch(cur.lastrowid)

def get_catch(catch_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM catches WHERE id=?", (catch_id,)).fetchone()
        return dict(row) if row else None

def _period_clause(period: str | None) -> str:
    return {"1m": "AND caught_at >= datetime('now','localtime','-30 days')",
            "3m": "AND caught_at >= datetime('now','localtime','-90 days')",
            "1y": "AND caught_at >= datetime('now','localtime','-365 days')"}.get(period or "", "")

def get_public_catches(bounds=None, limit: int = 200, period: str = None, species: str = None) -> list:
    parts = ["SELECT id, fish_species, fish_emoji, size_cm, lure_name, memo,",
             "       display_lat AS lat, display_lng AS lng, privacy, photo_filename, caught_at",
             "FROM catches WHERE privacy != 'private' AND display_lat IS NOT NULL", _period_clause(period)]
    params = []
    if species: parts.append("AND fish_species = ?"); params.append(species)
    if bounds:
        parts.append("AND display_lat BETWEEN ? AND ? AND display_lng BETWEEN ? AND ?")
        params += [bounds["s"], bounds["n"], bounds["w"], bounds["e"]]
    parts += ["ORDER BY caught_at DESC LIMIT ?"]; params.append(limit)
    with get_db() as conn:
        return [dict(r) for r in conn.execute(" ".join(parts), params).fetchall()]

def get_heatmap_stats(period: str = None, species: str = None) -> list:
    parts = ["SELECT ROUND(exact_lat*100)/100 AS grid_lat, ROUND(exact_lng*100)/100 AS grid_lng,",
             "       COUNT(*) AS count, fish_species FROM catches WHERE 1=1", _period_clause(period)]
    params = []
    if species: parts.append("AND fish_species = ?"); params.append(species)
    parts.append("GROUP BY grid_lat, grid_lng, fish_species")
    with get_db() as conn:
        return [dict(r) for r in conn.execute(" ".join(parts), params).fetchall()]

def get_catch_counts() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT fish_species, fish_emoji, COUNT(*) as cnt FROM catches GROUP BY fish_species ORDER BY cnt DESC"
        ).fetchall()
        return {r["fish_species"]: {"count": r["cnt"], "emoji": r["fish_emoji"]} for r in rows}

# ── 潮汐・AI提案 ───────────────────────────────────────────────
_REF_NEW_MOON = datetime(2024, 1, 11, 11, 57)
_LUNAR_CYCLE  = 29.53059

def _lunar_phase() -> float:
    return ((datetime.now() - _REF_NEW_MOON).total_seconds() / 86400 % _LUNAR_CYCLE) / _LUNAR_CYCLE

def get_tides() -> dict:
    now = datetime.now(); phase = _lunar_phase()
    moon_labels = [(0.0625,"🌑 新月"),(0.1875,"🌒 三日月"),(0.3125,"🌓 上弦の月"),
                   (0.4375,"🌔 十三夜"),(0.5625,"🌕 満月"),(0.6875,"🌖 十六夜"),
                   (0.8125,"🌗 下弦の月"),(1.0001,"🌘 二十六夜")]
    moon_phase = next(name for limit, name in moon_labels if phase < limit)
    amp = abs(math.cos(phase * 2 * math.pi))
    tide_type = "大潮" if amp > 0.8 else ("中潮" if amp > 0.5 else ("小潮" if amp > 0.2 else "長潮"))
    hour = now.hour + now.minute / 60
    tide_val = math.sin(hour * 2 * math.pi / 12.42)
    current = "満潮" if tide_val > 0.5 else ("干潮" if tide_val < -0.5 else ("上げ潮" if tide_val > 0 else "下げ潮"))
    def _next(ta): h = ((ta - (hour*2*math.pi/12.42)%(2*math.pi)) % (2*math.pi))/(2*math.pi)*12.42; return (now+timedelta(hours=h)).strftime("%H:%M")
    return {"moon_phase": moon_phase, "tide_type": tide_type, "current": current,
            "tide_level": round(tide_val,2), "next_high": _next(math.pi/2), "next_low": _next(3*math.pi/2), "amp": round(amp,2)}

_SEASON_FISH = {
    1:[("メバル","常夜灯・磯"),("カサゴ","根回り"),("シーバス","河口明暗部")],
    2:[("メバル","常夜灯・磯"),("カサゴ","根回り"),("シーバス","河口明暗部")],
    3:[("シーバス","河口・橋脚"),("メバル","磯堤防"),("アジ","常夜灯周り")],
    4:[("シーバス","シャロー"),("チヌ","藻場・河口"),("アジ","漁港")],
    5:[("チヌ","シャロー藻場"),("タコ","砂底"),("アジ","漁港常夜灯")],
    6:[("タコ","砂底テトラ"),("チヌ","ウェーディング"),("アジ","常夜灯")],
    7:[("タコ","砂底"),("アジ","常夜灯"),("イカ","漁港堤防")],
    8:[("タコ","砂底"),("アジ","常夜灯"),("イカ","漁港堤防")],
    9:[("シーバス","河口サーフ"),("チヌ","河口港"),("アジ","常夜灯")],
    10:[("シーバス","河口橋脚"),("ブリ","沖回遊"),("アジ","漁港")],
    11:[("シーバス","河口明暗"),("ブリ","沖"),("メバル","磯")],
    12:[("シーバス","河口橋脚"),("メバル","夜磯"),("カサゴ","根回り")],
}

def get_fishing_suggestion() -> dict:
    now = datetime.now(); tides = get_tides(); hour = now.hour
    time_rows = [(4,7,"朝マヅメ",5,"最高の時間帯！一日で最も活性が高くなります"),
                 (7,10,"朝",3,"朝マヅメの余韻あり。表層系ルアーで探りましょう"),
                 (10,15,"昼",2,"日中は活性低め。根魚・タコなど底物が狙い目"),
                 (15,18,"夕方",3,"夕マヅメに向けて活性が上昇中"),
                 (18,21,"夕マヅメ",5,"最高の時間帯！日没後30分が黄金時間")]
    time_name, time_score, time_msg = "夜", 3, "常夜灯ナイトゲームが有効。メバル・アジ・シーバス"
    for s, e, name, score, msg in time_rows:
        if s <= hour < e: time_name, time_score, time_msg = name, score, msg; break
    tide_msgs = {"満潮":"潮止まり前後。シャローに魚が差してきます","干潮":"潮止まり前後。深場・水路出口を狙いましょう",
                 "上げ潮":"釣りの好機！上げ3分が定番ポイント","下げ潮":"下げ7分が狙い目。流れのヨレを攻めましょう"}
    tide_score = 5 if tides["amp"] > 0.7 else (3 if tides["amp"] > 0.4 else 2)
    n = min(5, (time_score + tide_score) // 2)
    return {"date": now.strftime("%Y年%m月%d日 %H:%M"), "overall_score": "⭐"*n + "☆"*(5-n),
            "time_name": time_name, "time_msg": time_msg, "tide_current": tides["current"],
            "tide_type": tides["tide_type"], "tide_msg": tide_msgs.get(tides["current"],""),
            "moon_phase": tides["moon_phase"], "next_high": tides["next_high"], "next_low": tides["next_low"],
            "targets": [{"fish": f, "spot": s} for f, s in _SEASON_FISH.get(now.month, [("シーバス","河口")])]}

# ── User auth ─────────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())

def create_user(email: str, username: str, password: str) -> dict | None:
    pw_hash = hash_password(password)
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, username, password_hash) VALUES (?,?,?)",
                (email.lower(), username, pw_hash))
            conn.commit()
            return get_user_by_id(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None

def get_user_by_email(email: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
        return dict(row) if row else None

def get_user_by_id(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def update_user_profile(user_id: int, data: dict) -> dict | None:
    fields = {k: v for k, v in data.items() if k in ("username","bio","instagram_id","avatar_filename") and v is not None}
    if not fields: return get_user_by_id(user_id)
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", [*fields.values(), user_id])
        conn.commit()
    return get_user_by_id(user_id)

def update_fishing_status(user_id: int, is_fishing: bool, lat: float = None, lng: float = None) -> dict | None:
    with get_db() as conn:
        conn.execute("UPDATE users SET is_fishing=?, last_lat=?, last_lng=? WHERE id=?",
                     (1 if is_fishing else 0, lat, lng, user_id))
        conn.commit()
    return get_user_by_id(user_id)

def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1); dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def get_fishing_users_nearby(lat: float, lng: float, radius_km: float = 20, exclude_id: int = None) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, bio, instagram_id, avatar_filename, last_lat, last_lng, rank_points FROM users WHERE is_fishing=1 AND last_lat IS NOT NULL"
        ).fetchall()
    result = []
    for r in rows:
        d = _haversine(lat, lng, r["last_lat"], r["last_lng"])
        if d <= radius_km and r["id"] != exclude_id:
            u = dict(r); u["distance_km"] = round(d, 1); result.append(u)
    return sorted(result, key=lambda x: x["distance_km"])

# ── Friends ───────────────────────────────────────────────────
def send_friend_request(requester_id: int, addressee_id: int) -> dict | None:
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO friends (requester_id, addressee_id) VALUES (?,?)",
                (requester_id, addressee_id))
            conn.commit()
            row = conn.execute("SELECT * FROM friends WHERE id=?", (cur.lastrowid,)).fetchone()
            return dict(row)
    except sqlite3.IntegrityError:
        return None

def get_friends(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT f.id, f.status, f.created_at,
                   CASE WHEN f.requester_id=? THEN f.addressee_id ELSE f.requester_id END AS friend_id,
                   CASE WHEN f.requester_id=? THEN 'sent' ELSE 'received' END AS direction,
                   u.username, u.avatar_filename, u.rank_points, u.is_fishing
            FROM friends f
            JOIN users u ON u.id = (CASE WHEN f.requester_id=? THEN f.addressee_id ELSE f.requester_id END)
            WHERE (f.requester_id=? OR f.addressee_id=?) AND f.status != 'declined'
        """, (user_id,)*5).fetchall()
        return [dict(r) for r in rows]

def respond_friend_request(friend_id: int, status: str, user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM friends WHERE id=? AND addressee_id=?", (friend_id, user_id)).fetchone()
        if not row: return None
        conn.execute("UPDATE friends SET status=? WHERE id=?", (status, friend_id))
        conn.commit()
        if status == "accepted":
            return create_room(row["requester_id"], row["addressee_id"])
        return dict(conn.execute("SELECT * FROM friends WHERE id=?", (friend_id,)).fetchone())

# ── Rooms ─────────────────────────────────────────────────────
def create_room(user1_id: int, user2_id: int) -> dict | None:
    existing = get_room_by_users(user1_id, user2_id)
    if existing: return existing
    with get_db() as conn:
        cur = conn.execute("INSERT INTO rooms (user1_id, user2_id) VALUES (?,?)", (user1_id, user2_id))
        conn.commit()
        return get_room(cur.lastrowid, user1_id)

def get_room_by_users(u1: int, u2: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM rooms WHERE status='active' AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))",
            (u1, u2, u2, u1)).fetchone()
        return dict(row) if row else None

def get_room(room_id: int, user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM rooms WHERE id=? AND (user1_id=? OR user2_id=?)",
            (room_id, user_id, user_id)).fetchone()
        if not row: return None
        room = dict(row)
        partner_id = room["user2_id"] if room["user1_id"] == user_id else room["user1_id"]
        partner = conn.execute(
            "SELECT id, username, avatar_filename, rank_points, is_fishing, last_lat, last_lng FROM users WHERE id=?",
            (partner_id,)).fetchone()
        if partner: room["partner"] = dict(partner)
        return room

def get_user_rooms(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM rooms WHERE (user1_id=? OR user2_id=?) AND status='active' ORDER BY created_at DESC",
            (user_id, user_id)).fetchall()
        return [dict(r) for r in rows]

def update_room_meeting(room_id: int, user_id: int, lat: float, lng: float, label: str) -> dict | None:
    with get_db() as conn:
        conn.execute("UPDATE rooms SET meeting_lat=?, meeting_lng=?, meeting_label=? WHERE id=? AND (user1_id=? OR user2_id=?)",
                     (lat, lng, label, room_id, user_id, user_id))
        conn.commit()
    return get_room(room_id, user_id)

# ── Pair rank ─────────────────────────────────────────────────
def _elo(winner_pts: int, loser_pts: int, K: int = 32) -> tuple:
    exp = 1 / (1 + 10 ** ((loser_pts - winner_pts) / 400))
    return round(winner_pts + K * (1 - exp)), round(loser_pts + K * (0 - (1 - exp)))

def submit_rank_match(room_id: int, winner_id: int, loser_id: int, data: dict) -> dict:
    winner = get_user_by_id(winner_id); loser = get_user_by_id(loser_id)
    if not winner or not loser: return {}
    new_w, new_l = _elo(winner["rank_points"], loser["rank_points"])
    with get_db() as conn:
        conn.execute("UPDATE users SET rank_points=? WHERE id=?", (new_w, winner_id))
        conn.execute("UPDATE users SET rank_points=? WHERE id=?", (new_l, loser_id))
        cur = conn.execute(
            "INSERT INTO rank_matches (room_id, winner_id, loser_id, winner_fish, loser_fish, winner_size, loser_size, catch_photo, exif_valid) VALUES (?,?,?,?,?,?,?,?,?)",
            (room_id, winner_id, loser_id, data.get("winner_fish"), data.get("loser_fish"),
             data.get("winner_size"), data.get("loser_size"), data.get("catch_photo"), int(data.get("exif_valid", True))))
        conn.commit()
        return {"match_id": cur.lastrowid, "winner_new_pts": new_w, "loser_new_pts": new_l,
                "winner_delta": new_w - winner["rank_points"], "loser_delta": new_l - loser["rank_points"]}

def get_leaderboard(limit: int = 20) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, avatar_filename, rank_points, is_fishing FROM users ORDER BY rank_points DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

# ── Phase 4: 生態データ & AIスコアリング ─────────────────────────

SPECIES_ECOLOGY = {
    "シーバス": {
        "temp_range":(14,25),"temp_peak":(18,23),
        "tide_pref":"rising",
        "time_pref":[20,21,22,23,0,1,2,3,4,5],
        "season_peak":[9,10,11,4,5,6],
        "bait":["イワシ","コウナゴ","ボラ"],
        "habitat":"橋脚・明暗部・河川合流点・潮目",
    },
    "チヌ": {
        "temp_range":(15,28),"temp_peak":(20,26),
        "tide_pref":"any",
        "time_pref":list(range(24)),
        "season_peak":[5,6,7,8,9,10],
        "bait":["カニ","イガイ","カキ"],
        "habitat":"ゴロタ石・カキ瀬・藻場・濁り水",
    },
    "アジ": {
        "temp_range":(10,22),"temp_peak":(14,20),
        "tide_pref":"any",
        "time_pref":[18,19,20,21,22,23,0,1,2,3,4,5,6],
        "season_peak":[4,5,6,7,8,9,10],
        "bait":["アミ","プランクトン"],
        "habitat":"常夜灯周り・漁港・潮通しの良い場所",
    },
    "メバル": {
        "temp_range":(8,18),"temp_peak":(10,16),
        "tide_pref":"any",
        "time_pref":[18,19,20,21,22,23,0,1,2,3,4,5],
        "season_peak":[2,3,4,11,12,1],
        "bait":["アミ","小魚"],
        "habitat":"常夜灯・磯・テトラ・構造物",
    },
    "根魚": {
        "temp_range":(8,20),"temp_peak":(12,18),
        "tide_pref":"any",
        "time_pref":list(range(24)),
        "season_peak":[1,2,3,4,10,11,12],
        "bait":["カニ","エビ","小魚"],
        "habitat":"岩礁・テトラ・堤防基部",
    },
    "ヒラメ": {
        "temp_range":(12,22),"temp_peak":(15,20),
        "tide_pref":"rising",
        "time_pref":[4,5,6,7,17,18,19,20],
        "season_peak":[10,11,3,4,5],
        "bait":["イワシ","コウナゴ"],
        "habitat":"砂底サーフ・河口・流れの変化点",
    },
    "ブリ": {
        "temp_range":(15,25),"temp_peak":(18,22),
        "tide_pref":"any",
        "time_pref":[5,6,7,8,17,18,19,20],
        "season_peak":[10,11,12,1],
        "bait":["イワシ","アジ","サバ"],
        "habitat":"潮目・岬周り・沖磯",
    },
    "イカ": {
        "temp_range":(15,25),"temp_peak":(18,23),
        "tide_pref":"any",
        "time_pref":[18,19,20,21,22,23,0,1,2,3],
        "season_peak":[4,5,6,7,8,9],
        "bait":["小魚"],
        "habitat":"常夜灯・漁港・藻場",
    },
    "タコ": {
        "temp_range":(16,26),"temp_peak":(20,25),
        "tide_pref":"any",
        "time_pref":list(range(24)),
        "season_peak":[6,7,8,9],
        "bait":["カニ","エビ"],
        "habitat":"砂底・テトラ・岩礁",
    },
}

def _geo_variation(lat: float, lng: float) -> float:
    x, y = lat * 47.3, lng * 38.7
    v = (math.sin(x)*math.cos(y) +
         math.sin(x*2.3+0.7)*math.cos(y*1.7+0.3) +
         math.sin(x*0.5+1.1)*math.cos(y*3.1+0.9)) / 3
    return (v + 1) / 4  # 0.0–0.5

def _score_ecology(species: str, env: dict) -> float:
    eco = SPECIES_ECOLOGY.get(species)
    if not eco:
        return 0.5
    now = datetime.now()
    scores, weights = [], []
    # 水温スコア (2.5)
    temp = env.get("sea_temp", 18.0)
    t_lo, t_hi = eco["temp_range"]; t_pk_lo, t_pk_hi = eco["temp_peak"]
    if t_lo <= temp <= t_hi:
        if t_pk_lo <= temp <= t_pk_hi:
            ts = 1.0
        elif temp < t_pk_lo:
            ts = 0.5 + 0.5*(temp-t_lo)/max(1, t_pk_lo-t_lo)
        else:
            ts = 0.5 + 0.5*(t_hi-temp)/max(1, t_hi-t_pk_hi)
    else:
        ts = max(0.0, 1.0 - min(abs(temp-t_lo), abs(temp-t_hi))/5)
    scores.append(ts); weights.append(2.5)
    # 時間帯スコア (1.5)
    h = now.hour
    if h in eco["time_pref"]:
        tos = 1.0
    else:
        min_d = min(min(abs(h-p), 24-abs(h-p)) for p in eco["time_pref"])
        tos = max(0, 1.0 - min_d/5.0)
    scores.append(tos); weights.append(1.5)
    # 季節スコア (1.5)
    m = now.month
    if m in eco["season_peak"]:
        ss = 1.0
    else:
        min_d = min(min(abs(m-sp), 12-abs(m-sp)) for sp in eco["season_peak"])
        ss = max(0.15, 1.0 - min_d/3.0)
    scores.append(ss); weights.append(1.5)
    # 潮スコア (1.0)
    tc = env.get("tide_current", "")
    tp = eco["tide_pref"]
    if tp == "any":
        tds = 0.75
    elif tp == "rising" and "上げ" in tc:
        tds = 1.0
    elif tp == "falling" and "下げ" in tc:
        tds = 1.0
    else:
        tds = 0.4
    scores.append(tds); weights.append(1.0)
    # 潮汐振幅 (0.5)
    scores.append(min(1.0, env.get("tide_amp", 0.5)*1.3)); weights.append(0.5)
    tw = sum(weights)
    return sum(s*w for s, w in zip(scores, weights)) / tw

def _get_env_data(lat: float, lng: float) -> dict:
    import urllib.request, json as _json
    env: dict = {}
    # 潮汐データ（ローカル）
    try:
        t = get_tides()
        env.update(tide_current=t["current"], tide_type=t["tide_type"],
                   moon_phase=t["moon_phase"], tide_amp=t["amp"])
    except:
        env.update(tide_current="", tide_type="", moon_phase="", tide_amp=0.5)
    # Open-Meteo 気象データ（無料・APIキー不要）
    try:
        url = (f"https://api.open-meteo.com/v1/forecast"
               f"?latitude={lat:.4f}&longitude={lng:.4f}&current_weather=true&forecast_days=1")
        req = urllib.request.Request(url, headers={"User-Agent": "AnglerMap/4.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = _json.loads(r.read())
            cw = d.get("current_weather", {})
            env.update(air_temp=float(cw.get("temperature", 18)),
                       wind_speed=float(cw.get("windspeed", 0)),
                       wind_dir=float(cw.get("winddirection", 0)))
    except:
        env.update(air_temp=18.0, wind_speed=0.0, wind_dir=0.0)
    # Open-Meteo Marine API 海面水温（無料・APIキー不要）
    try:
        url = (f"https://marine-api.open-meteo.com/v1/marine"
               f"?latitude={lat:.4f}&longitude={lng:.4f}"
               f"&current=sea_surface_temperature&forecast_days=1")
        req = urllib.request.Request(url, headers={"User-Agent": "AnglerMap/4.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = _json.loads(r.read())
            sst = d.get("current", {}).get("sea_surface_temperature")
            env["sea_temp"] = float(sst) if sst is not None else env["air_temp"] - 1
    except:
        seasonal = {1:13,2:12,3:13,4:16,5:18,6:21,7:25,8:27,9:25,10:22,11:18,12:15}
        env["sea_temp"] = seasonal.get(datetime.now().month, 18)
    return env

def get_ecological_heatmap(lat: float, lng: float, species: str = "シーバス", radius_km: float = 20) -> dict:
    env = _get_env_data(lat, lng)
    base = _score_ecology(species, env)
    lat_step = 0.018
    lng_step = lat_step / max(0.1, math.cos(math.radians(lat)))
    steps = max(1, int(radius_km / 2.0))
    points = []
    for di in range(-steps, steps+1):
        for dj in range(-steps, steps+1):
            g_lat = lat + di * lat_step
            g_lng = lng + dj * lng_step
            dlat = (g_lat - lat) * 111
            dlng = (g_lng - lng) * 111 * math.cos(math.radians(lat))
            if math.sqrt(dlat**2 + dlng**2) > radius_km:
                continue
            geo = _geo_variation(g_lat, g_lng)
            score = round(min(1.0, base*0.72 + geo*0.28), 3)
            if score > 0.05:
                points.append({"lat": round(g_lat, 4), "lng": round(g_lng, 4), "score": score})
    eco = SPECIES_ECOLOGY.get(species, {})
    return {
        "points": points,
        "env": {
            "sea_temp":  round(env.get("sea_temp", 18), 1),
            "air_temp":  round(env.get("air_temp", 18), 1),
            "wind_speed": round(env.get("wind_speed", 0), 1),
            "wind_dir":  int(env.get("wind_dir", 0)),
            "tide_current": env.get("tide_current", ""),
            "tide_type": env.get("tide_type", ""),
            "moon_phase": env.get("moon_phase", ""),
            "base_score": round(base, 2),
        },
        "species": species,
        "habitat": eco.get("habitat", ""),
        "bait": eco.get("bait", []),
    }

# ── Phase 5: 川ヒートマップ（シーバス特化）────────────────────────

_river_cache:    dict = {}
_RIVER_CACHE_TTL = 7200  # 2時間（川データは変わらない）

_ZOOM_INTERVAL = {10:400, 11:200, 12:100, 13:50, 14:20, 15:10}   # m/点
_ZOOM_RADIUS_R = {10:28,  11:20,  12:13,  13:9,   14:6,  15:3}   # km（レガシー用）

# ── シーバス精密スコアリング ─────────────────────────────────────────
_river_score_cache: dict = {}
_RIVER_SCORE_CACHE_TTL  = 3600  # 1時間

# 既知の橋脚・合流点ランドマーク（実データ・精密スコアリング用）
_SEABASS_LANDMARKS = [
    # (lat, lng, type, bonus, name)
    # 江戸川 橋脚
    (35.6891, 139.8934, "bridge_pier", 50, "篠崎橋"),
    (35.7012, 139.8845, "bridge_pier", 50, "江戸川橋"),
    (35.7234, 139.8756, "bridge_pier", 50, "新葛飾橋"),
    (35.7456, 139.8623, "bridge_pier", 50, "葛飾橋"),
    # 江戸川 合流点
    (35.6823, 139.8912, "confluence",  45, "中川合流"),
    (35.7180, 139.8712, "confluence",  40, "新中川分岐"),
    # 隅田川 橋脚・合流点
    (35.6948, 139.7887, "bridge_pier", 50, "清洲橋"),
    (35.6863, 139.7961, "bridge_pier", 50, "永代橋"),
    (35.6782, 139.7823, "bridge_pier", 50, "勝鬨橋"),
    (35.7034, 139.8023, "confluence",  45, "北十間川合流"),
    # 荒川 橋脚・合流点
    (35.7423, 139.8234, "bridge_pier", 50, "木根川橋"),
    (35.7689, 139.7812, "confluence",  45, "綾瀬川合流"),
    # 多摩川 橋脚
    (35.5701, 139.7123, "bridge_pier", 50, "六郷橋"),
    (35.5823, 139.7234, "bridge_pier", 50, "ガス橋"),
    # 鶴見川
    (35.5012, 139.6823, "confluence",  40, "早淵川合流"),
]


def _get_river_scoring_features(bbox_str: str) -> dict:
    """橋・常夜灯・排水口・水門をOverpassから取得（TTLキャッシュ付き）"""
    bucket = f"RSF_{bbox_str}"
    now = _time.time()
    if bucket in _river_score_cache:
        ts, data = _river_score_cache[bucket]
        if now - ts < _RIVER_SCORE_CACHE_TTL:
            return data

    query = (
        f"[out:json][timeout:25];\n("
        f'way["bridge"="yes"]({bbox_str});'
        f'node["highway"="street_lamp"]({bbox_str});'
        f'node["man_made"="outfall"]({bbox_str});'
        f'node["waterway"~"weir|sluice_gate|floodgate"]({bbox_str});'
        f");\nout geom center;"
    )
    raw = _overpass_fetch_osm(query)

    bridges     = []  # (lat, lng, height_or_None)
    lamps       = []  # (lat, lng)
    outfalls    = []  # (lat, lng)
    water_gates = []  # (lat, lng)

    for el in raw.get("elements", []):
        tags  = el.get("tags", {})
        etype = el.get("type", "")
        if etype == "way" and tags.get("bridge") == "yes":
            center = el.get("center") or {}
            la, lo = center.get("lat"), center.get("lon")
            if la and lo:
                try:
                    h = float(str(tags.get("maxheight","")).replace("m","").strip())
                except Exception:
                    h = None
                bridges.append((float(la), float(lo), h))
        elif etype == "node":
            la, lo = el.get("lat"), el.get("lon")
            if not (la and lo): continue
            la, lo = float(la), float(lo)
            ww = tags.get("waterway","")
            hw = tags.get("highway","")
            mm = tags.get("man_made","")
            if ww in ("weir","sluice_gate","floodgate"):
                water_gates.append((la, lo))
            elif hw == "street_lamp":
                lamps.append((la, lo))
            elif mm == "outfall":
                outfalls.append((la, lo))

    result = {"bridges": bridges, "lamps": lamps, "outfalls": outfalls, "water_gates": water_gates}
    _river_score_cache[bucket] = (_time.time(), result)
    return result


def _score_seabass_point(g_lat: float, g_lng: float,
                          scoring_feats: dict, tides: dict) -> float:
    """川上のポイントをシーバス釣りスコアで評価（0-100）"""
    water_gates = scoring_feats.get("water_gates", [])
    bridges     = scoring_feats.get("bridges",     [])
    lamps       = scoring_feats.get("lamps",       [])
    outfalls    = scoring_feats.get("outfalls",    [])

    # 水門100m以内は除外
    for wla, wlo in water_gates:
        if _dist_km(g_lat, g_lng, wla, wlo) < 0.1:
            return 0.0

    score = 15.0  # ベーススコア（川上であること）

    # 既知ランドマーク（橋脚・合流点）スコアリング
    # max_landmark_bonus: 赤判定の基準（20以上なら赤許可）
    max_landmark_bonus = 0.0
    for bla, blo, btype, bonus, _ in _SEABASS_LANDMARKS:
        d_m = _dist_km(g_lat, g_lng, bla, blo) * 1000
        if btype == "bridge_pier":
            if d_m < 10:   lb = bonus
            elif d_m < 40: lb = bonus * (1 - (d_m - 10) / 30)
            else:          lb = 0.0
        elif btype == "confluence":
            lb = bonus * (1 - d_m / 50) if d_m < 50 else 0.0
        else:
            lb = 0.0
        if lb > 0:
            score += lb
            max_landmark_bonus = max(max_landmark_bonus, lb)

    # OSM橋ボーナス（最大値のみ採用・スタッキング防止）
    max_bridge = 0.0
    for bla, blo, bh in bridges:
        d_m = _dist_km(g_lat, g_lng, bla, blo) * 1000
        if d_m < 20:
            bridge_bonus = 35
            if bh is not None:
                if bh <= 5:    bridge_bonus += 15
                elif bh >= 10: bridge_bonus -= 5
            max_bridge = max(max_bridge, bridge_bonus * (1 - d_m / 20))
    score += max_bridge

    # 常夜灯ボーナス（最大値のみ採用・スタッキング防止）
    max_lamp = 0.0
    for lla, llo in lamps:
        d_m = _dist_km(g_lat, g_lng, lla, llo) * 1000
        if d_m < 30:
            max_lamp = max(max_lamp, 35 * (1 - d_m / 30))
    score += max_lamp

    # 排水口ボーナス（最大値のみ採用・スタッキング防止）
    max_outfall = 0.0
    for ola, olo in outfalls:
        d_m = _dist_km(g_lat, g_lng, ola, olo) * 1000
        if d_m < 20:
            max_outfall = max(max_outfall, 30 * (1 - d_m / 20))
    score += max_outfall

    # 潮汐ボーナス（下げ潮が最高）
    tide_current = tides.get("current", "") if tides else ""
    if "下げ" in tide_current:   score += 20
    elif "上げ" in tide_current: score += 15

    # 時間帯ボーナス（夜が有利）
    hour = datetime.now().hour
    if 20 <= hour or hour <= 4:              score += 20   # 深夜
    elif 18 <= hour <= 20 or 4 <= hour <= 7: score += 15   # マヅメ

    # 橋脚・合流点付近でない場合はスコアを65以下に制限（赤=70+ を防ぐ）
    if max_landmark_bonus < 20:
        score = min(score, 65.0)

    return min(100.0, score)

# ── 関東全域川データ (SQLite永続化・バックグラウンド更新) ────────────────
_KANTO_BBOX         = "34.8,138.0,37.2,141.2"   # 関東全域（利根川〜相模川）
_KANTO_REFRESH_SEC  = 3600                        # 1時間ごとに更新

def _fetch_kanto_rivers_all() -> dict:
    """関東全域 waterway=river を一括取得（ditch/drain/weir/sluice除外）"""
    query = (
        f"[out:json][timeout:120];\n("
        f'way["waterway"="river"]({_KANTO_BBOX});'
        f'node["waterway"~"weir|sluice_gate|floodgate"]({_KANTO_BBOX});'
        f");\nout geom;"
    )
    raw = _overpass_fetch_osm(query)
    rivers, weirs = [], []
    for el in raw.get("elements", []):
        tags  = el.get("tags", {})
        ww    = tags.get("waterway", "")
        etype = el.get("type", "")
        if etype == "way" and ww == "river":
            w_str = tags.get("width") or tags.get("est_width") or ""
            width = None
            try:
                width = float(w_str.split()[0])
                if width < 5:
                    continue
            except Exception:
                pass
            if tags.get("intermittent") == "yes":
                continue
            geom  = el.get("geometry", [])
            nodes = [(float(n["lat"]), float(n["lon"])) for n in geom if "lat" in n and "lon" in n]
            if len(nodes) >= 2:
                # 川の長さを計算（幅タグがない場合の水深代替指標）
                length_km = sum(
                    _dist_km(nodes[i-1][0], nodes[i-1][1], nodes[i][0], nodes[i][1])
                    for i in range(1, len(nodes))
                )
                rivers.append({"nodes": nodes, "name": tags.get("name", ""),
                               "width": width, "length_km": round(length_km, 2)})
        elif etype == "node" and ww in ("weir", "sluice_gate", "floodgate"):
            la, lo = el.get("lat"), el.get("lon")
            if la and lo:
                weirs.append((float(la), float(lo)))
    return {"rivers": rivers, "weirs": weirs}

def _save_rivers_to_db(rivers: list, weirs: list):
    """Overpassから取得した川データをSQLiteに保存（既存データを置換）"""
    import json as _json
    with get_db() as conn:
        conn.execute("DELETE FROM osm_rivers")
        conn.execute("DELETE FROM osm_weirs")
        for r in rivers:
            nodes = r["nodes"]
            lats  = [n[0] for n in nodes]
            lngs  = [n[1] for n in nodes]
            conn.execute(
                "INSERT INTO osm_rivers (name, width, length_km, nodes_json, min_lat, max_lat, min_lng, max_lng) VALUES (?,?,?,?,?,?,?,?)",
                (r.get("name") or "", r.get("width"), r.get("length_km") or 0,
                 _json.dumps(nodes, separators=(',', ':')),
                 min(lats), max(lats), min(lngs), max(lngs))
            )
        for lat, lng in weirs:
            conn.execute("INSERT INTO osm_weirs (lat, lng) VALUES (?,?)", (lat, lng))
        conn.commit()

def start_kanto_cache_refresh():
    """バックグラウンドスレッドで川データを段階的にSQLiteへ保存（メモリに蓄積しない）"""
    def _loop():
        # 初回: DBが空の場合は即座に取得
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM osm_rivers").fetchone()[0]
        if count == 0:
            try:
                data = _fetch_kanto_rivers_all()
                _save_rivers_to_db(data["rivers"], data["weirs"])
            except Exception:
                pass
        while True:
            _time.sleep(_KANTO_REFRESH_SEC)
            try:
                data = _fetch_kanto_rivers_all()
                _save_rivers_to_db(data["rivers"], data["weirs"])
            except Exception:
                pass
    threading.Thread(target=_loop, daemon=True).start()

def _width_to_score(width, length_km: float = None) -> float:
    """川幅→水深スコア変換。幅タグなし時は川の長さで代替 (深い/大=赤=1.0, 浅い/細=青=0.15)"""
    if width is not None:
        if   width >= 150: return 1.00
        elif width >= 80:  return 0.85
        elif width >= 40:  return 0.65
        elif width >= 15:  return 0.40
        else:              return 0.15
    # 長さで代替（利根川・荒川 > 30km, 神田川 ~10km, 小支流 < 1km）
    if length_km is not None:
        if   length_km >= 30: return 0.95
        elif length_km >= 10: return 0.80
        elif length_km >= 3:  return 0.55
        elif length_km >= 1:  return 0.35
        else:                 return 0.18
    return 0.55  # 情報なし

def _river_visible(river: dict, c_lat: float, c_lng: float, radius_km: float) -> bool:
    """河川ノードの一部をサンプリングして表示範囲チェック"""
    nodes = river["nodes"]
    step  = max(1, len(nodes) // 8)
    for la, lo in nodes[::step]:
        if _dist_km(la, lo, c_lat, c_lng) <= radius_km:
            return True
    return False

def _get_river_features(lat: float, lng: float, radius_km: float) -> dict:
    """waterway=river のライン座標と水門ノードを Overpass から取得。"""
    bucket = f"RV{round(lat*5)/5:.1f},{round(lng*5)/5:.1f},{int(radius_km)}"
    now = _time.time()
    if bucket in _river_cache:
        ts, data = _river_cache[bucket]
        if now - ts < _RIVER_CACHE_TTL:
            return data

    r_lat = radius_km / 111.0
    r_lng = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    bbox  = f"{lat-r_lat:.5f},{lng-r_lng:.5f},{lat+r_lat:.5f},{lng+r_lng:.5f}"

    query = (
        f"[out:json][timeout:30];\n("
        f'way["waterway"="river"]({bbox});'
        f'node["waterway"~"weir|sluice_gate|floodgate"]({bbox});'
        f");\nout geom;"
    )
    raw = _overpass_fetch_osm(query)

    rivers: list = []
    weirs:  list = []
    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        ww   = tags.get("waterway", "")
        etype = el.get("type", "")

        if etype == "way" and ww == "river":
            # 幅5m未満は除外（タグがなければ通す）
            w_str = tags.get("width") or tags.get("est_width") or ""
            try:
                if float(w_str.split()[0]) < 5:
                    continue
            except Exception:
                pass
            if tags.get("intermittent") == "yes":
                continue  # 季節河川を除外
            geom  = el.get("geometry", [])
            nodes = [(float(n["lat"]), float(n["lon"])) for n in geom if "lat" in n and "lon" in n]
            if len(nodes) >= 2:
                rivers.append({"nodes": nodes, "name": tags.get("name", "")})

        elif etype == "node" and ww in ("weir", "sluice_gate", "floodgate"):
            la, lo = el.get("lat"), el.get("lon")
            if la and lo:
                weirs.append((float(la), float(lo)))

    result = {"rivers": rivers, "weirs": weirs}
    _river_cache[bucket] = (now, result)
    return result

def _interpolate_river(nodes: list, interval_km: float,
                       c_lat: float, c_lng: float, radius_km: float, weirs: list,
                       bbox: tuple = None) -> list:
    """川ポリライン上に interval_km 間隔でポイントを生成（累積距離＋2分探索）。
    bbox=(s,w,n,e) を渡すと半径ではなくviewport矩形でフィルタ（半径制限撤廃）。"""
    if len(nodes) < 2:
        return []

    cum = [0.0]
    for i in range(1, len(nodes)):
        cum.append(cum[-1] + _dist_km(nodes[i-1][0], nodes[i-1][1], nodes[i][0], nodes[i][1]))
    total = cum[-1]
    if total < 1e-10:
        return []

    result  = []
    target  = 0.0
    n_segs  = len(nodes) - 1

    while target <= total + 1e-10:
        lo2, hi2 = 0, n_segs - 1
        while lo2 < hi2:
            mid = (lo2 + hi2) // 2
            if cum[mid + 1] >= target:
                hi2 = mid
            else:
                lo2 = mid + 1
        seg_i   = lo2
        seg_len = cum[seg_i + 1] - cum[seg_i]
        t = ((target - cum[seg_i]) / seg_len) if seg_len > 1e-10 else 0.0
        t = max(0.0, min(1.0, t))

        g_la = nodes[seg_i][0] + t * (nodes[seg_i+1][0] - nodes[seg_i][0])
        g_lo = nodes[seg_i][1] + t * (nodes[seg_i+1][1] - nodes[seg_i][1])

        # bbox指定時はviewport矩形フィルタ、なければ旧来の半径フィルタ
        if bbox:
            in_range = bbox[0] <= g_la <= bbox[2] and bbox[1] <= g_lo <= bbox[3]
        else:
            in_range = _dist_km(g_la, g_lo, c_lat, c_lng) <= radius_km

        if in_range:
            if not any(_dist_km(g_la, g_lo, wla, wlo) < 0.1 for wla, wlo in weirs):
                result.append({"lat": round(g_la, 5), "lng": round(g_lo, 5), "score": 1.0})

        target += interval_km

    return result

def get_river_heatmap(lat: float, lng: float, zoom: int = 13,
                      n: float = None, s: float = None,
                      e: float = None, w: float = None) -> dict:
    """シーバス川ヒートマップ: SQLiteから該当範囲の川のみ取得・精密スコアリング。
    n/s/e/w が指定された場合はviewport全体を表示（半径制限撤廃）。"""
    import json as _json

    interval_m = _ZOOM_INTERVAL.get(zoom, 50)

    # ズームレベルで表示する川の最小サイズを決定
    if zoom <= 12:
        min_length = 10.0   # 大河川のみ
    elif zoom <= 14:
        min_length = 1.0    # 中規模以上
    else:
        min_length = 0.0    # 全川

    # viewport boundsが指定された場合はそちらを優先（半径制限撤廃）
    if n is not None and s is not None and e is not None and w is not None:
        bbox_s, bbox_n, bbox_w, bbox_e = s, n, w, e
        viewport_bbox = (bbox_s, bbox_w, bbox_n, bbox_e)  # (s, w, n, e)
    else:
        radius_km = _ZOOM_RADIUS_R.get(zoom, 9)
        pad_lat   = radius_km / 111.0
        pad_lng   = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
        bbox_s, bbox_n = lat - pad_lat, lat + pad_lat
        bbox_w, bbox_e = lng - pad_lng, lng + pad_lng
        viewport_bbox = None  # レガシー：半径フィルタ

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM osm_rivers").fetchone()[0]
        if count == 0:
            return _get_river_heatmap_legacy(lat, lng, zoom)

        sql    = ("SELECT name, width, length_km, nodes_json FROM osm_rivers "
                  "WHERE max_lat >= ? AND min_lat <= ? AND max_lng >= ? AND min_lng <= ?")
        params = [bbox_s, bbox_n, bbox_w, bbox_e]
        if min_length > 0:
            sql    += " AND length_km >= ?"
            params.append(min_length)
        river_rows = conn.execute(sql, params).fetchall()

        weir_rows = conn.execute(
            "SELECT lat, lng FROM osm_weirs WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
            (bbox_s, bbox_n, bbox_w, bbox_e)
        ).fetchall()

    weirs  = [(r["lat"], r["lng"]) for r in weir_rows]
    rivers = [
        {"nodes": _json.loads(r["nodes_json"]), "name": r["name"] or "",
         "width": r["width"], "length_km": r["length_km"] or 0}
        for r in river_rows
    ]

    # スコアリング特徴量取得（zoom>=12 かつ小エリアのみ・大エリアはランドマーク専用）
    clat = (bbox_s + bbox_n) / 2
    area_km2 = (bbox_n - bbox_s) * 111 * (bbox_e - bbox_w) * 111 * math.cos(math.radians(clat))
    if zoom >= 12 and area_km2 <= 2000:
        bbox_str = f"{bbox_s:.3f},{bbox_w:.3f},{bbox_n:.3f},{bbox_e:.3f}"
        bucket   = f"RSF_{bbox_str}"
        if bucket in _river_score_cache:
            _, scoring_feats = _river_score_cache[bucket]
        else:
            threading.Thread(target=_get_river_scoring_features, args=(bbox_str,), daemon=True).start()
            scoring_feats = {"bridges": [], "lamps": [], "outfalls": [], "water_gates": []}
    else:
        # 広域ビュー: ランドマークのみ使用（Overpass大量クエリを防止）
        scoring_feats = {"bridges": [], "lamps": [], "outfalls": [], "water_gates": []}
    tides = get_tides()

    radius_km = _ZOOM_RADIUS_R.get(zoom, 9)  # _interpolate_river レガシー用
    points:        list = []
    visible_names: list = []
    for river in rivers:
        if river.get("name"):
            visible_names.append(river["name"])
        pts = _interpolate_river(
            river["nodes"], interval_m / 1000.0,
            lat, lng, radius_km, weirs,
            bbox=viewport_bbox
        )
        for p in pts:
            raw = _score_seabass_point(p["lat"], p["lng"], scoring_feats, tides)
            if raw < 10:
                continue   # 水門除外（score=0）のみフィルタ
            # 0-100 → 0.0-1.0 正規化
            if raw >= 70:
                p["score"] = 0.7 + (raw - 70) / 30 * 0.3    # 赤: 橋脚・合流点
            elif raw >= 40:
                p["score"] = 0.3 + (raw - 40) / 30 * 0.4    # 橙: 特徴物付近
            else:
                p["score"] = (raw - 10) / 30 * 0.3           # 黄: 基本河川
            points.append(p)

    river_names = list(dict.fromkeys(visible_names))
    return {
        "points":      points,
        "species":     "シーバス",
        "water_based": True,
        "river_count": len(rivers),
        "river_names": river_names[:20],
        "cache_age_min": 0,
    }

def _get_river_heatmap_legacy(lat: float, lng: float, zoom: int = 13) -> dict:
    """キャッシュ未ロード時のフォールバック（旧来の範囲クエリ）"""
    radius_km  = _ZOOM_RADIUS_R.get(zoom, 9)
    interval_m = _ZOOM_INTERVAL.get(zoom, 50)
    feats  = _get_river_features(lat, lng, radius_km)
    rivers = feats.get("rivers", [])
    weirs  = feats.get("weirs", [])
    points: list = []
    for river in rivers:
        pts = _interpolate_river(river["nodes"], interval_m / 1000.0, lat, lng, radius_km, weirs)
        points.extend(pts)
    river_names = list(dict.fromkeys(r["name"] for r in rivers if r.get("name")))
    return {"points": points, "species": "シーバス", "water_based": True,
            "river_count": len(rivers), "river_names": river_names, "cache_age_min": -1}

# ── Phase 4+: 水辺限定ヒートマップ ───────────────────────────────

_water_feat_cache: dict = {}
_WATER_CACHE_TTL = 1800  # 30分キャッシュ

def _overpass_fetch_osm(query: str) -> dict:
    """Overpass API取得（フォールバック付き）。"""
    import urllib.request, urllib.parse, json as _j
    for srv in ["https://overpass-api.de/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter"]:
        try:
            url = f"{srv}?data={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "AnglerMap/5.0"})
            with urllib.request.urlopen(req, timeout=22) as r:
                return _j.loads(r.read())
        except Exception:
            continue
    return {"elements": []}

def _get_water_features(lat: float, lng: float, radius_km: float = 15) -> list:
    """OSMから水辺ライン座標を取得（out geom で実際の輪郭/ライン）。TTLキャッシュ付き。"""
    bucket = f"{round(lat*5)/5:.1f},{round(lng*5)/5:.1f},{int(radius_km)}"
    now = _time.time()
    if bucket in _water_feat_cache:
        ts, data = _water_feat_cache[bucket]
        if now - ts < _WATER_CACHE_TTL:
            return data

    r_lat = radius_km / 111.0
    r_lng = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    bbox = f"{lat-r_lat:.5f},{lng-r_lng:.5f},{lat+r_lat:.5f},{lng+r_lng:.5f}"

    # out geom; で各wayの実際の座標列を取得（中心点ではなくライン形状）
    query = (
        f"[out:json][timeout:28];\n("
        f'way["natural"="water"]({bbox});'
        f'way["waterway"~"river|stream|canal|ditch"]({bbox});'
        f'way["natural"="coastline"]({bbox});'
        f'node["leisure"="fishing"]({bbox});'
        f'node["man_made"~"pier|breakwater|groyne"]({bbox});'
        f'way["man_made"~"pier|breakwater|groyne"]({bbox});'
        f'way["bridge"="yes"]({bbox});'
        f'node["highway"="street_lamp"]({bbox});'
        f");\nout geom;"   # ← centerではなく実座標
    )

    raw = _overpass_fetch_osm(query)

    type_map = {
        "natural":  {"water":"water","coastline":"coastline"},
        "waterway": {"river":"river","stream":"river","canal":"canal","ditch":"canal"},
        "leisure":  {"fishing":"fishing"},
        "man_made": {"pier":"pier","breakwater":"breakwater","groyne":"breakwater"},
        "bridge":   {"yes":"bridge"},
        "highway":  {"street_lamp":"light"},
    }
    # 各タイプの最大ノード数（合計が多くなりすぎないよう制限）
    CAPS = {"water":600,"coastline":400,"river":400,"canal":300,
            "bridge":120,"pier":120,"breakwater":120,"fishing":80,"light":200}

    feats: list = []
    counts: dict = {}

    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        ftype = None
        for tk, tv_map in type_map.items():
            if tags.get(tk, "") in tv_map:
                ftype = tv_map[tags[tk]]
                break
        if not ftype:
            continue

        cap = CAPS.get(ftype, 100)
        geom = el.get("geometry")  # way の場合は座標列

        if geom:
            # way: 実際の輪郭ノードをサブサンプリング
            # 最大40ノード/way を目安に間引く
            step = max(1, len(geom) // 40)
            nodes = geom[::step]
            # 最後のノードも必ず含める（輪郭を閉じる）
            if geom[-1] not in nodes:
                nodes.append(geom[-1])
            for nd in nodes:
                la, lo = nd.get("lat"), nd.get("lon")
                if la and lo and counts.get(ftype, 0) < cap:
                    feats.append({"lat": float(la), "lng": float(lo), "type": ftype})
                    counts[ftype] = counts.get(ftype, 0) + 1
        else:
            # node: そのまま使用
            la = el.get("lat")
            lo = el.get("lon")
            if la and lo and counts.get(ftype, 0) < cap:
                feats.append({"lat": float(la), "lng": float(lo), "type": ftype})
                counts[ftype] = counts.get(ftype, 0) + 1

    _water_feat_cache[bucket] = (now, feats)
    return feats

def _dist_km(la1: float, lo1: float, la2: float, lo2: float) -> float:
    clat = math.cos(math.radians((la1 + la2) / 2))
    return math.sqrt(((la2 - la1) * 111) ** 2 + ((lo2 - lo1) * 111 * clat) ** 2)

def _score_near_water(g_lat: float, g_lng: float, species: str,
                      features: list, env: dict) -> float:
    """水辺グリッドポイントのスコア計算。水辺ラインから150m超は0。"""
    WATER_TYPES = {"water","coastline","river","canal","fishing","pier","breakwater","bridge"}
    WATER_RANGE = 0.15   # km = 150m（out geomで実ラインを使うので狭く設定）

    min_w = min(
        (_dist_km(g_lat, g_lng, f["lat"], f["lng"]) for f in features if f["type"] in WATER_TYPES),
        default=9999.0
    )
    if min_w > WATER_RANGE:
        return 0.0   # 水辺150m超 → 陸地として除外

    score = max(0.0, 40.0 * (1.0 - min_w / WATER_RANGE))

    eco  = SPECIES_ECOLOGY.get(species, {})
    temp = env.get("sea_temp", 18.0)
    tide = env.get("tide_current", "")

    t_lo, t_hi     = eco.get("temp_range", (10, 28))
    t_pk_lo, t_pk_hi = eco.get("temp_peak", (15, 25))
    if t_lo <= temp <= t_hi:
        score += 20 if (t_pk_lo <= temp <= t_pk_hi) else 10

    tp = eco.get("tide_pref", "any")
    if   tp == "rising"  and "上げ" in tide: score += 20
    elif tp == "falling" and "下げ" in tide: score += 20
    elif tp == "any":                         score += 8

    for f in features:
        d  = _dist_km(g_lat, g_lng, f["lat"], f["lng"])
        ft = f["type"]
        if   species == "シーバス":
            if   ft == "bridge"               and d < 0.15: score += 40 * (1 - d/0.15)
            elif ft == "light"                and d < 0.05: score += 15 * (1 - d/0.05)
            elif ft in ("river","canal")      and d < 0.10: score += 35 * (1 - d/0.10)
        elif species == "チヌ":
            if   ft in ("breakwater","pier")  and d < 0.12: score += 40 * (1 - d/0.12)
            if "下げ" in tide: score += 5
        elif species in ("アジ","メバル"):
            if   ft == "light"                and d < 0.05: score += 45 * (1 - d/0.05)
            elif ft in ("pier","fishing")     and d < 0.20: score += 25 * (1 - d/0.20)
        elif species == "根魚":
            if   ft in ("breakwater","pier")  and d < 0.10: score += 45 * (1 - d/0.10)
        elif species == "ヒラメ":
            if   ft in ("river","canal")      and d < 0.15: score += 30 * (1 - d/0.15)

    return min(100.0, score)

def get_water_heatmap(lat: float, lng: float, species: str = "シーバス", radius_km: float = 15) -> dict:
    """水辺限定ヒートマップ。グリッド細分化+バケット空間インデックスで高速化。"""
    env      = _get_env_data(lat, lng)
    features = _get_water_features(lat, lng, radius_km)

    WATER_RANGE = 0.20   # km = 200m（out geom実ラインを使うので適切な幅）
    WATER_TYPES = {"water","coastline","river","canal","fishing","pier","breakwater","bridge"}
    water_feats = [f for f in features if f["type"] in WATER_TYPES]

    # ─ 空間バケット: 近傍の水辺フィーチャーを O(1) で探索 ─
    CELL = 0.003  # ~330m per cell
    bucket: dict = {}
    for f in water_feats:
        k = (int(f["lat"] / CELL), int(f["lng"] / CELL))
        bucket.setdefault(k, []).append(f)

    # ─ 細かいグリッド（0.004度 ≈ 440m）───────────────────────
    lat_step = 0.004
    lng_step = lat_step / max(0.01, math.cos(math.radians(lat)))
    steps    = max(1, int(radius_km / (lat_step * 111)))
    cos_lat  = math.cos(math.radians(lat))
    BCELLS   = int(WATER_RANGE / (CELL * 111)) + 1  # バケット検索半径

    points: list = []
    for di in range(-steps, steps + 1):
        for dj in range(-steps, steps + 1):
            g_lat = lat + di * lat_step
            g_lng = lng + dj * lng_step
            dlat  = (g_lat - lat) * 111
            dlng  = (g_lng - lng) * 111 * cos_lat
            if math.sqrt(dlat**2 + dlng**2) > radius_km:
                continue

            # ── Fast water check (バケット使用) ──
            ki = int(g_lat / CELL)
            kj = int(g_lng / CELL)
            gc = math.cos(math.radians(g_lat))
            min_w = 9999.0
            for bi in range(-BCELLS, BCELLS + 1):
                for bj in range(-BCELLS, BCELLS + 1):
                    for wf in bucket.get((ki+bi, kj+bj), []):
                        d = math.sqrt(((g_lat-wf["lat"])*111)**2 + ((g_lng-wf["lng"])*111*gc)**2)
                        if d < min_w:
                            min_w = d
            if min_w > WATER_RANGE:
                continue  # 水辺から遠い → スキップ（陸地除外）

            # ── Full scoring（水辺ポイントのみ到達）──
            s = _score_near_water(g_lat, g_lng, species, features, env)
            if s > 3:
                points.append({"lat": round(g_lat, 4), "lng": round(g_lng, 4), "score": round(s / 100, 3)})

    if not points:
        eco_result = get_ecological_heatmap(lat, lng, species, radius_km)
        eco_result["water_based"] = False
        return eco_result

    return {
        "points":         points,
        "features_count": len(features),
        "env": {
            "sea_temp":     round(env.get("sea_temp", 18), 1),
            "tide_current": env.get("tide_current", ""),
            "tide_type":    env.get("tide_type", ""),
            "moon_phase":   env.get("moon_phase", ""),
        },
        "species":    species,
        "water_based": True,
    }
