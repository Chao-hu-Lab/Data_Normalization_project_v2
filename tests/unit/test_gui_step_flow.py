from __future__ import annotations

from datetime import datetime
import queue
import threading

from metabolomics.gui.app import DataNormalizationApp


class _DummyWidget:
    def __init__(self):
        self.config_calls = []

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


class _DummyMaster:
    def after(self, _delay, _callback):
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
        {"name": "Step 2: QC Correction", "module": "metabolomics.processors.qc_lowess", "accent": "#34a853"},
        {"name": "Step 3: Conc. Normalization", "module": "metabolomics.processors.normalization", "accent": "#f9ab00"},
        {"name": "Step 4: QC Batch Scaling", "module": "metabolomics.processors.qc_batch_scaling", "accent": "#ea4335"},
    ]
    app.master = _DummyMaster()
    app.logger = _DummyLogger()
    app.cancel_flag = threading.Event()
    app.progress_queue = queue.Queue()
    app.execution_start_time = datetime.now()
    app.selected_file_path = None
    app.last_output_file = None
    app.completed_steps = set()
    app.step_outputs = {}
    app.current_session_dir = None
    app.step_status_labels = [_DummyWidget() for _ in app.steps]
    app.step_buttons = [_DummyWidget() for _ in app.steps]
    app.step_excel_buttons = [_DummyWidget() for _ in app.steps]
    app.step_plot_buttons = [_DummyWidget() for _ in app.steps]
    app.step_cards = [_DummyWidget() for _ in app.steps]
    app.cancel_btn = _DummyWidget()
    app.stats_completed_label = _DummyWidget()
    app.export_meta_btn = _DummyWidget()
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


def test_build_workflow_steps_exposes_four_ordered_steps():
    steps = DataNormalizationApp._build_workflow_steps()

    assert [step["name"] for step in steps] == [
        "Step 1: ISTD Correction",
        "Step 2: QC Correction",
        "Step 3: Conc. Normalization",
        "Step 4: QC Batch Scaling",
    ]


def test_get_step_card_label_marks_step4_as_paused_diagnostics_only():
    assert DataNormalizationApp._get_step_card_label("Step 4: QC Batch Scaling") == "QC Batch Scaling (paused / diagnostics-only)"
    assert DataNormalizationApp._get_step_card_label("Step 3: Conc. Normalization") == "Conc. Normalization"


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
    assert tokens["columns"] == 4
    assert tokens["run_all"]["width"] == 14
    assert tokens["stop"]["width"] == 14
    assert tokens["reset"]["width"] == 14
    assert tokens["export"]["width"] == 14
    assert tokens["export"]["disabled_text"] == "Export After Step 3"


def test_build_header_button_tokens_raise_secondary_action_contrast():
    tokens = DataNormalizationApp._build_header_button_tokens()

    assert tokens["run_all"]["bg"] == "#2563eb"
    assert tokens["run_all"]["fg"] == "#ffffff"
    assert tokens["stop"]["bg"] == "#dc2626"
    assert tokens["stop"]["fg"] == "#ffffff"
    assert tokens["export"]["disabled_bg"] == "#94a3b8"
    assert tokens["export"]["disabled_fg"] == "#f8fafc"
    assert tokens["export"]["disabled_relief"] == "flat"


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


def test_ensure_workflow_state_tracks_export_readiness_from_completed_steps():
    app = _make_app()
    app.completed_steps = {
        "Step 1: ISTD Correction",
        "Step 2: QC Correction",
        "Step 3: Conc. Normalization",
    }
    app.step_outputs = {
        "Step 3: Conc. Normalization": {"output_path": "C:/tmp/step3-output.xlsx"},
    }

    app._ensure_workflow_state()

    assert app.workflow_state["selected_file_path"] is None
    assert app.workflow_state["completed_steps"] == app.completed_steps
    assert app.workflow_state["export_ready"] is True
    assert [step["name"] for step in app.workflow_state["steps"]] == [
        "Step 1: ISTD Correction",
        "Step 2: QC Correction",
        "Step 3: Conc. Normalization",
        "Step 4: QC Batch Scaling",
    ]


def test_render_pipeline_nav_highlights_next_incomplete_step():
    app = _make_app()
    app.pipeline_nav_labels = [_DummyWidget() for _ in app.steps]
    app.completed_steps = {"Step 1: ISTD Correction"}
    expected_primary = app.color_scheme.get("primary", "#1a73e8")

    app._render_pipeline_nav()

    assert app.pipeline_nav_labels[1].config_calls[-1]["bg"] == expected_primary
    assert app.pipeline_nav_labels[0].config_calls[-1]["bg"] == "#0d1b2a"
    assert app.pipeline_nav_labels[0].config_calls[-1]["fg"] == "#9fb3c8"


def test_update_button_states_keeps_disabled_export_readable():
    app = _make_app()
    app.pipeline_nav_labels = [_DummyWidget() for _ in app.steps]

    app.update_button_states()

    assert app.export_meta_btn.config_calls[-1]["text"] == "Export After Step 3"
    assert app.export_meta_btn.config_calls[-1]["bg"] == "#94a3b8"
    assert app.export_meta_btn.config_calls[-1]["fg"] == "#f8fafc"


def test_update_button_states_enables_export_after_step3_output_exists():
    app = _make_app()
    app.pipeline_nav_labels = [_DummyWidget() for _ in app.steps]
    app.completed_steps = {
        "Step 1: ISTD Correction",
        "Step 2: QC Correction",
        "Step 3: Conc. Normalization",
    }
    app.step_outputs = {
        "Step 3: Conc. Normalization": {"output_path": "C:/tmp/step3-output.xlsx"},
    }

    app.update_button_states()

    assert app.export_meta_btn.config_calls[-1]["state"] == "normal"
    assert app.export_meta_btn.config_calls[-1]["text"] == "Export to MetaboAnalyst"


def test_run_step_uses_previous_step_output_instead_of_last_output_file():
    app = _make_app()
    step = app.steps[2]
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None, **kwargs):
            captured["input_file"] = input_file
            captured.update(kwargs)
            return {
                "output_path": "C:/tmp/step3-output.xlsx",
                "metabolites": 10,
                "samples": 5,
            }

    app.last_output_file = "C:/tmp/stale-step4-output.xlsx"
    app.step_outputs = {
        "Step 2: QC Correction": {
            "output_path": "C:/tmp/current-step2-output.xlsx",
        }
    }
    app.load_script = lambda _module_name: _DummyModule()

    app.run_step(step)

    assert captured["input_file"] == "C:/tmp/current-step2-output.xlsx"
    assert captured["normalization_method"] == "PQN"


def test_run_step_passes_selected_specnorm_pqn_method_to_normalization():
    app = _make_app()
    step = app.steps[2]
    app.normalization_method = type("DummyVar", (), {"get": lambda _self: "SpecNorm+PQN"})()
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None, **kwargs):
            captured.update(kwargs)
            return {
                "output_path": "C:/tmp/step3-output.xlsx",
                "metabolites": 10,
                "samples": 5,
            }

    app.step_outputs = {
        "Step 2: QC Correction": {
            "output_path": "C:/tmp/current-step2-output.xlsx",
        }
    }
    app.load_script = lambda _module_name: _DummyModule()

    app.run_step(step)

    assert captured["normalization_method"] == "SpecNorm+PQN"


def test_run_step_passes_diagnostics_only_to_step4():
    app = _make_app()
    step = app.steps[3]
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None, **kwargs):
            captured["input_file"] = input_file
            captured.update(kwargs)
            return {
                "output_path": "C:/tmp/step4-diagnostics.xlsx",
                "metabolites": 10,
                "samples": 5,
            }

    app.step_outputs = {
        "Step 3: Conc. Normalization": {
            "output_path": "C:/tmp/current-step3-output.xlsx",
        }
    }
    app.load_script = lambda _module_name: _DummyModule()

    app.run_step(step)

    assert captured["input_file"] == "C:/tmp/current-step3-output.xlsx"
    assert captured["diagnostics_only"] is True


def test_on_step_error_invalidates_failed_step_and_downstream(monkeypatch):
    app = _make_app()
    step = app.steps[2]
    app.completed_steps = {
        "Step 1: ISTD Correction",
        "Step 2: QC Correction",
        "Step 3: Conc. Normalization",
        "Step 4: QC Batch Scaling",
    }
    app.step_outputs = {
        "Step 2: QC Correction": {"output_path": "C:/tmp/step2-output.xlsx"},
        "Step 3: Conc. Normalization": {"output_path": "C:/tmp/step3-output.xlsx"},
        "Step 4: QC Batch Scaling": {"output_path": "C:/tmp/step4-output.xlsx"},
    }
    app.last_output_file = "C:/tmp/step4-output.xlsx"
    app.update_button_states = lambda: None
    monkeypatch.setattr("metabolomics.gui.app.messagebox.askyesno", lambda *_a, **_k: False)

    app.on_step_error(step, "boom")

    assert "Step 3: Conc. Normalization" not in app.completed_steps
    assert "Step 4: QC Batch Scaling" not in app.completed_steps
    assert "Step 3: Conc. Normalization" not in app.step_outputs
    assert "Step 4: QC Batch Scaling" not in app.step_outputs
    assert app.last_output_file == "C:/tmp/step2-output.xlsx"
