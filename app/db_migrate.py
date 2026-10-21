"""Additive schema upgrades for tables that already exist.

db.create_all() creates tables it has never seen but never alters one that exists, so a column added to a
model after the table shipped must also be listed here or an existing database errors the first time that
column is read.

Rules this module keeps:
  * only ADD COLUMN, never drop, rename or rewrite: existing rows and values are untouched, and a new
    column is NULL for them;
  * safe to run any number of times (a column that is already there is skipped), and safe when the backend
    and the worker start at the same moment (PostgreSQL gets ADD COLUMN IF NOT EXISTS; if a concurrent
    process wins the race, the loser re-checks and carries on);
  * one failing column never stops the others or the application from starting.
"""
from sqlalchemy import inspect, text

# (table, column, DDL type). Add new columns at the end.
COLUMNS = (
    ('users', 'telegram_chat_id', 'VARCHAR(255)'),
    # Model score behind an alert; NULL for rows written before this column existed.
    ('notification_history', 'confidence', 'FLOAT'),
    # Set once by the first person who acknowledges the alert (see routes/logs.py).
    ('notification_history', 'acknowledged_at', 'TIMESTAMP'),
    ('notification_history', 'acknowledged_by', 'INTEGER REFERENCES users(id)'),
    # Reserved for the web UI's fields; nothing writes these yet, so they stay NULL.
    ('notification_history', 'escalation_count', 'INTEGER'),
    ('notification_history', 'clip_path', 'VARCHAR(512)'),
    ('notification_history', 'still_down_seconds', 'FLOAT'),
)


def _column_names(engine, table):
    return {c['name'] for c in inspect(engine).get_columns(table)}


def ensure_columns(db, columns=COLUMNS):
    """Add every listed column that is missing. -> list of 'table.column' strings that were added."""
    engine = db.engine
    added = []
    for table, column, ddl_type in columns:
        try:
            if table not in inspect(engine).get_table_names():
                continue                      # create_all() has just built it with the column
            if column in _column_names(engine, table):
                continue
            if_not_exists = 'IF NOT EXISTS ' if engine.dialect.name == 'postgresql' else ''
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {if_not_exists}{column} {ddl_type}'))
            added.append(f'{table}.{column}')
            print(f'Added missing column {column} to {table} table')
        except Exception as exc:                                    # noqa: BLE001
            try:
                already_there = column in _column_names(engine, table)
            except Exception:                                       # noqa: BLE001
                already_there = False
            if not already_there:
                print(f'Could not add {table}.{column} automatically: {exc}')
    return added
