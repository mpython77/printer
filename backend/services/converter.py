"""Document normalization to PDF and 8-page Uzbek educational sample PDF generator."""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

from docx import Document as DocxDocument
from PIL import Image, ImageOps
from pptx import Presentation
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_FONTS_REGISTERED = False
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_MONO = "Courier"


def _pick_existing_font(candidates: list[Path]) -> Path | None:
    """Return the first existing font file from candidate paths."""
    for path in candidates:
        if path.exists():
            return path
    return None


def _ensure_fonts() -> tuple[str, str, str]:
    """Register Unicode TTF fonts from Linux (Raspberry Pi/Debian) or Windows Fonts when available."""
    global _FONTS_REGISTERED, FONT_REGULAR, FONT_BOLD, FONT_MONO
    if _FONTS_REGISTERED:
        return FONT_REGULAR, FONT_BOLD, FONT_MONO

    regular_path = _pick_existing_font([
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ])
    bold_path = _pick_existing_font([
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
    ])
    mono_path = _pick_existing_font([
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeMono.ttf"),
        Path(r"C:\Windows\Fonts\consola.ttf"),
    ])

    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont("SmartArial", str(regular_path)))
            FONT_REGULAR = "SmartArial"
        if bold_path:
            pdfmetrics.registerFont(TTFont("SmartArialBold", str(bold_path)))
            FONT_BOLD = "SmartArialBold"
        if mono_path:
            pdfmetrics.registerFont(TTFont("SmartConsola", str(mono_path)))
            FONT_MONO = "SmartConsola"
    except Exception:
        FONT_REGULAR = "Helvetica"
        FONT_BOLD = "Helvetica-Bold"
        FONT_MONO = "Courier"

    _FONTS_REGISTERED = True
    return FONT_REGULAR, FONT_BOLD, FONT_MONO


def _build_styles() -> dict[str, ParagraphStyle]:
    reg, bold, mono = _ensure_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "SmartTitle",
            parent=base["Title"],
            fontName=bold,
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "SmartH1",
            parent=base["Heading1"],
            fontName=bold,
            fontSize=16,
            leading=22,
            textColor=colors.HexColor("#312e81"),
            spaceBefore=8,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "SmartH2",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=12.5,
            leading=17,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "SmartBody",
            parent=base["Normal"],
            fontName=reg,
            fontSize=10.5,
            leading=15.5,
            textColor=colors.HexColor("#334155"),
            spaceAfter=6,
        ),
        "code": ParagraphStyle(
            "SmartCode",
            parent=base["Code"],
            fontName=mono,
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#0f172a"),
            backColor=colors.HexColor("#f1f5f9"),
            borderPadding=8,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "slide_title": ParagraphStyle(
            "SmartSlideTitle",
            parent=base["Heading1"],
            fontName=bold,
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#1e1b4b"),
            spaceAfter=12,
        ),
    }


def _convert_pdf(input_path: Path, output_pdf_path: Path) -> int:
    reader = PdfReader(str(input_path))
    page_count = len(reader.pages)
    if page_count <= 0:
        raise ValueError("PDF faylda birorta ham bet topilmadi.")
    shutil.copyfile(input_path, output_pdf_path)
    return page_count


def _convert_image(input_path: Path, output_pdf_path: Path) -> int:
    with Image.open(input_path) as img:
        oriented = ImageOps.exif_transpose(img)
        if oriented.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", oriented.size, (255, 255, 255))
            if oriented.mode == "P":
                oriented = oriented.convert("RGBA")
            mask = oriented.split()[-1] if oriented.mode in ("RGBA", "LA") else None
            background.paste(oriented, mask=mask)
            rgb = background
        else:
            rgb = oriented.convert("RGB")

        # Fit onto crisp A4 canvas (150 DPI -> 1240 x 1754 px)
        a4_w, a4_h = 1240, 1754
        margin = 60
        max_w, max_h = a4_w - 2 * margin, a4_h - 2 * margin
        scale = min(max_w / rgb.width, max_h / rgb.height)
        new_w = max(1, int(rgb.width * scale))
        new_h = max(1, int(rgb.height * scale))
        resized = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (a4_w, a4_h), (255, 255, 255))
        offset_x = (a4_w - new_w) // 2
        offset_y = (a4_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y))
        canvas.save(str(output_pdf_path), "PDF", resolution=150.0)
    return 1


import shutil
import subprocess
import sys
import tempfile
import threading
from io import BytesIO
from PIL import Image as PILImage
from reportlab.lib.pagesizes import landscape
from reportlab.platypus import Image as RLImage

_OFFICE_COM_LOCK = threading.Lock()
_DOCX_BLIP_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_DOCX_VML_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _make_rl_image(blob: bytes, max_w: float, max_h: float) -> RLImage | None:
    """Decode raw image bytes via Pillow and fit them cleanly inside (max_w, max_h) points."""
    try:
        with PILImage.open(BytesIO(blob)) as im:
            if im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            px_w, px_h = im.size
            if px_w <= 0 or px_h <= 0:
                return None
            out = BytesIO()
            im.save(out, format="PNG")
            out.seek(0)
        pt_w = px_w * 0.75
        pt_h = px_h * 0.75
        scale = min(max_w / pt_w, max_h / pt_h, 1.0)
        return RLImage(out, width=max(12.0, pt_w * scale), height=max(12.0, pt_h * scale))
    except Exception:
        return None


def _convert_office_via_com(input_path: Path, output_pdf_path: Path, kind: str) -> int | None:
    """Convert .docx/.pptx to 1:1 PDF via Windows COM automation (WPS Office / MS Office)."""
    if sys.platform != "win32":
        return None
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return None

    src_path = str(input_path.resolve())
    dst_path = str(output_pdf_path.resolve())
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    prog_ids = (
        ("KWPS.Application", "Word.Application")
        if kind == "docx"
        else ("KWPP.Application", "PowerPoint.Application")
    )

    with _OFFICE_COM_LOCK:
        pythoncom.CoInitialize()
        try:
            for prog_id in prog_ids:
                app = None
                doc_obj = None
                try:
                    if output_pdf_path.exists():
                        output_pdf_path.unlink()
                except OSError:
                    pass
                try:
                    app = win32com.client.DispatchEx(prog_id)
                    try:
                        app.DisplayAlerts = 0
                    except Exception:
                        pass
                    if kind == "docx":
                        try:
                            app.Visible = False
                        except Exception:
                            pass
                        doc_obj = app.Documents.Open(src_path, ReadOnly=True, Visible=False)
                        try:
                            doc_obj.ExportAsFixedFormat(dst_path, 17)
                        except Exception:
                            doc_obj.SaveAs(dst_path, 17)
                    else:
                        doc_obj = app.Presentations.Open(
                            src_path, ReadOnly=1, Untitled=0, WithWindow=0
                        )
                        doc_obj.SaveAs(dst_path, 32)
                except Exception:
                    continue
                finally:
                    if doc_obj is not None:
                        try:
                            doc_obj.Close(0) if kind == "docx" else doc_obj.Close()
                        except Exception:
                            pass
                    if app is not None:
                        try:
                            app.Quit()
                        except Exception:
                            pass
                    doc_obj = None
                    app = None

                if output_pdf_path.exists() and output_pdf_path.stat().st_size > 0:
                    return len(PdfReader(str(output_pdf_path)).pages)
        finally:
            pythoncom.CoUninitialize()
    return None


def _convert_office_via_libreoffice(input_path: Path, output_pdf_path: Path) -> int | None:
    """Convert .docx/.pptx to 1:1 PDF via headless LibreOffice when installed (Linux/macOS/Windows)."""
    bin_path = shutil.which("soffice") or shutil.which("libreoffice")
    if not bin_path:
        return None
    try:
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp_dir:
            proc = subprocess.run(
                [
                    bin_path,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_dir,
                    str(input_path.resolve()),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                return None
            candidate = Path(tmp_dir) / f"{input_path.stem}.pdf"
            if not candidate.exists():
                pdfs = list(Path(tmp_dir).glob("*.pdf"))
                if not pdfs:
                    return None
                candidate = pdfs[0]
            if candidate.stat().st_size <= 0:
                return None
            shutil.move(str(candidate), str(output_pdf_path))
            return len(PdfReader(str(output_pdf_path)).pages)
    except Exception:
        return None


def _extract_docx_element_rids(element) -> list[str]:
    """Collect image relationship IDs embedded inside a DOCX XML subtree."""
    rids: list[str] = []
    for node in element.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "blip":
            rid = node.get(_DOCX_BLIP_ATTR)
            if rid:
                rids.append(rid)
        elif tag == "imagedata":
            rid = node.get(_DOCX_VML_ATTR)
            if rid:
                rids.append(rid)
    return rids


def _convert_docx(input_path: Path, output_pdf_path: Path) -> int:
    com_pages = _convert_office_via_com(input_path, output_pdf_path, "docx")
    if com_pages:
        return com_pages
    lo_pages = _convert_office_via_libreoffice(input_path, output_pdf_path)
    if lo_pages:
        return lo_pages

    styles = _build_styles()
    doc = DocxDocument(str(input_path))
    story = []
    max_img_w = A4[0] - 36 * mm
    max_img_h = A4[1] - 50 * mm
    para_map = {p._element: p for p in doc.paragraphs}
    tbl_map = {t._element: t for t in doc.tables}
    seen_rids: set[str] = set()

    def _append_rids(element) -> None:
        for rid in _extract_docx_element_rids(element):
            if rid in seen_rids:
                continue
            rel = doc.part.rels.get(rid)
            if rel is None or getattr(rel, "is_external", False):
                continue
            seen_rids.add(rid)
            rl_img = _make_rl_image(rel.target_part.blob, max_img_w, max_img_h)
            if rl_img is not None:
                story.append(Spacer(1, 4))
                story.append(rl_img)
                story.append(Spacer(1, 6))

    for child in doc.element.body:
        if child in para_map:
            para = para_map[child]
            text = para.text.strip()
            if text:
                style_name = (para.style.name or "").lower()
                safe_text = escape(text).replace("\n", "<br/>")
                if "heading 1" in style_name or "title" in style_name:
                    story.append(Paragraph(safe_text, styles["h1"]))
                elif "heading" in style_name:
                    story.append(Paragraph(safe_text, styles["h2"]))
                else:
                    story.append(Paragraph(safe_text, styles["body"]))
            else:
                story.append(Spacer(1, 4))
            _append_rids(child)
        elif child in tbl_map:
            tbl = tbl_map[child]
            rows_data = []
            for row in tbl.rows:
                rows_data.append(
                    [Paragraph(escape(cell.text.strip() or " "), styles["body"]) for cell in row.cells]
                )
            if rows_data:
                table = Table(rows_data, repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("PADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.append(Spacer(1, 6))
                story.append(table)
                story.append(Spacer(1, 8))
            _append_rids(child)

    for rid, rel in doc.part.rels.items():
        if rid in seen_rids or getattr(rel, "is_external", False):
            continue
        if "image" not in str(getattr(rel, "reltype", "")).lower():
            continue
        seen_rids.add(rid)
        rl_img = _make_rl_image(rel.target_part.blob, max_img_w, max_img_h)
        if rl_img is not None:
            story.append(Spacer(1, 4))
            story.append(rl_img)
            story.append(Spacer(1, 6))

    if not story:
        story.append(Paragraph("Bo'sh Word hujjati", styles["body"]))

    pdf_doc = SimpleDocTemplate(
        str(output_pdf_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    pdf_doc.build(story)
    return len(PdfReader(str(output_pdf_path)).pages)


def _convert_pptx(input_path: Path, output_pdf_path: Path) -> int:
    com_pages = _convert_office_via_com(input_path, output_pdf_path, "pptx")
    if com_pages:
        return com_pages
    lo_pages = _convert_office_via_libreoffice(input_path, output_pdf_path)
    if lo_pages:
        return lo_pages

    styles = _build_styles()
    prs = Presentation(str(input_path))
    slide_pagesize = landscape(A4)
    max_img_w = slide_pagesize[0] - 40 * mm
    max_img_h = (slide_pagesize[1] - 60 * mm) * 0.65
    story = []

    def _collect_shape(shape, slide_title_shape) -> bool:
        has_content = False
        if hasattr(shape, "shapes"):
            for sub in shape.shapes:
                if _collect_shape(sub, slide_title_shape):
                    has_content = True
            return has_content

        if slide_title_shape is not None and shape == slide_title_shape:
            return False

        if hasattr(shape, "image"):
            try:
                rl_img = _make_rl_image(shape.image.blob, max_img_w, max_img_h)
                if rl_img is not None:
                    story.append(Spacer(1, 4))
                    story.append(rl_img)
                    story.append(Spacer(1, 6))
                    has_content = True
            except Exception:
                pass

        if getattr(shape, "has_table", False):
            rows_data = []
            for row in shape.table.rows:
                rows_data.append(
                    [Paragraph(escape(cell.text.strip() or " "), styles["body"]) for cell in row.cells]
                )
            if rows_data:
                table = Table(rows_data, repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("PADDING", (0, 0), (-1, -1), 5),
                        ]
                    )
                )
                story.append(Spacer(1, 4))
                story.append(table)
                story.append(Spacer(1, 6))
                has_content = True

        if getattr(shape, "has_text_frame", False):
            for p in shape.text_frame.paragraphs:
                line = p.text.strip()
                if line:
                    has_content = True
                    story.append(Paragraph(f"• {escape(line)}", styles["body"]))
        return has_content

    for idx, slide in enumerate(prs.slides, start=1):
        title_shape = None
        title_text = ""
        try:
            title_shape = slide.shapes.title
            if title_shape and title_shape.text:
                title_text = title_shape.text.strip()
        except Exception:
            title_shape = None

        story.append(
            Paragraph(
                f"Slayd {idx}: {escape(title_text or 'Sarlavhasiz slayd')}",
                styles["slide_title"],
            )
        )
        has_body = False
        for shape in slide.shapes:
            if _collect_shape(shape, title_shape):
                has_body = True
        if not has_body:
            story.append(Paragraph("(Slayd tarkibi mavjud emas)", styles["body"]))
        if idx < len(prs.slides):
            story.append(PageBreak())

    if not story:
        story.append(Paragraph("Bo'sh taqdimot fayli", styles["body"]))

    pdf_doc = SimpleDocTemplate(
        str(output_pdf_path),
        pagesize=slide_pagesize,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    pdf_doc.build(story)
    return len(PdfReader(str(output_pdf_path)).pages)


def _convert_text(input_path: Path, output_pdf_path: Path) -> int:
    styles = _build_styles()
    raw = input_path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines() or ["(Bo'sh matn fayli)"]
    story = []
    for line in lines:
        if not line.strip():
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(escape(line), styles["body"]))

    pdf_doc = SimpleDocTemplate(
        str(output_pdf_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    pdf_doc.build(story)
    return len(PdfReader(str(output_pdf_path)).pages)


def normalize_to_pdf(input_path: Path, original_filename: str, output_pdf_path: Path) -> int:
    """Convert any supported uploaded document to a standardized PDF and return page count."""
    ext = Path(original_filename).suffix.lower()
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".pdf":
        return _convert_pdf(input_path, output_pdf_path)
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        return _convert_image(input_path, output_pdf_path)
    if ext == ".docx":
        return _convert_docx(input_path, output_pdf_path)
    if ext == ".pptx":
        return _convert_pptx(input_path, output_pdf_path)
    if ext in {".txt", ".md", ".csv"}:
        return _convert_text(input_path, output_pdf_path)

    raise ValueError(f"Qo'llab-quvvatlanmaydigan fayl turi: {ext}")


def ensure_sample_pdf(samples_dir: Path) -> Path:
    """Create an 8-page Uzbek educational PDF sample for instant testing."""
    samples_dir.mkdir(parents=True, exist_ok=True)
    sample_path = samples_dir / "namuna_oquv_qollanma.pdf"
    if sample_path.exists() and sample_path.stat().st_size > 1000:
        try:
            if len(PdfReader(str(sample_path)).pages) == 8:
                return sample_path
        except Exception:
            pass

    reg, bold, mono = _ensure_fonts()
    styles = _build_styles()
    total_pages = 8

    def draw_chrome(canvas, doc):
        page_num = canvas.getPageNumber()
        w, h = A4
        canvas.saveState()
        # Top subtle accent bar
        canvas.setFillColor(colors.HexColor("#4f46e5"))
        canvas.rect(0, h - 8 * mm, w, 8 * mm, fill=1, stroke=0)

        # Top header label
        canvas.setFont(bold, 9)
        canvas.setFillColor(colors.HexColor("#ffffff"))
        canvas.drawString(18 * mm, h - 5.5 * mm, "TLG SMARTPRINT — O'QUV QO'LLANMA (NAMUNA)")
        canvas.drawRightString(w - 18 * mm, h - 5.5 * mm, f"{page_num}-BET / {total_pages}")

        # Large watermark badge in corner for crystal-clear thumbnail recognition
        canvas.setFillColor(colors.HexColor("#eef2ff"))
        canvas.roundRect(w - 40 * mm, h - 24 * mm, 24 * mm, 12 * mm, 3 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#3730a3"))
        canvas.setFont(bold, 11)
        canvas.drawCentredString(w - 28 * mm, h - 19.5 * mm, f"{page_num}-bet")

        # Footer divider & page number
        canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
        canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        canvas.setFont(reg, 9)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(18 * mm, 9 * mm, "Informatika va Axborot Texnologiyalari kafedrasi")
        canvas.setFont(bold, 9.5)
        canvas.setFillColor(colors.HexColor("#1e293b"))
        canvas.drawRightString(w - 18 * mm, 9 * mm, f"Sahifa {page_num} / {total_pages}")
        canvas.restoreState()

    story = []

    # Page 1: Cover & Table of Contents
    story.append(Spacer(1, 14 * mm))
    cover_banner = Table(
        [[Paragraph("INFORMATIKA VA AXBOROT TEXNOLOGIYALARI", styles["title"])]],
        colWidths=[174 * mm],
    )
    cover_banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2ff")),
                ("BOX", (0, 0), (-1, -1), 1.5, colors.HexColor("#4f46e5")),
                ("PADDING", (0, 0), (-1, -1), 16),
            ]
        )
    )
    story.append(cover_banner)
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            "<b>O'quvchilar uchun amaliy qo'llanma (8 betlik namuna hujjat)</b>",
            styles["h1"],
        )
    )
    story.append(
        Paragraph(
            "Ushbu namuna hujjat TLG SmartPrint tizimida kerakli betlarni tanlash, "
            "oraliq belgilash (masalan: <i>1-3, 6, 8</i>), oq-qora yoki rangli ko'rinishni "
            "tekshirish hamda chop etishga tayyorlashni sinab ko'rish uchun yaratilgan.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Mundarija", styles["h2"]))
    toc_data = [
        ["Bet", "Mavzu nomi", "Bo'lim turi"],
        ["1-bet", "Muqova sahifa va Mundarija", "Kirish"],
        ["2-bet", "1-bob. Algoritmlar va Ma'lumotlar Tuzilmasi", "Nazariya"],
        ["3-bet", "2-bob. Python Dasturlash Asoslari", "Kod namunalari"],
        ["4-bet", "3-bob. Ma'lumotlar Bazasi va SQL So'rovlar", "Jadval va taqqoslash"],
        ["5-bet", "4-bob. Kompyuter Tarmoqlari va OSI Modeli", "Arxitektura"],
        ["6-bet", "5-bob. Amaliy Mashg'ulot Topshiriqlari", "Topshiriqlar"],
        ["7-bet", "6-bob. Nazorat Test Savollari", "Nazorat ishi"],
        ["8-bet", "Ilova: Tezkor Formulalar va Qoidalar", "Ma'lumotnoma"],
    ]
    toc_table = Table(toc_data, colWidths=[24 * mm, 108 * mm, 42 * mm])
    toc_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold),
                ("FONTNAME", (0, 1), (-1, -1), reg),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(toc_table)
    story.append(PageBreak())

    # Page 2: Algorithms
    story.append(Paragraph("1-bob. Algoritmlar va Ma'lumotlar Tuzilmasi", styles["h1"]))
    story.append(
        Paragraph(
            "Algoritm — bu qo'yilgan masalani yechish uchun bajarilishi kerak bo'lgan aniq va chekli "
            "qoidalar ketma-ketligidir. Zamonaviy dasturlashda algoritm samaradorligi vaqt (Time) "
            "va xotira (Space) murakkabligi bilan baholanadi.",
            styles["body"],
        )
    )
    algo_table = Table(
        [
            ["Algoritm", "O'rtacha murakkablik", "Eng yomon holat", "Qo'llanilishi"],
            ["Binary Search", "O(log n)", "O(log n)", "Saralangan massivdan qidirish"],
            ["Merge Sort", "O(n log n)", "O(n log n)", "Barqaror saralash"],
            ["Quick Sort", "O(n log n)", "O(n^2)", "Tezkor xotira ichida saralash"],
            ["BFS / DFS", "O(V + E)", "O(V + E)", "Graf va daraxtlarni aylanib chiqish"],
        ],
        colWidths=[38 * mm, 40 * mm, 36 * mm, 60 * mm],
    )
    algo_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold),
                ("FONTNAME", (0, 1), (-1, -1), reg),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(algo_table)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Asosiy xossalar:", styles["h2"]))
    for bullet in [
        "Aniqlik (Determinizm) — har bir qadam bir xil tushunilishi kerak.",
        "Diskretlik — jarayon alohida qadamlarga bo'linadi.",
        "Natijaviylik — chekli qadamlardan so'ng yakuniy javob olinadi.",
        "Ommaviylik — bir xil turdagi barcha boshlang'ich ma'lumotlar uchun ishlaydi.",
    ]:
        story.append(Paragraph(f"• {bullet}", styles["body"]))
    story.append(PageBreak())

    # Page 3: Python Programming
    story.append(Paragraph("2-bob. Python Dasturlash Asoslari", styles["h1"]))
    story.append(
        Paragraph(
            "Python — o'qishga oson sintaksisi va boy kutubxonalari tufayli ta'lim, veb-ishlanma "
            "hamda sun'iy intellekt sohalarida yetakchi til hisoblanadi.",
            styles["body"],
        )
    )
    story.append(Paragraph("Namuna dastur: O'quvchilar ro'yxatini baholash", styles["h2"]))
    code_sample = (
        "def baho_hisobla(ballar: list[int]) -> str:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;ortacha = sum(ballar) / len(ballar)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;if ortacha >= 86:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;return \"A'lo (5)\"<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;elif ortacha >= 71:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;return \"Yaxshi (4)\"<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;return \"Qoniqarli (3)\"<br/><br/>"
        "print(baho_hisobla([90, 88, 95]))"
    )
    story.append(Paragraph(code_sample, styles["code"]))
    story.append(
        Paragraph(
            "Yuqoridagi funksiya ro'yxatdagi ballarning o'rtacha qiymatini hisoblab, mos baho "
            "toifasini matn ko'rinishida qaytaradi.",
            styles["body"],
        )
    )
    story.append(PageBreak())

    # Page 4: Databases & SQL
    story.append(Paragraph("3-bob. Ma'lumotlar Bazasi va SQL So'rovlar", styles["h1"]))
    story.append(
        Paragraph(
            "Relyatsion ma'lumotlar bazalarida (SQLite, PostgreSQL) ma'lumotlar o'zaro bog'langan "
            "jadvallarda saqlanadi. Quyida asosiy SQL buyruqlari keltirilgan:",
            styles["body"],
        )
    )
    sql_table = Table(
        [
            ["Buyruq", "Vazifasi", "Misol"],
            ["SELECT", "Ma'lumotlarni o'qish", "SELECT ism, guruh FROM oquvchilar;"],
            ["INSERT", "Yangi yozuv qo'shish", "INSERT INTO oquvchilar VALUES (1, 'Ali');"],
            ["UPDATE", "Mavjud yozuvni yangilash", "UPDATE oquvchilar SET ball = 95 WHERE id = 1;"],
            ["DELETE", "Yozuvni o'chirish", "DELETE FROM oquvchilar WHERE id = 1;"],
        ],
        colWidths=[28 * mm, 52 * mm, 94 * mm],
    )
    sql_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold),
                ("FONTNAME", (0, 1), (-1, -1), reg),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(sql_table)
    story.append(PageBreak())

    # Page 5: Computer Networks & OSI Model
    story.append(Paragraph("4-bob. Kompyuter Tarmoqlari va OSI Modeli", styles["h1"]))
    story.append(
        Paragraph(
            "OSI (Open Systems Interconnection) modeli tarmoq aloqasini 7 ta mantiqiy pog'onaga "
            "ajratadi. Har bir pog'ona ma'lumot uzatishda o'ziga xos vazifani bajaradi.",
            styles["body"],
        )
    )
    osi_table = Table(
        [
            ["Pog'ona", "Nomi", "Asosiy protokollar / vazifasi"],
            ["7", "Application (Ilova)", "HTTP, HTTPS, FTP, DNS, SMTP"],
            ["6", "Presentation (Taqdimot)", "Shifrlash (TLS/SSL), siqish"],
            ["5", "Session (Sessiya)", "Aloqa seanslarini boshqarish"],
            ["4", "Transport", "TCP (ishonchli), UDP (tezkor)"],
            ["3", "Network (Tarmoq)", "IP manzillash va marshrutlash"],
            ["2", "Data Link (Kanal)", "MAC manzillar, Ethernet, Wi-Fi"],
            ["1", "Physical (Jismoniy)", "Kabellar, elektr/optik signallar"],
        ],
        colWidths=[22 * mm, 56 * mm, 96 * mm],
    )
    osi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7c2d12")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold),
                ("FONTNAME", (0, 1), (-1, -1), reg),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 6.5),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(osi_table)
    story.append(PageBreak())

    # Page 6: Practical Tasks
    story.append(Paragraph("5-bob. Amaliy Mashg'ulot Topshiriqlari", styles["h1"]))
    story.append(
        Paragraph(
            "O'quvchilar faqat o'z variantiga mos betni yoki mashqlar sahifasini tanlab chop "
            "etishlari mumkin (masalan, faqat 6-betni tanlash).",
            styles["body"],
        )
    )
    for i in range(1, 7):
        story.append(
            Paragraph(
                f"<b>{i}-topshiriq:</b> 1 dan {i * 50} gacha bo'lgan tub sonlarni topuvchi "
                "algoritm tuzing va uning ishlash vaqtini o'lchang.",
                styles["body"],
            )
        )
    story.append(PageBreak())

    # Page 7: Control Test Sheet
    story.append(Paragraph("6-bob. Nazorat Test Savollari", styles["h1"]))
    story.append(Paragraph("O'quvchi F.I.Sh.: ___________________________   Guruh: ________", styles["body"]))
    story.append(Spacer(1, 4 * mm))
    tests = [
        ("1. Binary Search algoritmining vaqt murakkabligi qanday?", "A) O(n)   B) O(log n)   C) O(n^2)   D) O(1)"),
        ("2. Qaysi SQL buyrug'i jadvaldan ma'lumot o'qish uchun ishlatiladi?", "A) UPDATE   B) DELETE   C) SELECT   D) INSERT"),
        ("3. HTTP protokoli OSI modelining qaysi pog'onasida ishlaydi?", "A) 1-pog'ona   B) 3-pog'ona   C) 4-pog'ona   D) 7-pog'ona"),
        ("4. Python'da ro'yxat uzunligini aniqlovchi funksiya qaysi?", "A) size()   B) length()   C) len()   D) count()"),
    ]
    for q, opts in tests:
        story.append(Paragraph(f"<b>{q}</b>", styles["body"]))
        story.append(Paragraph(opts, styles["body"]))
        story.append(Spacer(1, 3 * mm))
    story.append(PageBreak())

    # Page 8: Appendix Formulas & Quick Reference
    story.append(Paragraph("Ilova: Tezkor Formulalar va Qoidalar", styles["h1"]))
    story.append(
        Paragraph(
            "Imtihon oldidan takrorlash uchun qisqacha eslatma sahifasi.",
            styles["body"],
        )
    )
    ref_table = Table(
        [
            ["Tushuncha", "Formula / Qiymat"],
            ["Axborot o'lchovi", "1 Bayt = 8 Bit; 1 KB = 1024 Bayt; 1 MB = 1024 KB"],
            ["Hartley formulasi", "I = log2(N)  (N — teng ehtimolli holatlar soni)"],
            ["O'tkazuvchanlik", "Hajm (bit) = Tezlik (bit/s) × Vaqt (s)"],
            ["RGB rang modeli", "Har bir piksel 24 bit (3 bayt): Qizil, Yashil, Ko'k"],
        ],
        colWidths=[54 * mm, 120 * mm],
    )
    ref_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4338ca")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold),
                ("FONTNAME", (0, 1), (-1, -1), reg),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(ref_table)

    pdf_doc = SimpleDocTemplate(
        str(sample_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=24 * mm,
        bottomMargin=20 * mm,
    )
    pdf_doc.build(story, onFirstPage=draw_chrome, onLaterPages=draw_chrome)
    return sample_path
