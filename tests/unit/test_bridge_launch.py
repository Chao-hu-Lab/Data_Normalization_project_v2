from pathlib import Path

import pandas as pd

from metabolomics.bootstrap_paths import find_ms_core_src
from metabolomics.startup_bridge import apply_startup_bridge, parse_startup_args


def test_find_ms_core_src_prefers_worktree_copy(tmp_path):
    dnp_root = tmp_path / "Desktop" / "Data_Normalization_project_v2"
    dnp_root.mkdir(parents=True, exist_ok=True)

    main_src = tmp_path / "Desktop" / "MS Data process package" / "ms-core" / "src"
    worktree_src = (
        tmp_path
        / "Desktop"
        / "MS Data process package"
        / "ms-core"
        / ".worktrees"
        / "cross-project-bridge"
        / "src"
    )

    (main_src / "ms_core" / "utils").mkdir(parents=True, exist_ok=True)
    (worktree_src / "ms_core" / "utils").mkdir(parents=True, exist_ok=True)
    (worktree_src / "ms_core" / "utils" / "bridge_workspace.py").write_text(
        "# bridge marker",
        encoding="utf-8",
    )

    assert find_ms_core_src(dnp_root) == worktree_src


def test_parse_startup_args_reads_ms_bridge_options():
    args = parse_startup_args(
        ["--ms-session-dir", "C:/tmp/session", "--ms-bridge-file", "C:/tmp/input.xlsx"]
    )

    assert args.ms_session_dir == "C:/tmp/session"
    assert args.ms_bridge_file == "C:/tmp/input.xlsx"


def test_apply_startup_bridge_calls_set_input_file(tmp_path):
    bridge_file = tmp_path / "bridge.xlsx"
    bridge_file.write_text("placeholder", encoding="utf-8")

    calls: dict[str, str] = {}

    class DummyApp:
        def _set_input_file(self, value):
            calls["value"] = value

    assert apply_startup_bridge(DummyApp(), str(bridge_file)) is True
    assert calls["value"] == str(Path(bridge_file))


def test_export_to_metaboanalyst_uses_shared_session_bridge_and_launch_args(monkeypatch, tmp_path):
    from metabolomics.gui.app import DataNormalizationApp

    app = DataNormalizationApp.__new__(DataNormalizationApp)
    app.master = type("DummyMaster", (), {"config": lambda *a, **k: None, "update": lambda *a, **k: None})()
    app.export_meta_btn = type("DummyBtn", (), {"config": lambda *a, **k: None})()
    app.update_button_states = lambda *a, **k: None
    app.logger = type("DummyLogger", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})()
    app.steps = [
        {"name": "Step 1: ISTD Correction"},
        {"name": "Step 2: QC Correction"},
        {"name": "Step 3: Conc. Normalization"},
        {"name": "Step 4: QC Batch Scaling"},
    ]
    normalized = tmp_path / "Normalized.xlsx"
    normalized.write_text("placeholder", encoding="utf-8")
    app.step_outputs = {"Step 3: Conc. Normalization": {"output_path": str(normalized)}}
    app._ms_session_dir = tmp_path / "workspace" / "sessions" / "s1"
    app._ms_session_dir.mkdir(parents=True, exist_ok=True)
    (app._ms_session_dir / "manifest.json").write_text('{"stages": {}}', encoding="utf-8")

    created: dict[str, object] = {}

    def _fake_build_bridge_path(session_dir, stage, bucket, filename):
        path = Path(session_dir) / stage / bucket / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        created["path"] = path
        return path

    monkeypatch.setattr("metabolomics.gui.app.build_bridge_path", _fake_build_bridge_path)
    monkeypatch.setattr("metabolomics.gui.app.update_manifest", lambda *_a, **_k: {})
    monkeypatch.setattr("metabolomics.gui.app.messagebox.askyesno", lambda *_a, **_k: True)
    monkeypatch.setattr("metabolomics.gui.app.messagebox.showwarning", lambda *_a, **_k: None)
    monkeypatch.setattr("metabolomics.gui.app.messagebox.showerror", lambda *_a, **_k: None)

    import os as _os
    exists_impl = _os.path.exists
    monkeypatch.setattr(
        "metabolomics.gui.app.os.path.exists",
        lambda value: exists_impl(value) or str(value).endswith("main.py"),
    )
    monkeypatch.setattr(
        "metabolomics.gui.app.subprocess.Popen",
        lambda argv, cwd=None: created.setdefault("argv", argv),
    )

    def _fake_convert(source, target):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text("placeholder", encoding="utf-8")
        return target

    monkeypatch.setattr("metabolomics.gui.app._load_dnp_to_ma_adapter", lambda: _fake_convert)

    app.export_to_metaboanalyst()

    assert created["path"].parts[-3:-1] == ("dnp", "bridge_to_ma")
    assert "--ms-bridge-file" in created["argv"]
    assert "--ms-session-dir" in created["argv"]


def test_dnp_to_metaboanalyst_prefers_step3_result_sheet_before_legacy_step4(tmp_path):
    from metabolomics.adapters.dnp_to_metaboanalyst import convert_dnp_to_metaboanalyst

    input_path = tmp_path / "dnp.xlsx"
    output_path = tmp_path / "ma.xlsx"

    with pd.ExcelWriter(input_path, engine="openpyxl") as writer:
        pd.DataFrame({"Mz/RT": ["F1"], "Sample_A": [1.0]}).to_excel(
            writer,
            sheet_name="PQN_Result",
            index=False,
        )
        pd.DataFrame({"Mz/RT": ["F1"], "Sample_A": [9.0]}).to_excel(
            writer,
            sheet_name="QC_Batch_Scaling_result",
            index=False,
        )
        pd.DataFrame({"Sample_Name": ["Sample_A"], "Sample_Type": ["Control"]}).to_excel(
            writer,
            sheet_name="SampleInfo",
            index=False,
        )

    convert_dnp_to_metaboanalyst(str(input_path), str(output_path))

    converted = pd.read_excel(output_path, sheet_name="Data")
    assert converted.loc[0, "Sample_A"] == 1.0


def test_dnp_to_metaboanalyst_falls_back_to_specnorm_pqn_sheet(tmp_path):
    from metabolomics.adapters.dnp_to_metaboanalyst import convert_dnp_to_metaboanalyst

    input_path = tmp_path / "dnp_specnorm.xlsx"
    output_path = tmp_path / "ma_specnorm.xlsx"

    with pd.ExcelWriter(input_path, engine="openpyxl") as writer:
        pd.DataFrame({"Mz/RT": ["F1"], "Sample_A": [5.0]}).to_excel(
            writer,
            sheet_name="SpecNorm_PQN_Result",
            index=False,
        )
        pd.DataFrame({"Sample_Name": ["Sample_A"], "Sample_Type": ["Control"]}).to_excel(
            writer,
            sheet_name="SampleInfo",
            index=False,
        )

    convert_dnp_to_metaboanalyst(str(input_path), str(output_path))

    converted = pd.read_excel(output_path, sheet_name="Data")
    assert converted.loc[0, "Sample_A"] == 5.0
