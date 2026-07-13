import sqlite3
from pathlib import Path


class ConversationMemory:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    wa_id TEXT PRIMARY KEY,
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add_message(self, wa_id: str, role: str, content: str) -> None:
        content = content.strip()
        if not content:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (wa_id, role, content) VALUES (?, ?, ?)",
                (wa_id, role, content[:12000]),
            )

    def recent_messages(self, wa_id: str, limit: int) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE wa_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (wa_id, limit),
            ).fetchall()

        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def last_user_message(self, wa_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content FROM messages
                WHERE wa_id = ? AND role = 'user'
                ORDER BY id DESC
                LIMIT 1
                """,
                (wa_id,),
            ).fetchone()
        return row[0] if row else ""

    def get_preferences(self, wa_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT notes FROM preferences WHERE wa_id = ?",
                (wa_id,),
            ).fetchone()
        return row[0] if row else ""

    def set_preferences(self, wa_id: str, notes: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (wa_id, notes, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(wa_id) DO UPDATE SET
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (wa_id, notes.strip()),
            )
