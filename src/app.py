"""Main Flet application controller."""

import asyncio
import os
import flet as ft

from src.models.config import FullConfig
from src.locale import t
from src.utils.logger import setup_logger, get_logger
from src.pages.translate_page import TranslatePage
from src.pages.settings_page import SettingsPage


class AIPDFTransApp:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.config_path = os.path.join(data_dir, "config.json")
        self.config = FullConfig.load(self.config_path)
        self.config.app.data_dir = data_dir
        self._page_ref = None
        self._server_thread = None
        self._task_manager = None
        self._server_port = 8654
        self._server_error = None
        self._remote_poll_task = None

    def _t(self, key: str) -> str:
        return t(key, self.config.app.ui_lang)

    def run(self, page: ft.Page) -> None:
        # Copy bundled resources (tectonic, fonts) to runtime data_dir
        from src.utils.resources import ensure_data_dir_resources
        ensure_data_dir_resources(self.data_dir)

        # Prevent re-initialization if called multiple times
        if hasattr(self, '_initialized') and self._initialized:
            log = get_logger()
            log.warning(f"Duplicate window detected — closing new page={id(page)}")
            page.window.destroy()
            return
        self._initialized = True
        self._page_ref = page
        page.title = self._t("app_title")
        page.theme_mode = ft.ThemeMode.SYSTEM
        page.window.width = 1000
        page.window.height = 750
        page.window.min_width = 800
        page.window.min_height = 600

        setup_logger(self.data_dir)
        log = get_logger()
        log.info("AI PDF Trans starting")

        # Diagnostic logging for new window detection
        log.info(f"run() called - page={id(page)}, session={id(page.session)}")
        if hasattr(self, '_run_count'):
            self._run_count += 1
            log.warning(f"run() called AGAIN ({self._run_count}x) - RECONNECTION detected!")
        else:
            self._run_count = 1

        self._settings_page = SettingsPage(self.config, self._on_config_changed, self._on_server_toggle)
        self._translate_page = TranslatePage(self.config, self.data_dir)

        self._tab_translate = ft.Tab(label=self._t("tab_translate"), icon=ft.Icons.TRANSLATE)
        self._tab_settings = ft.Tab(label=self._t("tab_settings"), icon=ft.Icons.SETTINGS)

        self._tabs = ft.Tabs(
            length=2,
            selected_index=0,
            expand=True,
            content=ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.TabBar(
                        tabs=[
                            self._tab_translate,
                            self._tab_settings,
                        ],
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            self._translate_page,
                            self._settings_page,
                        ],
                    ),
                ],
            ),
        )

        page.add(self._tabs)
        page.on_close = self._on_close
        page.on_connect = lambda e: log.info(f"Page connected - session={id(page.session)}")
        page.on_disconnect = lambda e: log.warning(f"Page disconnected! - session={id(page.session)}")

    def _on_config_changed(self):
        self.config.save(self.config_path)
        self._tab_translate.label = self._t("tab_translate")
        self._tab_settings.label = self._t("tab_settings")
        self._translate_page.update_texts()
        if self._page_ref:
            self._page_ref.title = self._t("app_title")
            self._page_ref.update()

    def _on_server_toggle(self, enable: bool, port: int) -> tuple[bool, str]:
        """Called by settings page when remote server toggle changes. Returns (success, error_msg)."""
        if enable:
            return self._start_server(port)
        else:
            self._stop_server()
            return True, ""

    def _start_server(self, port: int) -> tuple[bool, str]:
        import threading
        try:
            from src.server.server import run_server
            from src.server.task_manager import TaskManager

            if self._task_manager is None:
                self._task_manager = TaskManager()

            self._server_port = port
            self._server_error = None

            def _serve():
                try:
                    run_server("0.0.0.0", port, self._task_manager, self.config, self.data_dir)
                except Exception as e:
                    log = get_logger()
                    log.exception(f"Server thread error: {e}")
                    self._server_error = str(e)

            self._server_thread = threading.Thread(target=_serve, daemon=True)
            self._server_thread.start()

            # Verify it started
            import time
            time.sleep(0.8)
            if not self._server_thread.is_alive():
                err = self._server_error or "Server thread died immediately"
                log = get_logger()
                log.error(f"Server start failed: {err}")
                return False, err

            log = get_logger()
            log.info(f"Remote server started on port {port}")

            # Start polling remote task progress for the desktop GUI
            if self._page_ref and not self._remote_poll_task:
                self._remote_poll_task = self._page_ref.run_task(
                    self._remote_progress_poll
                )

            return True, ""
        except ImportError as e:
            log = get_logger()
            log.warning(f"Server dependencies not installed: {e}")
            return False, f"Missing dependency: {e}"
        except Exception as e:
            log = get_logger()
            log.exception(f"Failed to start server: {e}")
            return False, str(e)[:200]

    def _stop_server(self):
        self._remote_poll_task = None  # Stops the polling loop (checked in loop condition)
        if self._server_thread is not None:
            self._server_thread = None
            log = get_logger()
            log.info("Remote server stopped")

    async def _remote_progress_poll(self):
        """Poll task_manager for remote translation tasks and update the desktop GUI."""
        while self._remote_poll_task is not None:
            try:
                if self._task_manager:
                    task = self._task_manager.get_active_task_info()
                    if task:
                        self._translate_page.update_remote_progress(
                            stage=task.stage,
                            progress=task.progress,
                            message=task.message,
                            status=task.status,
                        )
            except Exception:
                pass
            await asyncio.sleep(1)

    def _on_close(self, e=None):
        # Cancel running translation task before closing
        if hasattr(self, '_translate_page') and self._translate_page._is_running:
            if self._translate_page._pipeline:
                self._translate_page._pipeline.cancel()
        self._settings_page._sync_config()
        self.config.save(self.config_path)
        self._stop_server()
        log = get_logger()
        log.info("Application closing")
        if self._page_ref:
            self._page_ref.window.destroy()
