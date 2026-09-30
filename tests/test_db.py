import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from lazy_termin import db


class SubscriberDatabaseTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		# Tests must never use the application's remote PostgreSQL settings.
		db.DB_HOST = os.getenv("TEST_DB_HOST", "127.0.0.1")
		db.DB_PORT = os.getenv("TEST_DB_PORT", "5432")
		db.DB_NAME = os.getenv("TEST_DB_NAME", db.DB_NAME)
		db.DB_USER = os.getenv("TEST_DB_USER", db.DB_USER)
		db.DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", db.DB_PASSWORD)
		if db.DB_HOST not in {"localhost", "127.0.0.1", "::1"}:
			raise unittest.SkipTest("Database tests require a local PostgreSQL host")

	def setUp(self):
		self.connection = db.create_connection()
		db.delete_subscriber(self.connection)

	def tearDown(self):
		db.delete_subscriber(self.connection)
		self.connection.close()

	def test_insert_and_get_active_subscriber(self):
		inserted = db.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertTrue(inserted)
		self.assertTrue(
			db.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_duplicate_active_subscriber_is_not_inserted(self):
		db.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		inserted_again = db.subscriber_insert_query(
			self.connection, "student@uni-trier.de", 12345
		)

		self.assertFalse(inserted_again)
		self.assertEqual(
			db.get_active_subscribers(self.connection), [12345]
		)

	def test_latest_subscription_entry_controls_status(self):
		old_record = """
			INSERT INTO subscriber
				(unique_id, uni_email, start_date, end_date, telegram_id, is_active)
			VALUES (%s, %s, %s, %s, %s, TRUE)
		"""
		new_record = """
			INSERT INTO subscriber
				(unique_id, uni_email, start_date, end_date, telegram_id, is_active)
			VALUES (%s, %s, %s, %s, %s, FALSE)
		"""

		older_start = datetime.now(timezone.utc) - timedelta(days=10)
		older_end = datetime.now(timezone.utc) + timedelta(days=2)
		newer_start = datetime.now(timezone.utc) - timedelta(hours=1)
		newer_end = datetime.now(timezone.utc) - timedelta(minutes=5)

		with self.connection.cursor() as cur:
			cur.execute(old_record, ("old-entry", "old@uni-trier.de", older_start, older_end, 99999))
			cur.execute(new_record, ("new-entry", "new@uni-trier.de", newer_start, newer_end, 99999))
		self.connection.commit()

		self.assertFalse(db.get_subscriber_status(self.connection, 99999))
		self.assertEqual(db.get_active_subscribers(self.connection), [])

	def test_active_subscriber_count_rejects_when_limit_is_reached(self):
		db.subscriber_insert_query(self.connection, "first@uni-trier.de", 1)

		with patch.object(db, "MAXIMUM_ENTRIES", 1):
			status, _ = db.check_active_subscriber_count(self.connection)
			self.assertFalse(status)

	def test_active_subscriber_count_ignores_other_domains(self):
		db.subscriber_insert_query(self.connection, "student@uni-trier.de", 1)
		db.subscriber_insert_query(self.connection, "person@example.com", 2)

		with patch.object(db, "MAXIMUM_ENTRIES", 2):
			status, _ = db.check_active_subscriber_count(self.connection)
			self.assertTrue(status)

	def test_expired_subscriber_is_deactivated(self):
		db.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)
		future = datetime.now(timezone.utc) + timedelta(days=6)

		with patch.object(db, "datetime") as datetime_mock:
			datetime_mock.now.return_value = future
			updated = db.subscriber_update_query(self.connection, 12345)

		self.assertTrue(updated)
		self.assertFalse(
			db.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_force_update_deactivates_active_subscriber(self):
		db.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		self.assertTrue(
			db.subscriber_update_query(self.connection, 12345, force=True)
		)
		self.assertFalse(
			db.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_update_returns_false_for_non_expired_subscriber(self):
		db.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		self.assertFalse(db.subscriber_update_query(self.connection, 12345))

	def test_delete_all_subscribers(self):
		db.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		self.assertTrue(db.delete_subscriber(self.connection))
		self.assertFalse(
			db.get_subscriber_status(
				self.connection, 12345
			)
		)

	def test_get_active_subscribers_returns_only_active_ids(self):
		db.subscriber_insert_query(self.connection, "first@uni-trier.de", 1)
		db.subscriber_insert_query(self.connection, "second@uni-trier.de", 2)
		db.subscriber_update_query(self.connection, 2, force=True)

		self.assertEqual(db.get_active_subscribers(self.connection), [1])

	def test_earliest_expired_subscriber_returns_default_without_active_rows(self):
		self.assertEqual(
			db.get_earliest_expired_subscriber(self.connection), 5
		)

	def test_earliest_expired_subscriber_returns_days_until_earliest_end(self):
		db.subscriber_insert_query(self.connection, "student@uni-trier.de", 12345)

		days_left = db.get_earliest_expired_subscriber(self.connection)

		self.assertGreaterEqual(days_left, 4)
		self.assertLessEqual(days_left, 5)


class OutboxDatabaseTests(unittest.TestCase):
	setUpClass = SubscriberDatabaseTests.setUpClass

	def setUp(self):
		self.connection = db.create_connection()
		self._clear()

	def tearDown(self):
		self._clear()
		self.connection.close()

	def _clear(self):
		with self.connection, self.connection.cursor() as cur:
			cur.execute("DELETE FROM notification_outbox")

	def _insert(self):
		return db.insert_outbox_event(self.connection, "APPOINTMENT_FOUND", {}, 60)

	def test_insert_skips_duplicate_inside_cooldown(self):
		self.assertTrue(self._insert())
		self.assertFalse(self._insert())

	def test_insert_after_cooldown(self):
		self._insert()
		with self.connection, self.connection.cursor() as cur:
			cur.execute("UPDATE notification_outbox SET created_at = now() - interval '61 minutes'")

		self.assertTrue(self._insert())

	def test_claim_skips_rows_locked_by_another_transaction(self):
		with self.connection, self.connection.cursor() as cur:
			cur.execute(
				"INSERT INTO notification_outbox (event_type) VALUES ('APPOINTMENT_FOUND'), ('APPOINTMENT_FOUND') RETURNING id"
			)
			locked_id, free_id = sorted(row[0] for row in cur.fetchall())

		other = db.create_connection()
		try:
			other.cursor().execute("SELECT id FROM notification_outbox WHERE id = %s FOR UPDATE", (locked_id,))
			claimed = db.claim_outbox_events(self.connection)
		finally:
			other.close()

		self.assertEqual([row[0] for row in claimed], [free_id])

	def test_error_retries_until_failed_after_three_attempts(self):
		self._insert()
		statuses = []
		for _ in range(3):
			(event_id, *_), = db.claim_outbox_events(self.connection)
			statuses.append(db.mark_outbox_error(self.connection, event_id, "boom"))

		self.assertEqual(statuses, ["pending", "pending", "failed"])
		self.assertEqual(db.claim_outbox_events(self.connection), [])

	def test_reset_stuck_processing_rows(self):
		self._insert()
		db.claim_outbox_events(self.connection)
		with self.connection, self.connection.cursor() as cur:
			cur.execute("UPDATE notification_outbox SET claimed_at = now() - interval '11 minutes'")

		self.assertEqual(db.reset_stuck_outbox_events(self.connection), 1)
		self.assertEqual(len(db.claim_outbox_events(self.connection)), 1)


if __name__ == "__main__":
	unittest.main()
