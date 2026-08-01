import logging
import os
import random
import time

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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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


    logger.info("Application finished.")

if __name__ == "__main__":
    TERMIN_URL = os.getenv("TERMIN_URL")
    main()