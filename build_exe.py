"""Build AI PDF Trans into a standalone Windows exe via PyInstaller.

Usage:
    python build_exe.py

The resulting exe is self-contained — no Python, no pip, no dependencies needed.
Just copy dist/AI_PDF_Trans.exe to any Windows 10/11 machine and run.
"""

import os
import shutil
import sys


def build():
    from flet_cli.__pyinstaller.utils import copy_flet_bin
    import PyInstaller.__main__

    temp_dir = copy_flet_bin()
    print(f"Flet client prepared at: {temp_dir}")

    args = [
        "--noconfirm", "--noconsole", "--onefile",
        "--name", "AI_PDF_Trans",
        "--distpath", "dist",
        f"--add-data=data/fonts{os.pathsep}data/fonts",
        f"--add-data=data/bin/tectonic.exe{os.pathsep}data/bin",
        f"--add-data=data/bin/pdfimages.exe{os.pathsep}data/bin",
        "--collect-data", "litellm",
        "--collect-submodules", "litellm",
    ]

    # All flet client files (Flutter engine, DLLs, assets)
    for root, _dirs, files in os.walk(temp_dir):
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, os.path.dirname(temp_dir))
            args.append(f"--add-data={src}{os.pathsep}{rel}")

    # Hidden imports for dynamically-loaded modules
    hidden = [
        "litellm", "litellm.llms.openai", "litellm.llms.anthropic",
        "litellm.main", "litellm.utils", "litellm.litellm_core_utils",
        "litellm.litellm_core_utils.litellm_logging",
        "fitz", "PIL", "PIL.Image", "tenacity",
        "cryptography", "cryptography.fernet",
        "concurrent.futures", "asyncio",
        "fastapi", "uvicorn", "starlette", "websockets", "python_multipart",
        "src", "src.server", "src.server.server", "src.server.task_manager",
        "src.server.network",
    ]
    for mod in hidden:
        args.append(f"--hidden-import={mod}")

    # Exclude large packages not used by this app
    excludes = [
        "torch", "torchvision", "numpy", "scipy", "pandas",
        "matplotlib", "sklearn", "onnxruntime", "cv2",
        "tensorflow", "jax", "jaxlib", "sympy", "numba",
    ]
    for mod in excludes:
        args.append(f"--exclude-module={mod}")

    args.append("main.py")

    # Clean previous build
    for d in ["build", "dist"]:
        if os.path.isdir(d):
            shutil.rmtree(d)

    print(f"Building with {len(args)} args...")
    PyInstaller.__main__.run(args)

    # Cleanup temp flet client
    shutil.rmtree(temp_dir, ignore_errors=True)

    exe_path = os.path.join("dist", "AI_PDF_Trans.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\nDone!  {exe_path}  ({size_mb:.0f} MB)")
    else:
        print("\nERROR: Build failed — no exe found.")
        sys.exit(1)


if __name__ == "__main__":
    build()
