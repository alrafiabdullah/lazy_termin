import random
import secrets
from contextlib import contextmanager
from email.utils import parseaddr

from telegram import Bot, BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db_utils import (
    check_active_subscriber_count,
    close_pool,
    get_active_subscribers,
    get_connection,
    get_earliest_expired_subscriber,
    get_subscriber_status,
    initialize_pool,
    release_connection,
    subscriber_insert_query,
    subscriber_update_query,
)
from ses_em import send_ses_email
from tele_utils import RANDOM_QUIRKY_MESSAGE_LIST, send_message_to_admin
from utils_logger import (
    ADMIN_ID,
    ALLOWED_DOMAINS,
    MAXIMUM_ENTRIES,
    TELEGRAM_BOT_TOKEN,
    TERMIN_URL,
    logger,
)


@contextmanager
def db_connection():
    """Borrow a PostgreSQL connection for one database operation."""
    connection = get_connection()
    try:
        yield connection
    except Exception:
        if not connection.closed:
            connection.rollback()
        raise
    finally:
        release_connection(connection)


async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /status is issued."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        random_message = random.choice(RANDOM_QUIRKY_MESSAGE_LIST)
        logger.warning(f"Unauthorized access attempt by user {user.username} ({user.id})")
        await update.message.reply_text(random_message)
        return

    with db_connection() as connection:
        _, subscriber_count = check_active_subscriber_count(connection)
        days_left = get_earliest_expired_subscriber(connection)

    status_message = (
        f"Active subscribers: {subscriber_count}\n"
        f"Earliest expired subscriber in: {days_left} day(s)\n"
        f"Maximum allowed entries: {MAXIMUM_ENTRIES}\n"
        f"Allowed domains: {ALLOWED_DOMAINS}\n"
        f"Termin URL: {TERMIN_URL}"
    )
    await update.message.reply_text(status_message)

async def user_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /status is issued."""
    user = update.effective_user
    
    with db_connection() as connection:
        is_subscribed = get_subscriber_status(connection, user.id)
    status_message = (
        f"- Hello {user.username}!\n"
        f"- Your Telegram ID: {user.id}\n"
        f"- You are currently {'subscribed' if is_subscribed else 'not subscribed'} to notifications.\n"
        f"- You can subscribe by typing /subscribe and unsubscribe by typing /unsubscribe.\n"
    )
    await update.message.reply_text(status_message)

async def send_to_users(bot: Bot):
    with db_connection() as connection:
        telegram_ids = get_active_subscribers(connection)
    logger.debug(f"telegram_ids: {telegram_ids}")
    message = (
        "A new appointment is available! 🎉\n\n"
        f"Please check {TERMIN_URL} for the appointment details "
        "and take action if it is suitable for you.\n\n"
        "You can unsubscribe from these notifications at any time by typing /unsubscribe."
    )

    successful_sends = 0
    for telegram_id in telegram_ids:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=message,
            )
            successful_sends += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send message to {telegram_id}: {e}")
    if len(telegram_ids) > 0:
        await send_message_to_admin(bot, message=f"Appointment available, message sent to {successful_sends}/{len(telegram_ids)} users.")


async def unsubscribe_user(bot: Bot):
    with db_connection() as connection:
        telegram_ids = get_active_subscribers(connection)
    logger.debug(f"telegram_ids: {telegram_ids}")
    message = (
        "Your subscription has been expired. You can re-subscribe by typing /subscribe."
    )

    update_counter = 0
    user_expired = False
    for telegram_id in telegram_ids:
        try:
            update_status = subscriber_update_query(connection, telegram_id)
            if update_status:
                user_expired = True
                update_counter += 1
                await bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send message to {telegram_id}: {e}")
    if user_expired:
        await send_message_to_admin(bot, message=f"Subscription expired, message sent to {update_counter} users.")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Unsubscribe the user from notifications."""
    user = update.effective_user
    with db_connection() as connection:
        subscription_status = get_subscriber_status(connection, telegram_id=user.id)
    if not subscription_status:
        await update.message.reply_text(
            "You are not currently subscribed to notifications."
        )
        return ConversationHandler.END
    with db_connection() as connection:
        subscriber_update_query(connection, telegram_id=user.id, force=True)
    await update.message.reply_text(
        "You have been successfully unsubscribed from notifications."
    )
    return ConversationHandler.END

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the subscription conversation."""
    with db_connection() as connection:
        subscriber_count, _ = check_active_subscriber_count(connection)
    if not subscriber_count:
        with db_connection() as connection:
            days_left = get_earliest_expired_subscriber(connection)
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
    with db_connection() as connection:
        is_subscribed = get_subscriber_status(connection, user.id)
    if is_subscribed:
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
    with db_connection() as connection:
        inserted = subscriber_insert_query(connection, email, user.id)
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
    help_message = "Available commands:\n"
    for command, (description, _) in USER_COMMANDS.items():
        help_message += f"/{command} - {description}\n"
    if update.effective_user.id == ADMIN_ID:
        help_message += "\nAdmin commands:\n"
        for command, (description, _) in ADMIN_COMMANDS.items():
            if command not in USER_COMMANDS:
                help_message += f"/{command} - {description}\n"
    await update.message.reply_text(help_message)


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    msg = update.message.text
    if update.effective_user.id == ADMIN_ID:
        logger.info(f"Received message from admin: {update.message.text}")
        msg = f"{msg}\n\n[Admin Message]"

    await update.message.reply_text(msg)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand(command, description)
        for command, (description, _) in ADMIN_COMMANDS.items()
    ]

    await application.bot.set_my_commands(commands)


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # on different commands - answer in Telegram
    application.add_handler(subscribe_conversation)
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("astatus", admin_status))
    application.add_handler(CommandHandler("status", user_status))
    application.add_handler(CommandHandler("help", help_command))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


USER_COMMANDS = {
    "subscribe": ("Subscribe to notifications", subscribe),
    "unsubscribe": ("Unsubscribe from notifications", unsubscribe),
    "status": ("Check your status", user_status),
    "help": ("Show available commands", help_command),
}

ADMIN_COMMANDS = {
    **USER_COMMANDS,
    "astatus": ("Show admin status", admin_status),
}

if __name__ == "__main__":
    initialize_pool()
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

    try:
        main()
    finally:
        close_pool()