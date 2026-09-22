import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("MAXIMUM_ENTRIES", "10")
os.environ.setdefault("ADMIN_ID", "1")

import db_utils
import main
import ses_em
import tele_bot


class SubscriberDatabaseTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		# Tests must never use the application's remote PostgreSQL settings.
		db_utils.DB_HOST = os.getenv("TEST_DB_HOST", "127.0.0.1")
		db_utils.DB_PORT = os.getenv("TEST_DB_PORT", "5432")
		db_utils.DB_NAME = os.getenv("TEST_DB_NAME", db_utils.DB_NAME)
		db_utils.DB_USER = os.getenv("TEST_DB_USER", db_utils.DB_USER)
		db_utils.DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", db_utils.DB_PASSWORD)
		if db_utils.DB_HOST not in {"localhost", "127.0.0.1", "::1"}:
			raise unittest.SkipTest("Database tests require a local PostgreSQL host")

	def setUp(self):
		self.connection = db_utils.create_connection()
		db_utils.delete_subscriber(self.connection)

	def tearDown(self):
		db_utils.delete_subscriber(self.connection)
		self.connection.close()

	def test_insert_and_get_active_subscriber(self):
		inserted = db_utils.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertTrue(inserted)
		self.assertTrue(
			db_utils.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_duplicate_active_subscriber_is_not_inserted(self):
		db_utils.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		inserted_again = db_utils.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertFalse(inserted_again)
		self.assertEqual(
			db_utils.get_active_subscribers(self.connection), [12345]
		)

	def test_active_subscriber_count_rejects_when_limit_is_reached(self):
		db_utils.subscriber_insert_query(self.connection, "first@uni-trier.de", 1)

		with patch.object(db_utils, "MAXIMUM_ENTRIES", 1):
			status, _ = db_utils.check_active_subscriber_count(self.connection)
			self.assertFalse(status)

	def test_active_subscriber_count_ignores_other_domains(self):
		db_utils.subscriber_insert_query(self.connection, "student@uni-trier.de", 1)
		db_utils.subscriber_insert_query(self.connection, "person@example.com", 2)

		with patch.object(db_utils, "MAXIMUM_ENTRIES", 2):
			status, _ = db_utils.check_active_subscriber_count(self.connection)
			self.assertTrue(status)

	def test_expired_subscriber_is_deactivated(self):
		db_utils.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)
		future = datetime.now(timezone.utc) + timedelta(days=6)

		with patch.object(db_utils, "datetime") as datetime_mock:
			datetime_mock.now.return_value = future
			updated = db_utils.subscriber_update_query(self.connection, 12345)

		self.assertTrue(updated)
		self.assertFalse(
			db_utils.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_force_update_deactivates_active_subscriber(self):
		db_utils.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		self.assertTrue(
			db_utils.subscriber_update_query(self.connection, 12345, force=True)
		)
		self.assertFalse(
			db_utils.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_update_returns_false_for_non_expired_subscriber(self):
		db_utils.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		self.assertFalse(db_utils.subscriber_update_query(self.connection, 12345))

	def test_delete_all_subscribers(self):
		db_utils.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		self.assertTrue(db_utils.delete_subscriber(self.connection))
		self.assertFalse(
			db_utils.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_get_active_subscribers_returns_only_active_ids(self):
		db_utils.subscriber_insert_query(self.connection, "first@uni-trier.de", 1)
		db_utils.subscriber_insert_query(self.connection, "second@uni-trier.de", 2)
		db_utils.subscriber_update_query(self.connection, 2, force=True)

		self.assertEqual(db_utils.get_active_subscribers(self.connection), [1])

	def test_earliest_expired_subscriber_returns_default_without_active_rows(self):
		self.assertEqual(
			db_utils.get_earliest_expired_subscriber(self.connection), 5
		)

	def test_earliest_expired_subscriber_returns_days_until_earliest_end(self):
		db_utils.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		days_left = db_utils.get_earliest_expired_subscriber(self.connection)

		self.assertGreaterEqual(days_left, 4)
		self.assertLessEqual(days_left, 5)


class NotificationTests(unittest.TestCase):
	def test_get_email_addresses_strips_whitespace_and_ignores_empty_values(self):
		with patch.dict(os.environ, {"EMAIL_IDS": " one@example.com, ,two@example.com "}):
			self.assertEqual(
				ses_em.get_email_addresses(), ["one@example.com", "two@example.com"]
			)

	def test_email_body_contains_appointment_details_and_url(self):
		with patch.object(ses_em, "TERMIN_URL", "https://appointments.example"):
			body = ses_em.get_email_body("Tuesday at 10:00")

		self.assertIn("Tuesday at 10:00", body)
		self.assertIn("https://appointments.example", body)

	def test_send_ses_email_sends_expected_message(self):
		client = MagicMock()
		with patch.dict(
			os.environ,
			{
				"AWS_ACCESS_KEY_ID": "access",
				"AWS_SECRET_ACCESS_KEY": "secret",
				"AWS_REGION": "eu-central-1",
				"AWS_SES_CONFIGURATION_SET": "config",
			},
		), patch.object(ses_em.boto3, "client", return_value=client):
			result = ses_em.send_ses_email(
				"recipient@example.com", "Subject", "Appointment details"
			)

		self.assertTrue(result)
		client.send_email.assert_called_once()
		request = client.send_email.call_args.kwargs
		self.assertEqual(request["Destination"]["ToAddresses"], ["recipient@example.com"])
		self.assertEqual(request["Message"]["Subject"]["Data"], "Subject")
		client.close.assert_called_once()

	def test_send_ses_email_returns_false_without_credentials(self):
		with patch.dict(
			os.environ,
			{
				"AWS_ACCESS_KEY_ID": "",
				"AWS_SECRET_ACCESS_KEY": "",
				"AWS_REGION": "",
			},
			clear=False,
		):
			self.assertFalse(ses_em.send_ses_email("recipient@example.com", None, "body"))


class TelegramHandlerTests(unittest.IsolatedAsyncioTestCase):
	async def test_track_update_records_message_metadata(self):
		update = MagicMock()
		update.update_id = 77
		update.effective_user.id = 12345
		update.effective_message.text = "hello"
		connection = MagicMock()

		with patch.object(tele_bot, "get_connection", return_value=connection), \
			patch.object(tele_bot, "release_connection"), \
			patch.object(tele_bot, "record_message_event") as record_event:
			await tele_bot.track_update(update, MagicMock())

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
			tele_bot, "get_connection", return_value=borrowed_connection
		) as get_connection, patch.object(
			tele_bot, "release_connection"
		) as release_connection, tele_bot.db_connection() as connection:
			self.assertIs(connection, borrowed_connection)

		get_connection.assert_called_once_with()
		release_connection.assert_called_once_with(borrowed_connection)

	async def test_unsubscribe_deactivates_subscribed_user(self):
		update = MagicMock()
		update.effective_user.id = 12345
		update.message.reply_text = AsyncMock()

		with patch.object(tele_bot, "get_connection", return_value=MagicMock()), \
			patch.object(tele_bot, "release_connection"), \
			patch.object(tele_bot, "get_subscriber_status", return_value=True), \
			patch.object(tele_bot, "subscriber_update_query") as update_subscriber:
			result = await tele_bot.unsubscribe(update, MagicMock())

		self.assertEqual(result, tele_bot.ConversationHandler.END)
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

		with patch.object(tele_bot, "get_connection", return_value=MagicMock()), \
			patch.object(tele_bot, "release_connection"), \
			patch.object(tele_bot, "get_subscriber_status", return_value=False), \
			patch.object(tele_bot, "subscriber_update_query") as update_subscriber:
			result = await tele_bot.unsubscribe(update, MagicMock())

		self.assertEqual(result, tele_bot.ConversationHandler.END)
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

		with patch.object(tele_bot, "get_connection", return_value=MagicMock()), \
			patch.object(tele_bot, "release_connection"), \
			patch.object(tele_bot, "NAME", 0, create=True), \
			patch.object(tele_bot, "EMAIL", 1, create=True), \
			patch.object(tele_bot, "OTP", 2, create=True), \
			patch.object(tele_bot, "CONFIRM", 3, create=True), \
			patch.object(tele_bot, "check_active_subscriber_count", return_value=(True, 0)), \
			patch.object(tele_bot, "get_subscriber_status", return_value=False), \
			patch.object(tele_bot, "send_ses_email") as send_email, \
			patch.object(tele_bot.secrets, "randbelow", return_value=123456), \
			patch.object(tele_bot, "subscriber_insert_query", return_value=True):
			self.assertEqual(await tele_bot.subscribe(update, context), 0)

			update.message.text = "Ada Lovelace"
			self.assertEqual(await tele_bot.get_name(update, context), 1)

			update.message.text = "student@uni-trier.de"
			self.assertEqual(await tele_bot.get_email(update, context), 2)
			send_email.assert_called_once()

			update.message.text = "123456"
			self.assertEqual(await tele_bot.verify_otp(update, context), 3)

			self.assertEqual(await tele_bot.confirm(update, context), -1)
			self.assertEqual(context.user_data["name"], "Ada Lovelace")
			self.assertEqual(context.user_data["email"], "student@uni-trier.de")

	async def test_help_command_replies_with_available_commands(self):
		update = MagicMock()
		update.message.reply_text = AsyncMock()

		await tele_bot.help_command(update, MagicMock())

		update.message.reply_text.assert_awaited_once()
		self.assertIn("/subscribe", update.message.reply_text.call_args.args[0])

	async def test_echo_marks_admin_messages(self):
		update = MagicMock()
		update.message.text = "maintenance"
		update.message.reply_text = AsyncMock()
		update.effective_user.id = tele_bot.ADMIN_ID

		await tele_bot.echo(update, MagicMock())

		update.message.reply_text.assert_awaited_once_with(
			"maintenance\n\n[Admin Message]"
		)


class BrowserHelperTests(unittest.TestCase):
	def test_click_element_falls_back_to_javascript_after_intercepted_click(self):
		driver = MagicMock()
		element = MagicMock()
		from selenium.common.exceptions import ElementClickInterceptedException

		element.click.side_effect = ElementClickInterceptedException()

		main.click_element(driver, element)

		driver.execute_script.assert_called_once()
		self.assertIs(driver.execute_script.call_args.args[1], element)


if __name__ == "__main__":
	unittest.main()
