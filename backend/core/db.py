import json
import os
import sqlite3
import time
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "forgery.sqlite")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks "
            "(task_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reports "
            "(report_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


def save_task(task_id: str, data: dict) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, data) VALUES (?, ?)",
            (task_id, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def get_task(task_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT data FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()


def save_report(report_id: str, data: dict) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO reports (report_id, data) VALUES (?, ?)",
            (report_id, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def get_report(report_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT data FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()


def cleanup_old_records(expiration_hours: int) -> tuple[int, int]:
    conn = get_db()
    try:
        expiration_secs = expiration_hours * 3600
        cutoff = time.time() - expiration_secs
        
        cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE json_extract(data, '$.timestamp') < ?", (cutoff,))
        tasks_deleted = cur.rowcount
        
        cur.execute("DELETE FROM reports WHERE json_extract(data, '$.timestamp') < ?", (cutoff,))
        reports_deleted = cur.rowcount
        
        conn.commit()
        return tasks_deleted, reports_deleted
    except Exception:
        return 0, 0
    finally:
        conn.close()

init_db()
