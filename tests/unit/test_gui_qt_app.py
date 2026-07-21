import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox, QSplitter

from metabolomics.gui.workflow import STEP1_NAME, StepState
from metabolomics.gui_qt.app import DNPMainWindow, STEP_NAMES, VISIBLE_STATES
from metabolomics.gui_qt.controller import WorkflowController
from metabolomics.utils.results import ProcessingResult
from tests.gui_qt_helpers import qt_app, wait_until


def test_p2_window_starts_with_four_plain_rows_and_six_visible_states():
    app = qt_app()
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
    assert set(window.step_rows) == set(STEP_NAMES)
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

    window.step_rows[STEP1_NAME].run_button.click()
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert window.step_rows[STEP1_NAME].status_label.text() == "Done"
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
    window.step_rows[STEP1_NAME].run_button.click()
    wait_until(entered.is_set)

    assert window.heartbeat.isActive()
    assert window.progress_label.text().startswith("Running")

    controller.request_stop()
    release.set()
    wait_until(lambda: not controller.is_running)

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
    window.step_rows[STEP1_NAME].run_button.click()
    wait_until(entered.is_set)

    window.close()
    qt_app().processEvents()

    assert window.isVisible()
    assert controller.is_running

    release.set()
    wait_until(lambda: not controller.is_running)
    window.close()
    qt_app().processEvents()
    assert not window.isVisible()
