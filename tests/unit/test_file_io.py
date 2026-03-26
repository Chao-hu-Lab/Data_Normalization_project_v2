from pathlib import Path

from metabolomics.utils import file_io


class TestOutputRootInference:
    def test_get_output_root_prefers_input_file_output_ancestor(self, tmp_path):
        upstream_output = tmp_path / "ms-core" / ".worktrees" / "cross-project-bridge" / "output"
        input_file = upstream_output / "QC_LOWESS_20260307_004818.xlsx"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.touch()

        output_root = file_io.get_output_root(input_file=str(input_file))

        assert output_root == upstream_output

    def test_build_plots_dir_uses_inferred_output_root(self, tmp_path):
        upstream_output = tmp_path / "ms-core" / ".worktrees" / "cross-project-bridge" / "output"
        input_file = upstream_output / "QC_LOWESS_20260307_004818.xlsx"
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


from metabolomics.utils.file_io import (
    create_session_dir,
    session_output_path,
    session_plots_dir,
)


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
