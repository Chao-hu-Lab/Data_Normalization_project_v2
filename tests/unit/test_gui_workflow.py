from metabolomics.workflow import (
    DEFAULT_STEP3_METHOD,
    STEP1_NAME,
    STEP2_NAME,
    STEP3_NAME,
    STEP4_NAME,
    STEP3_METHOD_OPTIONS,
    StepState,
    WorkflowState,
    build_workflow_steps,
    get_auto_run_terminal_step_name,
)
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome


STEP_NAMES = (STEP1_NAME, STEP2_NAME, STEP3_NAME, STEP4_NAME)


def _result(path, *, status=WorkflowOutcome.SUCCEEDED, reason=None):
    return ProcessingResult(
        file_path=path,
        output_path=path,
        metabolites=10,
        samples=5,
        status=status,
        reason=reason,
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
    assert DEFAULT_STEP3_METHOD == "PQN"
    assert STEP3_METHOD_OPTIONS == (
        ("PQN — urine dilution", "PQN"),
        ("SpecNorm — tissue reference", "SpecNorm"),
    )


def test_workflow_chains_success_and_skip_outputs():
    state = WorkflowState(STEP_NAMES)
    state.select_input("C:/input.xlsx")

    state.begin(STEP1_NAME)
    state.complete(
        STEP1_NAME,
        _result(
            "C:/input.xlsx",
            status=WorkflowOutcome.SKIPPED,
            reason="insufficient_good_istd",
        ),
    )

    assert state.status_of(STEP1_NAME) is StepState.SKIPPED
    assert state.resolve_input(STEP2_NAME) == "C:/input.xlsx"
    assert STEP1_NAME in state.completed_steps


def test_failure_invalidates_failed_step_and_downstream():
    state = WorkflowState(STEP_NAMES)
    state.select_input("C:/input.xlsx")
    for step_name, path in (
        (STEP1_NAME, "C:/step1.xlsx"),
        (STEP2_NAME, "C:/step2.xlsx"),
        (STEP3_NAME, "C:/step3.xlsx"),
        (STEP4_NAME, "C:/step4.xlsx"),
    ):
        state.begin(step_name)
        state.complete(step_name, _result(path))

    state.begin(STEP3_NAME)
    state.fail(STEP3_NAME, "invalid SampleInfo")

    assert state.status_of(STEP3_NAME) is StepState.FAILED
    assert state.status_of(STEP4_NAME) is StepState.PENDING
    assert state.result_for(STEP2_NAME).output_path == "C:/step2.xlsx"
    assert state.result_for(STEP3_NAME) is None
    assert state.result_for(STEP4_NAME) is None


def test_stop_request_discards_current_result_and_stops_auto_run():
    state = WorkflowState(STEP_NAMES)
    state.select_input("C:/input.xlsx")
    state.start_auto_run()
    state.begin(STEP1_NAME)

    assert state.request_stop() is True
    assert state.should_discard_result(STEP1_NAME) is True
    assert state.auto_run is False

    state.cancel(STEP1_NAME, "stop requested; completed result discarded")

    assert state.status_of(STEP1_NAME) is StepState.CANCELLED
    assert state.result_for(STEP1_NAME) is None


def test_workflow_rejects_non_processing_result():
    state = WorkflowState(STEP_NAMES)
    state.select_input("C:/input.xlsx")
    state.begin(STEP1_NAME)

    try:
        state.complete(STEP1_NAME, {"output_path": "C:/bad.xlsx"})
    except TypeError as exc:
        assert "ProcessingResult" in str(exc)
    else:
        raise AssertionError("dict result should be rejected")


def test_skipped_processing_result_requires_reason():
    try:
        _result("C:/input.xlsx", status=WorkflowOutcome.SKIPPED)
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("skipped result without reason should be rejected")


def test_processing_result_rejects_failed_processor_outcome():
    try:
        _result("C:/input.xlsx", status=WorkflowOutcome.FAILED, reason="save failed")
    except ValueError as exc:
        assert "succeeded or skipped" in str(exc)
    else:
        raise AssertionError("processors must raise instead of returning failed results")


def test_processing_result_keeps_legacy_positional_optional_fields():
    result = ProcessingResult(
        "C:/input.xlsx",
        "C:/output.xlsx",
        10,
        5,
        "C:/plots",
        {"diagnostic": True},
    )

    assert result.plots_dir == "C:/plots"
    assert result.extra == {"diagnostic": True}
    assert result.status is WorkflowOutcome.SUCCEEDED


def test_workflow_rejects_input_change_while_step_is_running():
    state = WorkflowState(STEP_NAMES)
    state.select_input("C:/input.xlsx")
    state.begin(STEP1_NAME)

    try:
        state.select_input("C:/replacement.xlsx")
    except RuntimeError as exc:
        assert "running" in str(exc)
    else:
        raise AssertionError("active workflow input should be immutable")

    assert state.selected_file_path == "C:/input.xlsx"
    assert state.active_step == STEP1_NAME
