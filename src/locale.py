"""UI locale strings for Chinese and English."""

UI_LANGS = {"en": "English", "zh": "中文"}

STRINGS = {
    "en": {
        # App
        "app_title": "AI PDF Translator",
        # Tabs
        "tab_translate": "Translate",
        "tab_settings": "Settings",
        # Translate page
        "file_selection": "File Selection",
        "no_file_selected": "No file selected",
        "select_pdf": "Select PDF",
        "output_location": "Output Location",
        "default_output": "Default: same as source directory",
        "translation_settings": "Translation Settings",
        "source_lang": "Source Language",
        "target_lang": "Target Language",
        "translate": "Translate",
        "cancel": "Cancel",
        "progress": "Progress",
        "ready": "Ready",
        "starting": "Starting...",
        "translation_complete": "Translation complete!",
        "cancelled": "Cancelled",
        "cancelling": "Cancelling...",
        "output": "Output",
        "select_pdf_dialog": "Select PDF file",
        "save_pdf_dialog": "Save translated PDF as",
        "translated": "translated",
        # Settings page
        "llm_api_config": "LLM API Configuration",
        "provider_type": "Provider Type",
        "api_url": "API URL (optional)",
        "api_key": "API Key",
        "model_name": "Model Name",
        "test_connection": "Test Connection",
        "testing": "Testing...",
        "tools_resources": "Tools & Resources",
        "tectonic_path": "Tectonic Binary Path",
        "not_installed": "Not installed",
        "download_tectonic": "Download Tectonic",
        "bundled_tectonic_note": "Tectonic is bundled with the application (no download needed)",
        "downloading": "Downloading...",
        "installing": "Installing...",
        "save_settings": "Save Settings",
        "settings_saved": "Settings saved!",
        "ui_language": "Language",
        # General
        "error_prefix": "Error",
    },
    "zh": {
        # App
        "app_title": "AI PDF 翻译器",
        # Tabs
        "tab_translate": "翻译",
        "tab_settings": "设置",
        # Translate page
        "file_selection": "文件选择",
        "no_file_selected": "未选择文件",
        "select_pdf": "选择PDF",
        "output_location": "输出位置",
        "default_output": "默认：与源文件同目录",
        "translation_settings": "翻译设置",
        "source_lang": "源语言",
        "target_lang": "目标语言",
        "translate": "翻译",
        "cancel": "取消",
        "progress": "进度",
        "ready": "就绪",
        "starting": "正在启动...",
        "translation_complete": "翻译完成！",
        "cancelled": "已取消",
        "cancelling": "正在取消...",
        "output": "输出",
        "select_pdf_dialog": "选择PDF文件",
        "save_pdf_dialog": "保存翻译后的PDF",
        "translated": "已翻译",
        # Settings page
        "llm_api_config": "大模型 API 配置",
        "provider_type": "服务商类型",
        "api_url": "API 地址（可选）",
        "api_key": "API 密钥",
        "model_name": "模型名称",
        "test_connection": "测试连接",
        "testing": "测试中...",
        "tools_resources": "工具与资源",
        "tectonic_path": "Tectonic 路径",
        "not_installed": "未安装",
        "download_tectonic": "下载 Tectonic",
        "bundled_tectonic_note": "Tectonic 已内置，无需下载",
        "downloading": "下载中...",
        "installing": "安装中...",
        "save_settings": "保存设置",
        "settings_saved": "设置已保存！",
        "ui_language": "界面语言",
        # General
        "error_prefix": "错误",
    },
}


def t(key: str, lang: str = "zh") -> str:
    """Get a translated string by key and language."""
    return STRINGS.get(lang, STRINGS["zh"]).get(key, key)
