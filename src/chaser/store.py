import json
import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "store" / "chaser.sqlite"


class ChaserStore:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    supplier_id TEXT NOT NULL,
                    supplier_name TEXT NOT NULL,
                    supplier_email TEXT NOT NULL,
                    component TEXT NOT NULL,
                    po TEXT NOT NULL,
                    what_we_need TEXT NOT NULL,
                    deadline TEXT NOT NULL,
                    language TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
                    direction TEXT NOT NULL,
                    sender TEXT,
                    recipient TEXT,
                    subject TEXT,
                    body TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replies (
                    reply_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
                    raw_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    new_eta TEXT,
                    quantity INTEGER,
                    confidence REAL NOT NULL,
                    needs_human INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inbox (
                    inbox_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def create_thread(self, payload: dict) -> None:
        with self.connect() as db:
            db.execute("""
                INSERT OR REPLACE INTO threads (
                    thread_id,supplier_id,supplier_name,supplier_email,component,po,
                    what_we_need,deadline,language,tone,subject,body,state,created_at,updated_at
                ) VALUES (
                    :thread_id,:supplier_id,:supplier_name,:supplier_email,:component,:po,
                    :what_we_need,:deadline,:language,:tone,:subject,:body,:state,:created_at,:updated_at
                )
            """, payload)

    def get_thread(self, thread_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return dict(row) if row else None

    def list_threads(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM threads ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def set_thread_state(self, thread_id: str, state: str, at: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE threads SET state=?, updated_at=? WHERE thread_id=?", (state, at, thread_id))

    def add_message(self, payload: dict) -> None:
        with self.connect() as db:
            db.execute("""
                INSERT INTO messages
                    (message_id,thread_id,direction,sender,recipient,subject,body,created_at)
                VALUES (:message_id,:thread_id,:direction,:sender,:recipient,:subject,:body,:created_at)
            """, payload)

    def add_reply(self, payload: dict) -> None:
        with self.connect() as db:
            db.execute("""
                INSERT INTO replies
                    (reply_id,thread_id,raw_text,status,new_eta,quantity,confidence,needs_human,created_at)
                VALUES (:reply_id,:thread_id,:raw_text,:status,:new_eta,:quantity,:confidence,:needs_human,:created_at)
            """, payload)

    def add_inbox(self, payload: dict) -> None:
        with self.connect() as db:
            db.execute("""
                INSERT INTO inbox
                    (inbox_id,thread_id,sender,recipient,subject,body,created_at)
                VALUES (:inbox_id,:thread_id,:sender,:recipient,:subject,:body,:created_at)
            """, payload)

    def log(self, thread_id: str | None, action: str, payload: dict, at: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO action_log(thread_id,action,payload,created_at) VALUES(?,?,?,?)",
                (thread_id, action, json.dumps(payload, ensure_ascii=False), at),
            )

    def action_log(self, thread_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if thread_id:
                rows = db.execute(
                    "SELECT * FROM action_log WHERE thread_id=? ORDER BY id", (thread_id,)
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM action_log ORDER BY id").fetchall()
        return [dict(row) for row in rows]
