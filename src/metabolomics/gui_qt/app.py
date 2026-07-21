"""Production PySide6 view for the DNP workflow."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QDesktopServices,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from metabolomics.gui import theme
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


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _step_title(step_name: str) -> tuple[str, str]:
    title = step_name.split(":", 1)[-1].strip()
    if step_name == STEP4_NAME:
        return title, "(paused / diagnostics-only)"
    return title, ""


def _load_preprocessing_adapter():
    from metabolomics.adapters.preprocessing_to_dnp import convert_preprocessing_to_dnp

    return convert_preprocessing_to_dnp


class StepCard(QFrame):
    run_requested = Signal(str)
    open_excel_requested = Signal(str)
    open_plots_requested = Signal(str)
    method_changed = Signal(str)

    def __init__(self, step_name: str, step_number: int) -> None:
        super().__init__()
        self.step_name = step_name
        self.setObjectName(f"stepCard{step_number}")
        self.setProperty("nextStep", False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        badge = QFrame()
        badge.setObjectName("stepBadge")
        badge.setFixedWidth(82)
        badge_layout = QVBoxLayout(badge)
        # Top-align "Step N" with the card title's baseline instead of centring
        # it over the full card height (which floats it between the title and
        # the input row). Top margin is tuned to match the info column so the
        # number reads as the heading of the title row.
        badge_layout.setContentsMargins(8, 14, 8, 8)
        badge_label = QLabel(f"Step {step_number}")
        badge_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        badge_layout.addWidget(badge_label)
        badge_layout.addStretch(1)
        layout.addWidget(badge)

        info = QWidget()
        info.setObjectName("cardInfo")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(16, 10, 16, 10)
        info_layout.setSpacing(5)

        title_row = QHBoxLayout()
        title, note = _step_title(step_name)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        title_row.addWidget(self.title_label)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusPill")
        self.status_label.setProperty("state", "idle")
        title_row.addWidget(self.status_label)
        title_row.addStretch(1)
        info_layout.addLayout(title_row)

        self.note_label = QLabel(note)
        self.note_label.setObjectName("cardHint")
        self.note_label.setVisible(bool(note))
        info_layout.addWidget(self.note_label)

        input_row = QHBoxLayout()
        input_label = QLabel("Input:")
        input_label.setObjectName("chainLabel")
        input_row.addWidget(input_label)
        self.input_source_label = QLabel(
            "Waiting for file selection..."
            if step_number == 1
            else f"Output from Step {step_number - 1}"
        )
        self.input_source_label.setObjectName("chainSource")
        self.input_source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        input_row.addWidget(self.input_source_label, 1)
        info_layout.addLayout(input_row)

        self.method_combo: QComboBox | None = None
        self.method_hint: QLabel | None = None
        if step_name == STEP3_NAME:
            method_row = QHBoxLayout()
            method_row.addWidget(QLabel("Method:"))
            self.method_combo = QComboBox()
            for label, value in STEP3_METHOD_OPTIONS:
                self.method_combo.addItem(label, value)
            self.method_combo.currentIndexChanged.connect(self._emit_method)
            method_row.addWidget(self.method_combo, 1)
            info_layout.addLayout(method_row)
            self.method_hint = QLabel(
                "Default builds a QC-based reference; plain PQN is reference-free."
            )
            self.method_hint.setObjectName("cardHint")
            self.method_hint.setWordWrap(True)
            info_layout.addWidget(self.method_hint)

        layout.addWidget(info, 1)

        actions = QFrame()
        actions.setObjectName("cardActionPanel")
        actions.setFixedWidth(236)
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(14, 10, 14, 10)
        action_layout.setSpacing(6)
        action_layout.addStretch(1)

        self.run_button = QPushButton("Run Step")
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self.step_name))
        action_layout.addWidget(self.run_button)

        artifacts = QHBoxLayout()
        artifacts.setSpacing(6)
        self.excel_button = QPushButton("Open Excel")
        self.excel_button.clicked.connect(
            lambda: self.open_excel_requested.emit(self.step_name)
        )
        artifacts.addWidget(self.excel_button)
        self.plots_button = QPushButton("Open Plots")
        self.plots_button.clicked.connect(
            lambda: self.open_plots_requested.emit(self.step_name)
        )
        artifacts.addWidget(self.plots_button)
        action_layout.addLayout(artifacts)
        action_layout.addStretch(1)
        layout.addWidget(actions)

    def render(
        self,
        state: StepState,
        can_run: bool,
        is_next_step: bool,
        input_source: str,
        has_excel: bool,
        has_plots: bool,
    ) -> None:
        label, token = VISIBLE_STATES[state]
        self.status_label.setText(label)
        self.status_label.setProperty("state", token)
        _repolish(self.status_label)

        self.setProperty("nextStep", is_next_step)
        _repolish(self)
        self.run_button.setObjectName("primaryAction" if is_next_step else "runStepButton")
        _repolish(self.run_button)

        self.input_source_label.setText(input_source)
        self.run_button.setEnabled(can_run)
        self.excel_button.setEnabled(has_excel)
        self.plots_button.setEnabled(has_plots)

    def set_method_enabled(self, enabled: bool) -> None:
        if self.method_combo is not None:
            self.method_combo.setEnabled(enabled)

    def _emit_method(self, index: int) -> None:
        if self.method_combo is not None and index >= 0:
            self.method_changed.emit(self.method_combo.itemData(index))


class DNPMainWindow(QMainWindow):
    """Production Qt view over ``WorkflowController``."""

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
        self._apply_window_defaults()

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

        divider = QFrame()
        divider.setObjectName("pageDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)

        self.file_bar = QFrame()
        self.file_bar.setObjectName("fileBar")
        file_layout = QHBoxLayout(self.file_bar)
        file_layout.setContentsMargins(14, 10, 14, 10)
        file_layout.setSpacing(10)
        file_layout.addWidget(QLabel("Input"))
        self.file_label = QLabel("No file selected...")
        self.file_label.setObjectName("selectedFile")
        self.file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        file_layout.addWidget(self.file_label, 1)
        self.import_button = QPushButton("Import Preprocessing")
        self.import_button.setObjectName("importButton")
        self.import_button.clicked.connect(self._import_preprocessing)
        file_layout.addWidget(self.import_button)
        self.browse_button = QPushButton("Browse")
        self.browse_button.setObjectName("browseButton")
        self.browse_button.clicked.connect(self._browse)
        file_layout.addWidget(self.browse_button)
        root.addWidget(self.file_bar)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.auto_button = QPushButton("Auto Run")
        self.auto_button.setObjectName("autoRunButton")
        self.auto_button.clicked.connect(self._start_auto_run)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self.controller.request_stop)
        self.reset_button = QPushButton("Reset Workflow")
        self.reset_button.setObjectName("resetButton")
        self.reset_button.clicked.connect(self.controller.reset)
        controls.addWidget(self.auto_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.reset_button)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("workspaceSplitter")
        splitter.setChildrenCollapsible(False)

        step_container = QWidget()
        step_container.setObjectName("workflowCards")
        step_layout = QVBoxLayout(step_container)
        step_layout.setContentsMargins(0, 0, 6, 0)
        step_layout.setSpacing(8)
        self.step_cards: dict[str, StepCard] = {}
        for step_number, step_name in enumerate(STEP_NAMES, start=1):
            step_card = StepCard(step_name, step_number)
            step_card.run_requested.connect(self._start_step)
            step_card.open_excel_requested.connect(self._open_step_excel)
            step_card.open_plots_requested.connect(self._open_step_plots)
            step_card.method_changed.connect(self.controller.set_normalization_method)
            self.step_cards[step_name] = step_card
            step_layout.addWidget(step_card, 1)
        splitter.addWidget(step_container)

        log_pane = QFrame()
        log_pane.setObjectName("logPane")
        log_layout = QVBoxLayout(log_pane)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Real-time execution output"))
        log_header.addStretch(1)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(lambda: self.log.clear())
        log_header.addWidget(clear_button)
        log_layout.addLayout(log_header)
        self.log = QTextEdit()
        self.log.setObjectName("executionLog")
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log, 1)
        splitter.addWidget(log_pane)
        splitter.setStretchFactor(0, 47)
        splitter.setStretchFactor(1, 53)
        splitter.setSizes([470, 530])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        status.addWidget(QLabel("Progress"))
        self.progress_label = QLabel("Not started")
        self.progress_label.setObjectName("progressText")
        status.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progressHeartbeat")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        status.addWidget(self.progress_bar)
        self.session_label = QLabel("Session: none yet")
        self.session_label.setObjectName("sessionPath")
        self.session_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status.addPermanentWidget(self.session_label, 1)
        self.setStatusBar(status)

        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(400)
        self.heartbeat.timeout.connect(self._advance_heartbeat)

        self.run_next_shortcuts = [
            QShortcut(QKeySequence(Qt.Key.Key_Return), self),
            QShortcut(QKeySequence(Qt.Key.Key_Enter), self),
        ]
        for shortcut in self.run_next_shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(self._run_next_step)
        self.stop_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.stop_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.stop_shortcut.activated.connect(self._stop_from_shortcut)

    def _apply_window_defaults(self) -> None:
        available = self.screen().availableGeometry()
        # Never demand more than the current work area can actually show. On
        # small laptops or Windows display scaling, availableGeometry() is in
        # logical pixels (e.g. 1080p @150% -> ~1280x720), so a hard-coded
        # 1200x700 minimum would push controls off-screen. Leave headroom for
        # the title bar / window frame and clamp the design minimum to fit.
        max_w = max(320, available.width() - 32)
        max_h = max(320, available.height() - 48)
        min_w = min(1200, max_w)
        min_h = min(700, max_h)
        self.setMinimumSize(min_w, min_h)
        self.resize(min(1480, max_w), min(940, max_h))

    @staticmethod
    def _focus_consumes_workflow_shortcut() -> bool:
        focused = QApplication.focusWidget()
        return isinstance(focused, (QComboBox, QLineEdit, QPlainTextEdit, QTextEdit))

    def _run_next_step(self) -> None:
        if self._focus_consumes_workflow_shortcut() or self.controller.is_running:
            return
        next_step = self._next_workflow_step()
        if next_step is not None:
            self._start_step(next_step)

    def _next_workflow_step(self) -> str | None:
        workflow = self.controller.workflow
        if not workflow.selected_file_path:
            return None
        completed = workflow.completed_steps
        for index, step_name in enumerate(STEP_NAMES):
            if step_name in completed:
                continue
            predecessor_ready = index == 0 or STEP_NAMES[index - 1] in completed
            if predecessor_ready:
                return step_name
            return None
        return None

    def _stop_from_shortcut(self) -> None:
        if not self._focus_consumes_workflow_shortcut():
            self.controller.request_stop()

    def _connect_controller(self) -> None:
        self.controller.changed.connect(self._render)
        self.controller.busy_changed.connect(self._set_busy)
        self.controller.log_line.connect(self._append_log)
        self.controller.notice.connect(self._show_notice)
        self.controller.session_changed.connect(self._update_session)

    def _browse(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select metabolomics workbook",
            "",
            "Excel workbooks (*.xlsx *.xls);;All files (*)",
        )
        if file_path:
            self.controller.select_input(file_path)

    def _import_preprocessing(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select ms-preprocessing output file",
            "",
            "Excel workbooks (*.xlsx *.xls);;All files (*)",
        )
        if not file_path:
            return

        source = Path(file_path)
        output_path = source.with_name(f"DNP_import_{source.stem}.xlsx")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._append_log("info", f"Converting preprocessing output: {source}")
            convert = _load_preprocessing_adapter()
            result_path = convert(str(source), str(output_path))
            self.controller.select_input(str(result_path))
            self._append_log("success", f"Conversion complete: {result_path}")
            QMessageBox.information(
                self,
                "Import Successful",
                f"File converted and loaded:\n{Path(result_path).name}",
            )
        except Exception as exc:
            self._append_log("error", f"Import from preprocessing failed: {exc}")
            QMessageBox.critical(self, "Import Failed", f"Conversion error:\n{exc}")
        finally:
            QApplication.restoreOverrideCursor()

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
        self.file_label.setText(Path(selected).name if selected else "No file selected...")
        self.file_label.setToolTip(selected or "")
        completed = workflow.completed_steps

        next_step = self._next_workflow_step()

        for index, step_name in enumerate(STEP_NAMES):
            if index == 0:
                predecessor_ready = bool(selected)
                input_source = (
                    Path(selected).name if selected else "Waiting for file selection..."
                )
            else:
                previous = STEP_NAMES[index - 1]
                predecessor_ready = previous in completed
                previous_result = workflow.result_for(previous)
                input_source = (
                    f"← {Path(previous_result.output_path).name}"
                    if previous_result is not None
                    else f"Output from Step {index}"
                )

            state = workflow.status_of(step_name)
            result = workflow.result_for(step_name)
            plots_path = self._plots_path_for(result)
            self.step_cards[step_name].render(
                state,
                can_run=not busy and predecessor_ready,
                is_next_step=step_name == next_step,
                input_source=input_source,
                has_excel=state is StepState.SUCCEEDED and result is not None,
                has_plots=(
                    state is StepState.SUCCEEDED
                    and plots_path is not None
                    and plots_path.is_dir()
                ),
            )
            self.step_cards[step_name].set_method_enabled(not busy)

        self.browse_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
        self.auto_button.setEnabled(not busy and bool(selected))
        self.stop_button.setEnabled(busy and not workflow.stop_requested)
        self.reset_button.setEnabled(not busy)

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._heartbeat_frame = 0
            self.heartbeat.start()
            self.progress_bar.setRange(0, 0)
            self._advance_heartbeat()
        else:
            self.heartbeat.stop()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_label.setText("Not running")
        self._render()

    def _advance_heartbeat(self) -> None:
        self._heartbeat_frame = (self._heartbeat_frame + 1) % 4
        self.progress_label.setText("Running" + "." * self._heartbeat_frame)

    def _append_log(self, level: str, message: str) -> None:
        normalized_level = level.lower()
        token = {
            "error": "log_error",
            "warning": "log_warning",
            "success": "log_success",
        }.get(normalized_level, "log_info")
        color = QColor(theme.resolve(token, self.theme_manager.mode))
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        text_format = QTextCharFormat()
        text_format.setForeground(color)
        for line in message.splitlines() or [""]:
            cursor.insertText(f"[{level.upper()}] {line}\n", text_format)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _update_session(self, session_dir: str) -> None:
        self.session_label.setText(
            f"Session: {session_dir}" if session_dir else "Session: none yet"
        )
        if session_dir:
            self._append_log("info", f"Session: {session_dir}")

    def _plots_path_for(self, result) -> Path | None:
        if self.controller.session_dir:
            return Path(self.controller.session_dir) / "plots"
        if result is not None and result.plots_dir:
            return Path(result.plots_dir)
        return None

    def _open_step_excel(self, step_name: str) -> None:
        result = self.controller.workflow.result_for(step_name)
        path = Path(result.output_path) if result is not None else None
        self._open_path(path, "No output generated for this step yet")

    def _open_step_plots(self, step_name: str) -> None:
        result = self.controller.workflow.result_for(step_name)
        self._open_path(self._plots_path_for(result), "No plots generated yet")

    def _open_path(self, path: Path | None, missing_message: str) -> None:
        if path is None or not path.exists():
            QMessageBox.warning(self, "Notice", missing_message)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self._append_log("error", f"Cannot open path: {path}")
            QMessageBox.warning(self, "Cannot open", f"Cannot open:\n{path}")

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
            self.progress_label.setText(
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
