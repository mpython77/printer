"""FastAPI application for TLG SmartPrint."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import shutil
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    claim_next_agent_job,
    clear_all_print_jobs,
    create_print_job,
    delete_print_job,
    get_admin_stats,
    get_document,
    get_print_job,
    get_settings,
    get_token_secret,
    init_db,
    list_print_jobs,
    record_agent_heartbeat,
    save_document,
    update_admin_credentials,
    update_print_job_status,
    update_settings,
    verify_admin_credentials,
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
    JobStatusUpdateRequest,
    PricingInfo,
    PrinterInfo,
    PrintJobCreateRequest,
    PrintJobResponse,
    PrintSegmentInfo,
    SystemStatusResponse,
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


def _job_to_response(job: dict) -> PrintJobResponse:
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
        print_segments=[PrintSegmentInfo(**seg) for seg in job.get("print_segments", [])],
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
        pdf_url=f"/api/print-jobs/{job['id']}/pdf",
        original_pdf_url=f"/api/documents/{job['document_id']}/pdf",
        created_at=job["created_at"],
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
    )


@app.post("/api/documents/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    original_filename = file.filename or "hujjat.pdf"
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
def submit_print_job(payload: PrintJobCreateRequest) -> PrintJobResponse:
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

    adapter = get_active_printer_adapter(mode=settings["printer_mode"])
    target_printer = payload.printer_name.strip() or settings["default_printer_name"]

    job_stub = {
        "id": job_id,
        "document_id": doc["id"],
        "original_filename": doc["original_filename"],
        "student_name": payload.student_name.strip(),
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
        "printer_name": target_printer,
        "printer_mode": adapter.mode_name,
        "output_pdf_path": str(output_pdf_path),
    }

    dispatch_result = adapter.submit_job(job_stub, output_pdf_path)
    job_stub["status"] = dispatch_result["status"]
    job_stub["status_message"] = dispatch_result["status_message"]

    saved_job = create_print_job(job_stub)
    return _job_to_response(saved_job)


@app.get("/api/print-jobs/{job_id}/pdf")
def serve_job_pdf(job_id: str) -> FileResponse:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
    pdf_path = Path(job["output_pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Tayyorlangan PDF topilmadi.")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{job_id}_print_ready.pdf"'},
    )


@app.get("/api/print-jobs/{job_id}/segments/{segment_index}/pdf")
def serve_job_segment_pdf(job_id: str, segment_index: int) -> FileResponse:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chop etish buyurtmasi topilmadi.")
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
def get_job_live_status(job_id: str) -> dict:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    if job["printer_mode"] == "WINDOWS_SPOOLER":
        spooler = get_spooler_status(job["printer_name"], document_title=job_id)
    elif job["printer_mode"] == "LINUX_CUPS":
        spooler = get_cups_spooler_status(job["printer_name"], document_title=job["original_filename"])
    else:
        spooler = None
    return {
        "job_id": job["id"],
        "status": job["status"],
        "status_message": job["status_message"],
        "printer_mode": job["printer_mode"],
        "spooler": spooler,
    }


# ---------------------------------------------------------------------------
# Admin Panel Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/admin/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest) -> AdminLoginResponse:
    if not verify_admin_credentials(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri.")
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
    jobs = [_job_to_response(j) for j in list_print_jobs(limit=200)]
    return AdminDashboardResponse(
        stats=AdminStats(**stats),
        settings=_settings_to_payload(settings),
        printers=printers,
        jobs=jobs,
    )


@app.put("/api/admin/settings", response_model=AdminSettingsPayload)
def admin_update_settings(
    payload: AdminSettingsUpdateRequest,
    _admin: str = Depends(require_admin),
) -> AdminSettingsPayload:
    data = payload.model_dump()
    if not data.get("agent_api_key", "").strip():
        data.pop("agent_api_key", None)
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
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")

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
            "QUEUED_FOR_AGENT": "Raspberry Pi printer agent navbatiga qo'yildi.",
            "PRINTING_ON_PI": "Raspberry Pi printerda chop etilmoqda.",
            "SENT_TO_PRINTER": "Printerga yuborilgan deb belgilandi.",
            "ERROR": "Xatolik holati belgilandi.",
        }
        msg = payload.status_message.strip() or default_messages.get(payload.status, "")
        updated = update_print_job_status(job_id, payload.status, msg)

    assert updated is not None
    return _job_to_response(updated)


@app.delete("/api/admin/print-jobs/{job_id}")
def admin_remove_print_job(
    job_id: str,
    _admin: str = Depends(require_admin),
) -> dict[str, bool]:
    job = get_print_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    delete_print_job(job_id)
    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
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
    claimed = claim_next_agent_job()
    return {
        "ok": True,
        "job": _job_to_response(claimed).model_dump() if claimed else None,
    }


@app.post("/api/agent/jobs/{job_id}/report", response_model=PrintJobResponse)
def agent_report_job_status(
    job_id: str,
    payload: AgentJobReportRequest,
    _agent: str = Depends(require_agent_key),
) -> PrintJobResponse:
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
    return _job_to_response(updated)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
