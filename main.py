import uvicorn

from src.api import app
from src.config import cfg

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=cfg.port,
        log_config=None,
    )