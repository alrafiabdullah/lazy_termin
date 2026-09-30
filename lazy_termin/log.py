import logging
from logging.handlers import TimedRotatingFileHandler

from .config import LOG_PATH, LOG_TO_TERMINAL

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

handler = (
    logging.StreamHandler()
    if LOG_TO_TERMINAL
    else TimedRotatingFileHandler(
        LOG_PATH,
        when="D",
        interval=7,
        backupCount=5,
        encoding="utf-8",
    )
)
handler.setLevel(LOG_LEVEL)
handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(handler)
