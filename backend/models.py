"""Pydantic schemas for TLG SmartPrint API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: str
    original_filename: str
    file_type: str
    file_size: int
    page_count: int
    pdf_url: str
    created_at: str


class PrintJobCreateRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    selected_pages: list[int] = Field(default_factory=list)
    page_range_text: str = Field(default="")
    rotations: dict[str, int] = Field(default_factory=dict)
    copies: int = Field(default=1, ge=1, le=99)
    color_mode: Literal["bw", "color", "mixed"] = "bw"
    color_pages: list[int] = Field(default_factory=list)
    color_pages_text: str = Field(default="")
    duplex: Literal["simplex", "duplex"] = "simplex"
    orientation: Literal["portrait", "landscape"] = "portrait"
    pages_per_sheet: Literal[1, 2, 4] = 1
    paper_size: Literal["A4", "A5", "Letter"] = "A4"
    student_name: str = Field(default="", max_length=120)
    printer_name: str = Field(default="", max_length=200)
    client_token: str = Field(default="", max_length=120)
    device_label: str = Field(default="", max_length=160)


class PrintSegmentInfo(BaseModel):
    segment_index: int
    color_mode: str
    sheet_count: int
    page_range_text: str
    pdf_filename: str = ""
    pdf_url: str = ""


class PrintJobResponse(BaseModel):
    id: str
    document_id: str
    original_filename: str
    student_name: str
    selected_pages: list[int]
    page_range_text: str
    rotations: dict[str, int]
    selected_page_count: int
    copies: int
    color_mode: str
    color_pages: list[int] = Field(default_factory=list)
    bw_sheets: int = 0
    color_sheets: int = 0
    print_segments: list[PrintSegmentInfo] = Field(default_factory=list)
    duplex: str
    orientation: str
    pages_per_sheet: int
    paper_size: str
    total_printed_pages: int
    physical_sheets: int
    estimated_cost: int
    estimated_seconds: int = 0
    printer_name: str
    printer_mode: str
    status: str
    status_message: str
    pdf_url: str
    original_pdf_url: str
    created_at: str
    client_token: str = ""
    device_id: str = ""
    device_label: str = ""
    client_ip: str = ""
    is_mine: bool = False
    queue_state: str = "COMPLETED"
    queue_position: int = 0
    remaining_print_seconds: int = 0
    confirm_remaining_seconds: int = 0
    payment_remaining_seconds: int = 0
    estimated_wait_seconds: int = 0
    started_at: str = ""
    completed_at: str = ""
    payment_status: str = "NOT_REQUIRED"
    payment_deadline_ts: float = 0.0
    payment_tx_id: str = ""
    payment_verified_at: str = ""
    payment_note: str = ""
    has_receipt: bool = False
    receipt_filename: str = ""
    receipt_uploaded_at: str = ""
    receipt_url: str = ""


class PrinterInfo(BaseModel):
    name: str
    is_default: bool = False
    status_text: str = "Tayyor"
    is_offline: bool = False
    jobs_in_queue: int = 0
    source: str = "local"
    connection_type: str = "LOCAL"
    port_or_uri: str = ""
    driver_name: str = ""
    hardware_present: bool | None = None
    is_virtual: bool = False
    ready_to_print: bool = True
    configured: bool = True
    supports_color: bool | None = None
    supports_duplex: bool | None = None
    host_label: str = ""
    can_auto_configure: bool = False
    suggested_queue_name: str = ""


class PricingInfo(BaseModel):
    bw_simplex: int
    bw_duplex: int
    color_simplex: int
    color_duplex: int
    seconds_bw_per_sheet: int = 7
    seconds_color_per_sheet: int = 14
    warmup_seconds: int = 5
    currency: str = "UZS"


class PaymentConfigInfo(BaseModel):
    enabled: bool = True
    card_number: str = ""
    card_holder: str = ""
    window_seconds: int = 120


class TelegramStatusInfo(BaseModel):
    connected: bool = False
    bot_username: str = "@HUMOcardbot"
    account_name: str = ""
    account_username: str = ""
    account_phone: str = ""
    error: str = ""


class TelegramSendCodeRequest(BaseModel):
    phone: str = Field(..., min_length=7, max_length=32)
    bot_username: str = Field(default="@HUMOcardbot", min_length=3, max_length=120)


class TelegramVerifyCodeRequest(BaseModel):
    auth_token: str = Field(..., min_length=8, max_length=128)
    code: str = Field(default="", max_length=20)
    password: str = Field(default="", max_length=120)


class SystemStatusResponse(BaseModel):
    printer_mode: str
    hardware_connected: bool
    default_printer_name: str
    mode_description: str
    printers: list[PrinterInfo]
    pricing: PricingInfo
    payment: PaymentConfigInfo


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=120)


class AdminLoginResponse(BaseModel):
    token: str
    username: str
    expires_in: int


class AdminSettingsPayload(BaseModel):
    admin_username: str
    bw_simplex: int
    bw_duplex: int
    color_simplex: int
    color_duplex: int
    seconds_bw_per_sheet: int = 7
    seconds_color_per_sheet: int = 14
    warmup_seconds: int = 5
    printer_mode: str
    default_printer_name: str
    agent_api_key: str = ""
    agent_last_seen: str = ""
    agent_hostname: str = ""
    payment_enabled: bool = True
    payment_card_number: str = ""
    payment_card_holder: str = ""
    payment_window_seconds: int = 120
    telegram_bot_username: str = "@HUMOcardbot"


class AdminSettingsUpdateRequest(BaseModel):
    bw_simplex: int = Field(..., ge=0, le=100000)
    bw_duplex: int = Field(..., ge=0, le=100000)
    color_simplex: int = Field(..., ge=0, le=100000)
    color_duplex: int = Field(..., ge=0, le=100000)
    seconds_bw_per_sheet: int = Field(default=7, ge=1, le=300)
    seconds_color_per_sheet: int = Field(default=14, ge=1, le=300)
    warmup_seconds: int = Field(default=5, ge=0, le=120)
    printer_mode: Literal["DRY_RUN", "LINUX_CUPS", "REMOTE_AGENT", "WINDOWS_SPOOLER"] = "DRY_RUN"
    default_printer_name: str = Field(default="", max_length=200)
    agent_api_key: str = Field(default="", max_length=200)
    payment_enabled: bool | None = None
    payment_card_number: str | None = Field(default=None, max_length=40)
    payment_card_holder: str | None = Field(default=None, max_length=120)
    payment_window_seconds: int | None = Field(default=None, ge=30, le=900)
    telegram_bot_username: str | None = Field(default=None, max_length=120)


class AdminPasswordUpdateRequest(BaseModel):
    new_username: str = Field(..., min_length=2, max_length=80)
    current_password: str = Field(..., min_length=1, max_length=120)
    new_password: str = Field(..., min_length=4, max_length=120)


class JobStatusUpdateRequest(BaseModel):
    status: Literal[
        "AWAITING_PAYMENT",
        "READY_IN_QUEUE",
        "WAITING_IN_QUEUE",
        "AWAITING_CONFIRMATION",
        "QUEUED_FOR_AGENT",
        "PRINTING_ON_PI",
        "SENT_TO_PRINTER",
        "COMPLETED",
        "CANCELLED",
        "ERROR",
        "DISPATCH_PRINTER",
        "APPROVE_PAYMENT",
    ]
    status_message: str = Field(default="", max_length=300)


class JobConfirmRequest(BaseModel):
    client_token: str = Field(default="", max_length=120)
    extra_seconds: int = Field(default=15, ge=5, le=120)


class QueuePublicJobItem(BaseModel):
    id: str
    student_name: str
    original_filename: str
    page_range_text: str
    selected_page_count: int
    copies: int
    color_mode: str
    duplex: str
    physical_sheets: int
    bw_sheets: int = 0
    color_sheets: int = 0
    estimated_seconds: int = 0
    queue_state: str
    status: str
    status_message: str
    queue_position: int = 0
    remaining_print_seconds: int = 0
    confirm_remaining_seconds: int = 0
    estimated_wait_seconds: int = 0
    is_mine: bool = False
    device_id: str = ""
    device_label: str = ""
    printer_name: str = ""
    printer_mode: str = ""
    created_at: str
    started_at: str = ""
    completed_at: str = ""


class LiveQueueStatusResponse(BaseModel):
    printer_busy: bool
    printer_state: Literal["IDLE", "PRINTING", "AWAITING_CONFIRMATION"]
    printer_mode: str
    default_printer_name: str = ""
    active_job: QueuePublicJobItem | None = None
    waiting_jobs: list[QueuePublicJobItem] = Field(default_factory=list)
    recent_jobs: list[QueuePublicJobItem] = Field(default_factory=list)
    waiting_count: int = 0
    total_estimated_wait_seconds: int = 0
    server_time: str


class PrinterScanRequest(BaseModel):
    network_ip: str = Field(default="", max_length=120)
    include_network_scan: bool = True
    wait_agent_seconds: float = Field(default=3.5, ge=0.0, le=8.0)


class PrinterScanSummary(BaseModel):
    total_configured: int = 0
    ready_physical_count: int = 0
    offline_physical_count: int = 0
    virtual_count: int = 0
    unconfigured_hardware_count: int = 0
    agent_online: bool = False
    agent_hostname: str = ""
    agent_last_seen: str = ""
    agent_stale_seconds: int | None = None
    scanned_at: str = ""
    layers_checked: list[str] = Field(default_factory=list)
    recommendation: str = ""
    target_ip_message: str = ""
    agent_responded: bool = False


class PrinterScanResponse(BaseModel):
    printers: list[PrinterInfo] = Field(default_factory=list)
    discovered_devices: list[PrinterInfo] = Field(default_factory=list)
    summary: PrinterScanSummary


class PrinterAutoConfigureRequest(BaseModel):
    device_uri: str = Field(..., min_length=5, max_length=300)
    queue_name: str = Field(default="", max_length=64)
    host_scope: Literal["local", "agent"] = "local"
    set_default: bool = True


class PrinterAutoConfigureResponse(BaseModel):
    ok: bool
    pending: bool = False
    queue_name: str = ""
    device_uri: str = ""
    model_used: str = ""
    message: str
    scan: PrinterScanResponse | None = None


class AgentHeartbeatRequest(BaseModel):
    hostname: str = Field(default="", max_length=120)
    printers: list[PrinterInfo] = Field(default_factory=list)
    unconfigured_devices: list[PrinterInfo] = Field(default_factory=list)
    cpu_temp_c: float | None = None
    os_info: str = Field(default="", max_length=160)
    scan_id: str = Field(default="", max_length=80)
    scan_layers: list[str] = Field(default_factory=list)
    command_result: dict[str, Any] | None = None


class AgentJobReportRequest(BaseModel):
    status: Literal["PRINTING_ON_PI", "COMPLETED", "ERROR"]
    status_message: str = Field(default="", max_length=400)


class AdminStats(BaseModel):
    total_jobs: int
    total_selected_pages: int
    total_physical_sheets: int
    total_revenue: int
    jobs_today: int


class AdminDashboardResponse(BaseModel):
    stats: AdminStats
    settings: AdminSettingsPayload
    printers: list[PrinterInfo]
    discovered_devices: list[PrinterInfo] = Field(default_factory=list)
    scan_summary: PrinterScanSummary | None = None
    jobs: list[PrintJobResponse]
    telegram: TelegramStatusInfo
