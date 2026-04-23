import os
from typing import Literal, cast
from dataclasses import dataclass

from dotenv import load_dotenv

LOG_MODE = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

@dataclass(slots=True, kw_only=True)
class Config:
    log_level: LOG_MODE
    port: int
    token: str
    use_redis: int
    redis_host: str
    redis_port: int
    redis_db: int


load_dotenv()
token = os.environ["token"]
if len(token) < 32:
    raise ValueError("token must be at least 32 characters long")

cfg = Config(
    log_level=cast(LOG_MODE, os.environ["log_level"]),
    port=int(os.getenv("port") or 8000),
    token=token,
    use_redis=int(os.environ["use_redis"]),
    redis_host=os.getenv("redis_host") or "127.0.0.1",
    redis_port=int(os.getenv("redis_port") or 6379),
    redis_db=int(os.getenv("redis_db") or 0),
)