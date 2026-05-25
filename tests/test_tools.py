"""Tests for all 15 translation agent tool functions."""

import json
import os
import tempfile

import pytest

from src.agent_runtime.tools import (
    get_pdf_info,
    get_page_text,
    get_page_blocks,
    get_page_as_image,
    run_pdfimages,
    extract_page_images,
    view_image,
    read_file,
    write_tex_file,
    read_tex_file,
    run_command,
    compile_tex_to_pdf,
    get_font_info,
    list_directory,
    translation_complete,
    TOOL_FUNCTIONS,
)
from tests.conftest import DATA_DIR, HAS_TECTONIC


# ─── Test 1: get_pdf_info ────────────────────────────────────────────────────

class TestGetPdfInfo:
    def test_basic_metadata(self, test_pdf):
        info = get_pdf_info(test_pdf)
        assert info["page_count"] >= 1
        assert info["file_size"] > 0
        assert isinstance(info["title"], str)
        assert isinstance(info["author"], str)

    def test_file_not_found(self):
        with pytest.raises(Exception):
            get_pdf_info("/nonexistent/file.pdf")


# ─── Test 2: get_page_text ───────────────────────────────────────────────────

class TestGetPageText:
    def test_extracts_text(self, test_pdf):
        text = get_page_text(test_pdf, 1)
        assert "Hello World" in text
        assert "Test PDF" in text

    def test_invalid_page_number(self, test_pdf):
        with pytest.raises(ValueError, match="out of range"):
            get_page_text(test_pdf, 999)

    def test_page_zero_invalid(self, test_pdf):
        with pytest.raises(ValueError):
            get_page_text(test_pdf, 0)


# ─── Test 3: get_page_blocks ─────────────────────────────────────────────────

class TestGetPageBlocks:
    def test_returns_json_structure(self, test_pdf):
        result = get_page_blocks(test_pdf, 1)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_contains_text_blocks(self, test_pdf):
        result = get_page_blocks(test_pdf, 1)
        parsed = json.loads(result)
        text_blocks = [b for b in parsed if b["type"] == "text"]
        assert len(text_blocks) > 0
        assert any("Hello World" in b["text"] for b in text_blocks)

    def test_blocks_have_positional_data(self, test_pdf):
        result = get_page_blocks(test_pdf, 1, verbose=True)
        parsed = json.loads(result)
        for block in parsed:
            assert "bbox" in block
            assert len(block["bbox"]) == 4

    def test_invalid_page(self, test_pdf):
        with pytest.raises(ValueError):
            get_page_blocks(test_pdf, 999)

    def test_detects_bordered_text_block(self, bordered_pdf):
        result = get_page_blocks(bordered_pdf, 1)
        parsed = json.loads(result)
        text_blocks = [b for b in parsed if b["type"] == "text"]
        # The "Framed Title Block" text should have has_border=true
        framed = [b for b in text_blocks if "Framed Title" in b["text"]]
        assert len(framed) > 0, "Should find the framed title block"
        assert framed[0].get("has_border") is True

    def test_non_bordered_block_no_border_flag(self, bordered_pdf):
        result = get_page_blocks(bordered_pdf, 1)
        parsed = json.loads(result)
        text_blocks = [b for b in parsed if b["type"] == "text"]
        normal = [b for b in text_blocks if "Normal paragraph" in b["text"]]
        assert len(normal) > 0, "Should find the normal paragraph"
        assert normal[0].get("has_border") is None

    def test_bordered_verbose_includes_border_details(self, bordered_pdf):
        result = get_page_blocks(bordered_pdf, 1, verbose=True)
        parsed = json.loads(result)
        text_blocks = [b for b in parsed if b["type"] == "text"]
        framed = [b for b in text_blocks if "Framed Title" in b["text"]]
        assert len(framed) > 0
        assert framed[0].get("has_border") is True
        assert framed[0].get("border_color") is not None
        assert framed[0].get("border_width") is not None
        assert framed[0].get("border_width") > 0


# ─── Test 4: get_page_as_image ───────────────────────────────────────────────

class TestGetPageAsImage:
    def test_renders_png(self, test_pdf, temp_dir):
        result = get_page_as_image(test_pdf, 1, temp_dir)
        assert "image_data" in result
        assert result["image_data"].startswith("data:image/png;base64,")
        assert result["width"] > 0
        assert result["height"] > 0
        assert result["file_size"] > 0

    def test_custom_dpi(self, test_pdf, temp_dir):
        result = get_page_as_image(test_pdf, 1, temp_dir, dpi=300)
        assert result["image_data"].startswith("data:image/png;base64,")
        assert result["file_size"] > 0

    def test_invalid_page(self, test_pdf, temp_dir):
        with pytest.raises(ValueError):
            get_page_as_image(test_pdf, 999, temp_dir)


# ─── Test 5: run_pdfimages ───────────────────────────────────────────────────

class TestRunPdfimages:
    def test_runs_or_returns_error(self, test_pdf, temp_dir):
        """pdfimages may not be installed; test it either runs or gives a helpful error."""
        result = run_pdfimages(test_pdf, temp_dir, prefix="img")
        if "error" in result and "pdfimages not found" in result["error"]:
            # pdfimages not installed — acceptable
            assert result["files"] == []
        else:
            # pdfimages ran successfully or with some other error
            assert "files" in result
            assert isinstance(result["files"], list)


# ─── Test 6: extract_page_images ─────────────────────────────────────────────

class TestExtractPageImages:
    def test_empty_result_for_text_pdf(self, test_pdf, temp_dir):
        """Our test PDF has no embedded images, so this returns empty."""
        result = extract_page_images(test_pdf, 1, temp_dir)
        assert result["page"] == 1
        assert isinstance(result["count"], int)
        assert isinstance(result["images"], list)
        assert result["directory"] == temp_dir

    def test_invalid_page_number(self, test_pdf, temp_dir):
        with pytest.raises(ValueError):
            extract_page_images(test_pdf, 999, temp_dir)


# ─── Test 7: view_image ──────────────────────────────────────────────────────

class TestViewImage:
    def test_returns_base64_data_url(self, test_image):
        result = view_image(test_image)
        assert "data:image/png;base64," in result
        assert os.path.basename(test_image) in result

    def test_file_not_found(self):
        result = view_image("/nonexistent/file.png")
        assert "Error" in result
        assert "not found" in result

    def test_includes_file_size(self, test_image):
        result = view_image(test_image)
        assert "bytes" in result


# ─── Test 8: read_file ───────────────────────────────────────────────────────

class TestReadFile:
    def test_reads_text_file(self, temp_dir):
        path = os.path.join(temp_dir, "test.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Hello world\n中文测试\n")
        content = read_file(path)
        assert "Hello world" in content
        assert "中文测试" in content

    def test_file_not_found(self):
        result = read_file("/nonexistent/file.txt")
        assert "Error" in result
        assert "not found" in result

    def test_binary_file_handling(self, test_image):
        """Should handle binary files gracefully."""
        result = read_file(test_image)
        # Either reads something or returns an error message
        assert isinstance(result, str)


# ─── Test 9: write_tex_file ──────────────────────────────────────────────────

class TestWriteTexFile:
    def test_writes_content(self, temp_dir):
        path = os.path.join(temp_dir, "test.tex")
        content = r"\documentclass{article}\begin{document}Hello\end{document}"
        result = write_tex_file(path, content)
        assert "Successfully wrote" in result
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == content

    def test_creates_intermediate_dirs(self, temp_dir):
        path = os.path.join(temp_dir, "sub", "dir", "test.tex")
        content = r"\documentclass{article}\begin{document}Test\end{document}"
        result = write_tex_file(path, content)
        assert "Successfully wrote" in result
        assert os.path.isfile(path)

    def test_overwrites_existing(self, temp_dir):
        path = os.path.join(temp_dir, "test.tex")
        write_tex_file(path, r"\documentclass{article}\begin{document}Old\end{document}")
        write_tex_file(path, r"\documentclass{article}\begin{document}New\end{document}")
        content = read_tex_file(path)
        assert "New" in content
        assert "Old" not in content


# ─── Test 10: read_tex_file ──────────────────────────────────────────────────

class TestReadTexFile:
    def test_reads_tex(self, temp_dir):
        path = os.path.join(temp_dir, "test.tex")
        expected = r"\documentclass{article}\begin{document}Test\end{document}"
        write_tex_file(path, expected)
        content = read_tex_file(path)
        assert content == expected

    def test_file_not_found(self):
        result = read_tex_file("/nonexistent/file.tex")
        assert "Error" in result
        assert "not found" in result


# ─── Test 11: run_command ────────────────────────────────────────────────────

class TestRunCommand:
    def test_simple_command(self):
        if os.name == "nt":
            result = run_command("echo Hello")
        else:
            result = run_command("echo Hello")
        assert result["returncode"] == 0
        # stdout may include quotes depending on shell
        assert "Hello" in result["stdout"]

    def test_command_not_found(self):
        result = run_command("nonexistent_command_xyz123")
        assert result["returncode"] != 0

    def test_timeout(self):
        if os.name == "nt":
            cmd = "ping -n 10 127.0.0.1"
        else:
            cmd = "sleep 10"
        result = run_command(cmd, timeout=1)
        assert "timed out" in result["stderr"].lower()

    def test_working_directory_available(self):
        """Verify the command runs in CWD; list current directory."""
        result = run_command("pwd" if os.name != "nt" else "cd")
        assert result["returncode"] == 0


# ─── Test 12: compile_tex_to_pdf ─────────────────────────────────────────────

class TestCompileTexToPdf:
    @pytest.mark.skipif(not HAS_TECTONIC, reason="Tectonic binary not available")
    def test_compile_success(self, temp_dir):
        tex_path = os.path.join(temp_dir, "test.tex")
        content = (
            r"\documentclass[12pt]{article}" + "\n"
            r"\usepackage{fontspec}" + "\n"
            r"\begin{document}" + "\n"
            r"Hello from agent tool!" + "\n"
            r"\end{document}" + "\n"
        )
        write_tex_file(tex_path, content)
        result = compile_tex_to_pdf(tex_path, temp_dir, DATA_DIR)
        assert result["success"], f"Compilation failed:\n{result['error']}"
        assert result["pdf_path"]
        assert os.path.isfile(result["pdf_path"])

    @pytest.mark.skipif(not HAS_TECTONIC, reason="Tectonic binary not available")
    def test_compile_with_cjk(self, temp_dir):
        from src.utils.font_utils import get_cjk_font_filename_for_lang
        font = get_cjk_font_filename_for_lang("Chinese")
        tex_path = os.path.join(temp_dir, "test_cjk.tex")
        content = (
            f"\\documentclass[12pt]{{article}}\n"
            f"\\usepackage{{fontspec}}\n"
            f"\\usepackage{{xeCJK}}\n"
            f"\\setCJKmainfont{{{font}}}\n"
            f"\\begin{{document}}\n"
            f"中文翻译测试\n"
            f"\\end{{document}}\n"
        )
        write_tex_file(tex_path, content)
        result = compile_tex_to_pdf(tex_path, temp_dir, DATA_DIR)
        assert result["success"], f"CJK compilation failed:\n{result['error']}"
        assert os.path.isfile(result["pdf_path"])


# ─── Test 13: get_font_info ──────────────────────────────────────────────────

class TestGetFontInfo:
    def test_chinese_font_info(self):
        info = get_font_info("chinese")
        assert info["needs_cjk"] is True
        assert info["font_filename"]
        assert info["font_family"]

    def test_english_font_info(self):
        info = get_font_info("english")
        assert info["needs_cjk"] is False
        assert info["font_filename"] == ""

    def test_japanese_font_info(self):
        info = get_font_info("japanese")
        assert info["needs_cjk"] is True

    def test_korean_font_info(self):
        info = get_font_info("korean")
        assert info["needs_cjk"] is True

    def test_cjk_note_contains_setup(self):
        info = get_font_info("chinese")
        assert "\\setCJKmainfont" in info["note"]

    def test_non_cjk_note(self):
        info = get_font_info("english")
        assert "No CJK font needed" in info["note"]


# ─── Test 14: list_directory ─────────────────────────────────────────────────

class TestListDirectory:
    def test_lists_entries(self, temp_dir):
        # Create some files
        for name in ("a.txt", "b.txt"):
            with open(os.path.join(temp_dir, name), "w") as f:
                f.write("test")
        result = list_directory(temp_dir)
        parsed = json.loads(result)
        assert len(parsed) >= 2
        names = [e["name"] for e in parsed]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_entry_has_metadata(self, temp_dir):
        with open(os.path.join(temp_dir, "test.txt"), "w") as f:
            f.write("test")
        result = json.loads(list_directory(temp_dir))
        entry = result[0]
        assert "name" in entry
        assert "size" in entry
        assert "is_dir" in entry
        assert "modified" in entry

    def test_directory_not_found(self):
        result = list_directory("/nonexistent/dir")
        assert "Error" in result
        assert "not found" in result

    def test_empty_directory(self, temp_dir):
        result = json.loads(list_directory(temp_dir))
        assert result == []


# ─── Test 15: translation_complete ───────────────────────────────────────────

class TestTranslationComplete:
    def test_complete_with_valid_pdf(self, temp_dir):
        pdf_path = os.path.join(temp_dir, "output.pdf")
        with open(pdf_path, "w") as f:
            f.write("fake pdf content")
        result = translation_complete(pdf_path, "Translated 10 pages to Chinese.")
        assert result["completed"] is True
        assert result["output_pdf_path"] == pdf_path
        assert "10 pages" in result["summary"]

    def test_complete_missing_pdf(self, temp_dir):
        pdf_path = os.path.join(temp_dir, "nonexistent.pdf")
        result = translation_complete(pdf_path, "N/A")
        assert result["completed"] is False
        assert "not found" in result["error"]


# ─── Test dispatcher ─────────────────────────────────────────────────────────

class TestToolFunctionsDispatch:
    def test_all_tools_registered(self):
        """Verify TOOL_FUNCTIONS dict has all 15 tools."""
        expected_tools = {
            "get_pdf_info", "get_page_text", "get_page_blocks",
            "get_page_as_image", "run_pdfimages", "extract_page_images",
            "view_image", "read_file", "write_tex_file", "read_tex_file",
            "run_command", "compile_tex_to_pdf", "get_font_info",
            "list_directory", "translation_complete",
        }
        assert set(TOOL_FUNCTIONS.keys()) == expected_tools

    def test_all_tools_are_callable(self):
        for name, fn in TOOL_FUNCTIONS.items():
            assert callable(fn), f"Tool {name} is not callable"
