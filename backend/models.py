"""Pydantic schemas for TLG SmartPrint API."""

from __future__ import annotations

from typing import Literal

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


class PrinterInfo(BaseModel):
    name: str
    is_default: bool
    status_text: str
    is_offline: bool
    jobs_in_queue: int


class PricingInfo(BaseModel):
    bw_simplex: int
    bw_duplex: int
    color_simplex: int
    color_duplex: int
    seconds_bw_per_sheet: int = 7
    seconds_color_per_sheet: int = 14
    warmup_seconds: int = 5
    currency: str = "UZS"


class SystemStatusResponse(BaseModel):
    printer_mode: str
    hardware_connected: bool
    default_printer_name: str
    mode_description: str
    printers: list[PrinterInfo]
    pricing: PricingInfo


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


class AdminPasswordUpdateRequest(BaseModel):
    new_username: str = Field(..., min_length=2, max_length=80)
    current_password: str = Field(..., min_length=1, max_length=120)
    new_password: str = Field(..., min_length=4, max_length=120)


class JobStatusUpdateRequest(BaseModel):
    status: Literal[
        "READY_IN_QUEUE",
        "QUEUED_FOR_AGENT",
        "PRINTING_ON_PI",
        "SENT_TO_PRINTER",
        "COMPLETED",
        "CANCELLED",
        "ERROR",
        "DISPATCH_PRINTER",
    ]
    status_message: str = Field(default="", max_length=300)


class AgentHeartbeatRequest(BaseModel):
    hostname: str = Field(default="", max_length=120)
    printers: list[PrinterInfo] = Field(default_factory=list)
    cpu_temp_c: float | None = None


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
    jobs: list[PrintJobResponse]
