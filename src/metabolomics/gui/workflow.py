"""Workflow policy helpers for the DNP GUI."""

from metabolomics.utils import normalization_contract


STEP1_NAME = "Step 1: ISTD Correction"
STEP2_NAME = "Step 2: QC-LOESS"
STEP3_NAME = "Step 3: Concentration Normalization"
STEP4_NAME = "Step 4: QC Batch Scaling"
DEFAULT_STEP3_METHOD = normalization_contract.DEFAULT_NORMALIZATION_METHOD
STEP3_METHOD_OPTIONS = normalization_contract.STEP3_METHOD_OPTIONS


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
