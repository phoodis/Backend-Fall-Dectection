"""Times that leave the backend, and the day boundaries used to query them.

The model columns are naive DateTime, and the code writes datetime.now(Asia/Bangkok) into them. What the database
then keeps depends on the driver:
  * PostgreSQL: psycopg2 sends the value as timestamptz and the server converts it to its own TimeZone (UTC in the
    docker image) when it stores it in the "timestamp without time zone" column. The stored wall clock is UTC.
  * SQLite (tests, local runs): the tzinfo is dropped, the stored wall clock is Bangkok time.
Rows already in the database are not touched; this module only tells the readers how to interpret them, so every
time sent to the web page carries an explicit offset (+07:00) and "today" is the Thai day. DB_NAIVE_TIMEZONE
overrides the guess (for a PostgreSQL whose TimeZone is not UTC).
"""
import os
from datetime import datetime, timedelta

import pytz

BANGKOK = pytz.timezone('Asia/Bangkok')


def storage_tz():
    """The zone of the wall clock stored in the naive DateTime columns."""
    name = os.getenv('DB_NAIVE_TIMEZONE')
    if not name:
        from app import db
        name = 'UTC' if db.engine.dialect.name == 'postgresql' else 'Asia/Bangkok'
    return pytz.timezone(name)


def as_bangkok(value):
    """A stored datetime as an aware Asia/Bangkok datetime (None stays None)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = storage_tz().localize(value)
    return value.astimezone(BANGKOK)


def iso_th(value):
    """ISO 8601 with the offset, e.g. 2026-10-22T16:05:09+07:00, so the browser cannot mistake it for UTC."""
    aware = as_bangkok(value)
    return aware.isoformat() if aware is not None else None


def thai_day_bounds(now=None):
    """(start, end) of the current Thai calendar day, as naive datetimes in the stored zone, for filters on the
    DateTime columns. `now` is only for tests."""
    now = now or datetime.now(BANGKOK)
    start = BANGKOK.localize(datetime(now.year, now.month, now.day))
    end = BANGKOK.localize(datetime(now.year, now.month, now.day) + timedelta(days=1)) - timedelta(microseconds=1)
    zone = storage_tz()
    return (start.astimezone(zone).replace(tzinfo=None), end.astimezone(zone).replace(tzinfo=None))
