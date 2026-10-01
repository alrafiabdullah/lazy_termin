import asyncio
import random
import secrets
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path

import psycopg2
from telegram import Bot, BotCommand, Update
from telegram.error import Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from .config import (
    ADMIN_ID,
    ALERT_COOLDOWN_MINUTES,
    ALLOWED_DOMAINS,
    MAXIMUM_ENTRIES,
    TELEGRAM_BOT_TOKEN,
    TERMIN_URL,
)
from .db import (
    check_active_subscriber_count,
    claim_outbox_events,
    close_pool,
    create_connection,
    delete_old_rows,
    get_active_subscribers,
    get_alert_recipients,
    get_connection,
    get_earliest_expired_subscriber,
    get_message_stats,
    get_subscriber_status,
    initialize_pool,
    mark_outbox_error,
    mark_outbox_sent,
    record_alert_delivery,
    record_message_event,
    release_connection,
    reset_stuck_outbox_events,
    subscriber_insert_query,
    subscriber_update_query,
)
from .log import logger
from .mailer import send_ses_email

HEARTBEAT_FILE = Path("/tmp/bot_heartbeat")
SEND_PAUSE_SECONDS = 0.05

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


async def track_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record incoming message metadata without storing message contents."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    message_text = getattr(message, "text", None) or getattr(message, "caption", None)
    message_type = "command" if message_text and message_text.startswith("/") else "message"
    with db_connection() as connection:
        record_message_event(
            connection,
            telegram_id=user.id,
            update_id=update.update_id,
            message_type=message_type,
        )


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
        message_count, user_count = get_message_stats(
            connection, datetime.now(timezone.utc) - timedelta(hours=24)
        )

    status_message = (
        f"Active subscribers: {subscriber_count}\n"
        f"Earliest expired subscriber in: {days_left} day(s)\n"
        f"Maximum allowed entries: {MAXIMUM_ENTRIES}\n"
        f"Allowed domains: {ALLOWED_DOMAINS}\n"
        f"Termin URL: {TERMIN_URL}\n"
        f"Messages received (24h): {message_count} from {user_count} user(s)"
    )
    await update.message.reply_text(status_message)

async def user_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /status is issued."""
    user = update.effective_user
    
    with db_connection() as connection:
        is_subscribed = get_subscriber_status(connection, user.id)

    user_name = f" {user.username}" if user.username else ""

    status_message = (
        f"- Hello{user_name}!\n"
        f"- Your Telegram ID: {user.id}\n"
        f"- You are currently {'subscribed' if is_subscribed else 'not subscribed'} to notifications.\n"
        f"- You can {'subscribe' if not is_subscribed else 'unsubscribe'} by typing /{'subscribe' if not is_subscribed else 'unsubscribe'}.\n"
    )
    await update.message.reply_text(status_message)

async def send_with_retry(bot: Bot, telegram_id, text):
    """Send one message, waiting and retrying once if Telegram rate-limits the bot."""
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except RetryAfter as e:
        retry_after = e.retry_after
        if isinstance(retry_after, timedelta):
            retry_after = retry_after.total_seconds()
        logger.warning(f"Rate limited; retrying {telegram_id} in {retry_after} seconds.")
        await asyncio.sleep(retry_after)
        await bot.send_message(chat_id=telegram_id, text=text)


async def send_to_users(bot: Bot, outbox_id):
    """Alert every subscriber who has not been alerted within the cooldown."""
    with db_connection() as connection:
        active_count = len(get_active_subscribers(connection))
        telegram_ids = get_alert_recipients(connection, ALERT_COOLDOWN_MINUTES)
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
            await send_with_retry(bot, telegram_id, message)
        except Forbidden:
            logger.info(f"User {telegram_id} blocked the bot; skipping.")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send message to {telegram_id}: {e}")
        else:
            # Recorded per send, so a retry of this event skips users already alerted.
            with db_connection() as connection:
                record_alert_delivery(connection, outbox_id, telegram_id)
            successful_sends += 1
        await asyncio.sleep(SEND_PAUSE_SECONDS)
    if successful_sends > 0:
        # A failed admin summary must not make the dispatcher resend to every user.
        try:
            await send_message_to_admin(
                bot,
                message=(
                    f"Appointment available, message sent to {successful_sends}/{len(telegram_ids)} eligible user(s); "
                    f"{active_count - len(telegram_ids)} skipped (alerted within cooldown)."
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send the admin summary: {e}")


async def unsubscribe_user(bot: Bot):
    with db_connection() as connection:
        telegram_ids = get_active_subscribers(connection)
        expired_ids = [
            telegram_id
            for telegram_id in telegram_ids
            if subscriber_update_query(connection, telegram_id)
        ]
    logger.debug(f"expired telegram_ids: {expired_ids}")
    message = (
        "Your subscription has been expired. You can re-subscribe by typing /subscribe."
    )

    for telegram_id in expired_ids:
        try:
            await send_with_retry(bot, telegram_id, message)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send message to {telegram_id}: {e}")
        await asyncio.sleep(SEND_PAUSE_SECONDS)
    if expired_ids:
        await send_message_to_admin(bot, message=f"Subscription expired, message sent to {len(expired_ids)} user(s).")


async def dispatch_outbox(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deliver pending outbox events queued by the scraper."""
    with db_connection() as connection:
        events = claim_outbox_events(connection)

    for event_id, event_type, _, attempts in events:
        try:
            if event_type != "APPOINTMENT_FOUND":
                raise ValueError(f"Unknown event type: {event_type}")
            await send_to_users(context.bot, event_id)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Outbox event {event_id} failed on attempt {attempts}.")
            with db_connection() as connection:
                status = mark_outbox_error(connection, event_id, e)
            if status == "failed":
                await send_message_to_admin(
                    context.bot,
                    message=f"Outbox event {event_id} ({event_type}) failed after {attempts} attempts: {e}",
                )
            continue

        with db_connection() as connection:
            mark_outbox_sent(connection, event_id)
        logger.info(f"Outbox event {event_id} sent.")


async def expire_subscriptions(context: ContextTypes.DEFAULT_TYPE) -> None:
    await unsubscribe_user(context.bot)


async def delete_old_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    with db_connection() as connection:
        delete_old_rows(connection)


async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Touch the heartbeat file for the container health check."""
    HEARTBEAT_FILE.touch()
    if context.application.bot_data["outbox_listener"].closed:
        try:
            start_outbox_listener(context.application)
        except psycopg2.Error as e:
            logger.error(f"Could not restart the outbox listener: {e}")


def start_outbox_listener(application: Application) -> None:
    """Wake the dispatcher as soon as the scraper sends NOTIFY; polling stays the fallback."""
    connection = create_connection()
    connection.autocommit = True
    connection.cursor().execute("LISTEN notification_outbox")
    application.bot_data["outbox_listener"] = connection
    loop = asyncio.get_running_loop()
    fd = connection.fileno()

    def on_notify():
        try:
            connection.poll()
        except psycopg2.Error as e:
            logger.error(f"Outbox listener disconnected: {e}")
            loop.remove_reader(fd)
            connection.close()
            return
        if connection.notifies:
            connection.notifies.clear()
            application.job_queue.run_once(dispatch_outbox, 0)

    loop.add_reader(fd, on_notify)


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
        "To provide this service, we store your university email address and Telegram ID, so we can send OTP/appointment notifications to your account.\n\n"
        "For service statistics, we also store the timestamp, Telegram ID, update ID, and type of incoming messages. We do not store message contents.\n\n"
        "Your data is processed only for these purposes and should be handled according to applicable EU data-protection rules, including the GDPR. You can unsubscribe at any time by typing /unsubscribe.\n\n"
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

    with db_connection() as connection:
        reset_count = reset_stuck_outbox_events(connection)
    if reset_count:
        logger.warning(f"Reset {reset_count} outbox event(s) stuck in processing.")

    start_outbox_listener(application)
    job_queue = application.job_queue
    job_queue.run_repeating(heartbeat, interval=60, first=0)
    job_queue.run_repeating(dispatch_outbox, interval=20, first=0)
    job_queue.run_repeating(expire_subscriptions, interval=15 * 60, first=0)
    job_queue.run_daily(delete_old_data, time=time(3, 0, tzinfo=timezone.utc))


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(TypeHandler(Update, track_update), group=-1)
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
    HEARTBEAT_FILE.unlink(missing_ok=True)  # A restarted container must not look healthy early.
    initialize_pool(min_connections=1, max_connections=3)
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