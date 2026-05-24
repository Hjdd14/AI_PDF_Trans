"""Main Flet application controller."""

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

        self._settings_page = SettingsPage(self.config, self._on_config_changed)
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

    def _on_close(self, e=None):
        # Cancel running translation task before closing
        if hasattr(self, '_translate_page') and self._translate_page._is_running:
            if self._translate_page._pipeline:
                self._translate_page._pipeline.cancel()
        self._settings_page._sync_config()
        self.config.save(self.config_path)
        log = get_logger()
        log.info("Application closing")
        if self._page_ref:
            self._page_ref.window.destroy()
