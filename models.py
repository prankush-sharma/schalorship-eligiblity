import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scorecard.db')


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS scorecards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            registration_no TEXT,
            qr_data TEXT,
            image_hash TEXT,
            gate_score TEXT,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            original_filename TEXT
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_qr_data ON scorecards(qr_data)
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_image_hash ON scorecards(image_hash)
    ''')
    conn.commit()
    conn.close()


def add_scorecard(student_name, registration_no, qr_data, image_hash, gate_score, original_filename):
    """Add a new scorecard entry to the database."""
    conn = get_db()
    cursor = conn.execute('''
        INSERT INTO scorecards (student_name, registration_no, qr_data, image_hash, gate_score, original_filename)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (student_name, registration_no, qr_data, image_hash, gate_score, original_filename))
    conn.commit()
    record_id = cursor.lastrowid
    conn.close()
    return record_id


def check_duplicate(qr_data, image_hash):
    """
    Check if a scorecard already exists in the database.
    Matches by QR data OR image hash (perceptual hash).
    Returns the matching record if found, else None.
    """
    conn = get_db()
    row = None

    # Check by QR data first (most reliable)
    if qr_data:
        row = conn.execute(
            'SELECT * FROM scorecards WHERE qr_data = ?', (qr_data,)
        ).fetchone()

    # If no QR match, check by image hash
    if not row and image_hash:
        row = conn.execute(
            'SELECT * FROM scorecards WHERE image_hash = ?', (image_hash,)
        ).fetchone()

    conn.close()
    return dict(row) if row else None


def get_all_scorecards():
    """Get all scorecard entries."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM scorecards ORDER BY uploaded_at DESC'
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_scorecard(record_id):
    """Delete a scorecard entry by ID."""
    conn = get_db()
    conn.execute('DELETE FROM scorecards WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()


def get_scorecard_count():
    """Get total number of scorecards."""
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM scorecards').fetchone()[0]
    conn.close()
    return count
