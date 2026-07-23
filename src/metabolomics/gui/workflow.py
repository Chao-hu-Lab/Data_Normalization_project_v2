"""Compatibility exports for the former GUI-owned workflow module."""

from metabolomics.workflow import (
    DEFAULT_STEP3_METHOD,
    STEP1_NAME,
    STEP2_NAME,
    STEP3_METHOD_OPTIONS,
    STEP3_NAME,
    STEP4_NAME,
    StepState,
    WorkflowState,
    build_workflow_steps,
    get_auto_run_terminal_step_name,
)

__all__ = [
    "DEFAULT_STEP3_METHOD",
    "STEP1_NAME",
    "STEP2_NAME",
    "STEP3_METHOD_OPTIONS",
    "STEP3_NAME",
    "STEP4_NAME",
    "StepState",
    "WorkflowState",
    "build_workflow_steps",
    "get_auto_run_terminal_step_name",
]
