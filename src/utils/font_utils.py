"""Font detection, mapping, and LaTeX package requirements."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from src.models.config import CJK_LANGUAGES

_WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")
_FONT_CANDIDATES = {
    "chinese": [
        ("simsun.ttc", "SimSun"),
        ("msyh.ttc", "Microsoft YaHei"),
        ("simhei.ttf", "SimHei"),
        ("msyhbd.ttc", "Microsoft YaHei"),
        ("simsunb.ttf", "SimSun"),
        ("SimsunExtG.ttf", "SimSun-ExtG"),
    ],
    "japanese": [
        ("msgothic.ttc", "MS Gothic"),
        ("meiryo.ttc", "Meiryo"),
        ("YuMincho.ttc", "Yu Mincho"),
    ],
    "korean": [
        ("malgun.ttf", "Malgun Gothic"),
        ("batang.ttc", "Batang"),
    ],
}


def detect_cjk(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0x3040 <= cp <= 0x309F
            or 0x30A0 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xD7AF
            or 0xF900 <= cp <= 0xFAFF
        ):
            return True
    return False


def _normalize_lang(target_lang: str) -> str:
    lang = target_lang.lower()
    if lang in CJK_LANGUAGES:
        return lang
    return "chinese"


def _first_existing_font(lang: str) -> tuple[str, str]:
    for filename, family in _FONT_CANDIDATES.get(lang, []):
        path = _WINDOWS_FONTS_DIR / filename
        if path.exists():
            return family, str(path).replace("\\", "/")
    fallback_file, fallback_family = _FONT_CANDIDATES["chinese"][0]
    return fallback_family, str((_WINDOWS_FONTS_DIR / fallback_file)).replace("\\", "/")


def ensure_fonts_available(data_dir: str) -> str:
    """Copy required CJK fonts to project-local fonts directory.

    Tries (in order):
    1. System fonts directory (C:/Windows/Fonts)
    2. Bundled fonts (PyInstaller exe)

    Returns the path to the project-local fonts directory.
    """
    project_fonts_dir = os.path.join(data_dir, "fonts")
    os.makedirs(project_fonts_dir, exist_ok=True)

    # Check bundled fonts first (for frozen exe)
    try:
        from src.utils.resources import get_bundled_data_dir, is_frozen
        bundled_fonts_dir = os.path.join(get_bundled_data_dir(), "fonts")
        if is_frozen() and os.path.isdir(bundled_fonts_dir):
            for name in os.listdir(bundled_fonts_dir):
                src = os.path.join(bundled_fonts_dir, name)
                dst = os.path.join(project_fonts_dir, name)
                if os.path.isfile(src) and not os.path.isfile(dst):
                    shutil.copy2(src, dst)
    except ImportError:
        pass

    # Fall back to system fonts
    for lang, candidates in _FONT_CANDIDATES.items():
        for filename, family in candidates:
            src = _WINDOWS_FONTS_DIR / filename
            if src.exists():
                dst = os.path.join(project_fonts_dir, filename)
                if not os.path.isfile(dst) or src.stat().st_mtime > os.path.getmtime(dst):
                    shutil.copy2(str(src), dst)
                break

    return project_fonts_dir


def get_cjk_font_for_lang(target_lang: str) -> str:
    return _first_existing_font(_normalize_lang(target_lang))[0]


def get_cjk_font_filename_for_lang(target_lang: str) -> str:
    """Return font filename (e.g., 'simsun.ttc') for use with fontspec Path option."""
    lang = _normalize_lang(target_lang)
    for filename, family in _FONT_CANDIDATES.get(lang, []):
        path = _WINDOWS_FONTS_DIR / filename
        if path.exists():
            return filename
    return _FONT_CANDIDATES["chinese"][0][0]


def get_cjk_font_stem_ext_for_lang(target_lang: str) -> tuple[str, str]:
    """Return (stem, extension) for the CJK font file, e.g. ('simsun', '.ttc')."""
    filename = get_cjk_font_filename_for_lang(target_lang)
    p = Path(filename)
    return p.stem, p.suffix


def get_cjk_font_file_for_lang(target_lang: str) -> str:
    """Return full font file path for Tectonic (fontconfig) compatibility."""
    return _first_existing_font(_normalize_lang(target_lang))[1]


def needs_cjk_package(target_lang: str) -> bool:
    return target_lang.lower() in CJK_LANGUAGES


def get_latex_font_command(font_name: str, font_size: float) -> str:
    size_map = {
        (0, 6): "\\tiny",
        (6, 8): "\\scriptsize",
        (8, 10): "\\footnotesize",
        (10, 11): "\\small",
        (11, 12): "\\normalsize",
        (12, 14): "\\large",
        (14, 17): "\\Large",
        (17, 20): "\\LARGE",
        (20, 25): "\\huge",
        (25, float("inf")): "\\Huge",
    }
    cmd = "\\normalsize"
    for (lo, hi), s_cmd in size_map.items():
        if lo <= font_size < hi:
            cmd = s_cmd
            break
    return cmd


def get_required_packages(target_lang: str, has_equations: bool, has_images: bool, has_tables: bool) -> list[str]:
    packages = ["inputenc", "fontenc", "graphicx", "hyperref"]
    if has_equations:
        packages.extend(["amsmath", "amssymb", "amsfonts"])
    if has_tables:
        packages.append("booktabs")
    if needs_cjk_package(target_lang):
        packages.append("xeCJK")
    return packages


def escape_latex(text: str) -> str:
    """Escape special LaTeX characters in text, preserving math mode."""
    parts = re.split(r'(\$\$.*?\$\$|\$.*?\$|\\\[.*?\\\]|\\\(.*?\\\))', text, flags=re.DOTALL)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
        else:
            for ch in ["\\", "{", "}", "#", "$", "%", "&", "~", "^"]:
                if ch == "\\":
                    part = part.replace("\\", "\\textbackslash{}")
                elif ch == "~":
                    part = part.replace("~", "\\textasciitilde{}")
                elif ch == "^":
                    part = part.replace("^", "\\textasciicircum{}")
                else:
                    part = part.replace(ch, f"\\{ch}")
            result.append(part)
    return "".join(result)
