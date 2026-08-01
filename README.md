# Lazy Termin

Lazy Termin is a Python automation script that checks a municipal appointment booking page, navigates through the relevant steps, and sends email notifications when a free appointment becomes available.

##
[![Termin Cron](https://github.com/alrafiabdullah/lazy_termin/actions/workflows/termin_cron.yml/badge.svg)](https://github.com/alrafiabdullah/lazy_termin/actions/workflows/termin_cron.yml)
##

## Features
- Opens the appointment page in a headless Chrome browser
- Automates the selection of the relevant service and request type
- Detects whether a free appointment is available
- Sends an email alert through Amazon SES
- Reads recipient addresses from an emails.txt file

## Requirements
- Python 3.10 or newer
- Google Chrome or Chromium installed and available in PATH
- Python packages: boto3, python-dotenv, and selenium
- AWS SES credentials stored in a .env file
- Environment variables: TERMIN_URL, SENDER_EMAIL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION
- An emails.txt file containing one recipient email address per line

```.env
TERMIN_URL=
SENDER_EMAIL=
AWS_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
EMAIL_IDS=

```

## Setup
1. Install the required Python packages:
   pip install boto3 python-dotenv selenium
2. Create a .env file with your configuration values.
3. Create an emails.txt file with one recipient per line.
4. Run the script:
   python main.py

## Notes
- The script uses Selenium to interact with the appointment website and may need updates if the site structure changes.
- Ensure your AWS SES sender address is verified in the AWS account you are using.

## Credits
Built and maintained by Abdullah Al Rafi.
Website: [abdullahalrafi.com](https://abdullahalrafi.com?ti=lt)