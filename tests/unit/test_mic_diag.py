"""Langkah 42 bagian 0: diagnosis tombol Bicara. Di luar READY TalkTapped diabaikan (penyebab
"Bicara tidak berfungsi" sebelum push-to-talk) dan kini tercatat INFO; log dev terpasang."""

import logging

from mica.core import logsetup
from mica.core.controller import UI_EVENTS


def test_ui_events_logged_at_info():
    assert "TalkTapped" in UI_EVENTS and "StopTapped" in UI_EVENTS


def test_configure_dev_logging_only_without_handlers(monkeypatch):
    root = logging.getLogger()
    saved = root.handlers[:]
    level = root.level
    try:
        root.handlers = []
        logsetup.configure_dev_logging()
        assert root.handlers and root.level == logging.INFO
        n = len(root.handlers)
        logsetup.configure_dev_logging()  # tidak dipasang dua kali
        assert len(root.handlers) == n
    finally:
        root.handlers = saved
        root.setLevel(level)
