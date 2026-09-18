from utils_logger import ADMIN_ID, logger


async def send_message_to_admin(bot, message="Default message to admin"):
    logger.debug(f"Sending message to admin: {message}")
    await bot.send_message(chat_id=ADMIN_ID, text=message)