import os, shutil, uuid, io
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

import jwt
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR  = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

db.init_db()

app = FastAPI(title="Angler's Map API", version="3.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup_event():
    db.start_kanto_cache_refresh()

JWT_SECRET    = os.environ.get("JWT_SECRET", "anglers-map-secret-2024-phase3")
JWT_ALGORITHM = "HS256"
security      = HTTPBearer(auto_error=False)

def _create_token(user_id: int, email: str) -> str:
    return jwt.encode(
        {"sub": str(user_id), "email": email, "exp": datetime.utcnow() + timedelta(days=7)},
        JWT_SECRET, algorithm=JWT_ALGORITHM)

def _get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds: raise HTTPException(401, "認証が必要です")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = db.get_user_by_id(int(payload["sub"]))
        if not user: raise HTTPException(401, "ユーザーが存在しません")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "トークンが期限切れです")
    except Exception:
        raise HTTPException(401, "無効なトークンです")

def _safe_user(u: dict) -> dict:
    return {k: v for k, v in u.items() if k != "password_hash"}

# ── Pydantic models ───────────────────────────────────────────
class RegisterBody(BaseModel):
    email: str; username: str; password: str

class LoginBody(BaseModel):
    email: str; password: str

class ProfileBody(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    instagram_id: Optional[str] = None

class StatusBody(BaseModel):
    is_fishing: bool; lat: Optional[float] = None; lng: Optional[float] = None

class FriendRequestBody(BaseModel):
    addressee_id: int

class RespondFriendBody(BaseModel):
    status: str  # accepted | declined

class MeetingSpotBody(BaseModel):
    lat: float; lng: float; label: Optional[str] = ""

class RankSubmitBody(BaseModel):
    room_id: int
    winner_id: int; loser_id: int
    winner_fish: Optional[str] = None; loser_fish: Optional[str] = None
    winner_size: Optional[float] = None; loser_size: Optional[float] = None

# ── Auth endpoints ────────────────────────────────────────────
@app.post("/api/auth/register")
def register(body: RegisterBody):
    if len(body.password) < 6: raise HTTPException(400, "パスワードは6文字以上")
    user = db.create_user(body.email, body.username, body.password)
    if not user: raise HTTPException(409, "このメールアドレスは既に使用されています")
    token = _create_token(user["id"], user["email"])
    return {"token": token, "user": _safe_user(user)}

@app.post("/api/auth/login")
def login(body: LoginBody):
    user = db.get_user_by_email(body.email)
    if not user or not db.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "メールアドレスまたはパスワードが間違っています")
    token = _create_token(user["id"], user["email"])
    return {"token": token, "user": _safe_user(user)}

@app.get("/api/auth/me")
def me(current_user=Depends(_get_current_user)):
    return _safe_user(current_user)

@app.put("/api/users/profile")
def update_profile(body: ProfileBody, current_user=Depends(_get_current_user)):
    user = db.update_user_profile(current_user["id"], body.dict())
    return _safe_user(user)

@app.post("/api/users/avatar")
async def upload_avatar(photo: UploadFile = File(...), current_user=Depends(_get_current_user)):
    ext = Path(photo.filename).suffix.lower()
    if ext not in {".jpg",".jpeg",".png",".webp"}: raise HTTPException(400, "画像ファイルのみ")
    fname = f"avatar_{current_user['id']}{ext}"
    with (UPLOAD_DIR / fname).open("wb") as f: shutil.copyfileobj(photo.file, f)
    user = db.update_user_profile(current_user["id"], {"avatar_filename": fname})
    return _safe_user(user)

@app.put("/api/users/status")
def update_status(body: StatusBody, current_user=Depends(_get_current_user)):
    user = db.update_fishing_status(current_user["id"], body.is_fishing, body.lat, body.lng)
    return _safe_user(user)

@app.get("/api/users/fishing-nearby")
def fishing_nearby(lat: float, lng: float, radius: float = 20, current_user=Depends(_get_current_user)):
    return db.get_fishing_users_nearby(lat, lng, radius, exclude_id=current_user["id"])

@app.get("/api/rank/leaderboard")
def leaderboard():
    return db.get_leaderboard()

# ── Friends ───────────────────────────────────────────────────
@app.post("/api/friends/request")
def friend_request(body: FriendRequestBody, current_user=Depends(_get_current_user)):
    result = db.send_friend_request(current_user["id"], body.addressee_id)
    if not result: raise HTTPException(409, "リクエスト済みか自分自身へのリクエストです")
    return result

@app.get("/api/friends")
def get_friends(current_user=Depends(_get_current_user)):
    return db.get_friends(current_user["id"])

@app.put("/api/friends/{friend_id}/respond")
def respond_friend(friend_id: int, body: RespondFriendBody, current_user=Depends(_get_current_user)):
    result = db.respond_friend_request(friend_id, body.status, current_user["id"])
    if not result: raise HTTPException(404, "リクエストが見つかりません")
    return result

# ── Rooms ─────────────────────────────────────────────────────
@app.get("/api/rooms")
def my_rooms(current_user=Depends(_get_current_user)):
    return db.get_user_rooms(current_user["id"])

@app.post("/api/rooms")
def create_room_direct(body: FriendRequestBody, current_user=Depends(_get_current_user)):
    room = db.create_room(current_user["id"], body.addressee_id)
    if not room: raise HTTPException(500, "ルーム作成失敗")
    return room

@app.get("/api/rooms/{room_id}")
def get_room(room_id: int, current_user=Depends(_get_current_user)):
    room = db.get_room(room_id, current_user["id"])
    if not room: raise HTTPException(404, "ルームが見つかりません")
    return room

@app.put("/api/rooms/{room_id}/meeting")
def set_meeting(room_id: int, body: MeetingSpotBody, current_user=Depends(_get_current_user)):
    room = db.update_room_meeting(room_id, current_user["id"], body.lat, body.lng, body.label or "集合場所")
    if not room: raise HTTPException(404, "ルームが見つかりません")
    return room

# ── Rank ─────────────────────────────────────────────────────
@app.post("/api/rank/submit")
async def rank_submit(
    room_id:     int   = Form(...),
    winner_id:   int   = Form(...),
    loser_id:    int   = Form(...),
    winner_fish: Optional[str]   = Form(None),
    loser_fish:  Optional[str]   = Form(None),
    winner_size: Optional[float] = Form(None),
    loser_size:  Optional[float] = Form(None),
    photo:       Optional[UploadFile] = File(None),
    current_user=Depends(_get_current_user),
):
    exif_valid = True
    photo_filename = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in {".jpg",".jpeg",".png",".webp",".heic"}: raise HTTPException(400, "画像ファイルのみ")
        content = await photo.read()
        exif_valid = _check_photo_exif(content)
        fname = f"rank_{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / fname).write_bytes(content)
        photo_filename = fname

    result = db.submit_rank_match(room_id, winner_id, loser_id, {
        "winner_fish": winner_fish, "loser_fish": loser_fish,
        "winner_size": winner_size, "loser_size": loser_size,
        "catch_photo": photo_filename, "exif_valid": exif_valid,
    })
    return result

def _check_photo_exif(content: bytes) -> bool:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(io.BytesIO(content))
        exif = img._getexif()
        if not exif: return True  # no EXIF, allow but warn
        tags = {TAGS.get(k, k): v for k, v in exif.items()}
        # Check if photo is too old (> 7 days)
        if "DateTimeOriginal" in tags:
            try:
                taken = datetime.strptime(tags["DateTimeOriginal"], "%Y:%m:%d %H:%M:%S")
                if (datetime.now() - taken).days > 7: return False
            except: pass
        return True
    except: return True

# ── Fishing catches ───────────────────────────────────────────
@app.get("/api/fish-list")
def fish_list(): return db.FISH_LIST

@app.get("/api/catches")
def get_catches(
    n: Optional[float] = None, s: Optional[float] = None,
    e: Optional[float] = None, w: Optional[float] = None,
    limit: int = 200, period: Optional[str] = None, species: Optional[str] = None,
):
    bounds = {"n":n,"s":s,"e":e,"w":w} if all(v is not None for v in [n,s,e,w]) else None
    return db.get_public_catches(bounds, limit, period, species)

@app.get("/api/heatmap")
def heatmap(
    lat:     Optional[float] = None,
    lng:     Optional[float] = None,
    zoom:    int             = 13,
    fish:    Optional[str]   = None,
    period:  Optional[str]   = None,
    species: Optional[str]   = None,
):
    if lat is not None and lng is not None:
        return db.get_river_heatmap(lat, lng, zoom)
    return db.get_heatmap_stats(period, species)

@app.get("/api/stats")
def stats(): return db.get_catch_counts()

@app.get("/api/tides")
def tides(): return db.get_tides()

@app.get("/api/fishing-suggestion")
def fishing_suggestion(): return db.get_fishing_suggestion()

@app.post("/api/catches")
async def create_catch(
    fish_species: str = Form(...), fish_emoji: str = Form("🐟"),
    size_cm: Optional[float] = Form(None), weight_g: Optional[float] = Form(None),
    lure_name: Optional[str] = Form(None), memo: Optional[str] = Form(None),
    lat: float = Form(...), lng: float = Form(...),
    privacy: str = Form("area"), user_id: str = Form("anonymous"),
    photo: Optional[UploadFile] = File(None),
):
    photo_filename = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in {".jpg",".jpeg",".png",".webp",".heic"}: raise HTTPException(400, "画像ファイルのみ")
        fname = f"{uuid.uuid4().hex}{ext}"
        with (UPLOAD_DIR / fname).open("wb") as f: shutil.copyfileobj(photo.file, f)
        photo_filename = fname
    return db.create_catch({
        "fish_species": fish_species, "fish_emoji": fish_emoji,
        "size_cm": size_cm, "weight_g": weight_g, "lure_name": lure_name, "memo": memo,
        "lat": lat, "lng": lng, "privacy": privacy, "user_id": user_id, "photo_filename": photo_filename,
    })

@app.get("/api/health")
def health(): return {"status": "ok", "version": "phase4"}

# ── Phase 4: Ecological heatmap ───────────────────────────────
@app.get("/api/ecological-heatmap")
def ecological_heatmap(
    lat: float = 35.68,
    lng: float = 139.69,
    species: str = "シーバス",
    radius: float = 20,
):
    return db.get_ecological_heatmap(lat, lng, species, min(radius, 50))

@app.get("/api/species-ecology")
def species_ecology():
    return [
        {"name": k, "temp_range": v["temp_range"],
         "season_peak": v["season_peak"], "habitat": v.get("habitat",""), "bait": v.get("bait",[])}
        for k, v in db.SPECIES_ECOLOGY.items()
    ]

@app.get("/api/water-heatmap")
def water_heatmap(
    lat: float = 35.68,
    lng: float = 139.69,
    species: str = "シーバス",
    radius: float = 15,
):
    return db.get_water_heatmap(lat, lng, species, min(float(radius), 25))

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
