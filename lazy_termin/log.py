import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import LOG_DIR, LOG_TO_TERMINAL

LOG_LEVEL = logging.DEBUG if LOG_TO_TERMINAL else logging.INFO
LOG_FORMAT = (
    "%(asctime)s | "
    "%(levelname)-8s | "
    "%(module)s:%(funcName)s:%(lineno)d | "
    "%(message)s"
)

logger = logging.getLogger("lazy_termin")
logger.setLevel(LOG_LEVEL)
logger.propagate = False

if LOG_TO_TERMINAL:
    handler = logging.StreamHandler()
else:
    # One file per entry point (scraper.log, bot.log), so the two processes never rotate the same file.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        LOG_DIR / f"{Path(sys.argv[0]).stem}.log",
        when="D",
        interval=7,
        backupCount=5,
        encoding="utf-8",
    )
handler.setLevel(LOG_LEVEL)
handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(handler)
