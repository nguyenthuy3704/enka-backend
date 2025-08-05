from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import enka

app = FastAPI(redirect_slashes=False)

# Thiết lập CORS cho các origin được phép
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

# Tạo client cho 3 game
genshin_client = enka.GenshinClient(enka.gi.Language.ENGLISH)
hsr_client = enka.HSRClient(enka.hsr.Language.ENGLISH)
zzz_client = enka.ZZZClient(enka.zzz.Language.ENGLISH)

@app.on_event("startup")
async def startup():
    await genshin_client.__aenter__()
    await hsr_client.__aenter__()
    await zzz_client.__aenter__()

@app.on_event("shutdown")
async def shutdown():
    await genshin_client.__aexit__(None, None, None)
    await hsr_client.__aexit__(None, None, None)
    await zzz_client.__aexit__(None, None, None)

# Nhận diện game từ UID
def detect_game(uid: int):
    uid_str = str(uid)
    if uid_str.startswith("6") and len(uid_str) == 9:
        return "hsr"
    elif uid_str.startswith("1") and len(uid_str) == 9:
        return "zzz"
    elif len(uid_str) == 9:
        return "gi"
    return None

# Hàm fetch dữ liệu chung
async def fetch_showcase(game: str, uid: int):
    if game == "gi":
        return await genshin_client.fetch_showcase(uid)
    if game == "hsr":
        return await hsr_client.fetch_showcase(uid)
    if game == "zzz":
        return await zzz_client.fetch_showcase(uid)
    raise HTTPException(status_code=400, detail="Invalid game detection")

# Route tự động nhận diện game
@app.get("/enka/{uid}")
async def get_enka_data(uid: int):
    game = detect_game(uid)
    if not game:
        raise HTTPException(status_code=400, detail="Unknown UID format")
    try:
        data = await fetch_showcase(game, uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route riêng cho Genshin
@app.get("/gi/{uid}")
async def get_genshin(uid: int):
    try:
        data = await fetch_showcase("gi", uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route riêng cho Honkai: Star Rail
@app.get("/hsr/{uid}")
async def get_hsr(uid: int):
    try:
        data = await fetch_showcase("hsr", uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route riêng cho Zenless Zone Zero
@app.get("/zzz/{uid}")
async def get_zzz(uid: int):
    try:
        data = await fetch_showcase("zzz", uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.responses import PlainTextResponse
from fastapi.requests import Request

@app.api_route("/ping", methods=["GET","HEAD"], include_in_schema=False)
@app.api_route("/ping/", methods=["GET","HEAD"], include_in_schema=False)
async def ping(request: Request):
    if request.method == "HEAD":
        return PlainTextResponse(status_code=200)
    return PlainTextResponse("pong", status_code=200)


import httpx

@app.get("/idv/{roleid}")
async def get_identityv_data(roleid: int):
    url = f"https://pay.neteasegames.com/gameclub/identityv/2001/login-role"
    params = {
        "roleid": roleid,
        "client_type": "gameclub"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

