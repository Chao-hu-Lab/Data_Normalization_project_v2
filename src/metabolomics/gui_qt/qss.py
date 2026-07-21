"""Application-wide QSS generated from the shared semantic theme tokens."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from metabolomics.gui import theme


ThemeMode = Literal["light", "dark"]
ThemePreference = Literal["system", "light", "dark"]


class ThemeManager(QObject):
    """Own the app-wide theme preference and apply QSS without rebuilding widgets."""

    preference_changed = Signal(str)
    mode_changed = Signal(str)

    def __init__(
        self,
        app: QApplication,
        preference: ThemePreference,
        style_hints: QObject | None = None,
    ) -> None:
        super().__init__(app)
        self._app = app
        self._style_hints = style_hints or QGuiApplication.styleHints()
        self._preference: ThemePreference = "light"
        self._mode: ThemeMode = "light"
        self._style_hints.colorSchemeChanged.connect(self._on_color_scheme_changed)
        self.set_preference(preference)

    @property
    def preference(self) -> ThemePreference:
        return self._preference

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    def set_preference(self, preference: ThemePreference) -> None:
        if preference not in {"system", "light", "dark"}:
            raise ValueError(f"Unsupported theme preference: {preference!r}")
        previous_preference = self._preference
        previous_mode = self._mode
        self._preference = preference
        self._mode = (
            _mode_from_color_scheme(self._style_hints.colorScheme())
            if preference == "system"
            else preference
        )
        self._app.setStyleSheet(build_stylesheet(self._mode))
        if preference != previous_preference:
            self.preference_changed.emit(preference)
        if self._mode != previous_mode:
            self.mode_changed.emit(self._mode)

    @Slot(Qt.ColorScheme)
    def _on_color_scheme_changed(self, color_scheme: Qt.ColorScheme) -> None:
        if self._preference != "system":
            return
        mode = _mode_from_color_scheme(color_scheme)
        if mode == self._mode:
            return
        self._mode = mode
        self._app.setStyleSheet(build_stylesheet(mode))
        self.mode_changed.emit(mode)


def _mode_from_color_scheme(color_scheme: Qt.ColorScheme) -> ThemeMode:
    return "dark" if color_scheme == Qt.ColorScheme.Dark else "light"


def build_stylesheet(mode: ThemeMode) -> str:
    """Return the complete Qt stylesheet for a resolved light/dark mode."""
    color = lambda token: theme.resolve(token, mode)
    return f"""
QWidget {{
    background-color: {color("surface")};
    color: {color("text")};
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 10pt;
}}
QMainWindow, QWidget#centralWidget, QWidget#workflowCards {{
    background-color: {color("surface")};
}}
QLabel#pageTitle {{
    font-size: 20pt;
    font-weight: 700;
}}
QLabel#pageSubtitle, QLabel#cardHint, QLabel#sessionPath {{
    color: {color("text_muted")};
}}
QFrame#stepCard1, QFrame#stepCard2, QFrame#stepCard3, QFrame#stepCard4,
QFrame#logPane, QFrame#fileBar {{
    background-color: {color("surface_raised")};
    border: 1px solid {color("border")};
    border-radius: 8px;
}}
QFrame#stepBadge {{
    background-color: {color("nav_bg")};
    border-radius: 5px;
}}
QFrame#stepBadge QLabel {{
    background: transparent;
    color: {color("nav_fg_active")};
    font-weight: 600;
}}
QFrame#cardDivider {{
    color: {color("divider")};
}}
QPushButton {{
    background-color: {color("action")};
    color: {color("action_fg")};
    border: 1px solid {color("border")};
    border-radius: 5px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: {color("hover")};
}}
QPushButton:disabled {{
    color: {color("action_disabled")};
}}
QPushButton#primaryAction, QPushButton#browseButton, QPushButton#autoRunButton {{
    background-color: {color("accent")};
    color: {color("accent_fg")};
    border-color: {color("accent")};
}}
QPushButton#primaryAction:hover, QPushButton#browseButton:hover,
QPushButton#autoRunButton:hover {{
    background-color: {color("accent_hover")};
}}
QPushButton#stopButton {{
    background-color: {color("control_stop_bg")};
    color: {color("control_fg")};
    border-color: {color("control_stop_bg")};
}}
QPushButton#themeOption {{
    border-radius: 0;
    padding: 4px 9px;
}}
QPushButton#themeOption:checked {{
    background-color: {color("accent")};
    color: {color("accent_fg")};
}}
QLabel#statusPill {{
    background-color: {color("status_idle_bg")};
    color: {color("status_idle")};
    border-radius: 8px;
    padding: 2px 8px;
    font-weight: 600;
}}
QLabel#statusPill[state="running"] {{
    background-color: {color("status_running")};
    color: {color("status_fg")};
}}
QLabel#statusPill[state="done"] {{
    background-color: {color("status_done")};
    color: {color("status_fg")};
}}
QLabel#statusPill[state="skipped"] {{
    background-color: {color("status_skipped")};
    color: {color("status_fg")};
}}
QLabel#statusPill[state="error"] {{
    background-color: {color("status_error")};
    color: {color("status_fg")};
}}
QLabel#statusPill[state="cancelled"] {{
    background-color: {color("status_cancelled")};
    color: {color("status_fg")};
}}
QPlainTextEdit#executionLog {{
    background-color: {color("console_bg")};
    color: {color("console_fg")};
    border: 1px solid {color("border")};
    border-radius: 5px;
    font-family: Consolas, Menlo, monospace;
}}
QStatusBar {{
    background-color: {color("surface_raised")};
    border-top: 1px solid {color("divider")};
}}
QSplitter::handle {{
    background-color: {color("divider")};
    width: 2px;
}}
""".strip()
