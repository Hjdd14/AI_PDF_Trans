"""LaTeX compilation using Tectonic."""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.file_utils import ensure_tectonic, get_tectonic_path
from src.utils.font_utils import ensure_fonts_available
from src.utils.logger import get_logger

TEX_TEMP_EXTENSIONS = [
    ".aux", ".log", ".out", ".synctex.gz", ".toc",
    ".fls", ".fdb_latexmk", ".bbl", ".blg",
    ".nav", ".snm", ".vrb", ".xdv",
]


class CompileResult:
    def __init__(
        self,
        success: bool,
        pdf_path: str = "",
        error: str = "",
        stdout: str = "",
        stderr: str = "",
        log_path: str = "",
        diagnostics_dir: str = "",
    ):
        self.success = success
        self.pdf_path = pdf_path
        self.error = error
        self.stdout = stdout
        self.stderr = stderr
        self.log_path = log_path
        self.diagnostics_dir = diagnostics_dir


class TexCompiler:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.log = get_logger()

    def _ensure_fontconfig(self, font_dirs: list[str] | None = None) -> str:
        """Create a fontconfig config pointing to the given font directories.

        If font_dirs is None, falls back to system font directories.
        Also includes Tectonic's bundled font directory for Latin Modern fonts.
        """
        config_dir = os.path.join(self.data_dir, "fontconfig")
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "fonts.conf")

        if font_dirs is None:
            font_dir = (os.environ.get("WINDIR", "C:/Windows") + "/Fonts").replace("\\", "/")
            user_font_dir = os.path.join(
                os.path.expanduser("~"), "AppData", "Local", "Microsoft", "Windows", "Fonts"
            ).replace("\\", "/")
            font_dirs = [font_dir, user_font_dir]

        # Include Tectonic's bundled fonts (Latin Modern, etc.)
        tectonic_bundle_dir = self._find_tectonic_bundle_fonts()
        if tectonic_bundle_dir and tectonic_bundle_dir not in font_dirs:
            font_dirs.append(tectonic_bundle_dir)

        dir_entries = "\n".join(f'  <dir>{d.replace(chr(92), "/")}</dir>' for d in font_dirs)
        conf = (
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            '<fontconfig>\n'
            f'{dir_entries}\n'
            '</fontconfig>\n'
        )
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(conf)
        self.log.info(f"Created fontconfig at {config_path}")
        return config_dir

    def _find_tectonic_bundle_fonts(self) -> str | None:
        """Find Tectonic's bundled font directory containing Latin Modern fonts."""
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            return None
        bundle_data_dir = os.path.join(local_app_data, "TectonicProject", "Tectonic", "bundles", "data")
        if not os.path.isdir(bundle_data_dir):
            return None
        # Find the hash-named subdirectory containing the fonts
        for entry in os.listdir(bundle_data_dir):
            entry_path = os.path.join(bundle_data_dir, entry)
            if os.path.isdir(entry_path) and os.path.isfile(os.path.join(entry_path, "lmroman12-regular.otf")):
                return entry_path.replace("\\", "/")
        return None

    def get_tectonic(self) -> str:
        path = get_tectonic_path(self.data_dir)
        if path:
            return path
        return ensure_tectonic(self.data_dir)

    def _diagnostics_root(self) -> str:
        path = os.path.join(self.data_dir, "diagnostics")
        os.makedirs(path, exist_ok=True)
        return path

    def _create_diagnostics_dir(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(self._diagnostics_root(), f"tectonic_failure_{timestamp}")
        os.makedirs(path, exist_ok=True)
        return path

    def _read_compile_log(self, tex_path: str) -> tuple[str, str]:
        log_file = os.path.join(os.path.dirname(tex_path), f"{Path(tex_path).stem}.log")
        if not os.path.exists(log_file):
            return "", ""
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            return log_file, f.read()

    def _summarize_error(self, stderr: str, stdout: str, log_content: str) -> str:
        combined = "\n".join(part for part in (stderr.strip(), stdout.strip(), log_content.strip()) if part)
        if not combined:
            return "Unknown compilation error"

        lines = combined.splitlines()
        missing_character_lines = [line for line in lines if "Missing character" in line]
        if missing_character_lines:
            summary = [
                "Missing character in font — CJK text may have leaked into math mode.",
                missing_character_lines[0],
                "This usually means Chinese/Japanese text ended up inside $...$ or \\begin{equation}.",
            ]
            return "\n".join(summary)

        fatal_markers = ("! ", "Undefined control sequence", "Display math should end", "Emergency stop", "Fatal error")
        for line in lines:
            if any(marker in line for marker in fatal_markers):
                return line

        warning_lines = [line for line in lines if "warning:" in line.lower()]
        if warning_lines:
            return warning_lines[0]

        return "\n".join(lines[-20:])

    def _write_failure_diagnostics(
        self,
        tex_path: str,
        stdout: str,
        stderr: str,
        log_path: str,
        log_content: str,
        project_fonts_dir: str,
        fontconfig_dir: str,
    ) -> str:
        diagnostics_dir = self._create_diagnostics_dir()
        if os.path.isfile(tex_path):
            shutil.copy2(tex_path, os.path.join(diagnostics_dir, Path(tex_path).name))
        if log_path and os.path.isfile(log_path):
            shutil.copy2(log_path, os.path.join(diagnostics_dir, Path(log_path).name))
        with open(os.path.join(diagnostics_dir, "tectonic_stdout.txt"), "w", encoding="utf-8") as f:
            f.write(stdout or "")
        with open(os.path.join(diagnostics_dir, "tectonic_stderr.txt"), "w", encoding="utf-8") as f:
            f.write(stderr or "")
        if log_content and not log_path:
            with open(os.path.join(diagnostics_dir, "output.log"), "w", encoding="utf-8") as f:
                f.write(log_content)

        fonts = sorted(os.listdir(project_fonts_dir)) if os.path.isdir(project_fonts_dir) else []
        with open(os.path.join(diagnostics_dir, "diagnostics.txt"), "w", encoding="utf-8") as f:
            f.write(f"tex_path={tex_path}\n")
            f.write(f"fontconfig_dir={fontconfig_dir}\n")
            f.write(f"project_fonts_dir={project_fonts_dir}\n")
            f.write("fonts=\n")
            for font in fonts:
                f.write(f"- {font}\n")
        return diagnostics_dir

    def compile(self, tex_path: str, output_dir: str) -> CompileResult:
        tectonic_path = self.get_tectonic()
        tex_path = os.path.abspath(tex_path)
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        self.log.info(f"Compiling {tex_path} with Tectonic")
        try:
            # Copy CJK fonts to the TeX file directory so XeTeX can find them by filename
            project_fonts_dir = ensure_fonts_available(self.data_dir)
            tex_dir = os.path.dirname(tex_path)
            for font_file in os.listdir(project_fonts_dir):
                src = os.path.join(project_fonts_dir, font_file)
                dst = os.path.join(tex_dir, font_file)
                if not os.path.isfile(dst):
                    shutil.copy2(src, dst)
            fontconfig_dir = self._ensure_fontconfig()
            env = os.environ.copy()
            env["FONTCONFIG_PATH"] = fontconfig_dir
            run_kwargs = dict(
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                cwd=os.path.dirname(tex_path),
                env=env,
            )
            if sys.platform == "win32":
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [tectonic_path, "-o", output_dir, tex_path],
                **run_kwargs,
            )
        except FileNotFoundError:
            return CompileResult(False, error="Tectonic binary not found. Please download it in Settings.")
        except subprocess.TimeoutExpired:
            return CompileResult(False, error="Compilation timed out (5 minutes). The document may be too complex.")

        if result.returncode != 0:
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            log_path = ""
            log_content = ""
            try:
                log_path, log_content = self._read_compile_log(tex_path)
            except Exception as e:
                self.log.warning(f"Could not read Tectonic log: {e}")

            summary = self._summarize_error(stderr, stdout, log_content)
            diagnostics_dir = ""
            try:
                diagnostics_dir = self._write_failure_diagnostics(
                    tex_path,
                    stdout,
                    stderr,
                    log_path,
                    log_content,
                    project_fonts_dir,
                    fontconfig_dir,
                )
            except Exception as e:
                self.log.warning(f"Could not write TeX diagnostics: {e}")

            details = []
            if stderr.strip():
                details.append(stderr.strip())
            elif stdout.strip():
                details.append(stdout.strip())
            if log_content.strip():
                details.append("Detailed log tail:\n" + "\n".join(log_content.splitlines()[-50:]))
            if diagnostics_dir:
                details.append(f"Diagnostics saved to: {diagnostics_dir}")
            error_msg = summary
            if details:
                error_msg = f"{summary}\n\n" + "\n\n".join(details)

            self.log.error("Tectonic compilation failed with stderr/stdout and log excerpt")
            self.log.error(f"Tectonic compilation failed:\n{error_msg}")
            return CompileResult(
                False,
                error=error_msg,
                stdout=stdout,
                stderr=stderr,
                log_path=log_path,
                diagnostics_dir=diagnostics_dir,
            )

        tex_name = Path(tex_path).stem
        pdf_path = os.path.join(output_dir, f"{tex_name}.pdf")
        if not os.path.isfile(pdf_path):
            tex_dir = os.path.dirname(tex_path)
            for f in os.listdir(tex_dir):
                if f.endswith(".pdf"):
                    pdf_path = os.path.join(tex_dir, f)
                    break

        if os.path.isfile(pdf_path):
            self.log.info(f"Compilation successful: {pdf_path}")
            self.cleanup(os.path.dirname(tex_path))
            return CompileResult(True, pdf_path=pdf_path)
        else:
            return CompileResult(False, error="PDF file not produced. Check LaTeX content.")

    def cleanup(self, temp_dir: str) -> None:
        tex_stem = None
        for f in os.listdir(temp_dir):
            if f.endswith(".tex"):
                tex_stem = Path(f).stem
                break
        if not tex_stem:
            return
        for ext in TEX_TEMP_EXTENSIONS:
            p = os.path.join(temp_dir, f"{tex_stem}{ext}")
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
