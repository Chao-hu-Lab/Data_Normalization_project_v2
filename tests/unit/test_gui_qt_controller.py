import os
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, Qt
import shiboken6

from metabolomics.gui.workflow import (
    STEP1_NAME,
    STEP2_NAME,
    STEP3_NAME,
    STEP4_NAME,
    StepState,
)
from metabolomics.gui_qt.controller import WorkflowController, skip_guidance
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome
from tests.gui_qt_helpers import qt_app, wait_until


def _result(input_path, output_path):
    return ProcessingResult(
        file_path=input_path,
        output_path=output_path,
        metabolites=10,
        samples=5,
    )


def test_single_step_success_runs_at_processor_boundary_without_success_notice():
    calls = []

    def processor(**kwargs):
        calls.append(kwargs)
        return _result(kwargs["input_file"], "C:/session/step1.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    notices = []
    controller.notice.connect(lambda *args: notices.append(args))
    controller.select_input("C:/input.xlsx")

    controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert controller.workflow.result_for(STEP1_NAME).output_path == "C:/session/step1.xlsx"
    assert calls == [{"input_file": "C:/input.xlsx", "session_dir": "C:/session"}]
    assert notices == []
    assert controller.shutdown(timeout_ms=1000)


def test_auto_run_chains_immediate_outputs_through_step_three_only():
    calls = []
    outputs = {
        STEP1_NAME: "C:/session/step1.xlsx",
        STEP2_NAME: "C:/session/step2.xlsx",
        STEP3_NAME: "C:/session/step3.xlsx",
        STEP4_NAME: "C:/session/step4.xlsx",
    }

    def make_processor(step_name):
        def processor(**kwargs):
            calls.append((step_name, kwargs.copy()))
            return _result(kwargs["input_file"], outputs[step_name])

        return processor

    controller = WorkflowController(
        processors={name: make_processor(name) for name in outputs},
        session_factory=lambda _input: "C:/session",
    )
    notices = []
    controller.notice.connect(lambda *args: notices.append(args))
    controller.select_input("C:/input.xlsx")

    controller.start_auto_run()
    wait_until(
        lambda: controller.workflow.status_of(STEP3_NAME) is StepState.SUCCEEDED
        and not controller.is_running
    )

    assert [step for step, _kwargs in calls] == [STEP1_NAME, STEP2_NAME, STEP3_NAME]
    assert [kwargs["input_file"] for _step, kwargs in calls] == [
        "C:/input.xlsx",
        "C:/session/step1.xlsx",
        "C:/session/step2.xlsx",
    ]
    assert controller.workflow.status_of(STEP4_NAME) is StepState.PENDING
    assert notices == [
        (
            "info",
            "Auto Run complete",
            "Steps 1–3 finished. Step 4 remains manual diagnostics-only.",
            STEP3_NAME,
        )
    ]
    assert controller.shutdown(timeout_ms=1000)


def test_auto_run_start_failure_does_not_leak_auto_run_state():
    calls = []

    def processor(**kwargs):
        calls.append(kwargs)
        return _result(kwargs["input_file"], "C:/session/step1.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )

    with pytest.raises(ValueError, match="select an input file"):
        controller.start_auto_run()

    assert not controller.workflow.auto_run
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    assert len(calls) == 1
    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert controller.workflow.status_of(STEP2_NAME) is StepState.PENDING
    assert controller.shutdown(timeout_ms=1000)


def test_stop_mid_run_discards_the_finished_result():
    entered = threading.Event()
    release = threading.Event()

    def processor(**kwargs):
        entered.set()
        assert release.wait(2)
        return _result(kwargs["input_file"], "C:/session/should-not-apply.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    wait_until(entered.is_set)

    assert controller.request_stop()
    release.set()
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.CANCELLED
    assert controller.workflow.result_for(STEP1_NAME) is None
    assert controller.workflow.status_of(STEP2_NAME) is StepState.PENDING
    assert controller.shutdown(timeout_ms=1000)


def test_error_invalidates_and_retry_uses_a_new_run():
    attempts = 0

    def processor(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("canned processor failure")
        return _result(kwargs["input_file"], "C:/session/retry.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    notices = []
    controller.notice.connect(lambda *args: notices.append(args))
    controller.select_input("C:/input.xlsx")

    failed_run = controller.start_step(STEP1_NAME)
    wait_until(
        lambda: controller.workflow.status_of(STEP1_NAME) is StepState.FAILED
        and not controller.is_running
    )

    assert controller.workflow.result_for(STEP1_NAME) is None
    assert notices[-1][0] == "retry"
    assert "See the Log panel" in notices[-1][2]

    retry_run = controller.retry_step(STEP1_NAME)
    wait_until(
        lambda: controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
        and not controller.is_running
    )

    assert retry_run != failed_run
    assert attempts == 2
    assert controller.workflow.result_for(STEP1_NAME).output_path == "C:/session/retry.xlsx"
    assert controller.shutdown(timeout_ms=1000)


def test_skip_guidance_preserves_the_three_domain_paths():
    istd = skip_guidance(STEP1_NAME, "insufficient_good_istd")
    single_batch = skip_guidance(STEP4_NAME, "single_batch")
    paused = skip_guidance(STEP4_NAME, "paused_nonshared_qc_design")

    assert "Step 2" in istd and "RawIntensity" in istd
    assert "single batch" in single_batch and "Step 3" in single_batch
    assert "diagnostics-only" in paused and "Step 3" in paused


def test_manual_skip_keeps_the_chain_and_emits_guidance_notice():
    def processor(**kwargs):
        return ProcessingResult(
            file_path=kwargs["input_file"],
            output_path=kwargs["input_file"],
            metabolites=10,
            samples=5,
            status=WorkflowOutcome.SKIPPED,
            reason="insufficient_good_istd",
        )

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    notices = []
    controller.notice.connect(lambda *args: notices.append(args))
    controller.select_input("C:/input.xlsx")

    controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SKIPPED
    assert controller.workflow.resolve_input(STEP2_NAME) == "C:/input.xlsx"
    assert notices == [
        (
            "skip",
            "Step skipped",
            skip_guidance(STEP1_NAME, "insufficient_good_istd"),
            STEP1_NAME,
        )
    ]
    assert controller.shutdown(timeout_ms=1000)


def test_selected_step_three_method_and_manual_step_four_kwargs_reach_processors():
    calls = []

    def make_processor(step_name):
        def processor(**kwargs):
            calls.append((step_name, kwargs.copy()))
            return _result(kwargs["input_file"], f"C:/session/{len(calls)}.xlsx")

        return processor

    controller = WorkflowController(
        processors={
            name: make_processor(name)
            for name in (STEP1_NAME, STEP2_NAME, STEP3_NAME, STEP4_NAME)
        },
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    controller.set_normalization_method("PQN")

    controller.start_auto_run()
    wait_until(
        lambda: controller.workflow.status_of(STEP3_NAME) is StepState.SUCCEEDED
        and not controller.is_running
    )
    controller.start_step(STEP4_NAME)
    wait_until(lambda: not controller.is_running)

    step3_kwargs = next(kwargs for step, kwargs in calls if step == STEP3_NAME)
    step4_kwargs = next(kwargs for step, kwargs in calls if step == STEP4_NAME)
    assert step3_kwargs["normalization_method"] == "PQN"
    assert step4_kwargs["diagnostics_only"] is True
    assert {kwargs["session_dir"] for _step, kwargs in calls} == {"C:/session"}
    assert controller.shutdown(timeout_ms=1000)


def test_worker_runs_off_gui_thread_and_streams_stdout_and_stderr():
    ran_on_gui_thread = []

    def processor(**kwargs):
        ran_on_gui_thread.append(QThread.currentThread() is qt_app().thread())
        print("processor info line")
        print("processor error line", file=sys.stderr)
        return _result(kwargs["input_file"], "C:/session/step1.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    logs = []
    controller.log_line.connect(lambda *args: logs.append(args))
    controller.select_input("C:/input.xlsx")

    controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    assert ran_on_gui_thread == [False]
    assert ("info", "processor info line") in logs
    assert ("error", "processor error line") in logs
    assert controller.shutdown(timeout_ms=1000)


def test_shutdown_keeps_thread_ownership_when_worker_has_not_finished():
    entered = threading.Event()
    release = threading.Event()

    def processor(**kwargs):
        entered.set()
        assert release.wait(2)
        return _result(kwargs["input_file"], "C:/session/discard.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    wait_until(entered.is_set)

    assert not controller.shutdown(timeout_ms=10)
    assert controller.is_running
    assert controller.workflow.stop_requested

    release.set()
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.CANCELLED
    assert controller.shutdown(timeout_ms=1000)


def test_invalid_processor_result_becomes_a_retryable_failure():
    controller = WorkflowController(
        processors={STEP1_NAME: lambda **_kwargs: None},
        session_factory=lambda _input: "C:/session",
    )
    notices = []
    logs = []
    controller.notice.connect(lambda *args: notices.append(args))
    controller.log_line.connect(lambda *args: logs.append(args))
    controller.select_input("C:/input.xlsx")

    controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.FAILED
    assert notices[-1][0] == "retry"
    assert any("Processor must return ProcessingResult" in message for _level, message in logs)
    assert controller.shutdown(timeout_ms=1000)


def test_auto_run_skip_continues_without_an_intermediate_blocking_notice():
    calls = []

    def step1(**kwargs):
        calls.append((STEP1_NAME, kwargs.copy()))
        return ProcessingResult(
            file_path=kwargs["input_file"],
            output_path=kwargs["input_file"],
            metabolites=10,
            samples=5,
            status=WorkflowOutcome.SKIPPED,
            reason="insufficient_good_istd",
        )

    def downstream(step_name, output_path):
        def processor(**kwargs):
            calls.append((step_name, kwargs.copy()))
            return _result(kwargs["input_file"], output_path)

        return processor

    controller = WorkflowController(
        processors={
            STEP1_NAME: step1,
            STEP2_NAME: downstream(STEP2_NAME, "C:/session/step2.xlsx"),
            STEP3_NAME: downstream(STEP3_NAME, "C:/session/step3.xlsx"),
        },
        session_factory=lambda _input: "C:/session",
    )
    notices = []
    controller.notice.connect(lambda *args: notices.append(args))
    controller.select_input("C:/input.xlsx")

    controller.start_auto_run()
    wait_until(
        lambda: controller.workflow.status_of(STEP3_NAME) is StepState.SUCCEEDED
        and not controller.is_running
    )

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SKIPPED
    assert calls[1][1]["input_file"] == "C:/input.xlsx"
    assert [notice[0] for notice in notices] == ["info"]
    assert controller.shutdown(timeout_ms=1000)


def test_worker_log_capture_does_not_steal_gui_thread_output(capsys):
    entered = threading.Event()
    release = threading.Event()

    def processor(**kwargs):
        print("worker-owned line")
        entered.set()
        assert release.wait(2)
        return _result(kwargs["input_file"], "C:/session/step1.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    logs = []
    controller.log_line.connect(lambda *args: logs.append(args))
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    wait_until(entered.is_set)

    print("gui-thread line")
    release.set()
    wait_until(lambda: not controller.is_running)

    assert "gui-thread line" in capsys.readouterr().out
    assert ("info", "worker-owned line") in logs
    assert all("gui-thread line" not in message for _level, message in logs)
    assert controller.shutdown(timeout_ms=1000)


def test_finish_applied_before_stop_keeps_the_successful_result():
    controller = WorkflowController(
        processors={
            STEP1_NAME: lambda **kwargs: _result(
                kwargs["input_file"],
                "C:/session/applied.xlsx",
            )
        },
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    assert not controller.request_stop()
    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert controller.workflow.result_for(STEP1_NAME).output_path == "C:/session/applied.xlsx"


def test_stop_after_finished_signal_but_before_slot_discards_result():
    entered = threading.Event()
    allow_finish = threading.Event()
    terminal_emitted = threading.Event()

    def processor(**kwargs):
        entered.set()
        assert allow_finish.wait(2)
        return _result(kwargs["input_file"], "C:/session/queued.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    wait_until(entered.is_set)

    worker = controller._worker
    assert worker is not None
    worker.finished.connect(
        lambda _run_id, _result: terminal_emitted.set(),
        Qt.ConnectionType.DirectConnection,
    )
    allow_finish.set()
    assert terminal_emitted.wait(2)
    assert controller.workflow.status_of(STEP1_NAME) is StepState.RUNNING

    assert controller.request_stop()
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.CANCELLED
    assert controller.workflow.result_for(STEP1_NAME) is None


def test_duplicate_and_stale_terminal_signals_do_not_change_the_current_run():
    entered_second = threading.Event()
    release_second = threading.Event()
    attempts = 0

    def processor(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _result(kwargs["input_file"], "C:/session/first.xlsx")
        entered_second.set()
        assert release_second.wait(2)
        return _result(kwargs["input_file"], "C:/session/second.xlsx")

    controller = WorkflowController(
        processors={STEP1_NAME: processor},
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    old_run_id = controller.start_step(STEP1_NAME)
    wait_until(lambda: not controller.is_running)

    new_run_id = controller.start_step(STEP1_NAME)
    wait_until(entered_second.is_set)
    assert new_run_id != old_run_id

    stale = _result("C:/input.xlsx", "C:/session/stale.xlsx")
    controller._on_finished(old_run_id, stale)
    controller._on_failed(old_run_id, "RuntimeError: stale failure")

    assert controller.workflow.status_of(STEP1_NAME) is StepState.RUNNING
    release_second.set()
    wait_until(lambda: not controller.is_running)

    assert controller.workflow.status_of(STEP1_NAME) is StepState.SUCCEEDED
    assert controller.workflow.result_for(STEP1_NAME).output_path == "C:/session/second.xlsx"

    controller._on_finished(new_run_id, stale)
    assert controller.workflow.result_for(STEP1_NAME).output_path == "C:/session/second.xlsx"


def test_finished_thread_deletes_its_worker_object():
    controller = WorkflowController(
        processors={
            STEP1_NAME: lambda **kwargs: _result(
                kwargs["input_file"],
                "C:/session/step1.xlsx",
            )
        },
        session_factory=lambda _input: "C:/session",
    )
    controller.select_input("C:/input.xlsx")
    controller.start_step(STEP1_NAME)
    worker = controller._worker
    assert worker is not None

    wait_until(lambda: not controller.is_running)
    wait_until(lambda: not shiboken6.isValid(worker))

    assert not shiboken6.isValid(worker)
