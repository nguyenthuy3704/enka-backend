from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.requests import Request
from fastapi.middleware.gzip import GZipMiddleware
import time
import httpx
import asyncio
import enka
from collections import defaultdict

app = FastAPI(redirect_slashes=False)

# ===== CORS =====
origins = [
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5501",
    "https://meostore.shop"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Gzip Compression =====
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ===== Persistent HTTP client =====
httpx_client = httpx.AsyncClient(timeout=8)

# ===== Lazy load Enka clients =====
genshin_client = None
hsr_client = None
zzz_client = None

async def get_client(game: str):
    """Khởi tạo client khi cần và dùng HTTP session chung"""
    global genshin_client, hsr_client, zzz_client
    if game == "gi":
        if genshin_client is None:
            genshin_client = enka.GenshinClient(enka.gi.Language.ENGLISH, client=httpx_client)
            await genshin_client.__aenter__()
        return genshin_client
    elif game == "hsr":
        if hsr_client is None:
            hsr_client = enka.HSRClient(enka.hsr.Language.ENGLISH, client=httpx_client)
            await hsr_client.__aenter__()
        return hsr_client
    elif game == "zzz":
        if zzz_client is None:
            zzz_client = enka.ZZZClient(enka.zzz.Language.ENGLISH, client=httpx_client)
            await zzz_client.__aenter__()
        return zzz_client
    else:
        raise HTTPException(status_code=400, detail="Invalid game")

# ===== Cache UID =====
cache_data = {}
CACHE_TTL = {
    "gi": 300,   # 5 phút
    "hsr": 300,  # 5 phút
    "zzz": 900   # 15 phút
}

# ===== Lock tránh gọi API trùng =====
fetch_locks = defaultdict(asyncio.Lock)

async def fetch_showcase(game: str, uid: int):
    now = time.time()
    key = f"{game}:{uid}"
    ttl = CACHE_TTL.get(game, 300)

    # Nếu cache còn hạn → trả luôn
    if key in cache_data and now - cache_data[key]["time"] < ttl:
        return cache_data[key]["data"]

    # Khóa theo UID để tránh fetch trùng
    async with fetch_locks[key]:
        # Kiểm tra lại cache sau khi chờ
        if key in cache_data and now - cache_data[key]["time"] < ttl:
            return cache_data[key]["data"]

        client = await get_client(game)
        data = await client.fetch_showcase(uid)
        cache_data[key] = {"data": data, "time": time.time()}
        return data

# ===== Nhận diện game từ UID =====
def detect_game(uid: int):
    s = str(uid)
    if s.startswith("6") and len(s) == 9:
        return "hsr"
    elif s.startswith("1") and len(s) == 9:
        return "zzz"
    elif len(s) == 9:
        return "gi"
    return None

# ===== Preload assets song song khi startup =====
@app.on_event("startup")
async def warmup():
    asyncio.create_task(preload_clients())

async def preload_clients():
    # UID thật hoặc test account để preload nhanh hơn
    preload_uids = [
        ("gi", 800000000),  # Genshin test UID
        ("hsr", 600000000), # HSR test UID
        ("zzz", 100000000)  # ZZZ test UID
    ]
    tasks = [fetch_showcase(game, uid) for game, uid in preload_uids]
    await asyncio.gather(*tasks)

# ===== API =====
@app.get("/")
async def root():
    return {"status": "ok", "message": "Enka backend is running"}

@app.api_route("/ping", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/ping/", methods=["GET", "HEAD"], include_in_schema=False)
async def ping(request: Request):
    if request.method == "HEAD":
        return PlainTextResponse(status_code=200)
    return PlainTextResponse("pong", status_code=200)

@app.get("/enka/{uid}")
async def get_enka(uid: int):
    game = detect_game(uid)
    if not game:
        raise HTTPException(status_code=400, detail="Unknown UID format")
    try:
        data = await fetch_showcase(game, uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/gi/{uid}")
async def get_gi(uid: int):
    try:
        data = await fetch_showcase("gi", uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/hsr/{uid}")
async def get_hsr(uid: int):
    try:
        data = await fetch_showcase("hsr", uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/zzz/{uid}")
async def get_zzz(uid: int):
    try:
        data = await fetch_showcase("zzz", uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===== API Identity V =====
@app.get("/idv/{roleid}")
async def get_idv(roleid: int):
    url = "https://pay.neteasegames.com/gameclub/identityv/2001/login-role"
    params = {"roleid": roleid, "client_type": "gameclub"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        async with httpx_client as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Request error: {str(e)}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
