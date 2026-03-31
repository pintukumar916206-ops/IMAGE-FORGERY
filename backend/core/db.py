import os
import json
import time
from typing import Optional, Dict, Tuple
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base, Session

DB_PATH = os.getenv("DB_PATH", "forgery.sqlite")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False},
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"
    task_id = Column(String, primary_key=True, index=True)
    data = Column(Text, nullable=False)

class Report(Base):
    __tablename__ = "reports"
    report_id = Column(String, primary_key=True, index=True)
    data = Column(Text, nullable=False)

def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
            conn.commit()
        except Exception:
            pass

def get_session() -> Session:
    return SessionLocal()

def save_task(task_id: str, data: Dict) -> None:
    session = get_session()
    try:
        task = session.query(Task).filter(Task.task_id == task_id).first()
        if task:
            task.data = json.dumps(data)
        else:
            task = Task(task_id=task_id, data=json.dumps(data))
            session.add(task)
        session.commit()
    finally:
        session.close()

def get_task(task_id: str) -> Optional[Dict]:
    session = get_session()
    try:
        task = session.query(Task).filter(Task.task_id == task_id).first()
        return json.loads(task.data) if task else None
    finally:
        session.close()

def save_report(report_id: str, data: Dict) -> None:
    session = get_session()
    try:
        report = session.query(Report).filter(Report.report_id == report_id).first()
        if report:
            report.data = json.dumps(data)
        else:
            report = Report(report_id=report_id, data=json.dumps(data))
            session.add(report)
        session.commit()
    finally:
        session.close()

def get_report(report_id: str) -> Optional[Dict]:
    session = get_session()
    try:
        report = session.query(Report).filter(Report.report_id == report_id).first()
        return json.loads(report.data) if report else None
    finally:
        session.close()

def cleanup_old_records(expiration_hours: int) -> Tuple[int, int]:
    session = get_session()
    try:
        cutoff = time.time() - (expiration_hours * 3600)
        from sqlalchemy import text
        tasks_deleted = session.execute(
            text("DELETE FROM tasks WHERE json_extract(data, '$.timestamp') < :cutoff"),
            {"cutoff": cutoff}
        ).rowcount
        reports_deleted = session.execute(
            text("DELETE FROM reports WHERE json_extract(data, '$.timestamp') < :cutoff"),
            {"cutoff": cutoff}
        ).rowcount
        session.commit()
        return tasks_deleted, reports_deleted
    except Exception:
        session.rollback()
        return 0, 0
    finally:
        session.close()

init_db()
