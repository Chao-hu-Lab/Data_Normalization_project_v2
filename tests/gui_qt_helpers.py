"""Shared event-loop helpers for Qt GUI tests."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    app = qt_app()
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for Qt state")
