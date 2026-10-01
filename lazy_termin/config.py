import os
from datetime import timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

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
# Minimum minutes between alerts to the same subscriber.
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES") or "60")
if ALERT_COOLDOWN_MINUTES < 2:
    raise ValueError("ALERT_COOLDOWN_MINUTES must be at least 2.")

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIMEZONE = timezone.utc

LOG_DIR = Path(os.getenv("LOG_DIR") or "logs")
LOG_TO_TERMINAL = os.getenv("DEBUG").strip().lower() == "true"
