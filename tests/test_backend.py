"""Automated unit and API integration tests for TLG SmartPrint."""

from __future__ import annotations

import io
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader

from backend.config import BACKUPS_DIR, DEFAULT_ADMIN_PASSWORD, SAMPLES_DIR, STORAGE_DIR
from backend.database import (
    checkpoint_wal,
    create_db_backup,
    create_print_job,
    get_connection,
    get_print_job,
    get_settings,
    init_db,
    maybe_create_startup_backup,
    recover_interrupted_jobs,
    update_settings,
)
from backend.humo_verifier import parse_humo_topup_message
from backend.main import _resolve_storage_file, app, reset_security_limiter
from backend.services.converter import ensure_sample_pdf, normalize_to_pdf
from backend.services.pdf_processor import (
    calculate_print_metrics,
    format_page_range,
    parse_page_range,
    slice_pdf_for_print,
)
from backend.services.printer_adapter import LinuxCupsPrinterAdapter, build_lp_command
from raspberry_pi.pi_print_agent import build_cups_lp_command


class PdfProcessorTests(unittest.TestCase):
    def test_parse_and_format_page_ranges(self) -> None:
        self.assertEqual(parse_page_range("1-3, 5, 7-8", 10), [1, 2, 3, 5, 7, 8])
        self.assertEqual(parse_page_range("5-2, 2", 10), [2, 3, 4, 5])
        self.assertEqual(parse_page_range("all", 4), [1, 2, 3, 4])
        self.assertEqual(format_page_range([8, 1, 3, 2, 5, 7]), "1-3, 5, 7-8")
        with self.assertRaises(ValueError):
            parse_page_range("1-abc", 10)

    def test_calculate_print_metrics(self) -> None:
        bw_simplex = calculate_print_metrics(5, 2, "bw", "simplex", 1)
        self.assertEqual(bw_simplex["physical_sheets"], 10)
        self.assertEqual(bw_simplex["total_printed_pages"], 10)
        self.assertEqual(bw_simplex["estimated_cost"], 4000)
        self.assertEqual(bw_simplex["estimated_seconds"], 75)  # 5s warmup + 10 * 7s

        color_duplex = calculate_print_metrics(5, 1, "color", "duplex", 1)
        self.assertEqual(color_duplex["physical_sheets"], 3)
        self.assertEqual(color_duplex["estimated_cost"], 5400)
        self.assertEqual(color_duplex["estimated_seconds"], 68)  # 5s warmup + ceil(3 * 14s * 1.5)

        nup = calculate_print_metrics(7, 1, "bw", "simplex", 4)
        self.assertEqual(nup["physical_sheets"], 2)


class ConverterAndSlicerTests(unittest.TestCase):
    def test_sample_pdf_and_slicing(self) -> None:
        sample_pdf = ensure_sample_pdf(SAMPLES_DIR)
        self.assertTrue(sample_pdf.exists())
        self.assertEqual(len(PdfReader(str(sample_pdf)).pages), 8)

        with tempfile.TemporaryDirectory() as tmp:
            out_pdf = Path(tmp) / "sliced.pdf"
            count = slice_pdf_for_print(
                source_pdf_path=sample_pdf,
                output_pdf_path=out_pdf,
                selected_pages=[1, 4, 8],
                rotations={"4": 90},
            )
            self.assertEqual(count, 3)
            reader = PdfReader(str(out_pdf))
            self.assertEqual(len(reader.pages), 3)

            # 2-up imposition of 3 pages -> 2 output sheets
            out_2up = Path(tmp) / "sliced_2up.pdf"
            count_2up = slice_pdf_for_print(
                source_pdf_path=sample_pdf,
                output_pdf_path=out_2up,
                selected_pages=[1, 2, 3],
                pages_per_sheet=2,
                orientation="portrait",
            )
            self.assertEqual(count_2up, 3)
            self.assertEqual(len(PdfReader(str(out_2up)).pages), 2)

            # 4-up imposition of 5 pages -> 2 output sheets
            out_4up = Path(tmp) / "sliced_4up.pdf"
            count_4up = slice_pdf_for_print(
                source_pdf_path=sample_pdf,
                output_pdf_path=out_4up,
                selected_pages=[1, 2, 3, 4, 5],
                rotations={"2": 90},
                pages_per_sheet=4,
                orientation="landscape",
            )
            self.assertEqual(count_4up, 5)
            self.assertEqual(len(PdfReader(str(out_4up)).pages), 2)

    def test_multi_format_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            # TXT -> PDF
            txt_in = tmp_dir / "notes.txt"
            txt_in.write_text("Salom TLG SmartPrint\nIkkinchi qator", encoding="utf-8")
            txt_out = tmp_dir / "notes.pdf"
            self.assertGreaterEqual(normalize_to_pdf(txt_in, "notes.txt", txt_out), 1)

            # PNG -> PDF
            png_in = tmp_dir / "img.png"
            Image.new("RGB", (400, 300), color=(79, 70, 229)).save(png_in)
            png_out = tmp_dir / "img.pdf"
            self.assertEqual(normalize_to_pdf(png_in, "img.png", png_out), 1)

            # DOCX -> PDF
            docx_in = tmp_dir / "essay.docx"
            doc = DocxDocument()
            doc.add_heading("Dars rejasi", level=1)
            doc.add_paragraph("O'quvchilar uchun amaliy matn.")
            doc.save(docx_in)
            docx_out = tmp_dir / "essay.pdf"
            self.assertGreaterEqual(normalize_to_pdf(docx_in, "essay.docx", docx_out), 1)

            # PPTX -> PDF
            pptx_in = tmp_dir / "slides.pptx"
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = "Kirish slaydi"
            prs.save(pptx_in)
            pptx_out = tmp_dir / "slides.pdf"
            self.assertEqual(normalize_to_pdf(pptx_in, "slides.pptx", pptx_out), 1)

            # XLSX -> PDF
            import openpyxl

            xlsx_in = tmp_dir / "table.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Natijalar"
            ws.append(["Talaba", "Baho"])
            ws.append(["Talaba A", 98])
            wb.save(xlsx_in)
            xlsx_out = tmp_dir / "table.pdf"
            self.assertGreaterEqual(normalize_to_pdf(xlsx_in, "table.xlsx", xlsx_out), 1)

    def test_bw_grayscale_preserves_transparent_smask_and_cmyk(self) -> None:
        import numpy as np
        import pypdfium2 as pdfium
        from reportlab.lib.colors import CMYKColor
        from reportlab.pdfgen import canvas as rl_canvas

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            overlay_png = tmp_dir / "watermark.png"
            rgba = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            for x in range(60, 140):
                for y in range(60, 140):
                    rgba.putpixel((x, y), (30, 80, 220, 180))
            rgba.save(overlay_png)

            src_pdf = tmp_dir / "transparent_src.pdf"
            c = rl_canvas.Canvas(str(src_pdf), pagesize=(400, 400))
            c.setFillColor(CMYKColor(0.8, 0.2, 0.0, 0.1))
            c.rect(20, 20, 100, 40, fill=1, stroke=0)
            c.drawImage(str(overlay_png), 150, 150, width=200, height=200, mask="auto")
            c.save()

            bw_pdf = tmp_dir / "bw_sliced.pdf"
            slice_pdf_for_print(
                source_pdf_path=src_pdf,
                output_pdf_path=bw_pdf,
                selected_pages=[1],
                color_mode="bw",
            )

            doc = pdfium.PdfDocument(str(bw_pdf))
            try:
                bmp = doc[0].render(scale=1.0)
                pil = bmp.to_pil().convert("RGB")
                arr = np.asarray(pil)
            finally:
                doc.close()

            max_chroma = int((arr.max(axis=2) - arr.min(axis=2)).max())
            self.assertEqual(max_chroma, 0)
            # Outer transparent region around the centered watermark must remain pure white, never solid black
            corner_brightness = float(arr[160:180, 160:180].mean())
            self.assertGreater(corner_brightness, 240.0)
            # CMYK rectangle must become grayscale shade, not disappear or stay chromatic
            cmyk_patch = float(arr[355:365, 40:80].mean())
            self.assertLess(cmyk_patch, 200.0)

    def test_landscape_image_and_nup_imposition(self) -> None:
        from reportlab.pdfgen import canvas as rl_canvas

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            land_img = tmp_dir / "certificate_wide.png"
            Image.new("RGB", (1200, 700), color=(240, 230, 200)).save(land_img)
            land_pdf = tmp_dir / "certificate_wide.pdf"
            self.assertEqual(normalize_to_pdf(land_img, "certificate_wide.png", land_pdf), 1)
            box = PdfReader(str(land_pdf)).pages[0].mediabox
            self.assertGreater(float(box.width), float(box.height))

            slides_pdf = tmp_dir / "landscape_slides.pdf"
            c = rl_canvas.Canvas(str(slides_pdf), pagesize=(960, 540))
            for i in range(4):
                c.drawString(40, 270, f"Landscape slide {i + 1}")
                c.showPage()
            c.save()

            out_2up = tmp_dir / "out_2up.pdf"
            slice_pdf_for_print(
                source_pdf_path=slides_pdf,
                output_pdf_path=out_2up,
                selected_pages=[1, 2],
                pages_per_sheet=2,
                orientation="portrait",
                color_mode="bw",
            )
            box_2up = PdfReader(str(out_2up)).pages[0].mediabox
            # 2 landscape slides stacked top-and-bottom fit best on a portrait A4 sheet
            self.assertLess(float(box_2up.width), float(box_2up.height))

            out_4up = tmp_dir / "out_4up.pdf"
            slice_pdf_for_print(
                source_pdf_path=slides_pdf,
                output_pdf_path=out_4up,
                selected_pages=[1, 2, 3, 4],
                pages_per_sheet=4,
                orientation="portrait",
                color_mode="color",
            )
            box_4up = PdfReader(str(out_4up)).pages[0].mediabox
            # 4 landscape slides fit best in 4 quadrants of a landscape A4 sheet
            self.assertGreater(float(box_4up.width), float(box_4up.height))


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_security_limiter()
        self.client = TestClient(app)
        self._orig_settings = get_settings()
        update_settings({"payment_enabled": False, "printer_mode": "DRY_RUN"})

    def tearDown(self) -> None:
        reset_security_limiter()
        update_settings(
            {
                "printer_mode": self._orig_settings.get("printer_mode", "DRY_RUN"),
                "default_printer_name": self._orig_settings.get("default_printer_name", ""),
                "payment_enabled": self._orig_settings.get("payment_enabled", True),
                "payment_card_number": self._orig_settings.get("payment_card_number", ""),
                "payment_card_holder": self._orig_settings.get("payment_card_holder", ""),
                "payment_window_seconds": self._orig_settings.get("payment_window_seconds", 120),
                "telegram_bot_username": self._orig_settings.get("telegram_bot_username", "@HUMOcardbot"),
            }
        )

    def test_system_status_defaults_to_dry_run(self) -> None:
        res = self.client.get("/api/system-status")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["printer_mode"], "DRY_RUN")
        self.assertFalse(body["hardware_connected"])

    def test_sample_load_slice_and_queue_flow(self) -> None:
        sample_res = self.client.post("/api/documents/sample")
        self.assertEqual(sample_res.status_code, 200)
        doc = sample_res.json()
        self.assertEqual(doc["page_count"], 8)

        # Fetch full normalized PDF
        pdf_res = self.client.get(doc["pdf_url"])
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(len(PdfReader(io.BytesIO(pdf_res.content)).pages), 8)

        # Submit print job for pages [1, 3, 6]
        job_res = self.client.post(
            "/api/print-jobs",
            json={
                "document_id": doc["id"],
                "selected_pages": [1, 3, 6],
                "rotations": {"3": 90},
                "copies": 2,
                "color_mode": "bw",
                "duplex": "simplex",
                "pages_per_sheet": 1,
                "paper_size": "A4",
                "student_name": "Azizbek (9-B)",
            },
        )
        self.assertEqual(job_res.status_code, 200)
        job = job_res.json()
        self.assertEqual(job["status"], "READY_IN_QUEUE")
        self.assertEqual(job["printer_mode"], "DRY_RUN")
        self.assertEqual(job["selected_page_count"], 3)
        self.assertEqual(job["physical_sheets"], 6)
        self.assertEqual(job["page_range_text"], "1, 3, 6")

        # Verify sliced print_ready.pdf has strictly 3 pages
        sliced_res = self.client.get(job["pdf_url"])
        self.assertEqual(sliced_res.status_code, 200)
        self.assertEqual(len(PdfReader(io.BytesIO(sliced_res.content)).pages), 3)

        # Verify job live status endpoint
        status_res = self.client.get(f"/api/print-jobs/{job['id']}/status")
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json()["status"], "READY_IN_QUEUE")

        # Unauthorized access to admin dashboard must return 401
        unauth_res = self.client.get("/api/admin/dashboard")
        self.assertEqual(unauth_res.status_code, 401)

        # Admin login & dashboard verification
        login_res = self.client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.assertEqual(login_res.status_code, 200)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        dash_res = self.client.get("/api/admin/dashboard", headers=headers)
        self.assertEqual(dash_res.status_code, 200)
        self.assertTrue(any(item["id"] == job["id"] for item in dash_res.json()["jobs"]))

        # Mark job as completed and delete cleanly via admin endpoints
        patch_res = self.client.patch(
            f"/api/admin/print-jobs/{job['id']}",
            headers=headers,
            json={"status": "COMPLETED"},
        )
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.json()["status"], "COMPLETED")

        del_res = self.client.delete(
            f"/api/admin/print-jobs/{job['id']}",
            headers=headers,
        )
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["deleted"])

    def test_admin_auth_pricing_and_credentials(self) -> None:
        # Wrong password rejected
        bad_login = self.client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        self.assertEqual(bad_login.status_code, 401)

        # Valid login
        login_res = self.client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.assertEqual(login_res.status_code, 200)
        headers = {"Authorization": f"Bearer {login_res.json()['token']}"}

        # Update 1-sheet pricing to 550 UZS for BW simplex
        original_status = self.client.get("/api/system-status").json()
        orig_pricing = original_status["pricing"]

        upd_res = self.client.put(
            "/api/admin/settings",
            headers=headers,
            json={
                "bw_simplex": 550,
                "bw_duplex": 900,
                "color_simplex": 1200,
                "color_duplex": 2000,
                "seconds_bw_per_sheet": 10,
                "seconds_color_per_sheet": 18,
                "printer_mode": "DRY_RUN",
                "default_printer_name": original_status.get("default_printer_name", ""),
            },
        )
        self.assertEqual(upd_res.status_code, 200)
        self.assertEqual(upd_res.json()["bw_simplex"], 550)
        self.assertEqual(upd_res.json()["seconds_bw_per_sheet"], 10)
        self.assertEqual(upd_res.json()["seconds_color_per_sheet"], 18)

        # Verify student system-status and job cost/duration calculation use 550 UZS & 10s
        new_status = self.client.get("/api/system-status").json()
        self.assertEqual(new_status["pricing"]["bw_simplex"], 550)
        self.assertEqual(new_status["pricing"]["seconds_bw_per_sheet"], 10)

        sample_doc = self.client.post("/api/documents/sample").json()
        job_res = self.client.post(
            "/api/print-jobs",
            json={
                "document_id": sample_doc["id"],
                "selected_pages": [1, 2],
                "copies": 1,
                "color_mode": "bw",
                "duplex": "simplex",
            },
        )
        self.assertEqual(job_res.status_code, 200)
        job = job_res.json()
        self.assertEqual(job["estimated_cost"], 1100)  # 2 sheets * 550 UZS
        self.assertEqual(job["estimated_seconds"], 25)  # 5s warmup + 2 * 10s
        self.client.delete(f"/api/admin/print-jobs/{job['id']}", headers=headers)

        # Restore original pricing and timing
        self.client.put(
            "/api/admin/settings",
            headers=headers,
            json={
                "bw_simplex": orig_pricing["bw_simplex"],
                "bw_duplex": orig_pricing["bw_duplex"],
                "color_simplex": orig_pricing["color_simplex"],
                "color_duplex": orig_pricing["color_duplex"],
                "seconds_bw_per_sheet": orig_pricing.get("seconds_bw_per_sheet", 7),
                "seconds_color_per_sheet": orig_pricing.get("seconds_color_per_sheet", 14),
                "printer_mode": "DRY_RUN",
                "default_printer_name": original_status.get("default_printer_name", ""),
            },
        )

        # Test password update & restore back to admin / admin123
        cred_res = self.client.put(
            "/api/admin/credentials",
            headers=headers,
            json={
                "new_username": "admin_new",
                "current_password": "admin123",
                "new_password": "secret999",
            },
        )
        self.assertEqual(cred_res.status_code, 200)
        new_headers = {"Authorization": f"Bearer {cred_res.json()['token']}"}

        verify_new = self.client.post(
            "/api/admin/login",
            json={"username": "admin_new", "password": "secret999"},
        )
        self.assertEqual(verify_new.status_code, 200)

        # Restore default credentials
        restore_res = self.client.put(
            "/api/admin/credentials",
            headers=new_headers,
            json={
                "new_username": "admin",
                "current_password": "secret999",
                "new_password": "admin123",
            },
        )
        self.assertEqual(restore_res.status_code, 200)

    def test_upload_docx_and_png(self) -> None:
        buf = io.BytesIO()
        Image.new("RGB", (300, 200), color=(16, 185, 129)).save(buf, format="PNG")
        buf.seek(0)

        upload_res = self.client.post(
            "/api/documents/upload",
            files={"file": ("rasm.png", buf.getvalue(), "image/png")},
        )
        self.assertEqual(upload_res.status_code, 200)
        self.assertEqual(upload_res.json()["page_count"], 1)

    def test_linux_cups_adapter_command_and_submit(self) -> None:
        job_stub = {
            "id": "job_pi_001",
            "original_filename": "biologiya.pdf",
            "copies": 2,
            "paper_size": "A4",
            "duplex": "duplex",
            "color_mode": "bw",
            "printer_name": "Canon_G3030",
        }
        cmd = build_lp_command("Canon_G3030", job_stub, Path("/tmp/test.pdf"))
        self.assertEqual(cmd[0], "lp")
        self.assertIn("-d", cmd)
        self.assertIn("Canon_G3030", cmd)
        self.assertIn("sides=two-sided-long-edge", cmd)
        self.assertIn("ColorModel=Gray", cmd)

        pi_cmd = build_cups_lp_command("Canon_G3030", {**job_stub, "color_mode": "color"}, Path("/tmp/test.pdf"))
        self.assertIn("ColorModel=RGB", pi_cmd)

        fake_proc = subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="request id is Canon_G3030-42 (1 file(s))\n",
            stderr="",
        )
        with patch("backend.services.printer_adapter.shutil.which", return_value="/usr/bin/lp"), patch(
            "backend.services.printer_adapter.subprocess.run", return_value=fake_proc
        ) as mock_run:
            result = LinuxCupsPrinterAdapter().submit_job(job_stub, Path("/tmp/test.pdf"))

        self.assertEqual(result["status"], "SENT_TO_PRINTER")
        self.assertIn("Canon_G3030-42", result["status_message"])
        self.assertEqual(mock_run.call_args.args[0][0], "/usr/bin/lp")

    def test_remote_agent_poll_and_report_flow(self) -> None:
        # Wrong agent key must be rejected with 401
        bad_poll = self.client.post(
            "/api/agent/poll",
            headers={"X-Agent-Key": "wrong-agent-key"},
            json={"hostname": "pi5-test", "printers": []},
        )
        self.assertEqual(bad_poll.status_code, 401)

        login_res = self.client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        headers = {"Authorization": f"Bearer {login_res.json()['token']}"}
        dash_before = self.client.get("/api/admin/dashboard", headers=headers).json()
        orig_settings = dash_before["settings"]
        agent_key = orig_settings["agent_api_key"]

        created_job_id = None
        try:
            # Switch server to REMOTE_AGENT mode
            self.client.put(
                "/api/admin/settings",
                headers=headers,
                json={
                    "bw_simplex": orig_settings["bw_simplex"],
                    "bw_duplex": orig_settings["bw_duplex"],
                    "color_simplex": orig_settings["color_simplex"],
                    "color_duplex": orig_settings["color_duplex"],
                    "printer_mode": "REMOTE_AGENT",
                    "default_printer_name": orig_settings["default_printer_name"],
                    "agent_api_key": agent_key,
                },
            )

            sample_doc = self.client.post("/api/documents/sample").json()
            job_res = self.client.post(
                "/api/print-jobs",
                json={
                    "document_id": sample_doc["id"],
                    "selected_pages": [1, 2],
                    "student_name": "Pi Test O'quvchi",
                },
            )
            self.assertEqual(job_res.status_code, 200)
            job = job_res.json()
            created_job_id = job["id"]
            self.assertEqual(job["status"], "QUEUED_FOR_AGENT")
            self.assertEqual(job["printer_mode"], "REMOTE_AGENT")

            # Pi Agent polls with valid key -> claims the queued job
            poll_res = self.client.post(
                "/api/agent/poll",
                headers={"X-Agent-Key": agent_key},
                json={
                    "hostname": "pi5-tashqari",
                    "cpu_temp_c": 48.5,
                    "printers": [
                        {
                            "name": "Canon_G3030_Pi",
                            "is_default": True,
                            "status_text": "Tayyor (Pi CUPS Idle)",
                            "is_offline": False,
                            "jobs_in_queue": 0,
                        }
                    ],
                },
            )
            self.assertEqual(poll_res.status_code, 200)
            poll_body = poll_res.json()
            self.assertTrue(poll_body["ok"])
            self.assertIsNotNone(poll_body["job"])
            self.assertEqual(poll_body["job"]["id"], created_job_id)
            self.assertEqual(poll_body["job"]["status"], "PRINTING_ON_PI")

            # Second poll finds queue empty
            second_poll = self.client.post(
                "/api/agent/poll",
                headers={"X-Agent-Key": agent_key},
                json={"hostname": "pi5-tashqari", "printers": []},
            )
            self.assertIsNone(second_poll.json()["job"])

            # Pi Agent reports completion back to server
            report_res = self.client.post(
                f"/api/agent/jobs/{created_job_id}/report",
                headers={"X-Agent-Key": agent_key},
                json={
                    "status": "COMPLETED",
                    "status_message": "Canon_G3030_Pi qog'ozni muvaffaqiyatli chiqardi.",
                },
            )
            self.assertEqual(report_res.status_code, 200)
            self.assertEqual(report_res.json()["status"], "COMPLETED")
        finally:
            if created_job_id:
                self.client.delete(f"/api/admin/print-jobs/{created_job_id}", headers=headers)
            self.client.put(
                "/api/admin/settings",
                headers=headers,
                json={
                    "bw_simplex": orig_settings["bw_simplex"],
                    "bw_duplex": orig_settings["bw_duplex"],
                    "color_simplex": orig_settings["color_simplex"],
                    "color_duplex": orig_settings["color_duplex"],
                    "printer_mode": "DRY_RUN",
                    "default_printer_name": orig_settings["default_printer_name"],
                    "agent_api_key": agent_key,
                },
            )

    def test_mixed_color_20_pages_with_2_7_16(self) -> None:
        from reportlab.pdfgen import canvas as rl_canvas

        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf)
        for idx in range(1, 21):
            c.setFillColorRGB(0.9, 0.1, 0.1)
            c.rect(72, 700, 120, 40, fill=1, stroke=0)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(72, 660, f"Sahifa {idx}")
            c.showPage()
        c.save()

        up_res = self.client.post(
            "/api/documents/upload",
            files={"file": ("kurs_ishi_20bet.pdf", buf.getvalue(), "application/pdf")},
        )
        self.assertEqual(up_res.status_code, 200)
        doc = up_res.json()
        self.assertEqual(doc["page_count"], 20)

        login_res = self.client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        headers = {"Authorization": f"Bearer {login_res.json()['token']}"}

        job_id = None
        try:
            job_res = self.client.post(
                "/api/print-jobs",
                json={
                    "document_id": doc["id"],
                    "selected_pages": list(range(1, 21)),
                    "color_mode": "mixed",
                    "color_pages": [2, 7, 16],
                    "duplex": "simplex",
                    "copies": 1,
                    "pages_per_sheet": 1,
                    "paper_size": "A4",
                    "student_name": "Malika (Aralash Test)",
                },
            )
            self.assertEqual(job_res.status_code, 200)
            job = job_res.json()
            job_id = job["id"]

            self.assertEqual(job["color_mode"], "mixed")
            self.assertEqual(job["color_pages"], [2, 7, 16])
            self.assertEqual(job["physical_sheets"], 20)
            self.assertEqual(job["bw_sheets"], 17)
            self.assertEqual(job["color_sheets"], 3)
            self.assertEqual(job["estimated_cost"], 17 * 400 + 3 * 1000)
            self.assertEqual(job["estimated_seconds"], 5 + 17 * 7 + 3 * 14)

            segments = job["print_segments"]
            expected_segments = [
                (1, "bw", 1, "1"),
                (2, "color", 1, "2"),
                (3, "bw", 4, "3-6"),
                (4, "color", 1, "7"),
                (5, "bw", 8, "8-15"),
                (6, "color", 1, "16"),
                (7, "bw", 4, "17-20"),
            ]
            self.assertEqual(len(segments), len(expected_segments))
            for seg, (exp_idx, exp_mode, exp_sheets, exp_range) in zip(segments, expected_segments):
                self.assertEqual(seg["segment_index"], exp_idx)
                self.assertEqual(seg["color_mode"], exp_mode)
                self.assertEqual(seg["sheet_count"], exp_sheets)
                self.assertEqual(seg["page_range_text"], exp_range)

                seg_pdf_res = self.client.get(seg["pdf_url"])
                self.assertEqual(seg_pdf_res.status_code, 200)
                seg_reader = PdfReader(io.BytesIO(seg_pdf_res.content))
                self.assertEqual(len(seg_reader.pages), exp_sheets)

            # Verify B&W page 1 in print_ready.pdf was converted to DeviceGray (no rg operator), while page 2 keeps RGB
            master_pdf_res = self.client.get(job["pdf_url"])
            self.assertEqual(master_pdf_res.status_code, 200)
            master_reader = PdfReader(io.BytesIO(master_pdf_res.content))
            self.assertEqual(len(master_reader.pages), 20)
            p1_data = master_reader.pages[0].get_contents().get_data()
            p2_data = master_reader.pages[1].get_contents().get_data()
            self.assertNotIn(b" rg", p1_data)
            self.assertIn(b" g", p1_data)
            self.assertIn(b" rg", p2_data)
        finally:
            if job_id:
                self.client.delete(f"/api/admin/print-jobs/{job_id}", headers=headers)

    def test_multi_user_10_concurrent_queue_and_confirmation_flow(self):
        from concurrent.futures import ThreadPoolExecutor

        admin_login = self.client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.assertEqual(admin_login.status_code, 200)
        token = admin_login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Ensure queue starts cleanly from IDLE
        initial_live = self.client.get("/api/queue/live")
        self.assertEqual(initial_live.status_code, 200)
        pre_existing_ids = []
        init_payload = initial_live.json()
        if init_payload.get("active_job"):
            pre_existing_ids.append(init_payload["active_job"]["id"])
        for item in init_payload.get("waiting_jobs", []):
            pre_existing_ids.append(item["id"])
        for old_id in pre_existing_ids:
            self.client.delete(f"/api/admin/print-jobs/{old_id}", headers=headers)

        idle_check = self.client.get("/api/queue/live").json()
        self.assertEqual(idle_check["printer_state"], "IDLE")
        self.assertFalse(idle_check["printer_busy"])

        up_resp = self.client.post("/api/documents/sample")
        self.assertEqual(up_resp.status_code, 200)
        doc_id = up_resp.json()["id"]

        created_jobs = []
        try:
            def submit_student(idx: int):
                client_tok = f"student-token-{idx}"
                resp = self.client.post(
                    "/api/print-jobs",
                    json={
                        "document_id": doc_id,
                        "student_name": f"Talaba {idx}",
                        "selected_pages": [1, 2],
                        "copies": 1,
                        "color_mode": "bw",
                        "duplex": "simplex",
                        "paper_size": "A4",
                        "client_token": client_tok,
                    },
                )
                return idx, client_tok, resp

            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(submit_student, range(1, 11)))

            for idx, client_tok, resp in results:
                self.assertEqual(resp.status_code, 200, f"Student {idx} failed: {resp.text}")
                created_jobs.append((client_tok, resp.json()))

            token_by_job_id = {job_data["id"]: tok for tok, job_data in created_jobs}

            live_unscoped = self.client.get("/api/queue/live")
            self.assertEqual(live_unscoped.status_code, 200)
            live_pub = live_unscoped.json()
            self.assertTrue(live_pub["printer_busy"])
            self.assertEqual(live_pub["printer_state"], "PRINTING")
            self.assertIsNotNone(live_pub["active_job"])
            self.assertNotIn("client_token", live_pub["active_job"])
            self.assertFalse(live_pub["active_job"]["is_mine"])
            self.assertTrue(live_pub["active_job"]["device_id"].startswith("#"))
            self.assertTrue(live_pub["active_job"]["device_label"])
            self.assertTrue(live_pub["active_job"]["printer_name"])

            active_id = live_pub["active_job"]["id"]
            active_token = token_by_job_id[active_id]
            first_waiting = live_pub["waiting_jobs"][0]
            last_waiting = live_pub["waiting_jobs"][-1]
            other_token = token_by_job_id[first_waiting["id"]]

            live_resp = self.client.get(
                "/api/queue/live", headers={"X-Client-Token": active_token}
            )
            self.assertEqual(live_resp.status_code, 200)
            live = live_resp.json()
            self.assertEqual(live["active_job"]["queue_state"], "ACTIVE_PRINTING")
            self.assertEqual(live["active_job"]["queue_position"], 0)
            self.assertTrue(live["active_job"]["is_mine"])
            self.assertEqual(live["waiting_count"], 9)
            self.assertEqual(len(live["waiting_jobs"]), 9)
            for expected_pos, w_item in enumerate(live["waiting_jobs"], start=1):
                self.assertEqual(w_item["queue_position"], expected_pos)
                self.assertEqual(w_item["queue_state"], "WAITING_IN_QUEUE")
                self.assertGreater(w_item["estimated_wait_seconds"], 0)
                self.assertFalse(w_item["is_mine"])
                self.assertTrue(w_item["device_id"].startswith("#"))
                self.assertTrue(w_item["device_label"])
                self.assertTrue(w_item["printer_name"])

            # Verify strict per-device lock: other users or empty token get 403 Forbidden
            for bad_body in ({"client_token": other_token}, {"client_token": ""}):
                self.assertEqual(
                    self.client.post(f"/api/print-jobs/{active_id}/confirm", json=bad_body).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        f"/api/print-jobs/{active_id}/extend",
                        json={**bad_body, "extra_seconds": 15},
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(f"/api/print-jobs/{active_id}/cancel", json=bad_body).status_code,
                    403,
                )

            # Test /extend with owner's token increases remaining_print_seconds
            before_rem = live["active_job"]["remaining_print_seconds"]
            extend_resp = self.client.post(
                f"/api/print-jobs/{active_id}/extend",
                json={"client_token": active_token, "extra_seconds": 15},
            )
            self.assertEqual(extend_resp.status_code, 200)
            self.assertGreaterEqual(
                extend_resp.json()["remaining_print_seconds"],
                before_rem + 10,
            )

            # Test /cancel removes the last waiting job cleanly using its own token
            cancel_resp = self.client.post(
                f"/api/print-jobs/{last_waiting['id']}/cancel",
                json={"client_token": token_by_job_id[last_waiting["id"]]},
            )
            self.assertEqual(cancel_resp.status_code, 200)
            self.assertEqual(cancel_resp.json()["status"], "CANCELLED")
            after_cancel = self.client.get("/api/queue/live").json()
            self.assertEqual(after_cancel["waiting_count"], 8)

            # Test /confirm marks active job COMPLETED and promotes #1 waiting student immediately
            confirm_resp = self.client.post(
                f"/api/print-jobs/{active_id}/confirm",
                json={"client_token": active_token},
            )
            self.assertEqual(confirm_resp.status_code, 200)
            confirmed = confirm_resp.json()
            self.assertEqual(confirmed["status"], "COMPLETED")
            self.assertEqual(confirmed["queue_state"], "COMPLETED")

            promoted_live = self.client.get(
                "/api/queue/live", headers={"X-Client-Token": other_token}
            ).json()
            self.assertTrue(promoted_live["printer_busy"])
            self.assertIsNotNone(promoted_live["active_job"])
            self.assertEqual(promoted_live["active_job"]["id"], first_waiting["id"])
            self.assertEqual(promoted_live["active_job"]["queue_state"], "ACTIVE_PRINTING")
            self.assertEqual(promoted_live["active_job"]["queue_position"], 0)
            self.assertTrue(promoted_live["active_job"]["is_mine"])
            self.assertEqual(promoted_live["waiting_count"], 7)
            for idx_pos, w_item in enumerate(promoted_live["waiting_jobs"], start=1):
                self.assertEqual(w_item["queue_position"], idx_pos)
                self.assertFalse(w_item["is_mine"])
        finally:
            for _, job_data in created_jobs:
                self.client.delete(f"/api/admin/print-jobs/{job_data['id']}", headers=headers)

    def test_humo_payment_120s_receipt_and_bot_verification_flow(self) -> None:
        login = self.client.post(
            "/api/admin/login", json={"username": "admin", "password": "admin123"}
        ).json()
        admin_headers = {"Authorization": f"Bearer {login['token']}"}

        # Enable Mode B payment gateway and configure HUMO card requisites
        cur_settings = self._orig_settings
        upd_res = self.client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={
                "bw_simplex": cur_settings["bw_simplex"],
                "bw_duplex": cur_settings["bw_duplex"],
                "color_simplex": cur_settings["color_simplex"],
                "color_duplex": cur_settings["color_duplex"],
                "seconds_bw_per_sheet": cur_settings["seconds_bw_per_sheet"],
                "seconds_color_per_sheet": cur_settings["seconds_color_per_sheet"],
                "warmup_seconds": cur_settings["warmup_seconds"],
                "printer_mode": cur_settings["printer_mode"],
                "default_printer_name": cur_settings["default_printer_name"],
                "agent_api_key": cur_settings.get("agent_api_key", ""),
                "payment_enabled": True,
                "payment_card_number": "9860 0000 0000 0000",
                "payment_card_holder": "TEST CARDHOLDER",
                "payment_window_seconds": 120,
                "telegram_bot_username": "https://t.me/HUMOcardbot",
            },
        )
        self.assertEqual(upd_res.status_code, 200)
        self.assertTrue(upd_res.json()["payment_enabled"])
        self.assertEqual(upd_res.json()["telegram_bot_username"], "@HUMOcardbot")

        sys_res = self.client.get("/api/system-status").json()
        self.assertTrue(sys_res["payment"]["enabled"])
        self.assertEqual(sys_res["payment"]["card_number"], "9860 0000 0000 0000")
        self.assertEqual(sys_res["payment"]["window_seconds"], 120)

        doc = self.client.post("/api/documents/sample").json()
        created_ids: list[str] = []
        test_tx_id = f"998877{uuid.uuid4().hex[:6]}"
        test_tx_uid = f"humo_{test_tx_id}"

        img_buf = io.BytesIO()
        Image.new("RGB", (40, 40), color="green").save(img_buf, format="PNG")
        receipt_bytes = img_buf.getvalue()

        try:
            # Clear active jobs if any from earlier manual runs
            existing_live = self.client.get("/api/queue/live").json()
            if existing_live.get("active_job"):
                self.client.delete(
                    f"/api/admin/print-jobs/{existing_live['active_job']['id']}",
                    headers=admin_headers,
                )

            token1 = "stu_pay_user_001"
            res1 = self.client.post(
                "/api/print-jobs",
                headers={"X-Client-Token": token1},
                json={
                    "document_id": doc["id"],
                    "selected_pages": [1, 2],
                    "page_range_text": "1-2",
                    "copies": 1,
                    "color_mode": "bw",
                    "duplex": "simplex",
                    "student_name": "To'lovchi Talaba 1",
                    "client_token": token1,
                },
            )
            self.assertEqual(res1.status_code, 200, res1.text)
            job1 = res1.json()
            created_ids.append(job1["id"])
            self.assertEqual(job1["queue_state"], "AWAITING_PAYMENT")
            self.assertEqual(job1["payment_status"], "AWAITING_PAYMENT")
            self.assertGreater(job1["payment_remaining_seconds"], 0)

            # Unpaid job must NOT block the physical printer queue
            live_before = self.client.get("/api/queue/live").json()
            self.assertFalse(live_before["printer_busy"])
            self.assertEqual(live_before["printer_state"], "IDLE")

            # 1) Unmatched payment returns 400 and still stores receipt for Admin
            with patch(
                "backend.main.verify_and_claim_humo_payment",
                return_value={
                    "verified": False,
                    "error_code": "PAYMENT_NOT_FOUND",
                    "message": "To'lov topilmadi.",
                },
            ):
                fail_res = self.client.post(
                    f"/api/print-jobs/{job1['id']}/verify-payment",
                    headers={"X-Client-Token": token1},
                    data={"client_token": token1},
                    files={"receipt": ("chek1.png", receipt_bytes, "image/png")},
                )
            self.assertEqual(fail_res.status_code, 400)

            # Receipt endpoint must reject anonymous callers (401) and allow Admin (200)
            anon_rcpt = self.client.get(f"/api/admin/print-jobs/{job1['id']}/receipt")
            self.assertEqual(anon_rcpt.status_code, 401)
            adm_rcpt = self.client.get(
                f"/api/admin/print-jobs/{job1['id']}/receipt", headers=admin_headers
            )
            self.assertEqual(adm_rcpt.status_code, 200)
            self.assertEqual(adm_rcpt.content, receipt_bytes)

            # 2) Genuine @HUMOcardbot top-up message parsing + verification succeeds
            expected_cost = int(job1["estimated_cost"])
            formatted_amt = f"{expected_cost:,}".replace(",", ".") + ",00"
            bot_text = (
                f"🎉 To'ldirish\n"
                f"➕ {formatted_amt} UZS\n"
                f"📍 UB P2P Humo2Humo>TAS\n"
                f"💳 HUMOCARD *0000\n"
                f"🕓 20:05 15.11.2026\n"
                f"💰 99.000,00 UZS"
            )
            parsed_tx = parse_humo_topup_message(
                bot_text,
                msg_id=55001,
                msg_date=time.time(),
                buttons=[[{"data": f"c=toggleBalance&id={test_tx_id}&balance=9900000"}]],
            )
            self.assertIsNotNone(parsed_tx)
            self.assertEqual(parsed_tx["tx_uid"], test_tx_uid)
            self.assertEqual(parsed_tx["amount_uzs"], expected_cost)
            self.assertEqual(parsed_tx["card_mask"], "*0000")

            mock_fetch_payload = {
                "connected": True,
                "error": "",
                "bot_username": "@HUMOcardbot",
                "account": {"name": "Test Admin", "username": "testadm", "phone": "+99890"},
                "transactions": [parsed_tx],
            }
            with (
                patch("backend.humo_verifier.get_saved_session_string", return_value="mock_session"),
                patch("backend.humo_verifier._fetch_bot_messages_sync", return_value=mock_fetch_payload),
            ):
                ok_res = self.client.post(
                    f"/api/print-jobs/{job1['id']}/verify-payment",
                    headers={"X-Client-Token": token1},
                    data={"client_token": token1},
                    files={"receipt": ("chek1.png", receipt_bytes, "image/png")},
                )
            self.assertEqual(ok_res.status_code, 200, ok_res.text)
            paid_job1 = ok_res.json()
            self.assertEqual(paid_job1["queue_state"], "ACTIVE_PRINTING")
            self.assertEqual(paid_job1["payment_status"], "PAID")
            self.assertEqual(paid_job1["payment_tx_id"], test_tx_uid)
            self.assertTrue(paid_job1["has_receipt"])

            # 3) Anti-replay check: 2nd job with same cost CANNOT reuse same @HUMOcardbot TX
            token2 = "stu_pay_user_002"
            res2 = self.client.post(
                "/api/print-jobs",
                headers={"X-Client-Token": token2},
                json={
                    "document_id": doc["id"],
                    "selected_pages": [1, 2],
                    "page_range_text": "1-2",
                    "copies": 1,
                    "color_mode": "bw",
                    "duplex": "simplex",
                    "student_name": "To'lovchi Talaba 2",
                    "client_token": token2,
                },
            )
            self.assertEqual(res2.status_code, 200)
            job2 = res2.json()
            created_ids.append(job2["id"])

            with (
                patch("backend.humo_verifier.get_saved_session_string", return_value="mock_session"),
                patch("backend.humo_verifier._fetch_bot_messages_sync", return_value=mock_fetch_payload),
                patch("backend.humo_verifier.time.sleep", return_value=None),
            ):
                replay_res = self.client.post(
                    f"/api/print-jobs/{job2['id']}/verify-payment",
                    headers={"X-Client-Token": token2},
                    data={"client_token": token2},
                    files={"receipt": ("chek2.png", receipt_bytes, "image/png")},
                )
            self.assertEqual(replay_res.status_code, 400)

            # 4) Renew payment timer works cleanly, and Admin manual approval queues job2
            renew_res = self.client.post(
                f"/api/print-jobs/{job2['id']}/renew-payment",
                headers={"X-Client-Token": token2},
                json={"client_token": token2},
            )
            self.assertEqual(renew_res.status_code, 200)
            self.assertGreater(renew_res.json()["payment_remaining_seconds"], 100)

            approve_res = self.client.patch(
                f"/api/admin/print-jobs/{job2['id']}",
                headers=admin_headers,
                json={"status": "APPROVE_PAYMENT", "status_message": "Chek tekshirildi."},
            )
            self.assertEqual(approve_res.status_code, 200, approve_res.text)
            approved_job2 = approve_res.json()
            self.assertEqual(approved_job2["payment_status"], "PAID")
            self.assertEqual(approved_job2["queue_state"], "WAITING_IN_QUEUE")
        finally:
            for jid in created_ids:
                self.client.delete(f"/api/admin/print-jobs/{jid}", headers=admin_headers)
            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM used_payment_transactions WHERE tx_uid = ?",
                    (test_tx_uid,),
                )

    def test_security_hardening_anti_bypass_and_abuse_controls(self) -> None:
        # 1) Security headers & no public admin default password / bot secret leak in HTML
        home_res = self.client.get("/")
        self.assertEqual(home_res.status_code, 200)
        self.assertEqual(home_res.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(home_res.headers.get("x-frame-options"), "DENY")
        self.assertNotIn("admin123", home_res.text)
        self.assertNotIn("HUMOcardbot", home_res.text)

        # Public system-status must not expose Telegram/bot connection details
        sys_res = self.client.get("/api/system-status")
        self.assertEqual(sys_res.status_code, 200)
        sys_payment = sys_res.json().get("payment", {})
        self.assertNotIn("bot_username", sys_payment)
        self.assertNotIn("telegram_connected", sys_payment)

        # Student-facing verify_and_claim_humo_payment messages must hide Telegram/@HUMOcardbot/raw errors
        from backend.humo_verifier import verify_and_claim_humo_payment

        with (
            patch(
                "backend.humo_verifier.get_telegram_status",
                return_value={"configured": False, "connected": False, "bot_username": "@HUMOcardbot"},
            ),
            patch(
                "backend.humo_verifier._fetch_bot_messages_sync",
                return_value={"ok": False, "connected": False, "error": "Telegram ulanmagan", "messages": []},
            ),
        ):
            res_disconnected = verify_and_claim_humo_payment(
                job_id="sec-disc-1",
                expected_amount_uzs=1500,
                payment_created_ts=0,
                attempts=1,
                delay_seconds=0,
            )
        self.assertFalse(res_disconnected["verified"])
        self.assertNotIn("humocardbot", res_disconnected["message"].lower())
        self.assertNotIn("telegram", res_disconnected["message"].lower())

        with (
            patch(
                "backend.humo_verifier.get_telegram_status",
                return_value={"configured": True, "connected": True, "bot_username": "@HUMOcardbot"},
            ),
            patch(
                "backend.humo_verifier._fetch_bot_messages_sync",
                return_value={"ok": False, "connected": True, "error": "Telethon AuthKeyError @HUMOcardbot", "messages": []},
            ),
        ):
            res_error = verify_and_claim_humo_payment(
                job_id="sec-err-1",
                expected_amount_uzs=1500,
                payment_created_ts=0,
                attempts=1,
                delay_seconds=0,
            )
        self.assertFalse(res_error["verified"])
        self.assertNotIn("humocardbot", res_error["message"].lower())
        self.assertNotIn("telegram", res_error["message"].lower())
        self.assertNotIn("telethon", res_error["message"].lower())

        with (
            patch(
                "backend.humo_verifier.get_telegram_status",
                return_value={"configured": True, "connected": True, "bot_username": "@HUMOcardbot"},
            ),
            patch(
                "backend.humo_verifier._fetch_bot_messages_sync",
                return_value={"ok": True, "connected": True, "error": None, "messages": []},
            ),
        ):
            res_missing = verify_and_claim_humo_payment(
                job_id="sec-miss-1",
                expected_amount_uzs=1500,
                payment_created_ts=0,
                attempts=1,
                delay_seconds=0,
            )
        self.assertFalse(res_missing["verified"])
        self.assertNotIn("humocardbot", res_missing["message"].lower())
        self.assertNotIn("telegram", res_missing["message"].lower())

        # 2) CUPS command-line / printer-name injection sanitization
        lp_cmd = build_lp_command(
            '-d "EvilPrinter;rm"',
            {"copies": 1, "original_filename": '-o proxy\n"bad.pdf', "paper_size": "EVIL_OPT"},
            Path("/tmp/safe.pdf"),
        )
        self.assertNotIn("EVIL_OPT", " ".join(lp_cmd))
        self.assertIn("media=A4", lp_cmd)
        self.assertFalse(lp_cmd[lp_cmd.index("-d") + 1].startswith("-"))
        self.assertFalse(lp_cmd[lp_cmd.index("-t") + 1].startswith("-"))

        pi_cmd = build_cups_lp_command(
            '--device="bad"',
            {"copies": 1, "original_filename": "--evil.pdf", "paper_size": "bad;opt"},
            Path("/tmp/safe.pdf"),
        )
        self.assertIn("media=A4", pi_cmd)
        self.assertFalse(pi_cmd[pi_cmd.index("-t") + 1].startswith("-"))

        # 3) Brute-force login protection (5 failures -> 6th returns 429) & token invalidation on password change
        for _ in range(5):
            bad_login = self.client.post(
                "/api/admin/login", json={"username": "admin", "password": "wrong_password"}
            )
            self.assertEqual(bad_login.status_code, 401)
        locked_res = self.client.post(
            "/api/admin/login", json={"username": "admin", "password": "admin123"}
        )
        self.assertEqual(locked_res.status_code, 429)

        reset_security_limiter()
        login_res = self.client.post(
            "/api/admin/login", json={"username": "admin", "password": "admin123"}
        )
        self.assertEqual(login_res.status_code, 200)
        token_old = login_res.json()["token"]
        headers_old = {"Authorization": f"Bearer {token_old}"}

        # Rotate credentials -> token_old must become 401 immediately
        upd_cred = self.client.put(
            "/api/admin/credentials",
            headers=headers_old,
            json={
                "new_username": "admin",
                "current_password": "admin123",
                "new_password": "NewStrongPass!99",
            },
        )
        self.assertEqual(upd_cred.status_code, 200)
        token_new = upd_cred.json()["token"]
        headers_new = {"Authorization": f"Bearer {token_new}"}
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=headers_old).status_code, 401)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=headers_new).status_code, 200)

        # Restore default password and get clean headers for teardown cleanup
        restore_cred = self.client.put(
            "/api/admin/credentials",
            headers=headers_new,
            json={
                "new_username": "admin",
                "current_password": "NewStrongPass!99",
                "new_password": "admin123",
            },
        )
        self.assertEqual(restore_cred.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {restore_cred.json()['token']}"}

        update_settings({"payment_enabled": True})
        doc = self.client.post("/api/documents/sample").json()
        stu_a = f"stu_sec_a_{uuid.uuid4().hex[:6]}"
        stu_b = f"stu_sec_b_{uuid.uuid4().hex[:6]}"
        created_ids: list[str] = []

        try:
            # 4) Unpaid PDF lock + Cross-student isolation + Magic-byte spoofed receipt rejection
            res_a = self.client.post(
                "/api/print-jobs",
                headers={"X-Client-Token": stu_a},
                json={
                    "document_id": doc["id"],
                    "selected_pages": [1, 2],
                    "copies": 1,
                    "color_mode": "bw",
                    "duplex": "simplex",
                    "printer_name": '-o malicious_printer "hack"',
                    "student_name": "Sec Test A",
                    "client_token": stu_a,
                },
            )
            self.assertEqual(res_a.status_code, 200, res_a.text)
            job_a = res_a.json()
            created_ids.append(job_a["id"])
            self.assertNotIn("malicious_printer", job_a["printer_name"])
            self.assertIn("access_key=", job_a["pdf_url"])

            # Unpaid PDF blocked for student (even with access_key), allowed for Admin
            self.assertEqual(self.client.get(job_a["pdf_url"]).status_code, 403)
            self.assertEqual(
                self.client.get(f"/api/print-jobs/{job_a['id']}/pdf", headers=admin_headers).status_code,
                200,
            )

            # Spoofed script disguised as PNG receipt must be rejected with 400
            spoof_res = self.client.post(
                f"/api/print-jobs/{job_a['id']}/verify-payment",
                headers={"X-Client-Token": stu_a},
                data={"client_token": stu_a},
                files={"receipt": ("evil.png", b"<script>alert(1)</script>", "image/png")},
            )
            self.assertEqual(spoof_res.status_code, 400)

            # Admin approves job_a -> Student A (signed URL) gets 200, Student B without key gets 403
            app_res = self.client.patch(
                f"/api/admin/print-jobs/{job_a['id']}",
                headers=admin_headers,
                json={"status": "APPROVE_PAYMENT"},
            )
            self.assertEqual(app_res.status_code, 200)
            self.assertEqual(self.client.get(job_a["pdf_url"]).status_code, 200)
            self.assertEqual(
                self.client.get(f"/api/print-jobs/{job_a['id']}/pdf", headers={"X-Client-Token": stu_b}).status_code,
                403,
            )

            # Student responses must omit admin-only client_ip/receipt_url, and /api/queue/live masks other students' filenames
            self.assertEqual(job_a.get("client_ip"), "")
            self.assertEqual(job_a.get("receipt_url"), "")

            live_a = self.client.get("/api/queue/live", headers={"X-Client-Token": stu_a}).json()
            live_b = self.client.get("/api/queue/live", headers={"X-Client-Token": stu_b}).json()

            def _find_in_live(payload: dict, target_id: str) -> dict | None:
                items = []
                if payload.get("active_job"):
                    items.append(payload["active_job"])
                items.extend(payload.get("waiting_jobs", []))
                for it in items:
                    if it.get("id") == target_id:
                        return it
                return None

            item_a = _find_in_live(live_a, job_a["id"])
            item_b = _find_in_live(live_b, job_a["id"])
            self.assertIsNotNone(item_a)
            self.assertIsNotNone(item_b)
            self.assertTrue(item_a["is_mine"])
            self.assertEqual(item_a["original_filename"], job_a["original_filename"])
            self.assertFalse(item_b["is_mine"])
            self.assertNotEqual(item_b["original_filename"], job_a["original_filename"])
            self.assertEqual(item_b["original_filename"], f"Hujjat ({job_a['selected_page_count']} bet)")

            # 5) Queue /extend cap (+60s max above estimated/90s ceiling)
            extend_hit_cap = False
            for _ in range(10):
                ext_res = self.client.post(
                    f"/api/print-jobs/{job_a['id']}/extend",
                    headers={"X-Client-Token": stu_a},
                    json={"client_token": stu_a, "extra_seconds": 15},
                )
                if ext_res.status_code == 400:
                    extend_hit_cap = True
                    break
            self.assertTrue(extend_hit_cap, "Expected /extend to reject infinite queue holding")

            # 6) Per-student unfinished job flood limit (3 unfinished OK, 4th -> 429)
            flood_tok = f"stu_flood_{uuid.uuid4().hex[:6]}"
            for idx in range(3):
                r = self.client.post(
                    "/api/print-jobs",
                    headers={"X-Client-Token": flood_tok},
                    json={
                        "document_id": doc["id"],
                        "selected_pages": [1],
                        "copies": 1,
                        "color_mode": "bw",
                        "duplex": "simplex",
                        "student_name": f"Flood {idx}",
                        "client_token": flood_tok,
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                created_ids.append(r.json()["id"])

            r4 = self.client.post(
                "/api/print-jobs",
                headers={"X-Client-Token": flood_tok},
                json={
                    "document_id": doc["id"],
                    "selected_pages": [1],
                    "copies": 1,
                    "color_mode": "bw",
                    "duplex": "simplex",
                    "student_name": "Flood 4",
                    "client_token": flood_tok,
                },
            )
            self.assertEqual(r4.status_code, 429)
        finally:
            for jid in created_ids:
                self.client.delete(f"/api/admin/print-jobs/{jid}", headers=admin_headers)


class DocumentLayoutAndPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_security_limiter()
        self.client = TestClient(app)

    def test_prepare_pptx_fixes_horizontal_and_vertical_overflow(self) -> None:
        import tempfile
        from pathlib import Path
        from pptx import Presentation
        from pptx.enum.text import MSO_AUTO_SIZE
        from pptx.util import Inches, Pt
        from backend.services.converter import _prepare_pptx_for_export

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "overflow.pptx"
            dst = Path(tmp) / "fixed.pptx"
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[6])

            # 1) word_wrap=False horizontal code pill overflow
            tb1 = slide.shapes.add_textbox(Inches(0.5), Inches(1.0), Inches(2.4), Inches(0.55))
            tf1 = tb1.text_frame
            tf1.word_wrap = False
            tf1.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            p1 = tf1.paragraphs[0]
            r1 = p1.add_run()
            r1.text = "qiymat1 if shart else qiymat2"
            r1.font.size = Pt(24)

            # 2) SHAPE_TO_FIT_TEXT card vertical overflow
            tb2 = slide.shapes.add_textbox(Inches(0.5), Inches(2.0), Inches(2.2), Inches(0.85))
            tf2 = tb2.text_frame
            tf2.word_wrap = True
            tf2.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
            p2 = tf2.paragraphs[0]
            r2 = p2.add_run()
            r2.text = "Ushbu matn kichkina kartochka balandligidan oshib ketmasligi uchun avtomatik moslashtirilishi kerak."
            r2.font.size = Pt(18)

            prs.save(str(src))
            out = _prepare_pptx_for_export(src, dst)
            self.assertEqual(out, dst)

            fixed = Presentation(str(dst))
            sh1, sh2 = list(fixed.slides[0].shapes)[:2]
            self.assertEqual(sh1.text_frame.auto_size, MSO_AUTO_SIZE.NONE)
            self.assertLess(sh1.text_frame.paragraphs[0].runs[0].font.size.pt, 24.0)
            self.assertEqual(sh2.text_frame.auto_size, MSO_AUTO_SIZE.NONE)
            self.assertLess(sh2.text_frame.paragraphs[0].runs[0].font.size.pt, 18.0)

    def test_prepare_docx_preserves_cached_pageref_without_bookmark_error(self) -> None:
        import tempfile
        import zipfile
        from pathlib import Path
        from backend.services.converter import _prepare_docx_for_export

        doc_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r><w:t>1.1. Mavzu\t</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText xml:space="preserve"> PAGEREF _TocMissing123 \\h </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>7</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
    <w:p>
      <w:fldSimple w:instr=" PAGEREF _TocMissing456 \\h "><w:r><w:t>12</w:t></w:r></w:fldSimple>
    </w:p>
  </w:body>
</w:document>"""

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "toc.docx"
            dst = Path(tmp) / "toc_fixed.docx"
            with zipfile.ZipFile(src, "w") as zf:
                zf.writestr("word/document.xml", doc_xml)

            out = _prepare_docx_for_export(src, dst)
            self.assertEqual(out, dst)
            with zipfile.ZipFile(dst, "r") as zf:
                sanitized = zf.read("word/document.xml").decode("utf-8")
            self.assertIn(">7<", sanitized)
            self.assertIn(">12<", sanitized)
            self.assertNotIn("PAGEREF _TocMissing123", sanitized)
            self.assertNotIn("PAGEREF _TocMissing456", sanitized)

    def test_markdown_tables_and_code_blocks_render_to_pdf(self) -> None:
        import tempfile
        from pathlib import Path
        from backend.services.converter import normalize_to_pdf

        md_text = (
            "# Asosiy Sarlavha\n\n"
            "Matn ichida **qalin** va `kod` bor.\n\n"
            "| Modul | Tavsif | Holat |\n"
            "| --- | --- | --- |\n"
            "| Auth | Foydalanuvchi kirishi va token tekshiruvi | Tayyor |\n"
            "| Print | Canon G3030 chiqarish navbati | Faol |\n\n"
            "```python\nprint('Salom SmartPrint')\n```\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "sample.md"
            pdf_path = Path(tmp) / "sample.pdf"
            md_path.write_text(md_text, encoding="utf-8")
            pages = normalize_to_pdf(md_path, "sample.md", pdf_path)
            self.assertGreaterEqual(pages, 1)
            extracted = "\n".join(p.extract_text() or "" for p in PdfReader(str(pdf_path)).pages)
            self.assertIn("Asosiy Sarlavha", extracted)
            self.assertIn("Modul", extracted)
            self.assertIn("Salom SmartPrint", extracted)

    def test_document_page_image_endpoint_returns_png(self) -> None:
        from PIL import Image as PILImage

        sample_res = self.client.post("/api/documents/sample")
        self.assertEqual(sample_res.status_code, 200)
        doc_id = sample_res.json()["id"]

        img_res = self.client.get(f"/api/documents/{doc_id}/pages/1/image?scale=1.5")
        self.assertEqual(img_res.status_code, 200, img_res.text)
        self.assertEqual(img_res.headers["content-type"], "image/png")
        with PILImage.open(io.BytesIO(img_res.content)) as im:
            self.assertGreater(im.width, 100)
            self.assertGreater(im.height, 100)

        bad_res = self.client.get(f"/api/documents/{doc_id}/pages/99/image")
        self.assertEqual(bad_res.status_code, 404)


class PersistenceAndBackupTests(unittest.TestCase):
    def test_sqlite_wal_full_sync_and_backup_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            tmp_db = tmp_dir / "test_persist.db"
            backups_dir = tmp_dir / "backups"
            init_db(db_path=tmp_db)

            with get_connection(db_path=tmp_db) as conn:
                jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
                sync_val = conn.execute("PRAGMA synchronous").fetchone()[0]
            self.assertEqual(str(jm).lower(), "wal")
            self.assertEqual(int(sync_val), 2)  # 2 == FULL

            b1 = create_db_backup(db_path=tmp_db, backups_dir=backups_dir, prefix="snap", max_keep=2)
            time.sleep(0.02)
            b2 = create_db_backup(db_path=tmp_db, backups_dir=backups_dir, prefix="snap", max_keep=2)
            time.sleep(0.02)
            b3 = create_db_backup(db_path=tmp_db, backups_dir=backups_dir, prefix="snap", max_keep=2)

            self.assertFalse(b1.exists())
            self.assertTrue(b2.exists())
            self.assertTrue(b3.exists())
            self.assertTrue(b3.read_bytes().startswith(b"SQLite format 3\x00"))

            checkpoint_wal(db_path=tmp_db)
            auto1 = maybe_create_startup_backup(db_path=tmp_db, backups_dir=backups_dir, min_age_seconds=3600)
            self.assertIsNotNone(auto1)
            auto2 = maybe_create_startup_backup(db_path=tmp_db, backups_dir=backups_dir, min_age_seconds=3600)
            self.assertIsNone(auto2)

    def test_recover_interrupted_jobs_and_portable_storage_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = Path(tmp) / "recover.db"
            init_db(db_path=tmp_db)
            with get_connection(db_path=tmp_db) as conn:
                conn.execute(
                    """
                    INSERT INTO documents (id, original_filename, file_type, file_size, normalized_pdf_path, page_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("doc_rec_1", "doc.pdf", "pdf", 100, "storage/normalized/doc_rec_1.pdf", 1, "2026-11-16T00:00:00Z"),
                )
            now = time.time()
            create_print_job(
                {
                    "id": "job_powercut_1",
                    "document_id": "doc_rec_1",
                    "original_filename": "doc.pdf",
                    "student_name": "Talaba B",
                    "selected_pages": [1],
                    "page_range_text": "1",
                    "rotations": {},
                    "selected_page_count": 1,
                    "copies": 1,
                    "color_mode": "bw",
                    "duplex": "simplex",
                    "orientation": "portrait",
                    "pages_per_sheet": 1,
                    "paper_size": "A4",
                    "total_printed_pages": 1,
                    "physical_sheets": 1,
                    "estimated_cost": 400,
                    "estimated_seconds": 10,
                    "printer_name": "",
                    "printer_mode": "DRY_RUN",
                    "status": "QUEUED_DRY_RUN",
                    "status_message": "Chop etilmoqda",
                    "output_pdf_path": "storage/jobs/job_powercut_1/print_ready.pdf",
                    "created_at": "2026-11-16T00:00:00Z",
                    "queue_state": "ACTIVE_PRINTING",
                    "printing_until_ts": now - 600.0,
                    "confirm_deadline_ts": 0.0,
                },
                db_path=tmp_db,
            )

            recovered = recover_interrupted_jobs(db_path=tmp_db, now_ts=now, confirm_timeout_seconds=90)
            self.assertEqual(recovered, 1)
            job_after = get_print_job("job_powercut_1", db_path=tmp_db)
            assert job_after is not None
            self.assertEqual(job_after["queue_state"], "AWAITING_CONFIRMATION")
            self.assertAlmostEqual(float(job_after["confirm_deadline_ts"]), now + 90.0, delta=1.0)

        # Portable storage resolution across OS / moved folders
        sample_target = STORAGE_DIR / "samples" / "portable_probe.tmp"
        sample_target.parent.mkdir(parents=True, exist_ok=True)
        sample_target.write_bytes(b"ok")
        try:
            resolved = _resolve_storage_file(r"C:\MovedLaptop\TLG_PRINTER\storage\samples\portable_probe.tmp")
            self.assertEqual(resolved.resolve(), sample_target.resolve())
        finally:
            sample_target.unlink(missing_ok=True)

    def test_admin_backup_download_requires_auth_and_returns_sqlite(self) -> None:
        reset_security_limiter()
        client = TestClient(app)
        anon_res = client.get("/api/admin/backup")
        self.assertEqual(anon_res.status_code, 401)

        login_res = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": DEFAULT_ADMIN_PASSWORD},
        )
        self.assertEqual(login_res.status_code, 200)
        token = login_res.json()["token"]

        created_name = ""
        try:
            res = client.get("/api/admin/backup", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.content.startswith(b"SQLite format 3\x00"))
            disp = res.headers.get("content-disposition", "")
            self.assertIn("smartprint_manual_", disp)
            if 'filename="' in disp:
                created_name = disp.split('filename="', 1)[1].split('"', 1)[0]
        finally:
            if created_name:
                (BACKUPS_DIR / created_name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
