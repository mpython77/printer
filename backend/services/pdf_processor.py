"""Page range parsing, formatting, PDF slicing/imposition, and print metrics calculation."""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import ContentStream, FloatObject, NameObject

from backend.config import (
    PRICE_BW_DUPLEX,
    PRICE_BW_SIMPLEX,
    PRICE_COLOR_DUPLEX,
    PRICE_COLOR_SIMPLEX,
    SECONDS_BW_PER_SHEET,
    SECONDS_COLOR_PER_SHEET,
    WARMUP_SECONDS,
)

PAPER_DIMENSIONS_PT: dict[str, tuple[float, float]] = {
    "A4": (595.28, 841.89),
    "A5": (419.53, 595.28),
    "Letter": (612.0, 792.0),
}


def parse_page_range(range_str: str, max_pages: int) -> list[int]:
    """Parse range text such as '1-3, 5, 7-8' or 'all' into sorted unique 1-based page numbers."""
    if max_pages < 1:
        return []

    cleaned = (range_str or "").strip().lower()
    if not cleaned:
        return []
    if cleaned in {"all", "barchasi", "*"}:
        return list(range(1, max_pages + 1))

    selected: set[int] = set()
    tokens = [part.strip() for part in cleaned.replace(";", ",").split(",") if part.strip()]

    for token in tokens:
        if "-" in token:
            pieces = [p.strip() for p in token.split("-", 1)]
            if len(pieces) != 2 or not pieces[0].isdigit() or not pieces[1].isdigit():
                raise ValueError(f"Noto'g'ri bet oralig'i: '{token}'")
            start = int(pieces[0])
            end = int(pieces[1])
            if start > end:
                start, end = end, start
            for page in range(max(1, start), min(max_pages, end) + 1):
                selected.add(page)
        else:
            if not token.isdigit():
                raise ValueError(f"Noto'g'ri bet raqami: '{token}'")
            page = int(token)
            if 1 <= page <= max_pages:
                selected.add(page)

    return sorted(selected)


def format_page_range(pages: list[int]) -> str:
    """Convert [1, 2, 3, 5, 7, 8] into '1-3, 5, 7-8'."""
    unique_sorted = sorted({p for p in pages if p >= 1})
    if not unique_sorted:
        return ""

    ranges: list[str] = []
    start = prev = unique_sorted[0]
    for page in unique_sorted[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = page
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def _is_page_landscape(page: PageObject) -> bool:
    """Return True if a PDF page's visual dimensions (accounting for /Rotate) are wider than tall."""
    try:
        rot = int(page.get("/Rotate", 0) or 0) % 360
    except Exception:
        rot = 0
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    if rot in {90, 270}:
        w, h = h, w
    return w > h


def _place_page_in_cell(
    dest_page: PageObject,
    src_page: PageObject,
    cell_x: float,
    cell_y: float,
    cell_w: float,
    cell_h: float,
    padding: float = 12.0,
) -> None:
    """Scale and center a source PDF page inside a target rectangular cell."""
    src_page.transfer_rotation_to_content()
    sw = max(1.0, float(src_page.mediabox.width))
    sh = max(1.0, float(src_page.mediabox.height))
    left = float(src_page.mediabox.left)
    bottom = float(src_page.mediabox.bottom)

    avail_w = max(10.0, cell_w - 2 * padding)
    avail_h = max(10.0, cell_h - 2 * padding)
    scale = min(avail_w / sw, avail_h / sh)

    tx = cell_x + (cell_w - sw * scale) / 2.0 - left * scale
    ty = cell_y + (cell_h - sh * scale) / 2.0 - bottom * scale

    dest_page.merge_transformed_page(
        src_page,
        Transformation().scale(scale, scale).translate(tx, ty),
    )


def _rewrite_content_stream_to_gray(content_obj: Any, pdf_owner: PdfWriter) -> ContentStream:
    """Convert RGB (`rg`, `RG`) and CMYK (`k`, `K`) PDF color operators into `DeviceGray` (`g`, `G`)."""
    cs = ContentStream(content_obj, pdf_owner)
    new_ops = []
    for operands, operator in cs.operations:
        if operator in {b"rg", b"RG"} and len(operands) == 3:
            try:
                r = float(operands[0])
                g = float(operands[1])
                b = float(operands[2])
                lum = round(max(0.0, min(1.0, 0.299 * r + 0.587 * g + 0.114 * b)), 4)
                new_op = b"g" if operator == b"rg" else b"G"
                new_ops.append(([FloatObject(lum)], new_op))
                continue
            except Exception:
                pass
        elif operator in {b"k", b"K"} and len(operands) == 4:
            try:
                c = float(operands[0])
                m = float(operands[1])
                y = float(operands[2])
                k = float(operands[3])
                r = (1.0 - c) * (1.0 - k)
                g = (1.0 - m) * (1.0 - k)
                b = (1.0 - y) * (1.0 - k)
                lum = round(max(0.0, min(1.0, 0.299 * r + 0.587 * g + 0.114 * b)), 4)
                new_op = b"g" if operator == b"k" else b"G"
                new_ops.append(([FloatObject(lum)], new_op))
                continue
            except Exception:
                pass
        new_ops.append((operands, operator))
    cs.operations = new_ops
    return cs


def _convert_page_streams_to_grayscale(
    page: PageObject,
    pdf_owner: PdfWriter,
    _visited: set[int] | None = None,
) -> None:
    """Safely convert vector color operators, embedded Form XObjects, and raster images to grayscale."""
    seen = _visited if _visited is not None else set()
    try:
        contents = page.get_contents()
        if contents is not None:
            cs = _rewrite_content_stream_to_gray(contents, pdf_owner)
            page.replace_contents(cs)
    except Exception:
        pass

    try:
        for img_file in list(getattr(page, "images", [])):
            try:
                img_obj = (
                    img_file.indirect_reference.get_object()
                    if getattr(img_file, "indirect_reference", None) is not None
                    else None
                )
                has_smask = img_obj is not None and "/SMask" in img_obj
                with Image.open(io.BytesIO(img_file.data)) as pil_img:
                    has_alpha = (
                        "A" in pil_img.getbands()
                        or pil_img.mode in {"RGBA", "LA", "PA"}
                        or (pil_img.mode == "P" and "transparency" in pil_img.info)
                    )
                    if has_alpha:
                        rgba = pil_img.convert("RGBA")
                        alpha = rgba.getchannel("A")
                        gray = rgba.convert("L")
                        merged = Image.merge("RGBA", (gray, gray, gray, alpha))
                        img_file.replace(merged)
                    elif has_smask:
                        # Keep external /SMask intact when pypdf did not merge alpha into img_file.data
                        continue
                    elif pil_img.mode not in {"1", "L"}:
                        gray_img = pil_img.convert("L")
                        img_file.replace(gray_img, quality=92)
            except Exception:
                continue
    except Exception:
        pass

    try:
        resources = page.get("/Resources")
        if resources and "/XObject" in resources:
            xobjs = resources["/XObject"].get_object()
            for key in list(xobjs.keys()):
                obj = xobjs[key].get_object()
                obj_id = id(obj)
                if obj_id in seen:
                    continue
                seen.add(obj_id)
                if obj.get("/Subtype") == NameObject("/Form"):
                    cs = _rewrite_content_stream_to_gray(obj, pdf_owner)
                    obj.set_data(cs.get_data())
                    sub_res = obj.get("/Resources")
                    if sub_res and "/XObject" in sub_res:
                        _convert_page_streams_to_grayscale(obj, pdf_owner, seen)
    except Exception:
        pass


def compute_sheet_color_plan(
    selected_pages: list[int],
    color_mode: str = "bw",
    color_pages: list[int] | None = None,
    duplex: str = "simplex",
    pages_per_sheet: int = 1,
) -> dict[str, Any]:
    """Group selected pages into physical sheets, per-sheet color modes, and ordered print segments."""
    ordered_pages = [int(p) for p in selected_pages if int(p) >= 1]
    if not ordered_pages:
        return {
            "face_modes": [],
            "sheet_modes": [],
            "bw_sheets_per_copy": 0,
            "color_sheets_per_copy": 0,
            "segments": [],
        }

    pps = pages_per_sheet if pages_per_sheet in {1, 2, 4} else 1
    faces_per_sheet = 2 if duplex == "duplex" else 1
    mode_norm = (color_mode or "bw").strip().lower()
    color_set = set(int(p) for p in (color_pages or []) if int(p) >= 1) & set(ordered_pages)

    faces: list[list[int]] = [
        ordered_pages[i : i + pps] for i in range(0, len(ordered_pages), pps)
    ]
    sheets_faces: list[list[list[int]]] = [
        faces[i : i + faces_per_sheet] for i in range(0, len(faces), faces_per_sheet)
    ]

    sheet_modes: list[str] = []
    face_modes: list[str] = []
    sheet_entries: list[dict[str, Any]] = []

    face_cursor = 0
    for sheet_idx, sh_faces in enumerate(sheets_faces):
        sh_pages = [p for f in sh_faces for p in f]
        if mode_norm == "color":
            sh_mode = "color"
        elif mode_norm == "mixed":
            sh_mode = "color" if any(p in color_set for p in sh_pages) else "bw"
        else:
            sh_mode = "bw"

        sheet_modes.append(sh_mode)
        start_face = face_cursor
        for f in sh_faces:
            if mode_norm == "color":
                f_mode = "color"
            elif mode_norm == "mixed":
                f_mode = "color" if any(p in color_set for p in f) else "bw"
            else:
                f_mode = "bw"
            face_modes.append(f_mode)
            face_cursor += 1
        end_face = face_cursor

        sheet_entries.append(
            {
                "sheet_index": sheet_idx,
                "mode": sh_mode,
                "pages": sh_pages,
                "start_face": start_face,
                "end_face": end_face,
            }
        )

    bw_sheets_per_copy = sum(1 for m in sheet_modes if m == "bw")
    color_sheets_per_copy = sum(1 for m in sheet_modes if m == "color")

    segments: list[dict[str, Any]] = []
    for entry in sheet_entries:
        if not segments or segments[-1]["color_mode"] != entry["mode"]:
            seg_idx = len(segments) + 1
            seg_mode = entry["mode"]
            segments.append(
                {
                    "segment_index": seg_idx,
                    "color_mode": seg_mode,
                    "sheet_count": 1,
                    "pages": list(entry["pages"]),
                    "start_face": entry["start_face"],
                    "end_face": entry["end_face"],
                    "pdf_filename": f"segment_{seg_idx:02d}_{seg_mode}.pdf",
                }
            )
        else:
            cur = segments[-1]
            cur["sheet_count"] += 1
            cur["pages"].extend(entry["pages"])
            cur["end_face"] = entry["end_face"]

    for seg in segments:
        seg["page_range_text"] = format_page_range(seg["pages"])

    return {
        "face_modes": face_modes,
        "sheet_modes": sheet_modes,
        "bw_sheets_per_copy": bw_sheets_per_copy,
        "color_sheets_per_copy": color_sheets_per_copy,
        "segments": segments,
    }


def slice_pdf_for_print(
    source_pdf_path: Path,
    output_pdf_path: Path,
    selected_pages: list[int],
    rotations: dict[str, int] | None = None,
    pages_per_sheet: int = 1,
    orientation: str = "portrait",
    paper_size: str = "A4",
    color_mode: str = "bw",
    color_pages: list[int] | None = None,
    duplex: str = "simplex",
) -> int:
    """Extract selected pages, apply rotations/layout/grayscale, write master + segment PDFs, and return count."""
    if not selected_pages:
        raise ValueError("Chop etish uchun kamida 1 ta bet tanlanishi kerak.")

    reader = PdfReader(str(source_pdf_path))
    total_pages = len(reader.pages)
    rot_map = {str(k): int(v) % 360 for k, v in (rotations or {}).items()}

    # Build temporary intermediate writer with selected & rotated pages
    temp_writer = PdfWriter()
    extracted_pages: list[PageObject] = []
    valid_selected: list[int] = []
    for page_num in selected_pages:
        if 1 <= page_num <= total_pages:
            page = reader.pages[page_num - 1]
            angle = rot_map.get(str(page_num), 0)
            if angle in {90, 180, 270}:
                page.rotate(angle)
            temp_writer.add_page(page)
            extracted_pages.append(temp_writer.pages[-1])
            valid_selected.append(page_num)

    if not extracted_pages:
        raise ValueError("Tanlangan betlar hujjat diapazonida topilmadi.")

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pps = pages_per_sheet if pages_per_sheet in {1, 2, 4} else 1
    base_w, base_h = PAPER_DIMENSIONS_PT.get(paper_size, PAPER_DIMENSIONS_PT["A4"])

    plan = compute_sheet_color_plan(
        selected_pages=valid_selected,
        color_mode=color_mode,
        color_pages=color_pages,
        duplex=duplex,
        pages_per_sheet=pps,
    )

    mode_norm = (color_mode or "bw").strip().lower()
    if mode_norm in {"bw", "mixed"}:
        face_modes = plan["face_modes"]
        for src_idx, src_page in enumerate(extracted_pages):
            face_idx = src_idx // pps
            if face_idx < len(face_modes) and face_modes[face_idx] == "bw":
                _convert_page_streams_to_grayscale(src_page, temp_writer)

    final_writer = PdfWriter()

    if pps == 1 and orientation == "portrait":
        for src in extracted_pages:
            final_writer.add_page(src)
    elif pps == 1:
        sheet_w, sheet_h = (base_h, base_w) if orientation == "landscape" else (base_w, base_h)
        for src in extracted_pages:
            blank = PageObject.create_blank_page(width=sheet_w, height=sheet_h)
            _place_page_in_cell(blank, src, 0.0, 0.0, sheet_w, sheet_h, padding=8.0)
            final_writer.add_page(blank)
    elif pps == 2:
        for idx in range(0, len(extracted_pages), 2):
            chunk = extracted_pages[idx : idx + 2]
            src_is_land = _is_page_landscape(chunk[0])
            if src_is_land:
                sheet_w, sheet_h = (base_w, base_h) if orientation == "portrait" else (base_h, base_w)
            else:
                sheet_w, sheet_h = (base_h, base_w) if orientation == "portrait" else (base_w, base_h)
            blank = PageObject.create_blank_page(width=sheet_w, height=sheet_h)
            if sheet_w >= sheet_h:
                half_w = sheet_w / 2.0
                _place_page_in_cell(blank, chunk[0], 0.0, 0.0, half_w, sheet_h)
                if len(chunk) > 1:
                    _place_page_in_cell(blank, chunk[1], half_w, 0.0, half_w, sheet_h)
            else:
                half_h = sheet_h / 2.0
                _place_page_in_cell(blank, chunk[0], 0.0, half_h, sheet_w, half_h)
                if len(chunk) > 1:
                    _place_page_in_cell(blank, chunk[1], 0.0, 0.0, sheet_w, half_h)
            final_writer.add_page(blank)
    else:
        for idx in range(0, len(extracted_pages), 4):
            chunk = extracted_pages[idx : idx + 4]
            src_is_land = _is_page_landscape(chunk[0])
            sheet_w, sheet_h = (
                (base_h, base_w)
                if (orientation == "landscape" or (orientation == "portrait" and src_is_land))
                else (base_w, base_h)
            )
            half_w = sheet_w / 2.0
            half_h = sheet_h / 2.0
            slots = [
                (0.0, half_h),
                (half_w, half_h),
                (0.0, 0.0),
                (half_w, 0.0),
            ]
            blank = PageObject.create_blank_page(width=sheet_w, height=sheet_h)
            for pos, src in enumerate(chunk):
                cx, cy = slots[pos]
                _place_page_in_cell(blank, src, cx, cy, half_w, half_h)
            final_writer.add_page(blank)

    with open(output_pdf_path, "wb") as f:
        final_writer.write(f)

    segments = plan["segments"]
    if len(segments) > 1:
        for seg in segments:
            seg_writer = PdfWriter()
            for face_idx in range(seg["start_face"], min(seg["end_face"], len(final_writer.pages))):
                seg_writer.add_page(final_writer.pages[face_idx])
            seg_path = output_pdf_path.parent / seg["pdf_filename"]
            with open(seg_path, "wb") as sf:
                seg_writer.write(sf)

    return len(extracted_pages)


def calculate_print_metrics(
    selected_page_count: int,
    copies: int,
    color_mode: str,
    duplex: str,
    pages_per_sheet: int,
    pricing: dict[str, int] | None = None,
    selected_pages: list[int] | None = None,
    color_pages: list[int] | None = None,
) -> dict[str, Any]:
    """Compute effective printed pages, physical sheets (BW + Color), cost in UZS, and duration."""
    safe_pages = max(0, int(selected_page_count))
    safe_copies = max(1, int(copies))
    safe_pps = max(1, int(pages_per_sheet))

    effective_pages_per_copy = math.ceil(safe_pages / safe_pps) if safe_pages > 0 else 0
    if duplex == "duplex":
        sheets_per_copy = math.ceil(effective_pages_per_copy / 2)
    else:
        sheets_per_copy = effective_pages_per_copy

    physical_sheets = sheets_per_copy * safe_copies
    total_printed_pages = safe_pages * safe_copies

    prices = pricing or {}
    bw_simplex = int(prices.get("bw_simplex", PRICE_BW_SIMPLEX))
    bw_duplex = int(prices.get("bw_duplex", PRICE_BW_DUPLEX))
    color_simplex = int(prices.get("color_simplex", PRICE_COLOR_SIMPLEX))
    color_duplex = int(prices.get("color_duplex", PRICE_COLOR_DUPLEX))

    bw_unit = bw_duplex if duplex == "duplex" else bw_simplex
    color_unit = color_duplex if duplex == "duplex" else color_simplex

    mode_norm = (color_mode or "bw").strip().lower()
    segments: list[dict[str, Any]] = []

    if mode_norm == "mixed" and selected_pages:
        plan = compute_sheet_color_plan(
            selected_pages=selected_pages,
            color_mode="mixed",
            color_pages=color_pages,
            duplex=duplex,
            pages_per_sheet=safe_pps,
        )
        bw_sheets = plan["bw_sheets_per_copy"] * safe_copies
        color_sheets = plan["color_sheets_per_copy"] * safe_copies
        segments = plan["segments"]
        unit_price = bw_unit if color_sheets == 0 else (color_unit if bw_sheets == 0 else color_unit)
    elif mode_norm == "color":
        bw_sheets = 0
        color_sheets = physical_sheets
        unit_price = color_unit
    else:
        bw_sheets = physical_sheets
        color_sheets = 0
        unit_price = bw_unit

    sec_bw = max(1, int(prices.get("seconds_bw_per_sheet", SECONDS_BW_PER_SHEET)))
    sec_color = max(1, int(prices.get("seconds_color_per_sheet", SECONDS_COLOR_PER_SHEET)))
    warmup = max(0, int(prices.get("warmup_seconds", WARMUP_SECONDS)))
    duplex_factor = 1.5 if duplex == "duplex" else 1.0

    estimated_seconds = (
        int(math.ceil(warmup + (bw_sheets * sec_bw + color_sheets * sec_color) * duplex_factor))
        if physical_sheets > 0
        else 0
    )

    estimated_cost = bw_sheets * bw_unit + color_sheets * color_unit
    return {
        "total_printed_pages": total_printed_pages,
        "physical_sheets": physical_sheets,
        "bw_sheets": bw_sheets,
        "color_sheets": color_sheets,
        "estimated_cost": estimated_cost,
        "unit_price": unit_price,
        "estimated_seconds": estimated_seconds,
        "segments": segments,
    }
