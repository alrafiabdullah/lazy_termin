import os
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("MAXIMUM_ENTRIES", "10")
os.environ.setdefault("ADMIN_ID", "1")

import main
import ses_em
import sqlite_db
import tele_bot


class SubscriberDatabaseTests(unittest.TestCase):
	def setUp(self):
		self.connection = sqlite3.connect(":memory:")
		sqlite_db.subscriber_schema(self.connection)

	def tearDown(self):
		self.connection.close()

	def test_insert_and_get_active_subscriber(self):
		inserted = sqlite_db.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertTrue(inserted)
		self.assertTrue(
			sqlite_db.get_subscriber_status(
				self.connection, "student@uni-trier.de", 12345
			)
		)

	def test_duplicate_active_subscriber_is_not_inserted(self):
		sqlite_db.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		inserted_again = sqlite_db.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertFalse(inserted_again)
		self.assertEqual(
			self.connection.execute("SELECT COUNT(*) FROM subscriber").fetchone()[0],
			1,
		)

	def test_insert_rejects_non_university_address_when_limit_is_reached(self):
		with patch.object(sqlite_db, "MAXIMUM_ENTRIES", 1):
			sqlite_db.subscriber_insert_query(
				self.connection, "first@uni-trier.de", 1
			)
			inserted = sqlite_db.subscriber_insert_query(
				self.connection, "second@example.com", 2
			)

		self.assertFalse(inserted)

	def test_expired_subscriber_is_deactivated(self):
		expired = datetime.now(timezone.utc) - timedelta(days=1)
		self.connection.execute(
			"""
			INSERT INTO subscriber
				(unique_id, uni_email, start_date, end_date, telegram_id, is_active)
			VALUES (?, ?, ?, ?, ?, ?)
			""",
			(
				"expired-id",
				"student@uni-trier.de",
				(expired - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
				expired.strftime("%Y-%m-%d %H:%M:%S"),
				12345,
				1,
			),
		)
		self.connection.commit()

		updated = sqlite_db.subscriber_update_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertTrue(updated)
		self.assertFalse(
			sqlite_db.get_subscriber_status(
				self.connection, "student@uni-trier.de", 12345
			)
		)


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
