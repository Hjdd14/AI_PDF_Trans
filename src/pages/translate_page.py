"""Translation page — file selection, progress, and results."""

import asyncio
import os

import flet as ft

from src.models.config import FullConfig, LANGUAGES
from src.agent_runtime import AgentRuntime
from src.locale import t
from src.utils.logger import get_logger


class TranslatePage(ft.Column):
    def __init__(self, config: FullConfig, data_dir: str):
        super().__init__(expand=True, spacing=10)
        self.config = config
        self.data_dir = data_dir
        self.log = get_logger()
        self._is_running = False
        self._pipeline = None
        self._source_path = ""
        self._output_path = ""
        self._progress_data = None
        self._source_picker = ft.FilePicker()
        self._output_picker = ft.FilePicker()
        self._build_ui()

    def _t(self, key: str) -> str:
        return t(key, self.config.app.ui_lang)

    def _build_ui(self):
        L = self._t
        self._source_label = ft.Text(L("no_file_selected"), size=13, color=ft.Colors.GREY_600)
        self._output_label = ft.Text(L("default_output"), size=13, color=ft.Colors.GREY_600)
        self._file_section_title = ft.Text(L("file_selection"), size=16, weight=ft.FontWeight.BOLD)
        self._select_pdf_btn = ft.ElevatedButton(L("select_pdf"), icon=ft.Icons.FOLDER_OPEN, on_click=self._on_pick_source)
        self._output_btn = ft.ElevatedButton(L("output_location"), icon=ft.Icons.SAVE_AS, on_click=self._on_pick_output)

        self._lang_section_title = ft.Text(L("translation_settings"), size=16, weight=ft.FontWeight.BOLD)
        self._source_lang = ft.Dropdown(
            label=L("source_lang"), value=self.config.app.source_lang,
            options=[ft.dropdown.Option(k) for k in LANGUAGES], width=200,
        )
        self._target_lang = ft.Dropdown(
            label=L("target_lang"), value=self.config.app.target_lang,
            options=[ft.dropdown.Option(k) for k in LANGUAGES], width=200,
        )

        self._progress_title = ft.Text(L("progress"), size=16, weight=ft.FontWeight.BOLD)
        self._progress_bar = ft.ProgressBar(value=0, width=400)
        self._status_text = ft.Text(L("ready"), size=13)
        self._detail_text = ft.Text("", size=12, color=ft.Colors.GREY_500)

        self._translate_btn = ft.ElevatedButton(
            L("translate"), icon=ft.Icons.PLAY_ARROW, on_click=self._on_translate, disabled=True,
        )
        self._cancel_btn = ft.ElevatedButton(
            L("cancel"), icon=ft.Icons.STOP, on_click=self._on_cancel, disabled=True, color=ft.Colors.RED,
        )

        file_section = ft.Card(content=ft.Container(content=ft.Column([
            self._file_section_title,
            ft.Row([self._select_pdf_btn, self._source_label]),
            ft.Row([self._output_btn, self._output_label]),
        ], spacing=10), padding=15))

        lang_section = ft.Card(content=ft.Container(content=ft.Column([
            self._lang_section_title,
            ft.Row([self._source_lang, self._target_lang], spacing=20),
        ], spacing=10), padding=15))

        action_section = ft.Row([self._translate_btn, self._cancel_btn], spacing=15)

        progress_section = ft.Card(content=ft.Container(content=ft.Column([
            self._progress_title, self._progress_bar, self._status_text, self._detail_text,
        ], spacing=8), padding=15))

        self.controls = [
            ft.Container(content=file_section, padding=5),
            ft.Container(content=lang_section, padding=5),
            ft.Container(content=action_section, padding=5),
            ft.Container(content=progress_section, padding=5),
        ]

    def update_texts(self):
        L = self._t
        self._source_label.value = L("no_file_selected") if not self._source_path else os.path.basename(self._source_path)
        self._output_label.value = L("default_output") if not self._output_path else os.path.basename(self._output_path)
        self._file_section_title.value = L("file_selection")
        self._select_pdf_btn.text = L("select_pdf")
        self._output_btn.text = L("output_location")
        self._lang_section_title.value = L("translation_settings")
        self._source_lang.label = L("source_lang")
        self._target_lang.label = L("target_lang")
        self._progress_title.value = L("progress")
        self._translate_btn.text = L("translate")
        self._cancel_btn.text = L("cancel")
        if not self._is_running:
            self._status_text.value = L("ready")

    def update_remote_progress(self, stage: str, progress: int, message: str, status: str):
        """Called from app.py polling loop — shows remote task progress on the desktop GUI."""
        if self._is_running:
            return  # Local translation takes priority over remote display

        if status == "running":
            self._progress_bar.value = progress / 100
            self._status_text.value = f"[远程] [{stage}] {message}"
            self._detail_text.value = f"{progress}%"
            self._translate_btn.disabled = True
        elif status == "completed":
            self._progress_bar.value = 1.0
            self._status_text.value = "[远程] 翻译完成"
            self._detail_text.value = ""
            self._translate_btn.disabled = False
        elif status in ("failed", "cancelled"):
            self._progress_bar.value = 0
            self._status_text.value = f"[远程] {status}: {message}"
            self._detail_text.value = ""
            self._translate_btn.disabled = False

        try:
            self.update()
        except Exception:
            pass

    async def _on_pick_source(self, e):
        files = await self._source_picker.pick_files(
            dialog_title=self._t("select_pdf_dialog"),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["pdf"],
        )
        if files and files[0].path:
            self._source_path = files[0].path
            self._source_label.value = os.path.basename(self._source_path)
            self._translate_btn.disabled = False
            base = os.path.splitext(self._source_path)[0]
            self._output_path = f"{base}_translated.pdf"
            self._output_label.value = os.path.basename(self._output_path)
            self.update()

    async def _on_pick_output(self, e):
        result = await self._output_picker.save_file(
            dialog_title=self._t("save_pdf_dialog"),
            file_name="translated.pdf",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["pdf"],
        )
        if result:
            self._output_path = result
            if not self._output_path.endswith(".pdf"):
                self._output_path += ".pdf"
            self._output_label.value = os.path.basename(self._output_path)
            self.update()

    async def _on_translate(self, e):
        if self._is_running:
            return
        if not self._source_path:
            return
        if not self._output_path:
            base = os.path.splitext(self._source_path)[0]
            self._output_path = f"{base}_translated.pdf"
        self.config.app.source_lang = self._source_lang.value
        self.log.info(f"_on_translate called - page={id(self.page)}, session={id(self.page.session)}")
        self.config.app.target_lang = self._target_lang.value
        self._is_running = True
        self._translate_btn.disabled = True
        self._cancel_btn.disabled = False
        self._progress_bar.value = 0
        self._status_text.value = self._t("starting")
        self._detail_text.value = ""
        self._progress_data = None
        self._pipeline = None
        self.update()
        self.page.run_task(self._run_translation)
        self.page.run_task(self._refresh_loop)

    async def _refresh_loop(self):
        loop_page_id = id(self.page)
        self.log.info(f"_refresh_loop started - page={loop_page_id}")
        while self._is_running or self._progress_data is not None:
            current_page_id = id(self.page)
            if current_page_id != loop_page_id:
                self.log.warning(f"PAGE CHANGED during refresh loop! old={loop_page_id}, new={current_page_id} — skipping update")
                await asyncio.sleep(0.2)
                continue
            if self._progress_data:
                stage, progress, message = self._progress_data
                self._progress_bar.value = progress / 100
                self._status_text.value = f"[{stage}] {message}"
                if stage == "done":
                    self._detail_text.value = f"{self._t('output')}: {self._output_path}"
                elif stage in ("error", "cancelled"):
                    self._detail_text.value = ""
                else:
                    self._detail_text.value = f"{progress}%"
                self._progress_data = None
                try:
                    self.update()
                except Exception as ex:
                    self.log.exception("self.update() failed in refresh loop")
            await asyncio.sleep(0.2)

    async def _run_translation(self):
        self.log.info(f"_run_translation started - page={id(self.page)}, session={id(self.page.session)}")
        try:
            agent = AgentRuntime(self.config.llm, self.config.app, self.data_dir)
            self._pipeline = agent

            def on_progress(stage, progress, message):
                self.log.info(
                    f"progress update stage={stage} progress={progress} message={message!r} "
                    f"page={id(self.page)} session={id(self.page.session)}"
                )
                self._progress_data = (stage, progress, message)

            await asyncio.to_thread(
                agent.run, self._source_path, self._output_path, on_progress,
            )
            self._progress_data = ("done", 100, self._t("translation_complete"))
        except InterruptedError:
            self.log.info("Translation cancelled by user", exc_info=True)
            self._progress_data = ("cancelled", 0, self._t("cancelled"))
        except Exception as ex:
            self._progress_data = ("error", 0, f"{self._t('error_prefix')}: {str(ex)[:200]}")
            self.log.exception("Translation error")
        finally:
            self._is_running = False
            self._translate_btn.disabled = False
            self._cancel_btn.disabled = True
            await asyncio.sleep(0.3)
            self.update()

    async def _on_cancel(self, e):
        if self._pipeline:
            self._pipeline.cancel()
            self._status_text.value = self._t("cancelling")
            self._cancel_btn.disabled = True
            self.update()
