import os
import unittest
from unittest.mock import MagicMock, patch

from lazy_termin import mailer


class NotificationTests(unittest.TestCase):
	def test_get_email_addresses_strips_whitespace_and_ignores_empty_values(self):
		with patch.dict(os.environ, {"EMAIL_IDS": " one@example.com, ,two@example.com "}):
			self.assertEqual(
				mailer.get_email_addresses(), ["one@example.com", "two@example.com"]
			)

	def test_email_body_contains_appointment_details_and_url(self):
		with patch.object(mailer, "TERMIN_URL", "https://appointments.example"):
			body = mailer.get_email_body("Tuesday at 10:00")

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
		), patch.object(mailer.boto3, "client", return_value=client):
			result = mailer.send_ses_email(
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
			self.assertFalse(mailer.send_ses_email("recipient@example.com", None, "body"))


if __name__ == "__main__":
	unittest.main()
