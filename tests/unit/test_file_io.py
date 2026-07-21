from metabolomics.utils import file_io
from metabolomics.utils.file_io import (
    create_session_dir,
    session_output_path,
    session_plots_dir,
)


class TestOutputRootInference:
    def test_tmp_path_fixture_stays_under_repo_build_tree(self, tmp_path):
        parts = tmp_path.parts

        assert "build" in parts
        assert "pytest" in parts
        assert "tmp-fixtures" in parts
        assert tmp_path.exists()

    def test_get_output_root_prefers_input_file_output_ancestor(self, tmp_path):
        upstream_output = tmp_path / "upstream-toolkit" / ".worktrees" / "feature-branch" / "output"
        input_file = upstream_output / "QC_LOESS_20260307_004818.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == upstream_output

    def test_build_plots_dir_uses_inferred_output_root(self, tmp_path):
        upstream_output = tmp_path / "upstream-toolkit" / ".worktrees" / "feature-branch" / "output"
        input_file = upstream_output / "QC_LOESS_20260307_004818.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()

        plots_dir = file_io.build_plots_dir(
            "Normalization_Figures",
            timestamp="20260307_010203",
            session_prefix="PQN",
            input_file=str(input_file),
        )

        expected = upstream_output / "Normalization_Figures" / "PQN_20260307_010203"
        assert plots_dir == expected
        assert plots_dir.exists()

    def test_get_output_root_still_accepts_legacy_qc_lowess_filename(self, tmp_path):
        upstream_output = tmp_path / "upstream-toolkit" / ".worktrees" / "feature-branch" / "output"
        input_file = upstream_output / "QC_LOWESS_20260307_004818.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == upstream_output

    def test_get_output_root_preserves_nested_test_data_runs_subtree(self, tmp_path):
        upstream_output = (
            tmp_path
            / "repo"
            / "output"
            / "test_data_runs"
            / "strong_batch"
            / "run_20260329_120000"
        )
        input_file = upstream_output / "Step2_QC_LOESS.xlsx"
        (upstream_output / "plots").mkdir(parents=True, exist_ok=True)
        input_file.touch()

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == upstream_output.parent

    def test_get_output_root_routes_scenario_matrix_to_test_data_runs(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        input_file = repo_root / "data" / "scenario_matrices" / "strong_batch.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()
        monkeypatch.setattr(file_io, "get_project_root", lambda: repo_root)

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == repo_root / "output" / "test_data_runs" / "strong_batch"
        assert output_root.exists()

    def test_get_output_root_routes_repo_test_inputs_to_test_data_runs(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        input_file = repo_root / "tests" / "fixtures" / "smoke_input.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()
        monkeypatch.setattr(file_io, "get_project_root", lambda: repo_root)

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == repo_root / "output" / "test_data_runs" / "smoke_input"
        assert output_root.exists()

    def test_get_output_root_routes_repo_data_inputs_during_pytest(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        input_file = repo_root / "data" / "feature_matrix_with_qc_non_group_AfterVBA.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()
        monkeypatch.setattr(file_io, "get_project_root", lambda: repo_root)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/unit/test_file_io.py::test_case")

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == repo_root / "output" / "test_data_runs" / input_file.stem
        assert output_root.exists()

    def test_get_output_root_routes_external_temp_inputs_during_pytest(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        external_root = tmp_path / "external"
        input_file = external_root / "Step2_QC_LOESS_with_extra.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()
        monkeypatch.setattr(file_io, "get_project_root", lambda: repo_root)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/unit/test_file_io.py::test_case")

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == repo_root / "output" / "test_data_runs" / input_file.stem
        assert output_root.exists()


class TestSessionDir:
    def test_create_session_dir_creates_timestamped_folder(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        assert session.exists()
        assert session.parent == tmp_path
        assert session.name.startswith("run_")

    def test_create_session_dir_creates_plots_subdir(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        assert (session / "plots").exists()

    def test_session_output_path_returns_path_in_session(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        path = session_output_path(session, step=1, prefix="ISTD_Results")
        assert path.parent == session
        assert path.name == "Step1_ISTD_Results.xlsx"

    def test_session_plots_dir_returns_plots_subdir(self, tmp_path):
        session = create_session_dir(output_root=tmp_path)
        plots = session_plots_dir(session)
        assert plots == session / "plots"
        assert plots.exists()

    def test_resolve_session_dir_reuses_existing_upstream_run(self, tmp_path):
        session = create_session_dir(output_root=tmp_path, timestamp="20260329_120000")
        input_file = session / "Step2_QC_LOESS.xlsx"
        input_file.touch()

        resolved = file_io.resolve_session_dir(input_file=str(input_file))

        assert resolved == session

    def test_resolve_session_dir_autocreates_pytest_session(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        input_file = repo_root / "data" / "feature_matrix_with_qc_non_group_AfterVBA.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()
        monkeypatch.setattr(file_io, "get_project_root", lambda: repo_root)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/unit/test_file_io.py::test_case")

        session = file_io.resolve_session_dir(input_file=str(input_file))

        assert session is not None
        assert session.parent == repo_root / "output" / "test_data_runs" / input_file.stem
        assert session.name.startswith("run_")
        assert (session / "plots").exists()
