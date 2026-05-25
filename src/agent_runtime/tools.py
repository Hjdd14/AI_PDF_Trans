"""Tool implementations for the translation agent.

Each tool is a standalone function that can be called by name from the agent loop.
Tools interact with the filesystem, PDF documents, and the Tectonic compiler.
"""

import base64
import json
import logging
import os
import re
import subprocess
import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from src.core.tex_compiler import TexCompiler
from src.utils.font_utils import (
    needs_cjk_package,
    get_cjk_font_filename_for_lang,
    get_cjk_font_for_lang,
    get_cjk_font_file_for_lang,
)


# ── PDF Handle Cache ────────────────────────────────────────────────────────────

# Track opened documents so we can close them on cleanup
_opened_docs: list = []


@lru_cache(maxsize=5)
def _open_pdf(pdf_path: str):
    """Cache and reuse PyMuPDF document handles across tool calls."""
    doc = fitz.open(pdf_path)
    _opened_docs.append(doc)
    return doc


def clear_pdf_cache():
    """Close all cached PDF documents and clear the cache."""
    for doc in _opened_docs:
        try:
            doc.close()
        except Exception:
            pass
    _opened_docs.clear()
    _open_pdf.cache_clear()


# ── Tool 1: get_pdf_info ──────────────────────────────────────────────────────

def get_pdf_info(pdf_path: str) -> dict:
    """Get basic PDF metadata."""
    doc = _open_pdf(pdf_path)
    try:
        metadata = doc.metadata or {}
        return {
            "page_count": doc.page_count,
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "file_size": os.path.getsize(pdf_path),
            "is_encrypted": doc.is_encrypted,
            "needs_pass": doc.needs_pass,
        }
    finally:
        pass  # cached, do not close


# ── Tool 2: get_page_text ─────────────────────────────────────────────────────

def get_page_text(pdf_path: str, page_num: int) -> str:
    """Extract all visible text from one page."""
    doc = _open_pdf(pdf_path)
    try:
        if page_num < 1 or page_num > doc.page_count:
            raise ValueError(f"Page {page_num} out of range (1-{doc.page_count})")
        page = doc[page_num - 1]
        text = page.get_text("text")
        return text.strip() if text else "(empty page - no text extracted)"
    finally:
        pass  # cached, do not close


# ── Tool 3: get_page_blocks ───────────────────────────────────────────────────

def _rect_contains_text(outer, inner, margin=20):
    """Check if rectangle *outer* tightly contains *inner* (with margin tolerance)."""
    return (
        outer.x0 - margin <= inner.x0
        and outer.y0 - margin <= inner.y0
        and outer.x1 + margin >= inner.x1
        and outer.y1 + margin >= inner.y1
    )


def _normalize_color(color):
    """Convert a PyMuPDF color (list of 0-1 floats or None) to a hex string."""
    if not color:
        return None
    r, g, b = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Decorative frame helpers ──────────────────────────────────────────────────

def _is_decorative_cluster(drawings: list, cluster_bbox) -> bool:
    """True = decorative frame (skip in run_pdfimages), False = real chart/table (keep).

    Filters out title-page decorative brackets formed by line segments,
    while preserving real vector charts/tables that contain curves or fills.
    """
    cluster_paths = [p for p in drawings if p["rect"].intersects(cluster_bbox)]

    # Real chart: has curves (Bezier data lines, circles)
    if any(item[0] == "c" for p in cluster_paths for item in p["items"]):
        return False

    # Real chart/table: has fills (colored areas, table header shading)
    if any(p.get("fill") and any(c > 0 for c in p["fill"][:3]) for p in cluster_paths):
        return False

    # Very few paths → decorative underline / icon
    if len(cluster_paths) < 3:
        return True

    # Extreme aspect ratio → horizontal/vertical separator line
    w, h = cluster_bbox.width, cluster_bbox.height
    if w > 0 and h > 0 and (w / h > 20 or h / w > 20):
        return True

    # Perimeter-only check: decorative title frames form a hollow rectangle
    # with all paths at the edges.  Real tables/charts have interior elements.
    margin = 0.1  # 10% from each edge = 80% interior zone
    inner = (
        cluster_bbox.x0 + cluster_bbox.width * margin,
        cluster_bbox.y0 + cluster_bbox.height * margin,
        cluster_bbox.x1 - cluster_bbox.width * margin,
        cluster_bbox.y1 - cluster_bbox.height * margin,
    )
    interior_count = 0
    for p in cluster_paths:
        r = p["rect"]
        if r.x0 < inner[2] and r.x1 > inner[0] and r.y0 < inner[3] and r.y1 > inner[1]:
            interior_count += 1

    if interior_count == 0:
        return True  # all paths at perimeter = decorative frame

    return False

def get_page_blocks(pdf_path: str, page_num: int, verbose: bool = False) -> str:
    """Extract structured text blocks from a page.

    By default returns text-only blocks (compact).  Set verbose=True to include
    bounding-box, font-size and bold/italic flags for layout analysis.

    Text blocks that are enclosed by a drawn rectangle get ``"has_border": true``.
    When verbose=True, additional border_color / border_fill / border_width keys
    are included so the LLM can reproduce the frame in LaTeX.
    """
    doc = _open_pdf(pdf_path)
    try:
        if page_num < 1 or page_num > doc.page_count:
            raise ValueError(f"Page {page_num} out of range (1-{doc.page_count})")
        page = doc[page_num - 1]
        blocks = page.get_text("dict", sort=True)["blocks"]

        # Collect drawn rectangles for border detection
        drawings = page.get_drawings()
        page_width = page.rect.width
        page_height = page.rect.height
        rect_paths = []
        for path in drawings:
            for item in path["items"]:
                if item[0] == "re":
                    rect = fitz.Rect(item[1])
                    if rect.width > 50 and rect.height > 20:
                        # Skip page-level decorative frames (>80% of page)
                        if rect.width > 0.8 * page_width or rect.height > 0.8 * page_height:
                            continue
                        rect_paths.append((rect, path))

        result = []
        for block in blocks:
            if block["type"] == 0:  # text block
                block_text = ""
                for line in block["lines"]:
                    for span in line["spans"]:
                        block_text += span["text"] + " "
                entry = {"type": "text", "text": block_text.strip()}
                if verbose:
                    font_sizes = []
                    is_bold = False
                    for line in block["lines"]:
                        for span in line["spans"]:
                            font_sizes.append(span["size"])
                            if span["font"].lower().find("bold") >= 0:
                                is_bold = True
                    avg_font = sum(font_sizes) / len(font_sizes) if font_sizes else 0
                    entry.update({
                        "bbox": [round(v, 1) for v in block["bbox"]],
                        "font_size": round(avg_font, 1),
                        "is_bold": is_bold,
                    })

                # Border detection: check if any drawn rectangle encloses this block
                block_bbox = fitz.Rect(block["bbox"])
                for rect, path in rect_paths:
                    if _rect_contains_text(rect, block_bbox):
                        entry["has_border"] = True
                        if verbose:
                            if path:
                                entry["border_color"] = _normalize_color(path.get("color"))
                                entry["border_fill"] = _normalize_color(path.get("fill"))
                                entry["border_width"] = round(path.get("width", 1), 1)
                            else:
                                entry["border_color"] = None
                                entry["border_fill"] = None
                                entry["border_width"] = None
                        break

                result.append(entry)
            elif block["type"] == 1:  # image block
                entry = {"type": "image_block"}
                if verbose:
                    entry.update({
                        "bbox": [round(v, 1) for v in block["bbox"]],
                        "width": block.get("width", 0),
                        "height": block.get("height", 0),
                    })
                result.append(entry)

        return json.dumps(result, ensure_ascii=False, indent=2)
    finally:
        pass  # cached, do not close


# ── Tool 4: get_page_as_image ─────────────────────────────────────────────────

def get_page_as_image(pdf_path: str, page_num: int, output_dir: str, dpi: int = 150) -> dict:
    """Render a PDF page for visual reference — NOT for use as a figure image."""
    doc = _open_pdf(pdf_path)
    try:
        if page_num < 1 or page_num > doc.page_count:
            raise ValueError(f"Page {page_num} out of range (1-{doc.page_count})")
        page = doc[page_num - 1]

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"page_{page_num:04d}.png")
        pix = page.get_pixmap(dpi=dpi)
        pix.save(output_path)

        with open(output_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        return {
            "image_data": f"data:image/png;base64,{b64[:200]}",
            "width": pix.width,
            "height": pix.height,
            "file_size": os.path.getsize(output_path),
            "note": "This is a FULL PAGE RENDER for VISUAL REFERENCE ONLY. "
                    "NEVER use this image in \\includegraphics. "
                    "It is not a figure — it is the entire page content.",
        }
    finally:
        pass  # cached, do not close


# ── Tool 5: run_pdfimages ─────────────────────────────────────────────────────

def _find_pdfimages() -> str | None:
    """Resolve pdfimages executable path.

    Checks bundled resource first (PyInstaller frozen exe), then system PATH.
    """
    try:
        from src.utils.resources import get_bundled_data_dir, is_frozen
        if is_frozen():
            bundled = os.path.join(get_bundled_data_dir(), "bin", "pdfimages.exe")
            if os.path.isfile(bundled):
                return bundled
    except ImportError:
        pass
    # Fall back to PATH lookup
    import shutil
    found = shutil.which("pdfimages")
    return found


def _parse_pdfimages_list(pdf_path: str) -> list[dict]:
    """Parse pdfimages -list output for page-level image metadata.

    pdfimages -list columns:
      page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio
      0    1   2    3     4      5     6    7   8   9      10     11 12    13    14   15

    Column 12,13 (x-ppi, y-ppi) give the rendering DPI, which we use to
    compute the physical rendering size in PDF points (1pt = 1/72 inch).
    """
    exe = _find_pdfimages()
    if not exe:
        return []
    try:
        result = subprocess.run([exe, "-list", pdf_path], capture_output=True, text=True, timeout=30)
    except Exception:
        return []
    entries = []
    for line in result.stdout.strip().split("\n")[2:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                pw = int(parts[3])
                xppi = int(parts[12]) if len(parts) > 12 else 72
                yppi = int(parts[13]) if len(parts) > 13 else 72
                entry = {
                    "page": int(parts[0]),
                    "width": pw,
                    "height": int(parts[4]),
                    "type": parts[2],
                    "x_ppi": xppi,
                    "y_ppi": yppi,
                    # Physical rendering size in PDF points (1pt = 1/72 inch)
                    "physical_width_pt": round(pw / xppi * 72, 1) if xppi > 0 else None,
                    "xref": int(parts[10]) if len(parts) > 10 else None,
                }
                entries.append(entry)
            except (ValueError, IndexError):
                continue
    return entries


def _suggest_figure_width(pixel_width: int, physical_width_pt: float | None = None) -> str:
    """Suggest a \\includegraphics width for a figure.

    Uses pixel-dimension heuristics as the primary basis (fraction of textwidth),
    then refines with DPI-based physical size when available — but never lets
    the physical size produce a value smaller than the pixel-based minimum.

    This prevents high-DPI images (e.g. 360 DPI) from getting unreasonably
    small pt values that would make the figure tiny in the translated output.
    """
    # Pixel-based heuristic: larger pixels → larger textwidth fraction
    if pixel_width > 900:
        pixel_ratio = 0.85
    elif pixel_width > 600:
        pixel_ratio = 0.65
    elif pixel_width > 300:
        pixel_ratio = 0.45
    else:
        pixel_ratio = 0.30

    if physical_width_pt is not None and physical_width_pt > 0:
        # Use physical size but never below pixel-based minimum
        # (455pt ≈ A4 text width with 2.5cm margins)
        pixel_min_pt = pixel_ratio * 455
        effective_pt = max(physical_width_pt, pixel_min_pt)
        return f"{effective_pt:.0f}pt"

    # No DPI info — use pixel-based heuristic directly
    return f"{pixel_ratio}\\textwidth"


def run_pdfimages(pdf_path: str, output_dir: str, prefix: str = "img") -> dict:
    """Extract embedded images using pdfimages (poppler-utils)."""
    os.makedirs(output_dir, exist_ok=True)
    prefix_path = os.path.join(output_dir, prefix)

    exe = _find_pdfimages()
    if not exe:
        return {"error": "pdfimages not found. Install poppler-utils or use extract_page_images instead.",
                "files": []}

    try:
        result = subprocess.run(
            [exe, "-png", pdf_path, prefix_path],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return {"error": "pdfimages not found. Install poppler-utils or use extract_page_images instead.",
                "files": []}
    except subprocess.TimeoutExpired:
        return {"error": "pdfimages timed out after 120 seconds.", "files": []}

    # List extracted files
    png_files = sorted([f for f in os.listdir(output_dir) if f.endswith(".png") and f.startswith(prefix)])

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Get pixel dimensions for each extracted file
    file_details = []
    for f in png_files:
        filepath = os.path.join(output_dir, f)
        try:
            with Image.open(filepath) as img:
                file_details.append({
                    "filename": f,
                    "width": img.width,
                    "height": img.height,
                    "size_bytes": os.path.getsize(filepath),
                })
        except Exception:
            file_details.append({
                "filename": f,
                "size_bytes": os.path.getsize(filepath),
                "note": "Could not read dimensions (possibly not an image)",
            })

    # Add source page mapping from pdfimages -list.
    # pdfimages -png extracts ALL entries (including smask) in the same order as -list.
    list_entries = _parse_pdfimages_list(pdf_path)
    content_count = 0
    source_pages_seen = set()
    for i, detail in enumerate(file_details):
        if i < len(list_entries):
            etype = list_entries[i]["type"]
            if etype == "image":
                detail["source_page"] = list_entries[i]["page"]
                detail["type"] = "content"
                # Store xref for bbox lookup later
                detail["xref"] = list_entries[i].get("xref")
                # Calculate physical width from DPI: physical_pt = pixel_width / x_ppi * 72
                # This is the actual rendering size on the PDF page.
                xppi = list_entries[i].get("x_ppi", 72) or 72
                pw = detail.get("width", 0) or 0
                phys_w = round(pw / xppi * 72, 1) if (pw > 0 and xppi > 0) else None
                detail["suggested_width"] = _suggest_figure_width(pw, phys_w)
                content_count += 1
                source_pages_seen.add(list_entries[i]["page"])
            else:
                detail["type"] = f"{etype} (skip)"

    # ── Full-page image filter ───────────────────────────────────────────────
    # Slide-exported PDFs often embed each entire slide as a single raster image.
    # Without filtering, the LLM places these as figures, duplicating all page text.
    # Check each image's placement bbox: if it covers >70% of its source page,
    # it's likely a full-page render, not a discrete figure — skip it.
    fullpage_pages = set()
    if content_count > 0:
        try:
            doc = _open_pdf(pdf_path)
            for sp in source_pages_seen:
                try:
                    page = doc[sp - 1]
                    pw, ph = page.rect.width, page.rect.height
                    page_area = pw * ph
                    for img_info in page.get_images(full=True):
                        xref = img_info[0]
                        for rect in page.get_image_rects(xref):
                            if rect.width * rect.height / page_area > 0.7:
                                fullpage_pages.add(sp)
                                break
                except Exception:
                    continue

            if fullpage_pages:
                for detail in file_details:
                    if detail.get("source_page") in fullpage_pages and detail.get("type") == "content":
                        detail["type"] = "fullpage (skip)"
                        content_count -= 1
        except Exception:
            pass

    # ── Image position metadata ────────────────────────────────────────────
    # Add bbox position on the source page so the LLM can infer the original
    # layout (e.g., 2×2 grid from images at different y-positions).  Group
    # images by source_page to detect multi-panel figures.
    try:
        doc = _open_pdf(pdf_path)
        # Build xref→bbox mapping for each source page
        page_xref_bboxes: dict[int, dict[int, list[list[float]]]] = {}
        for sp in source_pages_seen:
            try:
                page = doc[sp - 1]
                xref_bboxes: dict[int, list[list[float]]] = {}
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    rects = page.get_image_rects(xref)
                    xref_bboxes[xref] = [
                        [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)]
                        for r in rects
                    ]
                page_xref_bboxes[sp] = xref_bboxes
            except Exception:
                continue

        # Group content images by source_page for count and position hint
        content_by_page: dict[int, list[dict]] = {}
        for detail in file_details:
            if detail.get("type") == "content":
                sp = detail["source_page"]
                content_by_page.setdefault(sp, []).append(detail)

        for sp, items in content_by_page.items():
            count_on_page = len(items)
            for detail in items:
                detail["source_page_image_count"] = count_on_page
                # Look up bbox via xref
                xref = detail.get("xref")
                if xref is not None and sp in page_xref_bboxes and xref in page_xref_bboxes[sp]:
                    bboxes = page_xref_bboxes[sp][xref]
                    # Use the first bbox (most images appear only once)
                    detail["bbox"] = bboxes[0] if bboxes else None
                else:
                    detail["bbox"] = None
                # Position hint: multiple images on same page → likely subfigures
                detail["position_hint"] = "subfigure_grid" if count_on_page >= 2 else "single"
    except Exception:
        pass

    # ── Vector graphics fallback ──────────────────────────────────────────
    # pdfimages only extracts EMBEDDED RASTER images.  Pages with vector
    # graphics (line charts, diagrams, drawings) are drawn with PDF path
    # operators and produce NO pdfimages output.  Use cluster_drawings to
    # identify figure regions and render only the clipped area, preserving
    # the original graphic at its exact physical size.
    covered_pages: set[int] = (source_pages_seen - fullpage_pages) if fullpage_pages else set(source_pages_seen)
    rendered_pages: set[int] = set()
    try:
        doc = _open_pdf(pdf_path)
        for pg in range(1, doc.page_count + 1):
            if pg in covered_pages:
                continue  # already has content images from pdfimages
            page = doc[pg - 1]
            # Group nearby vector drawings into figure regions
            clusters = list(page.cluster_drawings(x_tolerance=15, y_tolerance=15))
            if not clusters:
                continue  # no vector drawings on this page
            page_drawings = page.get_drawings()
            # Page-level check: if this page has any real chart cluster (with
            # interior content), keep ALL clusters — chart axis frames may have
            # perimeter-only paths that _is_decorative_cluster would misdetect.
            sig_clusters = [b for b in clusters if b.width >= 50 and b.height >= 50]
            has_real_chart = any(
                not _is_decorative_cluster(page_drawings, b) for b in sig_clusters
            )
            for ci, bbox in enumerate(clusters):
                if bbox.width < 50 or bbox.height < 50:
                    continue  # too small — likely decorative noise
                # On pages WITHOUT real charts (e.g. cover page), skip decorative
                # clusters (title brackets) to avoid duplicate figure renders.
                # On pages WITH real charts, keep everything — axis frames are
                # needed for complete figure rendering.
                if not has_real_chart and _is_decorative_cluster(page_drawings, bbox):
                    continue
                # Expand 25pt to include axis labels, chart titles
                expanded = bbox + (-25, -25, 25, 25)
                expanded = expanded & page.rect  # clamp to page bounds
                filename = f"fig-page-{pg:04d}-c{ci}.png"
                filepath = os.path.join(output_dir, filename)
                if not os.path.isfile(filepath):
                    pix = page.get_pixmap(clip=expanded, dpi=200)
                    pix.save(filepath)
                with Image.open(filepath) as img:
                    file_details.append({
                        "filename": filename,
                        "width": img.width,
                        "height": img.height,
                        "size_bytes": os.path.getsize(filepath),
                        "source_page": pg,
                        "type": "vector_render",
                        # Physical width in PDF points = original on-page size
                        "suggested_width": f"{bbox.width:.0f}pt",
                    })
                    content_count += 1
                rendered_pages.add(pg)
    except Exception:
        pass

    remaining_pages = sorted(covered_pages | rendered_pages)
    summary = f"content images: {content_count} (source pages: {remaining_pages}). "
    summary += "Include images with type='content' or type='vector_render' as figures. Skip images with type containing '(skip)'. "
    summary += "type='vector_render' images are rendered figure regions for vector graphics (charts, diagrams) that pdfimages couldn't extract. "
    summary += "Each image includes a 'suggested_width' field — use it as the width parameter in \\includegraphics. "
    summary += "Content images now include 'bbox', 'source_page_image_count', and 'position_hint' fields for spatial layout info."

    return {
        "files": file_details,
        "count": len(png_files),
        "content_count": content_count,
        "stdout": stdout or "(no output)",
        "stderr": stderr or "(no errors)",
        "directory": output_dir,
        "note": summary,
    }


# ── Tool 6: extract_page_images ───────────────────────────────────────────────

def extract_page_images(pdf_path: str, page_num: int, output_dir: str) -> dict:
    """Extract embedded raster images from one page using PyMuPDF."""
    doc = _open_pdf(pdf_path)
    try:
        if page_num < 1 or page_num > doc.page_count:
            raise ValueError(f"Page {page_num} out of range (1-{doc.page_count})")
        page = doc[page_num - 1]

        os.makedirs(output_dir, exist_ok=True)
        image_list = page.get_images(full=True)
        extracted = []

        for idx, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            ext = base_image["ext"]
            filename = f"page{page_num:04d}_img{idx}_{xref}.{ext}"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            extracted.append({
                "filename": filename,
                "width": base_image["width"],
                "height": base_image["height"],
                "ext": ext,
                "size": len(image_bytes),
            })

        return {
            "page": page_num,
            "count": len(extracted),
            "images": extracted,
            "directory": output_dir,
        }
    finally:
        pass  # cached, do not close


# ── Tool 7: view_image ────────────────────────────────────────────────────────

def view_image(image_path: str) -> str:
    """Read a saved image and return as base64 data URL for visual inspection.

    Returns pixel dimensions so the LLM can calculate correct LaTeX size.
    Compresses large images (>500KB) to ~800px wide to keep results compact.
    """
    if not os.path.isfile(image_path):
        return f"Error: file not found: {image_path}"

    ext = Path(image_path).suffix.lower().lstrip(".")
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
    }
    mime = mime_map.get(ext, "image/png")

    file_size = os.path.getsize(image_path)

    with Image.open(image_path) as img:
        orig_w, orig_h = img.size
        # Compress large images to keep responses manageable
        if file_size > 500_000:
            ratio = min(800 / orig_w, 800 / orig_h, 1.0)
            new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        else:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

    return (
        f"Image: {image_path} ({file_size} bytes)\n"
        f"Dimensions: {orig_w}x{orig_h} px\n"
        f"![{image_path}](data:{mime};base64,{b64})"
    )


# ── Tool 8: read_file ─────────────────────────────────────────────────────────

def read_file(file_path: str) -> str:
    """Read any text file and return its content."""
    if not os.path.isfile(file_path):
        return f"Error: file not found: {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        # Try with different encoding for binary/text mixed files
        try:
            with open(file_path, "r", encoding="utf-16") as f:
                return f.read()
        except Exception:
            return f"Error: cannot read {file_path} as text (binary file?). Use view_image() for images."


# ── Tool 9: write_tex_file ────────────────────────────────────────────────────

# Regex: remove \begin{figure}[H]...\end{figure} blocks that contain page_renders
_PAGE_RENDER_FIGURE_RE = re.compile(
    r'\\begin\{figure\}\[H\]\s*\n'
    r'(?:\s*\\centering\s*\n)?'
    r'\s*\\includegraphics\[.*?\]\{.*?page_renders/.*?\}\s*\n'
    r'(?:\s*\\caption\{.*?\}\s*\n)?'
    r'(?:\s*\\label\{.*?\}\s*\n)?'
    r'\s*\\end\{figure\}',
    re.MULTILINE | re.DOTALL,
)

# Regex: remove stray \includegraphics referencing page_renders outside figure env
_PAGE_RENDER_INCLUDEGRAPHICS_RE = re.compile(
    r'\\includegraphics\[.*?\]\{.*?page_renders/.*?\}',
)


def _strip_page_render_figures(content: str) -> str:
    """Remove any \\includegraphics or figure environments referencing page_renders/."""
    cleaned = _PAGE_RENDER_FIGURE_RE.sub('', content)
    cleaned = _PAGE_RENDER_INCLUDEGRAPHICS_RE.sub('', cleaned)
    if cleaned != content:
        stripped_count = content.count('page_renders') - cleaned.count('page_renders')
        logging.warning("Stripped %%d page_renders/ reference(s) from .tex output", stripped_count)
    return cleaned


# LaTeX counter names for nested enumerate levels
_ENUM_COUNTERS = ['enumi', 'enumii', 'enumiii', 'enumiv']


def _extract_figures_from_lists(content: str) -> str:
    """Extract [H] figure environments from inside enumerate/itemize.

    LaTeX cannot properly page-break inside a list when a ``[H]`` float is
     embedded. This function detects figures inside list environments and
    splits the list around each figure, preserving item numbering.

    Before::

        \\begin{enumerate}
        \\item ...
        \\begin{figure}[H]...
        \\end{figure}
        \\item ...
        \\end{enumerate}

    After::

        \\begin{enumerate}
        \\item ...
        \\end{enumerate}
        \\begin{figure}[H]...
        \\end{figure}
        \\begin{enumerate}
        \\setcounter{enumi}{1}
        \\item ...
        \\end{enumerate}
    """
    lines = content.split('\n')
    out = []
    # Stack of active list environments: each entry has type and item_count
    list_stack: list[dict[str, int | str]] = []
    in_figure = False

    def _close_lists():
        for env in reversed(list_stack):
            out.append(f'\\end{{{env["type"]}}}')

    def _reopen_lists():
        for depth, env in enumerate(list_stack):
            out.append(f'\\begin{{{env["type"]}}}')
            cnt = env["item_count"]
            if env["type"] == "enumerate" and cnt > 0 and depth < len(_ENUM_COUNTERS):
                out.append(f'\\setcounter{{{_ENUM_COUNTERS[depth]}}}{{{cnt}}}')

    for line in lines:
        s = line.strip()

        # Enter list environment
        m = re.match(r'\\begin\{(enumerate|itemize)\}', s)
        if m and not in_figure:
            list_stack.append({'type': m.group(1), 'item_count': 0})
            out.append(line)
            continue

        # Exit list environment
        m = re.match(r'\\end\{(enumerate|itemize)\}', s)
        if m and not in_figure and list_stack:
            list_stack.pop()
            out.append(line)
            continue

        # Count items
        if re.match(r'\\item\b', s) and list_stack and not in_figure:
            list_stack[-1]['item_count'] += 1
            out.append(line)
            continue

        # Figure starts inside a list → close list(s) before emitting
        if re.match(r'\\begin\{figure\}', s) and list_stack and not in_figure:
            _close_lists()
            in_figure = True
            out.append(line)
            continue

        # Figure ends inside a list → reopen list(s) after
        if re.match(r'\\end\{figure\}', s) and in_figure:
            in_figure = False
            out.append(line)
            _reopen_lists()
            continue

        out.append(line)

    return '\n'.join(out)


# Regex: remove tcolorbox environments wrapping theorem-like blocks.
# The LLM sometimes adds decorative borders to definitions, theorems,
# etc. on its own, even though get_page_blocks reports has_border=false.
# This post-processor strips those boxes deterministically.
_THEOREM_ENV_NAMES = (
    r'theorem|definition|proposition|lemma|corollary'
    r'|remark|proof|example|axiom|conjecture|hypothesis|claim'
)

_TCOLORBOX_WRAPPED_THEOREM_RE = re.compile(
    r'\\begin\{tcolorbox\}(\[.*?\])?[ \t]*\n?'
    r'(.*?\\begin\{(' + _THEOREM_ENV_NAMES + r')\}.*?\\end\{\3\}(?:[\s\S]*?\\begin\{\3\}.*?\\end\{\3\})*?)\s*'
    r'\\end\{tcolorbox\}',
    re.DOTALL,
)


def _strip_spurious_tcolorbox(content: str) -> str:
    """Remove tcolorbox wrappers around theorem-like environments.

    The LLM sometimes adds decorative borders to definitions, theorems,
    etc. even when get_page_blocks reports has_border=false for all blocks.
    This post-processor strips those boxes deterministically.
    """
    def replacer(m):
        inner = m.group(2).strip()
        return inner
    return _TCOLORBOX_WRAPPED_THEOREM_RE.sub(replacer, content)


def write_tex_file(tex_path: str, content: str) -> str:
    """Write LaTeX content to a .tex file."""
    content = _strip_page_render_figures(content)
    content = _strip_spurious_tcolorbox(content)
    content = _extract_figures_from_lists(content)
    os.makedirs(os.path.dirname(os.path.abspath(tex_path)), exist_ok=True)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote {len(content)} bytes to {tex_path}"


# ── Tool 10: read_tex_file ────────────────────────────────────────────────────

def read_tex_file(tex_path: str) -> str:
    """Read content of a .tex file."""
    if not os.path.isfile(tex_path):
        return f"Error: file not found: {tex_path}"
    with open(tex_path, "r", encoding="utf-8") as f:
        return f.read()


# ── Tool 11: run_command ─────────────────────────────────────────────────────

def run_command(command: str, timeout: int = 60) -> dict:
    """Run a shell command and capture output."""
    try:
        kwargs = dict(
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(command, shell=True, **kwargs)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
    except FileNotFoundError as e:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {e}"}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Command timed out after {timeout} seconds"}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": f"Error: {e}"}


# ── Tool 12: compile_tex_to_pdf ───────────────────────────────────────────────

def compile_tex_to_pdf(tex_path: str, output_dir: str, data_dir: str) -> dict:
    """Compile a .tex file to PDF using Tectonic."""
    compiler = TexCompiler(data_dir)
    result = compiler.compile(tex_path, output_dir)

    return {
        "success": result.success,
        "pdf_path": result.pdf_path if result.success else "",
        "error": result.error,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "diagnostics_dir": result.diagnostics_dir,
    }


# ── Tool 13: get_font_info ────────────────────────────────────────────────────

def get_font_info(target_lang: str) -> dict:
    """Get font information for the target language."""
    normalized = target_lang.lower()
    needs_cjk = needs_cjk_package(normalized)
    filename = get_cjk_font_filename_for_lang(normalized) if needs_cjk else ""
    family = get_cjk_font_for_lang(normalized) if needs_cjk else ""
    filepath = get_cjk_font_file_for_lang(normalized) if needs_cjk else ""

    return {
        "needs_cjk": needs_cjk,
        "font_filename": filename,
        "font_family": family,
        "font_filepath": filepath,
        "note": (
            f"Use \\setCJKmainfont{{{filename}}} in your LaTeX preamble for CJK text."
            if needs_cjk
            else "No CJK font needed for this language."
        ),
    }


# ── Tool 14: list_directory ───────────────────────────────────────────────────

def list_directory(dir_path: str) -> str:
    """List all files in a directory with metadata."""
    if not os.path.isdir(dir_path):
        return f"Error: directory not found: {dir_path}"

    entries = []
    for name in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, name)
        stat = os.stat(full)
        entries.append({
            "name": name,
            "size": stat.st_size,
            "is_dir": os.path.isdir(full),
            "modified": stat.st_mtime,
        })

    return json.dumps(entries, ensure_ascii=False, indent=2)


# ── Tool 15: translation_complete ─────────────────────────────────────────────

def translation_complete(output_pdf_path: str, summary: str) -> dict:
    """Signal that translation is complete. Returns the result for the agent loop."""
    if not os.path.isfile(output_pdf_path):
        return {
            "error": f"Output PDF not found at {output_pdf_path}. Make sure compilation succeeded first.",
            "completed": False,
        }
    return {
        "completed": True,
        "output_pdf_path": output_pdf_path,
        "summary": summary,
    }


# ── Tool dispatcher ───────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "get_pdf_info": get_pdf_info,
    "get_page_text": get_page_text,
    "get_page_blocks": get_page_blocks,
    "get_page_as_image": get_page_as_image,
    "run_pdfimages": run_pdfimages,
    "extract_page_images": extract_page_images,
    "view_image": view_image,
    "read_file": read_file,
    "write_tex_file": write_tex_file,
    "read_tex_file": read_tex_file,
    "run_command": run_command,
    "compile_tex_to_pdf": compile_tex_to_pdf,
    "get_font_info": get_font_info,
    "list_directory": list_directory,
    "translation_complete": translation_complete,
}
