"""Configuration settings for TLG SmartPrint."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
NORMALIZED_DIR = STORAGE_DIR / "normalized"
JOBS_DIR = STORAGE_DIR / "jobs"
SAMPLES_DIR = STORAGE_DIR / "samples"
DB_PATH = STORAGE_DIR / "smartprint.db"

# Printer mode:
#   "DRY_RUN"         -> Processes PDFs and stores jobs in queue without touching physical printer.
#   "LINUX_CUPS"      -> Sends sliced PDF directly to local Linux/Raspberry Pi printer via CUPS (lp).
#   "REMOTE_AGENT"    -> Queues jobs for a remote Raspberry Pi print bridge polling over HTTPS/HTTP.
#   "WINDOWS_SPOOLER" -> Sends sliced PDF to local Windows printer via win32print.
PRINTER_MODE = os.environ.get("TLG_PRINTER_MODE", "DRY_RUN").strip().upper()
if PRINTER_MODE not in {"DRY_RUN", "LINUX_CUPS", "REMOTE_AGENT", "WINDOWS_SPOOLER"}:
    PRINTER_MODE = "DRY_RUN"

DEFAULT_PRINTER_NAME = os.environ.get("TLG_PRINTER_NAME", "").strip()
DEFAULT_AGENT_KEY = os.environ.get("TLG_AGENT_KEY", "tlg-pi-secret-2026").strip()

# Pricing per physical sheet (UZS)
PRICE_BW_SIMPLEX = 400
PRICE_BW_DUPLEX = 700
PRICE_COLOR_SIMPLEX = 1000
PRICE_COLOR_DUPLEX = 1800

# Default printing duration per physical sheet (seconds)
SECONDS_BW_PER_SHEET = 7
SECONDS_COLOR_PER_SHEET = 14
WARMUP_SECONDS = 5

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".txt",
    ".md",
    ".csv",
}

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def ensure_directories() -> None:
    """Create required storage directories if they do not exist."""
    for directory in (STORAGE_DIR, UPLOADS_DIR, NORMALIZED_DIR, JOBS_DIR, SAMPLES_DIR):
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()
