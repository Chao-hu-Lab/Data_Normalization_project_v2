import os
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QSplitter, QStatusBar

from metabolomics.gui import theme
from metabolomics.gui.workflow import STEP1_NAME, STEP2_NAME, STEP4_NAME, StepState
from metabolomics.gui_qt.app import DNPMainWindow, STEP_NAMES, VISIBLE_STATES, StepCard
from metabolomics.gui_qt.controller import WorkflowController
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome
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
    assert set(window.step_cards) == set(STEP_NAMES)
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


def test_p3_window_uses_real_cards_pills_file_bar_and_status_bar():
    app = qt_app()
    controller = WorkflowController(
        processors={},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)
    window.show()
    app.processEvents()

    assert all(isinstance(card, StepCard) for card in window.step_cards.values())
    assert all(isinstance(card, QFrame) for card in window.step_cards.values())
    assert [card.objectName() for card in window.step_cards.values()] == [
        "stepCard1",
        "stepCard2",
        "stepCard3",
        "stepCard4",
    ]
    assert all(
        card.status_label.objectName() == "statusPill"
        for card in window.step_cards.values()
    )
    assert window.file_bar.objectName() == "fileBar"
    assert isinstance(window.statusBar(), QStatusBar)
    assert window.step_cards[STEP4_NAME].note_label.text() == (
        "(paused / diagnostics-only)"
    )
    window.close()


def test_p3_chain_of_custody_and_single_accent_follow_workflow_state():
    app = qt_app()
    controller = WorkflowController(
        processors={},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)
    window.show()

    controller.select_input("C:/input/raw.xlsx")
    app.processEvents()

    first = window.step_cards[STEP1_NAME]
    second = window.step_cards[STEP2_NAME]
    assert window.file_label.text() == "raw.xlsx"
    assert first.input_source_label.text() == "raw.xlsx"
    assert second.input_source_label.text() == "Output from Step 1"
    assert first.property("nextStep") is True
    assert second.property("nextStep") is False
    assert first.run_button.objectName() == "primaryAction"

    controller.workflow.begin(STEP1_NAME)
    controller.workflow.complete(
        STEP1_NAME,
        ProcessingResult(
            file_path="C:/input/raw.xlsx",
            output_path="C:/session/step1.xlsx",
            metabolites=10,
            samples=5,
        ),
    )
    controller.changed.emit()
    app.processEvents()

    assert second.input_source_label.text() == "← step1.xlsx"
    assert first.property("nextStep") is False
    assert second.property("nextStep") is True
    assert second.run_button.objectName() == "primaryAction"
    window.close()


def test_p3_status_pill_exposes_all_six_state_tokens():
    card = StepCard(STEP1_NAME, step_number=1)

    for state, (label, token) in VISIBLE_STATES.items():
        card.render(
            state,
            can_run=False,
            is_next_step=False,
            input_source="Waiting for file selection...",
            has_excel=False,
            has_plots=False,
        )
        assert card.status_label.text() == label
        assert card.status_label.property("state") == token

    card.close()


def test_p3_artifact_actions_enable_only_for_success_and_open_qt_urls(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "step1.xlsx"
    output.write_bytes(b"workbook")
    plots = tmp_path / "plots"
    plots.mkdir()
    legacy_plots = tmp_path / "legacy_plots"
    legacy_plots.mkdir()

    def processor(**kwargs):
        return ProcessingResult(
            file_path=kwargs["input_file"],
            output_path=str(output),
            plots_dir=str(legacy_plots),
            metabolites=10,
            samples=5,
        )

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: str(tmp_path),
    )
    window = DNPMainWindow(controller=controller)
    window.show()
    controller.select_input(str(tmp_path / "input.xlsx"))
    window.step_cards[STEP1_NAME].run_button.click()
    wait_until(lambda: not controller.is_running)

    card = window.step_cards[STEP1_NAME]
    assert card.excel_button.isEnabled()
    assert card.plots_button.isEnabled()

    opened = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    card.excel_button.click()
    card.plots_button.click()

    assert [Path(path) for path in opened] == [output.resolve(), plots.resolve()]
    assert window.session_label.text() == f"Session: {tmp_path}"
    window.close()


def test_p3_skipped_result_updates_custody_without_enabling_artifacts(tmp_path):
    output = tmp_path / "passthrough.xlsx"
    output.write_bytes(b"workbook")
    plots = tmp_path / "plots"
    plots.mkdir()

    controller = WorkflowController(
        processors={},
        session_factory=lambda _input: str(tmp_path),
    )
    window = DNPMainWindow(controller=controller)
    controller.select_input(str(tmp_path / "input.xlsx"))
    controller.workflow.begin(STEP1_NAME)
    controller.workflow.complete(
        STEP1_NAME,
        ProcessingResult(
            file_path=str(tmp_path / "input.xlsx"),
            output_path=str(output),
            plots_dir=str(plots),
            metabolites=10,
            samples=5,
            status=WorkflowOutcome.SKIPPED,
            reason="insufficient_good_istd",
        ),
    )
    controller.changed.emit()
    qt_app().processEvents()

    first = window.step_cards[STEP1_NAME]
    assert not first.excel_button.isEnabled()
    assert not first.plots_button.isEnabled()
    assert window.step_cards[STEP2_NAME].input_source_label.text() == (
        "← passthrough.xlsx"
    )
    window.close()


def test_p3_import_preprocessing_is_functional(tmp_path, monkeypatch):
    source = tmp_path / "preprocessed.xlsx"
    converted = tmp_path / "DNP_import_preprocessed.xlsx"
    source.write_bytes(b"source")
    calls = []

    monkeypatch.setattr(
        "metabolomics.gui_qt.app.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    monkeypatch.setattr(
        "metabolomics.gui_qt.app._load_preprocessing_adapter",
        lambda: lambda source_path, output_path: (
            calls.append((source_path, output_path)) or str(converted)
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)

    controller = WorkflowController(
        processors={},
        session_factory=lambda _input: str(tmp_path),
    )
    window = DNPMainWindow(controller=controller)
    window.import_button.click()
    qt_app().processEvents()

    assert calls == [(str(source), str(converted))]
    assert controller.workflow.selected_file_path == str(converted)
    assert window.file_label.text() == converted.name
    window.close()


def test_p3_session_reset_colored_log_and_real_density_grab():
    app = qt_app()
    controller = WorkflowController(
        processors={},
        session_factory=lambda _input: "C:/session",
    )
    window = DNPMainWindow(controller=controller)
    window.resize(1280, 760)
    window.show()
    app.processEvents()

    controller.session_changed.emit("C:/session/run-001")
    controller.log_line.emit("error", "example failure")
    app.processEvents()

    assert window.session_label.text() == "Session: C:/session/run-001"
    assert theme.resolve("log_error", window.theme_manager.mode) in window.log.toHtml()
    assert not window.grab().isNull()
    assert len(window.findChildren(QLabel, "pageTitle")) == 1

    controller.select_input("C:/input/new.xlsx")
    app.processEvents()
    assert window.session_label.text() == "Session: none yet"
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

    window.step_cards[STEP1_NAME].run_button.click()
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert window.step_cards[STEP1_NAME].status_label.text() == "Done"
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
    window.step_cards[STEP1_NAME].run_button.click()
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
    window.step_cards[STEP1_NAME].run_button.click()
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
