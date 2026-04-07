import sqlite3
import threading
import os
from datetime import datetime


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_ROOT, "pickleball.db")
_lock = threading.Lock()


def init_db():
    """Create tables if they don't exist."""
    with sqlite3.connect(DB_PATH) as conn:
        # WAL mode allows reads and writes to happen concurrently —
        # prevents the /matches page from blocking while game_logic writes at 25fps
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ended_at   TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id   INTEGER NOT NULL,
                timestamp  TEXT NOT NULL,
                event_type TEXT NOT NULL,
                cx         REAL,
                cy         REAL,
                confidence REAL,
                notes      TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id     INTEGER NOT NULL,
                timestamp    TEXT NOT NULL,
                server_score INTEGER NOT NULL,
                receiver_score INTEGER NOT NULL,
                server_number  INTEGER NOT NULL,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        conn.commit()


def start_match():
    """Insert a new match row and return its ID."""
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "INSERT INTO matches (started_at) VALUES (?)",
                (datetime.now().isoformat(),)
            )
            conn.commit()
            return cur.lastrowid


def end_match(match_id):
    """Mark the match as ended."""
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE matches SET ended_at = ? WHERE id = ?",
                (datetime.now().isoformat(), match_id)
            )
            conn.commit()


def log_event(match_id, event_type, cx=None, cy=None, confidence=None, notes=None):
    """
    Log a game event.
    event_type examples: 'ball_detected', 'bounce', 'point', 'serve'
    """
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO events
                   (match_id, timestamp, event_type, cx, cy, confidence, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (match_id, datetime.now().isoformat(),
                 event_type, cx, cy, confidence, notes)
            )
            conn.commit()


def log_score(match_id, server_score, receiver_score, server_number):
    """Log a score update."""
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO scores
                   (match_id, timestamp, server_score, receiver_score, server_number)
                   VALUES (?, ?, ?, ?, ?)""",
                (match_id, datetime.now().isoformat(),
                 server_score, receiver_score, server_number)
            )
            conn.commit()


def get_match_events(match_id):
    """Retrieve all events for a match (for post-match analysis)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM events WHERE match_id = ? ORDER BY timestamp",
            (match_id,)
        )
        return [dict(row) for row in cur.fetchall()]


def get_all_matches():
    """Return all matches ordered newest first."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM matches ORDER BY id DESC")
        return [dict(row) for row in cur.fetchall()]


def get_match_summary(match_id):
    """Return match row plus aggregated event counts."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        match = conn.execute(
            "SELECT * FROM matches WHERE id = ?", (match_id,)
        ).fetchone()
        stats = conn.execute(
            """SELECT
                COUNT(CASE WHEN event_type='bounce'       THEN 1 END) AS total_bounces,
                COUNT(CASE WHEN event_type='point_server' THEN 1 END) AS total_points,
                COUNT(CASE WHEN event_type='side_out'     THEN 1 END) AS total_side_outs
               FROM events WHERE match_id = ?""",
            (match_id,)
        ).fetchone()
        return {"match": dict(match) if match else {}, "stats": dict(stats) if stats else {}}


def get_match_bounces(match_id):
    """Return all bounce events with position data."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT timestamp, cx, cy, notes FROM events
               WHERE match_id = ? AND event_type = 'bounce'
               ORDER BY timestamp""",
            (match_id,)
        )
        return [dict(row) for row in cur.fetchall()]


def get_match_scores(match_id):
    """Return all score snapshots for the timeline chart."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM scores WHERE match_id = ? ORDER BY timestamp",
            (match_id,)
        )
        return [dict(row) for row in cur.fetchall()]
