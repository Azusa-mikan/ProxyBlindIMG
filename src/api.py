import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Header, HTTPException, UploadFile, Response
from fastapi.responses import FileResponse
from redis import RedisError

from src.config import cfg
from src.taskbus import (
    Picenc,
    Picdec,
    images_encrypt_task,
    images_decrypt_task,
    autoscaler,
)
from src.log import logger
from src.util import FileDecryptError
from src.cache import MemoryCache, RedisCache

cache: RedisCache | MemoryCache = MemoryCache()

@asynccontextmanager
async def custom_lifespan(app: FastAPI):
    global cache
    warn_msg = "Redis Connect Failed, Fallback to Memory"
    t = asyncio.create_task(autoscaler())
    try:
        if cfg.use_redis > 0:
            cache = RedisCache()
            if await cache.ping():
                logger.info("Redis Connected")
            else:
                await cache.close()
                cache = MemoryCache()
                logger.warning(warn_msg)
        else:
            cache = MemoryCache()
    except RedisError:
        if isinstance(cache, RedisCache):
            await cache.close()
        cache = MemoryCache()
        logger.warning(warn_msg)
    try:
        yield
    finally:
        t.cancel()
        await t
        if isinstance(cache, RedisCache):
            await cache.close()
            logger.info("Redis Disconnected")
        else:
            cache.save()


app = FastAPI(lifespan=custom_lifespan)
index_html = Path(__file__).parent / "resources" / "index.html"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(index_html)

@app.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    token: str = Header(..., alias="X-PBIMG-Token")
    ):
    data = await file.read()
    is_jpg = data.startswith(b"\xff\xd8\xff")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    if not (is_jpg or is_png):
        raise HTTPException(status_code=400, detail="文件内容不是有效 JPG/PNG")

    fut: asyncio.Future[str] = (
        asyncio.get_running_loop().create_future()
    )
    try:
        images_encrypt_task.put_nowait(
            Picenc(token=token, image_bytes=data, fut=fut)
        )
    except asyncio.QueueFull:
        raise HTTPException(status_code=429, detail="服务器过载，请稍后再试")

    encrypted_file_name: str = await fut
    return {
        "success": True,
        "filename": encrypted_file_name
    }

@app.get("/image/{file_name}")
async def get_image(
    file_name: str,
    token: str
    ):
    if len(token) < 32:
        raise HTTPException(status_code=403, detail="TOKEN 不合法")

    fut: asyncio.Future[bytes] = (
        asyncio.get_running_loop().create_future()
    )
    try:
        images_decrypt_task.put_nowait(
            Picdec(
                token=token,
                file_name=file_name,
                fut=fut
            )
        )
    except asyncio.QueueFull:
        raise HTTPException(status_code=429, detail="服务器过载，请稍后再试")
    
    try:
        image_bytes: bytes = await fut
    except FileDecryptError:
        raise HTTPException(status_code=403, detail="图片解密失败")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="图片已过期")
    
    media_type = "application/octet-stream"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"

    return Response(
        content=image_bytes,
        media_type=media_type
    )