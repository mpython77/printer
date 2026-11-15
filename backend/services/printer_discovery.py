"""Multi-layer physical, USB, network (mDNS/IPP/RAW), CUPS, and remote Raspberry Pi printer discovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import time
from typing import Any

from backend.config import AGENT_STALE_SECONDS

try:
    import win32print
except ImportError:  # pragma: no cover - non-Windows fallback
    win32print = None

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
else:  # pragma: no cover - non-Windows
    ctypes = None
    wintypes = None


_VIRTUAL_PRINTER_KEYWORDS = (
    "onenote",
    "microsoft print to pdf",
    "microsoft xps document writer",
    "fax",
    "adobe pdf",
    "foxit",
    "cutepdf",
    "pdfcreator",
    "cups-pdf",
    "anydesk printer",
    "print to pdf",
)

_VIRTUAL_PORTS = ("nul:", "portprompt:", "file:", "shrpt", "cups-pdf:/")

_SAFE_URI_SCHEMES = ("usb://", "ipp://", "ipps://", "dnssd://", "socket://", "lpd://")
_MDNS_ADDR = "224.0.0.251"
_MDNS_PORT = 5353
_MDNS_SERVICES = ("_ipp._tcp.local", "_ipps._tcp.local", "_pdl-datastream._tcp.local")
_PRINTER_PROBE_PORTS = (631, 9100, 515)


def decode_windows_status_flags(status_code: int) -> tuple[str, bool]:
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


def is_virtual_printer(name: str, port_or_uri: str = "", driver_name: str = "") -> bool:
    """Return True if queue corresponds to a software/virtual printer rather than physical hardware."""
    combined = f"{name} {driver_name}".lower()
    if any(kw in combined for kw in _VIRTUAL_PRINTER_KEYWORDS):
        return True
    port_lower = (port_or_uri or "").strip().lower()
    if any(port_lower.startswith(vp) for vp in _VIRTUAL_PORTS):
        return True
    return False


def classify_connection(
    port_or_uri: str = "",
    driver_name: str = "",
    is_virtual: bool = False,
    configured: bool = True,
) -> str:
    """Classify connection medium (`USB`, `NETWORK`, `VIRTUAL`, `LOCAL`, `UNCONFIGURED_*`)."""
    if is_virtual:
        return "VIRTUAL"
    port_lower = (port_or_uri or "").strip().lower()
    low = f"{port_lower} {driver_name}".strip().lower()
    is_usb = port_lower.startswith("usb://") or bool(re.match(r"^(usb|dot4|cnusb)\d*\b", port_lower))
    is_net = (
        any(
            port_lower.startswith(prefix)
            for prefix in ("ipp://", "ipps://", "dnssd://", "socket://", "lpd://", "http://", "https://", "smb://", "ip_", "wsd", "cnbjnp", "bjnp")
        )
        or "network" in low
    )
    if not configured:
        return "UNCONFIGURED_NETWORK" if is_net and not is_usb else "UNCONFIGURED_USB"
    if is_usb:
        return "USB"
    if is_net:
        return "NETWORK"
    return "LOCAL"


def sanitize_queue_name(raw_name: str, fallback: str = "TLG_Printer") -> str:
    """Produce a valid CUPS queue identifier (letters, digits, underscore, dash)."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (raw_name or "").strip()).strip("_.-")
    return (cleaned or fallback)[:64]


def sanitize_device_uri(uri: str) -> str:
    """Validate printer device URI against strict safe schemes before passing to CUPS `lpadmin`."""
    clean = (uri or "").strip()
    if not clean or len(clean) > 300:
        raise ValueError("Printer URI bo'sh yoki juda uzun.")
    if clean.startswith("-") or re.search(r"[\x00-\x1f\s\"'`$;|&<>\\]", clean):
        raise ValueError("Printer URI da ruxsat etilmagan belgilar mavjud.")
    if not any(clean.lower().startswith(scheme) for scheme in _SAFE_URI_SCHEMES):
        raise ValueError("Faqat usb://, ipp://, ipps://, dnssd://, socket:// yoki lpd:// URI qo'llab-quvvatlanadi.")
    return clean


def _normalize_match_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _extract_ipv4_from_port(port_or_uri: str) -> str:
    raw = (port_or_uri or "").strip()
    m_ip_port = re.match(r"^IP_(\d{1,3}(?:\.\d{1,3}){3})$", raw, flags=re.IGNORECASE)
    if m_ip_port:
        return m_ip_port.group(1)
    m_uri = re.match(r"^(?:ipps?|socket|lpd|https?)://\[?(\d{1,3}(?:\.\d{1,3}){3})\]?(?::(\d+))?", raw, flags=re.IGNORECASE)
    if m_uri:
        return m_uri.group(1)
    return ""


def _probe_tcp_port(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_host_printer_ports(host: str, timeout: float = 0.45) -> list[int]:
    """Check standard network printer TCP ports (631 IPP, 9100 RAW, 515 LPD) concurrently."""
    open_ports: list[int] = []
    with ThreadPoolExecutor(max_workers=len(_PRINTER_PROBE_PORTS)) as pool:
        futures = {port: pool.submit(_probe_tcp_port, host, port, timeout) for port in _PRINTER_PROBE_PORTS}
        for port in _PRINTER_PROBE_PORTS:
            try:
                if futures[port].result():
                    open_ports.append(port)
            except Exception:
                pass
    return open_ports


def _run_cmd(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        return subprocess.run(
            [exe, *cmd[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Layer 1A: Windows Live USB Hardware PnP (setupapi.dll DIGCF_PRESENT) + Spooler
# ---------------------------------------------------------------------------


def probe_windows_usb_printers() -> dict[str, Any]:
    """Query physically plugged-in Windows USB printers via setupapi DIGCF_PRESENT (<10ms)."""
    if sys.platform != "win32" or ctypes is None or wintypes is None:
        return {"ok": False, "devices": []}

    class _SpDevinfoData(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("ClassGuid", ctypes.c_byte * 16),
            ("DevInst", wintypes.DWORD),
            ("Reserved", ctypes.c_void_p),
        ]

    try:
        setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
        setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
        setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
        setupapi.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_SpDevinfoData)]
        setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
        setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_SpDevinfoData),
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
        setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_SpDevinfoData),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    except Exception:
        return {"ok": False, "devices": []}

    digcf_present_all = 0x02 | 0x04  # DIGCF_PRESENT | DIGCF_ALLCLASSES
    invalid_handle = wintypes.HANDLE(-1).value
    spdrp_devicedesc = 0
    spdrp_service = 4
    spdrp_mfg = 11
    spdrp_friendlyname = 12

    def _read_prop(h: Any, dev: Any, prop_id: int) -> str:
        buf = ctypes.create_unicode_buffer(512)
        if setupapi.SetupDiGetDeviceRegistryPropertyW(h, ctypes.byref(dev), prop_id, None, buf, 1024, None):
            return buf.value.strip()
        return ""

    usbprint_devices: list[dict[str, Any]] = []
    usb_service_devices: list[dict[str, Any]] = []

    for enumerator in ("USBPRINT", "USB"):
        handle = setupapi.SetupDiGetClassDevsW(None, enumerator, None, digcf_present_all)
        if not handle or handle == invalid_handle:
            continue
        try:
            idx = 0
            while True:
                dev_data = _SpDevinfoData(cbSize=ctypes.sizeof(_SpDevinfoData))
                if not setupapi.SetupDiEnumDeviceInfo(handle, idx, ctypes.byref(dev_data)):
                    break
                idx += 1

                inst_buf = ctypes.create_unicode_buffer(512)
                if not setupapi.SetupDiGetDeviceInstanceIdW(handle, ctypes.byref(dev_data), inst_buf, 512, None):
                    continue
                instance_id = inst_buf.value.strip()
                if enumerator == "USB":
                    svc = _read_prop(handle, dev_data, spdrp_service).lower()
                    if "usbprint" not in svc:
                        continue

                friendly = _read_prop(handle, dev_data, spdrp_friendlyname)
                desc = _read_prop(handle, dev_data, spdrp_devicedesc)
                mfg = _read_prop(handle, dev_data, spdrp_mfg)

                port_hint = ""
                model_hint = ""
                parts = instance_id.split("\\")
                if enumerator == "USBPRINT":
                    if len(parts) >= 2:
                        model_hint = parts[1].replace("_", " ").strip()
                    tail = parts[-1] if parts else ""
                    m_port = re.search(r"(USB\d+|DOT4_\d+|CNUSB\d+)", tail, flags=re.IGNORECASE)
                    if m_port:
                        port_hint = m_port.group(1).upper()

                display_name = model_hint or friendly or desc or "USB Printer"
                if friendly and friendly.lower() not in {"microsoft ipp class driver", "usb printing support"}:
                    display_name = friendly
                elif model_hint:
                    display_name = model_hint.title() if model_hint.isupper() else model_hint

                entry = {
                    "name": display_name,
                    "friendly_name": friendly,
                    "device_desc": desc,
                    "manufacturer": mfg,
                    "instance_id": instance_id,
                    "port_hint": port_hint,
                    "model_hint": model_hint,
                    "enumerator": enumerator,
                }
                if enumerator == "USBPRINT":
                    usbprint_devices.append(entry)
                else:
                    usb_service_devices.append(entry)
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(handle)

    devices = list(usbprint_devices)
    if not devices and usb_service_devices:
        devices = usb_service_devices[:1]

    return {"ok": True, "devices": devices, "raw_usb_support_count": len(usb_service_devices)}


def discover_windows_printers(
    probe_network_ports: bool = False,
    usb_probe: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate Windows Spooler queues enriched with port, capabilities, and live USB/IP presence."""
    if not win32print:
        return []

    usb_info = usb_probe if usb_probe is not None else probe_windows_usb_printers()
    usb_devices = usb_info.get("devices", []) if usb_info.get("ok") else []
    active_usb_ports = {d["port_hint"].upper() for d in usb_devices if d.get("port_hint")}
    active_usb_norms = [
        _normalize_match_text(f"{d.get('model_hint', '')} {d.get('name', '')}")
        for d in usb_devices
    ]

    try:
        default_name = win32print.GetDefaultPrinter()
    except Exception:
        default_name = ""

    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        raw_printers = win32print.EnumPrinters(flags)
    except Exception:
        return []

    printers: list[dict[str, Any]] = []
    for entry in raw_printers:
        name = entry[2]
        status_text = "Tayyor"
        is_offline = False
        jobs_in_queue = 0
        port_name = ""
        driver_name = ""
        supports_color: bool | None = None
        supports_duplex: bool | None = None

        try:
            handle = win32print.OpenPrinter(name)
            try:
                info = win32print.GetPrinter(handle, 2)
                status_code = int(info.get("Status", 0) or 0)
                jobs_in_queue = int(info.get("cJobs", 0) or 0)
                attributes = int(info.get("Attributes", 0) or 0)
                port_name = str(info.get("pPortName") or "").strip()
                driver_name = str(info.get("pDriverName") or "").strip()
                work_offline = bool(attributes & 0x00000400)  # PRINTER_ATTRIBUTE_WORK_OFFLINE
                status_text, is_offline = decode_windows_status_flags(status_code)
                if work_offline and not is_offline:
                    status_text = "O'chiq / Ulanmagan (Offline)"
                    is_offline = True
            finally:
                win32print.ClosePrinter(handle)
        except Exception:
            status_text = "Tekshirib bo'lmadi"

        virtual = is_virtual_printer(name, port_name, driver_name)
        conn_type = classify_connection(port_name, driver_name, is_virtual=virtual, configured=True)

        if not virtual and hasattr(win32print, "DeviceCapabilities"):
            try:
                dc_color = win32print.DeviceCapabilities(name, port_name, 32)  # DC_COLORDEVICE
                supports_color = bool(dc_color == 1)
            except Exception:
                supports_color = None
            try:
                dc_duplex = win32print.DeviceCapabilities(name, port_name, 7)  # DC_DUPLEX
                supports_duplex = bool(dc_duplex == 1)
            except Exception:
                supports_duplex = None

        hardware_present: bool | None = None
        if virtual:
            hardware_present = None
        elif conn_type == "USB" and usb_info.get("ok"):
            port_upper = port_name.split(",")[0].strip().upper()
            norm_q = _normalize_match_text(name)
            matched_usb = (port_upper in active_usb_ports) or any(
                tok and (tok in norm_q or norm_q in tok) for tok in active_usb_norms
            )
            if port_upper.startswith("USB"):
                hardware_present = matched_usb
                if not matched_usb and not is_offline:
                    is_offline = True
                    status_text = "USB kabel uzilgan (printer ulanmagan)"
            elif matched_usb:
                hardware_present = True
        elif conn_type == "NETWORK":
            if is_offline:
                hardware_present = False
            elif probe_network_ports:
                ipv4 = _extract_ipv4_from_port(port_name)
                if ipv4:
                    open_ports = _probe_host_printer_ports(ipv4, timeout=0.35)
                    hardware_present = bool(open_ports)
                    if not open_ports:
                        is_offline = True
                        status_text = f"Tarmoq printeri ({ipv4}) javob bermayapti"

        printers.append(
            {
                "name": name,
                "is_default": name == default_name,
                "status_text": status_text,
                "is_offline": is_offline,
                "jobs_in_queue": jobs_in_queue,
                "source": "windows_spooler",
                "connection_type": conn_type,
                "port_or_uri": port_name,
                "driver_name": driver_name,
                "hardware_present": hardware_present,
                "is_virtual": virtual,
                "ready_to_print": (not is_offline) and (not virtual) and (hardware_present is not False),
                "configured": True,
                "supports_color": supports_color,
                "supports_duplex": supports_duplex,
                "host_label": "Asosiy server (Windows)",
                "can_auto_configure": False,
                "suggested_queue_name": "",
            }
        )

    return printers


# ---------------------------------------------------------------------------
# Layer 1B: Linux / macOS / Raspberry Pi CUPS + lpinfo -v + USB sysfs
# ---------------------------------------------------------------------------


def discover_cups_backends(timeout: float = 5.0) -> dict[str, Any]:
    """Run `lpinfo -v` to list all physically connected USB and network printer URIs seen by CUPS."""
    if not shutil.which("lpinfo"):
        return {"ok": False, "devices": []}

    res = _run_cmd(["lpinfo", "-v"], timeout=timeout)
    if not res or res.returncode != 0:
        return {"ok": False, "devices": []}

    devices: list[dict[str, Any]] = []
    seen_uris: set[str] = set()
    for raw in res.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        dev_class, uri = parts[0].strip().lower(), parts[1].strip()
        if "://" not in uri or uri in seen_uris:
            continue
        scheme, rest = uri.split("://", 1)
        if not rest.strip("/"):
            continue
        if f"{scheme.lower()}://" not in _SAFE_URI_SCHEMES:
            continue
        seen_uris.add(uri)

        model_name = _derive_name_from_uri(uri)
        devices.append(
            {
                "name": model_name,
                "port_or_uri": uri,
                "backend_class": dev_class,
                "connection_type": "UNCONFIGURED_USB" if scheme.lower() == "usb" else "UNCONFIGURED_NETWORK",
                "source": "cups_backend",
            }
        )

    return {"ok": True, "devices": devices}


def _derive_name_from_uri(uri: str) -> str:
    """Extract a readable hardware label from a CUPS USB/IPP/DNS-SD URI."""
    from urllib.parse import unquote

    decoded = unquote(uri)
    scheme, _, rest = decoded.partition("://")
    host_part = rest.split("?", 1)[0].strip("/")
    if scheme.lower() == "usb":
        segments = [seg.strip() for seg in host_part.split("/") if seg.strip()]
        if segments:
            return " ".join(segments[:2])
    if scheme.lower() == "dnssd":
        first = host_part.split("._", 1)[0].strip()
        if first:
            return first
    if host_part:
        return f"Printer ({host_part.split('/')[0]})"
    return "Printer"


def discover_linux_usb_hardware(usb_root: Path | None = None) -> list[dict[str, Any]]:
    """Inspect Linux `/sys/bus/usb/devices` for active USB Printer Class (`07`) hardware (<5ms)."""
    root = usb_root or Path("/sys/bus/usb/devices")
    if not root.exists():
        return []

    found: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _read_txt(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore").strip() if p.exists() else ""
        except Exception:
            return ""

    for entry in sorted(root.iterdir()):
        try:
            if not entry.is_dir():
                continue
            iface_class = _read_txt(entry / "bInterfaceClass").lower()
            dev_class = _read_txt(entry / "bDeviceClass").lower()
            if iface_class != "07" and dev_class != "07":
                continue

            # Interface paths look like `1-1:1.0`; parent USB device is `1-1`.
            dev_dir = entry
            if ":" in entry.name:
                candidate_parent = root / entry.name.split(":", 1)[0]
                if candidate_parent.exists():
                    dev_dir = candidate_parent

            vid = _read_txt(dev_dir / "idVendor")
            pid = _read_txt(dev_dir / "idProduct")
            mfg = _read_txt(dev_dir / "manufacturer")
            product = _read_txt(dev_dir / "product")
            serial = _read_txt(dev_dir / "serial")

            dedup_key = f"{vid}:{pid}:{serial or dev_dir.name}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            label = " ".join(part for part in (mfg, product) if part).strip() or f"USB Printer ({vid}:{pid})"
            found.append(
                {
                    "name": label,
                    "manufacturer": mfg,
                    "product": product,
                    "serial": serial,
                    "port_or_uri": f"usb-hw://{vid}:{pid}" + (f"?serial={serial}" if serial else ""),
                    "source": "linux_usb",
                }
            )
        except Exception:
            continue

    return found


def _inspect_cups_queue_capabilities(queue_name: str) -> tuple[bool | None, bool | None]:
    """Inspect `lpoptions -p <name> -l` for color and duplex capabilities."""
    if not shutil.which("lpoptions"):
        return None, None
    res = _run_cmd(["lpoptions", "-p", queue_name, "-l"], timeout=2.5)
    if not res or res.returncode != 0:
        return None, None
    supports_color: bool | None = None
    supports_duplex: bool | None = None
    for line in res.stdout.splitlines():
        low = line.lower()
        if "colormodel/" in low or low.startswith("color/") or "printoutmode/" in low:
            supports_color = any(tok in low for tok in ("rgb", "cmyk", "color"))
        elif "duplex/" in low:
            supports_duplex = any(tok in low for tok in ("duplexnotumble", "duplextumble", "two-sided"))
    return supports_color, supports_duplex


def _uris_refer_same_device(uri_a: str, uri_b: str) -> bool:
    """Compare two CUPS device URIs allowing serial/interface query normalization."""
    if not uri_a or not uri_b:
        return False
    a = uri_a.strip().lower()
    b = uri_b.strip().lower()
    if a == b:
        return True
    base_a, _, qa = a.partition("?")
    base_b, _, qb = b.partition("?")
    if base_a == base_b:
        m_sa = re.search(r"serial=([^&]+)", qa)
        m_sb = re.search(r"serial=([^&]+)", qb)
        if m_sa and m_sb:
            return m_sa.group(1) == m_sb.group(1)
        return True
    return False


def discover_cups_printers(
    include_capabilities: bool = False,
    backends_info: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate CUPS printers enriched with device URIs, live backend presence, and capabilities."""
    if not shutil.which("lpstat"):
        return []

    default_name = ""
    res_default = _run_cmd(["lpstat", "-d"])
    if res_default and res_default.returncode == 0:
        match = re.search(r":\s*(\S+)", res_default.stdout)
        if match:
            default_name = match.group(1).strip()

    uri_by_printer: dict[str, str] = {}
    res_uris = _run_cmd(["lpstat", "-v"])
    if res_uris and res_uris.returncode == 0:
        for line in res_uris.stdout.splitlines():
            m_uri = re.match(r"^(?:device|уст[а-я]+).*?\s+(?:for|для)\s+(\S+?):\s*(\S.+)$", line.strip(), flags=re.IGNORECASE)
            if m_uri:
                uri_by_printer[m_uri.group(1).strip()] = m_uri.group(2).strip()

    queue_counts: dict[str, int] = {}
    res_jobs = _run_cmd(["lpstat", "-W", "not-completed", "-o"])
    if res_jobs and res_jobs.returncode == 0:
        for line in res_jobs.stdout.splitlines():
            job_match = re.match(r"^([^\s]+)-\d+\s+", line.strip())
            if job_match:
                pname = job_match.group(1)
                queue_counts[pname] = queue_counts.get(pname, 0) + 1

    res_printers = _run_cmd(["lpstat", "-p"])
    if not res_printers or res_printers.returncode != 0:
        return []

    live_uris = [
        d.get("port_or_uri", "")
        for d in (backends_info or {}).get("devices", [])
        if d.get("port_or_uri")
    ]
    backends_checked = bool(backends_info and backends_info.get("ok"))

    printers: list[dict[str, Any]] = []
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

        uri = uri_by_printer.get(name, "")
        virtual = is_virtual_printer(name, uri, "")
        conn_type = classify_connection(uri, "", is_virtual=virtual, configured=True)

        hardware_present: bool | None = None
        if backends_checked and not virtual and uri:
            if conn_type == "USB":
                hardware_present = any(_uris_refer_same_device(uri, live_u) for live_u in live_uris)
                if not hardware_present and not is_offline:
                    is_offline = True
                    status_text = "USB kabel uzilgan yoki printer o'chiq"
            elif conn_type == "NETWORK":
                ipv4 = _extract_ipv4_from_port(uri)
                if any(_uris_refer_same_device(uri, live_u) for live_u in live_uris):
                    hardware_present = True
                elif ipv4:
                    hardware_present = bool(_probe_host_printer_ports(ipv4, timeout=0.35))
                    if not hardware_present and not is_offline:
                        is_offline = True
                        status_text = f"Tarmoq printeri ({ipv4}) javob bermayapti"

        supports_color, supports_duplex = (
            _inspect_cups_queue_capabilities(name)
            if (include_capabilities and not virtual)
            else (None, None)
        )

        printers.append(
            {
                "name": name,
                "is_default": name == default_name,
                "status_text": status_text,
                "is_offline": is_offline,
                "jobs_in_queue": queue_counts.get(name, 0),
                "source": "linux_cups",
                "connection_type": conn_type,
                "port_or_uri": uri,
                "driver_name": "",
                "hardware_present": hardware_present,
                "is_virtual": virtual,
                "ready_to_print": (not is_offline) and (not virtual) and (hardware_present is not False),
                "configured": True,
                "supports_color": supports_color,
                "supports_duplex": supports_duplex,
                "host_label": "Asosiy server (CUPS)",
                "can_auto_configure": False,
                "suggested_queue_name": "",
            }
        )

    return printers


# ---------------------------------------------------------------------------
# Layer 2: Pure-Python LAN mDNS (DNS-SD) + Optional Direct Network IP Probe
# ---------------------------------------------------------------------------


def _encode_dns_name(name: str) -> bytes:
    parts = [part.encode("utf-8") for part in name.strip(".").split(".") if part]
    return b"".join(bytes([len(p)]) + p for p in parts) + b"\x00"


def _build_mdns_ptr_query(service_names: tuple[str, ...]) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, len(service_names), 0, 0, 0)
    questions = b"".join(_encode_dns_name(svc) + struct.pack("!HH", 12, 1) for svc in service_names)
    return header + questions


def _read_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    seen_offsets: set[int] = set()
    end_offset = offset
    jumped = False
    pos = offset

    while pos < len(data):
        if pos in seen_offsets or len(seen_offsets) > 64:
            break
        seen_offsets.add(pos)
        length = data[pos]
        if length == 0:
            if not jumped:
                end_offset = pos + 1
            break
        if (length & 0xC0) == 0xC0:
            if pos + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[pos + 1]
            if not jumped:
                end_offset = pos + 2
                jumped = True
            pos = ptr
            continue
        pos += 1
        if pos + length > len(data):
            break
        labels.append(data[pos : pos + length].decode("utf-8", errors="replace"))
        pos += length
        if not jumped:
            end_offset = pos

    return ".".join(labels), end_offset


def _parse_txt_record(rdata: bytes) -> dict[str, str]:
    txt: dict[str, str] = {}
    idx = 0
    while idx < len(rdata):
        seg_len = rdata[idx]
        idx += 1
        if seg_len == 0 or idx + seg_len > len(rdata):
            break
        item = rdata[idx : idx + seg_len].decode("utf-8", errors="replace")
        idx += seg_len
        if "=" in item:
            k, _, v = item.partition("=")
            txt[k.strip()] = v.strip()
    return txt


def parse_mdns_response(data: bytes, source_ip: str = "") -> list[dict[str, Any]]:
    """Parse raw mDNS response bytes into printer SRV/TXT/A service records safely."""
    if len(data) < 12:
        return []
    try:
        _, _flags, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", data[:12])
    except struct.error:
        return []

    pos = 12
    for _ in range(min(qdcount, 64)):
        if pos >= len(data):
            return []
        _, pos = _read_dns_name(data, pos)
        pos += 4

    total_rrs = min(ancount + nscount + arcount, 128)
    srv_by_instance: dict[str, tuple[str, int]] = {}
    txt_by_instance: dict[str, dict[str, str]] = {}
    ip_by_host: dict[str, str] = {}
    ptr_instances: list[tuple[str, str]] = []

    for _ in range(total_rrs):
        if pos >= len(data):
            break
        rr_name, pos = _read_dns_name(data, pos)
        if pos + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", data[pos : pos + 10])
        pos += 10
        if pos + rdlen > len(data):
            break
        rdata_start = pos
        rdata = data[pos : pos + rdlen]
        pos += rdlen

        if rtype == 12:  # PTR
            target, _ = _read_dns_name(data, rdata_start)
            if target:
                ptr_instances.append((rr_name.lower(), target))
        elif rtype == 33 and len(rdata) >= 6:  # SRV
            _, _, port = struct.unpack("!HHH", rdata[:6])
            target, _ = _read_dns_name(data, rdata_start + 6)
            srv_by_instance[rr_name] = (target, port)
        elif rtype == 16:  # TXT
            txt_by_instance[rr_name] = _parse_txt_record(rdata)
        elif rtype == 1 and len(rdata) == 4:  # A record
            ip_by_host[rr_name.lower()] = socket.inet_ntoa(rdata)

    discovered: list[dict[str, Any]] = []
    for svc_name, inst_name in ptr_instances:
        if not any(svc in svc_name for svc in ("_ipp._tcp", "_ipps._tcp", "_pdl-datastream._tcp")):
            continue
        srv_target, port = srv_by_instance.get(inst_name, ("", 631 if "_ipp" in svc_name else 9100))
        ip = ip_by_host.get(srv_target.lower(), source_ip)
        if not ip:
            continue
        txt = txt_by_instance.get(inst_name, {})
        rp = (txt.get("rp") or "ipp/print").lstrip("/")
        if "_ipps._tcp" in svc_name:
            uri = f"ipps://{ip}:{port}/{rp}"
        elif "_ipp._tcp" in svc_name:
            uri = f"ipp://{ip}:{port}/{rp}"
        else:
            uri = f"socket://{ip}:{port}"

        model_label = txt.get("ty") or txt.get("product", "").strip("()") or inst_name.split("._", 1)[0]
        color_val = txt.get("Color", "").upper()
        duplex_val = txt.get("Duplex", "").upper()

        discovered.append(
            {
                "name": model_label[:90],
                "port_or_uri": uri,
                "ip": ip,
                "supports_color": True if color_val == "T" else (False if color_val == "F" else None),
                "supports_duplex": True if duplex_val == "T" else (False if duplex_val == "F" else None),
                "source": "mdns_network",
                "connection_type": "UNCONFIGURED_NETWORK",
            }
        )

    return discovered


def discover_mdns_printers(timeout: float = 1.1) -> list[dict[str, Any]]:
    """Broadcast a multicast DNS-SD PTR query for LAN IPP/AirPrint/JetDirect printers."""
    query = _build_mdns_ptr_query(_MDNS_SERVICES)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    found_by_uri: dict[str, dict[str, Any]] = {}
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setblocking(False)
        sock.sendto(query, (_MDNS_ADDR, _MDNS_PORT))

        deadline = time.monotonic() + max(0.2, min(timeout, 3.0))
        while time.monotonic() < deadline:
            wait = max(0.05, deadline - time.monotonic())
            readable, _, _ = select.select([sock], [], [], wait)
            if not readable:
                break
            try:
                data, addr = sock.recvfrom(8192)
            except OSError:
                break
            for item in parse_mdns_response(data, source_ip=addr[0]):
                uri = item.get("port_or_uri", "")
                if uri and uri not in found_by_uri:
                    found_by_uri[uri] = item
    except OSError:
        return []
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return list(found_by_uri.values())


def probe_network_printer_ip(raw_host: str, timeout: float = 0.6) -> dict[str, Any]:
    """Validate an IPv4/host input and probe standard printer ports (631 IPP, 9100 RAW, 515 LPD)."""
    cleaned = (raw_host or "").strip()
    if not cleaned:
        return {"requested": False, "found": False, "open_ports": [], "device": None, "message": ""}

    # Strip optional URL prefix or port suffix carefully
    cleaned = re.sub(r"^(?:ipps?|socket|lpd|https?)://", "", cleaned, flags=re.IGNORECASE).split("/", 1)[0]
    host_only = cleaned.split(":", 1)[0].strip()

    try:
        ip_obj = ipaddress.ip_address(host_only)
        if ip_obj.is_link_local and str(ip_obj).startswith("169.254."):
            return {
                "requested": True,
                "found": False,
                "open_ports": [],
                "device": None,
                "message": "Link-local metadata manzillariga (169.254.x.x) skaner ruxsat etilmaydi.",
            }
        resolved_host = str(ip_obj)
    except ValueError:
        if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*$", host_only):
            return {
                "requested": True,
                "found": False,
                "open_ports": [],
                "device": None,
                "message": f"'{raw_host}' — yaroqli IP yoki lokal printer manzili emas.",
            }
        resolved_host = host_only

    open_ports = _probe_host_printer_ports(resolved_host, timeout=timeout)
    if not open_ports:
        return {
            "requested": True,
            "found": False,
            "open_ports": [],
            "device": None,
            "message": f"{resolved_host} manzilida 631 (IPP), 9100 (RAW) yoki 515 (LPD) printer portlari javob bermadi.",
        }

    if 631 in open_ports:
        uri = f"ipp://{resolved_host}:631/ipp/print"
        proto_label = "IPP (631)"
    elif 9100 in open_ports:
        uri = f"socket://{resolved_host}:9100"
        proto_label = "JetDirect RAW (9100)"
    else:
        uri = f"lpd://{resolved_host}:515/lp"
        proto_label = "LPD (515)"

    device = {
        "name": f"Tarmoq printer ({resolved_host})",
        "port_or_uri": uri,
        "ip": resolved_host,
        "source": "network_ip_probe",
        "connection_type": "UNCONFIGURED_NETWORK",
        "status_text": f"Tarmoqda topildi ({proto_label})",
    }
    return {
        "requested": True,
        "found": True,
        "open_ports": open_ports,
        "device": device,
        "message": f"{resolved_host} manzilida ochiq printer portlari topildi: {', '.join(map(str, open_ports))}.",
    }


# ---------------------------------------------------------------------------
# Layer 3: Safe 1-Click CUPS Auto-Configuration (`lpadmin`)
# ---------------------------------------------------------------------------


def _select_best_cups_model(queue_hint: str) -> list[str]:
    """Query `lpinfo -m` and rank candidate PPDs: `everywhere` first, then model/generic fallbacks."""
    candidates = ["everywhere"]
    res = _run_cmd(["lpinfo", "-m"], timeout=6.0)
    if not res or res.returncode != 0:
        return candidates

    tokens = [t for t in re.split(r"[^a-z0-9]+", (queue_hint or "").lower()) if len(t) >= 3]
    scored: list[tuple[int, str]] = []
    generic_ppds: list[str] = []
    for line in res.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        model_id = parts[0].strip()
        desc = (parts[1] if len(parts) > 1 else model_id).lower()
        if "everywhere" == model_id.lower():
            continue
        if "generic" in desc or "sample.drv/generic.ppd" in model_id.lower():
            generic_ppds.append(model_id)
        score = sum(1 for tok in tokens if tok in desc)
        if score > 0:
            scored.append((score, model_id))

    scored.sort(key=lambda item: -item[0])
    for _, mid in scored[:3]:
        if mid not in candidates:
            candidates.append(mid)
    for g in generic_ppds[:2]:
        if g not in candidates:
            candidates.append(g)
    candidates.append("raw")
    return candidates


def auto_configure_cups_printer(
    device_uri: str,
    queue_name: str = "",
    set_default: bool = True,
) -> dict[str, Any]:
    """Safely configure an unconfigured USB/IPP/Socket printer into local CUPS via `lpadmin`."""
    clean_uri = sanitize_device_uri(device_uri)
    derived = queue_name.strip() or _derive_name_from_uri(clean_uri)
    clean_name = sanitize_queue_name(derived)

    lpadmin_bin = shutil.which("lpadmin")
    if not lpadmin_bin:
        return {
            "ok": False,
            "queue_name": clean_name,
            "device_uri": clean_uri,
            "model_used": "",
            "message": "CUPS `lpadmin` utility topilmadi (Windows tizimida Printerni Sozlamalar orqali qo'shing).",
        }

    models = _select_best_cups_model(derived)
    last_err = ""
    chosen_model = ""

    for model_opt in models:
        cmd = [lpadmin_bin, "-p", clean_name, "-E", "-v", clean_uri, "-m", model_opt]
        proc = _run_cmd(cmd, timeout=10.0)
        if proc and proc.returncode == 0:
            chosen_model = model_opt
            break
        if proc:
            last_err = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()

    if not chosen_model:
        return {
            "ok": False,
            "queue_name": clean_name,
            "device_uri": clean_uri,
            "model_used": "",
            "message": f"CUPS ga ulab bo'lmadi: {last_err or 'mos PPD drayver topilmadi'}.",
        }

    if shutil.which("cupsenable"):
        _run_cmd(["cupsenable", clean_name], timeout=5.0)
    if shutil.which("cupsaccept"):
        _run_cmd(["cupsaccept", clean_name], timeout=5.0)
    if set_default:
        _run_cmd([lpadmin_bin, "-d", clean_name], timeout=5.0)

    return {
        "ok": True,
        "queue_name": clean_name,
        "device_uri": clean_uri,
        "model_used": chosen_model,
        "message": f"Printer '{clean_name}' CUPS ga muvaffaqiyatli ulandi (drayver: {chosen_model}).",
    }


# ---------------------------------------------------------------------------
# Layer 4: Unified Orchestrator (Configured + Unconfigured + Pi Bridge Health)
# ---------------------------------------------------------------------------


def _parse_iso_age_seconds(iso_str: str) -> int | None:
    if not iso_str or not iso_str.strip():
        return None
    try:
        dt = datetime.fromisoformat(iso_str.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = int((datetime.now(timezone.utc) - dt).total_seconds())
        return max(0, age)
    except Exception:
        return None


def _normalize_agent_printer(
    raw: dict[str, Any],
    agent_hostname: str,
    agent_online: bool,
    agent_age_seconds: int | None,
) -> dict[str, Any]:
    name = str(raw.get("name", "")).strip()
    uri = str(raw.get("port_or_uri") or "").strip()
    is_virt = bool(raw.get("is_virtual", False)) or is_virtual_printer(name, uri, str(raw.get("driver_name") or ""))
    configured = bool(raw.get("configured", True))
    conn_type = str(raw.get("connection_type") or classify_connection(uri, "", is_virtual=is_virt, configured=configured))
    base_offline = bool(raw.get("is_offline", False))
    hw_present = raw.get("hardware_present")

    if not agent_online:
        is_offline = True
        hw_present = False
        age_hint = f"{agent_age_seconds}s oldin" if agent_age_seconds is not None else "aloqa yo'q"
        status_text = f"Raspberry Pi Agent uzilgan ({age_hint})"
    else:
        is_offline = base_offline
        status_text = str(raw.get("status_text") or "Raspberry Pi Agent")

    return {
        "name": name,
        "is_default": bool(raw.get("is_default", False)),
        "status_text": status_text,
        "is_offline": is_offline,
        "jobs_in_queue": int(raw.get("jobs_in_queue", 0) or 0),
        "source": str(raw.get("source") or "pi_agent"),
        "connection_type": conn_type,
        "port_or_uri": uri,
        "driver_name": str(raw.get("driver_name") or ""),
        "hardware_present": hw_present,
        "is_virtual": is_virt,
        "ready_to_print": (not is_offline) and (not is_virt) and configured and (hw_present is not False),
        "configured": configured,
        "supports_color": raw.get("supports_color"),
        "supports_duplex": raw.get("supports_duplex"),
        "host_label": str(raw.get("host_label") or agent_hostname or "Raspberry Pi Agent"),
        "can_auto_configure": bool(raw.get("can_auto_configure", False)),
        "suggested_queue_name": str(raw.get("suggested_queue_name") or ""),
    }


def _dedupe_unconfigured_device(
    candidate: dict[str, Any],
    configured_printers: list[dict[str, Any]],
) -> bool:
    """Return True if candidate hardware already matches an online/configured local queue."""
    cand_uri = str(candidate.get("port_or_uri") or "").strip().lower()
    cand_port = str(candidate.get("port_hint") or "").strip().upper()
    cand_norm = _normalize_match_text(f"{candidate.get('name', '')} {candidate.get('model_hint', '')}")

    for cfg in configured_printers:
        if cfg.get("is_virtual"):
            continue
        cfg_uri = str(cfg.get("port_or_uri") or "").strip()
        if cand_uri and cfg_uri and _uris_refer_same_device(cand_uri, cfg_uri):
            return True
        if cand_port and cfg_uri.upper().startswith(cand_port):
            return True
        cfg_ipv4 = _extract_ipv4_from_port(cfg_uri)
        cand_ipv4 = str(candidate.get("ip") or _extract_ipv4_from_port(cand_uri))
        if cfg_ipv4 and cand_ipv4 and cfg_ipv4 == cand_ipv4:
            return True
        cfg_norm = _normalize_match_text(cfg.get("name", ""))
        if cand_norm and cfg_norm and (cand_norm in cfg_norm or cfg_norm in cand_norm) and cfg.get("hardware_present") is True:
            return True
    return False


def run_comprehensive_printer_scan(
    settings: dict[str, Any] | None = None,
    include_network_scan: bool = True,
    network_ip: str = "",
) -> dict[str, Any]:
    """Execute full multi-layer discovery across OS spoolers, USB hardware, LAN mDNS/IP, and Pi Agent."""
    cfg = settings or {}
    layers_checked: list[str] = []

    windows_usb = probe_windows_usb_printers()
    if windows_usb.get("ok"):
        layers_checked.append("windows_usb_pnp")

    win_printers = discover_windows_printers(
        probe_network_ports=include_network_scan,
        usb_probe=windows_usb,
    )
    if win32print or win_printers:
        layers_checked.append("windows_spooler")

    cups_backends = discover_cups_backends()
    if cups_backends.get("ok"):
        layers_checked.append("cups_backends")

    cups_printers = discover_cups_printers(
        include_capabilities=include_network_scan,
        backends_info=cups_backends,
    )
    if shutil.which("lpstat") or cups_printers:
        layers_checked.append("linux_cups")

    linux_usb = discover_linux_usb_hardware()
    if Path("/sys/bus/usb/devices").exists():
        layers_checked.append("linux_usb")

    # Combine configured local + remote Pi Agent queues
    configured: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for p in [*win_printers, *cups_printers]:
        pname = str(p.get("name", "")).strip()
        if pname and pname not in seen_names:
            seen_names.add(pname)
            configured.append(p)

    agent_last_seen = str(cfg.get("agent_last_seen") or "").strip()
    agent_hostname = str(cfg.get("agent_hostname") or "").strip()
    agent_age = _parse_iso_age_seconds(agent_last_seen)
    agent_online = (agent_age is not None) and (agent_age <= AGENT_STALE_SECONDS)
    agent_printers_raw = cfg.get("agent_printers") or []
    agent_unconfigured_raw = cfg.get("agent_unconfigured_devices") or []
    if agent_last_seen or agent_printers_raw or agent_unconfigured_raw:
        layers_checked.append("pi_agent")

    for raw_ap in agent_printers_raw:
        if not isinstance(raw_ap, dict):
            continue
        pname = str(raw_ap.get("name", "")).strip()
        if not pname or pname in seen_names:
            continue
        seen_names.add(pname)
        configured.append(_normalize_agent_printer(raw_ap, agent_hostname, agent_online, agent_age))

    # Collect unconfigured hardware devices across all layers
    discovered_devices: list[dict[str, Any]] = []
    seen_uris: set[str] = set()

    def _add_unconfigured(item: dict[str, Any], host_scope: str = "local") -> None:
        uri = str(item.get("port_or_uri") or "").strip()
        dedup_token = uri.lower() or f"{item.get('name', '').lower()}::{item.get('source', '')}"
        if dedup_token in seen_uris:
            return
        if _dedupe_unconfigured_device(item, configured):
            return
        seen_uris.add(dedup_token)
        can_auto = bool(
            item.get("can_auto_configure")
            or (
                uri
                and any(uri.lower().startswith(s) for s in _SAFE_URI_SCHEMES)
                and (host_scope == "agent" or bool(shutil.which("lpadmin")))
            )
        )
        raw_name = str(item.get("name") or "Yangi Printer").strip()
        discovered_devices.append(
            {
                "name": raw_name,
                "is_default": False,
                "status_text": str(item.get("status_text") or "Yangi qurilma aniqlandi (hali ulanmagan)"),
                "is_offline": False,
                "jobs_in_queue": 0,
                "source": str(item.get("source") or "hardware_probe"),
                "connection_type": str(item.get("connection_type") or "UNCONFIGURED_USB"),
                "port_or_uri": uri,
                "driver_name": str(item.get("manufacturer") or ""),
                "hardware_present": True,
                "is_virtual": False,
                "ready_to_print": False,
                "configured": False,
                "supports_color": item.get("supports_color"),
                "supports_duplex": item.get("supports_duplex"),
                "host_label": str(item.get("host_label") or ("Raspberry Pi Agent" if host_scope == "agent" else "Asosiy server")),
                "can_auto_configure": can_auto,
                "suggested_queue_name": str(item.get("suggested_queue_name") or sanitize_queue_name(raw_name)),
            }
        )

    for dev in windows_usb.get("devices", []):
        _add_unconfigured(
            {
                "name": dev.get("name") or "USB Printer",
                "port_or_uri": dev.get("port_hint") or dev.get("instance_id") or "",
                "port_hint": dev.get("port_hint") or "",
                "model_hint": dev.get("model_hint") or "",
                "manufacturer": dev.get("manufacturer") or "",
                "source": "windows_usb_pnp",
                "connection_type": "UNCONFIGURED_USB",
                "status_text": "USB ga ulangan (Windows Sozlamalar -> Printerlar orqali navbat qo'shing)",
                "can_auto_configure": False,
            }
        )

    for dev in cups_backends.get("devices", []):
        _add_unconfigured(
            {
                **dev,
                "status_text": "CUPS da tayyor qurilma aniqlandi — 1 bosish bilan ulash mumkin",
                "can_auto_configure": bool(shutil.which("lpadmin")),
            }
        )

    for usb_dev in linux_usb:
        prod_norm = _normalize_match_text(usb_dev.get("product") or usb_dev.get("name") or "")
        already_seen_in_cups = any(
            (usb_dev.get("serial") and usb_dev["serial"].lower() in d.get("port_or_uri", "").lower())
            or (prod_norm and prod_norm in _normalize_match_text(d.get("port_or_uri", "")))
            for d in discovered_devices
        )
        if not already_seen_in_cups:
            _add_unconfigured(
                {
                    **usb_dev,
                    "connection_type": "UNCONFIGURED_USB",
                    "status_text": "Linux USB portida printer aniqlandi (`cups` va `ipp-usb` holatini tekshiring)",
                    "can_auto_configure": False,
                }
            )

    if include_network_scan:
        layers_checked.append("mdns_network")
        for mdns_dev in discover_mdns_printers(timeout=1.1):
            _add_unconfigured(
                {
                    **mdns_dev,
                    "status_text": f"Wi-Fi / LAN tarmoqda topildi ({mdns_dev.get('ip', '')})",
                }
            )

    target_ip_result: dict[str, Any] = {"requested": False, "found": False, "message": ""}
    if network_ip and network_ip.strip():
        layers_checked.append("network_ip_probe")
        probe_res = probe_network_printer_ip(network_ip.strip())
        target_ip_result = {
            "requested": bool(probe_res.get("requested")),
            "found": bool(probe_res.get("found")),
            "message": str(probe_res.get("message") or ""),
        }
        if probe_res.get("device"):
            _add_unconfigured(probe_res["device"])

    for ap_unconf in agent_unconfigured_raw:
        if isinstance(ap_unconf, dict) and agent_online:
            _add_unconfigured(
                {
                    **ap_unconf,
                    "source": "pi_agent",
                    "host_label": agent_hostname or "Raspberry Pi Agent",
                    "can_auto_configure": bool(
                        ap_unconf.get("can_auto_configure", True)
                        and any(str(ap_unconf.get("port_or_uri") or "").lower().startswith(s) for s in _SAFE_URI_SCHEMES)
                    ),
                },
                host_scope="agent",
            )

    # Sort configured printers cleanly: ready physical -> offline physical -> virtual
    configured.sort(
        key=lambda p: (
            bool(p.get("is_virtual")),
            not bool(p.get("ready_to_print")),
            not bool(p.get("is_default")),
            str(p.get("name", "")).lower(),
        )
    )

    ready_phys = [p for p in configured if p.get("ready_to_print")]
    offline_phys = [p for p in configured if not p.get("is_virtual") and not p.get("ready_to_print")]
    virt_list = [p for p in configured if p.get("is_virtual")]

    if ready_phys:
        names = ", ".join(p["name"] for p in ready_phys[:3])
        extra = f" (+{len(ready_phys) - 3})" if len(ready_phys) > 3 else ""
        recommendation = f"{len(ready_phys)} ta jismoniy printer chop etishga tayyor: {names}{extra}."
    elif discovered_devices:
        recommendation = (
            f"Jismoniy printer ulangan ({len(discovered_devices)} ta yangi qurilma topildi), "
            "lekin hali chop etish navbatiga sozlanmagan."
        )
    elif offline_phys:
        recommendation = (
            f"{len(offline_phys)} ta sozlangan printer oflayn yoki kabeli uzilgan. "
            "USB/Wi-Fi ulanishini va printer quvvatini tekshiring."
        )
    elif cfg.get("printer_mode") == "REMOTE_AGENT" and not agent_online:
        recommendation = "Raspberry Pi Agent hozircha onlayn emas — Pi qurilmasida `tlg-pi-agent` xizmati ishlayotganini tekshiring."
    else:
        recommendation = "Hech qanday jismoniy printer topilmadi. USB kabelni yoki tarmoq/Wi-Fi ulanishini tekshirib qayta skanerlang."

    summary = {
        "total_configured": len(configured),
        "ready_physical_count": len(ready_phys),
        "offline_physical_count": len(offline_phys),
        "virtual_count": len(virt_list),
        "unconfigured_hardware_count": len(discovered_devices),
        "agent_online": agent_online,
        "agent_hostname": agent_hostname,
        "agent_last_seen": agent_last_seen,
        "agent_stale_seconds": agent_age,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "layers_checked": layers_checked,
        "recommendation": recommendation,
        "target_ip_message": target_ip_result.get("message", ""),
    }

    return {
        "printers": configured,
        "discovered_devices": discovered_devices,
        "summary": summary,
    }


def discover_all_printers(
    agent_printers: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fast local + Pi Agent printer enumeration for system status and dispatch fallback."""
    merged_settings = dict(settings or {})
    if agent_printers is not None and "agent_printers" not in merged_settings:
        merged_settings["agent_printers"] = agent_printers
    # When legacy callers pass raw agent_printers without agent_last_seen, treat them as online
    if agent_printers and not merged_settings.get("agent_last_seen"):
        merged_settings["agent_last_seen"] = datetime.now(timezone.utc).isoformat()
    result = run_comprehensive_printer_scan(settings=merged_settings, include_network_scan=False)
    return result["printers"]
