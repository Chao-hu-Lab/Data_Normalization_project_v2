"""Characterization tests for the canonical workflow module boundary."""

import importlib


def test_canonical_workflow_module_is_toolkit_agnostic():
    workflow = importlib.import_module("metabolomics.workflow")

    assert workflow.WorkflowState.__module__ == "metabolomics.workflow"
    assert workflow.StepState.__module__ == "metabolomics.workflow"


def test_legacy_gui_workflow_path_reexports_canonical_identities():
    canonical = importlib.import_module("metabolomics.workflow")
    legacy = importlib.import_module("metabolomics.gui.workflow")

    exported_names = (
        "WorkflowState",
        "StepState",
        "STEP1_NAME",
        "STEP2_NAME",
        "STEP3_NAME",
        "STEP4_NAME",
        "DEFAULT_STEP3_METHOD",
        "STEP3_METHOD_OPTIONS",
        "build_workflow_steps",
        "get_auto_run_terminal_step_name",
    )
    for name in exported_names:
        assert getattr(legacy, name) is getattr(canonical, name)
