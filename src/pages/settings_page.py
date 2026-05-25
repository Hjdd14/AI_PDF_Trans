"""Settings page — API configuration, tool management, and language switch."""

import asyncio
import os

import flet as ft

from src.models.config import FullConfig, PROVIDER_TYPES
from src.locale import t, UI_LANGS
from src.utils.file_utils import download_tectonic, get_tectonic_path
from src.utils.resources import is_frozen
from src.utils.logger import get_logger


class SettingsPage(ft.Column):
    def __init__(self, config: FullConfig, on_save, on_server_toggle=None):
        super().__init__(expand=True, spacing=10, scroll=ft.ScrollMode.AUTO)
        self.config = config
        self.on_save = on_save
        self._on_server_toggle = on_server_toggle
        self.log = get_logger()
        self._server_running = False
        self._build_ui()

    def _t(self, key: str) -> str:
        return t(key, self.config.app.ui_lang)

    def _build_ui(self):
        L = self._t
        llm = self.config.llm
        app = self.config.app

        # UI Language switcher
        self._ui_lang = ft.Dropdown(
            label=L("ui_language"),
            value=app.ui_lang,
            options=[ft.dropdown.Option(key, val) for key, val in UI_LANGS.items()],
            width=150,
            on_select=self._on_lang_change,
        )

        # LLM config
        self._llm_title = ft.Text(L("llm_api_config"), size=16, weight=ft.FontWeight.BOLD)
        self._provider = ft.Dropdown(
            label=L("provider_type"), value=llm.provider_type,
            options=[ft.dropdown.Option(p) for p in PROVIDER_TYPES], width=200,
            on_select=lambda _: self._auto_save(),
        )
        self._api_url = ft.TextField(
            label=L("api_url"), value=llm.api_url or "",
            hint_text="https://api.example.com/v1", width=400,
            on_blur=lambda _: self._auto_save(),
        )
        self._api_key = ft.TextField(
            label=L("api_key"), value=llm.api_key,
            password=True, can_reveal_password=True, width=400,
            on_blur=lambda _: self._auto_save(),
        )
        self._model_name = ft.TextField(
            label=L("model_name"), value=llm.model_name,
            hint_text="claude-sonnet-4-20250514 / gpt-4o", width=300,
            on_blur=lambda _: self._auto_save(),
        )
        self._test_btn = ft.ElevatedButton(L("test_connection"), icon=ft.Icons.CHECK_CIRCLE, on_click=self._on_test)
        self._test_result = ft.Text("", size=13)

        # Tools
        self._tools_title = ft.Text(L("tools_resources"), size=16, weight=ft.FontWeight.BOLD)
        self._tectonic_label = ft.Text(L("tectonic_path"), size=13)
        tectonic_found = get_tectonic_path(app.data_dir)
        status = "[bundled]" if is_frozen() and tectonic_found else (tectonic_found or L("not_installed"))
        self._tectonic_path = ft.TextField(
            value=status,
            width=400, read_only=True,
        )
        tools_children = [
            self._tools_title,
            self._tectonic_label,
            self._tectonic_path,
        ]
        if not is_frozen():
            self._download_tectonic_btn = ft.ElevatedButton(
                L("download_tectonic"), icon=ft.Icons.DOWNLOAD, on_click=self._on_download_tectonic,
            )
            tools_children.append(self._download_tectonic_btn)
        else:
            self._download_tectonic_btn = None
            tools_children.append(ft.Text(L("bundled_tectonic_note"), size=12, color=ft.Colors.GREY_500))

        # Save
        self._save_btn = ft.ElevatedButton(L("save_settings"), icon=ft.Icons.SAVE, on_click=self._on_save)
        self._save_result = ft.Text("", size=13, color=ft.Colors.GREEN)

        # Layout
        lang_section = ft.Card(content=ft.Container(content=ft.Column([
            ft.Text(L("ui_language"), size=16, weight=ft.FontWeight.BOLD),
            self._ui_lang,
        ], spacing=10), padding=15))

        llm_section = ft.Card(content=ft.Container(content=ft.Column([
            self._llm_title,
            self._provider, self._api_url, self._api_key,
            self._model_name,
            ft.Row([self._test_btn, self._test_result], spacing=15),
        ], spacing=10), padding=15))

        tools_section = ft.Card(content=ft.Container(content=ft.Column(
            tools_children, spacing=10
        ), padding=15))

        save_section = ft.Row([self._save_btn, self._save_result], spacing=15)

        # Remote server card (built in separate method)
        remote_section = self._build_remote_card()

        self.controls = [
            ft.Container(content=lang_section, padding=5),
            ft.Container(content=llm_section, padding=5),
            ft.Container(content=tools_section, padding=5),
            ft.Container(content=save_section, padding=5),
            ft.Container(content=remote_section, padding=5),
        ]

    def _on_lang_change(self, e):
        new_lang = e.data if e.data else self._ui_lang.value
        self.config.app.ui_lang = new_lang
        self._ui_lang.value = new_lang
        self.on_save()
        self.update_texts()
        try:
            self.update()
        except Exception:
            pass

    def update_texts(self):
        L = self._t
        self._llm_title.value = L("llm_api_config")
        self._provider.label = L("provider_type")
        self._api_url.label = L("api_url")
        self._api_key.label = L("api_key")
        self._model_name.label = L("model_name")
        self._test_btn.text = L("test_connection")
        self._tools_title.value = L("tools_resources")
        self._tectonic_label.value = L("tectonic_path")
        if self._tectonic_path.value in ("Not installed", "未安装"):
            self._tectonic_path.value = L("not_installed")
        if self._download_tectonic_btn is not None:
            self._download_tectonic_btn.text = L("download_tectonic")
        self._save_btn.text = L("save_settings")
        self.update_remote_texts()

    def _test_connection_sync(self) -> tuple[bool, str]:
        """Test LLM connection synchronously (runs in thread)."""
        import litellm
        litellm.drop_params = True
        litellm.modify_params = True
        litellm.num_retries = 1
        llm = self.config.llm

        # Build params with temperature for non-o-series models
        params = {
            "model": llm.get_litellm_model(),
            "messages": [{"role": "user", "content": "Say 'OK' if you can read this."}],
            "max_tokens": 50,
            "temperature": 0.3,
            "timeout": 60,
        }
        if llm.api_key:
            params["api_key"] = llm.api_key
        if llm.api_url:
            params["api_base"] = llm.api_url

        # Fallback loop: strip unsupported params on BadRequestError
        used = set()
        while True:
            try:
                response = litellm.completion(**params)
                content = response.choices[0].message.content or ""
                return True, f"Connection successful. Response: {content[:100]}"
            except litellm.BadRequestError as e:
                fallback = self._next_test_fallback(params, used)
                if fallback:
                    params, key = fallback
                    used.add(key)
                    continue
                return False, f"Connection failed: {e}"
            except Exception as e:
                return False, f"Connection failed: {e}"

    @staticmethod
    def _next_test_fallback(params: dict, used: set) -> tuple[dict, str] | None:
        if "temperature" not in used and "temperature" in params:
            new = dict(params)
            del new["temperature"]
            return new, "temperature"
        if "max_tokens" not in used and "max_tokens" in params:
            new = dict(params)
            new["max_completion_tokens"] = new.pop("max_tokens")
            return new, "max_tokens"
        return None

    async def _on_test(self, e):
        self._test_result.value = self._t("testing")
        self._test_result.color = ft.Colors.GREY
        self.update()
        self._sync_config()
        ok, msg = await asyncio.to_thread(self._test_connection_sync)
        self._test_result.value = msg
        self._test_result.color = ft.Colors.GREEN if ok else ft.Colors.RED
        self.update()

    def _auto_save(self):
        self._sync_config()
        self.on_save()

    def _on_save(self, e):
        self._sync_config()
        self.on_save()
        self._save_result.value = self._t("settings_saved")
        self.update()

    def _sync_config(self):
        self.config.llm.provider_type = self._provider.value
        self.config.llm.api_url = self._api_url.value or None
        self.config.llm.api_key = self._api_key.value
        self.config.llm.model_name = self._model_name.value

    # ── Remote server ──────────────────────────────────────────────────────

    def _build_remote_card(self):
        L = self._t

        self._remote_title = ft.Text(L("remote_access"), size=16, weight=ft.FontWeight.BOLD)
        self._remote_toggle = ft.Switch(label=L("remote_enable"), value=False, on_change=self._on_remote_toggle)
        self._remote_status = ft.Text(f"{L('server_status')}: {L('server_stopped')}", size=13, color=ft.Colors.GREY)
        self._remote_ips = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self._remote_port = ft.TextField(label=L("server_port"), value="8654", width=100, on_blur=self._on_port_change)
        self._remote_firewall = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self._remote_qr = ft.Image(src="", width=200, height=200, visible=False)
        self._remote_qr_label = ft.Text("", size=12, color=ft.Colors.GREY_500, visible=False)
        self._remote_test_btn = ft.ElevatedButton(
            L("test_local_connection"), icon=ft.Icons.NETWORK_CHECK, on_click=self._on_test_remote,
            visible=False,
        )
        self._remote_test_result = ft.Text("", size=12)

        return ft.Card(content=ft.Container(content=ft.Column([
            self._remote_title,
            self._remote_toggle,
            self._remote_status,
            self._remote_ips,
            ft.Row([self._remote_port, self._remote_test_btn], spacing=10),
            self._remote_test_result,
            self._remote_firewall,
            self._remote_qr_label,
            self._remote_qr,
        ], spacing=8), padding=15))

    def _on_remote_toggle(self, e):
        if self._on_server_toggle is None:
            self._remote_toggle.value = False
            self.update()
            return
        enable = e.data == "true" if isinstance(e.data, str) else self._remote_toggle.value
        if enable:
            port = int(self._remote_port.value or "8654")
            success, err = self._on_server_toggle(True, port)
            if success:
                self._server_running = True
                self._update_remote_ui_running(port)
            else:
                self._remote_toggle.value = False
                err_msg = err or self._t("error_prefix")
                self._remote_status.value = f"{self._t('server_status')}: {err_msg}"
                self._remote_status.color = ft.Colors.RED
        else:
            self._on_server_toggle(False, 0)
            self._server_running = False
            self._update_remote_ui_stopped()
        self.update()

    def _on_port_change(self, e):
        if self._server_running:
            # Restart server on new port
            self._on_server_toggle(False, 0)
            port = int(self._remote_port.value or "8654")
            success, err = self._on_server_toggle(True, port)
            if success:
                self._update_remote_ui_running(port)
            else:
                err_msg = err or self._t("error_prefix")
                self._remote_status.value = f"{self._t('server_status')}: {err_msg}"
                self._remote_status.color = ft.Colors.RED
                self._update_remote_ui_stopped()
            self.update()

    def _update_remote_ui_running(self, port):
        from src.server.network import get_local_ips, check_firewall_rule, generate_qr_data_url
        L = self._t
        self._remote_status.value = f"{L('server_status')}: {L('server_running')}"
        self._remote_status.color = ft.Colors.GREEN
        ips = get_local_ips()
        if ips:
            self._remote_ips.value = f"{L('local_ips')}: {', '.join(ips)}"
            primary_ip = ips[0]
            url = f"http://{primary_ip}:{port}"
            qr_data = generate_qr_data_url(url)
            if qr_data:
                self._remote_qr.src = qr_data
                self._remote_qr.visible = True
                self._remote_qr_label.value = L("scan_qr_connect")
                self._remote_qr_label.visible = True
        else:
            self._remote_ips.value = L("server_running") + " (no network detected)"

        rule_ok, _, _ = check_firewall_rule(port)
        if rule_ok:
            self._remote_firewall.value = L("server_firewall_ok")
            self._remote_firewall.color = ft.Colors.GREEN
        else:
            self._remote_firewall.value = L("server_firewall_warning").format(port=port)
            self._remote_firewall.color = ft.Colors.ORANGE

        self._remote_test_btn.visible = True

    def _update_remote_ui_stopped(self):
        L = self._t
        self._remote_status.value = f"{L('server_status')}: {L('server_stopped')}"
        self._remote_status.color = ft.Colors.GREY
        self._remote_ips.value = ""
        self._remote_qr.src = ""
        self._remote_qr.visible = False
        self._remote_qr_label.visible = False
        self._remote_test_btn.visible = False
        self._remote_test_result.value = ""
        self._remote_firewall.value = ""

    def _on_test_remote(self, e):
        from src.server.network import test_port
        L = self._t
        port = int(self._remote_port.value or "8654")
        ok, err = test_port("127.0.0.1", port)
        if ok:
            self._remote_test_result.value = L("server_test_success")
            self._remote_test_result.color = ft.Colors.GREEN
        else:
            self._remote_test_result.value = f"{L('server_test_fail')}: {err}"
            self._remote_test_result.color = ft.Colors.RED
        self.update()

    def update_remote_texts(self):
        L = self._t
        self._remote_title.value = L("remote_access")
        self._remote_toggle.label = L("remote_enable")
        self._remote_port.label = L("server_port")
        self._remote_test_btn.text = L("test_local_connection")
        if self._server_running:
            self._update_remote_ui_running(int(self._remote_port.value or "8654"))
        else:
            self._update_remote_ui_stopped()

    async def _on_download_tectonic(self, e):
        self._tectonic_path.value = self._t("downloading")
        self.update()
        try:
            path = await asyncio.to_thread(download_tectonic, self.config.app.data_dir, None)
            self._tectonic_path.value = path
        except Exception as ex:
            self._tectonic_path.value = f"{self._t('error_prefix')}: {ex}"
        self.update()

