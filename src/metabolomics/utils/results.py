from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class WorkflowOutcome(str, Enum):
    """Terminal outcomes shared by processors and workflow orchestration."""

    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProcessingResult:
    """
    Standard return type for processor main() functions.
    """
    file_path: str
    output_path: str
    metabolites: int
    samples: int
    plots_dir: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    status: WorkflowOutcome = WorkflowOutcome.SUCCEEDED
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        self.status = WorkflowOutcome(self.status)
        if self.status not in {WorkflowOutcome.SUCCEEDED, WorkflowOutcome.SKIPPED}:
            raise ValueError("Processors may only return succeeded or skipped results")
        if self.status is WorkflowOutcome.SKIPPED and not self.reason:
            raise ValueError("Skipped results must include a reason")
        if not self.output_path:
            raise ValueError("ProcessingResult.output_path must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to a dict for UI/update pipelines.
        """
        data = {
            "file_path": self.file_path,
            "output_path": self.output_path,
            "metabolites": self.metabolites,
            "samples": self.samples,
            "status": self.status.value,
        }
        if self.reason:
            data["reason"] = self.reason
        if self.plots_dir:
            data["plots_dir"] = self.plots_dir
        if self.extra:
            data.update({key: value for key, value in self.extra.items() if key not in data})
        return data
