import secrets
from email.utils import parseaddr

from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ses_em import send_ses_email
from sqlite_db import (
    check_active_subscriber_count,
    create_connection,
    get_active_subscribers,
    get_earliest_expired_subscriber,
    get_subscriber_status,
    subscriber_insert_query,
    subscriber_update_query,
)
from utils_logger import (
    ADMIN_ID,
    ALLOWED_DOMAINS,
    TELEGRAM_BOT_TOKEN,
    TERMIN_URL,
    logger,
)


async def send_to_users(bot: Bot):
    conn = create_connection()
    telegram_ids = get_active_subscribers(conn)
    logger.debug(f"telegram_ids: {telegram_ids}")
    message = (
        "A new appointment is available! 🎉\n\n"
        f"Please check {TERMIN_URL} for the appointment details "
        "and take action if it is suitable for you.\n\n"
        "You can unsubscribe from these notifications at any time by typing /unsubscribe."
    )

    for telegram_id in telegram_ids:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=message,
            )
            subscriber_update_query(conn, telegram_id)

        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send message to {telegram_id}: {e}")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Unsubscribe the user from notifications."""
    user = update.effective_user
    conn = create_connection()
    subscriber_update_query(conn, telegram_id=user.id, force=True)
    await update.message.reply_text(
        "You have been successfully unsubscribed from notifications."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the subscription conversation."""
    subscriber_count = check_active_subscriber_count(conn)
    if not subscriber_count:
        days_left = get_earliest_expired_subscriber(conn)
        await update.message.reply_text(
            "Sorry, the maximum number of active subscribers has been reached. "
            f"Please try again {'tomorrow' if days_left < 1 else f'in {days_left} day(s)'}."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Welcome to the notification subscription!\n\n"
        "Please note that your email address will be stored in our database for the purpose of sending you notifications."
        "Your telegram ID will also be stored to ensure that you receive notifications only for your own account.\n\n"
        "You can cancel the subscription process before it is completed at any time by typing /cancel.\n\n"
        "If you agree to this, enter your name (first and last):"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's name and ask for their email."""
    context.user_data["name"] = update.message.text
    await update.message.reply_text(
        "Please enter your university email address:"
    )
    return EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_email = update.message.text.strip()

    _, email = parseaddr(raw_email)
    email = email.lower()

    # Check if the user is already subscribed
    if get_subscriber_status(conn,email, user.id):
        await update.message.reply_text(
            "You are already subscribed to notifications."
        )
        return ConversationHandler.END

    if not email or "@" not in email:
        await update.message.reply_text(
            "Please enter a valid email address."
        )
        return EMAIL

    _, domain = email.rsplit("@", 1)

    allowed_domain_list = [d.strip().lower() for d in ALLOWED_DOMAINS.split(",")]
    if domain not in allowed_domain_list:
        await update.message.reply_text(
            "Sorry, you need to use your Uni email address."
        )
        return EMAIL

    otp = f"{secrets.randbelow(1_000_000):06d}"
    logger.debug(f"Generated OTP for {email}: {otp}")

    context.user_data["email"] = email
    context.user_data["otp"] = otp

    send_ses_email(email, f"Email Verification Code for {user.username}", f"Your verification code is: {otp}", True)

    await update.message.reply_text(
        "I've sent a 6-digit verification code to your email.\n\n"
        "Please enter the code here."
    )

    return OTP

async def verify_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered_otp = update.message.text.strip()
    expected_otp = context.user_data.get("otp")

    if entered_otp != expected_otp:
        await update.message.reply_text(
            "That code is incorrect. Please try again."
        )
        return OTP

    context.user_data["email_verified"] = True

    await update.message.reply_text(
        "Email verified successfully! 🎉\n\n"
        "Send /confirm to complete your subscription."
    )

    return CONFIRM

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm the subscription and store the user's data."""
    user = update.effective_user
    name = context.user_data["name"]
    email = context.user_data["email"]

    # Insert the new subscriber into the database
    inserted = subscriber_insert_query(conn, email, user.id)
    if inserted:
        logger.info(f"User {user.username} ({user.id}) has confirmed subscription.")
        await update.message.reply_text(
            f"Thank you {name}! You have been successfully subscribed for next 5 days to notifications."
        )
    else:
        await update.message.reply_text(
            "There was an error subscribing you. Please try again later."
        )

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the subscription conversation."""
    user = update.effective_user
    logger.info(f"User {user.username} ({user.id}) has canceled the subscription process.")
    await update.message.reply_text(
        "Subscription process has been canceled. You can start again by typing /subscribe."
    )
    return ConversationHandler.END
   

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
    application.add_handler(subscribe_conversation)
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("help", help_command))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    conn = create_connection()
    NAME, EMAIL, OTP, CONFIRM = range(4)
    subscribe_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", subscribe)
        ],

        states={
            NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_name
                )
            ],

            EMAIL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_email
                )
            ],

            OTP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, verify_otp)
            ],

            CONFIRM: [
                CommandHandler("confirm", confirm)
            ],
        },

        fallbacks=[
            CommandHandler("cancel", cancel)
        ],
    )

    main()