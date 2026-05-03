"""Test session directory utilities and naming contracts."""

import pytest

from metabolomics.utils.file_io import create_session_dir, session_output_path, session_plots_dir


class TestSessionOutputUtilities:
    @pytest.fixture
    def session(self, tmp_path):
        return create_session_dir(output_root=tmp_path)

    def test_session_dir_structure(self, session):
        assert session.exists()
        assert (session / "plots").exists()

    def test_output_paths_all_land_in_session(self, session):
        for step, prefix in [
            (1, "ISTD_Results"),
            (2, "QC_LOESS"),
            (3, "Normalized_PQN"),
            (4, "QC_Batch_Scaling"),
        ]:
            path = session_output_path(session, step=step, prefix=prefix)
            assert path.parent == session
            assert path.name.startswith(f"Step{step}_")
            assert path.suffix == ".xlsx"

    def test_plots_dir_is_shared(self, session):
        plots = session_plots_dir(session)
        assert plots == session / "plots"

    def test_step_prefixed_filenames_sort_naturally(self, session):
        names = sorted([
            session_output_path(session, step=s, prefix=p).name
            for s, p in [(3, "C"), (1, "A"), (4, "D"), (2, "B")]
        ])
        assert names[0].startswith("Step1_")
        assert names[1].startswith("Step2_")
        assert names[2].startswith("Step3_")
        assert names[3].startswith("Step4_")
