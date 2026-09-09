import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from utils_logger import MAXIMUM_ENTRIES, logger


def create_connection(db_file):
    """ create a database connection to the SQLite database specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        subscriber_schema(conn)
        return conn
    except sqlite3.Error as e:
        logger.error(f"Error creating database connection: {e}")
        raise str(e)

def subscriber_schema(conn):
    """ create a database schema for the subscriber table
    :return: SQL statement for creating the subscriber table
    """
    subscriber_schema = """
    CREATE TABLE IF NOT EXISTS subscriber (
        unique_id TEXT PRIMARY KEY,
        uni_email TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        telegram_id INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    """
    cur = conn.cursor()
    cur.execute(subscriber_schema)
    conn.commit()
    return True

def delete_subscriber(conn, with_table=False):
    q = "DELETE FROM subscriber;"
    if with_table:
        q = "DROP TABLE IF EXISTS subscriber;"

    cur = conn.cursor()
    cur.execute(q)
    conn.commit()

    return True

def check_active_subscriber_count(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM subscriber WHERE uni_email LIKE ? AND is_active=1",
        ("%@uni-trier.de",),
    )
    total_active_entries = cur.fetchone()[0]
    if total_active_entries >= MAXIMUM_ENTRIES:
        logger.warning(
            f"Maximum entries reached: {total_active_entries}/{MAXIMUM_ENTRIES} active entries."
        )
        return False  # Maximum entries reached, do not insert
    return True 

def subscriber_insert_query(conn, uni_email, telegram_id):
    # get total active entries with email ending with @uni-trier.de
    cur = conn.cursor()

    current_status = get_subscriber_status(conn, uni_email, telegram_id)
    if current_status:
        return False  # User is already active, no need to insert again

    unique_id = str(uuid4())
    start_datetime = datetime.now(timezone.utc)
    start_date = start_datetime.strftime("%Y-%m-%d %H:%M:%S")
    end_date = (start_datetime + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

    query = """
    INSERT INTO subscriber (unique_id, uni_email, start_date, end_date, telegram_id, is_active)
    VALUES (?, ?, ?, ?, ?, 1);
    """
    cur = conn.cursor()
    cur.execute(query, (unique_id, uni_email, start_date, end_date, telegram_id))
    conn.commit()

    return True

def subscriber_update_query(conn, uni_email, telegram_id):
    cur = conn.cursor()
    target_user = cur.execute(
        "SELECT * FROM subscriber WHERE uni_email=? AND telegram_id=?",
        (uni_email, telegram_id),
    ).fetchone()

    if target_user:
        right_now = datetime.now(timezone.utc)
        end_date = datetime.strptime(target_user[2], "%Y-%m-%d %H:%M:%S").astimezone(timezone.utc)

        if right_now > end_date:
            # update is_active to 0
            cur.execute(
                "UPDATE subscriber SET is_active=0 WHERE uni_email=? AND telegram_id=?",
                (uni_email, telegram_id),
            )
            conn.commit()
            return True

    return False


def get_subscriber_status(conn, uni_email, telegram_id):
    subscriber_update_query(conn, uni_email, telegram_id)  # Update status if expired
    cur = conn.cursor()
    cur.execute(
        "SELECT is_active FROM subscriber WHERE uni_email=? AND telegram_id=?",
        (uni_email, telegram_id),
    )
    row = cur.fetchone()
    status = False if row is None else row[0] == 1

    return status
