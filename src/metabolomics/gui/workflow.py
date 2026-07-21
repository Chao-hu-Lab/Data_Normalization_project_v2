"""Pure workflow policy and state for the DNP GUI."""

from dataclasses import dataclass, field
from enum import Enum

from metabolomics.utils import normalization_contract
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome


STEP1_NAME = "Step 1: ISTD Correction"
STEP2_NAME = "Step 2: QC-LOESS"
STEP3_NAME = "Step 3: Concentration Normalization"
STEP4_NAME = "Step 4: QC Batch Scaling"
DEFAULT_STEP3_METHOD = normalization_contract.DEFAULT_NORMALIZATION_METHOD
STEP3_METHOD_OPTIONS = normalization_contract.STEP3_METHOD_OPTIONS


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = WorkflowOutcome.SUCCEEDED.value
    SKIPPED = WorkflowOutcome.SKIPPED.value
    FAILED = WorkflowOutcome.FAILED.value
    CANCELLED = WorkflowOutcome.CANCELLED.value


@dataclass
class WorkflowState:
    """Canonical workflow state with no dependency on Tk widgets."""

    step_names: tuple[str, ...]
    selected_file_path: str | None = None
    step_results: dict[str, ProcessingResult] = field(default_factory=dict)
    step_states: dict[str, StepState] = field(init=False)
    step_reasons: dict[str, str] = field(default_factory=dict)
    active_step: str | None = None
    stop_requested: bool = False
    auto_run: bool = False

    def __post_init__(self) -> None:
        self.step_names = tuple(self.step_names)
        if not self.step_names or len(set(self.step_names)) != len(self.step_names):
            raise ValueError("Workflow step names must be non-empty and unique")
        self.step_states = {name: StepState.PENDING for name in self.step_names}

    @property
    def completed_steps(self) -> set[str]:
        return {
            name
            for name, state in self.step_states.items()
            if state in {StepState.SUCCEEDED, StepState.SKIPPED}
        }

    def status_of(self, step_name: str) -> StepState:
        self._step_index(step_name)
        return self.step_states[step_name]

    def result_for(self, step_name: str) -> ProcessingResult | None:
        self._step_index(step_name)
        return self.step_results.get(step_name)

    def select_input(self, file_path: str) -> None:
        if not file_path:
            raise ValueError("Input file path must not be empty")
        self.selected_file_path = file_path
        self.reset_steps()

    def reset(self) -> None:
        self.selected_file_path = None
        self.reset_steps()

    def reset_steps(self) -> None:
        self.step_results.clear()
        self.step_reasons.clear()
        self.step_states = {name: StepState.PENDING for name in self.step_names}
        self.active_step = None
        self.stop_requested = False
        self.auto_run = False

    def invalidate_from(self, step_name: str) -> None:
        start_index = self._step_index(step_name)
        for name in self.step_names[start_index:]:
            self.step_results.pop(name, None)
            self.step_reasons.pop(name, None)
            self.step_states[name] = StepState.PENDING
        if self.active_step in self.step_names[start_index:]:
            self.active_step = None
            self.stop_requested = False

    def resolve_input(self, step_name: str) -> str:
        step_index = self._step_index(step_name)
        if step_index == 0:
            if not self.selected_file_path:
                raise ValueError("Please select an input file first")
            return self.selected_file_path

        previous_name = self.step_names[step_index - 1]
        previous_result = self.step_results.get(previous_name)
        if previous_result is None:
            raise ValueError(
                f"Previous output not found for {previous_name}. "
                "Please ensure the previous step succeeded or was skipped."
            )
        return previous_result.output_path

    def begin(self, step_name: str) -> None:
        if self.active_step is not None:
            raise RuntimeError(f"Workflow step already running: {self.active_step}")
        self.resolve_input(step_name)
        self.invalidate_from(step_name)
        self.active_step = step_name
        self.step_states[step_name] = StepState.RUNNING
        self.stop_requested = False

    def complete(self, step_name: str, result: ProcessingResult) -> None:
        self._require_active(step_name)
        if not isinstance(result, ProcessingResult):
            raise TypeError("Workflow steps must return ProcessingResult")

        final_state = {
            WorkflowOutcome.SUCCEEDED: StepState.SUCCEEDED,
            WorkflowOutcome.SKIPPED: StepState.SKIPPED,
        }.get(result.status)
        if final_state is None:
            raise ValueError(f"Invalid processor outcome: {result.status.value}")

        self.step_results[step_name] = result
        self.step_states[step_name] = final_state
        if result.reason:
            self.step_reasons[step_name] = result.reason
        self.active_step = None
        self.stop_requested = False

    def fail(self, step_name: str, reason: str) -> None:
        self._finish_without_result(step_name, StepState.FAILED, reason)

    def cancel(self, step_name: str, reason: str) -> None:
        self._finish_without_result(step_name, StepState.CANCELLED, reason)

    def start_auto_run(self) -> None:
        self.auto_run = True

    def stop_auto_run(self) -> None:
        self.auto_run = False

    def next_auto_step(self, completed_step: str, terminal_step: str) -> str | None:
        completed_index = self._step_index(completed_step)
        self._step_index(terminal_step)
        if not self.auto_run or self.stop_requested or completed_step == terminal_step:
            self.auto_run = False
            return None
        next_index = completed_index + 1
        if next_index >= len(self.step_names):
            self.auto_run = False
            return None
        return self.step_names[next_index]

    def request_stop(self) -> bool:
        if self.active_step is None:
            return False
        self.stop_requested = True
        self.auto_run = False
        return True

    def should_discard_result(self, step_name: str) -> bool:
        return self.active_step == step_name and self.stop_requested

    def _finish_without_result(self, step_name: str, state: StepState, reason: str) -> None:
        self._require_active(step_name)
        self.invalidate_from(step_name)
        self.step_states[step_name] = state
        self.step_reasons[step_name] = reason
        self.active_step = None
        self.stop_requested = False
        self.auto_run = False

    def _require_active(self, step_name: str) -> None:
        self._step_index(step_name)
        if self.active_step != step_name:
            raise RuntimeError(f"Step is not active: {step_name}")

    def _step_index(self, step_name: str) -> int:
        try:
            return self.step_names.index(step_name)
        except ValueError as exc:
            raise KeyError(f"Unknown workflow step: {step_name}") from exc


def build_workflow_steps():
    """Return the ordered DNP workflow steps exposed by the GUI."""
    return [
        {"name": STEP1_NAME, "module": "metabolomics.processors.istd", "enabled": True},
        {"name": STEP2_NAME, "module": "metabolomics.processors.qc_lowess", "enabled": False},
        {"name": STEP3_NAME, "module": "metabolomics.processors.normalization", "enabled": False},
        {"name": STEP4_NAME, "module": "metabolomics.processors.qc_batch_scaling", "enabled": False},
    ]


def get_auto_run_terminal_step_name():
    """Return the final step for active Auto Run execution."""
    return STEP3_NAME
