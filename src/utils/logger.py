"""Logging configuration."""

import logging
import os
from typing import Optional


_logger: Optional[logging.Logger] = None
_ui_log_handler = None


class UILogHandler(logging.Handler):
    """A logging handler that stores messages for UI display."""

    def __init__(self, max_messages: int = 500):
        super().__init__()
        self.messages: list[str] = []
        self.max_messages = max_messages

    def emit(self, record):
        msg = self.format(record)
        self.messages.append(msg)
        if len(self.messages) > self.max_messages:
            del self.messages[: len(self.messages) - self.max_messages]

    def get_and_clear(self) -> list[str]:
        msgs = self.messages.copy()
        self.messages.clear()
        return msgs


def setup_logger(data_dir: str, level: int = logging.DEBUG) -> logging.Logger:
    global _logger, _ui_log_handler

    log_dir = os.path.join(data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    _logger = logging.getLogger("ai_pdf_trans")
    _logger.setLevel(level)
    _logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        os.path.join(log_dir, "app.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    _logger.addHandler(file_handler)

    _ui_log_handler = UILogHandler()
    _ui_log_handler.setLevel(logging.INFO)
    _ui_log_handler.setFormatter(fmt)
    _logger.addHandler(_ui_log_handler)

    return _logger


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("ai_pdf_trans")
        if not _logger.handlers:
            _logger.addHandler(logging.NullHandler())
    return _logger


def get_ui_messages() -> list[str]:
    global _ui_log_handler
    if _ui_log_handler is None:
        return []
    return _ui_log_handler.get_and_clear()
