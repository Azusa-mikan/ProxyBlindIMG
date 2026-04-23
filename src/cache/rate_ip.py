import time
import math
import asyncio
from dataclasses import dataclass

from src.config import cfg

BURST_LIMIT = 5
COOLDOWN_SECONDS = 60
IDLE_RESET_SECONDS = 5 * 60
CLEANUP_INTERVAL_SECONDS = 30


@dataclass(slots=True)
class IPRateState:
    burst_used: int = 0
    last_at: float = 0.0


ip_rate_map: dict[str, IPRateState] = {}
ip_rate_lock = asyncio.Lock()
next_cleanup_at: float = 0.0


async def check_and_consume_ip_quota(client_ip: str) -> tuple[bool, int]:
    global next_cleanup_at
    now = time.monotonic()
    async with ip_rate_lock:
        # 按间隔执行全表清理
        if now >= next_cleanup_at:
            to_delete = [
                k for k, v in ip_rate_map.items()
                if v.last_at > 0 and (now - v.last_at) >= IDLE_RESET_SECONDS
            ]
            for k in to_delete:
                ip_rate_map.pop(k, None)
            next_cleanup_at = now + CLEANUP_INTERVAL_SECONDS

        state = ip_rate_map.get(client_ip)
        if state is None:
            state = IPRateState()
            ip_rate_map[client_ip] = state

        if state.last_at > 0 and (now - state.last_at) >= IDLE_RESET_SECONDS:
            state.burst_used = 0

        # 还在 burst 阶段
        if state.burst_used < BURST_LIMIT:
            state.burst_used += 1
            state.last_at = now
            return True, 0

        # burst 用完后，改为每分钟一次
        elapsed = now - state.last_at
        if elapsed < COOLDOWN_SECONDS:
            wait_s = math.ceil(COOLDOWN_SECONDS - elapsed)
            return False, wait_s

        # 冷却完成，允许 1 次
        state.last_at = now
        return True, 0
