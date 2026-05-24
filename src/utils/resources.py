"""Bundled resource resolution for PyInstaller frozen executables.

When running as a PyInstaller exe, sys._MEIPASS points to the temporary
extraction directory where bundled data files live.  When running from
source, the project root is used instead.
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True if running as a PyInstaller-bundled executable."""
    return getattr(sys, "frozen", False)


def get_project_root() -> str:
    """Return the project root directory.

    - Frozen exe: sys._MEIPASS (PyInstaller extraction dir)
    - Source: 3 levels up from this file (src/utils/resources.py → project root)
    """
    if is_frozen():
        return sys._MEIPASS
    return str(Path(__file__).resolve().parent.parent.parent)


def get_bundled_data_dir() -> str:
    """Return the bundled data/ directory path."""
    return os.path.join(get_project_root(), "data")


def ensure_data_dir_resources(data_dir: str) -> None:
    """Copy bundled resources (tectonic, fonts) into the runtime data_dir.

    Called once at app startup.  The runtime data_dir is typically
    %LOCALAPPDATA%/AI_PDF_Trans — this is where config, logs, fontconfig
    and cached binaries live.
    """
    bundled = get_bundled_data_dir()

    # ── Tectonic ──────────────────────────────────────────────────────
    src_tectonic = os.path.join(bundled, "bin", "tectonic.exe")
    dst_tectonic = os.path.join(data_dir, "bin", "tectonic.exe")
    if os.path.isfile(src_tectonic) and not os.path.isfile(dst_tectonic):
        os.makedirs(os.path.dirname(dst_tectonic), exist_ok=True)
        import shutil
        shutil.copy2(src_tectonic, dst_tectonic)

    # ── Fonts ─────────────────────────────────────────────────────────
    src_fonts_dir = os.path.join(bundled, "fonts")
    dst_fonts_dir = os.path.join(data_dir, "fonts")
    if os.path.isdir(src_fonts_dir):
        os.makedirs(dst_fonts_dir, exist_ok=True)
        import shutil
        for name in os.listdir(src_fonts_dir):
            src = os.path.join(src_fonts_dir, name)
            dst = os.path.join(dst_fonts_dir, name)
            if os.path.isfile(src) and not os.path.isfile(dst):
                shutil.copy2(src, dst)
