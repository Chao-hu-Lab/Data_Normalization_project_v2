import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter

from metabolomics.gui.workflow import STEP1_NAME, StepState
from metabolomics.gui_qt.app import DNPMainWindow, STEP_NAMES, VISIBLE_STATES
from metabolomics.gui_qt.controller import WorkflowController
from metabolomics.utils.results import ProcessingResult


def _app():
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout_ms=3000):
    app = _app()
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for Qt view state")


def test_p2_window_starts_with_four_cards_and_six_visible_states():
    app = _app()
    controller = WorkflowController(
        processors={},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)

    window.show()
    app.processEvents()
    window.theme_manager.set_preference("dark")
    app.processEvents()

    assert window.isVisible()
    assert set(window.cards) == set(STEP_NAMES)
    assert window.findChild(QSplitter, "workspaceSplitter").count() == 2
    assert {state.value for state in VISIBLE_STATES} == {
        "pending",
        "running",
        "succeeded",
        "skipped",
        "failed",
        "cancelled",
    }
    window.close()


def test_p2_view_runs_a_step_and_renders_the_terminal_state():
    def processor(**kwargs):
        return ProcessingResult(
            file_path=kwargs["input_file"],
            output_path="C:/session/step1.xlsx",
            metabolites=10,
            samples=5,
        )

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)
    window.show()
    controller.select_input("C:/input.xlsx")

    window.cards[STEP1_NAME].run_button.click()
    _wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert window.cards[STEP1_NAME].status_label.text() == "Done"
    assert "Starting Step 1" in window.log.toPlainText()
    window.close()


def test_heartbeat_is_owned_by_the_ui_timer_not_the_worker():
    entered = threading.Event()
    release = threading.Event()

    def processor(**kwargs):
        entered.set()
        assert release.wait(2)
        return ProcessingResult(
            file_path=kwargs["input_file"],
            output_path="C:/session/step1.xlsx",
            metabolites=10,
            samples=5,
        )

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)
    window.show()
    controller.select_input("C:/input.xlsx")
    window.cards[STEP1_NAME].run_button.click()
    _wait_until(entered.is_set)

    assert window.heartbeat.isActive()
    assert window.progress_label.text().startswith("Running")

    controller.request_stop()
    release.set()
    _wait_until(lambda: not controller.is_running)

    assert not window.heartbeat.isActive()
    assert controller.workflow.status_of(STEP1_NAME) is StepState.CANCELLED
    window.close()


def test_close_event_keeps_window_alive_until_worker_finishes(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def processor(**kwargs):
        entered.set()
        assert release.wait(3)
        return ProcessingResult(
            file_path=kwargs["input_file"],
            output_path="C:/session/discard.xlsx",
            metabolites=10,
            samples=5,
        )

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)
    window.show()
    controller.select_input("C:/input.xlsx")
    window.cards[STEP1_NAME].run_button.click()
    _wait_until(entered.is_set)

    window.close()
    _app().processEvents()

    assert window.isVisible()
    assert controller.is_running

    release.set()
    _wait_until(lambda: not controller.is_running)
    window.close()
    _app().processEvents()
    assert not window.isVisible()
