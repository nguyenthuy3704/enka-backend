import asyncio
import os
import json
import time
import uvloop
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse
import enka
import httpx
import redis.asyncio as redis

# ==================== CONFIG ====================

uvloop.install()

CACHE_TTL = {
    "gi": 300,   # 5 phút
    "hsr": 300,  # 5 phút
    "zzz": 900   # 15 phút
}
RETRY_COUNT = 2

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5501",
    "https://meostore.shop"
]

PRELOAD_UIDS = [
    ("gi", 800000000),
    ("hsr", 600000000),
    ("zzz", 100000000)
]

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL environment variable is not set!")

# ==================== APP SETUP ====================

app = FastAPI(redirect_slashes=False)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ==================== GLOBAL CLIENTS ====================

genshin_client = enka.GenshinClient(enka.gi.Language.ENGLISH)
hsr_client = enka.HSRClient(enka.hsr.Language.ENGLISH)
zzz_client = enka.ZZZClient(enka.zzz.Language.ENGLISH)

idv_client: httpx.AsyncClient | None = None

redis_client = redis.from_url(
    REDIS_URL,
    encoding="utf-8",
    decode_responses=True
)

fetch_locks = defaultdict(asyncio.Lock)

# ==================== STARTUP / SHUTDOWN ====================

@app.on_event("startup")
async def on_startup():
    global idv_client
    idv_client = httpx.AsyncClient(timeout=15)

    await genshin_client.__aenter__()
    await hsr_client.__aenter__()
    await zzz_client.__aenter__()

    try:
        pong = await redis_client.ping()
        print(f"[REDIS] Connected: {pong}")
    except Exception as e:
        print(f"[REDIS] Connection failed: {e}")

    asyncio.create_task(preload_showcases(PRELOAD_UIDS))
    print("[STARTUP] Enka clients ready.")

@app.on_event("shutdown")
async def on_shutdown():
    await genshin_client.__aexit__(None, None, None)
    await hsr_client.__aexit__(None, None, None)
    await zzz_client.__aexit__(None, None, None)

    if idv_client:
        await idv_client.aclose()

    await redis_client.aclose()
    print("[SHUTDOWN] All clients closed.")

# ==================== UTILS ====================

async def fetch_with_retry(client_func, uid: int, game: str):
    last_error = None
    for attempt in range(1, RETRY_COUNT + 2):
        try:
            start = time.time()
            data = await client_func(uid)
            elapsed = round(time.time() - start, 3)
            print(f"[FETCH] {game.upper()} UID {uid} in {elapsed}s (try {attempt})")
            return data
        except enka.errors.APIRequestTimeoutError as e:
            print(f"[TIMEOUT] {game.upper()} UID {uid} (try {attempt})")
            last_error = e
        except Exception as e:
            print(f"[ERROR] {game.upper()} UID {uid} (try {attempt}) {e}")
            last_error = e
    raise last_error

async def fetch_showcase(game: str, uid: int):
    key = f"{game}:{uid}"
    ttl = CACHE_TTL.get(game, 300)

    # Lấy cache từ Redis
    cached_json = await redis_client.get(key)
    if cached_json:
        try:
            return json.loads(cached_json)
        except Exception:
            print(f"[CACHE ERROR] {key} parse failed, refetching...")

    async with fetch_locks[key]:
        # Double check cache trong lock
        cached_json = await redis_client.get(key)
        if cached_json:
            try:
                return json.loads(cached_json)
            except Exception:
                pass

        client_map = {
            "gi": genshin_client.fetch_showcase,
            "hsr": hsr_client.fetch_showcase,
            "zzz": zzz_client.fetch_showcase
        }

        try:
            data = await fetch_with_retry(client_map[game], uid, game)
            data_dict = data.model_dump()

            # Lưu Redis với default=str để tránh lỗi datetime + key số
            await redis_client.setex(key, ttl, json.dumps(data_dict, default=str))
            return data_dict
        except Exception as e:
            if cached_json:
                print(f"[FALLBACK CACHE] {key}")
                return json.loads(cached_json)
            raise HTTPException(status_code=500, detail=str(e))

async def preload_showcases(uid_list):
    tasks = [fetch_showcase(game, uid) for game, uid in uid_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (game, uid), res in zip(uid_list, results):
        if isinstance(res, Exception):
            print(f"[PRELOAD] {game.upper()} {uid} FAILED: {res}")
        else:
            print(f"[PRELOAD] {game.upper()} {uid} OK")

# ==================== ROUTES ====================

@app.get("/")
async def root():
    return {"status": "ok", "message": "Enka backend is running"}

@app.api_route("/ping", methods=["GET", "HEAD"], include_in_schema=False)
async def ping(request: Request):
    if request.method == "HEAD":
        return PlainTextResponse(status_code=200)
    return PlainTextResponse("pong", status_code=200)

@app.get("/gi/{uid}")
async def get_gi(uid: int):
    return await fetch_showcase("gi", uid)

@app.get("/hsr/{uid}")
async def get_hsr(uid: int):
    return await fetch_showcase("hsr", uid)

@app.get("/zzz/{uid}")
async def get_zzz(uid: int):
    return await fetch_showcase("zzz", uid)

@app.get("/enka/{game}/{uid}")
async def get_enka(game: str, uid: int):
    if game not in CACHE_TTL:
        raise HTTPException(status_code=400, detail="Unknown game")
    return await fetch_showcase(game, uid)

# ==================== IDENTITY V API ====================

@app.get("/idv/{roleid}")
async def get_idv(roleid: int):
    key = f"idv:{roleid}"
    ttl = 300  # 5 phút

    # Check cache
    cached = await redis_client.get(key)
    if cached:
        return json.loads(cached)

    url = "https://pay.neteasegames.com/gameclub/identityv/2001/login-role"
    params = {"roleid": roleid, "client_type": "gameclub"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        start = time.time()
        response = await idv_client.get(url, params=params, headers=headers)
        response.raise_for_status()
        elapsed = round(time.time() - start, 3)
        print(f"[IDV] RoleID {roleid} in {elapsed}s")

        data = response.json()

        # Lưu cache với default=str
        await redis_client.setex(key, ttl, json.dumps(data, default=str))

        return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Request error: {str(e)}")
