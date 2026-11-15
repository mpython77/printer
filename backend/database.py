"""SQLite database initialization and CRUD helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

QUEUE_LOCK = threading.RLock()

from backend.config import (
    DB_PATH,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_AGENT_KEY,
    DEFAULT_PRINTER_NAME,
    PRICE_BW_DUPLEX,
    PRICE_BW_SIMPLEX,
    PRICE_COLOR_DUPLEX,
    PRICE_COLOR_SIMPLEX,
    PRINTER_MODE,
    SECONDS_BW_PER_SHEET,
    SECONDS_COLOR_PER_SHEET,
    WARMUP_SECONDS,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: str | None = None) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random hex salt."""
    used_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        used_salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"{used_salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored 'salt$digest' hash."""
    if "$" not in stored_hash:
        return False
    salt, expected = stored_hash.split("$", 1)
    candidate = _hash_password(password, salt=salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, expected)


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection configured with WAL mode and busy timeout."""
    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create database tables and seed default system settings if missing."""
    now = _utc_now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                normalized_pdf_path TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS print_jobs (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                student_name TEXT NOT NULL DEFAULT '',
                selected_pages_json TEXT NOT NULL,
                page_range_text TEXT NOT NULL,
                rotations_json TEXT NOT NULL DEFAULT '{}',
                selected_page_count INTEGER NOT NULL,
                copies INTEGER NOT NULL DEFAULT 1,
                color_mode TEXT NOT NULL DEFAULT 'bw',
                duplex TEXT NOT NULL DEFAULT 'simplex',
                orientation TEXT NOT NULL DEFAULT 'portrait',
                pages_per_sheet INTEGER NOT NULL DEFAULT 1,
                paper_size TEXT NOT NULL DEFAULT 'A4',
                total_printed_pages INTEGER NOT NULL,
                physical_sheets INTEGER NOT NULL,
                estimated_cost INTEGER NOT NULL,
                estimated_seconds INTEGER NOT NULL DEFAULT 0,
                color_pages_json TEXT NOT NULL DEFAULT '[]',
                bw_sheets INTEGER NOT NULL DEFAULT 0,
                color_sheets INTEGER NOT NULL DEFAULT 0,
                segments_json TEXT NOT NULL DEFAULT '[]',
                printer_name TEXT NOT NULL DEFAULT '',
                printer_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                status_message TEXT NOT NULL DEFAULT '',
                output_pdf_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                client_token TEXT NOT NULL DEFAULT '',
                device_label TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT '',
                queue_state TEXT NOT NULL DEFAULT 'COMPLETED',
                started_at TEXT NOT NULL DEFAULT '',
                printing_until_ts REAL NOT NULL DEFAULT 0,
                confirm_deadline_ts REAL NOT NULL DEFAULT 0,
                completed_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (document_id) REFERENCES documents (id)
            )
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(print_jobs)").fetchall()}
        migrations = {
            "estimated_seconds": "INTEGER NOT NULL DEFAULT 0",
            "color_pages_json": "TEXT NOT NULL DEFAULT '[]'",
            "bw_sheets": "INTEGER NOT NULL DEFAULT 0",
            "color_sheets": "INTEGER NOT NULL DEFAULT 0",
            "segments_json": "TEXT NOT NULL DEFAULT '[]'",
            "client_token": "TEXT NOT NULL DEFAULT ''",
            "device_label": "TEXT NOT NULL DEFAULT ''",
            "client_ip": "TEXT NOT NULL DEFAULT ''",
            "queue_state": "TEXT NOT NULL DEFAULT 'COMPLETED'",
            "started_at": "TEXT NOT NULL DEFAULT ''",
            "printing_until_ts": "REAL NOT NULL DEFAULT 0",
            "confirm_deadline_ts": "REAL NOT NULL DEFAULT 0",
            "completed_at": "TEXT NOT NULL DEFAULT ''",
            "payment_status": "TEXT NOT NULL DEFAULT 'NOT_REQUIRED'",
            "payment_created_ts": "REAL NOT NULL DEFAULT 0",
            "payment_deadline_ts": "REAL NOT NULL DEFAULT 0",
            "payment_tx_id": "TEXT NOT NULL DEFAULT ''",
            "payment_verified_at": "TEXT NOT NULL DEFAULT ''",
            "payment_note": "TEXT NOT NULL DEFAULT ''",
            "receipt_path": "TEXT NOT NULL DEFAULT ''",
            "receipt_filename": "TEXT NOT NULL DEFAULT ''",
            "receipt_uploaded_at": "TEXT NOT NULL DEFAULT ''",
        }
        for col_name, col_def in migrations.items():
            if col_name not in cols:
                conn.execute(f"ALTER TABLE print_jobs ADD COLUMN {col_name} {col_def}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS used_payment_transactions (
                tx_uid TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                amount_uzs INTEGER NOT NULL,
                card_mask TEXT NOT NULL DEFAULT '',
                msg_date TEXT NOT NULL DEFAULT '',
                raw_text TEXT NOT NULL DEFAULT '',
                claimed_at TEXT NOT NULL
            )
            """
        )

        defaults = {
            "admin_username": "admin",
            "admin_password_hash": _hash_password(DEFAULT_ADMIN_PASSWORD),
            "token_secret": secrets.token_hex(32),
            "price_bw_simplex": str(PRICE_BW_SIMPLEX),
            "price_bw_duplex": str(PRICE_BW_DUPLEX),
            "price_color_simplex": str(PRICE_COLOR_SIMPLEX),
            "price_color_duplex": str(PRICE_COLOR_DUPLEX),
            "seconds_bw_per_sheet": str(SECONDS_BW_PER_SHEET),
            "seconds_color_per_sheet": str(SECONDS_COLOR_PER_SHEET),
            "warmup_seconds": str(WARMUP_SECONDS),
            "printer_mode": PRINTER_MODE,
            "default_printer_name": DEFAULT_PRINTER_NAME,
            "agent_api_key": DEFAULT_AGENT_KEY or f"tlg-{secrets.token_hex(12)}",
            "agent_last_seen": "",
            "agent_hostname": "",
            "agent_printers_json": "[]",
            "payment_enabled": "1",
            "payment_card_number": "",
            "payment_card_holder": "",
            "payment_window_seconds": "120",
            "telegram_bot_username": "@HUMOcardbot",
            "telegram_session_string": "",
            "telegram_account_name": "",
            "telegram_account_username": "",
            "telegram_account_phone": "",
        }
        for key, value in defaults.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, now),
            )


def _get_raw_settings(db_path: Path | None = None) -> dict[str, str]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def get_token_secret(db_path: Path | None = None) -> str:
    """Return persistent HMAC signing secret for admin tokens."""
    raw = _get_raw_settings(db_path=db_path)
    secret = raw.get("token_secret")
    if secret:
        return secret
    init_db(db_path=db_path)
    return _get_raw_settings(db_path=db_path)["token_secret"]


def get_settings(db_path: Path | None = None) -> dict[str, Any]:
    """Return typed pricing, printer configuration, and admin username."""
    raw = _get_raw_settings(db_path=db_path)
    if not raw:
        init_db(db_path=db_path)
        raw = _get_raw_settings(db_path=db_path)

    try:
        agent_printers = json.loads(raw.get("agent_printers_json", "[]") or "[]")
        if not isinstance(agent_printers, list):
            agent_printers = []
    except Exception:
        agent_printers = []

    return {
        "admin_username": raw.get("admin_username", "admin"),
        "bw_simplex": int(raw.get("price_bw_simplex", PRICE_BW_SIMPLEX)),
        "bw_duplex": int(raw.get("price_bw_duplex", PRICE_BW_DUPLEX)),
        "color_simplex": int(raw.get("price_color_simplex", PRICE_COLOR_SIMPLEX)),
        "color_duplex": int(raw.get("price_color_duplex", PRICE_COLOR_DUPLEX)),
        "seconds_bw_per_sheet": int(raw.get("seconds_bw_per_sheet", SECONDS_BW_PER_SHEET)),
        "seconds_color_per_sheet": int(raw.get("seconds_color_per_sheet", SECONDS_COLOR_PER_SHEET)),
        "warmup_seconds": int(raw.get("warmup_seconds", WARMUP_SECONDS)),
        "printer_mode": raw.get("printer_mode", PRINTER_MODE),
        "default_printer_name": raw.get("default_printer_name", DEFAULT_PRINTER_NAME),
        "agent_api_key": raw.get("agent_api_key", DEFAULT_AGENT_KEY),
        "agent_last_seen": raw.get("agent_last_seen", ""),
        "agent_hostname": raw.get("agent_hostname", ""),
        "agent_printers": agent_printers,
        "payment_enabled": str(raw.get("payment_enabled", "1")).strip().lower() not in {"0", "false", "no", ""},
        "payment_card_number": raw.get("payment_card_number", ""),
        "payment_card_holder": raw.get("payment_card_holder", ""),
        "payment_window_seconds": max(30, int(raw.get("payment_window_seconds", "120") or 120)),
        "telegram_bot_username": raw.get("telegram_bot_username", "@HUMOcardbot"),
        "telegram_session_string": raw.get("telegram_session_string", ""),
        "telegram_account_name": raw.get("telegram_account_name", ""),
        "telegram_account_username": raw.get("telegram_account_username", ""),
        "telegram_account_phone": raw.get("telegram_account_phone", ""),
    }


def update_settings(updates: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    """Persist updated pricing and printer settings and return the new settings."""
    key_map = {
        "bw_simplex": "price_bw_simplex",
        "bw_duplex": "price_bw_duplex",
        "color_simplex": "price_color_simplex",
        "color_duplex": "price_color_duplex",
        "seconds_bw_per_sheet": "seconds_bw_per_sheet",
        "seconds_color_per_sheet": "seconds_color_per_sheet",
        "warmup_seconds": "warmup_seconds",
        "printer_mode": "printer_mode",
        "default_printer_name": "default_printer_name",
        "agent_api_key": "agent_api_key",
        "payment_enabled": "payment_enabled",
        "payment_card_number": "payment_card_number",
        "payment_card_holder": "payment_card_holder",
        "payment_window_seconds": "payment_window_seconds",
        "telegram_bot_username": "telegram_bot_username",
        "telegram_session_string": "telegram_session_string",
        "telegram_account_name": "telegram_account_name",
        "telegram_account_username": "telegram_account_username",
        "telegram_account_phone": "telegram_account_phone",
    }
    now = _utc_now_iso()
    with get_connection(db_path) as conn:
        for src_key, db_key in key_map.items():
            if src_key in updates and updates[src_key] is not None:
                raw_val = updates[src_key]
                if src_key == "payment_enabled":
                    if isinstance(raw_val, bool):
                        str_val = "1" if raw_val else "0"
                    else:
                        str_val = "0" if str(raw_val).strip().lower() in {"0", "false", "no", ""} else "1"
                else:
                    str_val = str(raw_val)
                conn.execute(
                    """
                    INSERT INTO system_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (db_key, str_val, now),
                )
    return get_settings(db_path=db_path)


def verify_admin_credentials(username: str, password: str, db_path: Path | None = None) -> bool:
    """Validate admin username and password against stored PBKDF2 hash."""
    raw = _get_raw_settings(db_path=db_path)
    if not raw:
        init_db(db_path=db_path)
        raw = _get_raw_settings(db_path=db_path)
    expected_user = raw.get("admin_username", "admin")
    stored_hash = raw.get("admin_password_hash", "")
    return hmac.compare_digest(username.strip(), expected_user) and _verify_password(
        password, stored_hash
    )


def update_admin_credentials(
    new_username: str,
    current_password: str,
    new_password: str,
    db_path: Path | None = None,
) -> bool:
    """Verify current password, then update admin username and hashed password."""
    raw = _get_raw_settings(db_path=db_path)
    stored_hash = raw.get("admin_password_hash", "")
    if not _verify_password(current_password, stored_hash):
        return False

    clean_user = new_username.strip()
    if not clean_user or not new_password:
        return False

    now = _utc_now_iso()
    new_hash = _hash_password(new_password)
    new_secret = secrets.token_hex(32)
    with get_connection(db_path) as conn:
        for key, value in (
            ("admin_username", clean_user),
            ("admin_password_hash", new_hash),
            ("token_secret", new_secret),
        ):
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
    return True


def save_document(
    doc_id: str,
    original_filename: str,
    file_type: str,
    file_size: int,
    normalized_pdf_path: str,
    page_count: int,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert a normalized document record and return its representation."""
    created_at = _utc_now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, original_filename, file_type, file_size,
                normalized_pdf_path, page_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                original_filename,
                file_type,
                file_size,
                normalized_pdf_path,
                page_count,
                created_at,
            ),
        )
    return {
        "id": doc_id,
        "original_filename": original_filename,
        "file_type": file_type,
        "file_size": file_size,
        "normalized_pdf_path": normalized_pdf_path,
        "page_count": page_count,
        "created_at": created_at,
    }


def get_document(doc_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Fetch a document record by ID."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    return dict(row) if row else None


_ALLOWED_JOB_UPDATE_FIELDS = frozenset(
    {
        "status",
        "status_message",
        "queue_state",
        "started_at",
        "printing_until_ts",
        "confirm_deadline_ts",
        "completed_at",
        "payment_status",
        "payment_created_ts",
        "payment_deadline_ts",
        "payment_tx_id",
        "payment_verified_at",
        "payment_note",
        "receipt_path",
        "receipt_filename",
        "receipt_uploaded_at",
    }
)


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["selected_pages"] = json.loads(data.pop("selected_pages_json", "[]"))
    data["rotations"] = json.loads(data.pop("rotations_json", "{}"))
    data["color_pages"] = json.loads(data.pop("color_pages_json", "[]") or "[]")
    data["print_segments"] = json.loads(data.pop("segments_json", "[]") or "[]")
    data["bw_sheets"] = int(data.get("bw_sheets") or 0)
    data["color_sheets"] = int(data.get("color_sheets") or 0)
    data["estimated_seconds"] = int(data.get("estimated_seconds") or 0)
    data["client_token"] = str(data.get("client_token") or "")
    data["device_label"] = str(data.get("device_label") or "")
    data["client_ip"] = str(data.get("client_ip") or "")
    data["queue_state"] = str(data.get("queue_state") or "COMPLETED")
    data["started_at"] = str(data.get("started_at") or "")
    data["printing_until_ts"] = float(data.get("printing_until_ts") or 0.0)
    data["confirm_deadline_ts"] = float(data.get("confirm_deadline_ts") or 0.0)
    data["completed_at"] = str(data.get("completed_at") or "")
    data["payment_status"] = str(data.get("payment_status") or "NOT_REQUIRED")
    data["payment_created_ts"] = float(data.get("payment_created_ts") or 0.0)
    data["payment_deadline_ts"] = float(data.get("payment_deadline_ts") or 0.0)
    data["payment_tx_id"] = str(data.get("payment_tx_id") or "")
    data["payment_verified_at"] = str(data.get("payment_verified_at") or "")
    data["payment_note"] = str(data.get("payment_note") or "")
    data["receipt_path"] = str(data.get("receipt_path") or "")
    data["receipt_filename"] = str(data.get("receipt_filename") or "")
    data["receipt_uploaded_at"] = str(data.get("receipt_uploaded_at") or "")
    return data


def create_print_job(job: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    """Persist a new print job record."""
    created_at = job.get("created_at") or _utc_now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO print_jobs (
                id, document_id, original_filename, student_name,
                selected_pages_json, page_range_text, rotations_json,
                selected_page_count, copies, color_mode, duplex,
                orientation, pages_per_sheet, paper_size,
                total_printed_pages, physical_sheets, estimated_cost,
                estimated_seconds, color_pages_json, bw_sheets,
                color_sheets, segments_json, printer_name, printer_mode,
                status, status_message, output_pdf_path, created_at,
                client_token, device_label, client_ip, queue_state, started_at,
                printing_until_ts, confirm_deadline_ts, completed_at,
                payment_status, payment_created_ts, payment_deadline_ts,
                payment_tx_id, payment_verified_at, payment_note,
                receipt_path, receipt_filename, receipt_uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"],
                job["document_id"],
                job["original_filename"],
                job.get("student_name", ""),
                json.dumps(job["selected_pages"]),
                job["page_range_text"],
                json.dumps(job.get("rotations", {})),
                job["selected_page_count"],
                job["copies"],
                job["color_mode"],
                job["duplex"],
                job["orientation"],
                job["pages_per_sheet"],
                job["paper_size"],
                job["total_printed_pages"],
                job["physical_sheets"],
                job["estimated_cost"],
                int(job.get("estimated_seconds", 0) or 0),
                json.dumps(job.get("color_pages", [])),
                int(job.get("bw_sheets", 0) or 0),
                int(job.get("color_sheets", 0) or 0),
                json.dumps(job.get("print_segments", [])),
                job.get("printer_name", ""),
                job["printer_mode"],
                job["status"],
                job.get("status_message", ""),
                job["output_pdf_path"],
                created_at,
                job.get("client_token", ""),
                job.get("device_label", ""),
                job.get("client_ip", ""),
                job.get("queue_state", "COMPLETED"),
                job.get("started_at", ""),
                float(job.get("printing_until_ts", 0.0) or 0.0),
                float(job.get("confirm_deadline_ts", 0.0) or 0.0),
                job.get("completed_at", ""),
                job.get("payment_status", "NOT_REQUIRED"),
                float(job.get("payment_created_ts", 0.0) or 0.0),
                float(job.get("payment_deadline_ts", 0.0) or 0.0),
                job.get("payment_tx_id", ""),
                job.get("payment_verified_at", ""),
                job.get("payment_note", ""),
                job.get("receipt_path", ""),
                job.get("receipt_filename", ""),
                job.get("receipt_uploaded_at", ""),
            ),
        )
    stored = get_print_job(job["id"], db_path=db_path)
    assert stored is not None
    return stored


def list_print_jobs(limit: int = 100, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return print jobs ordered newest-first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM print_jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def get_print_job(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Fetch a single print job by ID."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM print_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return _row_to_job(row) if row else None


def count_unfinished_jobs_for_token(
    client_token: str,
    db_path: Path | None = None,
) -> int:
    """Count jobs belonging to client_token that are currently awaiting payment or in queue."""
    clean = (client_token or "").strip()
    if not clean:
        return 0
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM print_jobs
            WHERE client_token = ?
              AND queue_state IN ('AWAITING_PAYMENT', 'WAITING_IN_QUEUE', 'ACTIVE_PRINTING', 'AWAITING_CONFIRMATION')
            """,
            (clean,),
        ).fetchone()
    return int(row["cnt"] if row else 0)


def get_active_queue_job(db_path: Path | None = None) -> dict[str, Any] | None:
    """Return the job currently occupying the physical printer or awaiting student confirmation."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM print_jobs
            WHERE queue_state IN ('ACTIVE_PRINTING', 'AWAITING_CONFIRMATION')
            ORDER BY created_at ASC, rowid ASC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_job(row) if row else None


def list_waiting_queue_jobs(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return waiting jobs in strict FIFO submission order."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM print_jobs
            WHERE queue_state = 'WAITING_IN_QUEUE'
            ORDER BY created_at ASC, rowid ASC
            """
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def list_recent_completed_jobs(limit: int = 5, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return the most recently completed print jobs for live queue visibility."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM print_jobs
            WHERE queue_state = 'COMPLETED'
            ORDER BY COALESCE(NULLIF(completed_at, ''), created_at) DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_queue_fields(
    job_id: str,
    fields: dict[str, Any],
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Atomically update whitelisted queue and status columns for a print job."""
    clean_items = [(k, v) for k, v in fields.items() if k in _ALLOWED_JOB_UPDATE_FIELDS]
    if not clean_items:
        return get_print_job(job_id, db_path=db_path)
    assignments = ", ".join(f"{col} = ?" for col, _ in clean_items)
    values = [val for _, val in clean_items] + [job_id]
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE print_jobs SET {assignments} WHERE id = ?", values)
    return get_print_job(job_id, db_path=db_path)


def compute_job_queue_enrichment(
    job: dict[str, Any],
    active_job: dict[str, Any] | None,
    waiting_jobs: list[dict[str, Any]],
    now_ts: float | None = None,
) -> dict[str, int]:
    """Compute live queue position and countdown timers for a job snapshot."""
    now = time.time() if now_ts is None else now_ts
    q_state = job.get("queue_state") or "COMPLETED"
    remaining_print = (
        max(0, int(math.ceil(float(job.get("printing_until_ts") or 0.0) - now)))
        if q_state == "ACTIVE_PRINTING"
        else 0
    )
    confirm_rem = (
        max(0, int(math.ceil(float(job.get("confirm_deadline_ts") or 0.0) - now)))
        if q_state == "AWAITING_CONFIRMATION"
        else 0
    )
    payment_rem = (
        max(0, int(math.ceil(float(job.get("payment_deadline_ts") or 0.0) - now)))
        if q_state == "AWAITING_PAYMENT"
        else 0
    )

    queue_position = 0
    estimated_wait_seconds = 0
    if q_state == "WAITING_IN_QUEUE":
        idx = next((i for i, item in enumerate(waiting_jobs) if item["id"] == job["id"]), len(waiting_jobs))
        queue_position = idx + 1
        active_rem = 0
        if active_job and active_job.get("queue_state") == "ACTIVE_PRINTING":
            active_rem = max(0, int(math.ceil(float(active_job.get("printing_until_ts") or 0.0) - now)))
        ahead_wait = sum(int(w.get("estimated_seconds") or 0) for w in waiting_jobs[:idx])
        estimated_wait_seconds = active_rem + ahead_wait

    return {
        "queue_position": queue_position,
        "remaining_print_seconds": remaining_print,
        "confirm_remaining_seconds": confirm_rem,
        "payment_remaining_seconds": payment_rem,
        "estimated_wait_seconds": estimated_wait_seconds,
    }


def update_print_job_status(
    job_id: str,
    status: str,
    status_message: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Update status and message of an existing print job while syncing queue_state."""
    existing = get_print_job(job_id, db_path=db_path)
    if not existing:
        return None
    fields: dict[str, Any] = {
        "status": status,
        "status_message": status_message,
    }
    now = time.time()
    if status == "COMPLETED":
        fields["queue_state"] = "COMPLETED"
        fields["completed_at"] = _utc_now_iso()
        fields["printing_until_ts"] = 0.0
        fields["confirm_deadline_ts"] = 0.0
    elif status == "CANCELLED":
        fields["queue_state"] = "CANCELLED"
        fields["printing_until_ts"] = 0.0
        fields["confirm_deadline_ts"] = 0.0
    elif status == "ERROR":
        fields["queue_state"] = "ERROR"
        fields["printing_until_ts"] = 0.0
        fields["confirm_deadline_ts"] = 0.0
    elif status == "WAITING_IN_QUEUE":
        fields["queue_state"] = "WAITING_IN_QUEUE"
        fields["printing_until_ts"] = 0.0
        fields["confirm_deadline_ts"] = 0.0
    elif status == "AWAITING_CONFIRMATION":
        fields["queue_state"] = "AWAITING_CONFIRMATION"
    elif status == "AWAITING_PAYMENT":
        fields["queue_state"] = "AWAITING_PAYMENT"
        fields["printing_until_ts"] = 0.0
        fields["confirm_deadline_ts"] = 0.0
    elif existing.get("queue_state") not in {"ACTIVE_PRINTING", "AWAITING_CONFIRMATION"}:
        fields["queue_state"] = "ACTIVE_PRINTING"
        if not existing.get("started_at"):
            fields["started_at"] = _utc_now_iso()
        fields["printing_until_ts"] = now + max(1, int(existing.get("estimated_seconds") or 5))
        fields["confirm_deadline_ts"] = 0.0

    return update_job_queue_fields(job_id, fields, db_path=db_path)


def delete_print_job(job_id: str, db_path: Path | None = None) -> bool:
    """Delete a print job record and return True if a row was removed."""
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM print_jobs WHERE id = ?", (job_id,))
    return cur.rowcount > 0


def clear_all_print_jobs(db_path: Path | None = None) -> int:
    """Delete all print jobs from history and return count removed."""
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM print_jobs")
    return cur.rowcount


def get_admin_stats(db_path: Path | None = None) -> dict[str, int]:
    """Compute aggregated statistics across all print jobs."""
    today_prefix = datetime.now(timezone.utc).date().isoformat()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_jobs,
                COALESCE(SUM(total_printed_pages), 0) AS total_selected_pages,
                COALESCE(SUM(physical_sheets), 0) AS total_physical_sheets,
                COALESCE(SUM(estimated_cost), 0) AS total_revenue
            FROM print_jobs
            """
        ).fetchone()
        today_row = conn.execute(
            "SELECT COUNT(*) AS jobs_today FROM print_jobs WHERE created_at LIKE ?",
            (f"{today_prefix}%",),
        ).fetchone()

    return {
        "total_jobs": int(row["total_jobs"]),
        "total_selected_pages": int(row["total_selected_pages"]),
        "total_physical_sheets": int(row["total_physical_sheets"]),
        "total_revenue": int(row["total_revenue"]),
        "jobs_today": int(today_row["jobs_today"]),
    }


def record_agent_heartbeat(
    hostname: str,
    printers: list[dict[str, Any]],
    cpu_temp_c: float | None = None,
    db_path: Path | None = None,
) -> None:
    """Record Raspberry Pi print agent heartbeat, hostname, and attached printers."""
    now = _utc_now_iso()
    label = hostname.strip() or "raspberry-pi"
    if cpu_temp_c is not None:
        label = f"{label} ({cpu_temp_c:.1f}°C)"
    with get_connection(db_path) as conn:
        for key, value in (
            ("agent_last_seen", now),
            ("agent_hostname", label),
            ("agent_printers_json", json.dumps(printers)),
        ):
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )


def claim_next_agent_job(db_path: Path | None = None) -> dict[str, Any] | None:
    """Atomically claim the currently active job queued for the remote Raspberry Pi print agent."""
    with QUEUE_LOCK, get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM print_jobs
            WHERE status = 'QUEUED_FOR_AGENT' AND queue_state = 'ACTIVE_PRINTING'
            ORDER BY created_at ASC, rowid ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        job_id = row["id"]
        cur = conn.execute(
            """
            UPDATE print_jobs
            SET status = 'PRINTING_ON_PI',
                status_message = 'Raspberry Pi printer ko''prigi hujjatni yuklab oldi va chop etmoqda...'
            WHERE id = ? AND status = 'QUEUED_FOR_AGENT' AND queue_state = 'ACTIVE_PRINTING'
            """,
            (job_id,),
        )
        if cur.rowcount == 0:
            return None
        claimed = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(claimed) if claimed else None


def is_payment_tx_used(tx_uid: str, db_path: Path | None = None) -> bool:
    """Return True if a HUMO bot transaction UID was already claimed by a print job."""
    if not tx_uid:
        return False
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM used_payment_transactions WHERE tx_uid = ?",
            (tx_uid,),
        ).fetchone()
    return row is not None


def list_used_payment_txs(limit: int = 50, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return recently claimed HUMO payment transactions for Admin monitoring."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM used_payment_transactions
            ORDER BY claimed_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def claim_payment_transaction(
    tx_uid: str,
    job_id: str,
    amount_uzs: int,
    card_mask: str = "",
    msg_date: str = "",
    raw_text: str = "",
    db_path: Path | None = None,
) -> bool:
    """Atomically claim a @HUMOcardbot transaction UID so it can never be reused."""
    if not tx_uid:
        return False
    now = _utc_now_iso()
    with QUEUE_LOCK, get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO used_payment_transactions (
                tx_uid, job_id, amount_uzs, card_mask, msg_date, raw_text, claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tx_uid, job_id, int(amount_uzs), card_mask, msg_date, raw_text, now),
        )
    return cur.rowcount > 0
