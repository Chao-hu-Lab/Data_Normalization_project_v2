from __future__ import annotations

from datetime import datetime

from metabolomics.gui.app import DataNormalizationApp
from metabolomics.gui.workflow import WorkflowState
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome


class _DummyWidget:
    def __init__(self):
        self.config_calls = []

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


class _DummyMaster:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))
        return None


class _DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def _make_app():
    app = DataNormalizationApp.__new__(DataNormalizationApp)
    app.steps = [
        {"name": "Step 1: ISTD Correction", "module": "metabolomics.processors.istd", "accent": "#1a73e8"},
        {"name": "Step 2: QC-LOESS", "module": "metabolomics.processors.qc_lowess", "accent": "#34a853"},
        {"name": "Step 3: Concentration Normalization", "module": "metabolomics.processors.normalization", "accent": "#f9ab00"},
        {"name": "Step 4: QC Batch Scaling", "module": "metabolomics.processors.qc_batch_scaling", "accent": "#ea4335"},
    ]
    app.workflow = WorkflowState(tuple(step["name"] for step in app.steps))
    app.master = _DummyMaster()
    app.logger = _DummyLogger()
    app.execution_start_time = datetime.now()
    app.current_stats = {
        "step_name": "",
        "metabolites": 0,
        "samples": 0,
        "output_path": "",
        "execution_time": 0,
    }
    app.last_output_file = None
    app.current_session_dir = None
    app.step_status_labels = [_DummyWidget() for _ in app.steps]
    app.step_buttons = [_DummyWidget() for _ in app.steps]
    app.step_excel_buttons = [_DummyWidget() for _ in app.steps]
    app.step_plot_buttons = [_DummyWidget() for _ in app.steps]
    app.step_cards = [_DummyWidget() for _ in app.steps]
    app.cancel_btn = _DummyWidget()
    app.color_scheme = {
        "success": "#0f0",
        "danger": "#f00",
        "running": "#00f",
        "ghost": "#ccc",
        "ghost_text": "#111",
        "disabled": "#999",
        "border": "#ddd",
    }
    return app


def _result(path, *, status=WorkflowOutcome.SUCCEEDED, reason=None):
    return ProcessingResult(
        file_path=path,
        output_path=path,
        metabolites=10,
        samples=5,
        status=status,
        reason=reason,
    )


def _complete_steps(app, output_paths):
    app.workflow.select_input("C:/tmp/input.xlsx")
    for step, output_path in zip(app.steps, output_paths):
        app.workflow.begin(step["name"])
        app.workflow.complete(step["name"], _result(output_path))


def test_build_workflow_steps_exposes_four_ordered_steps():
    steps = DataNormalizationApp._build_workflow_steps()

    assert [step["name"] for step in steps] == [
        "Step 1: ISTD Correction",
        "Step 2: QC-LOESS",
        "Step 3: Concentration Normalization",
        "Step 4: QC Batch Scaling",
    ]


def test_get_step_card_label_marks_step4_as_paused_diagnostics_only():
    assert DataNormalizationApp._get_step_card_label(
        "Step 1: ISTD Correction"
    ) == "ISTD Monitoring / Selective Correction"
    assert DataNormalizationApp._get_step_card_label("Step 4: QC Batch Scaling") == "QC Batch Scaling (paused / diagnostics-only)"
    assert DataNormalizationApp._get_step_card_label("Step 3: Concentration Normalization") == "Concentration Normalization"


def test_build_window_defaults_favors_wider_1920_layout():
    defaults = DataNormalizationApp._build_window_defaults()

    assert defaults["geometry"] == "1480x940+80+20"
    assert defaults["minsize"] == (1360, 920)


def test_build_header_button_tokens_makes_reset_destructive_and_explicit():
    tokens = DataNormalizationApp._build_header_button_tokens()

    assert tokens["reset"]["text"] == "Reset Workflow"
    assert tokens["reset"]["bg"] == "#475569"
    assert tokens["reset"]["fg"] == "#ffffff"


def test_build_header_text_tokens_removes_duplicate_workflow_copy():
    tokens = DataNormalizationApp._build_header_text_tokens()

    assert tokens["title"] == "Pipeline Controls"
    assert tokens["subtitle"] == ""


def test_build_header_button_tokens_uses_uniform_control_grid_sizing():
    tokens = DataNormalizationApp._build_header_button_tokens()

    assert tokens["layout"] == "single_row"
    assert tokens["columns"] == 3
    assert tokens["run_all"]["width"] == 14
    assert tokens["stop"]["width"] == 14
    assert tokens["reset"]["width"] == 14
    assert "export" not in tokens


def test_build_header_button_tokens_raise_secondary_action_contrast():
    tokens = DataNormalizationApp._build_header_button_tokens()

    assert tokens["run_all"]["bg"] == "#2563eb"
    assert tokens["run_all"]["fg"] == "#ffffff"
    assert tokens["stop"]["bg"] == "#dc2626"
    assert tokens["stop"]["fg"] == "#ffffff"


def test_build_workspace_defaults_targets_balanced_split():
    defaults = DataNormalizationApp._build_workspace_defaults()

    assert defaults["left_minsize"] == 540
    assert defaults["right_minsize"] == 540
    assert defaults["split_ratio"] == 0.47
    assert defaults["initial_retry_ms"] == 120
    assert defaults["keep_ratio_on_resize"] is True
    assert defaults["card_rows"] == 4


def test_build_step_card_tokens_reserve_space_for_three_button_actions():
    tokens = DataNormalizationApp._build_step_card_tokens()

    assert tokens["badge_width"] == 96
    assert tokens["actions_width"] == 348
    assert tokens["show_status_chip"] is False
    assert tokens["action_columns"] == 3
    assert tokens["card_gap"] == 8
    assert tokens["badge_layout"] == "inline"


def test_build_info_panel_tabs_only_exposes_execution_log():
    assert DataNormalizationApp._build_info_panel_tabs() == ("Execution Log",)


def test_app_uses_workflow_as_its_only_step_state():
    app = _make_app()
    _complete_steps(
        app,
        ["C:/tmp/step1.xlsx", "C:/tmp/step2.xlsx", "C:/tmp/step3.xlsx"],
    )

    assert app.workflow.selected_file_path == "C:/tmp/input.xlsx"
    assert app.workflow.result_for(app.steps[2]["name"]).output_path == "C:/tmp/step3.xlsx"
    assert not hasattr(app, "completed_steps")
    assert not hasattr(app, "step_outputs")
    assert not hasattr(app, "workflow_state")


def test_render_pipeline_nav_highlights_next_incomplete_step():
    app = _make_app()
    app.pipeline_nav_labels = [_DummyWidget() for _ in app.steps]
    _complete_steps(app, ["C:/tmp/step1.xlsx"])
    expected_primary = app.color_scheme.get("primary", "#1a73e8")

    app._render_pipeline_nav()

    assert app.pipeline_nav_labels[1].config_calls[-1]["bg"] == expected_primary
    assert app.pipeline_nav_labels[0].config_calls[-1]["bg"] == "#0d1b2a"
    assert app.pipeline_nav_labels[0].config_calls[-1]["fg"] == "#9fb3c8"


def test_update_button_states_does_not_require_export_button():
    app = _make_app()
    app.pipeline_nav_labels = [_DummyWidget() for _ in app.steps]
    _complete_steps(
        app,
        ["C:/tmp/step1.xlsx", "C:/tmp/step2.xlsx", "C:/tmp/step3-output.xlsx"],
    )

    app.update_button_states()

    assert not hasattr(app, "export_meta_btn")
    assert not hasattr(app, "stats_completed_label")


def test_run_step_uses_previous_step_output_instead_of_last_output_file():
    app = _make_app()
    step = app.steps[2]
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None, **kwargs):
            captured["input_file"] = input_file
            captured.update(kwargs)
            return _result("C:/tmp/step3-output.xlsx")

    app.last_output_file = "C:/tmp/stale-step4-output.xlsx"
    _complete_steps(app, ["C:/tmp/step1.xlsx", "C:/tmp/current-step2-output.xlsx"])
    app.workflow.begin(step["name"])
    app.load_script = lambda _module_name: _DummyModule()

    app.run_step(step)

    assert captured["input_file"] == "C:/tmp/current-step2-output.xlsx"
    assert captured["normalization_method"] == "PQN"


def test_run_step_passes_selected_specnorm_method_to_normalization():
    app = _make_app()
    step = app.steps[2]
    app.normalization_method = type("DummyVar", (), {"get": lambda _self: "SpecNorm"})()
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None, **kwargs):
            captured.update(kwargs)
            return _result("C:/tmp/step3-output.xlsx")

    _complete_steps(app, ["C:/tmp/step1.xlsx", "C:/tmp/current-step2-output.xlsx"])
    app.workflow.begin(step["name"])
    app.load_script = lambda _module_name: _DummyModule()

    app.run_step(step)

    assert captured["normalization_method"] == "SpecNorm"


def test_run_step_passes_diagnostics_only_to_step4():
    app = _make_app()
    step = app.steps[3]
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None, **kwargs):
            captured["input_file"] = input_file
            captured.update(kwargs)
            return _result("C:/tmp/step4-diagnostics.xlsx")

    _complete_steps(
        app,
        ["C:/tmp/step1.xlsx", "C:/tmp/step2.xlsx", "C:/tmp/current-step3-output.xlsx"],
    )
    app.workflow.begin(step["name"])
    app.load_script = lambda _module_name: _DummyModule()

    app.run_step(step)

    assert captured["input_file"] == "C:/tmp/current-step3-output.xlsx"
    assert captured["diagnostics_only"] is True


def test_run_step_rejects_none_result_instead_of_completing():
    app = _make_app()
    step = app.steps[0]
    app.workflow.select_input("C:/tmp/input.xlsx")
    app.workflow.begin(step["name"])
    errors = []

    class _DummyModule:
        @staticmethod
        def main(**_kwargs):
            return None

    app.load_script = lambda _module_name: _DummyModule()
    app.on_step_error = lambda _step, error: errors.append(error)

    app.run_step(step)
    for _delay, callback in app.master.after_calls:
        callback()

    assert errors == [
        "Step 1: ISTD Correction returned NoneType; expected ProcessingResult"
    ]
    assert app.workflow.result_for(step["name"]) is None


def test_stop_request_waits_for_current_calculation(monkeypatch):
    app = _make_app()
    step = app.steps[0]
    app.workflow.select_input("C:/tmp/input.xlsx")
    app.workflow.start_auto_run()
    app.workflow.begin(step["name"])
    progress_calls = []
    app.set_progress = lambda *args, **kwargs: progress_calls.append((args, kwargs))
    monkeypatch.setattr(
        "metabolomics.gui.app.messagebox.askyesno",
        lambda *_args, **_kwargs: True,
    )

    app.cancel_execution()

    assert app.workflow.stop_requested is True
    assert app.workflow.auto_run is False
    assert "finishing current calculation" in progress_calls[-1][0][0]
    assert app.cancel_btn.config_calls[-1]["state"] == "disabled"


def test_completion_callback_discards_result_when_stop_arrives_after_worker_check():
    app = _make_app()
    step = app.steps[0]
    app.workflow.select_input("C:/tmp/input.xlsx")
    app.workflow.begin(step["name"])
    app.update_button_states = lambda: None
    app.set_progress = lambda *_args, **_kwargs: None
    app.workflow.request_stop()

    app.on_step_complete(step, _result("C:/tmp/step1-output.xlsx"))

    assert app.workflow.status_of(step["name"]).value == "cancelled"
    assert app.workflow.result_for(step["name"]) is None


def test_auto_run_stops_after_step3_and_does_not_schedule_step4(monkeypatch):
    app = _make_app()
    _complete_steps(app, ["C:/tmp/step1.xlsx", "C:/tmp/step2.xlsx"])
    app.workflow.start_auto_run()
    app.workflow.begin(app.steps[2]["name"])
    app.current_stats = {"execution_time": 1.0}
    app.update_input_source_labels = lambda: None
    app.update_button_states = lambda: None
    app.set_progress = lambda *_args, **_kwargs: None
    info_calls = []
    monkeypatch.setattr(
        "metabolomics.gui.app.messagebox.showinfo",
        lambda *args, **kwargs: info_calls.append((args, kwargs)),
    )

    app.on_step_complete(
        app.steps[2],
        _result("C:/tmp/step3-output.xlsx"),
    )

    assert app.workflow.auto_run is False
    assert app.master.after_calls == []
    assert info_calls
    assert "Step 3" in info_calls[0][0][1]


def test_on_step_error_invalidates_failed_step_and_downstream(monkeypatch):
    app = _make_app()
    step = app.steps[2]
    _complete_steps(
        app,
        [
            "C:/tmp/step1-output.xlsx",
            "C:/tmp/step2-output.xlsx",
            "C:/tmp/step3-output.xlsx",
            "C:/tmp/step4-output.xlsx",
        ],
    )
    app.workflow.begin(step["name"])
    app.last_output_file = "C:/tmp/step4-output.xlsx"
    app.update_button_states = lambda: None
    prompt_calls = []
    monkeypatch.setattr(
        "metabolomics.gui.app.messagebox.askyesno",
        lambda *args, **kwargs: prompt_calls.append((args, kwargs)) or False,
    )

    app.on_step_error(step, "SampleInfo 中找不到 SpecNorm 所需的 specimen-reference 欄位")

    assert "Step 3: Concentration Normalization" not in app.workflow.completed_steps
    assert "Step 4: QC Batch Scaling" not in app.workflow.completed_steps
    assert app.workflow.result_for("Step 3: Concentration Normalization") is None
    assert app.workflow.result_for("Step 4: QC Batch Scaling") is None
    assert app.last_output_file == "C:/tmp/step2-output.xlsx"
    assert prompt_calls
    prompt_text = prompt_calls[0][0][1]
    assert "See the Log panel" in prompt_text
    assert "SampleInfo 中找不到" not in prompt_text


def test_on_step_error_tells_user_to_fill_missing_batch(monkeypatch):
    app = _make_app()
    step = app.steps[0]
    app.workflow.select_input("C:/tmp/input.xlsx")
    app.workflow.begin(step["name"])
    app.update_button_states = lambda: None
    prompt_calls = []
    monkeypatch.setattr(
        "metabolomics.gui.app.messagebox.askyesno",
        lambda *args, **kwargs: prompt_calls.append((args, kwargs)) or False,
    )

    app.on_step_error(step, "2 個樣本缺少 Batch 資訊；請先補齊 Batch 後再執行")

    assert prompt_calls
    assert "補齊 Batch" in prompt_calls[0][0][1]
