import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


def main():
    logger.info("Starting the application...")
    # Your main application logic here
    logger.info("Application finished.")

if __name__ == "__main__":
    main()