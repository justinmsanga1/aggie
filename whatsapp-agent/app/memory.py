import sqlite3
import json
import os
from pathlib import Path
from typing import Any

import httpx


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_files (
                    wa_id TEXT PRIMARY KEY,
                    media_id TEXT NOT NULL,
                    filename TEXT,
                    mime_type TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_instructions (
                    wa_id TEXT PRIMARY KEY,
                    instruction TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

    def set_pending_file(
        self,
        wa_id: str,
        media_id: str,
        filename: str | None,
        mime_type: str | None,
    ) -> None:
        payload = {
            "media_id": media_id,
            "filename": filename or "",
            "mime_type": mime_type or "",
        }
        if _redis_set(f"pending_file:{wa_id}", payload):
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_files (wa_id, media_id, filename, mime_type, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(wa_id) DO UPDATE SET
                    media_id = excluded.media_id,
                    filename = excluded.filename,
                    mime_type = excluded.mime_type,
                    created_at = CURRENT_TIMESTAMP
                """,
                (wa_id, media_id, filename or "", mime_type or ""),
            )

    def get_pending_file(self, wa_id: str) -> dict[str, Any] | None:
        redis_value = _redis_get(f"pending_file:{wa_id}")
        if redis_value:
            return {
                "media_id": redis_value.get("media_id"),
                "filename": redis_value.get("filename") or None,
                "mime_type": redis_value.get("mime_type") or None,
            }

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT media_id, filename, mime_type FROM pending_files
                WHERE wa_id = ?
                """,
                (wa_id,),
            ).fetchone()
        if not row:
            return None
        media_id, filename, mime_type = row
        return {
            "media_id": media_id,
            "filename": filename or None,
            "mime_type": mime_type or None,
        }

    def clear_pending_file(self, wa_id: str) -> None:
        _redis_delete(f"pending_file:{wa_id}")
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_files WHERE wa_id = ?", (wa_id,))

    def set_pending_instruction(self, wa_id: str, instruction: str) -> None:
        instruction = instruction.strip()
        if not instruction:
            return
        payload = {"instruction": instruction}
        if _redis_set(f"pending_instruction:{wa_id}", payload):
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_instructions (wa_id, instruction, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(wa_id) DO UPDATE SET
                    instruction = excluded.instruction,
                    created_at = CURRENT_TIMESTAMP
                """,
                (wa_id, instruction[:4000]),
            )

    def get_pending_instruction(self, wa_id: str) -> str:
        redis_value = _redis_get(f"pending_instruction:{wa_id}")
        if redis_value:
            return str(redis_value.get("instruction") or "")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT instruction FROM pending_instructions
                WHERE wa_id = ?
                """,
                (wa_id,),
            ).fetchone()
        return row[0] if row else ""

    def clear_pending_instruction(self, wa_id: str) -> None:
        _redis_delete(f"pending_instruction:{wa_id}")
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_instructions WHERE wa_id = ?", (wa_id,))


def _redis_config() -> tuple[str, str] | None:
    url = (
        os.environ.get("KV_REST_API_URL")
        or os.environ.get("UPSTASH_REDIS_REST_URL")
        or ""
    ).strip().rstrip("/")
    token = (
        os.environ.get("KV_REST_API_TOKEN")
        or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
        or ""
    ).strip()
    if not url or not token:
        return None
    return url, token


def _redis_set(key: str, value: dict[str, Any], ttl_seconds: int = 86400) -> bool:
    config = _redis_config()
    if not config:
        return False
    url, token = config
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=["SET", key, json.dumps(value), "EX", str(ttl_seconds)],
            )
            response.raise_for_status()
        return True
    except Exception:
        return False


def _redis_get(key: str) -> dict[str, Any] | None:
    config = _redis_config()
    if not config:
        return None
    url, token = config
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=["GET", key],
            )
            response.raise_for_status()
        raw_value = response.json().get("result")
        if not raw_value:
            return None
        value = json.loads(raw_value)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _redis_delete(key: str) -> None:
    config = _redis_config()
    if not config:
        return
    url, token = config
    try:
        with httpx.Client(timeout=10) as client:
            client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=["DEL", key],
            )
    except Exception:
        return
