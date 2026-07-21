import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from metabolomics.gui import theme
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QWidget

from metabolomics.gui_qt.qss import ThemeManager, build_stylesheet
from metabolomics.gui_qt.theme_controls import ThemeSelector


class FakeStyleHints(QObject):
    colorSchemeChanged = Signal(Qt.ColorScheme)

    def __init__(self, scheme):
        super().__init__()
        self._scheme = scheme

    def colorScheme(self):
        return self._scheme

    def set_color_scheme(self, scheme):
        self._scheme = scheme
        self.colorSchemeChanged.emit(scheme)


def test_stylesheet_uses_theme_tokens_for_each_mode():
    light = build_stylesheet("light")
    dark = build_stylesheet("dark")

    assert theme.resolve("surface", "light") in light
    assert theme.resolve("surface", "dark") in dark
    assert theme.resolve("accent", "light") in light
    assert theme.resolve("accent", "dark") in dark
    assert light != dark


def test_theme_manager_swaps_qss_without_rebuilding_window():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    manager = ThemeManager(app, preference="light")
    original_window = id(window)

    light_stylesheet = app.styleSheet()
    manager.set_preference("dark")

    assert manager.preference == "dark"
    assert manager.mode == "dark"
    assert app.styleSheet() != light_stylesheet
    assert theme.resolve("surface", "dark") in app.styleSheet()
    assert id(window) == original_window

    window.close()


def test_system_preference_uses_qt_os_color_scheme_at_startup():
    app = QApplication.instance() or QApplication([])
    style_hints = FakeStyleHints(Qt.ColorScheme.Dark)

    manager = ThemeManager(app, preference="system", style_hints=style_hints)

    assert manager.preference == "system"
    assert manager.mode == "dark"
    assert theme.resolve("surface", "dark") in app.styleSheet()


def test_system_preference_tracks_qt_os_color_scheme_changes():
    app = QApplication.instance() or QApplication([])
    style_hints = FakeStyleHints(Qt.ColorScheme.Dark)
    manager = ThemeManager(app, preference="system", style_hints=style_hints)

    style_hints.set_color_scheme(Qt.ColorScheme.Light)
    app.processEvents()

    assert manager.mode == "light"
    assert theme.resolve("surface", "light") in app.styleSheet()


def test_theme_selector_changes_the_live_preference():
    app = QApplication.instance() or QApplication([])
    manager = ThemeManager(app, preference="light")
    selector = ThemeSelector(manager)
    dark_button = next(
        button
        for button in selector.findChildren(QPushButton)
        if button.text() == "Dark"
    )

    dark_button.click()

    assert manager.preference == "dark"
    assert dark_button.isChecked()
    assert theme.resolve("surface", "dark") in app.styleSheet()


def test_real_qt_window_starts_and_toggles_theme_without_rebuild():
    app = QApplication.instance() or QApplication([])
    manager = ThemeManager(app, preference="light")
    window = QMainWindow()
    selector = ThemeSelector(manager)
    window.setCentralWidget(selector)
    original_window = id(window)

    window.show()
    app.processEvents()
    manager.set_preference("dark")
    app.processEvents()

    assert window.isVisible()
    assert id(window) == original_window
    window.close()
