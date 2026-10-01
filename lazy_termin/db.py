from datetime import datetime, timedelta
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
from psycopg2.pool import ThreadedConnectionPool

from .config import (
    ADMIN_ID,
    ALLOWED_DOMAINS,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    MAXIMUM_ENTRIES,
    TIME_FORMAT,
    TIMEZONE,
)
from .log import logger

connection_pool = None


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
        raise


def initialize_pool(min_connections=1, max_connections=10):
    """Initialize the PostgreSQL connection pool and create the schema."""
    global connection_pool

    if connection_pool is not None:
        return

    connection_pool = ThreadedConnectionPool(
        minconn=min_connections,
        maxconn=max_connections,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )
    connection = connection_pool.getconn()
    try:
        subscriber_schema(connection)
    finally:
        connection_pool.putconn(connection)


def get_connection():
    """Borrow a healthy connection from the pool."""
    if connection_pool is None:
        initialize_pool()

    connection = connection_pool.getconn()
    if connection.closed:
        connection_pool.putconn(connection, close=True)
        connection = connection_pool.getconn()
    return connection


def release_connection(connection):
    """Return a connection to the pool, discarding closed connections."""
    if connection_pool is None:
        connection.close()
        return

    connection_pool.putconn(connection, close=bool(connection.closed))


def close_pool():
    """Close all connections managed by the pool."""
    global connection_pool

    if connection_pool is not None:
        connection_pool.closeall()
        connection_pool = None

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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_message_event (
            event_id BIGSERIAL PRIMARY KEY,
            telegram_update_id BIGINT UNIQUE,
            telegram_id BIGINT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            message_type TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INT NOT NULL DEFAULT 0,
            claimed_at TIMESTAMPTZ NULL,
            processed_at TIMESTAMPTZ NULL,
            last_error TEXT NULL
        );
        CREATE INDEX IF NOT EXISTS notification_outbox_status_created_at_idx
            ON notification_outbox (status, created_at);
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_delivery (
            outbox_id BIGINT NOT NULL REFERENCES notification_outbox(id) ON DELETE CASCADE,
            telegram_id BIGINT NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (outbox_id, telegram_id)
        );
        CREATE INDEX IF NOT EXISTS alert_delivery_telegram_id_sent_at_idx
            ON alert_delivery (telegram_id, sent_at);
        """
    )
    conn.commit()
    return True


def insert_outbox_event(conn, event_type, payload):
    """Insert an outbox event unless one of the same type is still waiting to be sent.
    :return: True if a row was inserted
    """
    with conn:
        cur = conn.cursor()
        # Serialise concurrent inserts so the dedup check cannot race.
        cur.execute("LOCK TABLE notification_outbox IN SHARE ROW EXCLUSIVE MODE")
        cur.execute(
            """
            INSERT INTO notification_outbox (event_type, payload)
            SELECT %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM notification_outbox
                WHERE event_type = %s
                  AND status IN ('pending', 'processing')
            )
            """,
            (event_type, Json(payload), event_type),
        )
        inserted = cur.rowcount == 1
        if inserted:
            cur.execute("NOTIFY notification_outbox")
    return inserted


def claim_outbox_events(conn, limit=10):
    """Mark up to `limit` pending events as processing and return (id, event_type, payload, attempts)."""
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE notification_outbox
            SET status = 'processing', attempts = attempts + 1, claimed_at = now()
            WHERE id IN (
                SELECT id FROM notification_outbox
                WHERE status = 'pending'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            RETURNING id, event_type, payload, attempts
            """,
            (limit,),
        )
        return sorted(cur.fetchall())


def mark_outbox_sent(conn, event_id):
    with conn:
        conn.cursor().execute(
            "UPDATE notification_outbox SET status = 'sent', processed_at = now() WHERE id = %s",
            (event_id,),
        )


def mark_outbox_error(conn, event_id, error, max_attempts=3):
    """Record a send error; return the new status ('pending' to retry, or 'failed')."""
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE notification_outbox
            SET last_error = %s,
                status = CASE WHEN attempts < %s THEN 'pending' ELSE 'failed' END,
                processed_at = CASE WHEN attempts < %s THEN NULL ELSE now() END
            WHERE id = %s
            RETURNING status
            """,
            (str(error)[:500], max_attempts, max_attempts, event_id),
        )
        return cur.fetchone()[0]


def reset_stuck_outbox_events(conn, minutes=10):
    """Return events stuck in processing (e.g. after a crash mid-send) to pending."""
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE notification_outbox SET status = 'pending'
            WHERE status = 'processing' AND claimed_at < now() - make_interval(mins => %s)
            """,
            (minutes,),
        )
        return cur.rowcount


def delete_old_rows(conn, days=30):
    """Delete outbox and message-event rows older than `days`."""
    with conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM notification_outbox WHERE created_at < now() - make_interval(days => %s)",
            (days,),
        )
        cur.execute(
            "DELETE FROM telegram_message_event WHERE received_at < now() - make_interval(days => %s)",
            (days,),
        )


def record_message_event(conn, telegram_id, update_id, message_type):
    """Record message metadata without storing message contents."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO telegram_message_event
            (telegram_update_id, telegram_id, received_at, message_type)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (telegram_update_id) DO NOTHING
        """,
        (update_id, telegram_id, datetime.now(TIMEZONE), message_type),
    )
    conn.commit()


def get_message_stats(conn, since):
    """Return message count and unique-user count since a UTC timestamp."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT telegram_id)
        FROM telegram_message_event
        WHERE received_at >= %s AND telegram_id != %s
        """,
        (since, ADMIN_ID),
    )
    message_count, user_count = cur.fetchone()
    return message_count, user_count

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


def get_latest_subscriber_row(conn, telegram_id):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
            WHERE telegram_id = %s
        ) ranked
        WHERE rn = 1
        """,
        (telegram_id,),
    )
    return cur.fetchone()


def get_earliest_expired_subscriber(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT end_date
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
        ) ranked
        WHERE rn = 1
          AND is_active = TRUE
        ORDER BY end_date ASC
        LIMIT 1
        """
    )
    data = cur.fetchone()

    if data is None:
        return 5

    end_date = data[0]
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, TIME_FORMAT).replace(tzinfo=TIMEZONE)
    days_left = (end_date - datetime.now(TIMEZONE)).days

    return days_left


def get_active_subscribers(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT telegram_id
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
        ) ranked
        WHERE rn = 1
          AND is_active = TRUE
        """
    )
    data = cur.fetchall()
    return [row[0] for row in data]


def get_alert_recipients(conn, cooldown_minutes):
    """Return active subscribers who have not been alerted within the cooldown.

    The 1-minute grace stops a delivery a few seconds short of the cooldown
    from pushing the next alert to a later scrape.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT telegram_id
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
        ) ranked
        WHERE rn = 1
          AND is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM alert_delivery
              WHERE alert_delivery.telegram_id = ranked.telegram_id
                AND alert_delivery.sent_at > now() - make_interval(mins => %s)
          )
        """,
        (cooldown_minutes - 1,),
    )
    return [row[0] for row in cur.fetchall()]


def record_alert_delivery(conn, outbox_id, telegram_id):
    """Record that one alert reached one subscriber."""
    with conn:
        conn.cursor().execute(
            """
            INSERT INTO alert_delivery (outbox_id, telegram_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (outbox_id, telegram_id),
        )


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
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
        ) ranked
        WHERE rn = 1
          AND is_active = TRUE
          AND LOWER(TRIM(SPLIT_PART(uni_email, '@', 2))) = ANY(%s)
        """,
        (allowed_domain_list,),
    )
    total_active_entries = cur.fetchone()[0]
    if total_active_entries >= MAXIMUM_ENTRIES:
        logger.warning(
            f"Maximum entries reached: {total_active_entries}/{MAXIMUM_ENTRIES} active entries."
        )
        return False, total_active_entries
    return True, total_active_entries

def subscriber_insert_query(conn, uni_email, telegram_id):
    current_status = get_subscriber_status(conn, telegram_id)
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
        """
        SELECT unique_id, end_date
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
            WHERE telegram_id = %s
        ) ranked
        WHERE rn = 1
        """,
        (telegram_id,),
    )
    target_user = cur.fetchone()

    if target_user:
        unique_id, end_date = target_user
        q = "UPDATE subscriber SET is_active = FALSE WHERE unique_id = %s"
        if force:
            cur.execute(q, (unique_id,))
            conn.commit()
            return True

        right_now = datetime.now(TIMEZONE)
        if right_now > end_date:
            cur.execute(q, (unique_id,))
            conn.commit()
            return True

    return False


def get_subscriber_status(conn, telegram_id):
    subscriber_update_query(conn, telegram_id)  # Update only the latest record if expired
    cur = conn.cursor()
    cur.execute(
        """
        SELECT is_active
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY telegram_id
                       ORDER BY start_date DESC, end_date DESC, unique_id DESC
                   ) AS rn
            FROM subscriber
            WHERE telegram_id = %s
        ) ranked
        WHERE rn = 1
        """,
        (telegram_id,),
    )
    row = cur.fetchone()
    status = False if row is None else row[0] == 1

    return status
