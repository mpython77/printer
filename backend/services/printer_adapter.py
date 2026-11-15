"""Plug-and-play printer adapter layer (DRY_RUN, Linux CUPS / Raspberry Pi, Remote Agent, Windows Spooler)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from backend.config import DEFAULT_PRINTER_NAME, PRINTER_MODE

try:
    import win32api
    import win32print
except ImportError:  # pragma: no cover - non-Windows fallback
    win32api = None
    win32print = None


def _decode_status_flags(status_code: int) -> tuple[str, bool]:
    """Convert win32print printer status bitmask into readable Uzbek label and offline flag."""
    if not win32print:
        return "Tayyor", False

    if status_code == 0:
        return "Tayyor (Normal)", False

    labels: list[str] = []
    is_offline = False

    if status_code & getattr(win32print, "PRINTER_STATUS_OFFLINE", 0x80):
        labels.append("O'chiq / Ulanmagan (Offline)")
        is_offline = True
    if status_code & getattr(win32print, "PRINTER_STATUS_ERROR", 0x02):
        labels.append("Xatolik")
        is_offline = True
    if status_code & getattr(win32print, "PRINTER_STATUS_PAPER_JAM", 0x08):
        labels.append("Qog'oz tiqilib qolgan")
        is_offline = True
    if status_code & getattr(win32print, "PRINTER_STATUS_PAPER_OUT", 0x10):
        labels.append("Qog'oz tugagan")
    if status_code & getattr(win32print, "PRINTER_STATUS_PRINTING", 0x400):
        labels.append("Chop etmoqda")
    if status_code & getattr(win32print, "PRINTER_STATUS_PAUSED", 0x01):
        labels.append("To'xtatilgan (Paused)")

    if not labels:
        labels.append(f"Holat kodi: {status_code}")

    return ", ".join(labels), is_offline


def _decode_job_status_flags(job_status: int) -> dict[str, Any]:
    """Decode Windows Print Spooler JOB_STATUS_* bitmask for completion/error monitoring."""
    if not win32print:
        return {"state": "UNKNOWN", "label": "Spooler mavjud emas", "finished": False, "error": False}

    if job_status & getattr(win32print, "JOB_STATUS_ERROR", 0x02):
        return {"state": "ERROR", "label": "Chop etishda xatolik", "finished": False, "error": True}
    if job_status & getattr(win32print, "JOB_STATUS_PAPEROUT", 0x40):
        return {"state": "PAPER_OUT", "label": "Printerda qog'oz tugadi", "finished": False, "error": True}
    if job_status & getattr(win32print, "JOB_STATUS_OFFLINE", 0x20):
        return {"state": "OFFLINE", "label": "Printer o'chiq (Offline)", "finished": False, "error": True}
    if job_status & getattr(win32print, "JOB_STATUS_PRINTED", 0x80):
        return {"state": "PRINTED", "label": "Qog'oz chiqarildi", "finished": True, "error": False}
    if job_status & getattr(win32print, "JOB_STATUS_COMPLETE", 0x1000):
        return {"state": "COMPLETE", "label": "Vazifa yakunlandi", "finished": True, "error": False}
    if job_status & getattr(win32print, "JOB_STATUS_PRINTING", 0x10):
        return {"state": "PRINTING", "label": "Printerga yuborilmoqda / chiqarilmoqda", "finished": False, "error": False}
    if job_status & getattr(win32print, "JOB_STATUS_SPOOLING", 0x08):
        return {"state": "SPOOLING", "label": "Fayl tayyorlanmoqda (Spooling)", "finished": False, "error": False}
    return {"state": "QUEUED", "label": "Navbatda kutilmoqda", "finished": False, "error": False}


def get_spooler_status(printer_name: str, document_title: str | None = None) -> dict[str, Any]:
    """Inspect Windows Print Spooler queue and printer state without modifying any jobs."""
    if not win32print or not printer_name:
        return {
            "printer_name": printer_name or "Aniqlanmagan",
            "printer_status": "Tayyor",
            "is_offline": False,
            "jobs_in_queue": 0,
            "matching_job": None,
        }

    try:
        handle = win32print.OpenPrinter(printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
            status_code = int(info.get("Status", 0) or 0)
            status_text, is_offline = _decode_status_flags(status_code)
            jobs = win32print.EnumJobs(handle, 0, 50, 1)
            matched = None
            if document_title:
                for job in jobs:
                    if document_title in (job.get("pDocument") or ""):
                        decoded = _decode_job_status_flags(int(job.get("Status", 0) or 0))
                        matched = {
                            "spooler_job_id": job.get("JobId"),
                            "pages_printed": job.get("PagesPrinted", 0),
                            "total_pages": job.get("TotalPages", 0),
                            **decoded,
                        }
                        break
            return {
                "printer_name": printer_name,
                "printer_status": status_text,
                "is_offline": is_offline,
                "jobs_in_queue": len(jobs),
                "matching_job": matched,
            }
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return {
            "printer_name": printer_name,
            "printer_status": f"Tekshirib bo'lmadi ({exc})",
            "is_offline": True,
            "jobs_in_queue": 0,
            "matching_job": None,
        }


def discover_windows_printers() -> list[dict[str, Any]]:
    """Safely enumerate installed Windows printers without sending any print jobs."""
    if not win32print:
        return []

    printers: list[dict[str, Any]] = []
    try:
        default_name = win32print.GetDefaultPrinter()
    except Exception:
        default_name = ""

    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        raw_printers = win32print.EnumPrinters(flags)
    except Exception:
        return []

    for entry in raw_printers:
        name = entry[2]
        status_text = "Tayyor"
        is_offline = False
        jobs_in_queue = 0

        try:
            handle = win32print.OpenPrinter(name)
            try:
                info = win32print.GetPrinter(handle, 2)
                status_code = int(info.get("Status", 0) or 0)
                jobs_in_queue = int(info.get("cJobs", 0) or 0)
                attributes = int(info.get("Attributes", 0) or 0)
                work_offline = bool(attributes & 0x00000400)  # PRINTER_ATTRIBUTE_WORK_OFFLINE
                status_text, is_offline = _decode_status_flags(status_code)
                if work_offline and not is_offline:
                    status_text = "O'chiq / Ulanmagan (Offline)"
                    is_offline = True
            finally:
                win32print.ClosePrinter(handle)
        except Exception:
            status_text = "Tekshirib bo'lmadi"

        printers.append(
            {
                "name": name,
                "is_default": name == default_name,
                "status_text": status_text,
                "is_offline": is_offline,
                "jobs_in_queue": jobs_in_queue,
            }
        )

    return printers


def _run_cups_cmd(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    """Execute a CUPS CLI utility safely without raising on non-zero return codes."""
    executable = shutil.which(cmd[0])
    if not executable:
        return None
    try:
        return subprocess.run(
            [executable, *cmd[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None


def discover_cups_printers() -> list[dict[str, Any]]:
    """Safely enumerate installed CUPS printers (Linux / Raspberry Pi / macOS)."""
    if not shutil.which("lpstat"):
        return []

    default_name = ""
    res_default = _run_cups_cmd(["lpstat", "-d"])
    if res_default and res_default.returncode == 0:
        match = re.search(r":\s*(\S+)", res_default.stdout)
        if match:
            default_name = match.group(1).strip()

    queue_counts: dict[str, int] = {}
    res_jobs = _run_cups_cmd(["lpstat", "-W", "not-completed", "-o"])
    if res_jobs and res_jobs.returncode == 0:
        for line in res_jobs.stdout.splitlines():
            job_match = re.match(r"^([^\s-]+(?:-[^\s-]+)*)-\d+\s+", line.strip())
            if job_match:
                pname = job_match.group(1)
                queue_counts[pname] = queue_counts.get(pname, 0) + 1

    printers: list[dict[str, Any]] = []
    res_printers = _run_cups_cmd(["lpstat", "-p"])
    if not res_printers or res_printers.returncode != 0:
        return printers

    for raw_line in res_printers.stdout.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("printer "):
            continue
        match = re.match(r"^printer\s+(\S+)\s+(.+)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        name = match.group(1).strip()
        rest = match.group(2).strip()
        rest_lower = rest.lower()

        is_offline = "disabled" in rest_lower or "offline" in rest_lower or "not connected" in rest_lower
        if "now printing" in rest_lower:
            status_text = "Chop etmoqda (CUPS)"
        elif is_offline:
            status_text = "O'chiq / To'xtatilgan (CUPS Disabled)"
        elif "is idle" in rest_lower:
            status_text = "Tayyor (CUPS Idle)"
        else:
            status_text = rest[:80]

        printers.append(
            {
                "name": name,
                "is_default": name == default_name,
                "status_text": status_text,
                "is_offline": is_offline,
                "jobs_in_queue": queue_counts.get(name, 0),
            }
        )

    return printers


def discover_all_printers(agent_printers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Combine local (Windows Spooler + Linux CUPS) and remote Raspberry Pi agent printers."""
    combined: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for p in [*discover_windows_printers(), *discover_cups_printers()]:
        name = str(p.get("name", "")).strip()
        if name and name not in seen_names:
            seen_names.add(name)
            combined.append(p)

    for p in agent_printers or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        combined.append(
            {
                "name": name,
                "is_default": bool(p.get("is_default", False)),
                "status_text": str(p.get("status_text") or "Raspberry Pi Agent"),
                "is_offline": bool(p.get("is_offline", False)),
                "jobs_in_queue": int(p.get("jobs_in_queue", 0) or 0),
            }
        )

    return combined


def get_cups_spooler_status(printer_name: str, document_title: str | None = None) -> dict[str, Any]:
    """Inspect Linux CUPS printer and active job queue using lpstat without altering jobs."""
    if not shutil.which("lpstat"):
        return {
            "printer_name": printer_name or "CUPS mavjud emas",
            "printer_status": "CUPS lpstat topilmadi",
            "is_offline": False,
            "jobs_in_queue": 0,
            "matching_job": None,
        }

    printers = discover_cups_printers()
    target = next((p for p in printers if p["name"] == printer_name), None)
    if not target and printers:
        target = next((p for p in printers if p["is_default"]), printers[0])

    active_jobs = 0
    matching_job = None
    res_not_done = _run_cups_cmd(["lpstat", "-W", "not-completed", "-o"])
    if res_not_done and res_not_done.returncode == 0:
        lines = [ln.strip() for ln in res_not_done.stdout.splitlines() if ln.strip()]
        for ln in lines:
            if not printer_name or ln.startswith(f"{printer_name}-"):
                active_jobs += 1
                if document_title and document_title in ln:
                    matching_job = {
                        "cups_job": ln.split()[0],
                        "state": "PRINTING",
                        "label": "CUPS navbatida chop etilmoqda",
                        "finished": False,
                        "error": False,
                    }

    if target:
        return {
            "printer_name": target["name"],
            "printer_status": target["status_text"],
            "is_offline": target["is_offline"],
            "jobs_in_queue": active_jobs or target["jobs_in_queue"],
            "matching_job": matching_job,
        }

    return {
        "printer_name": printer_name or "Aniqlanmagan",
        "printer_status": "CUPS printeri topilmadi",
        "is_offline": True,
        "jobs_in_queue": active_jobs,
        "matching_job": matching_job,
    }


_ALLOWED_PAPER_SIZES = {"A4", "A5", "Letter"}


def _sanitize_printer_name(name: str | None) -> str:
    """Strip unsafe shell/option characters from printer names while preserving valid device names."""
    clean = re.sub(r'[\x00-\x1f"\\;|`$&<>]+', "", (name or "").strip())
    clean = clean.lstrip("-").strip()
    return clean[:120]


def _sanitize_job_title(title: str | None) -> str:
    """Sanitize print job title before passing to external printer tools."""
    clean = re.sub(r'[\x00-\x1f"\\;|`$&<>]+', "_", (title or "").strip())
    clean = clean.lstrip("-").strip()
    return (clean or "TLG-Print")[:80]


def build_lp_command(printer_name: str | None, job: dict[str, Any], output_pdf_path: Path) -> list[str]:
    """Construct CUPS `lp` CLI arguments matching print job options."""
    cmd = ["lp"]
    clean_printer = _sanitize_printer_name(printer_name)
    if clean_printer:
        cmd.extend(["-d", clean_printer])

    copies = max(1, int(job.get("copies", 1)))
    cmd.extend(["-n", str(copies)])

    raw_title = str(job.get("original_filename") or job.get("document_name") or f"TLG-{job.get('id', 'job')}")
    title = _sanitize_job_title(raw_title)
    if title:
        cmd.extend(["-t", title])

    raw_paper = str(job.get("paper_size", "A4")).strip()
    paper_size = raw_paper if raw_paper in _ALLOWED_PAPER_SIZES else "A4"
    cmd.extend(["-o", f"media={paper_size}"])

    duplex = str(job.get("duplex", "simplex")).strip().lower()
    sides_opt = "two-sided-long-edge" if duplex == "duplex" else "one-sided"
    cmd.extend(["-o", f"sides={sides_opt}"])

    color_mode = str(job.get("color_mode", "bw")).strip().lower()
    color_opt = "Gray" if color_mode == "bw" else "RGB"
    cmd.extend(["-o", f"ColorModel={color_opt}"])

    cmd.extend(["-o", "fit-to-page"])
    cmd.append(str(output_pdf_path))
    return cmd


class PrinterAdapter(ABC):
    """Strategy interface for hardware printer dispatch."""

    mode_name: str

    @abstractmethod
    def submit_job(self, job: dict[str, Any], output_pdf_path: Path) -> dict[str, str]:
        """Submit a sliced print-ready PDF and return status & status_message."""


class DryRunPrinterAdapter(PrinterAdapter):
    """Safe default adapter: creates the sliced PDF and records the job without hardware printing."""

    mode_name = "DRY_RUN"

    def submit_job(self, job: dict[str, Any], output_pdf_path: Path) -> dict[str, str]:
        printer_label = job.get("printer_name") or "Tanlanmagan (Keyin ulanadi)"
        segments = job.get("print_segments") or []
        if job.get("color_mode") == "mixed" and segments:
            detail = (
                f"{job.get('bw_sheets', 0)} oq-qora + {job.get('color_sheets', 0)} rangli varaq "
                f"({len(segments)} ta ketma-ket segmentda tayyorlandi)."
            )
        else:
            detail = f"Hujjat tanlangan {job['selected_page_count']} ta bet bo'yicha tayyorlandi."
        return {
            "status": "READY_IN_QUEUE",
            "status_message": (
                f"{detail} Printer hozircha ulanmagan ({printer_label}) — Test rejimi: jismoniy printerga yuborilmadi."
            ),
        }


class LinuxCupsPrinterAdapter(PrinterAdapter):
    """Direct Raspberry Pi / Linux CUPS adapter calling `lp`."""

    mode_name = "LINUX_CUPS"

    def submit_job(self, job: dict[str, Any], output_pdf_path: Path) -> dict[str, str]:
        lp_bin = shutil.which("lp")
        if not lp_bin:
            return {
                "status": "ERROR",
                "status_message": "CUPS `lp` buyrug'i topilmadi — Raspberry Pi/Linux da `cups` paketini o'rnating.",
            }

        target_printer = (job.get("printer_name") or DEFAULT_PRINTER_NAME or "").strip()
        segments = job.get("print_segments") or []
        printer_label = target_printer or "Standart CUPS printer"

        try:
            if len(segments) > 1:
                copies = max(1, int(job.get("copies", 1)))
                cups_ids: list[str] = []
                for _copy_idx in range(copies):
                    for seg in segments:
                        seg_file = output_pdf_path.parent / seg["pdf_filename"]
                        seg_job = {
                            **job,
                            "copies": 1,
                            "color_mode": seg["color_mode"],
                            "original_filename": f"{job.get('original_filename', 'doc')}-s{seg['segment_index']}",
                        }
                        cmd = build_lp_command(target_printer, seg_job, seg_file)
                        cmd[0] = lp_bin
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
                        if proc.returncode != 0:
                            err_detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
                            return {
                                "status": "ERROR",
                                "status_message": f"CUPS segment #{seg['segment_index']} xatoligi: {err_detail}",
                            }
                        match = re.search(r"request id is\s+(\S+)", proc.stdout or "", flags=re.IGNORECASE)
                        if match:
                            cups_ids.append(match.group(1))
                suffix = f" ({len(segments)} ta segment, CUPS: {', '.join(cups_ids[:3])})" if cups_ids else ""
                return {
                    "status": "SENT_TO_PRINTER",
                    "status_message": f"Aralash hujjat '{printer_label}' CUPS printeriga ketma-ket yuborildi{suffix}.",
                }

            cmd = build_lp_command(target_printer, job, output_pdf_path)
            cmd[0] = lp_bin
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
            if proc.returncode != 0:
                err_detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
                return {
                    "status": "ERROR",
                    "status_message": f"CUPS printerga yuborishda xatolik: {err_detail}",
                }

            out_text = (proc.stdout or "").strip()
            match = re.search(r"request id is\s+(\S+)", out_text, flags=re.IGNORECASE)
            cups_id = match.group(1) if match else ""
            suffix = f" (CUPS ID: {cups_id})" if cups_id else ""
            return {
                "status": "SENT_TO_PRINTER",
                "status_message": f"Hujjat '{printer_label}' CUPS printeriga yuborildi{suffix}.",
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "status_message": f"CUPS jarayonida xatolik: {exc}",
            }


class RemoteAgentPrinterAdapter(PrinterAdapter):
    """Cloud/VPS queue adapter waiting for the Raspberry Pi print bridge to claim and print."""

    mode_name = "REMOTE_AGENT"

    def submit_job(self, job: dict[str, Any], output_pdf_path: Path) -> dict[str, str]:
        printer_label = (job.get("printer_name") or DEFAULT_PRINTER_NAME or "Raspberry Pi printer").strip()
        return {
            "status": "QUEUED_FOR_AGENT",
            "status_message": (
                f"Hujjat tayyorlandi va Raspberry Pi printer ko'prigi ({printer_label}) uchun navbatga qo'yildi."
            ),
        }


class WindowsSpoolerPrinterAdapter(PrinterAdapter):
    """Live Windows Spooler adapter (activated when TLG_PRINTER_MODE=WINDOWS_SPOOLER)."""

    mode_name = "WINDOWS_SPOOLER"

    def submit_job(self, job: dict[str, Any], output_pdf_path: Path) -> dict[str, str]:
        if not win32print or not win32api:
            return {
                "status": "ERROR",
                "status_message": "pywin32 kutubxonasi topilmadi — Windows Spooler ishga tushmadi.",
            }

        target_printer = _sanitize_printer_name(job.get("printer_name") or DEFAULT_PRINTER_NAME)
        if not target_printer:
            try:
                target_printer = _sanitize_printer_name(win32print.GetDefaultPrinter())
            except Exception as exc:
                return {
                    "status": "ERROR",
                    "status_message": f"Standart printer topilmadi: {exc}",
                }

        try:
            handle = win32print.OpenPrinter(target_printer)
            win32print.ClosePrinter(handle)

            copies = max(1, int(job.get("copies", 1)))
            for _ in range(copies):
                win32api.ShellExecute(
                    0,
                    "printto",
                    str(output_pdf_path),
                    f'"{target_printer}"',
                    ".",
                    0,
                )

            return {
                "status": "SENT_TO_PRINTER",
                "status_message": f"Hujjat '{target_printer}' printer navbatiga muvaffaqiyatli yuborildi.",
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "status_message": f"Printerga yuborishda xatolik: {exc}",
            }


def get_active_printer_adapter(mode: str | None = None) -> PrinterAdapter:
    """Return the active printer adapter according to configuration."""
    effective_mode = (mode or PRINTER_MODE).upper()
    if effective_mode == "LINUX_CUPS":
        return LinuxCupsPrinterAdapter()
    if effective_mode == "REMOTE_AGENT":
        return RemoteAgentPrinterAdapter()
    if effective_mode == "WINDOWS_SPOOLER":
        return WindowsSpoolerPrinterAdapter()
    return DryRunPrinterAdapter()
