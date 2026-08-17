import os
import sqlite3

from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get(
    "SPENDLY_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "spendly.db"),
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def db_is_healthy():
    """Readiness check — the DB is reachable and writable. DB logic only;
    the /readyz route in app.py calls this rather than touching sqlite3
    or get_db() directly."""
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except sqlite3.Error:
        return False


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def create_user(name, email, password):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash(password)),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return user


def seed_db():
    conn = get_db()

    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    if row[0] > 0:
        conn.close()
        return

    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
    )
    user_id = cursor.lastrowid

    expenses = [
        (user_id, 450.00,  "Food",          "2026-04-01", "Groceries from D-Mart"),
        (user_id, 120.00,  "Transport",     "2026-04-02", "Metro card recharge"),
        (user_id, 1200.00, "Bills",         "2026-04-03", "Electricity bill"),
        (user_id, 350.00,  "Health",        "2026-04-05", "Pharmacy — vitamins"),
        (user_id, 500.00,  "Entertainment", "2026-04-06", "Movie tickets"),
        (user_id, 800.00,  "Shopping",      "2026-04-07", "New earphones"),
        (user_id, 200.00,  "Other",         "2026-04-08", "Miscellaneous"),
        (user_id, 180.00,  "Food",          "2026-04-08", "Lunch with colleagues"),
    ]

    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()
