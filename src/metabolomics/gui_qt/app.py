"""P2 functional PySide6 GUI for the DNP workflow."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from metabolomics.gui.workflow import (
    STEP1_NAME,
    STEP2_NAME,
    STEP3_METHOD_OPTIONS,
    STEP3_NAME,
    STEP4_NAME,
    StepState,
)
from metabolomics.gui_qt.controller import WorkflowController
from metabolomics.gui_qt.qss import ThemeManager
from metabolomics.gui_qt.theme_controls import ThemeSelector


WINDOW_TITLE = "Data Normalization Workflow v2"
STEP_NAMES = (STEP1_NAME, STEP2_NAME, STEP3_NAME, STEP4_NAME)
VISIBLE_STATES = {
    StepState.PENDING: ("Idle", "idle"),
    StepState.RUNNING: ("Running", "running"),
    StepState.SUCCEEDED: ("Done", "done"),
    StepState.SKIPPED: ("Skipped", "skipped"),
    StepState.FAILED: ("Error", "error"),
    StepState.CANCELLED: ("Cancelled", "cancelled"),
}


class StepCard(QFrame):
    run_requested = Signal(str)
    method_changed = Signal(str)

    def __init__(self, step_number: int, step_name: str) -> None:
        super().__init__()
        self.step_name = step_name
        self.setObjectName(f"stepCard{step_number}")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        badge = QFrame()
        badge.setObjectName("stepBadge")
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(7, 3, 7, 3)
        badge_layout.addWidget(QLabel(f"Step {step_number}"))
        header.addWidget(badge)
        title = QLabel(step_name.replace(f"Step {step_number}: ", ""))
        title.setWordWrap(True)
        header.addWidget(title, 1)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusPill")
        self.status_label.setProperty("state", "idle")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Input:"))
        self.input_label = QLabel("Waiting for upstream output...")
        self.input_label.setObjectName("cardHint")
        self.input_label.setWordWrap(True)
        source_row.addWidget(self.input_label, 1)
        layout.addLayout(source_row)

        self.method_combo: QComboBox | None = None
        if step_name == STEP3_NAME:
            method_row = QHBoxLayout()
            method_row.addWidget(QLabel("Method:"))
            self.method_combo = QComboBox()
            for label, value in STEP3_METHOD_OPTIONS:
                self.method_combo.addItem(label, value)
            self.method_combo.currentIndexChanged.connect(self._emit_method)
            method_row.addWidget(self.method_combo, 1)
            layout.addLayout(method_row)

        self.run_button = QPushButton("Run Step")
        self.run_button.setObjectName("primaryAction")
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self.step_name))
        layout.addWidget(self.run_button)

    def render(self, state: StepState, input_text: str, can_run: bool) -> None:
        label, token = VISIBLE_STATES[state]
        self.status_label.setText(label)
        self.status_label.setProperty("state", token)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.input_label.setText(input_text)
        self.run_button.setEnabled(can_run)

    def set_method_enabled(self, enabled: bool) -> None:
        if self.method_combo is not None:
            self.method_combo.setEnabled(enabled)

    def _emit_method(self, index: int) -> None:
        if self.method_combo is not None and index >= 0:
            self.method_changed.emit(self.method_combo.itemData(index))


class DNPMainWindow(QMainWindow):
    """Deliberately plain P2 view over ``WorkflowController``."""

    def __init__(
        self,
        controller: WorkflowController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("DNPMainWindow requires an active QApplication")

        self.controller = controller or WorkflowController(parent=self)
        self.theme_manager = ThemeManager(app, preference="system")
        self._heartbeat_frame = 0
        self._build_ui()
        self._connect_controller()
        self._render()

    def _build_ui(self) -> None:
        self.setObjectName("dnpQtMainWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1480, 940)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        central.setObjectName("centralWidget")
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel(WINDOW_TITLE)
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Metabolomics data processing pipeline | VBA-formatted Excel required"
        )
        subtitle.setObjectName("pageSubtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        title_row.addLayout(title_block, 1)
        title_row.addWidget(ThemeSelector(self.theme_manager))
        root.addLayout(title_row)

        file_bar = QFrame()
        file_bar.setObjectName("fileBar")
        file_layout = QHBoxLayout(file_bar)
        file_layout.setContentsMargins(10, 8, 10, 8)
        file_layout.addWidget(QLabel("Input"))
        self.file_label = QLabel("No file selected...")
        self.file_label.setObjectName("cardHint")
        self.file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        file_layout.addWidget(self.file_label, 1)
        self.browse_button = QPushButton("Browse")
        self.browse_button.setObjectName("browseButton")
        self.browse_button.clicked.connect(self._browse)
        file_layout.addWidget(self.browse_button)
        root.addWidget(file_bar)

        controls = QHBoxLayout()
        self.auto_button = QPushButton("Auto Run")
        self.auto_button.setObjectName("autoRunButton")
        self.auto_button.clicked.connect(self._start_auto_run)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self.controller.request_stop)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.controller.reset)
        controls.addWidget(self.auto_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.reset_button)
        controls.addStretch(1)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("workspaceSplitter")
        splitter.setChildrenCollapsible(False)

        scroll = QScrollArea()
        scroll.setObjectName("workflowScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        card_container = QWidget()
        card_container.setObjectName("workflowCards")
        card_layout = QVBoxLayout(card_container)
        card_layout.setContentsMargins(0, 0, 6, 0)
        card_layout.setSpacing(10)
        self.cards: dict[str, StepCard] = {}
        for step_number, step_name in enumerate(STEP_NAMES, start=1):
            card = StepCard(step_number, step_name)
            card.run_requested.connect(self._start_step)
            card.method_changed.connect(self.controller.set_normalization_method)
            self.cards[step_name] = card
            card_layout.addWidget(card)
        card_layout.addStretch(1)
        scroll.setWidget(card_container)
        splitter.addWidget(scroll)

        log_pane = QFrame()
        log_pane.setObjectName("logPane")
        log_layout = QVBoxLayout(log_pane)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Real-time execution output"))
        log_header.addStretch(1)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(lambda: self.log.clear())
        log_header.addWidget(clear_button)
        log_layout.addLayout(log_header)
        self.log = QPlainTextEdit()
        self.log.setObjectName("executionLog")
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log, 1)
        progress_row = QHBoxLayout()
        progress_row.addWidget(QLabel("Progress"))
        self.progress_label = QLabel("Not started")
        progress_row.addWidget(self.progress_label)
        progress_row.addStretch(1)
        log_layout.addLayout(progress_row)
        self.session_label = QLabel("Session: none yet")
        self.session_label.setObjectName("sessionPath")
        self.session_label.setWordWrap(True)
        log_layout.addWidget(self.session_label)
        splitter.addWidget(log_pane)
        splitter.setSizes([620, 800])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Select an input workbook to begin")

        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(400)
        self.heartbeat.timeout.connect(self._advance_heartbeat)

    def _connect_controller(self) -> None:
        self.controller.changed.connect(self._render)
        self.controller.busy_changed.connect(self._set_busy)
        self.controller.log_line.connect(self._append_log)
        self.controller.notice.connect(self._show_notice)
        self.controller.session_changed.connect(self._set_session)

    def _browse(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select metabolomics workbook",
            "",
            "Excel workbooks (*.xlsx *.xls);;All files (*)",
        )
        if file_path:
            self.controller.select_input(file_path)

    def _start_step(self, step_name: str) -> None:
        try:
            self.controller.start_step(step_name)
        except Exception as exc:
            self._append_log("error", str(exc))
            QMessageBox.warning(self, "Cannot run step", str(exc))

    def _start_auto_run(self) -> None:
        reply = QMessageBox.question(
            self,
            "Start Auto Run?",
            "Run Steps 1–3 in sequence? Step 4 remains manual diagnostics-only.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.controller.start_auto_run()

    def _render(self) -> None:
        workflow = self.controller.workflow
        busy = self.controller.is_running
        selected = workflow.selected_file_path
        self.file_label.setText(selected or "No file selected...")
        completed = workflow.completed_steps

        for index, step_name in enumerate(STEP_NAMES):
            if index == 0:
                input_text = Path(selected).name if selected else "Waiting for file selection..."
                predecessor_ready = bool(selected)
            else:
                previous = STEP_NAMES[index - 1]
                previous_result = workflow.result_for(previous)
                input_text = (
                    Path(previous_result.output_path).name
                    if previous_result is not None
                    else f"Output from Step {index}"
                )
                predecessor_ready = previous in completed
            self.cards[step_name].render(
                workflow.status_of(step_name),
                input_text,
                can_run=not busy and predecessor_ready,
            )
            self.cards[step_name].set_method_enabled(not busy)

        self.browse_button.setEnabled(not busy)
        self.auto_button.setEnabled(not busy and bool(selected))
        self.stop_button.setEnabled(busy and not workflow.stop_requested)
        self.reset_button.setEnabled(not busy)
        if workflow.active_step:
            self.statusBar().showMessage(workflow.active_step)
        elif selected:
            self.statusBar().showMessage("Ready")
        else:
            self.statusBar().showMessage("Select an input workbook to begin")

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._heartbeat_frame = 0
            self.heartbeat.start()
            self._advance_heartbeat()
        else:
            self.heartbeat.stop()
            self.progress_label.setText("Not running")
        self._render()

    def _advance_heartbeat(self) -> None:
        self._heartbeat_frame = (self._heartbeat_frame + 1) % 4
        self.progress_label.setText("Running" + "." * self._heartbeat_frame)

    def _append_log(self, level: str, message: str) -> None:
        for line in message.splitlines() or [""]:
            self.log.appendPlainText(f"[{level.upper()}] {line}")
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_session(self, session_dir: str) -> None:
        self.session_label.setText(
            f"Session: {session_dir}" if session_dir else "Session: none yet"
        )

    def _show_notice(
        self,
        kind: str,
        title: str,
        message: str,
        step_name: str,
    ) -> None:
        if kind == "retry":
            reply = QMessageBox.question(self, title, message)
            if reply == QMessageBox.StandardButton.Yes:
                self.controller.retry_step(step_name)
            return
        QMessageBox.information(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.controller.is_running:
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "Processing is still running",
            "Stop after the current calculation and close?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        if self.controller.shutdown(timeout_ms=1500):
            event.accept()
        else:
            self.statusBar().showMessage(
                "Still finishing the current calculation; close again when it completes."
            )
            event.ignore()


def build_main_window(
    controller: WorkflowController | None = None,
) -> DNPMainWindow:
    return DNPMainWindow(controller=controller)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = build_main_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
