import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from metabolomics.workflow import STEP1_NAME
from metabolomics.gui_qt.app import DNPMainWindow
from metabolomics.gui_qt.controller import WorkflowController
from tests.gui_qt_helpers import qt_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _gui_module(name: str, main) -> ModuleType:
    module = ModuleType(name)
    module.main = main
    return module


def _load_root_launcher():
    launcher_path = PROJECT_ROOT / "Data_Normalization_program_v2.py"
    spec = importlib.util.spec_from_file_location("dnp_root_launcher", launcher_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_launcher_delegates_to_qt_without_tk_fallback(monkeypatch):
    calls = []

    def fail_tk():
        raise AssertionError("root launcher must not route to tkinter")

    monkeypatch.setitem(
        sys.modules,
        "metabolomics.gui_qt.app",
        _gui_module("metabolomics.gui_qt.app", lambda: calls.append("qt")),
    )
    monkeypatch.setitem(
        sys.modules,
        "metabolomics.gui.app",
        _gui_module("metabolomics.gui.app", fail_tk),
    )

    _load_root_launcher().main()

    assert calls == ["qt"]


def test_package_main_delegates_to_qt_without_tk_fallback(monkeypatch):
    calls = []

    def fail_tk():
        raise AssertionError("python -m metabolomics must not route to tkinter")

    monkeypatch.setitem(
        sys.modules,
        "metabolomics.gui_qt.app",
        _gui_module("metabolomics.gui_qt.app", lambda: calls.append("qt")),
    )
    monkeypatch.setitem(
        sys.modules,
        "metabolomics.gui.app",
        _gui_module("metabolomics.gui.app", fail_tk),
    )
    package_main = importlib.import_module("metabolomics.__main__")

    package_main.main()

    assert calls == ["qt"]


def test_production_build_and_ci_route_to_qt():
    production_spec = (PROJECT_ROOT / "build" / "MetabolomicsNormalization.spec").read_text(
        encoding="utf-8"
    )
    build_workflow = (PROJECT_ROOT / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )

    assert "'gui_qt', 'app.py'" in production_spec
    assert "'gui', 'app.py'" not in production_spec
    assert "'metabolomics.gui_qt'" in production_spec
    assert "'metabolomics.gui'," not in production_spec
    assert "'metabolomics.processors.qc_batch_scaling'" in production_spec
    assert "'metabolomics.processors.batch_effect'" not in production_spec
    assert "excludes=['tkinter']" in production_spec
    assert "'unittest'," not in production_spec
    assert 'spec-file: "build/MetabolomicsNormalization.spec"' in build_workflow


def test_p4_shortcuts_run_next_and_respect_text_focus(monkeypatch):
    app = qt_app()
    controller = WorkflowController(processors={})
    window = DNPMainWindow(controller=controller)
    window.show()
    controller.select_input("C:/input.xlsx")
    calls = []
    monkeypatch.setattr(controller, "start_step", calls.append)

    window.browse_button.setFocus()
    app.processEvents()
    window.run_next_shortcuts[0].activated.emit()
    assert calls == [STEP1_NAME]

    window.log.setFocus()
    app.processEvents()
    window.run_next_shortcuts[0].activated.emit()
    assert calls == [STEP1_NAME]

    window.close()


def test_p4_escape_shortcut_stops_except_from_text_focus(monkeypatch):
    app = qt_app()
    controller = WorkflowController(processors={})
    window = DNPMainWindow(controller=controller)
    window.show()
    calls = []
    monkeypatch.setattr(controller, "request_stop", lambda: calls.append("stop"))

    window.browse_button.setFocus()
    app.processEvents()
    window.stop_shortcut.activated.emit()
    assert calls == ["stop"]

    window.log.setFocus()
    app.processEvents()
    window.stop_shortcut.activated.emit()
    assert calls == ["stop"]

    window.close()


def test_p4_window_has_final_startup_and_minimum_size():
    window = DNPMainWindow(controller=WorkflowController(processors={}))

    available = window.screen().availableGeometry()
    # Design minimum is 1200x700, but it must never exceed the work area so the
    # window always fits on small or display-scaled screens.
    assert 320 <= window.minimumWidth() <= min(1200, available.width())
    assert 320 <= window.minimumHeight() <= min(700, available.height())
    # Startup size stays within [minimum, work area] on every screen.
    assert window.minimumWidth() <= window.width() <= available.width()
    assert window.minimumHeight() <= window.height() <= available.height()
    assert {
        shortcut.key().toString() for shortcut in window.run_next_shortcuts
    } == {"Return", "Enter"}
    assert window.stop_shortcut.key().toString() == "Esc"

    window.close()
