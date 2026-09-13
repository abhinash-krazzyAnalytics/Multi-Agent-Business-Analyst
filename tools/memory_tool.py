"""
Persistent conversation + analytical memory, stored in its own SQLite
database (separate from the business database being analyzed).

Per the design doc: short-term memory lives in the LangGraph state
for the duration of one turn; this module is the persistent layer
that survives across app restarts within a session_id.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from config.settings import MEMORY_DB_PATH


def _connect():
    os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analytical_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            user_question TEXT,
            route TEXT,
            sql_query TEXT,
            filters TEXT,
            summary TEXT
        )
    """)
    return conn


def save_step(session_id: str, user_question: str, route: str,
              sql_query: str = None, filters: dict = None, summary: str = None):
    conn = _connect()
    conn.execute(
        "INSERT INTO analytical_steps (session_id, timestamp, user_question, route, sql_query, filters, summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            datetime.now(timezone.utc).isoformat(),
            user_question,
            route,
            sql_query,
            json.dumps(filters or {}),
            summary,
        ),
    )
    conn.commit()
    conn.close()


def get_recent_steps(session_id: str, limit: int = 5) -> list:
    conn = _connect()
    cur = conn.execute(
        "SELECT user_question, route, sql_query, filters, summary FROM analytical_steps "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    rows = cur.fetchall()
    conn.close()

    steps = []
    for question, route, sql_query, filters, summary in reversed(rows):
        steps.append({
            "user_question": question,
            "route": route,
            "sql_query": sql_query,
            "filters": json.loads(filters) if filters else {},
            "summary": summary,
        })
    return steps


def get_last_filters(session_id: str) -> dict:
    steps = get_recent_steps(session_id, limit=1)
    return steps[-1]["filters"] if steps else {}