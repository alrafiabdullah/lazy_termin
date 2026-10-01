import os

# Required settings must exist before lazy_termin.config is imported.
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("MAXIMUM_ENTRIES", "10")
os.environ.setdefault("ADMIN_ID", "1")


def use_local_test_database():
	"""Point lazy_termin.db at the local test database; skip if it is not local."""
	import unittest

	from lazy_termin import db

	# Tests must never use the application's remote PostgreSQL settings.
	db.DB_HOST = os.getenv("TEST_DB_HOST", "127.0.0.1")
	db.DB_PORT = os.getenv("TEST_DB_PORT", "5432")
	db.DB_NAME = os.getenv("TEST_DB_NAME", db.DB_NAME)
	db.DB_USER = os.getenv("TEST_DB_USER", db.DB_USER)
	db.DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", db.DB_PASSWORD)
	if db.DB_HOST not in {"localhost", "127.0.0.1", "::1"}:
		raise unittest.SkipTest("Database tests require a local PostgreSQL host")
