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
            session_prefix="PQN_SampleSpecific",
            input_file=str(input_file),
        )

        expected = upstream_output / "Normalization_Figures" / "PQN_SampleSpecific_20260307_010203"
        assert plots_dir == expected
        assert plots_dir.exists()
