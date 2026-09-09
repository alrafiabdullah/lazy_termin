import logging
import os

from dotenv import load_dotenv
    
load_dotenv(override=True)

LOG_TO_TERMINAL = os.getenv("DEBUG").strip().lower() == "true"
LOG_FORMAT = (
    "%(asctime)s | "
    "%(levelname)-8s | "
    "%(module)s:%(funcName)s:%(lineno)d | "
    "%(message)s"
)

logger = logging.getLogger("lazy_termin")
logger.setLevel(logging.INFO)
logger.propagate = False

handler = (
    logging.StreamHandler()
    if LOG_TO_TERMINAL
    else logging.FileHandler("app.log", mode="a", encoding="utf-8")
)
handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(handler)



TERMIN_URL = os.getenv("TERMIN_URL")
SENDER = os.getenv("SENDER_EMAIL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAXIMUM_ENTRIES = int(os.getenv("MAXIMUM_ENTRIES"))
DB_FILE = os.getenv("DB_FILE")
ADMIN_ID = int(os.getenv("ADMIN_ID"))