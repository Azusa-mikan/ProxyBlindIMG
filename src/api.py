import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
import secrets

from fastapi import (
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    Response,
    Depends,
    Request
)
from fastapi.templating import Jinja2Templates

from src.taskbus import (
    Picenc,
    Picdec,
    images_encrypt_task,
    images_decrypt_task,
    autoscaler,
)
from src.config import cfg
from src.util import CounterService, FileDecryptError, get_client_ip
from src.cache.base import MemoryCache, RedisCache
from src.cache import cache_interface, close_cache
from src.cache.rate_ip import check_and_consume_ip_quota
from src.cache.atomic import token_guard
from src.sch import init_scheduler
from src.edncrypt import encrypt_image_path

@asynccontextmanager
async def custom_lifespan(app: FastAPI):
    t = asyncio.create_task(autoscaler())
    app.state.cache = await cache_interface()
    app.state.counter = CounterService()
    sch = init_scheduler(app)
    sch.start()
    try:
        yield
    finally:
        t.cancel()
        await t
        await close_cache(app.state.cache)
        sch.shutdown(wait=False)


app = FastAPI(lifespan=custom_lifespan)
templates = Jinja2Templates(
    directory=(Path(__file__).parent / "templates")
)

CacheType = MemoryCache | RedisCache


def get_cache(request: Request) -> CacheType:
    return request.app.state.cache

def get_counter(request: Request) -> CounterService:
    return request.app.state.counter

@app.get("/")
async def index(request: Request):
    counter: CounterService = request.app.state.counter
    image_count = sum(1 for p in encrypt_image_path.iterdir() if p.is_file())
    if cfg.use_custom_index <= 0:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "image_count": image_count,
                "today_requests": await counter.get(),
            }
        )
    else:
        return templates.TemplateResponse(
            request=request,
            name="custom_index.html",
            context={
                "custom_text": cfg.index_title,
                "image_count": image_count,
                "today_requests": await counter.get(),
            }
        )

@app.get("/token")
async def get_token(
        request: Request,
        cache: CacheType = Depends(get_cache),
        counter: CounterService = Depends(get_counter)
    ):
    """获取一次性Token用于图片上传和获取"""
    client_ip = get_client_ip(request)
    ok, retry_after = await check_and_consume_ip_quota(client_ip)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，请 {retry_after}s 后再试",
        )

    new_token = secrets.token_hex(16)
    await cache.set(new_token, 300)
    await counter.inc()
    return {
        "success": True,
        "new_token": new_token
    }

@app.post("/upload")
async def upload_image(
        file: UploadFile = File(...),
        token: str = Header(..., alias="X-PBIMG-Token"),
        cache: CacheType = Depends(get_cache),
        counter: CounterService = Depends(get_counter)
    ):
    data = await file.read()
    is_jpg = data.startswith(b"\xff\xd8\xff")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    if not (is_jpg or is_png):
        raise HTTPException(status_code=400, detail="文件内容不是有效 JPG/PNG")

    async with token_guard(token):
        ok = await cache.consume_upload(token)
        if not ok:
            raise HTTPException(status_code=403, detail="TOKEN 已过期或上传次数已尽")

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
    await counter.inc()
    return {
        "success": True,
        "filename": encrypted_file_name
    }

@app.get("/image/{file_name}")
async def get_image(
        file_name: str,
        token: str,
        cache: CacheType = Depends(get_cache),
        counter: CounterService = Depends(get_counter)
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

    async with token_guard(token):
        ok = await cache.consume_read(token)
        if not ok:
            raise HTTPException(status_code=403, detail="TOKEN 已过期或解密次数已尽")
    
    media_type = "application/octet-stream"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"

    await counter.inc()
    return Response(
        content=image_bytes,
        media_type=media_type
    )
