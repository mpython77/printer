"""SQLite database initialization and CRUD helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.config import (
    DB_PATH,
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
    """Yield a SQLite connection configured with dict-like Row access."""
    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False)
    conn.row_factory = sqlite3.Row
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

        defaults = {
            "admin_username": "admin",
            "admin_password_hash": _hash_password("admin123"),
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
            "agent_api_key": DEFAULT_AGENT_KEY,
            "agent_last_seen": "",
            "agent_hostname": "",
            "agent_printers_json": "[]",
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
    }
    now = _utc_now_iso()
    with get_connection(db_path) as conn:
        for src_key, db_key in key_map.items():
            if src_key in updates and updates[src_key] is not None:
                conn.execute(
                    """
                    INSERT INTO system_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (db_key, str(updates[src_key]), now),
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
    with get_connection(db_path) as conn:
        for key, value in (("admin_username", clean_user), ("admin_password_hash", new_hash)):
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


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["selected_pages"] = json.loads(data.pop("selected_pages_json", "[]"))
    data["rotations"] = json.loads(data.pop("rotations_json", "{}"))
    data["color_pages"] = json.loads(data.pop("color_pages_json", "[]") or "[]")
    data["print_segments"] = json.loads(data.pop("segments_json", "[]") or "[]")
    data["bw_sheets"] = int(data.get("bw_sheets") or 0)
    data["color_sheets"] = int(data.get("color_sheets") or 0)
    data["estimated_seconds"] = int(data.get("estimated_seconds") or 0)
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
                status, status_message, output_pdf_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
    stored = get_print_job(job["id"], db_path=db_path)
    assert stored is not None
    return stored


def list_print_jobs(limit: int = 100, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return print jobs ordered newest-first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM print_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def get_print_job(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Fetch a single print job by ID."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM print_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return _row_to_job(row) if row else None


def update_print_job_status(
    job_id: str,
    status: str,
    status_message: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Update status and message of an existing print job."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE print_jobs SET status = ?, status_message = ? WHERE id = ?",
            (status, status_message, job_id),
        )
    return get_print_job(job_id, db_path=db_path)


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
    """Atomically claim the oldest job queued for the remote Raspberry Pi print agent."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM print_jobs
            WHERE status = 'QUEUED_FOR_AGENT'
            ORDER BY created_at ASC
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
            WHERE id = ? AND status = 'QUEUED_FOR_AGENT'
            """,
            (job_id,),
        )
        if cur.rowcount == 0:
            return None
        claimed = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(claimed) if claimed else None
