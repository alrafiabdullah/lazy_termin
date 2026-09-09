import logging
import os
from datetime import timezone
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv

load_dotenv(override=True)

LOG_TO_TERMINAL = os.getenv("DEBUG").strip().lower() == "true"
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
        "app.log",
        when="D",
        interval=7,
        backupCount=5,
        encoding="utf-8",
    )
)
handler.setLevel(LOG_LEVEL)
handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(handler)



TERMIN_URL = os.getenv("TERMIN_URL")
SENDER = os.getenv("SENDER_EMAIL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAXIMUM_ENTRIES = int(os.getenv("MAXIMUM_ENTRIES"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
ALLOWED_DOMAINS = os.getenv("ALLOWED_DOMAINS")

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIMEZONE = timezone.utc