# main.py
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse
import enka
import httpx
import asyncio
import time
from collections import defaultdict

# ==================== CONFIG ====================
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

# ==================== APP ====================
app = FastAPI(redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# ==================== GLOBALS ====================
genshin_client = enka.GenshinClient(enka.gi.Language.ENGLISH)
hsr_client = enka.HSRClient(enka.hsr.Language.ENGLISH)
zzz_client = enka.ZZZClient(enka.zzz.Language.ENGLISH)

cache_data = {}
fetch_locks = defaultdict(asyncio.Lock)

# ==================== STARTUP / SHUTDOWN ====================
@app.on_event("startup")
async def startup_event():
    await genshin_client.__aenter__()
    await hsr_client.__aenter__()
    await zzz_client.__aenter__()
    print("[STARTUP] Enka clients ready.")

@app.on_event("shutdown")
async def shutdown_event():
    await genshin_client.__aexit__(None, None, None)
    await hsr_client.__aexit__(None, None, None)
    await zzz_client.__aexit__(None, None, None)
    print("[SHUTDOWN] Enka clients closed.")

# ==================== UTILS ====================
def detect_game(uid: int):
    s = str(uid)
    if s.startswith("6") and len(s) == 9:
        return "hsr"
    elif s.startswith("1") and len(s) == 9:
        return "zzz"
    elif len(s) == 9:
        return "gi"
    return None

async def fetch_with_retry(client_func, uid: int, game: str):
    """Fetch showcase với retry + cache fallback"""
    last_error = None
    for attempt in range(1, RETRY_COUNT + 2):  # lần cuối là lần thật sự cuối
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
    now = time.time()

    # Cache còn hạn → trả ngay
    if key in cache_data and now - cache_data[key]["time"] < ttl:
        return cache_data[key]["data"]

    async with fetch_locks[key]:
        # Kiểm tra lại cache sau khi chờ lock
        if key in cache_data and now - cache_data[key]["time"] < ttl:
            return cache_data[key]["data"]

        client_map = {
            "gi": genshin_client.fetch_showcase,
            "hsr": hsr_client.fetch_showcase,
            "zzz": zzz_client.fetch_showcase
        }

        try:
            data = await fetch_with_retry(client_map[game], uid, game)
            cache_data[key] = {"data": data, "time": time.time()}
            return data
        except Exception as e:
            # Nếu lỗi nhưng cache cũ còn → trả cache
            if key in cache_data:
                print(f"[FALLBACK CACHE] {game.upper()} UID {uid}")
                return cache_data[key]["data"]
            raise HTTPException(status_code=500, detail=str(e))

# ==================== ROUTES ====================
@app.get("/")
async def root():
    return {"status": "ok", "message": "Enka backend is running"}

@app.api_route("/ping", methods=["GET", "HEAD"], include_in_schema=False)
async def ping(request: Request):
    if request.method == "HEAD":
        return PlainTextResponse(status_code=200)
    return PlainTextResponse("pong", status_code=200)

@app.get("/enka/{uid}")
async def get_enka(uid: int):
    game = detect_game(uid)
    if not game:
        raise HTTPException(status_code=400, detail="Unknown UID format")
    return (await fetch_showcase(game, uid)).model_dump()

@app.get("/gi/{uid}")
async def get_gi(uid: int):
    return (await fetch_showcase("gi", uid)).model_dump()

@app.get("/hsr/{uid}")
async def get_hsr(uid: int):
    return (await fetch_showcase("hsr", uid)).model_dump()

@app.get("/zzz/{uid}")
async def get_zzz(uid: int):
    return (await fetch_showcase("zzz", uid)).model_dump()

# ==================== IDENTITY V API ====================
@app.get("/idv/{roleid}")
async def get_idv(roleid: int):
    url = "https://pay.neteasegames.com/gameclub/identityv/2001/login-role"
    params = {"roleid": roleid, "client_type": "gameclub"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            start = time.time()
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            elapsed = round(time.time() - start, 3)
            print(f"[IDV] RoleID {roleid} in {elapsed}s")
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Request error: {str(e)}")
