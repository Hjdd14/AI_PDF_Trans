"""Shared fixtures for AI PDF Trans tests."""

import os
import tempfile

import pytest

from src.utils.file_utils import get_tectonic_path


DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AI_PDF_Trans")
HAS_TECTONIC = get_tectonic_path(DATA_DIR) is not None


@pytest.fixture(scope="session")
def data_dir():
    return DATA_DIR


@pytest.fixture(scope="session")
def has_tectonic():
    return HAS_TECTONIC


@pytest.fixture
def test_pdf():
    """Create a minimal 1-page PDF with text content for testing."""
    import fitz
    from src.agent_runtime.tools import clear_pdf_cache
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf_path = f.name
    f.close()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Hello World Test PDF", fontsize=14)
    page.insert_text((50, 150), "Math symbols: α β γ ∈ ∇", fontsize=12)
    page.insert_text((50, 200), "CJK text: 中文测试", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    yield pdf_path
    clear_pdf_cache()
    os.unlink(pdf_path)


@pytest.fixture
def test_image():
    """Create a minimal 1x1 PNG image for testing."""
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c49444154789c63606060000000040001f61738550000000049454e44ae"
        "426082"
    )
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img_path = f.name
    f.write(png_bytes)
    f.close()
    yield img_path
    os.unlink(img_path)


@pytest.fixture
def test_tex_file():
    """Create a simple valid .tex file."""
    content = (
        r"\documentclass[12pt]{article}" + "\n"
        r"\usepackage{fontspec}" + "\n"
        r"\begin{document}" + "\n"
        r"Hello, world!" + "\n"
        r"\end{document}" + "\n"
    )
    f = tempfile.NamedTemporaryFile(suffix=".tex", mode="w", encoding="utf-8", delete=False)
    tex_path = f.name
    f.write(content)
    f.close()
    yield tex_path
    os.unlink(tex_path)


@pytest.fixture
def fake_pdf(temp_dir):
    """Create a minimal fake PDF file for agent loop tests."""
    from src.agent_runtime.tools import clear_pdf_cache
    path = os.path.join(temp_dir, "source.pdf")
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 fake pdf for agent testing")
    yield path
    clear_pdf_cache()


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    dir_path = tempfile.mkdtemp()
    yield dir_path
    import shutil
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def bordered_pdf():
    """Create a PDF with a text block enclosed by a drawn rectangle."""
    import fitz
    from src.agent_runtime.tools import clear_pdf_cache
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf_path = f.name
    f.close()
    doc = fitz.open()
    page = doc.new_page()
    # Draw a rectangle border
    rect = fitz.Rect(40, 80, 400, 160)
    page.draw_rect(rect, color=(0, 0, 0), width=1.5)
    # Insert text inside the rectangle
    page.insert_text((50, 110), "Framed Title Block", fontsize=14)
    page.insert_text((50, 140), "Subtitle inside frame", fontsize=11)
    # Insert text outside the rectangle (no border)
    page.insert_text((50, 220), "Normal paragraph without border", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    yield pdf_path
    clear_pdf_cache()
    os.unlink(pdf_path)


