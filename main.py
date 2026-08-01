import logging
import os
import random
import time

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

logging.basicConfig(
    format=(
        "%(asctime)s | "
        "%(levelname)-8s | "
        "%(module)s:%(funcName)s:%(lineno)d | "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


def get_random_wait_time():
    wait_time = random.uniform(1, 3)  # Random wait time between 1 and 3 seconds
    logger.info(f"Waiting for {wait_time:.2f} seconds...")
    time.sleep(wait_time)


def click_element(driver, element):
    try:
        element.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        logger.warning("Primary click failed; trying a JavaScript click.")
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
            element,
        )


def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument("--disable-gpu")  # Disable GPU acceleration
    options.add_argument("--no-sandbox")  # Bypass OS security model
    driver = webdriver.Chrome(options=options)
    return driver

def get_email_addresses():
    with open("emails.txt", "r") as file:
        email_addresses = [line.strip() for line in file if line.strip()]

    return email_addresses

def get_email_body(body):
    return f"""
    <!DOCTYPE html>
        <html lang="en">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>New Appointment Available</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
            color: #1f2937;
        ">

            <table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"
                style="background-color: #f4f6f8;">
                <tr>
                    <td align="center" style="padding: 40px 15px;">

                        <!-- Main container -->
                        <table width="600" border="0" cellpadding="0" cellspacing="0" role="presentation" style="
                                width: 100%;
                                max-width: 600px;
                                background-color: #ffffff;
                                border-radius: 12px;
                                overflow: hidden;
                            ">

                            <!-- Header -->
                            <tr>
                                <td align="center" style="
                                        padding: 32px 30px;
                                        background-color: #2563eb;
                                    ">
                                    <div style="
                                        font-size: 30px;
                                        line-height: 36px;
                                        margin-bottom: 8px;
                                    ">
                                        📅
                                    </div>

                                    <h1 style="
                                        margin: 0;
                                        color: #ffffff;
                                        font-size: 26px;
                                        line-height: 34px;
                                        font-weight: 700;
                                    ">
                                        New Appointment Available
                                    </h1>

                                    <p style="
                                        margin: 8px 0 0 0;
                                        color: #dbeafe;
                                        font-size: 15px;
                                        line-height: 22px;
                                    ">
                                        An appointment matching your alert is available.
                                    </p>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 35px 35px 30px 35px;">

                                    <p style="
                                        margin: 0 0 20px 0;
                                        font-size: 16px;
                                        line-height: 26px;
                                        color: #374151;
                                    ">
                                        Hello,
                                    </p>

                                    <p style="
                                        margin: 0 0 25px 0;
                                        font-size: 16px;
                                        line-height: 26px;
                                        color: #374151;
                                    ">
                                        A new appointment is now available. Here are the
                                        details:
                                    </p>

                                    <!-- Appointment details -->
                                    <table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="
                                            background-color: #f8fafc;
                                            border: 1px solid #e5e7eb;
                                            border-radius: 8px;
                                        ">
                                        <tr>
                                            <td style="
                                                padding: 20px;
                                                font-size: 15px;
                                                line-height: 24px;
                                                color: #374151;
                                            ">
                                                {body}
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="
                                        margin: 25px 0 0 0;
                                        font-size: 14px;
                                        line-height: 22px;
                                        color: #6b7280;
                                    ">
                                        Please check <a href="{TERMIN_URL}" style="color: #2563eb; text-decoration: underline;">the appointment details</a> and take
                                        action if it is suitable for you.
                                    </p>

                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="
                                    padding: 22px 30px;
                                    background-color: #f8fafc;
                                    border-top: 1px solid #e5e7eb;
                                ">
                                    <p style="
                                        margin: 0;
                                        text-align: center;
                                        font-size: 12px;
                                        line-height: 18px;
                                        color: #9ca3af;
                                    ">
                                        Appointment Alert &bull; Automated notification
                                    </p>
                                </td>
                            </tr>

                        </table>

                    </td>
                </tr>
            </table>

        </body>

    </html>
    """

def send_email(email, subject, body):
    email_subject = subject or "New Appointment Available"
    BODY_HTML = get_email_body(body)
    CHARSET = "UTF-8"

    access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region_name = os.getenv("AWS_REGION")

    if not access_key_id or not secret_access_key or not region_name:
        raise RuntimeError(
            "Missing AWS credentials in .env. Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION."
        )

    client = boto3.client(
        "ses",
        region_name=region_name,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )

    try:
        response = client.send_email(
            Destination={
                "ToAddresses": [email],
            },
            Message={
                "Body": {
                    "Html": {
                        "Charset": CHARSET,
                        "Data": BODY_HTML,
                    },
                    "Text": {
                        "Charset": CHARSET,
                        "Data": body,
                    },
                },
                "Subject": {
                    "Charset": CHARSET,
                    "Data": email_subject,
                },
            },
            Source=SENDER,
        )
    except NoCredentialsError as exc:
        logger.error("AWS SES credentials were not found in the .env file.")
        raise RuntimeError("AWS SES credentials were not found in the .env file.") from exc
    except ClientError as exc:
        logger.error("AWS SES request failed: %s", exc.response["Error"]["Message"])
        raise
    else:
        logger.info("Email sent! Message ID: %s", response["MessageId"])

def main():
    logger.info("Starting the application...")

    file_name = "emails.txt"
    if not os.path.exists(file_name):
        logger.error(f"{file_name} file not found. Please create the file with email addresses.")
        return

    driver = setup_driver()
    driver.get(TERMIN_URL)
    get_random_wait_time()
    logger.info(f"Page title: {driver.title}")

    wait = WebDriverWait(driver, 10)

    # step 1
    # get the button element by its name component
    auslaenderbehoerde_button = wait.until(
        EC.element_to_be_clickable((By.NAME, "Ausländerbehörde"))
    )
    get_random_wait_time()
    click_element(driver, auslaenderbehoerde_button)
    logger.info("Clicked the Ausländerbehörde button.")
    get_random_wait_time()

    # step 2
    # get button element by its data-type component
    plus_data_fields = wait.until(
        EC.presence_of_all_elements_located((By.XPATH, "//button[@data-type='plus']"))
    )
    target_button = None
    for plus_data in plus_data_fields:
        if "Verlängerung" in (plus_data.get_attribute("title") or ""):
            target_button = plus_data
            break

    if target_button is None:
        raise RuntimeError("No 'Verlängerung' button was found.")

    click_element(driver, target_button)
    logger.info("Clicked the plus button to increase the number of Anliegen.")
    get_random_wait_time()

    # get the next button element by its value attribute
    step_2_next_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//*[@value='Weiter']"))
    )
    get_random_wait_time()
    click_element(driver, step_2_next_button)
    logger.info("Clicked the next in step 2 button.")
    get_random_wait_time()

    # step 3
    step_2_next_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//*[@value='Weiter']"))
    )
    get_random_wait_time()
    click_element(driver, step_2_next_button)
    logger.info("Clicked the next in step 3 button.")
    get_random_wait_time()

    # step 4
    termin_found = False
    h2_elements = wait.until(
        EC.presence_of_all_elements_located((By.CLASS_NAME, "h1like"))
    )
    for h2 in h2_elements:
        if "Kein freier Termin" in h2.text:
            continue

        termin_found = True

    if termin_found:
        logger.info("A free appointment was found!")
        email_addresses = get_email_addresses()
        for email in email_addresses:
            send_email(email=email, body="A free appointment was found!", subject="Appointment Alert")
        logger.info(f"Email notifications sent to {len(email_addresses)} recipient(s).")
            

    logger.info("Application finished.")

if __name__ == "__main__":
    TERMIN_URL = os.getenv("TERMIN_URL")
    SENDER = os.getenv("SENDER_EMAIL")

    main()