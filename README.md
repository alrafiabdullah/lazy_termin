# Lazy Termin

Lazy Termin is a Python automation script that checks an appointment booking webpage, moves through the required steps, and sends a Telegram or email alert when a free appointment is detected.

## Features

- Opens the target booking page in Chrome
- Automates the booking flow with Selenium
- Detects whether an appointment is available
- Sends notifications through Telegram or Amazon SES
- Queues Telegram alerts in a PostgreSQL outbox so none are lost or sent twice
- Supports multiple recipient email addresses from environment variables
- Stores Telegram subscriptions in PostgreSQL for five days
- Rotates file logs every seven days when debug logging is disabled

## Requirements

- Python 3.10 or newer
- Google Chrome or Chromium installed and available in `PATH`
- Python packages: `boto3`, `python-dotenv`, `psycopg2-binary`, `python-telegram-bot[job-queue]`, and `selenium`
- AWS SES credentials
- A `.env` file with the configuration values below

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

- `EMAIL_IDS` should contain a comma-separated list of recipient email addresses used by email notifications.
- `ALLOWED_DOMAINS` should contain a comma-separated list of allowed email domains for Telegram subscriptions.
- `MAXIMUM_ENTRIES` limits the number of active `@uni-trier.de` subscriptions.
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` configure the PostgreSQL database used for subscriptions.
- Set `DEBUG=False` to write `INFO` and higher logs to `app.log`. The file rotates every seven days and keeps five archived files. Set it to `True` to enable debug logs in the terminal.
- `ALERT_COOLDOWN_MINUTES` (default 60) stops a new appointment alert from being queued while another one was queued within that many minutes.
- Find your `ADMIN_ID` by sending a message to your bot and checking the logs for the user ID.

## Setup

1. Install the required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

2. Create `.env` from `.env.example` and fill in the required settings.
3. Make sure the sender address is verified in Amazon SES if you use email notifications.
4. Run the appointment checker:

   ```bash
   python -m lazy_termin.scraper
   ```

   Telegram notifications are used by default: the checker queues an alert in the database and the bot delivers it. To use email notifications instead, pass `--use_email` (or `-ue`):

   ```bash
   python -m lazy_termin.scraper --use_email
   ```

5. Run the Telegram bot. It is the only process that talks to Telegram: it handles subscriptions and delivers queued alerts:

   ```bash
   python -m lazy_termin.bot
   ```

   Users can use `/subscribe`, `/confirm`, `/cancel`, `/unsubscribe`, and `/help`. The subscription flow verifies the user's allowed email domain and sends a one-time verification code through Amazon SES.

6. Testing:

   ```bash
   python -m unittest discover -s tests -t . -v
   ```

   The test suite currently covers:

   - PostgreSQL subscriber insertion, duplicate prevention, deletion, active subscriber lookup, expiry handling, forced deactivation, and subscription limits.
   - Earliest active subscriber expiry calculation, including the empty-database default.
   - Email recipient parsing, email body generation, SES sending, and missing credentials.
   - Telegram subscription flow from `/subscribe` through name entry, email verification, OTP verification, and confirmation.
   - Telegram unsubscription for both subscribed and non-subscribed users.
   - Telegram help, admin-message, message telemetry, and pooled database connection handlers.
   - Notification outbox: cooldown deduplication, claiming with `SKIP LOCKED`, retry until `failed` after three attempts, and stuck-row recovery.
   - Outbox dispatcher, subscription expiry on a single database connection, and rate-limit retry.
   - Selenium click fallback behavior when a click is intercepted, and `driver.quit()` on early return or error.

   The suite contains 35 tests and requires access to a local PostgreSQL database.
   Set `TEST_DB_NAME`, `TEST_DB_USER`, `TEST_DB_PASSWORD`, `TEST_DB_HOST`, and
   `TEST_DB_PORT` for a dedicated local test database. `TEST_DB_HOST` defaults to
   `127.0.0.1` and `TEST_DB_PORT` defaults to `5432`; non-local hosts are rejected.

   Incoming Telegram messages are tracked in PostgreSQL without storing their contents.
   The bot records the UTC timestamp, Telegram user ID, update ID, and whether the update
   was a command or regular message. Admins can view the previous 24-hour message and
   unique-user counts with `/astatus`.

## Project Structure

```text
lazy_termin/
├── lazy_termin/        # Application package
│   ├── config.py       # Settings loaded from .env
│   ├── log.py          # Logger setup
│   ├── db.py           # PostgreSQL access and the notification outbox
│   ├── mailer.py       # Amazon SES email
│   ├── scraper.py      # Selenium appointment checker
│   └── bot.py          # Telegram bot and its scheduled jobs
├── tests/              # Unit tests, one file per module
├── .github/workflows/  # GitHub Actions workflow
├── .env.example        # Configuration template
├── compose.yaml        # Docker Compose services
├── crontab             # Scraper schedule (Europe/Berlin)
├── Dockerfile
└── requirements.txt
```

## How It Works

1. The checker (`lazy_termin/scraper.py`) opens the configured booking page and goes through the booking flow with Selenium.
2. If a free appointment is found, it inserts an `APPOINTMENT_FOUND` row into the `notification_outbox` table and sends `NOTIFY notification_outbox`. With `--use_email`, it emails every address in `EMAIL_IDS` instead.
3. The bot (`lazy_termin/bot.py`) wakes on the `NOTIFY`, or polls every 20 seconds, claims pending rows, and messages every active subscriber. A failed row is retried up to three times, then marked `failed` and reported to the admin.
4. The bot also runs its own jobs: subscription expiry every 15 minutes, deletion of outbox and message-event rows older than 30 days at 03:00 UTC, and a heartbeat file for the Docker health check.
5. Subscriber records are stored in PostgreSQL and expire after five days.

## GitHub Actions

This repository also includes a GitHub Actions workflow for running the checker in the cloud. Its alerts are queued in the outbox of the database it connects to, so a bot must be running against the same database.

- The workflow runs on weekdays during the configured Europe/Berlin time windows and can also be started manually from the Actions tab.
- It installs the dependencies, sets up Chrome, and runs `python -m lazy_termin.scraper`.
- Because the checker uses Telegram by default, configure `TELEGRAM_BOT_TOKEN`, `MAXIMUM_ENTRIES`, the PostgreSQL connection settings, `ADMIN_ID`, and `ALLOWED_DOMAINS` as workflow secrets and add them to the workflow environment before using the scheduled job.
- For the email path, configure `TERMIN_URL`, `SENDER_EMAIL`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SES_CONFIGURATION_SET`, and `EMAIL_IDS`, and run `python -m lazy_termin.scraper --use_email`.

## Notes

- The booking flow depends on the target website structure, so selectors may need updates if the page changes.
- This repository is intended as a general automation template for appointment availability checks.
- If you do not need a configuration set in SES, you can leave `AWS_SES_CONFIGURATION_SET` blank.

## Legal and Responsible Use

This project is an appointment-availability monitoring tool. It is intended to check publicly accessible appointment information using the normal website flow and to notify users when availability is detected.

Users are responsible for complying with the terms of use, acceptable-use policies, and applicable laws governing the appointment website they monitor. The software must not be used to bypass authentication, CAPTCHA, rate limits, access controls, or other technical security measures, and must not generate traffic that interferes with the availability or operation of the target service.

The project does not automatically book appointments. Users should complete the appointment process themselves through the official government website.

When operating the notification component, operators should collect only the personal data necessary for the notification service, protect stored data appropriately, and delete subscriber data when it is no longer required.


## Credits

Built and maintained by Abdullah Al Rafi.
Website: [abdullahalrafi.com](https://abdullahalrafi.com?ti=lt)
