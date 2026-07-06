"""
Lightweight SQLite-backed conversation state store.

Each WhatsApp sender (phone number) maps to exactly one active
conversation record. This gives us persistence across process
restarts without needing an external database for a take-home-sized
project, while still being easy to swap for Redis/Postgres later
(see README "Scaling notes").
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from config import Config

_lock = threading.Lock()

STAGE_COLLECTING = "collecting"
STAGE_CONFIRMING = "confirming"
STAGE_SUBMITTED = "submitted"


def _init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                phone_number TEXT PRIMARY KEY,
                stage TEXT NOT NULL DEFAULT 'collecting',
                fields TEXT NOT NULL DEFAULT '{}',
                history TEXT NOT NULL DEFAULT '[]',
                order_reference TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()


@contextmanager
def _connect():
    conn = sqlite3.connect(Config.DATABASE_PATH, timeout=10)
    try:
        yield conn
    finally:
        conn.close()


def get_or_create(phone_number: str) -> dict:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT phone_number, stage, fields, history, order_reference, created_at, updated_at "
            "FROM conversations WHERE phone_number = ?",
            (phone_number,),
        )
        row = cur.fetchone()
        now = time.time()
        if row is None:
            conn.execute(
                "INSERT INTO conversations (phone_number, stage, fields, history, order_reference, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (phone_number, STAGE_COLLECTING, "{}", "[]", None, now, now),
            )
            conn.commit()
            return {
                "phone_number": phone_number,
                "stage": STAGE_COLLECTING,
                "fields": {},
                "history": [],
                "order_reference": None,
            }

        _, stage, fields_json, history_json, order_reference, created_at, updated_at = row

        # Expire stale sessions so a returning customer starts fresh.
        if now - updated_at > Config.SESSION_TIMEOUT_MINUTES * 60:
            reset(phone_number)
            return {
                "phone_number": phone_number,
                "stage": STAGE_COLLECTING,
                "fields": {},
                "history": [],
                "order_reference": None,
            }

        return {
            "phone_number": phone_number,
            "stage": stage,
            "fields": json.loads(fields_json),
            "history": json.loads(history_json),
            "order_reference": order_reference,
        }


def save(phone_number: str, stage: str, fields: dict, history: list, order_reference: str = None) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE conversations SET stage = ?, fields = ?, history = ?, order_reference = ?, "
            "updated_at = ? WHERE phone_number = ?",
            (stage, json.dumps(fields), json.dumps(history), order_reference, time.time(), phone_number),
        )
        conn.commit()


def reset(phone_number: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE conversations SET stage = ?, fields = '{}', history = '[]', order_reference = NULL, "
            "updated_at = ? WHERE phone_number = ?",
            (STAGE_COLLECTING, time.time(), phone_number),
        )
        conn.commit()


_init_db()
