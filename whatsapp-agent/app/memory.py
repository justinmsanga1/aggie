import sqlite3
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from app import blob_store

logger = logging.getLogger("whatsapp-agent")


class ConversationMemory:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _init_db(self) -> None:
        try:
            self._create_tables(self._connect())
        except sqlite3.DatabaseError:
            logger.warning("SQLite database corrupted, recreating: %s", self.database_path)
            self._recreate_database()

    def _recreate_database(self) -> None:
        try:
            self.database_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            wal_path = self.database_path.with_suffix(".sqlite3-wal")
            wal_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            shm_path = self.database_path.with_suffix(".sqlite3-shm")
            shm_path.unlink(missing_ok=True)
        except Exception:
            pass
        self._create_tables(self._connect())

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        with conn:
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
                    blob_path TEXT,
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_jobs (
                    job_id TEXT PRIMARY KEY,
                    wa_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    media_id TEXT,
                    filename TEXT,
                    mime_type TEXT,
                    source_blob_path TEXT,
                    result_blob_path TEXT,
                    instruction TEXT,
                    result_filename TEXT,
                    error TEXT,
                    events_json TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            _ensure_column(conn, "pending_files", "blob_path", "TEXT")
            _ensure_column(conn, "document_jobs", "source_blob_path", "TEXT")
            _ensure_column(conn, "document_jobs", "result_blob_path", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def is_message_processed(self, message_id: str) -> bool:
        if _get_persistent(f"processed_msg:{message_id}"):
            return True
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM processed_messages WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
            return row is not None
        except sqlite3.DatabaseError:
            logger.warning("DB read failed in is_message_processed, recreating database")
            self._recreate_database()
            return False

    def mark_message_processed(self, message_id: str) -> None:
        _set_persistent(
            f"processed_msg:{message_id}",
            {"message_id": message_id},
            ttl_seconds=604800,
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)",
                    (message_id,),
                )
        except sqlite3.DatabaseError:
            logger.warning("DB write failed in mark_message_processed, recreating database")
            self._recreate_database()

    def add_message(self, wa_id: str, role: str, content: str) -> None:
        content = content.strip()
        if not content:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO messages (wa_id, role, content) VALUES (?, ?, ?)",
                    (wa_id, role, content[:12000]),
                )
        except sqlite3.DatabaseError:
            logger.warning("DB write failed in add_message, recreating database")
            self._recreate_database()

    def recent_messages(self, wa_id: str, limit: int) -> list[dict[str, str]]:
        try:
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
        except sqlite3.DatabaseError:
            logger.warning("DB read failed in recent_messages, recreating database")
            self._recreate_database()
            return []

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
        blob_path: str | None = None,
    ) -> None:
        payload = {
            "media_id": media_id,
            "filename": filename or "",
            "mime_type": mime_type or "",
            "blob_path": blob_path or "",
        }
        if _set_persistent(f"pending_file:{wa_id}", payload):
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_files (wa_id, media_id, filename, mime_type, blob_path, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(wa_id) DO UPDATE SET
                    media_id = excluded.media_id,
                    filename = excluded.filename,
                    mime_type = excluded.mime_type,
                    blob_path = excluded.blob_path,
                    created_at = CURRENT_TIMESTAMP
                """,
                (wa_id, media_id, filename or "", mime_type or "", blob_path or ""),
            )

    def get_pending_file(self, wa_id: str) -> dict[str, Any] | None:
        value = _get_persistent(f"pending_file:{wa_id}")
        if value:
            return {
                "media_id": value.get("media_id"),
                "filename": value.get("filename") or None,
                "mime_type": value.get("mime_type") or None,
                "blob_path": value.get("blob_path") or None,
            }

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT media_id, filename, mime_type, blob_path FROM pending_files
                WHERE wa_id = ?
                """,
                (wa_id,),
            ).fetchone()
        if not row:
            return None
        media_id, filename, mime_type, blob_path = row
        return {
            "media_id": media_id,
            "filename": filename or None,
            "mime_type": mime_type or None,
            "blob_path": blob_path or None,
        }

    def clear_pending_file(self, wa_id: str) -> None:
        _redis_delete(f"pending_file:{wa_id}")
        blob_store.delete(_blob_key(f"pending_file:{wa_id}"))
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_files WHERE wa_id = ?", (wa_id,))

    def set_pending_instruction(self, wa_id: str, instruction: str) -> None:
        instruction = instruction.strip()
        if not instruction:
            return
        payload = {"instruction": instruction}
        if _set_persistent(f"pending_instruction:{wa_id}", payload):
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
        value = _get_persistent(f"pending_instruction:{wa_id}")
        if value:
            return str(value.get("instruction") or "")
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
        blob_store.delete(_blob_key(f"pending_instruction:{wa_id}"))
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_instructions WHERE wa_id = ?", (wa_id,))

    def create_document_job(
        self,
        wa_id: str,
        media_id: str,
        filename: str | None,
        mime_type: str | None,
        instruction: str = "",
        source_blob_path: str | None = None,
    ) -> dict[str, Any]:
        job = {
            "job_id": uuid.uuid4().hex,
            "wa_id": wa_id,
            "status": "received",
            "media_id": media_id,
            "filename": filename or "",
            "mime_type": mime_type or "",
            "source_blob_path": source_blob_path or "",
            "result_blob_path": "",
            "instruction": instruction.strip(),
            "result_filename": "",
            "error": "",
            "events": [],
        }
        job["events"].append(_job_event("received", "File received"))
        self._save_document_job(job)
        _set_persistent(f"latest_document_job:{wa_id}", {"job_id": job["job_id"]})
        return job

    def latest_document_job(self, wa_id: str) -> dict[str, Any] | None:
        latest = _get_persistent(f"latest_document_job:{wa_id}")
        if latest and latest.get("job_id"):
            job = self.get_document_job(str(latest["job_id"]))
            if job:
                return job
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id FROM document_jobs
                WHERE wa_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (wa_id,),
            ).fetchone()
        return self.get_document_job(row[0]) if row else None

    def get_document_job(self, job_id: str) -> dict[str, Any] | None:
        persistent_job = _get_persistent(f"document_job:{job_id}")
        if persistent_job:
            return persistent_job
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, wa_id, status, media_id, filename, mime_type, instruction,
                       result_filename, error, events_json, source_blob_path, result_blob_path
                FROM document_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if not row:
            return None
        (
            job_id,
            wa_id,
            status,
            media_id,
            filename,
            mime_type,
            instruction,
            result_filename,
            error,
            events_json,
            source_blob_path,
            result_blob_path,
        ) = row
        return {
            "job_id": job_id,
            "wa_id": wa_id,
            "status": status,
            "media_id": media_id or "",
            "filename": filename or "",
            "mime_type": mime_type or "",
            "source_blob_path": source_blob_path or "",
            "result_blob_path": result_blob_path or "",
            "instruction": instruction or "",
            "result_filename": result_filename or "",
            "error": error or "",
            "events": _loads_events(events_json),
        }

    def update_document_job(
        self,
        job: dict[str, Any],
        status: str | None = None,
        event: str | None = None,
        detail: str = "",
        **updates: Any,
    ) -> dict[str, Any]:
        if status:
            job["status"] = status
        for key, value in updates.items():
            job[key] = value or ""
        if event:
            events = job.setdefault("events", [])
            if isinstance(events, list):
                events.append(_job_event(event, detail))
        self._save_document_job(job)
        return job

    def recent_document_jobs(self, wa_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if wa_id:
                rows = conn.execute(
                    """
                    SELECT job_id FROM document_jobs
                    WHERE wa_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (wa_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT job_id FROM document_jobs
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [job for row in rows if (job := self.get_document_job(row[0]))]

    def _save_document_job(self, job: dict[str, Any]) -> None:
        events = job.get("events") if isinstance(job.get("events"), list) else []
        job["events"] = events
        _set_persistent(f"document_job:{job['job_id']}", job, ttl_seconds=604800)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO document_jobs (
                    job_id, wa_id, status, media_id, filename, mime_type, instruction,
                    source_blob_path, result_blob_path, result_filename, error, events_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    media_id = excluded.media_id,
                    filename = excluded.filename,
                    mime_type = excluded.mime_type,
                    instruction = excluded.instruction,
                    source_blob_path = excluded.source_blob_path,
                    result_blob_path = excluded.result_blob_path,
                    result_filename = excluded.result_filename,
                    error = excluded.error,
                    events_json = excluded.events_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    job["job_id"],
                    job.get("wa_id", ""),
                    job.get("status", ""),
                    job.get("media_id", ""),
                    job.get("filename", ""),
                    job.get("mime_type", ""),
                    job.get("instruction", ""),
                    job.get("source_blob_path", ""),
                    job.get("result_blob_path", ""),
                    job.get("result_filename", ""),
                    job.get("error", ""),
                    json.dumps(events),
                ),
            )


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


def _set_persistent(key: str, value: dict[str, Any], ttl_seconds: int = 86400) -> bool:
    if _redis_set(key, value, ttl_seconds=ttl_seconds):
        return True
    if blob_store.put_json(_blob_key(key), value):
        return True
    return False


def _get_persistent(key: str) -> dict[str, Any] | None:
    value = _redis_get(key)
    if value:
        return value
    return blob_store.get_json(_blob_key(key))


def _blob_key(key: str) -> str:
    safe = key.replace(":", "/")
    return f"state/{safe}.json"


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


def _job_event(event: str, detail: str = "") -> dict[str, str]:
    from datetime import datetime, timezone

    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "detail": detail,
    }


def _loads_events(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
