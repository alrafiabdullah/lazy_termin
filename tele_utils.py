from utils_logger import ADMIN_ID, logger


RANDOM_QUIRKY_MESSAGE_LIST = [
    "I admire the confidence, but your admin powers are still buffering.",
    "That command is admin-only. Your application is being reviewed by a very tiny committee.",
    "You found the secret admin door. Sadly, your key is just enthusiasm.",
    "I checked your permissions twice. They remain spectacularly non-admin.",
    "Nice try. The command nodded politely and then asked for your admin badge.",
    "Your request has been declined by the Department of Absolutely Not Yet.",
    "You may have the ambition of an admin, but the bot has seen no supporting documents.",
    "That command is reserved for the admin. Please enjoy this complimentary rejection.",
    "I would let you use that command, but then the actual admin might get ideas.",
    "Permission denied. Please try again after completing the imaginary admin tutorial.",
]

async def send_message_to_admin(bot, message="Default message to admin"):
    logger.debug(f"Sending message to admin: {message}")
    await bot.send_message(chat_id=ADMIN_ID, text=message)