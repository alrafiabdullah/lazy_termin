# Lazy Termin

Lazy Termin is a Python automation script that checks an appointment booking webpage, moves through the required steps, and sends a Telegram or email alert when a free appointment is detected.

## Features

- Opens the target booking page in Chrome
- Automates the booking flow with Selenium
- Detects whether an appointment is available
- Sends notifications through Telegram or Amazon SES
- Supports multiple recipient email addresses from environment variables
- Stores Telegram subscriptions in SQLite for five days
- Rotates file logs every seven days when debug logging is disabled

## Requirements

- Python 3.10 or newer
- Google Chrome or Chromium installed and available in `PATH`
- Python packages: `boto3`, `python-dotenv`, `pysqlite3`, `python-telegram-bot`, and `selenium`
- AWS SES credentials
- A `.env` file with the configuration values below

## Configuration

Create a `.env` file in the project root:

```env
TERMIN_URL=
SENDER_EMAIL=
AWS_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SES_CONFIGURATION_SET=
EMAIL_IDS=
TELEGRAM_BOT_TOKEN=
MAXIMUM_ENTRIES=
DEBUG=
DB_FILE=
ADMIN_ID=
ALLOWED_DOMAINS=
```

- `EMAIL_IDS` should contain a comma-separated list of recipient email addresses used by email notifications.
- `ALLOWED_DOMAINS` should contain a comma-separated list of allowed email domains for Telegram subscriptions.
- `MAXIMUM_ENTRIES` limits the number of active `@uni-trier.de` subscriptions.
- `DB_FILE` is the SQLite database file used for subscriptions.
- Set `DEBUG=False` to write `INFO` and higher logs to `app.log`. The file rotates every seven days and keeps five archived files. Set it to `True` to enable debug logs in the terminal.
- Find your `ADMIN_ID` by sending a message to your bot and checking the logs for the user ID.

## Setup

1. Install the required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file and fill in the required settings.
3. Make sure the sender address is verified in Amazon SES if you use email notifications.
4. Run the appointment checker:

   ```bash
   python main.py
   ```

   Telegram notifications are used by default. To use email notifications instead, pass `--use_email` (or `-ue`):

   ```bash
   python main.py --use_email
   ```

5. Run the Telegram bot separately to manage subscriptions:

   ```bash
   python tele_bot.py
   ```

   Users can use `/subscribe`, `/confirm`, `/cancel`, `/unsubscribe`, and `/help`. The subscription flow verifies the user's allowed email domain and sends a one-time verification code through Amazon SES.

6. Testing:

   ```bash
   python -m unittest tests.py -v
   ```

## How It Works

1. The script opens the configured booking page.
2. It navigates through the booking flow using Selenium.
3. If a free appointment is found, it sends a Telegram message to active subscribers or an email to every address in `EMAIL_IDS`.
4. Subscriber records are stored in the SQLite database configured by `DB_FILE` and expire after five days.

## GitHub Actions

This repository also includes a GitHub Actions workflow for running the checker in the cloud.

- The workflow runs on weekdays during the configured Europe/Berlin time windows and can also be started manually from the Actions tab.
- It installs the dependencies, sets up Chrome, and runs `python main.py`.
- Because `main.py` uses Telegram by default, configure `TELEGRAM_BOT_TOKEN`, `MAXIMUM_ENTRIES`, `DB_FILE`, `ADMIN_ID`, and `ALLOWED_DOMAINS` as workflow secrets and add them to the workflow environment before using the scheduled job.
- For the email path, configure `TERMIN_URL`, `SENDER_EMAIL`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SES_CONFIGURATION_SET`, and `EMAIL_IDS`, and run `python main.py --use_email`.

## Notes

- The booking flow depends on the target website structure, so selectors may need updates if the page changes.
- This repository is intended as a general automation template for appointment availability checks.
- If you do not need a configuration set in SES, you can leave `AWS_SES_CONFIGURATION_SET` blank.

## Credits

Built and maintained by Abdullah Al Rafi.
Website: [abdullahalrafi.com](https://abdullahalrafi.com?ti=lt)
