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
        rect_paths = []
        for path in drawings:
            for item in path["items"]:
                if item[0] == "re":
                    rect = fitz.Rect(item[1])
                    if rect.width > 50 and rect.height > 20:
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
                            entry["border_color"] = _normalize_color(path.get("color"))
                            entry["border_fill"] = _normalize_color(path.get("fill"))
                            entry["border_width"] = round(path.get("width", 1), 1)
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
    """Parse pdfimages -list output for page-level image metadata."""
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
                entries.append({
                    "page": int(parts[0]),
                    "width": int(parts[3]),
                    "height": int(parts[4]),
                    "type": parts[2],
                })
            except (ValueError, IndexError):
                continue
    return entries


def _suggest_figure_width(pixel_width: int) -> str:
    """Suggest a \\includegraphics width based on image pixel dimensions."""
    if pixel_width > 900:
        return "0.85\\textwidth"
    elif pixel_width > 600:
        return "0.65\\textwidth"
    elif pixel_width > 300:
        return "0.45\\textwidth"
    else:
        return "0.3\\textwidth"


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
                detail["suggested_width"] = _suggest_figure_width(detail.get("width", 0) or 0)
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

    remaining_pages = sorted(source_pages_seen - fullpage_pages) if fullpage_pages else sorted(source_pages_seen)
    summary = f"content images: {content_count} (source pages: {remaining_pages}). "
    summary += "ONLY include images with type='content' as figures. Skip images with type containing '(skip)'. "
    summary += "Each content image includes a 'suggested_width' field — use it as the width parameter in \\includegraphics."

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


def write_tex_file(tex_path: str, content: str) -> str:
    """Write LaTeX content to a .tex file."""
    content = _strip_page_render_figures(content)
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
