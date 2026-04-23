import ipaddress
import asyncio

from fastapi import Request

class CounterService:
    def __init__(self, initial: int = 0) -> None:
        self._value = initial
        self._lock = asyncio.Lock()

    async def inc(self, n: int = 1) -> int:
        async with self._lock:
            self._value += n
            return self._value

    async def get(self) -> int:
        async with self._lock:
            return self._value

    async def reset(self) -> None:
        async with self._lock:
            self._value = 0

class FileDecryptError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)

def get_client_ip(request: Request) -> str:
    # 仅当直连方是本机或私网地址时，才信任反向代理透传的 IP 头。
    peer = request.client.host if request.client else "0.0.0.0"
    trust_forward_headers = False
    try:
        peer_ip = ipaddress.ip_address(peer)
        trust_forward_headers = peer_ip.is_loopback or peer_ip.is_private
    except ValueError:
        trust_forward_headers = False

    if trust_forward_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first_ip = xff.split(",")[0].strip()
            try:
                ipaddress.ip_address(first_ip)
                return first_ip
            except ValueError:
                pass

        x_real_ip = request.headers.get("x-real-ip")
        if x_real_ip:
            ip = x_real_ip.strip()
            try:
                ipaddress.ip_address(ip)
                return ip
            except ValueError:
                pass

    return peer