import os, shutil, uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

import database as db

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

db.init_db()

app = FastAPI(title="Angler's Map API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ────────────────────────────────────────────────

@app.get("/api/fish-list")
def fish_list():
    return db.FISH_LIST

@app.get("/api/catches")
def get_catches(
    n: Optional[float] = None, s: Optional[float] = None,
    e: Optional[float] = None, w: Optional[float] = None,
    limit: int = 200,
):
    bounds = {"n": n, "s": s, "e": e, "w": w} if all(v is not None for v in [n,s,e,w]) else None
    return db.get_public_catches(bounds, limit)

@app.get("/api/heatmap")
def heatmap():
    return db.get_heatmap_stats()

@app.get("/api/stats")
def stats():
    return db.get_catch_counts()

@app.post("/api/catches")
async def create_catch(
    fish_species: str  = Form(...),
    fish_emoji:   str  = Form("🐟"),
    size_cm:      Optional[float] = Form(None),
    weight_g:     Optional[float] = Form(None),
    lure_name:    Optional[str]   = Form(None),
    memo:         Optional[str]   = Form(None),
    lat:          float = Form(...),
    lng:          float = Form(...),
    privacy:      str   = Form("area"),
    user_id:      str   = Form("anonymous"),
    photo:        Optional[UploadFile] = File(None),
):
    photo_filename = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
            raise HTTPException(400, "画像ファイルのみアップロード可能です")
        fname = f"{uuid.uuid4().hex}{ext}"
        dest = UPLOAD_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(photo.file, f)
        photo_filename = fname

    catch = db.create_catch({
        "fish_species": fish_species, "fish_emoji": fish_emoji,
        "size_cm": size_cm, "weight_g": weight_g,
        "lure_name": lure_name, "memo": memo,
        "lat": lat, "lng": lng,
        "privacy": privacy, "user_id": user_id,
        "photo_filename": photo_filename,
    })
    return catch

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "phase1"}

# ── Static files (serve PWA) ──────────────────────────────────

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
