"""Automated unit and API integration tests for TLG SmartPrint."""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader

from backend.config import SAMPLES_DIR
from backend.main import app
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


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

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

            live_resp = self.client.get("/api/queue/live")
            self.assertEqual(live_resp.status_code, 200)
            live = live_resp.json()
            self.assertTrue(live["printer_busy"])
            self.assertEqual(live["printer_state"], "PRINTING")
            self.assertIsNotNone(live["active_job"])
            self.assertEqual(live["active_job"]["queue_state"], "ACTIVE_PRINTING")
            self.assertEqual(live["active_job"]["queue_position"], 0)
            self.assertEqual(live["waiting_count"], 9)
            self.assertEqual(len(live["waiting_jobs"]), 9)
            for expected_pos, w_item in enumerate(live["waiting_jobs"], start=1):
                self.assertEqual(w_item["queue_position"], expected_pos)
                self.assertEqual(w_item["queue_state"], "WAITING_IN_QUEUE")
                self.assertGreater(w_item["estimated_wait_seconds"], 0)

            active_job = live["active_job"]
            active_id = active_job["id"]
            active_token = active_job["client_token"]
            first_waiting = live["waiting_jobs"][0]
            last_waiting = live["waiting_jobs"][-1]

            # Test /extend increases remaining_print_seconds
            before_rem = active_job["remaining_print_seconds"]
            extend_resp = self.client.post(
                f"/api/print-jobs/{active_id}/extend",
                json={"client_token": active_token, "extra_seconds": 15},
            )
            self.assertEqual(extend_resp.status_code, 200)
            self.assertGreaterEqual(
                extend_resp.json()["remaining_print_seconds"],
                before_rem + 10,
            )

            # Test /cancel removes the last waiting job cleanly
            cancel_resp = self.client.post(
                f"/api/print-jobs/{last_waiting['id']}/cancel",
                json={"client_token": last_waiting["client_token"]},
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

            promoted_live = self.client.get("/api/queue/live").json()
            self.assertTrue(promoted_live["printer_busy"])
            self.assertIsNotNone(promoted_live["active_job"])
            self.assertEqual(promoted_live["active_job"]["id"], first_waiting["id"])
            self.assertEqual(promoted_live["active_job"]["queue_state"], "ACTIVE_PRINTING")
            self.assertEqual(promoted_live["active_job"]["queue_position"], 0)
            self.assertEqual(promoted_live["waiting_count"], 7)
            for idx_pos, w_item in enumerate(promoted_live["waiting_jobs"], start=1):
                self.assertEqual(w_item["queue_position"], idx_pos)
        finally:
            for _, job_data in created_jobs:
                self.client.delete(f"/api/admin/print-jobs/{job_data['id']}", headers=headers)


if __name__ == "__main__":
    unittest.main()
