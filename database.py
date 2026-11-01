import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent / "assistant.db"



def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with get_connection() as connection:
        # 1. Create tasks table for new databases.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
                    CHECK (completed IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ),
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                user_sub TEXT NOT NULL
            )
        """)

        # 2. Migrate existing tasks table without deleting data.
        task_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tasks)"
            ).fetchall()
        }

        if "user_sub" not in task_columns:
            connection.execute(
                "ALTER TABLE tasks ADD COLUMN user_sub TEXT"
            )

        if "priority" not in task_columns:
            connection.execute("""
                ALTER TABLE tasks
                ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'
            """)

        if "due_date" not in task_columns:
            connection.execute(
                "ALTER TABLE tasks ADD COLUMN due_date TEXT"
            )

        # 3. Create calendar_events table for new databases.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ),
                user_sub TEXT NOT NULL,
                CHECK (end_time > start_time)
            )
        """)

        # 4. Migrate existing calendar_events table.
        event_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(calendar_events)"
            ).fetchall()
        }

        if "user_sub" not in event_columns:
            connection.execute(
                "ALTER TABLE calendar_events ADD COLUMN user_sub TEXT"
            )





def create_task(
    title: str,
    user_sub: str,
    priority: str = "medium",
    due_date: str | None = None,
) -> dict:
    title = title.strip()
    priority = priority.strip().lower()

    if not user_sub or not user_sub.strip():
     raise ValueError("User identity is required.")

    if not title:
        raise ValueError("Task title cannot be empty.")

    if priority not in {"low", "medium", "high"}:
        raise ValueError("Priority must be low, medium, or high.")

    if due_date:
        try:
            datetime.fromisoformat(due_date.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                "Due date must be a valid ISO 8601 date or datetime."
            )

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        cursor = conn.execute(
            """
            INSERT INTO tasks (title, priority, due_date, completed, created_at, user_sub)
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (
                title,
                priority,
                due_date,
                datetime.now(timezone.utc).isoformat(),
                user_sub,
            ),
        )

        task_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_sub = ?",
            (task_id, user_sub),
        ).fetchone()

        return dict(row)


def list_tasks(user_sub: str, pending_only: bool = True) -> list[dict]:
    query = "SELECT * FROM tasks WHERE user_sub = ?"
    parameters = (user_sub,)

    if not user_sub or not user_sub.strip():
        raise ValueError("User identity is required.")
 
    if pending_only:
        query += " AND completed = 0"

    query += " ORDER BY id DESC"

    with get_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]


def complete_task(task_id: int, user_sub: str) -> dict | None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE tasks SET completed = 1 WHERE id = ? AND user_sub = ?",
            (task_id, user_sub),
        )

        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_sub = ?",
            (task_id, user_sub),
        ).fetchone()

        return dict(row) if row else None


initialize_database()



def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str,
    user_sub: str,
) -> dict:
    title = title.strip()

    if not user_sub or not user_sub.strip():
     raise ValueError("User identity is required.")

    if not title:
        raise ValueError("Event title cannot be empty.")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO calendar_events
                (title, start_time, end_time, user_sub)
            VALUES (?, ?, ?, ?)
            """,
            (title, start_time, end_time, user_sub),
        )

        row = connection.execute(
            """
            SELECT *
            FROM calendar_events
            WHERE id = ? AND user_sub = ?
            """,
            (cursor.lastrowid, user_sub),
        ).fetchone()

        return dict(row)


def list_upcoming_events(
    from_time: str,
    user_sub: str,
    limit: int = 10,
) -> list[dict]:
    if not user_sub or not user_sub.strip():
     raise ValueError("User identity is required.")

    if limit < 1:
      raise ValueError("Limit must be at least 1.")
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM calendar_events
            WHERE user_sub = ? AND start_time >= ?
            ORDER BY start_time ASC
            LIMIT ?
            """,
            (user_sub, from_time, limit),
        ).fetchall()

        return [dict(row) for row in rows]
