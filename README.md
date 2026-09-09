# Lazy Termin

Lazy Termin is a Python automation script that checks an appointment booking webpage, moves through the required steps, and sends an email alert when a free appointment is detected.

## Features
- Opens the target booking page in a headless Chrome browser
- Automates the booking flow with Selenium
- Detects whether an appointment is available
- Sends notifications through Amazon SES
- Supports multiple recipient email addresses from environment variables

## Requirements
- Python 3.10 or newer
- Google Chrome or Chromium installed and available in `PATH`
- Python packages: `boto3`, `python-dotenv`, and `selenium`
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

- `EMAIL_IDS` should contain a comma-separated list of recipient email addresses.
- `ALLOWED_DOMAINS` should contain a comma-separated list of allowed email domains.
- Set `DEBUG=False` to write logs to `app.log`; leave it as `True` to show logs in the terminal.
- Find your `ADMIN_ID` by sending a message to your bot and checking the logs for the `user ID`.

## Setup
1. Install the required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file and fill in your booking URL, SES credentials, sender address, and recipient addresses.
3. Make sure the sender address is verified in Amazon SES.
4. Run the script:

   ```bash
   python main.py
   ```
5. Testing:
   ```bash
   python -m unittest tests.py -v
   ```

## How It Works
1. The script opens the configured booking page.
2. It navigates through the booking flow using Selenium.
3. If a free appointment is found, it sends an email to every address in `EMAIL_IDS`.

## GitHub Actions
This repository also includes a GitHub Actions workflow for running the checker in the cloud.

- The workflow can run on a schedule and can also be started manually from the Actions tab.
- It installs the dependencies, sets up Chrome, and runs `python main.py`.
- It expects the same configuration values to be stored as repository secrets, including `TERMIN_URL`, `SENDER_EMAIL`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SES_CONFIGURATION_SET`, and `EMAIL_IDS`.

## Notes
- The booking flow depends on the target website structure, so selectors may need updates if the page changes.
- This repository is intended as a general automation template for appointment availability checks.
- If you do not need a configuration set in SES, you can leave `AWS_SES_CONFIGURATION_SET` blank.

## Credits
Built and maintained by Abdullah Al Rafi.
Website: [abdullahalrafi.com](https://abdullahalrafi.com?ti=lt)