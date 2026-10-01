import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from telegram.error import Forbidden

from lazy_termin import bot, db
from tests import use_local_test_database


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

		send_to_users.assert_awaited_once_with(context.bot, 7)
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


class AlertDeliveryTests(unittest.IsolatedAsyncioTestCase):
	"""Outbox dispatch against the local test database, with Telegram mocked."""

	@classmethod
	def setUpClass(cls):
		use_local_test_database()

	def setUp(self):
		self.connection = db.create_connection()
		self._clear()
		self.fake_bot = MagicMock()
		self.fake_bot.send_message = AsyncMock()
		self.context = MagicMock(bot=self.fake_bot)
		for patcher in (
			patch.object(bot, "get_connection", return_value=self.connection),
			patch.object(bot, "release_connection"),
			patch.object(bot, "ALERT_COOLDOWN_MINUTES", 60),
			patch.object(bot, "SEND_PAUSE_SECONDS", 0),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		self._clear()
		self.connection.close()

	def _clear(self):
		with self.connection, self.connection.cursor() as cur:
			cur.execute("DELETE FROM notification_outbox")
		db.delete_subscriber(self.connection)

	def _subscribe(self, *telegram_ids):
		for telegram_id in telegram_ids:
			db.subscriber_insert_query(self.connection, f"user{telegram_id}@uni-trier.de", telegram_id)

	def _alerted(self):
		calls = self.fake_bot.send_message.await_args_list
		return sorted(call.kwargs["chat_id"] for call in calls if call.kwargs["chat_id"] != bot.ADMIN_ID)

	def _admin_messages(self):
		calls = self.fake_bot.send_message.await_args_list
		return [call.kwargs["text"] for call in calls if call.kwargs["chat_id"] == bot.ADMIN_ID]

	def _query(self, sql):
		with self.connection, self.connection.cursor() as cur:
			cur.execute(sql)
			return cur.fetchall()

	async def _scrape_and_dispatch(self):
		"""Queue an alert as the scraper does, dispatch it, and return who was alerted."""
		self.fake_bot.send_message.reset_mock()
		self.assertTrue(db.insert_outbox_event(self.connection, "APPOINTMENT_FOUND", {}))
		await bot.dispatch_outbox(self.context)
		self.assertEqual(self._query("SELECT DISTINCT status FROM notification_outbox"), [("sent",)])
		return self._alerted()

	def _advance_minutes(self, minutes):
		self._query(
			f"UPDATE alert_delivery SET sent_at = sent_at - interval '{minutes} minutes' RETURNING 1"
		)

	async def test_behaviour_table_with_new_subscriber(self):
		a, x = 1001, 1002
		self._subscribe(a)
		alerted = {"10:00": await self._scrape_and_dispatch()}
		self._subscribe(x)  # X subscribes at 10:05.
		for scrape in ("10:15", "10:30", "10:45", "11:00", "11:15"):
			self._advance_minutes(15)
			alerted[scrape] = await self._scrape_and_dispatch()

		self.assertEqual(
			alerted,
			{"10:00": [a], "10:15": [x], "10:30": [], "10:45": [], "11:00": [a], "11:15": [x]},
		)

	async def test_retry_after_crash_only_reaches_users_not_yet_alerted(self):
		self._subscribe(1001, 1002, 1003)
		db.insert_outbox_event(self.connection, "APPOINTMENT_FOUND", {})
		(event_id, *_), = db.claim_outbox_events(self.connection)
		# The bot crashed after alerting two of the three users.
		db.record_alert_delivery(self.connection, event_id, 1001)
		db.record_alert_delivery(self.connection, event_id, 1002)
		self._query("UPDATE notification_outbox SET claimed_at = now() - interval '11 minutes' RETURNING 1")
		self.assertEqual(db.reset_stuck_outbox_events(self.connection), 1)

		await bot.dispatch_outbox(self.context)

		self.assertEqual(self._alerted(), [1003])
		self.assertEqual(self._query("SELECT status FROM notification_outbox"), [("sent",)])

	async def test_blocked_user_gets_no_delivery_row_and_event_is_sent(self):
		self._subscribe(1001, 1002)

		async def send_message(chat_id, text):
			if chat_id == 1001:
				raise Forbidden("Forbidden: bot was blocked by the user")

		self.fake_bot.send_message.side_effect = send_message
		await self._scrape_and_dispatch()

		self.assertEqual(self._query("SELECT telegram_id FROM alert_delivery"), [(1002,)])
		self.assertEqual(db.get_alert_recipients(self.connection, 60), [1001])
		self.assertEqual(
			self._admin_messages(),
			["Appointment available, message sent to 1/2 eligible user(s); 0 skipped (alerted within cooldown)."],
		)

	async def test_no_admin_summary_when_nobody_is_eligible(self):
		self._subscribe(1001)
		await self._scrape_and_dispatch()

		self.assertEqual(await self._scrape_and_dispatch(), [])
		self.fake_bot.send_message.assert_not_awaited()



if __name__ == "__main__":
	unittest.main()
