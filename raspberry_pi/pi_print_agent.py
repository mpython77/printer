#!/usr/bin/env python3
"""Raspberry Pi 5 remote print bridge for TLG SmartPrint.

Polls the main TLG SmartPrint server (VPS/cloud or local network) using X-Agent-Key,
downloads queued print-ready PDF files, dispatches them to the attached printer via CUPS (`lp`),
tracks completion via `lpstat`, and reports status back to the server.

Pure Python standard library — requires zero third-party pip packages on Raspberry Pi.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.error
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


def discover_local_cups_printers() -> list[dict[str, Any]]:
    """Enumerate printers configured in Raspberry Pi CUPS."""
    if os.environ.get("TLG_PI_SIMULATE_CUPS") == "1":
        return [
            {
                "name": "Canon_G3030_Pi_Sim",
                "is_default": True,
                "status_text": "Tayyor (Raspberry Pi Simulyatsiya)",
                "is_offline": False,
                "jobs_in_queue": 0,
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

    for line in res_p.stdout.splitlines():
        m = re.match(r"^printer\s+(\S+)\s+(.+)$", line.strip(), flags=re.IGNORECASE)
        if not m:
            continue
        name = m.group(1).strip()
        rest = m.group(2).strip()
        lower = rest.lower()
        is_offline = "disabled" in lower or "offline" in lower
        if "now printing" in lower:
            status_text = "Chop etmoqda (Pi CUPS)"
        elif is_offline:
            status_text = "O'chiq / To'xtatilgan (Pi CUPS)"
        elif "is idle" in lower:
            status_text = "Tayyor (Pi CUPS Idle)"
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


def build_cups_lp_command(printer_name: str, job: dict[str, Any], pdf_path: Path) -> list[str]:
    """Build `lp` arguments for the downloaded print job PDF."""
    cmd = ["lp"]
    target = (printer_name or "").strip()
    if target:
        cmd.extend(["-d", target])

    copies = max(1, int(job.get("copies", 1)))
    cmd.extend(["-n", str(copies)])

    title = str(job.get("original_filename") or f"TLG-{job.get('id', 'job')}").strip()
    if title:
        cmd.extend(["-t", title])

    paper_size = str(job.get("paper_size", "A4")).strip() or "A4"
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


def run_once(server_url: str, agent_key: str, default_printer: str = "") -> bool:
    """Send heartbeat + claim up to one queued job. Returns True if a job was processed."""
    base = server_url.rstrip("/")
    payload = {
        "hostname": socket.gethostname(),
        "printers": discover_local_cups_printers(),
        "cpu_temp_c": read_pi_cpu_temp_c(),
    }
    resp = _http_json(f"{base}/api/agent/poll", method="POST", agent_key=agent_key, payload=payload)
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
        default=os.environ.get("TLG_AGENT_KEY", "tlg-pi-secret-2026"),
        help="Admin paneldagi X-Agent-Key kaliti",
    )
    parser.add_argument(
        "--printer",
        default=os.environ.get("TLG_PRINTER_NAME", ""),
        help="Standart CUPS printer nomi (ixtiyoriy)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("TLG_POLL_INTERVAL", "3.0")),
        help="So'rov oralig'i (soniya)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Faqat bir marta tekshirib chiqish (test uchun)",
    )
    args = parser.parse_args(argv)

    print(f"[PI-AGENT] Ishga tushdi -> Server: {args.server_url}")
    if args.once:
        run_once(args.server_url, args.agent_key, default_printer=args.printer)
        return 0

    while True:
        try:
            processed = run_once(args.server_url, args.agent_key, default_printer=args.printer)
            if processed:
                continue
        except urllib.error.HTTPError as exc:
            print(f"[PI-AGENT] Server HTTP xatosi ({exc.code}): {exc.reason}", file=sys.stderr)
        except Exception as exc:
            print(f"[PI-AGENT] Aloqa xatosi: {exc}", file=sys.stderr)
        time.sleep(max(1.0, args.poll_interval))


if __name__ == "__main__":
    raise SystemExit(main())
