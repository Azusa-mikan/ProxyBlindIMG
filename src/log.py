import logging
import re
import sys

from src.config import cfg

LOG_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

class RenameUvicornError(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.error":
            record.name = "fastapi"
        if record.name == "uvicorn.access":
            record.name = "fastapi.access"
        return True


class MaskAccessToken(logging.Filter):
    _token_pattern = re.compile(r"([?&]token=)[^&\s]+")

    @classmethod
    def _mask_token(cls, text: str) -> str:
        return cls._token_pattern.sub(r"\1...", text)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name not in {"uvicorn.access", "fastapi.access"}:
            return True

        # Uvicorn access logger usually stores URL path in record.args[2].
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            args[2] = self._mask_token(str(args[2]))
            record.args = tuple(args)
            return True

        record.msg = self._mask_token(str(record.msg))
        return True

logging.basicConfig(
    level=LOG_LEVEL_MAP[cfg.log_level.upper()],
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

root = logging.getLogger()
for h in root.handlers:
    h.addFilter(RenameUvicornError())
    h.addFilter(MaskAccessToken())

logger = logging.getLogger("fastapi")
