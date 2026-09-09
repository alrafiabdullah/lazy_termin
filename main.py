import argparse
import random
import time

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ses_em import get_email_addresses, send_ses_email
from utils_logger import TERMIN_URL, logger


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
    # options.add_argument("--headless")  # Run in headless mode
    options.add_argument("--disable-gpu")  # Disable GPU acceleration
    options.add_argument("--no-sandbox")  # Bypass OS security model
    driver = webdriver.Chrome(options=options)
    return driver


def main():
    logger.info("Starting the application...")

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

        if USE_TELEGRAM:
            print("A free appointment was found! Sending Telegram notification...")
        else:
            email_addresses = get_email_addresses()
            for email in email_addresses:
                ses_email_status = send_ses_email(email=email, body="A free appointment was found!", subject="Appointment Alert")
                if not ses_email_status:
                    logger.error(f"Failed to send email to {email}.")

            logger.info(f"Email notifications sent to {len(email_addresses)} recipient(s).")
    else:
        logger.info("No free appointments found.")

    logger.info("Application finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the lazy termin script.")
    parser.add_argument("--use_email", "-ue", action="store_true", help="Use email for sending messages.")

    args = parser.parse_args()

    USE_TELEGRAM = bool(not args.use_email)

    main()
