from redis import RedisError

from src.config import cfg
from src.log import logger
from src.cache.base import MemoryCache, RedisCache

async def cache_interface() -> RedisCache | MemoryCache:
    warn_msg = "Redis Connect Failed, Fallback to Memory"
    try:
        if cfg.use_redis > 0:
            interface = RedisCache()
            if await interface.ping():
                logger.info("Redis Connected")
            else:
                await interface.close()
                interface = MemoryCache()
                logger.warning(warn_msg)
        else:
            interface = MemoryCache()
    except RedisError:
        interface = MemoryCache()
        logger.warning(warn_msg)
    
    return interface

async def close_cache(interface: MemoryCache | RedisCache) -> None:
    if isinstance(interface, RedisCache):
        await interface.close()
        logger.info("Redis Disconnected")
    else:
        interface.save()