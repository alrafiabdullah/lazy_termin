from datetime import datetime, timedelta
from uuid import uuid4

import psycopg2

from utils_logger import (
    ALLOWED_DOMAINS,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    MAXIMUM_ENTRIES,
    TIME_FORMAT,
    TIMEZONE,
    logger,
)


def create_connection():
    """Create a database connection to PostgreSQL.
    :return: Connection object or None
    """
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
        )
        subscriber_schema(conn)
        return conn
    except psycopg2.Error as e:
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
        start_date TIMESTAMPTZ NOT NULL,
        end_date TIMESTAMPTZ NOT NULL,
        telegram_id BIGINT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    );
    """
    cur = conn.cursor()
    cur.execute(subscriber_schema)
    conn.commit()
    return True

def delete_subscriber(conn, id=None, with_table=False):
    if id:
        cur = conn.cursor()
        cur.execute("DELETE FROM subscriber WHERE unique_id = %s", (id,))
        conn.commit()
        return True
    
    q = "DELETE FROM subscriber;"
    if with_table:
        q = "DROP TABLE IF EXISTS subscriber;"

    cur = conn.cursor()
    cur.execute(q)
    conn.commit()

    return True


def get_earliest_expired_subscriber(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM subscriber
                WHERE is_active = TRUE
        ORDER BY end_date ASC
        LIMIT 1
        """
    )
    data = cur.fetchone()
    
    if data is None:
        return 5

    end_date = data[3]
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, TIME_FORMAT).replace(tzinfo=TIMEZONE)
    days_left = (end_date - datetime.now(TIMEZONE)).days

    return days_left


def get_active_subscribers(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT telegram_id FROM subscriber WHERE is_active = TRUE"
    )
    data = cur.fetchall()
    data = [row[0] for row in data]  # Extract telegram_id from each row
    
    return data


def check_active_subscriber_count(conn):
    cur = conn.cursor()
    allowed_domain_list = [
        domain.strip().lower().lstrip("@")
        for domain in ALLOWED_DOMAINS.split(",")
        if domain.strip()
    ]
    
    cur.execute(
        """
        SELECT COUNT(*)
        FROM subscriber
        WHERE is_active = TRUE
          AND LOWER(TRIM(SPLIT_PART(uni_email, '@', 2))) = ANY(%s)
        """,
        (allowed_domain_list,),
    )
    total_active_entries = cur.fetchone()[0]
    if total_active_entries >= MAXIMUM_ENTRIES:
        logger.warning(
            f"Maximum entries reached: {total_active_entries}/{MAXIMUM_ENTRIES} active entries."
        )
        return False  # Maximum entries reached, do not insert
    return True

def subscriber_insert_query(conn, uni_email, telegram_id):
    current_status = get_subscriber_status(conn, uni_email, telegram_id)
    if current_status:
        return False  # User is already active, no need to insert again

    unique_id = str(uuid4())
    start_datetime = datetime.now(TIMEZONE)
    end_date = start_datetime + timedelta(days=5)

    query = """
    INSERT INTO subscriber (unique_id, uni_email, start_date, end_date, telegram_id, is_active)
    VALUES (%s, %s, %s, %s, %s, TRUE);
    """
    cur = conn.cursor()
    cur.execute(query, (unique_id, uni_email, start_datetime, end_date, telegram_id))
    conn.commit()

    return True

def subscriber_update_query(conn, telegram_id, force=False):
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM subscriber WHERE telegram_id = %s",
        (telegram_id,),
    )
    target_user = cur.fetchone()

    if target_user:
        q = "UPDATE subscriber SET is_active = FALSE WHERE telegram_id = %s"
        if force:
            cur.execute(q, (telegram_id,))
            conn.commit()
            return True

        right_now = datetime.now(TIMEZONE)
        end_date = target_user[3]

        if right_now > end_date:
            cur.execute(q, (telegram_id,))
            conn.commit()
            return True

    return False


def get_subscriber_status(conn, uni_email, telegram_id):
    subscriber_update_query(conn, telegram_id)  # Update status if expired
    cur = conn.cursor()
    cur.execute(
        """
        SELECT is_active
        FROM subscriber
        WHERE uni_email = %s AND telegram_id = %s
        """,
        (uni_email, telegram_id),
    )
    row = cur.fetchone()
    status = False if row is None else row[0] == 1

    return status
