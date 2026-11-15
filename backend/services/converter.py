"""Document normalization to PDF and 8-page Uzbek educational sample PDF generator."""

from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from html import escape
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from PIL import Image, ImageOps
from PIL import Image as PILImage
from pptx import Presentation
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepInFrame,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.frames import Frame

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
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "SmartH3",
            parent=base["Heading3"],
            fontName=bold,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            spaceBefore=7,
            spaceAfter=4,
            keepWithNext=True,
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
        "bullet": ParagraphStyle(
            "SmartBullet",
            parent=base["Normal"],
            fontName=reg,
            fontSize=10.5,
            leading=15,
            leftIndent=14,
            firstLineIndent=-9,
            textColor=colors.HexColor("#334155"),
            spaceAfter=4,
        ),
        "quote": ParagraphStyle(
            "SmartQuote",
            parent=base["Normal"],
            fontName=reg,
            fontSize=10,
            leading=14.5,
            leftIndent=14,
            rightIndent=8,
            backColor=colors.HexColor("#f8fafc"),
            textColor=colors.HexColor("#475569"),
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=6,
        ),
        "table_header": ParagraphStyle(
            "SmartTableHeader",
            parent=base["Normal"],
            fontName=bold,
            fontSize=9,
            leading=12.5,
            textColor=colors.white,
            wordWrap="CJK",
        ),
        "table_cell": ParagraphStyle(
            "SmartTableCell",
            parent=base["Normal"],
            fontName=reg,
            fontSize=8.8,
            leading=12.2,
            textColor=colors.HexColor("#1e293b"),
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "SmartCode",
            parent=base["Code"],
            fontName=mono,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#0f172a"),
            backColor=colors.HexColor("#f1f5f9"),
            borderPadding=8,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "code_pre": ParagraphStyle(
            "SmartCodePre",
            parent=base["Code"],
            fontName=mono,
            fontSize=8.2,
            leading=11.2,
            textColor=colors.HexColor("#0f172a"),
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

        # Fit onto crisp 300 DPI A4 canvas matching the image's natural orientation
        a4_w, a4_h = (3508, 2480) if rgb.width > rgb.height else (2480, 3508)
        margin = 72
        max_w, max_h = a4_w - 2 * margin, a4_h - 2 * margin
        scale = min(max_w / rgb.width, max_h / rgb.height)
        new_w = max(1, int(rgb.width * scale))
        new_h = max(1, int(rgb.height * scale))
        resized = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (a4_w, a4_h), (255, 255, 255))
        offset_x = (a4_w - new_w) // 2
        offset_y = (a4_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y))
        canvas.save(str(output_pdf_path), "PDF", resolution=300.0)
    return 1


_OFFICE_COM_LOCK = threading.Lock()
_DOCX_BLIP_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_DOCX_VML_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_EMU_PER_PT = 12700.0
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


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


def _dispatch_com_app(prog_id: str):
    """Instantiate a COM application via DispatchEx, self-healing corrupted pywin32 gen_py cache if needed."""
    import win32com.client

    try:
        return win32com.client.DispatchEx(prog_id)
    except AttributeError as exc:
        msg = str(exc)
        if "CLSIDTo" not in msg and "gen_py" not in msg:
            raise
        from win32com.client import gencache

        gen_dir = Path(gencache.GetGeneratePath())
        if gen_dir.exists():
            for child in gen_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
        for mod_name in [m for m in list(sys.modules) if m.startswith("win32com.gen_py.")]:
            sys.modules.pop(mod_name, None)
        try:
            gencache.Rebuild()
        except Exception:
            pass
        return win32com.client.DispatchEx(prog_id)


_MONOSPACE_FONTS = {"consolas", "courier", "courier new", "dejavu sans mono", "liberation mono"}


def _emu_to_pt(value, default_pt: float = 0.0) -> float:
    return float(value) / _EMU_PER_PT if value is not None else default_pt


def _iter_pptx_leaf_shapes(shapes):
    """Yield non-group shapes recursively so grouped slide boxes are also inspected."""
    for shape in shapes:
        if hasattr(shape, "shapes"):
            yield from _iter_pptx_leaf_shapes(shape.shapes)
        else:
            yield shape


def _resolve_pptx_font_pt(para, run=None, tx_body=None) -> tuple[float, bool, bool]:
    """Return (font_size_pt, is_bold, is_mono) resolving run -> paragraph -> XML defaults."""
    is_bold = False
    is_mono = False
    pt_val: float | None = None

    def _inspect_font(font_obj) -> None:
        nonlocal pt_val, is_bold, is_mono
        if font_obj is None:
            return
        if pt_val is None and font_obj.size is not None:
            pt_val = float(font_obj.size.pt)
        if font_obj.bold:
            is_bold = True
        if font_obj.name and font_obj.name.strip().lower() in _MONOSPACE_FONTS:
            is_mono = True

    if run is not None:
        _inspect_font(run.font)
    _inspect_font(para.font)

    if pt_val is None:
        p_pr = para._p.find(f"{{{_A_NS}}}pPr")
        if p_pr is not None:
            def_rpr = p_pr.find(f"{{{_A_NS}}}defRPr")
            if def_rpr is not None and def_rpr.get("sz"):
                pt_val = int(def_rpr.get("sz")) / 100.0
                if def_rpr.get("b") == "1":
                    is_bold = True

    if pt_val is None and tx_body is not None:
        lst_style = tx_body.find(f"{{{_A_NS}}}lstStyle")
        if lst_style is not None:
            lvl_tag = f"{{{_A_NS}}}lvl{(getattr(para, 'level', 0) or 0) + 1}pPr"
            lvl_ppr = lst_style.find(lvl_tag) or lst_style.find(f"{{{_A_NS}}}lvl1pPr")
            if lvl_ppr is not None:
                def_rpr = lvl_ppr.find(f"{{{_A_NS}}}defRPr")
                if def_rpr is not None and def_rpr.get("sz"):
                    pt_val = int(def_rpr.get("sz")) / 100.0
                    if def_rpr.get("b") == "1":
                        is_bold = True

    return (pt_val if pt_val is not None else 15.0), is_bold, is_mono


def _estimate_pptx_tf_metrics(tf, avail_w_pt: float, font_scale: float = 1.0) -> tuple[float, float]:
    """Estimate (wrapped_height_pt, max_unwrapped_line_width_pt) using conservative WPS metrics."""
    tx_body = tf._txBody
    total_h = 0.0
    max_line_w = 0.0
    safe_w = max(24.0, avail_w_pt)

    for para in tf.paragraphs:
        raw_text = para.text or ""
        runs = list(para.runs)
        sample_run = runs[0] if runs else None
        base_pt, is_bold, is_mono = _resolve_pptx_font_pt(para, sample_run, tx_body)
        if runs:
            pts = [_resolve_pptx_font_pt(para, r, tx_body)[0] for r in runs if (r.text or "")]
            if pts:
                base_pt = max(pts)
            if any(r.font.bold for r in runs):
                is_bold = True
            if any((r.font.name or "").strip().lower() in _MONOSPACE_FONTS for r in runs):
                is_mono = True

        eff_pt = max(7.5, base_pt * font_scale)
        alpha_chars = [c for c in raw_text if c.isalpha()]
        upper_ratio = (sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)) if alpha_chars else 0.0
        if is_mono:
            char_factor = 0.64
        elif upper_ratio >= 0.45:
            char_factor = 0.67 if is_bold else 0.62
        else:
            char_factor = 0.59 if is_bold else 0.55
        char_w = eff_pt * char_factor

        ls = para.line_spacing
        if isinstance(ls, (int, float)) and ls > 0:
            ls_mult = max(1.05, float(ls) * 1.06)
        elif hasattr(ls, "pt"):
            ls_mult = max(1.05, float(ls.pt) / max(eff_pt, 1.0))
        else:
            ls_mult = 1.28

        if not raw_text.strip():
            total_h += eff_pt * ls_mult * 0.75
            continue

        lines_in_para = 0
        for segment in raw_text.split("\n"):
            seg_w = len(segment) * char_w
            if seg_w > max_line_w:
                max_line_w = seg_w
            words = [w for w in segment.split(" ") if w != ""]
            if not words:
                lines_in_para += 1
                continue
            cur_w = 0.0
            lines_in_para += 1
            for tok in words:
                tok_w = len(tok) * char_w
                if cur_w == 0.0:
                    if tok_w > safe_w:
                        extra = max(0, math.ceil(tok_w / safe_w) - 1)
                        lines_in_para += extra
                        rem = tok_w - extra * safe_w
                        cur_w = rem
                    else:
                        cur_w = tok_w
                elif cur_w + char_w + tok_w <= safe_w:
                    cur_w += char_w + tok_w
                else:
                    lines_in_para += 1
                    if tok_w > safe_w:
                        extra = max(0, math.ceil(tok_w / safe_w) - 1)
                        lines_in_para += extra
                        cur_w = tok_w - extra * safe_w
                    else:
                        cur_w = tok_w

        sp_before = _emu_to_pt(para.space_before, 0.0) * font_scale
        sp_after = _emu_to_pt(para.space_after, 0.0) * font_scale
        total_h += sp_before + (lines_in_para * eff_pt * ls_mult) + sp_after

    return total_h, max_line_w


def _scale_pptx_text_frame(tf, scale: float, Pt) -> None:
    """Apply explicit scaled font sizes and spacing across every run and paragraph in a text frame."""
    tx_body = tf._txBody
    for para in tf.paragraphs:
        para_pt, _, _ = _resolve_pptx_font_pt(para, None, tx_body)
        has_runs = False
        for run in para.runs:
            has_runs = True
            cur_pt, _, _ = _resolve_pptx_font_pt(para, run, tx_body)
            run.font.size = Pt(round(max(7.5, cur_pt * scale), 1))
        if not has_runs or para.font.size is not None:
            para.font.size = Pt(round(max(7.5, para_pt * scale), 1))
        p_pr = para._p.find(f"{{{_A_NS}}}pPr")
        if p_pr is not None:
            def_rpr = p_pr.find(f"{{{_A_NS}}}defRPr")
            if def_rpr is not None and def_rpr.get("sz"):
                old_sz = int(def_rpr.get("sz")) / 100.0
                def_rpr.set("sz", str(int(round(max(7.5, old_sz * scale) * 100))))
        if para.space_before is not None and _emu_to_pt(para.space_before) > 1.0:
            para.space_before = Pt(round(max(0.0, _emu_to_pt(para.space_before) * scale), 1))
        if para.space_after is not None and _emu_to_pt(para.space_after) > 1.0:
            para.space_after = Pt(round(max(0.0, _emu_to_pt(para.space_after) * scale), 1))


def _prepare_pptx_for_export(input_path: Path, output_path: Path) -> Path:
    """Prevent WPS/PowerPoint text box stretching and horizontal word_wrap=False collisions before PDF export."""
    if input_path.suffix.lower() != ".pptx":
        return input_path
    try:
        from pptx.enum.text import MSO_AUTO_SIZE
        from pptx.util import Pt

        prs = Presentation(str(input_path))
    except Exception:
        return input_path

    modified = False
    for slide in prs.slides:
        for shape in _iter_pptx_leaf_shapes(slide.shapes):
            if not getattr(shape, "has_text_frame", False):
                continue
            tf = shape.text_frame
            full_text = (tf.text or "").strip()
            if not full_text:
                continue

            ml = _emu_to_pt(tf.margin_left, 7.2)
            mr = _emu_to_pt(tf.margin_right, 7.2)
            mt = _emu_to_pt(tf.margin_top, 3.6)
            mb = _emu_to_pt(tf.margin_bottom, 3.6)
            avail_w = _emu_to_pt(shape.width) - ml - mr
            avail_h = _emu_to_pt(shape.height) - mt - mb
            if avail_w < 24.0 or avail_h < 14.0:
                continue

            # Never allow WPS/PowerPoint to stretch a card's bounding box beyond its designed height.
            if tf.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT:
                tf.auto_size = MSO_AUTO_SIZE.NONE
                modified = True

            # Fix horizontal overflow when word_wrap is explicitly disabled (e.g., wide code badges).
            if tf.word_wrap is False:
                _, max_unwrapped_w = _estimate_pptx_tf_metrics(tf, avail_w, font_scale=1.0)
                if max_unwrapped_w > avail_w * 0.98:
                    non_empty_paras = [p for p in tf.paragraphs if (p.text or "").strip()]
                    if len(non_empty_paras) == 1 and (avail_w / max(1.0, avail_h)) >= 2.0:
                        horiz_scale = max(0.55, (avail_w / max_unwrapped_w) * 0.93)
                        _scale_pptx_text_frame(tf, horiz_scale, Pt)
                        _, after_w = _estimate_pptx_tf_metrics(tf, avail_w, font_scale=1.0)
                        if after_w > avail_w:
                            tf.word_wrap = True
                    else:
                        tf.word_wrap = True
                    tf.auto_size = MSO_AUTO_SIZE.NONE
                    modified = True

            # Fix vertical wrapping overflow so text never spills out onto cards or charts below.
            est_h, _ = _estimate_pptx_tf_metrics(tf, avail_w, font_scale=1.0)
            if est_h > avail_h * 0.98 and len(full_text) >= 6 and avail_h >= 22.0:
                best_scale = 0.55
                for candidate in (0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55):
                    cand_h, _ = _estimate_pptx_tf_metrics(tf, avail_w, font_scale=candidate)
                    if cand_h <= avail_h * 0.96:
                        best_scale = candidate
                        break
                _scale_pptx_text_frame(tf, best_scale, Pt)
                if mt > 2.0:
                    tf.margin_top = Pt(round(mt * 0.6, 1))
                if mb > 2.0:
                    tf.margin_bottom = Pt(round(mb * 0.6, 1))
                tf.auto_size = MSO_AUTO_SIZE.NONE
                modified = True

    if not modified:
        return input_path
    try:
        prs.save(str(output_path))
        return output_path
    except Exception:
        return input_path


def _sanitize_docx_xml_fields(doc_xml_bytes: bytes, existing_bookmarks: set[str] | None = None) -> tuple[bytes, set[str], bool]:
    """Preserve cached TOC/PAGEREF numbers when referenced bookmarks are missing."""
    from lxml import etree as LET

    root = LET.fromstring(doc_xml_bytes)
    w_bm_start = f"{{{_W_NS}}}bookmarkStart"
    w_name = f"{{{_W_NS}}}name"
    w_fld_simple = f"{{{_W_NS}}}fldSimple"
    w_instr_attr = f"{{{_W_NS}}}instr"
    w_fld_lock = f"{{{_W_NS}}}fldLock"
    w_r = f"{{{_W_NS}}}r"
    w_fld_char = f"{{{_W_NS}}}fldChar"
    w_fld_char_type = f"{{{_W_NS}}}fldCharType"
    w_instr_text = f"{{{_W_NS}}}instrText"

    if existing_bookmarks is None:
        existing_bookmarks = {
            bm.get(w_name) for bm in root.iter(w_bm_start) if bm.get(w_name)
        }

    changed = False
    ref_re = re.compile(r"\b(?:PAGEREF|REF)\s+([^\s\\\"]+)", re.IGNORECASE)

    # 1) Unwrap or lock <w:fldSimple> pointing to missing bookmarks or TOCs
    for fld in list(root.iter(w_fld_simple)):
        instr = fld.get(w_instr_attr) or ""
        m = ref_re.search(instr)
        if m and m.group(1) not in existing_bookmarks:
            parent = fld.getparent()
            if parent is not None and len(fld) > 0:
                idx = list(parent).index(fld)
                for offset, child in enumerate(list(fld)):
                    fld.remove(child)
                    parent.insert(idx + offset, child)
                parent.remove(fld)
                changed = True
                continue
        if re.search(r"\b(?:TOC|PAGEREF|REF)\b", instr, re.IGNORECASE):
            if fld.get(w_fld_lock) != "1":
                fld.set(w_fld_lock, "1")
                changed = True

    # 2) Walk complex fields per container element so leaf broken PAGEREF/REF fields keep cached text
    for container in list(root.iter()):
        stack: list[dict] = []
        to_remove: list = []
        for idx, child in enumerate(list(container)):
            if child.tag != w_r:
                continue
            fc = child.find(w_fld_char)
            if fc is not None:
                ftype = fc.get(w_fld_char_type)
                if ftype == "begin":
                    stack.append({
                        "begin_fc": fc,
                        "instr_runs": [child],
                        "instr_text": "",
                        "has_sep": False,
                        "value_runs": [],
                    })
                    continue
                if ftype == "separate" and stack:
                    top = stack[-1]
                    if not top["has_sep"]:
                        top["has_sep"] = True
                        top["instr_runs"].append(child)
                    continue
                if ftype == "end" and stack:
                    top = stack.pop()
                    instr = top["instr_text"].strip()
                    m = ref_re.search(instr)
                    if m and m.group(1) not in existing_bookmarks and top["has_sep"] and top["value_runs"]:
                        to_remove.extend(top["instr_runs"])
                        to_remove.append(child)
                        changed = True
                    elif re.search(r"\b(?:TOC|PAGEREF|REF)\b", instr, re.IGNORECASE):
                        if top["begin_fc"].get(w_fld_lock) != "1":
                            top["begin_fc"].set(w_fld_lock, "1")
                            changed = True
                    continue

            if stack:
                top = stack[-1]
                if not top["has_sep"]:
                    top["instr_runs"].append(child)
                    for it in child.iter(w_instr_text):
                        if it.text:
                            top["instr_text"] += it.text
                else:
                    has_text = any(True for _ in child.iter(f"{{{_W_NS}}}t"))
                    if has_text:
                        top["value_runs"].append(child)

        for rem in to_remove:
            if rem.getparent() is container:
                container.remove(rem)

    # Lock any remaining orphan complex fields referencing TOC/PAGEREF
    for fc in root.iter(w_fld_char):
        if fc.get(w_fld_char_type) == "begin" and fc.get(w_fld_lock) != "1":
            # Keep untouched unless needed; main loop handles well-formed container fields.
            pass

    if not changed:
        return doc_xml_bytes, existing_bookmarks, False
    return LET.tostring(root, xml_declaration=True, encoding="UTF-8"), existing_bookmarks, True


def _prepare_docx_for_export(input_path: Path, output_path: Path) -> Path:
    """Lock/unwrap broken TOC and PAGEREF fields so WPS/Word keeps cached page numbers."""
    if input_path.suffix.lower() != ".docx":
        return input_path
    try:
        from lxml import etree as LET
        import zipfile
    except Exception:
        return input_path

    try:
        with zipfile.ZipFile(input_path, "r") as zin:
            names = zin.namelist()
            if "word/document.xml" not in names:
                return input_path
            doc_bytes = zin.read("word/document.xml")
            new_doc_bytes, bookmarks, doc_changed = _sanitize_docx_xml_fields(doc_bytes)
            replacements: dict[str, bytes] = {}
            if doc_changed:
                replacements["word/document.xml"] = new_doc_bytes

            if "word/settings.xml" in names:
                s_bytes = zin.read("word/settings.xml")
                s_root = LET.fromstring(s_bytes)
                s_changed = False
                for uf in list(s_root.iter(f"{{{_W_NS}}}updateFields")):
                    parent = uf.getparent()
                    if parent is not None:
                        parent.remove(uf)
                        s_changed = True
                if s_changed:
                    replacements["word/settings.xml"] = LET.tostring(
                        s_root, xml_declaration=True, encoding="UTF-8"
                    )

            for name in names:
                if name.startswith(("word/header", "word/footer")) and name.endswith(".xml"):
                    raw_part = zin.read(name)
                    new_part, _, part_changed = _sanitize_docx_xml_fields(raw_part, bookmarks)
                    if part_changed:
                        replacements[name] = new_part

            if not replacements:
                return input_path

            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = replacements.get(item.filename)
                    if data is None:
                        data = zin.read(item.filename)
                    zout.writestr(item, data)
        return output_path
    except Exception:
        return input_path


def _prepare_office_input(input_path: Path, tmp_dir: Path) -> Path:
    """Prepare sanitized temporary copies of .pptx/.docx files before Office/LibreOffice export."""
    ext = input_path.suffix.lower()
    if ext == ".pptx":
        return _prepare_pptx_for_export(input_path, tmp_dir / f"{input_path.stem}_fixed.pptx")
    if ext == ".docx":
        return _prepare_docx_for_export(input_path, tmp_dir / f"{input_path.stem}_fixed.docx")
    return input_path


def _convert_office_via_com(input_path: Path, output_pdf_path: Path, kind: str) -> int | None:
    """Convert .doc/.docx/.ppt/.pptx/.xls/.xlsx to 1:1 PDF via Windows COM automation (WPS / MS Office)."""
    if sys.platform != "win32":
        return None
    try:
        import pythoncom
    except Exception:
        return None

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path = str(output_pdf_path.resolve())
    if kind == "docx":
        prog_ids = ("KWPS.Application", "Word.Application")
    elif kind == "pptx":
        prog_ids = ("KWPP.Application", "PowerPoint.Application")
    else:
        prog_ids = ("KET.Application", "Excel.Application")

    with _OFFICE_COM_LOCK:
        with tempfile.TemporaryDirectory() as tmp_dir:
            prepared_input = _prepare_office_input(input_path, Path(tmp_dir))
            src_path = str(prepared_input.resolve())
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
                        app = _dispatch_com_app(prog_id)
                        try:
                            app.DisplayAlerts = False if kind == "xlsx" else 0
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
                        elif kind == "pptx":
                            doc_obj = app.Presentations.Open(
                                src_path, ReadOnly=1, Untitled=0, WithWindow=0
                            )
                            doc_obj.SaveAs(dst_path, 32)
                        else:
                            try:
                                app.Visible = False
                            except Exception:
                                pass
                            doc_obj = app.Workbooks.Open(src_path, ReadOnly=True)
                            doc_obj.ExportAsFixedFormat(0, dst_path)
                    except Exception:
                        continue
                    finally:
                        if doc_obj is not None:
                            try:
                                if kind == "docx":
                                    doc_obj.Close(0)
                                elif kind == "xlsx":
                                    doc_obj.Close(False)
                                else:
                                    doc_obj.Close()
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
            prepared_input = _prepare_office_input(input_path, Path(tmp_dir))
            proc = subprocess.run(
                [
                    bin_path,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_dir,
                    str(prepared_input.resolve()),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                return None
            candidate = Path(tmp_dir) / f"{prepared_input.stem}.pdf"
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
    if input_path.suffix.lower() == ".doc":
        raise ValueError("Eski .doc formatini PDF ga aylantirish uchun Office yoki LibreOffice kerak.")

    styles = _build_styles()
    doc = DocxDocument(str(input_path))
    story = []
    avail_w = A4[0] - 36 * mm
    max_img_w = avail_w
    max_img_h = A4[1] - 50 * mm
    para_map = {p._element: p for p in doc.paragraphs}
    tbl_map = {t._element: t for t in doc.tables}
    seen_rids: set[str] = set()

    def _collect_new_images(element, max_w: float, max_h: float) -> list:
        imgs = []
        for rid in _extract_docx_element_rids(element):
            if rid in seen_rids:
                continue
            rel = doc.part.rels.get(rid)
            if rel is None or getattr(rel, "is_external", False):
                continue
            seen_rids.add(rid)
            rl_img = _make_rl_image(rel.target_part.blob, max_w, max_h)
            if rl_img is not None:
                imgs.append(rl_img)
        return imgs

    def _append_rids(element) -> None:
        for rl_img in _collect_new_images(element, max_img_w, max_img_h):
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
            col_count = max((len(r.cells) for r in tbl.rows), default=1)
            cell_max_w = max(48.0, (avail_w / max(1, col_count)) - 12.0)
            col_widths = [avail_w / max(1, col_count)] * col_count
            rows_data = []
            for row_idx, row in enumerate(tbl.rows):
                row_cells = []
                cell_style = styles["table_header"] if row_idx == 0 else styles["table_cell"]
                for cell in row.cells[:col_count]:
                    cell_items = []
                    txt = cell.text.strip()
                    if txt:
                        cell_items.append(Paragraph(escape(txt).replace("\n", "<br/>"), cell_style))
                    for cell_img in _collect_new_images(cell._tc, cell_max_w, max_img_h * 0.55):
                        cell_items.append(cell_img)
                    if not cell_items:
                        cell_items.append(Paragraph(" ", cell_style))
                    row_cells.append(cell_items)
                while len(row_cells) < col_count:
                    row_cells.append([Paragraph(" ", cell_style)])
                rows_data.append(row_cells)
            if rows_data:
                table = Table(rows_data, colWidths=col_widths, repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("PADDING", (0, 0), (-1, -1), 5),
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


def _pptx_rgb_to_rl(color_format):
    """Safely extract a solid RGB fill/line color as a ReportLab Color, or return None."""
    try:
        from pptx.enum.dml import MSO_FILL

        if getattr(color_format, "type", None) == MSO_FILL.SOLID and color_format.fore_color and color_format.fore_color.rgb:
            rgb = color_format.fore_color.rgb
            return colors.Color(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    except Exception:
        pass
    return None


def _draw_pptx_shape_on_canvas(pdf_canvas, shape, slide_h_pt: float, reg_font: str, bold_font: str, off_x: float = 0.0, off_y: float = 0.0) -> None:
    """Render a PPTX shape at its true slide coordinates on a 1:1 ReportLab canvas."""
    if hasattr(shape, "shapes"):
        for sub in shape.shapes:
            _draw_pptx_shape_on_canvas(pdf_canvas, sub, slide_h_pt, reg_font, bold_font, off_x, off_y)
        return

    left_pt = off_x + _emu_to_pt(getattr(shape, "left", 0), 0.0)
    top_pt = off_y + _emu_to_pt(getattr(shape, "top", 0), 0.0)
    w_pt = max(1.0, _emu_to_pt(getattr(shape, "width", 0), 0.0))
    h_pt = max(1.0, _emu_to_pt(getattr(shape, "height", 0), 0.0))
    canvas_y = slide_h_pt - (top_pt + h_pt)

    fill_col = _pptx_rgb_to_rl(getattr(shape, "fill", None))
    line_col = None
    try:
        line_obj = getattr(shape, "line", None)
        if line_obj and line_obj.fill and line_obj.fill.type is not None and line_obj.color and line_obj.color.rgb:
            rgb = line_obj.color.rgb
            line_col = colors.Color(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    except Exception:
        line_col = None

    if fill_col is not None or line_col is not None:
        pdf_canvas.saveState()
        if fill_col is not None:
            pdf_canvas.setFillColor(fill_col)
        if line_col is not None:
            pdf_canvas.setStrokeColor(line_col)
            pdf_canvas.setLineWidth(1.0)
        pdf_canvas.rect(
            left_pt,
            canvas_y,
            w_pt,
            h_pt,
            stroke=1 if line_col is not None else 0,
            fill=1 if fill_col is not None else 0,
        )
        pdf_canvas.restoreState()

    if hasattr(shape, "image"):
        try:
            with PILImage.open(BytesIO(shape.image.blob)) as im:
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
                out = BytesIO()
                im.save(out, format="PNG")
                out.seek(0)
            pdf_canvas.drawImage(ImageReader(out), left_pt, canvas_y, width=w_pt, height=h_pt, mask="auto")
            return
        except Exception:
            pass

    if getattr(shape, "has_table", False):
        tbl = shape.table
        col_widths = [_emu_to_pt(col.width, w_pt / max(1, len(tbl.columns))) for col in tbl.columns]
        total_cw = sum(col_widths) or w_pt
        col_widths = [cw * (w_pt / total_cw) for cw in col_widths]
        tbl_cell_style = ParagraphStyle(
            "PptxFallbackCell",
            fontName=reg_font,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#0f172a"),
        )
        rows_data = [
            [Paragraph(escape(c.text.strip() or " ").replace("\n", "<br/>"), tbl_cell_style) for c in row.cells]
            for row in tbl.rows
        ]
        if rows_data:
            rl_tbl = Table(rows_data, colWidths=col_widths)
            rl_tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            _, drawn_h = rl_tbl.wrapOn(pdf_canvas, w_pt, h_pt)
            rl_tbl.drawOn(pdf_canvas, left_pt, canvas_y + max(0.0, h_pt - drawn_h))
        return

    if getattr(shape, "has_text_frame", False) and (shape.text_frame.text or "").strip():
        tf = shape.text_frame
        flowables = []
        for idx, para in enumerate(tf.paragraphs):
            txt = (para.text or "").strip()
            if not txt:
                flowables.append(Spacer(1, 4))
                continue
            runs = list(para.runs)
            pt_val, is_bold, _ = _resolve_pptx_font_pt(para, runs[0] if runs else None, tf._txBody)
            if not is_bold:
                is_bold = any(bool(r.font.bold) for r in runs)
            text_col = colors.HexColor("#0f172a")
            for src_font in ([runs[0].font] if runs else []) + [para.font]:
                try:
                    if src_font.color and src_font.color.rgb:
                        rgb = src_font.color.rgb
                        cand = colors.Color(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
                        if fill_col is None and (rgb[0] + rgb[1] + rgb[2]) > 680:
                            cand = colors.HexColor("#0f172a")
                        text_col = cand
                        break
                except Exception:
                    pass
            p_style = ParagraphStyle(
                f"PptxP{idx}",
                fontName=bold_font if is_bold else reg_font,
                fontSize=max(7.5, min(42.0, pt_val)),
                leading=max(9.5, min(50.0, pt_val * 1.24)),
                textColor=text_col,
                spaceAfter=max(0.0, _emu_to_pt(para.space_after, 2.0)),
            )
            flowables.append(Paragraph(escape(txt).replace("\n", "<br/>"), p_style))

        ml = min(w_pt * 0.25, _emu_to_pt(tf.margin_left, 4.0))
        mr = min(w_pt * 0.25, _emu_to_pt(tf.margin_right, 4.0))
        mt = min(h_pt * 0.25, _emu_to_pt(tf.margin_top, 2.0))
        mb = min(h_pt * 0.25, _emu_to_pt(tf.margin_bottom, 2.0))
        inner_w = max(8.0, w_pt - ml - mr)
        inner_h = max(8.0, h_pt - mt - mb)
        kif = KeepInFrame(inner_w, inner_h, flowables, mode="shrink")
        frame = Frame(
            left_pt + ml,
            canvas_y + mb,
            inner_w,
            inner_h,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            showBoundary=0,
        )
        frame.addFromList([kif], pdf_canvas)


def _convert_pptx(input_path: Path, output_pdf_path: Path) -> int:
    com_pages = _convert_office_via_com(input_path, output_pdf_path, "pptx")
    if com_pages:
        return com_pages
    lo_pages = _convert_office_via_libreoffice(input_path, output_pdf_path)
    if lo_pages:
        return lo_pages
    if input_path.suffix.lower() == ".ppt":
        raise ValueError("Eski .ppt formatini PDF ga aylantirish uchun Office yoki LibreOffice kerak.")

    reg_font, bold_font, _ = _ensure_fonts()
    prs = Presentation(str(input_path))
    slide_w_pt = max(200.0, _emu_to_pt(prs.slide_width, landscape(A4)[0]))
    slide_h_pt = max(200.0, _emu_to_pt(prs.slide_height, landscape(A4)[1]))

    pdf_canvas = rl_canvas.Canvas(str(output_pdf_path), pagesize=(slide_w_pt, slide_h_pt))
    slides = list(prs.slides)
    if not slides:
        pdf_canvas.setFont(reg_font, 12)
        pdf_canvas.drawString(36, slide_h_pt - 50, "Bo'sh taqdimot fayli")
        pdf_canvas.showPage()
        pdf_canvas.save()
        return 1

    for slide in slides:
        bg_col = _pptx_rgb_to_rl(getattr(getattr(slide, "background", None), "fill", None))
        pdf_canvas.saveState()
        pdf_canvas.setFillColor(bg_col if bg_col is not None else colors.white)
        pdf_canvas.rect(0, 0, slide_w_pt, slide_h_pt, fill=1, stroke=0)
        pdf_canvas.restoreState()

        for shape in slide.shapes:
            _draw_pptx_shape_on_canvas(pdf_canvas, shape, slide_h_pt, reg_font, bold_font)
        pdf_canvas.showPage()

    pdf_canvas.save()
    return len(PdfReader(str(output_pdf_path)).pages)


def _convert_excel(input_path: Path, output_pdf_path: Path) -> int:
    com_pages = _convert_office_via_com(input_path, output_pdf_path, "xlsx")
    if com_pages:
        return com_pages
    lo_pages = _convert_office_via_libreoffice(input_path, output_pdf_path)
    if lo_pages:
        return lo_pages

    try:
        import openpyxl
    except ImportError as exc:
        raise ValueError(
            "Excel (.xlsx/.xls) faylini PDF ga aylantirish uchun Office yoki LibreOffice kerak."
        ) from exc

    if input_path.suffix.lower() == ".xls":
        raise ValueError("Eski .xls formatini PDF ga aylantirish uchun Office yoki LibreOffice kerak.")

    styles = _build_styles()
    wb = openpyxl.load_workbook(str(input_path), data_only=True, read_only=True)
    story = []
    max_cols = 0
    try:
        for sheet_idx, ws in enumerate(wb.worksheets):
            rows_data = []
            for row in ws.iter_rows(values_only=True):
                if not any(cell is not None and str(cell).strip() != "" for cell in row):
                    continue
                row_strs = ["" if cell is None else str(cell) for cell in row]
                while row_strs and row_strs[-1] == "":
                    row_strs.pop()
                if row_strs:
                    max_cols = max(max_cols, len(row_strs))
                    rows_data.append(
                        [Paragraph(escape(c or " "), styles["body"]) for c in row_strs]
                    )
            if not rows_data:
                continue
            if sheet_idx > 0 and story:
                story.append(PageBreak())
            story.append(Paragraph(f"Varoq: {escape(ws.title)}", styles["h2"]))
            col_count = max(len(r) for r in rows_data)
            for r in rows_data:
                while len(r) < col_count:
                    r.append(Paragraph(" ", styles["body"]))
            table = Table(rows_data, repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(Spacer(1, 4))
            story.append(table)
    finally:
        wb.close()

    if not story:
        story.append(Paragraph("Bo'sh Excel jadvali", styles["body"]))

    pagesize = landscape(A4) if max_cols > 5 else A4
    pdf_doc = SimpleDocTemplate(
        str(output_pdf_path),
        pagesize=pagesize,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    pdf_doc.build(story)
    return len(PdfReader(str(output_pdf_path)).pages)


_MD_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_MD_ORDERED_RE = re.compile(r"^\s*(\d+[.)])\s+(.*)$")
_MD_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_MD_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")


def _split_md_table_row(line: str) -> list[str]:
    """Split a Markdown pipe-table line into trimmed cell strings."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith(r"\|"):
        s = s[:-1]
    parts = re.split(r"(?<!\\)\|", s)
    return [p.replace(r"\|", "|").strip() for p in parts]


def _md_inline_to_rml(raw: str, mono_font: str) -> str:
    """Convert basic inline Markdown (**bold**, *italic*, `code`, [link](url)) to safe ReportLab XML."""
    code_tokens: list[str] = []

    def _stash_code(match: re.Match) -> str:
        idx = len(code_tokens)
        code_tokens.append(match.group(1))
        return f"\x00CODE{idx}\x00"

    text = re.sub(r"`([^`\n]+)`", _stash_code, raw)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1", text)
    escaped = escape(text)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)

    for idx, code_txt in enumerate(code_tokens):
        rml_code = f'<font name="{mono_font}" backColor="#f1f5f9">{escape(code_txt)}</font>'
        escaped = escaped.replace(f"\x00CODE{idx}\x00", rml_code)
    return escaped


def _safe_md_paragraph(raw: str, style: ParagraphStyle, mono_font: str) -> Paragraph:
    """Build a ReportLab Paragraph with inline Markdown formatting, falling back safely to plain text."""
    try:
        return Paragraph(_md_inline_to_rml(raw, mono_font), style)
    except Exception:
        return Paragraph(escape(raw), style)


def _wrap_code_line(line: str, max_chars: int = 94) -> list[str]:
    """Soft-wrap oversized lines inside fenced code blocks so text never clips past page edges."""
    if len(line) <= max_chars:
        return [line]
    return [line[i : i + max_chars] for i in range(0, len(line), max_chars)]


def _build_md_table(raw_rows: list[list[str]], avail_w: float, styles: dict[str, ParagraphStyle], mono_font: str) -> Table:
    """Construct a proportional, word-wrapped ReportLab Table from Markdown table rows."""
    col_count = max(len(r) for r in raw_rows)
    norm_rows = [r + [""] * (col_count - len(r)) for r in raw_rows]

    # Estimate column weights from content lengths with bounded bounds so narrow/wide columns stay balanced
    max_lens = [3] * col_count
    for r in norm_rows[:30]:
        for c_idx, cell in enumerate(r):
            max_lens[c_idx] = max(max_lens[c_idx], min(42, len(cell)))
    min_col_w = min(44.0, avail_w / max(1, col_count))
    total_len = sum(max_lens) or col_count
    raw_widths = [max(min_col_w, avail_w * (ln / total_len)) for ln in max_lens]
    w_scale = avail_w / max(1.0, sum(raw_widths))
    col_widths = [w * w_scale for w in raw_widths]

    flow_rows = []
    for r_idx, r in enumerate(norm_rows):
        c_style = styles["table_header"] if r_idx == 0 else styles["table_cell"]
        flow_rows.append([_safe_md_paragraph(c or " ", c_style, mono_font) for c in r])

    table = Table(flow_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _convert_markdown(raw: str, output_pdf_path: Path) -> int:
    """Render Markdown documents (.md) with styled headings, wrapped pipe tables, and code blocks."""
    styles = _build_styles()
    _, _, mono_font = _ensure_fonts()
    lines = raw.splitlines() or ["(Bo'sh hujjat)"]

    # Detect wide Markdown tables upfront so pagesize matches column count
    has_wide_table = False
    for idx in range(len(lines) - 1):
        if "|" in lines[idx] and _MD_TABLE_SEP_RE.match(lines[idx + 1]):
            if len(_split_md_table_row(lines[idx])) >= 6:
                has_wide_table = True
                break

    pagesize = landscape(A4) if has_wide_table else A4
    margin_mm = 16
    avail_w = pagesize[0] - 2 * margin_mm * mm
    story = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code block (``` or ~~~)
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith(fence):
                code_lines.extend(_wrap_code_line(lines[i], 96 if has_wide_table else 82))
                i += 1
            if i < n and lines[i].strip().startswith(fence):
                i += 1
            if not code_lines:
                code_lines = [" "]
            for chunk_start in range(0, len(code_lines), 38):
                chunk = "\n".join(code_lines[chunk_start : chunk_start + 38])
                code_tbl = Table([[Preformatted(chunk, styles["code_pre"])]], colWidths=[avail_w])
                code_tbl.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("PADDING", (0, 0), (-1, -1), 7),
                        ]
                    )
                )
                story.append(Spacer(1, 3))
                story.append(code_tbl)
                story.append(Spacer(1, 5))
            continue

        # Markdown pipe table
        if i + 1 < n and "|" in line and _MD_TABLE_SEP_RE.match(lines[i + 1]):
            raw_rows = [_split_md_table_row(line)]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                if not _MD_TABLE_SEP_RE.match(lines[i]):
                    raw_rows.append(_split_md_table_row(lines[i]))
                i += 1
            story.append(Spacer(1, 4))
            story.append(_build_md_table(raw_rows, avail_w, styles, mono_font))
            story.append(Spacer(1, 7))
            continue

        # Horizontal rule
        if re.match(r"^\s*([-*_])\1{2,}\s*$", stripped):
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#cbd5e1")))
            story.append(Spacer(1, 5))
            i += 1
            continue

        # Heading (#, ##, ###...)
        hm = _MD_HEADING_RE.match(line)
        if hm:
            lvl = len(hm.group(1))
            htext = hm.group(2).strip()
            h_style = styles["title"] if lvl == 1 else (styles["h1"] if lvl == 2 else (styles["h2"] if lvl == 3 else styles["h3"]))
            story.append(_safe_md_paragraph(htext, h_style, mono_font))
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            q_parts = []
            while i < n and lines[i].strip().startswith(">"):
                q_parts.append(lines[i].strip().lstrip(">").strip())
                i += 1
            story.append(_safe_md_paragraph(" ".join(q_parts), styles["quote"], mono_font))
            continue

        # Bullet / Ordered list item
        bm = _MD_BULLET_RE.match(line)
        om = _MD_ORDERED_RE.match(line)
        if bm:
            story.append(_safe_md_paragraph(f"• {bm.group(1)}", styles["bullet"], mono_font))
            i += 1
            continue
        if om:
            story.append(_safe_md_paragraph(f"**{om.group(1)}** {om.group(2)}", styles["bullet"], mono_font))
            i += 1
            continue

        # Regular paragraph: merge wrapped consecutive prose lines
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i]
            ns = nxt.strip()
            if (
                not ns
                or ns.startswith(("```", "~~~", ">"))
                or _MD_HEADING_RE.match(nxt)
                or _MD_BULLET_RE.match(nxt)
                or _MD_ORDERED_RE.match(nxt)
                or re.match(r"^\s*([-*_])\1{2,}\s*$", ns)
                or (i + 1 < n and "|" in nxt and _MD_TABLE_SEP_RE.match(lines[i + 1]))
            ):
                break
            para_lines.append(ns)
            i += 1
        story.append(_safe_md_paragraph(" ".join(para_lines), styles["body"], mono_font))

    if not story:
        story.append(Paragraph("Bo'sh Markdown hujjati", styles["body"]))

    pdf_doc = SimpleDocTemplate(
        str(output_pdf_path),
        pagesize=pagesize,
        leftMargin=margin_mm * mm,
        rightMargin=margin_mm * mm,
        topMargin=margin_mm * mm,
        bottomMargin=margin_mm * mm,
    )
    pdf_doc.build(story)
    return len(PdfReader(str(output_pdf_path)).pages)


def _convert_csv(raw: str, output_pdf_path: Path) -> int:
    """Render .csv files cleanly into wrapped tables instead of misaligned plain lines."""
    styles = _build_styles()
    rows = [r for r in csv.reader(raw.splitlines()) if any(c.strip() for c in r)]
    if not rows:
        return _convert_plain_text("(Bo'sh CSV fayli)", output_pdf_path)

    col_count = max(len(r) for r in rows)
    pagesize = landscape(A4) if col_count > 5 else A4
    avail_w = pagesize[0] - 28 * mm
    col_widths = [avail_w / max(1, col_count)] * col_count
    flow_rows = []
    for r_idx, row in enumerate(rows):
        style = styles["table_header"] if r_idx == 0 else styles["table_cell"]
        padded = row + [""] * (col_count - len(row))
        flow_rows.append([Paragraph(escape(c or " "), style) for c in padded])

    table = Table(flow_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    pdf_doc = SimpleDocTemplate(
        str(output_pdf_path),
        pagesize=pagesize,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    pdf_doc.build([table])
    return len(PdfReader(str(output_pdf_path)).pages)


def _convert_plain_text(raw: str, output_pdf_path: Path) -> int:
    styles = _build_styles()
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


def _convert_text(input_path: Path, output_pdf_path: Path) -> int:
    raw = input_path.read_text(encoding="utf-8", errors="replace")
    ext = input_path.suffix.lower()
    if ext == ".md":
        return _convert_markdown(raw, output_pdf_path)
    if ext == ".csv":
        return _convert_csv(raw, output_pdf_path)
    return _convert_plain_text(raw, output_pdf_path)


def normalize_to_pdf(input_path: Path, original_filename: str, output_pdf_path: Path) -> int:
    """Convert any supported uploaded document to a standardized PDF and return page count."""
    ext = Path(original_filename).suffix.lower()
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".pdf":
        return _convert_pdf(input_path, output_pdf_path)
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        return _convert_image(input_path, output_pdf_path)
    if ext in {".docx", ".doc"}:
        return _convert_docx(input_path, output_pdf_path)
    if ext in {".pptx", ".ppt"}:
        return _convert_pptx(input_path, output_pdf_path)
    if ext in {".xlsx", ".xls"}:
        return _convert_excel(input_path, output_pdf_path)
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
