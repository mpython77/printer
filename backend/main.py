"""FastAPI application for TLG SmartPrint."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import mimetypes
import re
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pypdf import PdfReader

from backend.config import (
    ALLOWED_EXTENSIONS,
    FRONTEND_DIR,
    JOBS_DIR,
    MAX_UPLOAD_SIZE_BYTES,
    NORMALIZED_DIR,
    SAMPLES_DIR,
    UPLOADS_DIR,
    ensure_directories,
)
from backend.database import (
    QUEUE_LOCK,
    claim_next_agent_job,
    clear_all_print_jobs,
    compute_job_queue_enrichment,
    count_unfinished_jobs_for_token,
    create_print_job,
    delete_print_job,
    get_active_queue_job,
    get_admin_stats,
    get_document,
    get_print_job,
    get_settings,
    get_token_secret,
    init_db,
    list_print_jobs,
    list_recent_completed_jobs,
    list_waiting_queue_jobs,
    record_agent_heartbeat,
    save_document,
    update_admin_credentials,
    update_job_queue_fields,
    update_print_job_status,
    update_settings,
    verify_admin_credentials,
)
from backend.humo_verifier import (
    admin_disconnect_telegram,
    admin_send_telegram_code,
    admin_verify_telegram_code,
    fetch_recent_humo_topups,
    get_telegram_status,
    normalize_bot_username,
    verify_and_claim_humo_payment,
)
from backend.models import (
    AdminDashboardResponse,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminPasswordUpdateRequest,
    AdminSettingsPayload,
    AdminSettingsUpdateRequest,
    AdminStats,
    AgentHeartbeatRequest,
    AgentJobReportRequest,
    DocumentResponse,
    JobConfirmRequest,
    JobStatusUpdateRequest,
    LiveQueueStatusResponse,
    PaymentConfigInfo,
    PricingInfo,
    PrinterInfo,
    PrintJobCreateRequest,
    PrintJobResponse,
    PrintSegmentInfo,
    QueuePublicJobItem,
    SystemStatusResponse,
    TelegramSendCodeRequest,
    TelegramStatusInfo,
    TelegramVerifyCodeRequest,
)
from backend.services.converter import ensure_sample_pdf, normalize_to_pdf
from backend.services.pdf_processor import (
    calculate_print_metrics,
    format_page_range,
    parse_page_range,
    slice_pdf_for_print,
)
from backend.services.printer_adapter import (
    discover_all_printers,
    get_active_printer_adapter,
    get_cups_spooler_status,
    get_spooler_status,
)

ADMIN_TOKEN_TTL_SECONDS = 12 * 3600

ensure_directories()
init_db()

app = FastAPI(
    title="TLG SmartPrint API",
    description="O'quvchilar uchun hujjatlarni yuklash, bet tanlash va avtomatlashtirilgan chop etish tizimi",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_LOGIN_LOCK = threading.Lock()
_LOGIN_FAILURES: dict[str, list[float]] = {}
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_FAILURES = 5


def reset_security_limiter() -> None:
    """Clear tracked failed admin login attempts (used in unit tests)."""
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.clear()


def _extract_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return "127.0.0.1"


def _check_login_rate_limit(client_ip: str) -> None:
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SECONDS
    with _LOGIN_LOCK:
        attempts = [t for t in _LOGIN_FAILURES.get(client_ip, []) if t >= cutoff]
        if attempts:
            _LOGIN_FAILURES[client_ip] = attempts
        else:
            _LOGIN_FAILURES.pop(client_ip, None)
        if len(attempts) >= _LOGIN_MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="Juda ko'p noto'g'ri urinishlar. Iltimos, 5 daqiqadan so'ng qayta urinib ko'ring.",
            )


def _record_login_failure(client_ip: str) -> None:
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SECONDS
    with _LOGIN_LOCK:
        attempts = [t for t in _LOGIN_FAILURES.get(client_ip, []) if t >= cutoff]
        attempts.append(now)
        _LOGIN_FAILURES[client_ip] = attempts


def _clear_login_failures(client_ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.pop(client_ip, None)


def _sanitize_filename(filename: str | None, fallback: str = "hujjat.pdf") -> str:
    """Strip path traversal, quotes, control chars, and leading dashes from uploaded filenames."""
    base = Path((filename or "").replace("\\", "/")).name
    clean = re.sub(r'[\x00-\x1f"\\<>|:*?]+', "_", base).strip()
    clean = clean.lstrip("-.").strip()
    if not clean:
        clean = fallback
    if len(clean) > 120:
        stem = Path(clean).stem[:90]
        suffix = Path(clean).suffix[:20]
        clean = f"{stem}{suffix}" or fallback
    return clean


@app.middleware("http")
async def _security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def _issue_admin_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + ADMIN_TOKEN_TTL_SECONDS}
    raw_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    secret = get_token_secret().encode("utf-8")
    sig = hmac.new(secret, raw_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw_b64}.{sig}"


def _verify_admin_token(token: str) -> str:
    if "." not in token:
        raise HTTPException(status_code=401, detail="Admin tokeni noto'g'ri.")
    raw_b64, sig = token.split(".", 1)
    secret = get_token_secret().encode("utf-8")
    expected_sig = hmac.new(secret, raw_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=401, detail="Admin sessiyasi yaroqsiz.")
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw_b64.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Tokenni o'qib bo'lmadi.") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Admin sessiyasi muddati tugagan. Qayta kiring.")
    return str(payload.get("sub", "admin"))


def require_admin(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin huquqi talab qilinadi.")
    token = authorization.removeprefix("Bearer ").strip()
    return _verify_admin_token(token)


def require_admin_header_or_query(
    authorization: str = Header(default=""),
    token: str = "",
) -> str:
    if authorization.startswith("Bearer "):
        return _verify_admin_token(authorization.removeprefix("Bearer ").strip())
    if token.strip():
        return _verify_admin_token(token.strip())
    raise HTTPException(status_code=401, detail="Admin huquqi talab qilinadi.")


def _doc_to_response(doc: dict) -> DocumentResponse:
    return DocumentResponse(
        id=doc["id"],
        original_filename=doc["original_filename"],
        file_type=doc["file_type"],
        file_size=doc["file_size"],
        page_count=doc["page_count"],
        pdf_url=f"/api/documents/{doc['id']}/pdf",
        created_at=doc["created_at"],
    )


CONFIRM_TIMEOUT_SECONDS = 90


def _build_device_id(client_token: str, client_ip: str = "", user_agent: str = "") -> str:
    seed = (client_token or "").strip() or f"{client_ip}:{user_agent}" or "unknown"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:4].upper()
    return f"#{digest}"


def _detect_device_label(user_agent: str, client_hint: str = "", device_id: str = "") -> str:
    hint = (client_hint or "").strip()
    if hint:
        base = hint[:100]
    else:
        ua = (user_agent or "").lower()
        if "iphone" in ua:
            os_part = "📱 iPhone"
        elif "ipad" in ua:
            os_part = "📱 iPad"
        elif "android" in ua:
            os_part = "📱 Android Telefon"
        elif "windows" in ua:
            os_part = "💻 Windows Kompyuter"
        elif "macintosh" in ua or "mac os" in ua:
            os_part = "💻 Mac Kompyuter"
        elif "linux" in ua:
            os_part = "💻 Linux Kompyuter"
        else:
            os_part = "🖥️ Qurilma"

        if "edg/" in ua:
            browser = "Edge"
        elif "chrome/" in ua or "crios/" in ua:
            browser = "Chrome"
        elif "firefox/" in ua or "fxios/" in ua:
            browser = "Firefox"
        elif "safari/" in ua:
            browser = "Safari"
        else:
            browser = ""

        base = f"{os_part} • {browser}" if browser else os_part

    if device_id and device_id not in base:
        return f"{base} ({device_id})"
    return base


def _is_job_owner(job: dict, caller_token: str) -> bool:
    expected = (job.get("client_token") or "").strip()
    caller = (caller_token or "").strip()
    return bool(expected and caller and hmac.compare_digest(expected, caller))


def _job_access_key(job_id: str, client_token: str) -> str:
    """Derive a signed short access key tying job PDF downloads to the owner's session."""
    secret = get_token_secret().encode("utf-8")
    msg = f"pdf:{job_id}:{(client_token or '').strip()}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:24]


def _is_valid_admin_auth(authorization: str) -> bool:
    if not authorization.startswith("Bearer "):
        return False
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return False
    try:
        _verify_admin_token(token)
        return True
    except HTTPException:
        return False


def _is_valid_agent_auth(x_agent_key: str) -> bool:
    expected = get_settings().get("agent_api_key", "").strip()
    provided = (x_agent_key or "").strip()
    return bool(expected and provided and hmac.compare_digest(provided, expected))


def _authorize_job_pdf_access(
    job: dict,
    access_key: str = "",
    x_client_token: str = "",
    client_token: str = "",
    authorization: str = "",
    x_agent_key: str = "",
) -> None:
    """Enforce owner/admin/agent access control and block student PDF downloads before payment."""
    if _is_valid_admin_auth(authorization) or _is_valid_agent_auth(x_agent_key):
        return

    caller_tok = (x_client_token or client_token or "").strip()
    expected_key = _job_access_key(job["id"], job.get("client_token", ""))
    key_ok = bool(access_key and hmac.compare_digest(access_key.strip(), expected_key))
    owner_ok = _is_job_owner(job, caller_tok)
    if not (key_ok or owner_ok):
        raise HTTPException(
            status_code=403,
            detail="Boshqa foydalanuvchining chop etish faylini ko'rish taqiqlanadi.",
        )

    if job.get("queue_state") == "AWAITING_PAYMENT":
        raise HTTPException(
            status_code=403,
            detail="To'lov tasdiqlanmaguncha tayyor PDF faylni yuklab olish mumkin emas.",
        )


def _validate_receipt_file_bytes(content: bytes, ext: str) -> None:
    """Validate uploaded receipt magic bytes and structure so spoofed scripts are rejected."""
    try:
        if ext == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF signature")
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) < 1:
                raise ValueError("Empty PDF")
            return
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        with Image.open(io.BytesIO(content)) as img2:
            if (img2.format or "").upper() not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image format")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Chek fayli shikastlangan yoki soxta formatda. Haqiqiy rasm (JPG/PNG/WEBP) yoki PDF yuklang.",
        ) from exc


def _job_to_response(
    job: dict,
    active_job: dict | None = None,
    waiting_jobs: list[dict] | None = None,
    now_ts: float | None = None,
    caller_token: str = "",
    include_secret_token: bool = False,
) -> PrintJobResponse:
    if active_job is None and waiting_jobs is None and job.get("queue_state") in {
        "ACTIVE_PRINTING",
        "AWAITING_CONFIRMATION",
        "WAITING_IN_QUEUE",
    }:
        active_job = get_active_queue_job()
        waiting_jobs = list_waiting_queue_jobs()
    enrich = compute_job_queue_enrichment(
        job, active_job, waiting_jobs or [], now_ts=now_ts
    )
    dev_id = _build_device_id(job.get("client_token", ""), job.get("client_ip", ""))
    is_mine = include_secret_token or _is_job_owner(job, caller_token)
    access_suffix = (
        f"?access_key={_job_access_key(job['id'], job.get('client_token', ''))}"
        if is_mine
        else ""
    )
    signed_segments = [
        PrintSegmentInfo(
            **{
                **seg,
                "pdf_url": f"/api/print-jobs/{job['id']}/segments/{seg['segment_index']}/pdf{access_suffix}",
            }
        )
        for seg in job.get("print_segments", [])
    ]
    return PrintJobResponse(
        id=job["id"],
        document_id=job["document_id"],
        original_filename=job["original_filename"],
        student_name=job["student_name"],
        selected_pages=job["selected_pages"],
        page_range_text=job["page_range_text"],
        rotations=job["rotations"],
        selected_page_count=job["selected_page_count"],
        copies=job["copies"],
        color_mode=job["color_mode"],
        color_pages=job.get("color_pages", []),
        bw_sheets=int(job.get("bw_sheets", 0) or 0),
        color_sheets=int(job.get("color_sheets", 0) or 0),
        print_segments=signed_segments,
        duplex=job["duplex"],
        orientation=job["orientation"],
        pages_per_sheet=job["pages_per_sheet"],
        paper_size=job["paper_size"],
        total_printed_pages=job["total_printed_pages"],
        physical_sheets=job["physical_sheets"],
        estimated_cost=job["estimated_cost"],
        estimated_seconds=int(job.get("estimated_seconds", 0) or 0),
        printer_name=job["printer_name"],
        printer_mode=job["printer_mode"],
        status=job["status"],
        status_message=job["status_message"],
        pdf_url=f"/api/print-jobs/{job['id']}/pdf{access_suffix}",
        original_pdf_url=f"/api/documents/{job['document_id']}/pdf",
        created_at=job["created_at"],
        client_token=job.get("client_token", "") if is_mine else "",
        device_id=dev_id,
        device_label=job.get("device_label") or f"Qurilma ({dev_id})",
        client_ip=job.get("client_ip", "") if include_secret_token else "",
        is_mine=is_mine,
        queue_state=job.get("queue_state", "COMPLETED"),
        queue_position=enrich["queue_position"],
        remaining_print_seconds=enrich["remaining_print_seconds"],
        confirm_remaining_seconds=enrich["confirm_remaining_seconds"],
        payment_remaining_seconds=enrich["payment_remaining_seconds"],
        estimated_wait_seconds=enrich["estimated_wait_seconds"],
        started_at=job.get("started_at", ""),
        completed_at=job.get("completed_at", ""),
        payment_status=job.get("payment_status", "NOT_REQUIRED"),
        payment_deadline_ts=float(job.get("payment_deadline_ts") or 0.0),
        payment_tx_id=job.get("payment_tx_id", ""),
        payment_verified_at=job.get("payment_verified_at", ""),
        payment_note=job.get("payment_note", ""),
        has_receipt=bool(job.get("receipt_path")),
        receipt_filename=job.get("receipt_filename", ""),
        receipt_uploaded_at=job.get("receipt_uploaded_at", ""),
        receipt_url=f"/api/admin/print-jobs/{job['id']}/receipt" if job.get("receipt_path") else "",
    )


def _job_to_public_item(
    job: dict,
    active_job: dict | None,
    waiting_jobs: list[dict],
    now_ts: float,
    caller_token: str = "",
) -> QueuePublicJobItem:
    enrich = compute_job_queue_enrichment(job, active_job, waiting_jobs, now_ts=now_ts)
    dev_id = _build_device_id(job.get("client_token", ""), job.get("client_ip", ""))
    is_mine = _is_job_owner(job, caller_token)
    return QueuePublicJobItem(
        id=job["id"],
        student_name=job.get("student_name") or "Ismsiz foydalanuvchi",
        original_filename=job["original_filename"],
        page_range_text=job["page_range_text"],
        selected_page_count=int(job["selected_page_count"]),
        copies=int(job["copies"]),
        color_mode=job["color_mode"],
        duplex=job["duplex"],
        physical_sheets=int(job["physical_sheets"]),
        bw_sheets=int(job.get("bw_sheets", 0) or 0),
        color_sheets=int(job.get("color_sheets", 0) or 0),
        estimated_seconds=int(job.get("estimated_seconds", 0) or 0),
        queue_state=job.get("queue_state", "COMPLETED"),
        status=job["status"],
        status_message=job.get("status_message", ""),
        queue_position=enrich["queue_position"],
        remaining_print_seconds=enrich["remaining_print_seconds"],
        confirm_remaining_seconds=enrich["confirm_remaining_seconds"],
        estimated_wait_seconds=enrich["estimated_wait_seconds"],
        is_mine=is_mine,
        device_id=dev_id,
        device_label=job.get("device_label") or f"Qurilma ({dev_id})",
        printer_name=job.get("printer_name") or "",
        printer_mode=job.get("printer_mode") or "",
        created_at=job["created_at"],
        started_at=job.get("started_at", ""),
        completed_at=job.get("completed_at", ""),
    )


def _dispatch_job_to_printer(job: dict) -> tuple[str, dict]:
    settings = get_settings()
    adapter = get_active_printer_adapter(mode=settings["printer_mode"])
    target_printer = (job.get("printer_name") or "").strip() or settings["default_printer_name"]
    dispatch_stub = {
        **job,
        "printer_name": target_printer,
        "printer_mode": adapter.mode_name,
    }
    result = adapter.submit_job(dispatch_stub, Path(job["output_pdf_path"]))
    return adapter.mode_name, result


def _promote_next_waiting_job(now_ts: float) -> dict | None:
    waiting = list_waiting_queue_jobs()
    if not waiting:
        return None
    nxt = waiting[0]
    _mode_name, dispatch_result = _dispatch_job_to_printer(nxt)
    started_at = datetime.now(timezone.utc).isoformat()
    duration = max(1, int(nxt.get("estimated_seconds") or 5))
    return update_job_queue_fields(
        nxt["id"],
        {
            "queue_state": "ACTIVE_PRINTING",
            "status": dispatch_result["status"],
            "status_message": dispatch_result["status_message"],
            "started_at": started_at,
            "printing_until_ts": now_ts + duration,
            "confirm_deadline_ts": 0.0,
        },
    )


def _tick_and_advance_queue(now_ts: float | None = None) -> tuple[dict | None, list[dict]]:
    """Advance queue state transitions safely under QUEUE_LOCK and promote next waiting job."""
    with QUEUE_LOCK:
        now = time.time() if now_ts is None else now_ts
        active = get_active_queue_job()
        if active:
            q_state = active.get("queue_state")
            print_until = float(active.get("printing_until_ts") or 0.0)
            confirm_until = float(active.get("confirm_deadline_ts") or 0.0)
            if q_state == "ACTIVE_PRINTING" and print_until > 0 and now >= print_until:
                active = update_job_queue_fields(
                    active["id"],
                    {
                        "queue_state": "AWAITING_CONFIRMATION",
                        "confirm_deadline_ts": now + CONFIRM_TIMEOUT_SECONDS,
                        "status_message": "Taxminiy chiqish vaqti tugadi. Qog'ozlar chiqqanini tasdiqlang!",
                    },
                )
            elif q_state == "AWAITING_CONFIRMATION" and confirm_until > 0 and now >= confirm_until:
                update_job_queue_fields(
                    active["id"],
                    {
                        "queue_state": "COMPLETED",
                        "status": "COMPLETED",
                        "status_message": "Tasdiqlash vaqti tugagani sababli navbat avtomatik yopildi.",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "printing_until_ts": 0.0,
                        "confirm_deadline_ts": 0.0,
                    },
                )
                active = None

        if active is None:
            active = _promote_next_waiting_job(now)

        waiting = list_waiting_queue_jobs()
        return active, waiting


def _authorize_client_action(job: dict, provided_token: str) -> None:
    expected = (job.get("client_token") or "").strip()
    provided = (provided_token or "").strip()
    if expected and (not provided or not hmac.compare_digest(expected, provided)):
        raise HTTPException(
            status_code=403,
            detail="Faqat ushbu buyurtmani yuborgan qurilma/foydalanuvchi bu amalni bajarishi mumkin.",
        )


def _settings_to_payload(settings: dict) -> AdminSettingsPayload:
    return AdminSettingsPayload(
        admin_username=settings["admin_username"],
        bw_simplex=settings["bw_simplex"],
        bw_duplex=settings["bw_duplex"],
        color_simplex=settings["color_simplex"],
        color_duplex=settings["color_duplex"],
        seconds_bw_per_sheet=settings.get("seconds_bw_per_sheet", 7),
        seconds_color_per_sheet=settings.get("seconds_color_per_sheet", 14),
        warmup_seconds=settings.get("warmup_seconds", 5),
        printer_mode=settings["printer_mode"],
        default_printer_name=settings["default_printer_name"],
        agent_api_key=settings.get("agent_api_key", ""),
        agent_last_seen=settings.get("agent_last_seen", ""),
        agent_hostname=settings.get("agent_hostname", ""),
        payment_enabled=bool(settings.get("payment_enabled", True)),
        payment_card_number=settings.get("payment_card_number", ""),
        payment_card_holder=settings.get("payment_card_holder", ""),
        payment_window_seconds=int(settings.get("payment_window_seconds", 120)),
        telegram_bot_username=settings.get("telegram_bot_username", "@HUMOcardbot"),
    )


def require_agent_key(x_agent_key: str = Header(default="")) -> str:
    expected = get_settings().get("agent_api_key", "").strip()
    provided = x_agent_key.strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Raspberry Pi Agent kaliti (X-Agent-Key) noto'g'ri.",
        )
    return provided


_MODE_DESCRIPTIONS = {
    "LINUX_CUPS": "Jonli printer rejimi (Raspberry Pi / Linux CUPS faol)",
    "REMOTE_AGENT": "Bulut + Raspberry Pi printer ko'prigi faol (REMOTE_AGENT)",
    "WINDOWS_SPOOLER": "Jonli printer rejimi (Windows Spooler faol)",
    "DRY_RUN": "Xavfsiz test rejimi (DRY_RUN) — Printer keyin ulanadi, jismoniy printerga yuborilmaydi",
}


@app.get("/api/system-status", response_model=SystemStatusResponse)
def system_status() -> SystemStatusResponse:
    settings = get_settings()
    printers = [PrinterInfo(**p) for p in discover_all_printers(settings.get("agent_printers"))]
    printer_mode = settings["printer_mode"]
    hardware_connected = printer_mode in {"LINUX_CUPS", "REMOTE_AGENT", "WINDOWS_SPOOLER"}
    mode_description = _MODE_DESCRIPTIONS.get(printer_mode, _MODE_DESCRIPTIONS["DRY_RUN"])
    tg_status = get_telegram_status(check_remote=False)
    return SystemStatusResponse(
        printer_mode=printer_mode,
        hardware_connected=hardware_connected,
        default_printer_name=settings["default_printer_name"],
        mode_description=mode_description,
        printers=printers,
        pricing=PricingInfo(
            bw_simplex=settings["bw_simplex"],
            bw_duplex=settings["bw_duplex"],
            color_simplex=settings["color_simplex"],
            color_duplex=settings["color_duplex"],
            seconds_bw_per_sheet=settings.get("seconds_bw_per_sheet", 7),
            seconds_color_per_sheet=settings.get("seconds_color_per_sheet", 14),
            warmup_seconds=settings.get("warmup_seconds", 5),
        ),
        payment=PaymentConfigInfo(
            enabled=bool(settings.get("payment_enabled", True)),
            card_number=settings.get("payment_card_number", ""),
            card_holder=settings.get("payment_card_holder", ""),
            window_seconds=int(settings.get("payment_window_seconds", 120)),
            bot_username=normalize_bot_username(settings.get("telegram_bot_username") or "@HUMOcardbot"),
            telegram_connected=bool(tg_status.get("connected")),
        ),
    )


@app.post("/api/documents/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    original_filename = _sanitize_filename(file.filename, fallback="hujjat.pdf")
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Qo'llab-quvvatlanmaydigan fayl formati ({ext}). Ruxsat etilgan: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Yuklangan fayl bo'sh.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Fayl hajmi 50 MB dan oshmasligi kerak.",
        )

    doc_id = uuid.uuid4().hex[:12]
    safe_raw_path = UPLOADS_DIR / f"{doc_id}{ext}"
    normalized_pdf_path = NORMALIZED_DIR / f"{doc_id}.pdf"

    safe_raw_path.write_bytes(content)

    try:
        page_count = normalize_to_pdf(safe_raw_path, original_filename, normalized_pdf_path)
    except Exception as exc:
        safe_raw_path.unlink(missing_ok=True)
        normalized_pdf_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"Hujjatni o'qib bo'lmadi: {exc}",
        ) from exc

    doc = save_document(
        doc_id=doc_id,
        original_filename=original_filename,
        file_type=ext.lstrip("."),
        file_size=len(content),
        normalized_pdf_path=str(normalized_pdf_path),
        page_count=page_count,
    )
    return _doc_to_response(doc)


@app.post("/api/documents/sample", response_model=DocumentResponse)
def load_sample_document() -> DocumentResponse:
    sample_path = ensure_sample_pdf(SAMPLES_DIR)
    doc_id = uuid.uuid4().hex[:12]
    normalized_pdf_path = NORMALIZED_DIR / f"{doc_id}.pdf"
    shutil.copyfile(sample_path, normalized_pdf_path)
    page_count = normalize_to_pdf(sample_path, sample_path.name, normalized_pdf_path)

    doc = save_document(
        doc_id=doc_id,
        original_filename="Namuna_Oquv_Qollanma_8bet.pdf",
        file_type="pdf",
        file_size=sample_path.stat().st_size,
        normalized_pdf_path=str(normalized_pdf_path),
        page_count=page_count,
    )
    return _doc_to_response(doc)


@app.get("/api/documents/{doc_id}", response_model=DocumentResponse)
def fetch_document(doc_id: str) -> DocumentResponse:
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi.")
    return _doc_to_response(doc)


@app.get("/api/documents/{doc_id}/pdf")
def serve_document_pdf(doc_id: str) -> FileResponse:
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi.")
    pdf_path = Path(doc["normalized_pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF fayl diskda topilmadi.")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc["id"]}.pdf"'},
    )


@app.post("/api/print-jobs", response_model=PrintJobResponse)
def submit_print_job(
    payload: PrintJobCreateRequest,
    request: Request,
    x_client_token: str = Header(default=""),
) -> PrintJobResponse:
    doc = get_document(payload.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi.")

    max_pages = int(doc["page_count"])
    selected_pages = sorted({p for p in payload.selected_pages if 1 <= p <= max_pages})

    if not selected_pages and payload.page_range_text.strip():
        try:
            selected_pages = parse_page_range(payload.page_range_text, max_pages)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not selected_pages:
        raise HTTPException(
            status_code=400,
            detail="Chop etish uchun kamida bitta bet tanlanishi kerak.",
        )

    settings = get_settings()
    range_text = format_page_range(selected_pages)

    color_pages = sorted({p for p in payload.color_pages if p in selected_pages})
    if not color_pages and payload.color_pages_text.strip():
        try:
            parsed_cp = parse_page_range(payload.color_pages_text, max_pages)
            color_pages = [p for p in parsed_cp if p in selected_pages]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Rangli betlar xatosi: {exc}") from exc

    effective_color_mode = payload.color_mode
    if effective_color_mode == "mixed":
        if not color_pages:
            effective_color_mode = "bw"
        elif set(color_pages) == set(selected_pages):
            effective_color_mode = "color"
            color_pages = list(selected_pages)
    elif effective_color_mode == "color":
        color_pages = list(selected_pages)
    else:
        color_pages = []

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_pdf_path = job_dir / "print_ready.pdf"

    try:
        sliced_count = slice_pdf_for_print(
            source_pdf_path=Path(doc["normalized_pdf_path"]),
            output_pdf_path=output_pdf_path,
            selected_pages=selected_pages,
            rotations=payload.rotations,
            pages_per_sheet=payload.pages_per_sheet,
            orientation=payload.orientation,
            paper_size=payload.paper_size,
            color_mode=effective_color_mode,
            color_pages=color_pages,
            duplex=payload.duplex,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Tanlangan betlarni ajratishda xatolik: {exc}",
        ) from exc

    metrics = calculate_print_metrics(
        selected_page_count=sliced_count,
        copies=payload.copies,
        color_mode=effective_color_mode,
        duplex=payload.duplex,
        pages_per_sheet=payload.pages_per_sheet,
        pricing=settings,
        selected_pages=selected_pages,
        color_pages=color_pages,
    )

    print_segments = [
        {
            "segment_index": seg["segment_index"],
            "color_mode": seg["color_mode"],
            "sheet_count": seg["sheet_count"],
            "page_range_text": seg["page_range_text"],
            "pdf_filename": seg["pdf_filename"],
            "pdf_url": f"/api/print-jobs/{job_id}/segments/{seg['segment_index']}/pdf",
        }
        for seg in metrics.get("segments", [])
    ]

    effective_token = (payload.client_token or x_client_token or "").strip() or f"stu_{secrets.token_hex(10)}"
    if count_unfinished_jobs_for_token(effective_token) >= 3:
        raise HTTPException(
            status_code=429,
            detail="Sizda allaqachon 3 ta yakunlanmagan buyurtma mavjud. Yangi buyurtma berishdan oldin ularni yakunlang yoki bekor qiling.",
        )
    client_ip = _extract_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    dev_id = _build_device_id(effective_token, client_ip, user_agent)
    dev_label = _detect_device_label(user_agent, payload.device_label, dev_id)

    job_stub = {
        "id": job_id,
        "document_id": doc["id"],
        "original_filename": doc["original_filename"],
        "student_name": payload.student_name.strip(),
        "client_token": effective_token,
        "device_label": dev_label,
        "client_ip": client_ip,
        "selected_pages": selected_pages,
        "page_range_text": range_text,
        "rotations": payload.rotations,
        "selected_page_count": sliced_count,
        "copies": payload.copies,
        "color_mode": effective_color_mode,
        "color_pages": color_pages,
        "bw_sheets": metrics["bw_sheets"],
        "color_sheets": metrics["color_sheets"],
        "print_segments": print_segments,
        "duplex": payload.duplex,
        "orientation": payload.orientation,
        "pages_per_sheet": payload.pages_per_sheet,
        "paper_size": payload.paper_size,
        "total_printed_pages": metrics["total_printed_pages"],
        "physical_sheets": metrics["physical_sheets"],
        "estimated_cost": metrics["estimated_cost"],
        "estimated_seconds": metrics["estimated_seconds"],
        "printer_name": "",
        "printer_mode": settings["printer_mode"],
        "output_pdf_path": str(output_pdf_path),
    }

    with QUEUE_LOCK:
        now = time.time()
        active_job, waiting_jobs = _tick_and_advance_queue(now_ts=now)
        live_settings = get_settings()
        adapter = get_active_printer_adapter(mode=live_settings["printer_mode"])
        default_fallback = (
            "Raspberry Pi CUPS"
            if adapter.mode_name == "REMOTE_AGENT"
            else "Virtual Test Printer"
            if adapter.mode_name == "DRY_RUN"
            else "Standart Printer"
        )
        requested_printer = payload.printer_name.strip()
        allowed_printers = {
            str(p.get("name", "")).strip()
            for p in discover_all_printers(live_settings.get("agent_printers"))
            if p.get("name")
        }
        if live_settings.get("default_printer_name"):
            allowed_printers.add(str(live_settings["default_printer_name"]).strip())
        target_printer = (
            requested_printer
            if requested_printer and requested_printer in allowed_printers
            else (live_settings["default_printer_name"] or default_fallback)
        )
        job_stub["printer_name"] = target_printer
        job_stub["printer_mode"] = adapter.mode_name

        if bool(live_settings.get("payment_enabled", True)) and int(metrics["estimated_cost"] or 0) > 0:
            window_seconds = max(30, int(live_settings.get("payment_window_seconds", 120) or 120))
            job_stub["status"] = "AWAITING_PAYMENT"
            job_stub["status_message"] = (
                f"To'lov kutilmoqda: {window_seconds} soniya ichida {metrics['estimated_cost']} UZS o'tkazing va chek yuklang."
            )
            job_stub["queue_state"] = "AWAITING_PAYMENT"
            job_stub["started_at"] = ""
            job_stub["printing_until_ts"] = 0.0
            job_stub["confirm_deadline_ts"] = 0.0
            job_stub["payment_status"] = "AWAITING_PAYMENT"
            job_stub["payment_created_ts"] = now
            job_stub["payment_deadline_ts"] = now + window_seconds
            saved_job = create_print_job(job_stub)
            return _job_to_response(
                saved_job,
                active_job=active_job,
                waiting_jobs=waiting_jobs,
                now_ts=now,
                caller_token=effective_token,
                include_secret_token=True,
            )

        job_stub["payment_status"] = "NOT_REQUIRED"
        if active_job is None:
            dispatch_result = adapter.submit_job(job_stub, output_pdf_path)
            duration = max(1, int(metrics["estimated_seconds"] or 5))
            job_stub["status"] = dispatch_result["status"]
            job_stub["status_message"] = dispatch_result["status_message"]
            job_stub["queue_state"] = "ACTIVE_PRINTING"
            job_stub["started_at"] = datetime.now(timezone.utc).isoformat()
            job_stub["printing_until_ts"] = now + duration
            job_stub["confirm_deadline_ts"] = 0.0
            saved_job = create_print_job(job_stub)
            return _job_to_response(
                saved_job,
                active_job=saved_job,
                waiting_jobs=waiting_jobs,
                now_ts=now,
                caller_token=effective_token,
                include_secret_token=True,
            )

        pos = len(waiting_jobs) + 1
        job_stub["status"] = "WAITING_IN_QUEUE"
        job_stub["status_message"] = (
            f"Printer hozir band. Siz navbatda {pos}-o'rindasiz — navbatingiz kelishi bilan chop etiladi."
        )
        job_stub["queue_state"] = "WAITING_IN_QUEUE"
        job_stub["started_at"] = ""
        job_stub["printing_until_ts"] = 0.0
        job_stub["confirm_deadline_ts"] = 0.0
        saved_job = create_print_job(job_stub)
        updated_waiting = list_waiting_queue_jobs()
        return _job_to_response(
            saved_job,
            active_job=active_job,
            waiting_jobs=updated_waiting,
            now_ts=now,
            caller_token=effective_token,
            include_secret_token=True,
        )


@app.get("/api/queue/live", response_model=LiveQueueStatusResponse)
def get_live_print_queue(
    x_client_token: str = Header(default=""),
    client_token: str = "",
) -> LiveQueueStatusResponse:
    now = time.time()
    caller_token = (x_client_token or client_token or "").strip()
    active_job, waiting_jobs = _tick_and_advance_queue(now_ts=now)
    recent_jobs = list_recent_completed_jobs(limit=5)
    settings = get_settings()

    if not active_job:
        printer_state = "IDLE"
        active_rem = 0
    elif active_job.get("queue_state") == "AWAITING_CONFIRMATION":
        printer_state = "AWAITING_CONFIRMATION"
        active_rem = 0
    else:
        printer_state = "PRINTING"
        active_rem = max(
            0, int(float(active_job.get("printing_until_ts") or 0.0) - now + 0.999)
        )

    total_wait = active_rem + sum(int(w.get("estimated_seconds") or 0) for w in waiting_jobs)
    return LiveQueueStatusResponse(
        printer_busy=active_job is not None,
        printer_state=printer_state,
        printer_mode=settings["printer_mode"],
        default_printer_name=settings.get("default_printer_name") or "Standart Printer",
        active_job=(
            _job_to_public_item(active_job, active_job, waiting_jobs, now, caller_token=caller_token)
            if active_job
            else None
        ),
        waiting_jobs=[
            _job_to_public_item(w, active_job, waiting_jobs, now, caller_token=caller_token)
            for w in waiting_jobs
        ],
        recent_jobs=[
            _job_to_public_item(r, active_job, waiting_jobs, now, caller_token=caller_token)
            for r in recent_jobs
        ],
        waiting_count=len(waiting_jobs),
        total_estimated_wait_seconds=total_wait,
        server_time=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/api/print-jobs/{job_id}/confirm", response_model=PrintJobResponse)
def confirm_job_printed(
    job_id: str,
    payload: JobConfirmRequest | None = Body(default=None),
    x_client_token: str = Header(default=""),
) -> PrintJobResponse:
    with QUEUE_LOCK:
        now = time.time()
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
        caller_token = ((payload.client_token if payload else "") or x_client_token or "").strip()
        _authorize_client_action(job, caller_token)

        q_state = job.get("queue_state")
        if q_state == "COMPLETED":
            active, waiting = _tick_and_advance_queue(now_ts=now)
            return _job_to_response(
                job, active_job=active, waiting_jobs=waiting, now_ts=now, caller_token=caller_token
            )
        if q_state not in {"ACTIVE_PRINTING", "AWAITING_CONFIRMATION"}:
            raise HTTPException(
                status_code=400,
                detail="Bu buyurtma hozir faol chop etish bosqichida emas.",
            )

        updated = update_job_queue_fields(
            job_id,
            {
                "queue_state": "COMPLETED",
                "status": "COMPLETED",
                "status_message": "Foydalanuvchi qog'ozlar chiqqanini tasdiqladi.",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "printing_until_ts": 0.0,
                "confirm_deadline_ts": 0.0,
            },
        )
        assert updated is not None
        active, waiting = _tick_and_advance_queue(now_ts=now)
        return _job_to_response(
            updated, active_job=active, waiting_jobs=waiting, now_ts=now, caller_token=caller_token
        )


@app.post("/api/print-jobs/{job_id}/extend", response_model=PrintJobResponse)
def extend_job_print_time(
    job_id: str,
    payload: JobConfirmRequest | None = Body(default=None),
    x_client_token: str = Header(default=""),
) -> PrintJobResponse:
    with QUEUE_LOCK:
        now = time.time()
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
        caller_token = ((payload.client_token if payload else "") or x_client_token or "").strip()
        _authorize_client_action(job, caller_token)
        if job.get("queue_state") not in {"ACTIVE_PRINTING", "AWAITING_CONFIRMATION"}:
            raise HTTPException(
                status_code=400,
                detail="Faqat chop etilayotgan buyurtma vaqtini uzaytirish mumkin.",
            )

        extra_sec = max(5, min(30, int(payload.extra_seconds) if payload else 15))
        base_ts = max(now, float(job.get("printing_until_ts") or now))
        max_remaining = max(90, int(job.get("estimated_seconds") or 15) + 60)
        if (base_ts + extra_sec) - now > max_remaining:
            raise HTTPException(
                status_code=400,
                detail="Qo'shimcha vaqt limiti (maksimal +60 soniya) tugagan.",
            )
        updated = update_job_queue_fields(
            job_id,
            {
                "queue_state": "ACTIVE_PRINTING",
                "printing_until_ts": base_ts + extra_sec,
                "confirm_deadline_ts": 0.0,
                "status_message": f"Printer uchun qo'shimcha {extra_sec} soniya vaqt qo'shildi...",
            },
        )
        assert updated is not None
        waiting = list_waiting_queue_jobs()
        return _job_to_response(
            updated, active_job=updated, waiting_jobs=waiting, now_ts=now, caller_token=caller_token
        )


@app.post("/api/print-jobs/{job_id}/cancel", response_model=PrintJobResponse)
def cancel_print_job(
    job_id: str,
    payload: JobConfirmRequest | None = Body(default=None),
    x_client_token: str = Header(default=""),
) -> PrintJobResponse:
    with QUEUE_LOCK:
        now = time.time()
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
        caller_token = ((payload.client_token if payload else "") or x_client_token or "").strip()
        _authorize_client_action(job, caller_token)
        if job.get("queue_state") == "COMPLETED":
            raise HTTPException(
                status_code=400,
                detail="Allaqachon chop etilgan buyurtmani bekor qilib bo'lmaydi.",
            )

        updated = update_job_queue_fields(
            job_id,
            {
                "queue_state": "CANCELLED",
                "status": "CANCELLED",
                "status_message": "Buyurtma foydalanuvchi tomonidan bekor qilindi.",
                "printing_until_ts": 0.0,
                "confirm_deadline_ts": 0.0,
            },
        )
        assert updated is not None
        active, waiting = _tick_and_advance_queue(now_ts=now)
        return _job_to_response(
            updated, active_job=active, waiting_jobs=waiting, now_ts=now, caller_token=caller_token
        )


@app.get("/api/print-jobs/{job_id}/pdf")
def serve_job_pdf(
    job_id: str,
    access_key: str = "",
    client_token: str = "",
    x_client_token: str = Header(default=""),
    authorization: str = Header(default=""),
    x_agent_key: str = Header(default=""),
) -> FileResponse:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
    _authorize_job_pdf_access(
        job,
        access_key=access_key,
        x_client_token=x_client_token,
        client_token=client_token,
        authorization=authorization,
        x_agent_key=x_agent_key,
    )
    pdf_path = Path(job["output_pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Tayyorlangan PDF topilmadi.")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{job_id}_print_ready.pdf"'},
    )


@app.get("/api/print-jobs/{job_id}/segments/{segment_index}/pdf")
def serve_job_segment_pdf(
    job_id: str,
    segment_index: int,
    access_key: str = "",
    client_token: str = "",
    x_client_token: str = Header(default=""),
    authorization: str = Header(default=""),
    x_agent_key: str = Header(default=""),
) -> FileResponse:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
    _authorize_job_pdf_access(
        job,
        access_key=access_key,
        x_client_token=x_client_token,
        client_token=client_token,
        authorization=authorization,
        x_agent_key=x_agent_key,
    )
    segments = job.get("print_segments") or []
    seg = next((s for s in segments if int(s.get("segment_index", 0)) == segment_index), None)
    if not seg:
        raise HTTPException(status_code=404, detail="Chop etish segmenti topilmadi.")
    seg_path = JOBS_DIR / job_id / seg["pdf_filename"]
    if not seg_path.exists():
        seg_path = Path(job["output_pdf_path"])
    if not seg_path.exists():
        raise HTTPException(status_code=404, detail="Segment PDF fayli diskda topilmadi.")
    return FileResponse(
        path=seg_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{job_id}_{seg["pdf_filename"]}"'},
    )


@app.get("/api/print-jobs/{job_id}/status")
def get_job_live_status(
    job_id: str,
    x_client_token: str = Header(default=""),
    client_token: str = "",
) -> dict:
    with QUEUE_LOCK:
        now = time.time()
        active_job, waiting_jobs = _tick_and_advance_queue(now_ts=now)
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    caller_token = (x_client_token or client_token or "").strip()
    dev_id = _build_device_id(job.get("client_token", ""), job.get("client_ip", ""))
    is_mine = _is_job_owner(job, caller_token)
    if job["printer_mode"] == "WINDOWS_SPOOLER":
        spooler = get_spooler_status(job["printer_name"], document_title=job_id)
    elif job["printer_mode"] == "LINUX_CUPS":
        spooler = get_cups_spooler_status(job["printer_name"], document_title=job["original_filename"])
    else:
        spooler = None
    enrich = compute_job_queue_enrichment(job, active_job, waiting_jobs, now_ts=now)
    return {
        "job_id": job["id"],
        "status": job["status"],
        "status_message": job["status_message"],
        "printer_name": job["printer_name"],
        "printer_mode": job["printer_mode"],
        "device_id": dev_id,
        "device_label": job.get("device_label") or f"Qurilma ({dev_id})",
        "is_mine": is_mine,
        "queue_state": job.get("queue_state", "COMPLETED"),
        "queue_position": enrich["queue_position"],
        "remaining_print_seconds": enrich["remaining_print_seconds"],
        "confirm_remaining_seconds": enrich["confirm_remaining_seconds"],
        "payment_remaining_seconds": enrich["payment_remaining_seconds"],
        "payment_status": job.get("payment_status", "NOT_REQUIRED"),
        "estimated_wait_seconds": enrich["estimated_wait_seconds"],
        "spooler": spooler,
    }


_ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
_MAX_RECEIPT_BYTES = 10 * 1024 * 1024


def _enqueue_or_dispatch_paid_job(job_id: str) -> tuple[dict, dict | None, list[dict]]:
    now = time.time()
    active_job, waiting_jobs = _tick_and_advance_queue(now_ts=now)
    job = get_print_job(job_id)
    assert job is not None
    live_settings = get_settings()
    adapter = get_active_printer_adapter(mode=live_settings["printer_mode"])
    target_printer = (job.get("printer_name") or "").strip() or live_settings["default_printer_name"]
    if active_job is None:
        job_for_dispatch = {
            **job,
            "printer_name": target_printer,
            "printer_mode": adapter.mode_name,
        }
        dispatch_result = adapter.submit_job(job_for_dispatch, Path(job["output_pdf_path"]))
        duration = max(1, int(job.get("estimated_seconds") or 5))
        updated = update_job_queue_fields(
            job_id,
            {
                "status": dispatch_result["status"],
                "status_message": dispatch_result["status_message"],
                "queue_state": "ACTIVE_PRINTING",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "printing_until_ts": now + duration,
                "confirm_deadline_ts": 0.0,
            },
        )
        assert updated is not None
        active_after, waiting_after = _tick_and_advance_queue(now_ts=now)
        return updated, active_after, waiting_after

    pos = len(waiting_jobs) + 1
    updated = update_job_queue_fields(
        job_id,
        {
            "status": "WAITING_IN_QUEUE",
            "status_message": f"To'lov tasdiqlandi! Printer hozir band — siz navbatda {pos}-o'rindasiz.",
            "queue_state": "WAITING_IN_QUEUE",
            "started_at": "",
            "printing_until_ts": 0.0,
            "confirm_deadline_ts": 0.0,
        },
    )
    assert updated is not None
    waiting_after = list_waiting_queue_jobs()
    return updated, active_job, waiting_after


@app.post("/api/print-jobs/{job_id}/verify-payment", response_model=PrintJobResponse)
async def verify_job_payment(
    job_id: str,
    receipt: UploadFile = File(...),
    client_token: str = Form(default=""),
    x_client_token: str = Header(default=""),
) -> PrintJobResponse:
    caller_token = (x_client_token or client_token or "").strip()
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    _authorize_client_action(job, caller_token)

    if job.get("queue_state") != "AWAITING_PAYMENT":
        raise HTTPException(
            status_code=400,
            detail="Bu buyurtma hozir to'lov kutish holatida emas.",
        )

    original_receipt_name = _sanitize_filename(receipt.filename, fallback="chek.jpg")
    ext = Path(original_receipt_name).suffix.lower()
    if ext not in _ALLOWED_RECEIPT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="To'lov cheki faqat rasm (JPG, PNG, WEBP) yoki PDF formatda bo'lishi kerak.",
        )

    content = await receipt.read()
    if not content:
        raise HTTPException(status_code=400, detail="Yuklangan chek fayli bo'sh.")
    if len(content) > _MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=400, detail="Chek fayli hajmi 10 MB dan oshmasligi kerak.")
    _validate_receipt_file_bytes(content, ext)

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = job_dir / f"receipt{ext}"
    receipt_path.write_bytes(content)

    now = time.time()
    uploaded_iso = datetime.now(timezone.utc).isoformat()
    update_job_queue_fields(
        job_id,
        {
            "receipt_path": str(receipt_path),
            "receipt_filename": original_receipt_name[:180],
            "receipt_uploaded_at": uploaded_iso,
        },
    )

    deadline_ts = float(job.get("payment_deadline_ts") or 0.0)
    if deadline_ts > 0 and now > deadline_ts + 5:
        expired_msg = "120 soniyalik to'lov muddati tugadi. 'Vaqtni yangilash' tugmasini bosib qayta urinib ko'ring."
        update_job_queue_fields(
            job_id,
            {
                "payment_status": "EXPIRED",
                "payment_note": expired_msg,
                "status_message": expired_msg,
            },
        )
        raise HTTPException(status_code=400, detail=expired_msg)

    expected_cost = int(job.get("estimated_cost") or 0)
    if expected_cost <= 0:
        verification = {
            "verified": True,
            "transaction": {"tx_uid": f"free_{job_id}"},
            "message": "Bepul buyurtma avtomatik tasdiqlandi.",
        }
    else:
        created_ts = int(float(job.get("payment_created_ts") or now))
        verification = await asyncio.to_thread(
            verify_and_claim_humo_payment,
            job_id=job_id,
            expected_amount_uzs=expected_cost,
            payment_created_ts=created_ts,
            attempts=3,
            delay_seconds=2.0,
        )

    if not verification.get("verified"):
        fail_msg = verification.get("message") or "To'lov tasdiqlanmadi."
        update_job_queue_fields(
            job_id,
            {
                "payment_status": "UNVERIFIED",
                "payment_note": fail_msg,
                "status_message": fail_msg,
            },
        )
        raise HTTPException(status_code=400, detail=fail_msg)

    tx = verification.get("transaction") or {}
    verified_iso = datetime.now(timezone.utc).isoformat()
    with QUEUE_LOCK:
        latest = get_print_job(job_id)
        if not latest or latest.get("queue_state") != "AWAITING_PAYMENT":
            raise HTTPException(status_code=400, detail="Buyurtma holati o'zgargan.")
        update_job_queue_fields(
            job_id,
            {
                "payment_status": "PAID",
                "payment_tx_id": str(tx.get("tx_uid") or ""),
                "payment_verified_at": verified_iso,
                "payment_note": str(verification.get("message") or "To'lov tasdiqlandi."),
            },
        )
        dispatched_job, active_job, waiting_jobs = _enqueue_or_dispatch_paid_job(job_id)
        return _job_to_response(
            dispatched_job,
            active_job=active_job,
            waiting_jobs=waiting_jobs,
            caller_token=caller_token,
            include_secret_token=True,
        )


@app.post("/api/print-jobs/{job_id}/renew-payment", response_model=PrintJobResponse)
def renew_job_payment_timer(
    job_id: str,
    payload: JobConfirmRequest,
    x_client_token: str = Header(default=""),
) -> PrintJobResponse:
    caller_token = (payload.client_token or x_client_token or "").strip()
    with QUEUE_LOCK:
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
        _authorize_client_action(job, caller_token)
        if job.get("queue_state") != "AWAITING_PAYMENT":
            raise HTTPException(
                status_code=400,
                detail="Faqat to'lov kutayotgan buyurtma vaqtini uzaytirish mumkin.",
            )
        settings = get_settings()
        window_seconds = max(30, int(settings.get("payment_window_seconds", 120) or 120))
        now = time.time()
        created_ts = float(job.get("payment_created_ts") or now)
        if now - created_ts > 900:
            raise HTTPException(
                status_code=400,
                detail="To'lov vaqtini uzaytirish limiti tugagan. Iltimos, yangi buyurtma yarating.",
            )
        updated = update_job_queue_fields(
            job_id,
            {
                "payment_status": "AWAITING_PAYMENT",
                "payment_created_ts": created_ts,
                "payment_deadline_ts": now + window_seconds,
                "payment_note": "",
                "status_message": f"To'lov oynasi yangilandi: {window_seconds} soniya ichida to'lang va chek yuklang.",
            },
        )
        assert updated is not None
        active_job, waiting_jobs = _tick_and_advance_queue(now_ts=now)
        return _job_to_response(
            updated,
            active_job=active_job,
            waiting_jobs=waiting_jobs,
            now_ts=now,
            caller_token=caller_token,
            include_secret_token=True,
        )


# ---------------------------------------------------------------------------
# Admin Panel Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/admin/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest, request: Request) -> AdminLoginResponse:
    client_ip = _extract_client_ip(request)
    _check_login_rate_limit(client_ip)
    if not verify_admin_credentials(payload.username, payload.password):
        _record_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri.")
    _clear_login_failures(client_ip)
    clean_user = payload.username.strip()
    token = _issue_admin_token(clean_user)
    return AdminLoginResponse(
        token=token,
        username=clean_user,
        expires_in=ADMIN_TOKEN_TTL_SECONDS,
    )


@app.get("/api/admin/dashboard", response_model=AdminDashboardResponse)
def admin_dashboard(_admin: str = Depends(require_admin)) -> AdminDashboardResponse:
    settings = get_settings()
    stats = get_admin_stats()
    printers = [PrinterInfo(**p) for p in discover_all_printers(settings.get("agent_printers"))]
    jobs = [_job_to_response(j, include_secret_token=True) for j in list_print_jobs(limit=200)]
    tg_status = get_telegram_status(check_remote=False)
    return AdminDashboardResponse(
        stats=AdminStats(**stats),
        settings=_settings_to_payload(settings),
        printers=printers,
        jobs=jobs,
        telegram=TelegramStatusInfo(**tg_status),
    )


@app.get("/api/admin/print-jobs/{job_id}/receipt")
def admin_get_job_receipt(
    job_id: str,
    _admin: str = Depends(require_admin_header_or_query),
) -> FileResponse:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    raw_path = (job.get("receipt_path") or "").strip()
    if not raw_path:
        raise HTTPException(status_code=404, detail="Ushbu buyurtma uchun to'lov cheki yuklanmagan.")
    receipt_file = Path(raw_path)
    if not receipt_file.exists():
        raise HTTPException(status_code=404, detail="Chek fayli diskda topilmadi.")
    media_type, _ = mimetypes.guess_type(str(receipt_file))
    safe_name = _sanitize_filename(job.get("receipt_filename") or receipt_file.name, fallback="chek.png")
    return FileResponse(
        path=receipt_file,
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@app.post("/api/admin/telegram/send-code")
def admin_telegram_send_code(
    payload: TelegramSendCodeRequest,
    _admin: str = Depends(require_admin),
) -> dict:
    try:
        return admin_send_telegram_code(payload.phone, payload.bot_username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Telegram kodi yuborishda xato: {exc}") from exc


@app.post("/api/admin/telegram/verify-code")
def admin_telegram_verify_code(
    payload: TelegramVerifyCodeRequest,
    _admin: str = Depends(require_admin),
) -> dict:
    try:
        return admin_verify_telegram_code(
            auth_token=payload.auth_token,
            code=payload.code,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Telegram tasdiqlashda xato: {exc}") from exc


@app.post("/api/admin/telegram/disconnect")
def admin_telegram_disconnect(_admin: str = Depends(require_admin)) -> dict:
    return admin_disconnect_telegram()


@app.get("/api/admin/telegram/recent-payments")
def admin_telegram_recent_payments(_admin: str = Depends(require_admin)) -> dict:
    return fetch_recent_humo_topups(limit=20)


@app.put("/api/admin/settings", response_model=AdminSettingsPayload)
def admin_update_settings(
    payload: AdminSettingsUpdateRequest,
    _admin: str = Depends(require_admin),
) -> AdminSettingsPayload:
    data = payload.model_dump()
    if not (data.get("agent_api_key") or "").strip():
        data.pop("agent_api_key", None)
    if data.get("telegram_bot_username"):
        data["telegram_bot_username"] = normalize_bot_username(data["telegram_bot_username"])
    updated = update_settings(data)
    return _settings_to_payload(updated)


@app.put("/api/admin/credentials")
def admin_update_credentials(
    payload: AdminPasswordUpdateRequest,
    _admin: str = Depends(require_admin),
) -> dict[str, str | bool]:
    ok = update_admin_credentials(
        new_username=payload.new_username,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Joriy parol noto'g'ri.")
    token = _issue_admin_token(payload.new_username.strip())
    return {
        "updated": True,
        "username": payload.new_username.strip(),
        "token": token,
    }


@app.patch("/api/admin/print-jobs/{job_id}", response_model=PrintJobResponse)
def admin_update_job(
    job_id: str,
    payload: JobStatusUpdateRequest,
    _admin: str = Depends(require_admin),
) -> PrintJobResponse:
    with QUEUE_LOCK:
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")

        if payload.status == "APPROVE_PAYMENT":
            verified_iso = datetime.now(timezone.utc).isoformat()
            note = payload.status_message.strip() or "Admin tomonidan to'lov cheki asosida tasdiqlandi."
            update_job_queue_fields(
                job_id,
                {
                    "payment_status": "PAID",
                    "payment_tx_id": job.get("payment_tx_id") or f"admin_manual_{job_id}",
                    "payment_verified_at": verified_iso,
                    "payment_note": note,
                },
            )
            updated, active_job, waiting_jobs = _enqueue_or_dispatch_paid_job(job_id)
            return _job_to_response(updated, active_job=active_job, waiting_jobs=waiting_jobs, include_secret_token=True)

        if payload.status == "DISPATCH_PRINTER":
            settings = get_settings()
            active_mode = settings["printer_mode"]
            if active_mode in {"LINUX_CUPS", "REMOTE_AGENT", "WINDOWS_SPOOLER"}:
                dispatch_mode = active_mode
            elif shutil.which("lp"):
                dispatch_mode = "LINUX_CUPS"
            else:
                dispatch_mode = "WINDOWS_SPOOLER"
            adapter = get_active_printer_adapter(mode=dispatch_mode)
            job_for_dispatch = {
                **job,
                "printer_name": job.get("printer_name") or settings["default_printer_name"],
            }
            result = adapter.submit_job(job_for_dispatch, Path(job["output_pdf_path"]))
            updated = update_print_job_status(job_id, result["status"], result["status_message"])
        else:
            default_messages = {
                "COMPLETED": "Admin tomonidan 'Chop etildi' deb belgilandi.",
                "CANCELLED": "Admin tomonidan bekor qilindi.",
                "READY_IN_QUEUE": "Navbatga qaytarildi.",
                "WAITING_IN_QUEUE": "Kutish navbatiga qaytarildi.",
                "AWAITING_CONFIRMATION": "Foydalanuvchi tasdiqlashi kutilmoqda.",
                "QUEUED_FOR_AGENT": "Raspberry Pi printer agent navbatiga qo'yildi.",
                "PRINTING_ON_PI": "Raspberry Pi printerda chop etilmoqda.",
                "SENT_TO_PRINTER": "Printerga yuborilgan deb belgilandi.",
                "ERROR": "Xatolik holati belgilandi.",
            }
            msg = payload.status_message.strip() or default_messages.get(payload.status, "")
            updated = update_print_job_status(job_id, payload.status, msg)

        assert updated is not None
        active_job, waiting_jobs = _tick_and_advance_queue()
        return _job_to_response(updated, active_job=active_job, waiting_jobs=waiting_jobs, include_secret_token=True)


@app.delete("/api/admin/print-jobs/{job_id}")
def admin_remove_print_job(
    job_id: str,
    _admin: str = Depends(require_admin),
) -> dict[str, bool]:
    with QUEUE_LOCK:
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
        delete_print_job(job_id)
        job_dir = JOBS_DIR / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        _tick_and_advance_queue()
    return {"deleted": True}


@app.delete("/api/admin/print-jobs")
def admin_clear_all_jobs(_admin: str = Depends(require_admin)) -> dict[str, int]:
    removed = clear_all_print_jobs()
    if JOBS_DIR.exists():
        for entry in JOBS_DIR.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
    return {"cleared": removed}


# ---------------------------------------------------------------------------
# Raspberry Pi 5 Remote Print Agent Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/agent/poll")
def agent_poll_next_job(
    payload: AgentHeartbeatRequest,
    _agent: str = Depends(require_agent_key),
) -> dict:
    printers_data = [p.model_dump() for p in payload.printers]
    record_agent_heartbeat(
        hostname=payload.hostname,
        printers=printers_data,
        cpu_temp_c=payload.cpu_temp_c,
    )
    with QUEUE_LOCK:
        _tick_and_advance_queue()
        claimed = claim_next_agent_job()
        return {
            "ok": True,
            "job": _job_to_response(claimed, include_secret_token=True).model_dump() if claimed else None,
        }


@app.post("/api/agent/jobs/{job_id}/report", response_model=PrintJobResponse)
def agent_report_job_status(
    job_id: str,
    payload: AgentJobReportRequest,
    _agent: str = Depends(require_agent_key),
) -> PrintJobResponse:
    with QUEUE_LOCK:
        job = get_print_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
        default_msgs = {
            "PRINTING_ON_PI": "Raspberry Pi CUPS printerida chop etilmoqda...",
            "COMPLETED": "Raspberry Pi printer qog'ozni muvaffaqiyatli chiqardi.",
            "ERROR": "Raspberry Pi printerida xatolik yuz berdi.",
        }
        msg = payload.status_message.strip() or default_msgs.get(payload.status, "")
        updated = update_print_job_status(job_id, payload.status, msg)
        assert updated is not None
        active_job, waiting_jobs = _tick_and_advance_queue()
        return _job_to_response(updated, active_job=active_job, waiting_jobs=waiting_jobs, include_secret_token=True)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
