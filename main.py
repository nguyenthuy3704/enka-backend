from fastapi import FastAPI, HTTPException
import enka

app = FastAPI()

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

# Tự động nhận diện game từ UID
def detect_game(uid: int):
    uid_str = str(uid)
    if uid_str.startswith("6") and len(uid_str) == 9:
        return "hsr"
    elif uid_str.startswith("1") and len(uid_str) == 9:
        return "zzz"
    elif len(uid_str) == 9:
        return "gi"
    else:
        return None

# Route tự động nhận diện game
@app.get("/enka/{uid}")
async def get_enka_data(uid: int):
    game = detect_game(uid)
    if game is None:
        raise HTTPException(status_code=400, detail="Unknown UID format")

    try:
        if game == "gi":
            data = await genshin_client.fetch_showcase(uid)
        elif game == "hsr":
            data = await hsr_client.fetch_showcase(uid)
        elif game == "zzz":
            data = await zzz_client.fetch_showcase(uid)
        else:
            raise HTTPException(status_code=400, detail="Invalid game detection")
        
        return data.model_dump()  # Trả toàn bộ JSON của Enka
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route riêng cho Genshin
@app.get("/gi/{uid}")
async def get_genshin(uid: int):
    try:
        data = await genshin_client.fetch_showcase(uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route riêng cho Honkai: Star Rail
@app.get("/hsr/{uid}")
async def get_hsr(uid: int):
    try:
        data = await hsr_client.fetch_showcase(uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Route riêng cho Zenless Zone Zero
@app.get("/zzz/{uid}")
async def get_zzz(uid: int):
    try:
        data = await zzz_client.fetch_showcase(uid)
        return data.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
