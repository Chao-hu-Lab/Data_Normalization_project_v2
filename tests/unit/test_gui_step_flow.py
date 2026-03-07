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
        {"name": "Step 1: ISTD Correction", "module": "metabolomics.processors.istd"},
        {"name": "Step 2: QC Correction", "module": "metabolomics.processors.qc_lowess"},
        {"name": "Step 3: Batch Correction", "module": "metabolomics.processors.batch_effect"},
        {"name": "Step 4: Conc. Normalization", "module": "metabolomics.processors.normalization"},
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


def test_run_step_uses_previous_step_output_instead_of_last_output_file():
    app = _make_app()
    step = app.steps[2]
    captured = {}

    class _DummyModule:
        @staticmethod
        def main(input_file=None):
            captured["input_file"] = input_file
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


def test_on_step_error_invalidates_failed_step_and_downstream(monkeypatch):
    app = _make_app()
    step = app.steps[2]
    app.completed_steps = {
        "Step 1: ISTD Correction",
        "Step 2: QC Correction",
        "Step 3: Batch Correction",
        "Step 4: Conc. Normalization",
    }
    app.step_outputs = {
        "Step 2: QC Correction": {"output_path": "C:/tmp/step2-output.xlsx"},
        "Step 3: Batch Correction": {"output_path": "C:/tmp/step3-output.xlsx"},
        "Step 4: Conc. Normalization": {"output_path": "C:/tmp/step4-output.xlsx"},
    }
    app.last_output_file = "C:/tmp/step4-output.xlsx"
    app.update_button_states = lambda: None
    monkeypatch.setattr("metabolomics.gui.app.messagebox.askyesno", lambda *_a, **_k: False)

    app.on_step_error(step, "boom")

    assert "Step 3: Batch Correction" not in app.completed_steps
    assert "Step 4: Conc. Normalization" not in app.completed_steps
    assert "Step 3: Batch Correction" not in app.step_outputs
    assert "Step 4: Conc. Normalization" not in app.step_outputs
    assert app.last_output_file == "C:/tmp/step2-output.xlsx"
