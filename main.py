"""AI PDF Translator — AI-powered PDF translation preserving layout and math.

Usage:
    python main.py
"""

import logging
import multiprocessing
import msvcrt
import os

import flet as ft

from src.app import AIPDFTransApp

_app_instance = None
_lock_handle = None


def _acquire_lock(data_dir: str) -> bool:
    """Try to acquire a singleton file lock. Returns True if this is the only instance."""
    global _lock_handle
    lock_path = os.path.join(data_dir, "app.lock")
    try:
        _lock_handle = open(lock_path, 'w')
        msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except (IOError, OSError):
        return False


def main(page: ft.Page):
    global _app_instance
    data_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "AI_PDF_Trans",
    )
    os.makedirs(data_dir, exist_ok=True)

    if _app_instance is None:
        _app_instance = AIPDFTransApp(data_dir)
    _app_instance.run(page)


def run():
    multiprocessing.freeze_support()

    # Enable Flet transport-level debug logging for diagnostics
    logging.getLogger("flet").setLevel(logging.DEBUG)

    data_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "AI_PDF_Trans",
    )
    os.makedirs(data_dir, exist_ok=True)
    if not _acquire_lock(data_dir):
        return

    ft.app(target=main, name="AI PDF Trans")


if __name__ == "__main__":
    run()
