import sqlite3
from config.settings import DB_PATH


def execute_sql(sql: str) -> dict:
    """
    Executes an already-validated, read-only SQL query.
    Returns {"columns": [...], "rows": [...]} or raises on error.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA query_only = ON;")  # extra safety belt at the DB level
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        return {"columns": columns, "rows": rows}
    finally:
        conn.close()