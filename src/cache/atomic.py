import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

@dataclass
class LockEntry:
    lock: asyncio.Lock
    refs: int = 0

Lock_map: dict[str, LockEntry] = {}
Lock_map_guard = asyncio.Lock()

@asynccontextmanager
async def token_guard(token: str):
    async with Lock_map_guard:
        le = Lock_map.get(token)
        if le is None:
            le = LockEntry(lock=asyncio.Lock())
            Lock_map[token] = le
        le.refs += 1
    
    try:
        async with le.lock:
            yield
    finally:
        async with Lock_map_guard:
            el = Lock_map.get(token)
            if el is not None:
                el.refs -= 1
                if el.refs <= 0 and (not el.lock.locked()):
                    Lock_map.pop(token, None)
