import sqlite3
import json
import os
from typing import Dict, Optional

DB_PATH = os.getenv("DB_PATH", "forgery.sqlite")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.commit()

def save_task(task_id: str, data: dict):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, data) VALUES (?, ?)",
            (task_id, json.dumps(data))
        )
        conn.commit()

def get_task(task_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT data FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row:
            return json.loads(row["data"])
    return None

def save_report(report_id: str, data: dict):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reports (report_id, data) VALUES (?, ?)",
            (report_id, json.dumps(data))
        )
        conn.commit()

def get_report(report_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT data FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        if row:
            return json.loads(row["data"])
    return None

init_db()
