"""Tests for TeX compilation: fontconfig, font utilities, and Tectonic integration."""

import os
import tempfile

import pytest

from src.core.tex_compiler import TexCompiler
from src.utils.file_utils import get_tectonic_path
from src.utils.font_utils import (
    ensure_fonts_available,
    get_cjk_font_for_lang,
    get_cjk_font_file_for_lang,
    get_cjk_font_filename_for_lang,
    needs_cjk_package,
    escape_latex,
    detect_cjk,
    get_latex_font_command,
)
from tests.conftest import DATA_DIR, HAS_TECTONIC


# ─── Fontconfig tests ────────────────────────────────────────────────────────

class TestFontconfig:
    def test_fontconfig_paths_use_forward_slashes(self):
        compiler = TexCompiler(DATA_DIR)
        config_dir = compiler._ensure_fontconfig()
        config_path = os.path.join(config_dir, "fonts.conf")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "\\" not in content, f"fonts.conf contains backslashes:\n{content}"
        assert "C:/Windows/Fonts" in content or "C:/WINDOWS/Fonts" in content

    def test_fontconfig_file_is_valid_xml(self):
        compiler = TexCompiler(DATA_DIR)
        config_dir = compiler._ensure_fontconfig()
        config_path = os.path.join(config_dir, "fonts.conf")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '<?xml version="1.0"?>' in content
        assert "<fontconfig>" in content
        assert "</fontconfig>" in content

    def test_compile_copies_fonts_to_tex_dir(self):
        """Verify that compile() copies CJK fonts to the TeX file directory."""
        font_filename = get_cjk_font_filename_for_lang("Chinese")
        tex_content = f"""\\documentclass[12pt]{{article}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setCJKmainfont{{{font_filename}}}
\\begin{{document}}
Test
\\end{{document}}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "test.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex_content)
            compiler = TexCompiler(DATA_DIR)
            result = compiler.compile(tex_path, tmpdir)
            assert result.success, f"Compilation failed:\n{result.error}"
            assert os.path.isfile(os.path.join(tmpdir, font_filename))

    def test_cjk_font_candidates_resolve_to_existing_fonts(self):
        for lang in ("Chinese", "Japanese", "Korean"):
            font_name = get_cjk_font_for_lang(lang)
            font_file = get_cjk_font_file_for_lang(lang)
            assert font_name
            assert font_file
            assert "\\" not in font_file
            assert os.path.isfile(font_file), f"missing font file for {lang}: {font_file}"

    def test_chinese_body_font_not_simsun_extg(self):
        font_filename = get_cjk_font_filename_for_lang("Chinese")
        assert font_filename.lower() != "simsunextg.ttf"

    def test_ensure_fonts_available_copies_primary_chinese_font(self):
        font_filename = get_cjk_font_filename_for_lang("Chinese")
        with tempfile.TemporaryDirectory() as tmpdir:
            fonts_dir = ensure_fonts_available(tmpdir)
            assert os.path.isfile(os.path.join(fonts_dir, font_filename))


# ─── Font utility unit tests ─────────────────────────────────────────────────

class TestFontUtils:
    def test_needs_cjk_package_chinese(self):
        assert needs_cjk_package("Chinese") is True
        assert needs_cjk_package("chinese") is True

    def test_needs_cjk_package_japanese(self):
        assert needs_cjk_package("Japanese") is True

    def test_needs_cjk_package_korean(self):
        assert needs_cjk_package("Korean") is True

    def test_needs_cjk_package_english(self):
        assert needs_cjk_package("English") is False

    def test_detect_cjk_chinese(self):
        assert detect_cjk("中文测试") is True

    def test_detect_cjk_english(self):
        assert detect_cjk("Hello world") is False

    def test_detect_cjk_mixed(self):
        assert detect_cjk("Hello 中文 test") is True

    def test_detect_cjk_japanese(self):
        assert detect_cjk("こんにちは") is True

    def test_detect_cjk_korean(self):
        assert detect_cjk("안녕하세요") is True

    def test_latex_font_command_sizes(self):
        assert get_latex_font_command("SomeFont", 5) == "\\tiny"
        assert get_latex_font_command("SomeFont", 9) == "\\footnotesize"
        assert get_latex_font_command("SomeFont", 11) == "\\normalsize"
        assert get_latex_font_command("SomeFont", 15) == "\\Large"
        assert get_latex_font_command("SomeFont", 22) == "\\huge"
        assert get_latex_font_command("SomeFont", 30) == "\\Huge"

    def test_escape_latex_preserves_math(self):
        text = r"x $y = z$ &"
        result = escape_latex(text)
        assert "\\&" in result
        assert "$y = z$" in result  # math mode preserved

    def test_escape_latex_no_math(self):
        text = "100% of &text{here}"
        result = escape_latex(text)
        assert "\\%" in result
        assert "\\&" in result


# ─── Tectonic compilation tests (need binary) ────────────────────────────────

@pytest.mark.skipif(not HAS_TECTONIC, reason="Tectonic binary not available")
class TestTectonicCompilation:
    def test_compile_simple_english_tex(self):
        tex_content = r"""\documentclass[12pt]{article}
\usepackage{fontspec}
\begin{document}
Hello, world! This is a test.
\end{document}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "test.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex_content)
            compiler = TexCompiler(DATA_DIR)
            result = compiler.compile(tex_path, tmpdir)
            assert result.success, f"Compilation failed:\n{result.error}"
            assert os.path.isfile(result.pdf_path)
            assert os.path.getsize(result.pdf_path) > 0

    def test_compile_cjk_tex(self):
        font_filename = get_cjk_font_filename_for_lang("Chinese")
        tex_content = f"""\\documentclass[12pt]{{article}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setCJKmainfont{{{font_filename}}}
\\begin{{document}}
Hello, world!
\\end{{document}}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "test.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex_content)
            compiler = TexCompiler(DATA_DIR)
            result = compiler.compile(tex_path, tmpdir)
            assert result.success, f"CJK compilation failed:\n{result.error}"
            assert os.path.isfile(result.pdf_path)
            assert os.path.getsize(result.pdf_path) > 0

    def test_compile_cjk_uses_project_fonts(self):
        """Verify CJK compilation works with project-local fonts."""
        font_filename = get_cjk_font_filename_for_lang("Chinese")
        tex_content = f"""\\documentclass[12pt]{{article}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setCJKmainfont{{{font_filename}}}
\\begin{{document}}
Hello, world! This tests project-local font resolution.
\\end{{document}}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "test.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex_content)
            compiler = TexCompiler(DATA_DIR)
            result = compiler.compile(tex_path, tmpdir)
            assert result.success, f"Project-font CJK compilation failed:\n{result.error}"
            assert os.path.isfile(result.pdf_path)

    def test_compile_tex_with_latex_math_commands(self):
        tex_content = r"""\documentclass[12pt]{article}
\usepackage{fontspec}
\usepackage{amsmath,amssymb}
\begin{document}
If $x \in S$ and $\rho \geq 0$, then $\alpha \to \beta$.
\end{document}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "test.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex_content)
            compiler = TexCompiler(DATA_DIR)
            result = compiler.compile(tex_path, tmpdir)
            assert result.success, f"Math compilation failed:\n{result.error}"
            assert os.path.isfile(result.pdf_path)
            assert os.path.getsize(result.pdf_path) > 0

    def test_compile_cjk_with_math(self):
        font_filename = get_cjk_font_filename_for_lang("Chinese")
        tex_content = f"""\\documentclass[12pt]{{article}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\usepackage{{amsmath,amssymb}}
\\setCJKmainfont{{{font_filename}}}
\\begin{{document}}
数学模型 数据 函数

If $x \\in S$ and $\\rho \\geq 0$.
\\end{{document}}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "test.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex_content)
            compiler = TexCompiler(DATA_DIR)
            result = compiler.compile(tex_path, tmpdir)
            assert result.success, f"CJK+Math compilation failed:\n{result.error}"
            assert os.path.isfile(result.pdf_path)
            assert os.path.getsize(result.pdf_path) > 0
            assert "Missing character" not in result.error
