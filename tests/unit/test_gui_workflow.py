from metabolomics.gui.workflow import (
    DEFAULT_STEP3_METHOD,
    STEP3_METHOD_OPTIONS,
    build_workflow_steps,
    get_auto_run_terminal_step_name,
)


def test_workflow_helper_defines_active_terminal_step():
    steps = build_workflow_steps()

    assert [step["name"] for step in steps] == [
        "Step 1: ISTD Correction",
        "Step 2: QC-LOESS",
        "Step 3: Concentration Normalization",
        "Step 4: QC Batch Scaling",
    ]
    assert get_auto_run_terminal_step_name() == "Step 3: Concentration Normalization"
    assert DEFAULT_STEP3_METHOD == "SpecNorm+PQN"
    assert STEP3_METHOD_OPTIONS[0] == ("SpecNorm+PQN", "SpecNorm+PQN")
