"""
Schema inspection tool, per the design doc's recommendation:
instead of dumping the entire schema into every prompt, expose small
functions the agents/orchestrator can call to get just what's needed.

For this small demo database the full schema is cheap to include, but
the interface is written so it scales to larger databases later
(e.g. by only fetching tables relevant to the current question).
"""

import sqlite3
from config.settings import DB_PATH


def _connect():
    return sqlite3.connect(DB_PATH)


def get_database_schema() -> dict:
    """Returns {table_name: [(column_name, column_type), ...]} for every table."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cur.fetchall()]

    schema = {}
    for table in tables:
        cur.execute(f"PRAGMA table_info({table})")
        schema[table] = [(col[1], col[2]) for col in cur.fetchall()]

    conn.close()
    return schema


def get_table_columns(table_name: str) -> list:
    schema = get_database_schema()
    return schema.get(table_name, [])


def get_table_sample(table_name: str, n: int = 3) -> list:
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table_name} LIMIT ?", (n,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def get_database_date_range(table_name: str, date_column: str = "sale_date") -> dict:
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT MIN({date_column}), MAX({date_column}) FROM {table_name}")
        min_d, max_d = cur.fetchone()
        return {"min_date": min_d, "max_date": max_d}
    finally:
        conn.close()


def get_distinct_values(table_name: str, column_name: str, limit: int = 200) -> list:
    """Returns distinct values for a column, used to detect literal filter
    values (e.g. a named region/category/product) mentioned in a question."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT DISTINCT {column_name} FROM {table_name} LIMIT ?", (limit,))
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def schema_as_prompt_text() -> str:
    """Renders the schema as compact text suitable for inclusion in an LLM prompt."""
    schema = get_database_schema()
    lines = []
    for table, columns in schema.items():
        col_desc = ", ".join(f"{name} ({ctype})" for name, ctype in columns)
        lines.append(f"- {table}({col_desc})")
    return "\n".join(lines)