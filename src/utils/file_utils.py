"""Temporary file management and Tectonic binary management."""

import os
import platform
import shutil
import tempfile
import time
import zipfile
import tarfile
from pathlib import Path
from typing import Callable, Optional

import urllib.request

TECTONIC_VERSION = "0.16.9"
USER_AGENT = "AI-PDF-Trans/1.0"


def _download_with_retry(url: str, dest: str, callback: Optional[Callable] = None,
                         max_retries: int = 3, timeout: int = 30) -> None:
    headers = {"User-Agent": USER_AGENT}
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if callback and total > 0:
                            pct = int(downloaded * 100 / total)
                            callback("downloading", pct, f"Downloading... {pct}%")
            return
        except Exception as e:
            last_err = e
            if os.path.exists(dest):
                os.remove(dest)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last_err


def create_temp_dir(prefix: str = "ai_pdf_trans_") -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    return path


def cleanup_temp_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def get_tectonic_path(data_dir: str) -> Optional[str]:
    exe_name = "tectonic.exe" if platform.system() == "Windows" else "tectonic"
    # Check runtime data_dir first (may have been copied from bundle)
    path = os.path.join(data_dir, "bin", exe_name)
    if os.path.isfile(path):
        return path
    # Check bundled resources (PyInstaller frozen mode)
    try:
        from src.utils.resources import get_bundled_data_dir, is_frozen
        if is_frozen():
            bundled_path = os.path.join(get_bundled_data_dir(), "bin", exe_name)
            if os.path.isfile(bundled_path):
                return bundled_path
    except ImportError:
        pass
    return None


def ensure_tectonic(data_dir: str, progress_callback: Optional[Callable] = None) -> str:
    existing = get_tectonic_path(data_dir)
    if existing:
        return existing
    return download_tectonic(data_dir, progress_callback)


def download_tectonic(data_dir: str, progress_callback: Optional[Callable] = None) -> str:
    bin_dir = os.path.join(data_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)

    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        suffix = "x86_64-pc-windows-msvc"
        exe_name = "tectonic.exe"
        ext = "zip"
    elif system == "Darwin":
        suffix = "x86_64-apple-darwin" if "x86" in machine or "amd64" in machine else "aarch64-apple-darwin"
        exe_name = "tectonic"
        ext = "tar.gz"
    else:
        suffix = "x86_64-unknown-linux-gnu"
        exe_name = "tectonic"
        ext = "tar.gz"

    url = f"https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40{TECTONIC_VERSION}/tectonic-{TECTONIC_VERSION}-{suffix}.{ext}"

    if progress_callback:
        progress_callback("downloading", 0, "Downloading Tectonic...")

    archive_path = os.path.join(bin_dir, f"tectonic-{suffix}.{ext}")

    try:
        _download_with_retry(url, archive_path, progress_callback)
    except Exception as e:
        raise RuntimeError(f"Failed to download Tectonic: {e}")

    if progress_callback:
        progress_callback("extracting", 90, "Extracting Tectonic...")

    if ext == "zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(exe_name):
                    zf.extract(name, bin_dir)
                    extracted = os.path.join(bin_dir, name)
                    final = os.path.join(bin_dir, exe_name)
                    if extracted != final:
                        shutil.move(extracted, final)
                    break
    else:
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(exe_name):
                    member.name = exe_name
                    tar.extract(member, bin_dir)
                    break

    if os.path.exists(archive_path):
        os.remove(archive_path)

    exe_path = os.path.join(bin_dir, exe_name)
    if system != "Windows":
        os.chmod(exe_path, 0o755)

    if progress_callback:
        progress_callback("done", 100, "Tectonic installed successfully.")

    return exe_path


def download_model(data_dir: str, progress_callback: Optional[Callable] = None) -> str:
    model_dir = os.path.join(data_dir, "models")
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "doclayout_yolo_docstructbench_imgsz1024.onnx")

    if os.path.isfile(model_path):
        return model_path

    model_file = "doclayout_yolo_docstructbench_imgsz1024.onnx"
    urls = [
        f"https://hf-mirror.com/wybxc/DocLayout-YOLO-DocStructBench-onnx/resolve/main/{model_file}",
        f"https://huggingface.co/wybxc/DocLayout-YOLO-DocStructBench-onnx/resolve/main/{model_file}",
    ]

    if progress_callback:
        progress_callback("downloading", 0, "Downloading DocLayout-YOLO model...")

    last_err = None
    for url in urls:
        try:
            _download_with_retry(url, model_path, progress_callback)
            if progress_callback:
                progress_callback("done", 100, "Model downloaded successfully.")
            return model_path
        except Exception as e:
            last_err = e
            if os.path.exists(model_path):
                os.remove(model_path)
            if progress_callback:
                progress_callback("retrying", 0, "Mirror failed, trying next...")

    raise RuntimeError(f"Failed to download model: {last_err}")


def get_model_path(data_dir: str) -> Optional[str]:
    model_path = os.path.join(data_dir, "models", "doclayout_yolo_docstructbench_imgsz1024.onnx")
    if os.path.isfile(model_path):
        return model_path
    return None


def check_tesseract() -> bool:
    import subprocess
    try:
        result = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
