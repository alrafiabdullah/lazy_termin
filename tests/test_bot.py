import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from lazy_termin import bot


class TelegramHandlerTests(unittest.IsolatedAsyncioTestCase):
	async def test_track_update_records_message_metadata(self):
		update = MagicMock()
		update.update_id = 77
		update.effective_user.id = 12345
		update.effective_message.text = "hello"
		connection = MagicMock()

		with patch.object(bot, "get_connection", return_value=connection), \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "record_message_event") as record_event:
			await bot.track_update(update, MagicMock())

		record_event.assert_called_once_with(
			connection,
			telegram_id=12345,
			update_id=77,
			message_type="message",
		)

	def test_db_connection_returns_connection_to_pool(self):
		borrowed_connection = MagicMock()
		borrowed_connection.closed = 0

		with patch.object(
			bot, "get_connection", return_value=borrowed_connection
		) as get_connection, patch.object(
			bot, "release_connection"
		) as release_connection, bot.db_connection() as connection:
			self.assertIs(connection, borrowed_connection)

		get_connection.assert_called_once_with()
		release_connection.assert_called_once_with(borrowed_connection)

	async def test_unsubscribe_deactivates_subscribed_user(self):
		update = MagicMock()
		update.effective_user.id = 12345
		update.message.reply_text = AsyncMock()

		with patch.object(bot, "get_connection", return_value=MagicMock()), \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "get_subscriber_status", return_value=True), \
			patch.object(bot, "subscriber_update_query") as update_subscriber:
			result = await bot.unsubscribe(update, MagicMock())

		self.assertEqual(result, bot.ConversationHandler.END)
		update_subscriber.assert_called_once_with(
			ANY, telegram_id=12345, force=True
		)
		update.message.reply_text.assert_awaited_once_with(
			"You have been successfully unsubscribed from notifications."
		)

	async def test_unsubscribe_rejects_user_without_subscription(self):
		update = MagicMock()
		update.effective_user.id = 12345
		update.message.reply_text = AsyncMock()

		with patch.object(bot, "get_connection", return_value=MagicMock()), \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "get_subscriber_status", return_value=False), \
			patch.object(bot, "subscriber_update_query") as update_subscriber:
			result = await bot.unsubscribe(update, MagicMock())

		self.assertEqual(result, bot.ConversationHandler.END)
		update_subscriber.assert_not_called()
		update.message.reply_text.assert_awaited_once_with(
			"You are not currently subscribed to notifications."
		)

	async def test_subscription_conversation_happy_path(self):
		update = MagicMock()
		update.effective_user.id = 12345
		update.effective_user.username = "student"
		update.message.reply_text = AsyncMock()
		context = MagicMock()
		context.user_data = {}

		with patch.object(bot, "get_connection", return_value=MagicMock()), \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "NAME", 0, create=True), \
			patch.object(bot, "EMAIL", 1, create=True), \
			patch.object(bot, "OTP", 2, create=True), \
			patch.object(bot, "CONFIRM", 3, create=True), \
			patch.object(bot, "check_active_subscriber_count", return_value=(True, 0)), \
			patch.object(bot, "get_subscriber_status", return_value=False), \
			patch.object(bot, "send_ses_email") as send_email, \
			patch.object(bot.secrets, "randbelow", return_value=123456), \
			patch.object(bot, "subscriber_insert_query", return_value=True):
			self.assertEqual(await bot.subscribe(update, context), 0)

			update.message.text = "Ada Lovelace"
			self.assertEqual(await bot.get_name(update, context), 1)

			update.message.text = "student@uni-trier.de"
			self.assertEqual(await bot.get_email(update, context), 2)
			send_email.assert_called_once()

			update.message.text = "123456"
			self.assertEqual(await bot.verify_otp(update, context), 3)

			self.assertEqual(await bot.confirm(update, context), -1)
			self.assertEqual(context.user_data["name"], "Ada Lovelace")
			self.assertEqual(context.user_data["email"], "student@uni-trier.de")

	async def test_dispatch_outbox_marks_sent_event(self):
		context = MagicMock()
		with patch.object(bot, "get_connection", return_value=MagicMock()), \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "claim_outbox_events", return_value=[(7, "APPOINTMENT_FOUND", {}, 1)]), \
			patch.object(bot, "send_to_users", new_callable=AsyncMock) as send_to_users, \
			patch.object(bot, "mark_outbox_sent") as mark_sent:
			await bot.dispatch_outbox(context)

		send_to_users.assert_awaited_once_with(context.bot)
		mark_sent.assert_called_once_with(ANY, 7)

	async def test_dispatch_outbox_alerts_admin_when_event_fails(self):
		with patch.object(bot, "get_connection", return_value=MagicMock()), \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "claim_outbox_events", return_value=[(7, "APPOINTMENT_FOUND", {}, 3)]), \
			patch.object(bot, "send_to_users", new_callable=AsyncMock, side_effect=RuntimeError("down")), \
			patch.object(bot, "mark_outbox_error", return_value="failed") as mark_error, \
			patch.object(bot, "mark_outbox_sent") as mark_sent, \
			patch.object(bot, "send_message_to_admin", new_callable=AsyncMock) as admin:
			await bot.dispatch_outbox(MagicMock())

		mark_error.assert_called_once_with(ANY, 7, ANY)
		mark_sent.assert_not_called()
		admin.assert_awaited_once()

	async def test_unsubscribe_user_uses_one_connection(self):
		connection = MagicMock()
		fake_bot = MagicMock()
		fake_bot.send_message = AsyncMock()

		with patch.object(bot, "get_connection", return_value=connection) as get_connection, \
			patch.object(bot, "release_connection"), \
			patch.object(bot, "get_active_subscribers", return_value=[1, 2]), \
			patch.object(bot, "subscriber_update_query", side_effect=[True, False]) as update_subscriber, \
			patch.object(bot, "send_message_to_admin", new_callable=AsyncMock):
			await bot.unsubscribe_user(fake_bot)

		get_connection.assert_called_once_with()
		for call in update_subscriber.call_args_list:
			self.assertIs(call.args[0], connection)
		fake_bot.send_message.assert_awaited_once_with(chat_id=1, text=ANY)

	async def test_send_with_retry_waits_after_rate_limit(self):
		from telegram.error import RetryAfter

		fake_bot = MagicMock()
		fake_bot.send_message = AsyncMock(side_effect=[RetryAfter(2), None])

		with patch.object(bot.asyncio, "sleep", new_callable=AsyncMock) as sleep:
			await bot.send_with_retry(fake_bot, 1, "hi")

		sleep.assert_awaited_once()
		self.assertEqual(sleep.call_args.args[0], 2)
		self.assertEqual(fake_bot.send_message.await_count, 2)

	async def test_help_command_replies_with_available_commands(self):
		update = MagicMock()
		update.message.reply_text = AsyncMock()

		await bot.help_command(update, MagicMock())

		update.message.reply_text.assert_awaited_once()
		self.assertIn("/subscribe", update.message.reply_text.call_args.args[0])

	async def test_echo_marks_admin_messages(self):
		update = MagicMock()
		update.message.text = "maintenance"
		update.message.reply_text = AsyncMock()
		update.effective_user.id = bot.ADMIN_ID

		await bot.echo(update, MagicMock())

		update.message.reply_text.assert_awaited_once_with(
			"maintenance\n\n[Admin Message]"
		)


if __name__ == "__main__":
	unittest.main()
