"""Qt controller glue around the frozen workflow and processor contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from metabolomics.gui.workflow import (
    DEFAULT_STEP3_METHOD,
    STEP1_NAME,
    STEP2_NAME,
    STEP3_NAME,
    STEP3_METHOD_OPTIONS,
    STEP4_NAME,
    StepState,
    WorkflowState,
    build_workflow_steps,
    get_auto_run_terminal_step_name,
)
from metabolomics.gui_qt.workers import Processor, ProcessorWorker
from metabolomics.utils import file_io
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome


SessionFactory = Callable[[str], str]


def skip_guidance(step_name: str, reason: str) -> str:
    """Return the established human guidance for a processor skip outcome."""
    if step_name == STEP1_NAME and reason == "insufficient_good_istd":
        return (
            "Step 1 found too few usable ISTDs. Step 2 will continue from "
            "RawIntensity in the selected workbook."
        )
    if step_name == STEP4_NAME and reason == "single_batch":
        return (
            "Only a single batch was detected, so cross-batch diagnostics are not "
            "needed. The Step 3 workbook remains the final normalized output."
        )
    if step_name == STEP4_NAME and reason == "paused_nonshared_qc_design":
        return (
            "Active batch scaling is paused for this QC design. Step 4 stays "
            "diagnostics-only and the Step 3 workbook remains the primary output."
        )
    return f"{step_name} was skipped ({reason}). Downstream uses its returned input."


def _default_processors() -> dict[str, Processor]:
    from metabolomics.processors import istd, normalization, qc_batch_scaling, qc_lowess

    return {
        STEP1_NAME: istd.main,
        STEP2_NAME: qc_lowess.main,
        STEP3_NAME: normalization.main,
        STEP4_NAME: qc_batch_scaling.main,
    }


def _default_session_factory(input_file: str) -> str:
    output_root = file_io.get_output_root(input_file=input_file)
    return str(file_io.create_session_dir(output_root=output_root))


class WorkflowController(QObject):
    """Run the DNP workflow while keeping all widget access in the GUI thread."""

    changed = Signal()
    busy_changed = Signal(bool)
    log_line = Signal(str, str)
    notice = Signal(str, str, str, str)
    session_changed = Signal(str)

    def __init__(
        self,
        processors: Mapping[str, Processor] | None = None,
        session_factory: SessionFactory | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        step_names = tuple(step["name"] for step in build_workflow_steps())
        self.workflow = WorkflowState(step_names)
        self._processors = dict(processors) if processors is not None else _default_processors()
        self._session_factory = session_factory or _default_session_factory
        self._session_dir: str | None = None
        self._normalization_method = DEFAULT_STEP3_METHOD
        self._thread: QThread | None = None
        self._worker: ProcessorWorker | None = None
        self._active_run_id: str | None = None
        self._active_step: str | None = None
        self._terminal_run_ids: set[str] = set()
        self._pending_auto_step: str | None = None
        self._last_failed_step: str | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    @property
    def session_dir(self) -> str | None:
        return self._session_dir

    @property
    def normalization_method(self) -> str:
        return self._normalization_method

    def select_input(self, file_path: str) -> None:
        self.workflow.select_input(file_path)
        self._session_dir = None
        self._last_failed_step = None
        self.session_changed.emit("")
        self.changed.emit()

    def reset(self) -> None:
        if self.is_running:
            raise RuntimeError("Cannot reset while a workflow step is running")
        self.workflow.reset()
        self._session_dir = None
        self._last_failed_step = None
        self.session_changed.emit("")
        self.changed.emit()

    def set_normalization_method(self, method: str) -> None:
        if self.is_running:
            raise RuntimeError("Cannot change normalization method while a step is running")
        valid_methods = {value for _label, value in STEP3_METHOD_OPTIONS}
        if method not in valid_methods:
            raise ValueError(f"Unsupported normalization method: {method!r}")
        self._normalization_method = method
        self.changed.emit()

    def start_step(self, step_name: str) -> str:
        if self.is_running:
            raise RuntimeError("A workflow step is already running")
        processor = self._processors.get(step_name)
        if processor is None:
            raise KeyError(f"No processor configured for {step_name}")

        input_file = self.workflow.resolve_input(step_name)
        if self._session_dir is None:
            selected_file = self.workflow.selected_file_path
            if not selected_file:
                raise ValueError("Please select an input file first")
            self._session_dir = self._session_factory(selected_file)
            self.session_changed.emit(self._session_dir)

        self.workflow.begin(step_name)
        run_id = uuid4().hex
        kwargs: dict[str, object] = {
            "input_file": input_file,
            "session_dir": self._session_dir,
        }
        if step_name == STEP3_NAME:
            kwargs["normalization_method"] = self._normalization_method
        elif step_name == STEP4_NAME:
            kwargs["diagnostics_only"] = True

        thread = QThread(self)
        worker = ProcessorWorker(run_id, processor, kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_line.connect(self._on_log_line)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        self._active_run_id = run_id
        self._active_step = step_name
        self._pending_auto_step = None
        self.changed.emit()
        self.busy_changed.emit(True)
        self.log_line.emit("info", f"Starting {step_name}")
        thread.start()
        return run_id

    def start_auto_run(self) -> str:
        if self.is_running:
            raise RuntimeError("A workflow step is already running")
        self.workflow.start_auto_run()
        return self.start_step(STEP1_NAME)

    def retry_step(self, step_name: str) -> str:
        if self._last_failed_step != step_name:
            raise RuntimeError(f"No failed run is available to retry for {step_name}")
        if self.workflow.status_of(step_name) is not StepState.FAILED:
            raise RuntimeError(f"Step is not failed: {step_name}")
        return self.start_step(step_name)

    def request_stop(self) -> bool:
        requested = self.workflow.request_stop()
        if requested:
            self.log_line.emit(
                "warning",
                "Stop requested; finishing the current calculation before discarding it.",
            )
            self.changed.emit()
        return requested

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        thread = self._thread
        if thread is None:
            return True
        self.request_stop()
        thread.quit()
        if not thread.wait(timeout_ms):
            return False
        if self._active_run_id not in self._terminal_run_ids and self._active_step:
            self._terminal_run_ids.add(self._active_run_id)
            self.workflow.cancel(self._active_step, "Application closed during processing")
        self._drop_thread_references(thread)
        self.changed.emit()
        self.busy_changed.emit(False)
        return True

    @Slot(str, str, str)
    def _on_log_line(self, run_id: str, level: str, message: str) -> None:
        if run_id == self._active_run_id and run_id not in self._terminal_run_ids:
            self.log_line.emit(level, message)

    @Slot(str, object)
    def _on_finished(self, run_id: str, result: ProcessingResult) -> None:
        if not self._claim_terminal(run_id):
            return
        step_name = self._active_step
        if step_name is None:
            return

        was_auto_run = self.workflow.auto_run
        if self.workflow.should_discard_result(step_name):
            self.workflow.cancel(step_name, "Stopped; finished result was discarded")
            self.log_line.emit("warning", f"Discarded finished result for {step_name}")
        else:
            self.workflow.complete(step_name, result)
            if result.status is WorkflowOutcome.SKIPPED:
                guidance = skip_guidance(step_name, result.reason or "unknown")
                self.log_line.emit(
                    "warning",
                    f"{step_name} skipped: {result.reason}. {guidance}",
                )
                if not was_auto_run:
                    self.notice.emit("skip", "Step skipped", guidance, step_name)
            self._pending_auto_step = self.workflow.next_auto_step(
                step_name,
                get_auto_run_terminal_step_name(),
            )
            if was_auto_run and self._pending_auto_step is None:
                self.notice.emit(
                    "info",
                    "Auto Run complete",
                    "Steps 1–3 finished. Step 4 remains manual diagnostics-only.",
                    step_name,
                )

        self.changed.emit()
        self._request_thread_quit()

    @Slot(str, str)
    def _on_failed(self, run_id: str, traceback_text: str) -> None:
        if not self._claim_terminal(run_id):
            return
        step_name = self._active_step
        if step_name is None:
            return
        summary = traceback_text.strip().splitlines()[-1]
        self.workflow.fail(step_name, summary)
        self._last_failed_step = step_name
        self.log_line.emit("error", traceback_text.rstrip())
        self.notice.emit(
            "retry",
            "Step failed",
            "The step failed. See the Log panel for details. Retry?",
            step_name,
        )
        self.changed.emit()
        self._request_thread_quit()

    def _claim_terminal(self, run_id: str) -> bool:
        if run_id != self._active_run_id or run_id in self._terminal_run_ids:
            return False
        self._terminal_run_ids.add(run_id)
        return True

    def _request_thread_quit(self) -> None:
        if self._thread is not None:
            self._thread.quit()

    @Slot()
    def _on_thread_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, QThread) or thread is not self._thread:
            return
        pending_step = self._pending_auto_step
        self._drop_thread_references(thread)
        self.changed.emit()
        self.busy_changed.emit(False)
        if pending_step is not None:
            QTimer.singleShot(0, lambda: self.start_step(pending_step))

    def _drop_thread_references(self, thread: QThread) -> None:
        thread.wait(0)
        if self._worker is not None:
            self._worker.deleteLater()
        thread.deleteLater()
        self._thread = None
        self._worker = None
        self._active_run_id = None
        self._active_step = None
        self._pending_auto_step = None
