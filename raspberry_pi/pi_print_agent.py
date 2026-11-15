#!/usr/bin/env python3
"""Raspberry Pi 5 remote print bridge for TLG SmartPrint.

Polls the main TLG SmartPrint server (VPS/cloud or local network) using X-Agent-Key,
downloads queued print-ready PDF files, dispatches them to the attached printer via CUPS (`lp`),
tracks completion via `lpstat`, and reports status back to the server.

Pure Python standard library — requires zero third-party pip packages on Raspberry Pi.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.error
from urllib.parse import unquote
import urllib.request


def read_pi_cpu_temp_c() -> float | None:
    """Read Raspberry Pi SoC temperature from sysfs when running on Linux."""
    thermal_file = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        if thermal_file.exists():
            raw = thermal_file.read_text(encoding="utf-8").strip()
            if raw:
                return round(int(raw) / 1000.0, 1)
    except Exception:
        pass
    return None


def _run_cmd(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str] | None:
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


_SAFE_URI_SCHEMES = ("usb://", "ipp://", "ipps://", "dnssd://", "socket://", "lpd://")


def _derive_label_from_uri(uri: str) -> str:
    decoded = unquote(uri)
    scheme, _, rest = decoded.partition("://")
    host_part = rest.split("?", 1)[0].strip("/")
    if scheme.lower() == "usb":
        segs = [s.strip() for s in host_part.split("/") if s.strip()]
        if segs:
            return " ".join(segs[:2])
    if scheme.lower() == "dnssd":
        first = host_part.split("._", 1)[0].strip()
        if first:
            return first
    return f"Printer ({host_part.split('/')[0]})" if host_part else "Printer"


def _sanitize_queue_name(raw_name: str, fallback: str = "TLG_Pi_Printer") -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", (raw_name or "").strip()).strip("_.-")
    return (clean or fallback)[:64]


def _uris_match(uri_a: str, uri_b: str) -> bool:
    a, b = (uri_a or "").strip().lower(), (uri_b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    base_a, _, qa = a.partition("?")
    base_b, _, qb = b.partition("?")
    if base_a == base_b:
        sa = re.search(r"serial=([^&]+)", qa)
        sb = re.search(r"serial=([^&]+)", qb)
        return sa.group(1) == sb.group(1) if (sa and sb) else True
    return False


def _discover_cups_backends() -> tuple[bool, list[dict[str, Any]]]:
    if not shutil.which("lpinfo"):
        return False, []
    res = _run_cmd(["lpinfo", "-v"], timeout=6.0)
    if not res or res.returncode != 0:
        return False, []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in res.stdout.splitlines():
        parts = raw.strip().split(None, 1)
        if len(parts) < 2:
            continue
        uri = parts[1].strip()
        if "://" not in uri or uri in seen:
            continue
        scheme, rest = uri.split("://", 1)
        if not rest.strip("/") or f"{scheme.lower()}://" not in _SAFE_URI_SCHEMES:
            continue
        seen.add(uri)
        name = _derive_label_from_uri(uri)
        found.append(
            {
                "name": name,
                "port_or_uri": uri,
                "connection_type": "UNCONFIGURED_USB" if scheme.lower() == "usb" else "UNCONFIGURED_NETWORK",
                "source": "cups_backend",
                "configured": False,
                "is_offline": False,
                "is_virtual": False,
                "hardware_present": True,
                "ready_to_print": False,
                "can_auto_configure": bool(shutil.which("lpadmin")),
                "suggested_queue_name": _sanitize_queue_name(name),
                "status_text": "Pi CUPS da yangi qurilma topildi — 1 bosish bilan ulash mumkin",
            }
        )
    return True, found


def _discover_linux_usb_sysfs(usb_root: Path | None = None) -> list[dict[str, Any]]:
    root = usb_root or Path("/sys/bus/usb/devices")
    if not root.exists():
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _txt(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore").strip() if p.exists() else ""
        except Exception:
            return ""

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if _txt(entry / "bInterfaceClass").lower() != "07" and _txt(entry / "bDeviceClass").lower() != "07":
            continue
        dev_dir = root / entry.name.split(":", 1)[0] if ":" in entry.name and (root / entry.name.split(":", 1)[0]).exists() else entry
        vid, pid = _txt(dev_dir / "idVendor"), _txt(dev_dir / "idProduct")
        mfg, prod, ser = _txt(dev_dir / "manufacturer"), _txt(dev_dir / "product"), _txt(dev_dir / "serial")
        key = f"{vid}:{pid}:{ser or dev_dir.name}"
        if key in seen:
            continue
        seen.add(key)
        label = " ".join(x for x in (mfg, prod) if x).strip() or f"USB Printer ({vid}:{pid})"
        found.append(
            {
                "name": label,
                "port_or_uri": f"usb-hw://{vid}:{pid}" + (f"?serial={ser}" if ser else ""),
                "serial": ser,
                "product": prod,
                "connection_type": "UNCONFIGURED_USB",
                "source": "linux_usb",
                "configured": False,
                "is_offline": False,
                "is_virtual": False,
                "hardware_present": True,
                "ready_to_print": False,
                "can_auto_configure": False,
                "suggested_queue_name": _sanitize_queue_name(label),
                "status_text": "Raspberry Pi USB portida printer aniqlandi",
            }
        )
    return found


def _probe_port(host: str, port: int, timeout: float = 0.45) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_target_ip(raw_host: str) -> dict[str, Any] | None:
    clean = re.sub(r"^(?:ipps?|socket|lpd|https?)://", "", (raw_host or "").strip(), flags=re.IGNORECASE).split("/", 1)[0]
    host = clean.split(":", 1)[0].strip()
    if not host:
        return None
    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_link_local and str(ip_obj).startswith("169.254."):
            return None
        host = str(ip_obj)
    except ValueError:
        if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*$", host):
            return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        hits = [p for p, ok in ((631, pool.submit(_probe_port, host, 631)), (9100, pool.submit(_probe_port, host, 9100)), (515, pool.submit(_probe_port, host, 515))) if ok.result()]
    if not hits:
        return None
    uri = f"ipp://{host}:631/ipp/print" if 631 in hits else (f"socket://{host}:9100" if 9100 in hits else f"lpd://{host}:515/lp")
    return {
        "name": f"Tarmoq printer ({host})",
        "port_or_uri": uri,
        "connection_type": "UNCONFIGURED_NETWORK",
        "source": "network_ip_probe",
        "configured": False,
        "is_offline": False,
        "is_virtual": False,
        "hardware_present": True,
        "ready_to_print": False,
        "can_auto_configure": bool(shutil.which("lpadmin")),
        "suggested_queue_name": _sanitize_queue_name(f"Net_{host}"),
        "status_text": f"Pi tarmog'ida topildi (port {', '.join(map(str, hits))})",
    }


def _discover_mdns_quick(timeout: float = 0.9) -> list[dict[str, Any]]:
    def _enc(n: str) -> bytes:
        return b"".join(bytes([len(p.encode())]) + p.encode() for p in n.strip(".").split(".") if p) + b"\x00"

    def _rdname(buf: bytes, off: int) -> tuple[str, int]:
        out, seen, end, jumped, pos = [], set(), off, False, off
        while pos < len(buf) and pos not in seen and len(seen) < 64:
            seen.add(pos)
            ln = buf[pos]
            if ln == 0:
                if not jumped:
                    end = pos + 1
                break
            if (ln & 0xC0) == 0xC0 and pos + 1 < len(buf):
                if not jumped:
                    end = pos + 2
                    jumped = True
                pos = ((ln & 0x3F) << 8) | buf[pos + 1]
                continue
            pos += 1
            if pos + ln > len(buf):
                break
            out.append(buf[pos : pos + ln].decode("utf-8", errors="replace"))
            pos += ln
            if not jumped:
                end = pos
        return ".".join(out), end

    svcs = ("_ipp._tcp.local", "_ipps._tcp.local", "_pdl-datastream._tcp.local")
    pkt = struct.pack("!HHHHHH", 0, 0, len(svcs), 0, 0, 0) + b"".join(_enc(s) + struct.pack("!HH", 12, 1) for s in svcs)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    found: dict[str, dict[str, Any]] = {}
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setblocking(False)
        sock.sendto(pkt, ("224.0.0.251", 5353))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([sock], [], [], max(0.05, deadline - time.monotonic()))
            if not ready:
                break
            data, addr = sock.recvfrom(8192)
            if len(data) < 12:
                continue
            _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
            pos = 12
            for _ in range(min(qd, 32)):
                _, pos = _rdname(data, pos)
                pos += 4
            srvs, txts, ips, ptrs = {}, {}, {}, []
            for _ in range(min(an + ns + ar, 96)):
                if pos >= len(data):
                    break
                rn, pos = _rdname(data, pos)
                if pos + 10 > len(data):
                    break
                rt, _, _, rlen = struct.unpack("!HHIH", data[pos : pos + 10])
                pos += 10
                if pos + rlen > len(data):
                    break
                rs = pos
                pos += rlen
                if rt == 12:
                    t, _ = _rdname(data, rs)
                    ptrs.append((rn.lower(), t))
                elif rt == 33 and rlen >= 6:
                    _, _, prt = struct.unpack("!HHH", data[rs : rs + 6])
                    tgt, _ = _rdname(data, rs + 6)
                    srvs[rn] = (tgt, prt)
                elif rt == 16:
                    idx, dtxt = rs, {}
                    while idx < rs + rlen:
                        sl = data[idx]
                        idx += 1
                        if sl == 0 or idx + sl > rs + rlen:
                            break
                        item = data[idx : idx + sl].decode("utf-8", errors="replace")
                        idx += sl
                        if "=" in item:
                            k, _, v = item.partition("=")
                            dtxt[k.strip()] = v.strip()
                    txts[rn] = dtxt
                elif rt == 1 and rlen == 4:
                    ips[rn.lower()] = socket.inet_ntoa(data[rs : rs + 4])
            for sn, inst in ptrs:
                if not any(x in sn for x in ("_ipp._tcp", "_ipps._tcp", "_pdl-datastream._tcp")):
                    continue
                tgt, prt = srvs.get(inst, ("", 631 if "_ipp" in sn else 9100))
                ip = ips.get(tgt.lower(), addr[0])
                tmap = txts.get(inst, {})
                rp = (tmap.get("rp") or "ipp/print").lstrip("/")
                uri = f"ipps://{ip}:{prt}/{rp}" if "_ipps._tcp" in sn else (f"ipp://{ip}:{prt}/{rp}" if "_ipp._tcp" in sn else f"socket://{ip}:{prt}")
                if uri not in found:
                    label = tmap.get("ty") or tmap.get("product", "").strip("()") or inst.split("._", 1)[0]
                    found[uri] = {
                        "name": label[:90],
                        "port_or_uri": uri,
                        "connection_type": "UNCONFIGURED_NETWORK",
                        "source": "mdns_network",
                        "configured": False,
                        "is_offline": False,
                        "is_virtual": False,
                        "hardware_present": True,
                        "ready_to_print": False,
                        "can_auto_configure": bool(shutil.which("lpadmin")),
                        "suggested_queue_name": _sanitize_queue_name(label),
                        "status_text": f"Pi Wi-Fi/LAN da topildi ({ip})",
                    }
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return list(found.values())


def discover_local_cups_printers(
    backends: tuple[bool, list[dict[str, Any]]] | None = None,
    include_capabilities: bool = False,
) -> list[dict[str, Any]]:
    """Enumerate printers configured in Raspberry Pi CUPS with live URI/USB presence check."""
    host = socket.gethostname()
    if os.environ.get("TLG_PI_SIMULATE_CUPS") == "1":
        return [
            {
                "name": "Canon_G3030_Pi_Sim",
                "is_default": True,
                "status_text": "Tayyor (Raspberry Pi Simulyatsiya)",
                "is_offline": False,
                "jobs_in_queue": 0,
                "source": "pi_agent",
                "connection_type": "USB",
                "port_or_uri": "usb://Canon/G3030%20series?serial=SIM001",
                "hardware_present": True,
                "is_virtual": False,
                "ready_to_print": True,
                "configured": True,
                "supports_color": True,
                "host_label": host,
            }
        ]

    if not shutil.which("lpstat"):
        return []

    default_name = ""
    res_def = _run_cmd(["lpstat", "-d"])
    if res_def and res_def.returncode == 0:
        m = re.search(r":\s*(\S+)", res_def.stdout)
        if m:
            default_name = m.group(1).strip()

    uri_by_printer: dict[str, str] = {}
    res_uris = _run_cmd(["lpstat", "-v"])
    if res_uris and res_uris.returncode == 0:
        for line in res_uris.stdout.splitlines():
            mu = re.match(r"^(?:device|уст[а-я]+).*?\s+(?:for|для)\s+(\S+?):\s*(\S.+)$", line.strip(), flags=re.IGNORECASE)
            if mu:
                uri_by_printer[mu.group(1).strip()] = mu.group(2).strip()

    queue_counts: dict[str, int] = {}
    res_jobs = _run_cmd(["lpstat", "-W", "not-completed", "-o"])
    if res_jobs and res_jobs.returncode == 0:
        for line in res_jobs.stdout.splitlines():
            jm = re.match(r"^([^\s]+)-\d+\s+", line.strip())
            if jm:
                pname = jm.group(1)
                queue_counts[pname] = queue_counts.get(pname, 0) + 1

    printers: list[dict[str, Any]] = []
    res_p = _run_cmd(["lpstat", "-p"])
    if not res_p or res_p.returncode != 0:
        return printers

    backends_ok, backend_list = backends if backends is not None else (False, [])
    live_uris = [b["port_or_uri"] for b in backend_list if b.get("port_or_uri")]

    for line in res_p.stdout.splitlines():
        m = re.match(r"^printer\s+(\S+)\s+(.+)$", line.strip(), flags=re.IGNORECASE)
        if not m:
            continue
        name = m.group(1).strip()
        rest = m.group(2).strip()
        lower = rest.lower()
        is_offline = "disabled" in lower or "offline" in lower or "not connected" in lower
        if "now printing" in lower:
            status_text = "Chop etmoqda (Pi CUPS)"
        elif is_offline:
            status_text = "O'chiq / To'xtatilgan (Pi CUPS)"
        elif "is idle" in lower:
            status_text = "Tayyor (Pi CUPS Idle)"
        else:
            status_text = rest[:80]

        uri = uri_by_printer.get(name, "")
        is_virt = "cups-pdf" in name.lower() or uri.lower().startswith("cups-pdf:")
        conn_type = "VIRTUAL" if is_virt else ("USB" if uri.lower().startswith("usb://") else ("NETWORK" if "://" in uri else "LOCAL"))

        hardware_present: bool | None = None
        if backends_ok and not is_virt and uri and conn_type == "USB":
            hardware_present = any(_uris_match(uri, lu) for lu in live_uris)
            if not hardware_present and not is_offline:
                is_offline = True
                status_text = "USB kabel uzilgan yoki printer o'chiq (Pi)"

        sup_color: bool | None = None
        sup_duplex: bool | None = None
        if include_capabilities and not is_virt and shutil.which("lpoptions"):
            opts = _run_cmd(["lpoptions", "-p", name, "-l"], timeout=2.5)
            if opts and opts.returncode == 0:
                ol = opts.stdout.lower()
                if "colormodel/" in ol or "color/" in ol:
                    sup_color = any(t in ol for t in ("rgb", "cmyk", "color"))
                if "duplex/" in ol:
                    sup_duplex = any(t in ol for t in ("duplexnotumble", "duplextumble", "two-sided"))

        printers.append(
            {
                "name": name,
                "is_default": name == default_name,
                "status_text": status_text,
                "is_offline": is_offline,
                "jobs_in_queue": queue_counts.get(name, 0),
                "source": "pi_agent",
                "connection_type": conn_type,
                "port_or_uri": uri,
                "hardware_present": hardware_present,
                "is_virtual": is_virt,
                "ready_to_print": (not is_offline) and (not is_virt) and (hardware_present is not False),
                "configured": True,
                "supports_color": sup_color,
                "supports_duplex": sup_duplex,
                "host_label": host,
            }
        )
    return printers


def collect_agent_scan_telemetry(deep: bool = False, network_ip: str = "") -> dict[str, Any]:
    """Collect configured CUPS queues plus unconfigured USB/CUPS/mDNS/IP printers on Raspberry Pi."""
    layers = ["pi_cups"]
    backends_ok, backend_devs = _discover_cups_backends()
    if backends_ok:
        layers.append("cups_backends")

    printers = discover_local_cups_printers(
        backends=(backends_ok, backend_devs),
        include_capabilities=deep,
    )
    configured_uris = [p.get("port_or_uri", "") for p in printers if p.get("port_or_uri")]

    unconfigured: list[dict[str, Any]] = []
    seen_uris: set[str] = set()

    def _add_if_new(dev: dict[str, Any]) -> None:
        uri = str(dev.get("port_or_uri") or "").strip()
        if any(_uris_match(uri, cu) for cu in configured_uris):
            return
        key = uri.lower() or dev.get("name", "").lower()
        if key in seen_uris:
            return
        seen_uris.add(key)
        unconfigured.append(dev)

    for b in backend_devs:
        _add_if_new(b)

    if Path("/sys/bus/usb/devices").exists():
        layers.append("linux_usb")
        for u in _discover_linux_usb_sysfs():
            ser = (u.get("serial") or "").lower()
            prod = re.sub(r"[^a-z0-9]+", "", (u.get("product") or "").lower())
            matched_backend = any(
                (ser and ser in d.get("port_or_uri", "").lower())
                or (prod and prod in re.sub(r"[^a-z0-9]+", "", d.get("port_or_uri", "").lower()))
                for d in unconfigured
            )
            if not matched_backend:
                _add_if_new(u)

    if deep:
        layers.append("mdns_network")
        for md in _discover_mdns_quick(timeout=0.9):
            _add_if_new(md)
        if network_ip.strip():
            layers.append("network_ip_probe")
            ip_dev = _probe_target_ip(network_ip.strip())
            if ip_dev:
                _add_if_new(ip_dev)

    return {
        "hostname": socket.gethostname(),
        "cpu_temp_c": read_pi_cpu_temp_c(),
        "os_info": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "printers": printers,
        "unconfigured_devices": unconfigured,
        "scan_layers": layers,
    }


def execute_auto_configure_command(cmd: dict[str, Any]) -> dict[str, Any]:
    """Execute a validated 1-click CUPS `lpadmin` setup command requested from the Admin panel."""
    cmd_id = str(cmd.get("command_id") or "")
    uri = str(cmd.get("device_uri") or "").strip()
    queue_name = _sanitize_queue_name(str(cmd.get("queue_name") or _derive_label_from_uri(uri)))
    set_default = bool(cmd.get("set_default", True))

    if (
        not uri
        or uri.startswith("-")
        or re.search(r"[\x00-\x1f\s\"'`$;|&<>\\]", uri)
        or not any(uri.lower().startswith(s) for s in _SAFE_URI_SCHEMES)
    ):
        return {"command_id": cmd_id, "ok": False, "queue_name": queue_name, "message": "Noto'g'ri printer URI."}

    lpadmin = shutil.which("lpadmin")
    if not lpadmin:
        return {"command_id": cmd_id, "ok": False, "queue_name": queue_name, "message": "Raspberry Pi da `lpadmin` topilmadi."}

    models = ["everywhere"]
    res_m = _run_cmd(["lpinfo", "-m"], timeout=6.0)
    if res_m and res_m.returncode == 0:
        tokens = [t for t in re.split(r"[^a-z0-9]+", queue_name.lower()) if len(t) >= 3]
        scored = []
        for ln in res_m.stdout.splitlines():
            parts = ln.strip().split(None, 1)
            if parts and parts[0].lower() != "everywhere":
                sc = sum(1 for t in tokens if t in ln.lower())
                if sc > 0:
                    scored.append((sc, parts[0]))
        scored.sort(key=lambda x: -x[0])
        models.extend(m for _, m in scored[:3])
    models.append("raw")

    chosen, err_txt = "", ""
    for m_opt in models:
        proc = _run_cmd([lpadmin, "-p", queue_name, "-E", "-v", uri, "-m", m_opt], timeout=12.0)
        if proc and proc.returncode == 0:
            chosen = m_opt
            break
        if proc:
            err_txt = (proc.stderr or proc.stdout or "").strip()

    if not chosen:
        return {"command_id": cmd_id, "ok": False, "queue_name": queue_name, "message": f"CUPS ulash xatosi: {err_txt or 'drayver topilmadi'}"}

    if shutil.which("cupsenable"):
        _run_cmd(["cupsenable", queue_name], timeout=5.0)
    if shutil.which("cupsaccept"):
        _run_cmd(["cupsaccept", queue_name], timeout=5.0)
    if set_default:
        _run_cmd([lpadmin, "-d", queue_name], timeout=5.0)

    return {
        "command_id": cmd_id,
        "ok": True,
        "queue_name": queue_name,
        "model_used": chosen,
        "message": f"Raspberry Pi printer '{queue_name}' muvaffaqiyatli ulandi (drayver: {chosen}).",
    }


_ALLOWED_PAPER_SIZES = {"A4", "A5", "Letter"}


def _sanitize_arg_value(val: str | None, fallback: str = "", max_len: int = 80) -> str:
    clean = re.sub(r'[\x00-\x1f"\\;|`$&<>]+', "", (val or "").strip()).lstrip("-").strip()
    return (clean or fallback)[:max_len]


def build_cups_lp_command(printer_name: str, job: dict[str, Any], pdf_path: Path) -> list[str]:
    """Build `lp` arguments for the downloaded print job PDF."""
    cmd = ["lp"]
    target = _sanitize_arg_value(printer_name, max_len=120)
    if target:
        cmd.extend(["-d", target])

    copies = max(1, int(job.get("copies", 1)))
    cmd.extend(["-n", str(copies)])

    title = _sanitize_arg_value(str(job.get("original_filename") or f"TLG-{job.get('id', 'job')}"), fallback="TLG-Print", max_len=80)
    if title:
        cmd.extend(["-t", title])

    raw_paper = str(job.get("paper_size", "A4")).strip()
    paper_size = raw_paper if raw_paper in _ALLOWED_PAPER_SIZES else "A4"
    cmd.extend(["-o", f"media={paper_size}"])

    duplex = str(job.get("duplex", "simplex")).strip().lower()
    cmd.extend(["-o", f"sides={'two-sided-long-edge' if duplex == 'duplex' else 'one-sided'}"])

    color_mode = str(job.get("color_mode", "bw")).strip().lower()
    cmd.extend(["-o", f"ColorModel={'Gray' if color_mode == 'bw' else 'RGB'}"])

    cmd.extend(["-o", "fit-to-page", str(pdf_path)])
    return cmd


def _http_json(
    url: str,
    method: str,
    agent_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Agent-Key": agent_key,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_pdf(url: str, dest_path: Path, agent_key: str, timeout: float = 60.0) -> None:
    req = urllib.request.Request(url, headers={"X-Agent-Key": agent_key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest_path.write_bytes(resp.read())


def wait_for_cups_completion(
    cups_job_id: str,
    min_wait_seconds: float = 0.0,
    timeout_seconds: float = 600.0,
) -> tuple[bool, str]:
    """Wait until CUPS clears the job AND the estimated physical print time has elapsed."""
    start = time.monotonic()
    min_deadline = start + max(0.0, min_wait_seconds)
    deadline = start + max(timeout_seconds, min_wait_seconds + 30.0)

    if cups_job_id and shutil.which("lpstat"):
        while time.monotonic() < deadline:
            res = _run_cmd(["lpstat", "-W", "not-completed", "-o"], timeout=5.0)
            cups_done = not res or res.returncode != 0 or not any(
                line.strip().startswith(cups_job_id) for line in res.stdout.splitlines() if line.strip()
            )
            if cups_done and time.monotonic() >= min_deadline:
                return True, f"Raspberry Pi printer qog'ozni chiqardi (CUPS ID: {cups_job_id})."
            time.sleep(2.0)

    remaining = min_deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)

    if cups_job_id:
        return True, f"Printer chiqish vaqti yakunlandi (CUPS ID: {cups_job_id})."
    return True, "Printerga yuborildi va hisoblangan chiqish vaqti yakunlandi."


def process_claimed_job(
    server_url: str,
    agent_key: str,
    job: dict[str, Any],
    default_printer: str = "",
) -> dict[str, Any]:
    """Download a claimed job's PDF (or ordered color/BW segments), print via CUPS, and report completion."""
    job_id = str(job["id"])
    base = server_url.rstrip("/")
    pdf_url = f"{base}{job['pdf_url']}"
    target_printer = str(job.get("printer_name") or default_printer or "").strip()
    segments = job.get("print_segments") or []

    with tempfile.TemporaryDirectory(prefix="tlg_pi_") as tmpdir:
        tmp = Path(tmpdir)
        local_pdf = tmp / f"{job_id}.pdf"
        seg_files: list[tuple[dict[str, Any], Path]] = []
        try:
            if len(segments) > 1:
                for seg in segments:
                    seg_path = tmp / seg["pdf_filename"]
                    seg_url = f"{base}{seg['pdf_url']}"
                    _download_pdf(seg_url, seg_path, agent_key)
                    seg_files.append((seg, seg_path))
            else:
                _download_pdf(pdf_url, local_pdf, agent_key)
        except Exception as exc:
            return _http_json(
                f"{base}/api/agent/jobs/{job_id}/report",
                method="POST",
                agent_key=agent_key,
                payload={
                    "status": "ERROR",
                    "status_message": f"Raspberry Pi PDF faylni yuklab ololmadi: {exc}",
                },
            )

        if os.environ.get("TLG_PI_SIMULATE_CUPS") == "1":
            if seg_files:
                cmd_preview = "; ".join(
                    " ".join(
                        build_cups_lp_command(
                            target_printer,
                            {**job, "copies": 1, "color_mode": seg["color_mode"]},
                            seg_path,
                        )
                    )
                    for seg, seg_path in seg_files
                )
            else:
                cmd_preview = " ".join(build_cups_lp_command(target_printer, job, local_pdf))
            return _http_json(
                f"{base}/api/agent/jobs/{job_id}/report",
                method="POST",
                agent_key=agent_key,
                payload={
                    "status": "COMPLETED",
                    "status_message": f"Raspberry Pi CUPS simulyatsiyada chiqardi: {cmd_preview}",
                },
            )

        lp_bin = shutil.which("lp")
        if not lp_bin:
            return _http_json(
                f"{base}/api/agent/jobs/{job_id}/report",
                method="POST",
                agent_key=agent_key,
                payload={
                    "status": "ERROR",
                    "status_message": "Raspberry Pi da CUPS `lp` buyrug'i topilmadi (`sudo apt install cups`).",
                },
            )

        last_cups_id = ""
        if seg_files:
            copies = max(1, int(job.get("copies", 1)))
            for _copy_idx in range(copies):
                for seg, seg_path in seg_files:
                    seg_job = {
                        **job,
                        "copies": 1,
                        "color_mode": seg["color_mode"],
                        "original_filename": f"{job.get('original_filename', 'doc')}-s{seg['segment_index']}",
                    }
                    cmd = build_cups_lp_command(target_printer, seg_job, seg_path)
                    cmd[0] = lp_bin
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
                    if proc.returncode != 0:
                        err_msg = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
                        return _http_json(
                            f"{base}/api/agent/jobs/{job_id}/report",
                            method="POST",
                            agent_key=agent_key,
                            payload={
                                "status": "ERROR",
                                "status_message": f"Raspberry Pi segment #{seg['segment_index']} xatoligi: {err_msg}",
                            },
                        )
                    m = re.search(r"request id is\s+(\S+)", proc.stdout or "", flags=re.IGNORECASE)
                    if m:
                        last_cups_id = m.group(1)
        else:
            cmd = build_cups_lp_command(target_printer, job, local_pdf)
            cmd[0] = lp_bin
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            if proc.returncode != 0:
                err_msg = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
                return _http_json(
                    f"{base}/api/agent/jobs/{job_id}/report",
                    method="POST",
                    agent_key=agent_key,
                    payload={
                        "status": "ERROR",
                        "status_message": f"Raspberry Pi CUPS xatoligi: {err_msg}",
                    },
                )
            m = re.search(r"request id is\s+(\S+)", proc.stdout or "", flags=re.IGNORECASE)
            if m:
                last_cups_id = m.group(1)

        est_seconds = float(job.get("estimated_seconds") or 0)
        ok, done_msg = wait_for_cups_completion(last_cups_id, min_wait_seconds=est_seconds)
        return _http_json(
            f"{base}/api/agent/jobs/{job_id}/report",
            method="POST",
            agent_key=agent_key,
            payload={
                "status": "COMPLETED" if ok else "ERROR",
                "status_message": done_msg,
            },
        )


def run_once(server_url: str, agent_key: str, default_printer: str = "", deep_scan: bool = False) -> bool:
    """Send heartbeat + handle on-demand scan/setup commands + claim up to one queued job."""
    base = server_url.rstrip("/")
    payload = collect_agent_scan_telemetry(deep=deep_scan)
    resp = _http_json(f"{base}/api/agent/poll", method="POST", agent_key=agent_key, payload=payload)

    pending_cmd = resp.get("pending_command")
    if isinstance(pending_cmd, dict) and pending_cmd.get("action") == "AUTO_CONFIGURE_PRINTER":
        cmd_res = execute_auto_configure_command(pending_cmd)
        print(f"[PI-AGENT] Printer ulash natijasi: {cmd_res.get('message')}")
        fresh = collect_agent_scan_telemetry(deep=True)
        fresh["command_result"] = cmd_res
        _http_json(f"{base}/api/agent/scan-report", method="POST", agent_key=agent_key, payload=fresh)
    elif isinstance(resp.get("scan_request"), dict) and resp["scan_request"].get("scan_id"):
        req_info = resp["scan_request"]
        fresh = collect_agent_scan_telemetry(deep=True, network_ip=str(req_info.get("network_ip") or ""))
        fresh["scan_id"] = str(req_info["scan_id"])
        print(f"[PI-AGENT] Chuqur skanerlash bajarildi: {len(fresh['printers'])} tayyor, {len(fresh['unconfigured_devices'])} yangi")
        _http_json(f"{base}/api/agent/scan-report", method="POST", agent_key=agent_key, payload=fresh)

    job = resp.get("job")
    if not job:
        return False

    print(f"[PI-AGENT] Yangi buyurtma olindi: {job['id']} ({job.get('original_filename')})")
    result = process_claimed_job(base, agent_key, job, default_printer=default_printer)
    print(f"[PI-AGENT] Yakuniy holat: {result.get('status')} — {result.get('status_message')}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TLG SmartPrint Raspberry Pi 5 Print Bridge")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("TLG_SERVER_URL", "http://127.0.0.1:8000"),
        help="Asosiy TLG SmartPrint server manzili (masalan https://print.example.uz)",
    )
    parser.add_argument(
        "--agent-key",
        default=os.environ.get("TLG_AGENT_KEY", ""),
        help="Admin paneldagi X-Agent-Key kaliti (TLG_AGENT_KEY)",
    )
    parser.add_argument(
        "--printer",
        default=os.environ.get("TLG_PRINTER_NAME", ""),
        help="Standart CUPS printer nomi (ixtiyoriy)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("TLG_POLL_INTERVAL", "2.0")),
        help="So'rov oralig'i (soniya)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Faqat bir marta tekshirib chiqish (test uchun)",
    )
    args = parser.parse_args(argv)

    if not args.agent_key.strip():
        print(
            "[PI-AGENT] XATO: TLG_AGENT_KEY muhit o'zgaruvchisi yoki --agent-key berilmagan.",
            file=sys.stderr,
        )
        return 2

    print(f"[PI-AGENT] Ishga tushdi -> Server: {args.server_url}")
    if args.once:
        run_once(args.server_url, args.agent_key, default_printer=args.printer, deep_scan=True)
        return 0

    first_cycle = True
    while True:
        try:
            processed = run_once(
                args.server_url,
                args.agent_key,
                default_printer=args.printer,
                deep_scan=first_cycle,
            )
            first_cycle = False
            if processed:
                continue
        except urllib.error.HTTPError as exc:
            print(f"[PI-AGENT] Server HTTP xatosi ({exc.code}): {exc.reason}", file=sys.stderr)
        except Exception as exc:
            print(f"[PI-AGENT] Aloqa xatosi: {exc}", file=sys.stderr)
        time.sleep(max(1.0, args.poll_interval))


if __name__ == "__main__":
    raise SystemExit(main())
