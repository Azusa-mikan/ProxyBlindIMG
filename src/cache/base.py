from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
import orjson
import pickle
from pathlib import Path

import redis.asyncio as redis

from src.config import cfg


cache_file = Path(__file__).parents[2] / "cache.tmp"


@dataclass(kw_only=True)
class TokenCache:
    upload_count: int
    read_count: int
    expired: int


class BaseCache(ABC):
    @abstractmethod
    async def get(self, token: str) -> TokenCache | None:
        ...
    
    @abstractmethod
    async def set(self, token: str, ttl: int = 0):
        ...

    @abstractmethod
    async def consume_upload(self, token: str) -> bool:
        ...

    @abstractmethod
    async def consume_read(self, token: str) -> bool:
        ...
    
    @abstractmethod
    async def delete(self, token: str):
        ...

class MemoryCache(BaseCache):
    def __init__(self) -> None:
        self.token_cache: dict[str, TokenCache] = (
            pickle.loads(cache_file.read_bytes())
            if cache_file.exists()
            else {}
        )
    
    def save(self):
        cache_file.write_bytes(
            pickle.dumps(self.token_cache)
        )
    
    async def get(self, token: str) -> TokenCache | None:
        data = self.token_cache.get(token)
        if data is None:
            return None

        if data.expired < 0:
            return TokenCache(
                upload_count=data.upload_count,
                read_count=data.read_count,
                expired=-1,
            )

        remain = data.expired - time.monotonic()
        if remain <= 0:
            self.token_cache.pop(token, None)
            return None

        return TokenCache(
            upload_count=data.upload_count,
            read_count=data.read_count,
            expired=int(remain),
        )
    
    async def set(self, token: str, ttl: int = 0):
        self.token_cache[token] = TokenCache(
            upload_count=1,
            read_count=10,
            expired=int((time.monotonic() + ttl) if ttl > 0 else -1)
        )

    async def consume_upload(self, token: str) -> bool:
        data = self.token_cache.get(token)
        if data is None:
            return False

        if data.expired >= 0 and data.expired <= time.monotonic():
            self.token_cache.pop(token, None)
            return False

        if data.upload_count <= 0:
            return False

        data.upload_count -= 1
        if data.upload_count <= 0 and data.read_count <= 0:
            self.token_cache.pop(token, None)
        return True

    async def consume_read(self, token: str) -> bool:
        data = self.token_cache.get(token)
        if data is None:
            return False

        if data.expired >= 0 and data.expired <= time.monotonic():
            self.token_cache.pop(token, None)
            return False

        if data.read_count <= 0:
            return False

        data.read_count -= 1
        if data.upload_count <= 0 and data.read_count <= 0:
            self.token_cache.pop(token, None)
        return True
    
    async def delete(self, token: str):
        self.token_cache.pop(token, None)

class RedisCache(BaseCache):
    def __init__(self) -> None:
        self.rc = redis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            db=cfg.redis_db,
        )
        self._consume_upload_lua = """
            local key = KEYS[1]
            local raw = redis.call('GET', key)
            if not raw then return 0 end
            local obj = cjson.decode(raw)
            local up = tonumber(obj['upload_count']) or 0
            local rd = tonumber(obj['read_count']) or 0
            if up <= 0 then return 0 end
            up = up - 1
            obj['upload_count'] = up
            if up <= 0 and rd <= 0 then redis.call('DEL', key); return 1 end
            local ttl = redis.call('TTL', key)
            local new_raw = cjson.encode(obj)
            if ttl > 0 then redis.call('SET', key, new_raw, 'EX', ttl) else redis.call('SET', key, new_raw) end
            return 1
            """
        self._consume_read_lua = """
            local key = KEYS[1]
            local raw = redis.call('GET', key)
            if not raw then return 0 end
            local obj = cjson.decode(raw)
            local up = tonumber(obj['upload_count']) or 0
            local rd = tonumber(obj['read_count']) or 0
            if rd <= 0 then return 0 end
            rd = rd - 1
            obj['read_count'] = rd
            if up <= 0 and rd <= 0 then redis.call('DEL', key); return 1 end
            local ttl = redis.call('TTL', key)
            local new_raw = cjson.encode(obj)
            if ttl > 0 then redis.call('SET', key, new_raw, 'EX', ttl) else redis.call('SET', key, new_raw) end
            return 1
            """
    
    async def ping(self):
        return await self.rc.ping() # type: ignore

    async def close(self):
        await self.rc.aclose()

    async def get(self, token: str) -> TokenCache | None:
        key = f"proxyblindimg:token:{token}"
        raw = await self.rc.get(key)
        if raw is None:
            return None
        ttl = await self.rc.ttl(key)
        raw_dict = orjson.loads(raw)
        return TokenCache(
            upload_count=raw_dict["upload_count"],
            read_count=raw_dict["read_count"],
            expired=ttl # 实际上没什么用，因为 Redis 会自己删掉过期键
        )

    async def set(self, token: str, ttl: int = 0):
        key = f"proxyblindimg:token:{token}"
        raw = orjson.dumps(
            {
                "upload_count": 1,
                "read_count": 10,
            }
        )
        if ttl > 0:
            await self.rc.set(key, raw, ex=ttl)
        else:
            await self.rc.set(key, raw)

    async def consume_upload(self, token: str) -> bool:
        key = f"proxyblindimg:token:{token}"
        result = await self.rc.eval(self._consume_upload_lua, 1, key) # type: ignore
        return int(result) == 1

    async def consume_read(self, token: str) -> bool:
        key = f"proxyblindimg:token:{token}"
        result = await self.rc.eval(self._consume_read_lua, 1, key) # type: ignore
        return int(result) == 1
    
    async def delete(self, token: str):
        key = f"proxyblindimg:token:{token}"
        await self.rc.delete(key)