import argparse
import random
import sys
import time
from contextlib import closing

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import TERMIN_URL
from .db import create_connection, insert_outbox_event
from .log import logger
from .mailer import get_email_addresses, send_ses_email


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
    options.add_argument("--headless=new")  # Run in headless mode
    options.add_argument("--disable-gpu")  # Disable GPU acceleration
    options.add_argument("--no-sandbox")  # Bypass OS security model
    options.add_argument("--disable-dev-shm-usage")  # Use /tmp instead of the small /dev/shm
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--blink-settings=imagesEnabled=false")  # Skip images to save memory
    driver = webdriver.Chrome(options=options)
    return driver


def queue_appointment_alert(heading):
    """Queue an alert in the outbox; the bot decides which subscribers receive it."""
    with closing(create_connection()) as connection:
        inserted = insert_outbox_event(connection, "APPOINTMENT_FOUND", {"heading": heading})
    if inserted:
        logger.info("Appointment alert queued in the outbox.")
    else:
        logger.info("Alert skipped: one is already pending.")


def run_booking_flow(driver, use_email):
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
        logger.error("No 'Verlängerung' button was found.")
        return

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
    free_heading = None
    h2_elements = wait.until(
        EC.presence_of_all_elements_located((By.CLASS_NAME, "h1like"))
    )
    for h2 in h2_elements:
        if "Kein freier Termin" in h2.text:
            continue

        free_heading = h2.text

    if free_heading is not None:
        logger.info("A free appointment was found!")

        if not use_email:
            queue_appointment_alert(free_heading)
        else:
            email_addresses = get_email_addresses()
            for email in email_addresses:
                ses_email_status = send_ses_email(email=email, body="A free appointment was found!", subject="Appointment Alert")
                if not ses_email_status:
                    logger.error(f"Failed to send email to {email}.")

            logger.info(f"Email notifications sent to {len(email_addresses)} recipient(s).")
    else:
        logger.info("No free appointments found.")


def main(use_email=False):
    logger.info("Starting the application...")

    driver = setup_driver()
    try:
        run_booking_flow(driver, use_email)
    finally:
        driver.quit()

    logger.info("Application finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the lazy termin script.")
    parser.add_argument("--use_email", "-ue", action="store_true", help="Use email for sending messages.")

    args = parser.parse_args()

    try:
        main(use_email=args.use_email)
    except Exception:
        logger.exception("The run failed.")
        sys.exit(1)
