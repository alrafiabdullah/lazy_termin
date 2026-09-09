from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from sqlite_db import get_subscriber_status, subscriber_insert_query
from utils_logger import ADMIN_ID, TELEGRAM_BOT_TOKEN, logger


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /subscribe is issued."""
    user = update.effective_user
    logger.info(f"User {user.username} ({user.id}) has subscribed to notifications.")
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! You have subscribed to notifications.",
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    # make the help message dynamic based on the available commands
    help_message = (
        "Available commands:\n"
        "/subscribe - Subscribe to notifications\n"
        "/help - Show this help message\n"
    )
    await update.message.reply_text(help_message)


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    msg = update.message.text
    if update.effective_user.id == ADMIN_ID:
        logger.info(f"Received message from admin: {update.message.text}")
        msg = f"{msg}\n\n[Admin Message]"

    await update.message.reply_text(msg)


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("help", help_command))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()