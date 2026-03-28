"""
Tests for the QC Batch Scaling processor (new Step 3).

These tests lock the intended semantics before implementation:
1. `Batch` parsing trims whitespace around semicolon-separated labels
2. QC samples may contribute to multiple batches
3. Non-QC samples may not belong to multiple batches
4. Batch scaling uses the median QC intensity of the sample's batch
"""
from importlib import import_module
from importlib.util import find_spec

import numpy as np
import pandas as pd
import pytest
from pathlib import Path


def load_qc_batch_scaling_module():
    """Import the module only after asserting it exists."""
    assert find_spec("metabolomics.processors.qc_batch_scaling") is not None
    return import_module("metabolomics.processors.qc_batch_scaling")


def build_sample_info():
    return pd.DataFrame(
        {
            "Sample_Name": [
                "QC_1",
                "QC_2",
                "QC_3",
                "QC_4",
                "QC_5",
                "Sample_A1",
                "Sample_B1",
            ],
            "Sample_Type": [
                "QC",
                "QC",
                "QC",
                "QC",
                "QC",
                "Exposure",
                "Control",
            ],
            "Batch": [
                "A",
                "A",
                "A; B",
                "B",
                "B",
                "A",
                "B",
            ],
        }
    )


class TestQCBatchScalingHelpers:
    def test_parse_batch_labels_trims_whitespace(self):
        module = load_qc_batch_scaling_module()

        assert module.parse_batch_labels("A;B") == ["A", "B"]
        assert module.parse_batch_labels("A; B") == ["A", "B"]
        assert module.parse_batch_labels(" A ; B ") == ["A", "B"]

    def test_multi_batch_qc_is_added_to_both_batch_qc_pools(self):
        module = load_qc_batch_scaling_module()
        sample_info_df = build_sample_info()

        batch_to_qc, batch_to_samples = module.build_batch_membership(sample_info_df)

        assert "QC_3" in batch_to_qc["A"]
        assert "QC_3" in batch_to_qc["B"]
        assert "Sample_A1" in batch_to_samples["A"]
        assert "Sample_B1" in batch_to_samples["B"]

    def test_build_batch_membership_maps_sampleinfo_names_to_data_columns(self):
        module = load_qc_batch_scaling_module()
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": [
                    "Breast Cancer Tissue pooled QC 1",
                    "Breast Cancer Tissue pooled QC 2",
                    "Breast Cancer Tissue pooled QC 3",
                    "Sample A1",
                ],
                "Sample_Type": ["QC", "QC", "QC", "Exposure"],
                "Batch": ["A", "A", "A;B", "A"],
            }
        )
        sample_columns = [
            "Breast_Cancer_Tissue_pooled_QC_1",
            "Breast_Cancer_Tissue_pooled_QC_2",
            "Breast_Cancer_Tissue_pooled_QC_3",
            "Sample_A1",
        ]

        batch_to_qc, batch_to_samples = module.build_batch_membership(
            sample_info_df,
            sample_columns=sample_columns,
        )

        assert batch_to_qc["A"] == [
            "Breast_Cancer_Tissue_pooled_QC_1",
            "Breast_Cancer_Tissue_pooled_QC_2",
            "Breast_Cancer_Tissue_pooled_QC_3",
        ]
        assert batch_to_samples["A"][-1] == "Sample_A1"

    def test_non_qc_sample_cannot_belong_to_multiple_batches(self):
        module = load_qc_batch_scaling_module()
        sample_info_df = build_sample_info()
        sample_info_df.loc[sample_info_df["Sample_Name"] == "Sample_A1", "Batch"] = "A;B"

        with pytest.raises(ValueError, match="single batch"):
            module.build_batch_membership(sample_info_df)

    def test_batch_scaling_uses_batch_specific_qc_median(self):
        module = load_qc_batch_scaling_module()

        feature_row = pd.Series(
            {
                "FeatureID": "100.1/5.0",
                "QC_1": 10.0,
                "QC_2": 20.0,
                "QC_3": 30.0,
                "QC_4": 40.0,
                "QC_5": 50.0,
                "Sample_A1": 60.0,
                "Sample_B1": 120.0,
            }
        )
        batch_to_qc = {
            "A": ["QC_1", "QC_2", "QC_3"],
            "B": ["QC_3", "QC_4", "QC_5"],
        }
        batch_to_samples = {
            "A": ["QC_1", "QC_2", "QC_3", "Sample_A1"],
            "B": ["QC_3", "QC_4", "QC_5", "Sample_B1"],
        }

        scaled, medians = module.scale_feature_by_batch_qc_median(
            feature_row, batch_to_qc, batch_to_samples
        )

        assert medians["A"] == pytest.approx(20.0)
        assert medians["B"] == pytest.approx(40.0)
        assert scaled["Sample_A1"] == pytest.approx(3.0)
        assert scaled["Sample_B1"] == pytest.approx(3.0)

    def test_calculate_batch_residuals_includes_multi_batch_memberships(self):
        module = load_qc_batch_scaling_module()

        scaled_matrix = np.array(
            [
                [1.0, 2.0],
                [3.0, 4.0],
                [5.0, 6.0],
            ]
        )
        sample_columns = ["QC_1", "QC_2", "QC_3"]
        batch_memberships = [("A",), ("A", "B"), ("B",)]

        residuals = module.calculate_batch_residuals(
            scaled_matrix,
            sample_columns,
            batch_memberships,
        )

        assert set(residuals) == {"A", "B"}
        assert residuals["A"] == pytest.approx(np.array([-1.0, -1.0]))
        assert residuals["B"] == pytest.approx(np.array([1.0, 1.0]))

    def test_prepare_residual_matrix_clips_negative_values_and_returns_finite_matrix(self):
        module = load_qc_batch_scaling_module()

        data_df = pd.DataFrame(
            {
                "FeatureID": ["F1", "F2", "F3"],
                "QC_1": [10.0, -5.0, 40.0],
                "QC_2": [20.0, 0.0, 30.0],
                "Sample_A1": [15.0, 5.0, 35.0],
            }
        )

        scaled_matrix = module.prepare_residual_matrix(data_df, ["QC_1", "QC_2", "Sample_A1"])

        assert scaled_matrix.shape == (3, 3)
        assert np.isfinite(scaled_matrix).all()

    def test_batch_scaling_reduces_mean_absolute_residual_on_synthetic_batch_bias(self):
        module = load_qc_batch_scaling_module()

        data_df = pd.DataFrame(
            {
                "FeatureID": ["F1", "F2"],
                "QC_1": [100.0, 110.0],
                "QC_2": [102.0, 112.0],
                "QC_3": [300.0, 330.0],
                "QC_4": [306.0, 336.0],
                "Sample_A1": [98.0, 108.0],
                "Sample_B1": [294.0, 324.0],
            }
        )
        sample_columns = ["QC_1", "QC_2", "QC_3", "QC_4", "Sample_A1", "Sample_B1"]
        batch_to_qc = {
            "A": ["QC_1", "QC_2"],
            "B": ["QC_3", "QC_4"],
        }
        batch_to_samples = {
            "A": ["QC_1", "QC_2", "Sample_A1"],
            "B": ["QC_3", "QC_4", "Sample_B1"],
        }
        batch_memberships = [
            ("A",),
            ("A",),
            ("B",),
            ("B",),
            ("A",),
            ("B",),
        ]

        result_df, _ = module.scale_dataframe_by_qc_medians(
            data_df,
            sample_columns,
            batch_to_qc,
            batch_to_samples,
        )

        residuals_before = module.calculate_batch_residuals(
            module.prepare_residual_matrix(data_df, sample_columns),
            sample_columns,
            batch_memberships,
        )
        residuals_after = module.calculate_batch_residuals(
            module.prepare_residual_matrix(result_df, sample_columns),
            sample_columns,
            batch_memberships,
        )

        mean_abs_before = np.mean([np.abs(values).mean() for values in residuals_before.values()])
        mean_abs_after = np.mean([np.abs(values).mean() for values in residuals_after.values()])

        assert mean_abs_after < mean_abs_before

    def test_plot_batch_residual_analysis_uses_single_batch_labels(self, tmp_path):
        module = load_qc_batch_scaling_module()

        fig = module.plot_batch_residual_analysis(
            {
                "A": np.array([-0.2, 0.1]),
                "B": np.array([0.2, -0.1]),
            },
            {
                "A": np.array([-0.05, 0.02]),
                "B": np.array([0.05, -0.02]),
            },
            output_path=tmp_path / "residual.png",
        )

        legend_labels = {
            text.get_text()
            for ax in fig.axes
            for legend in [ax.get_legend()]
            if legend is not None
            for text in legend.get_texts()
        }

        assert "Batch A" in legend_labels
        assert "Batch B" in legend_labels
        assert "A;B" not in legend_labels


class TestQCBatchScalingOutput:
    def test_generate_pca_plots_skips_batch_plot_when_only_one_batch(self, tmp_path):
        module = load_qc_batch_scaling_module()

        source_df = pd.DataFrame(
            {
                "FeatureID": ["F1", "F2", "F3"],
                "QC_1": [10.0, 20.0, 30.0],
                "QC_2": [11.0, 19.0, 29.0],
                "QC_3": [12.0, 18.0, 28.0],
                "Sample_A1": [13.0, 17.0, 27.0],
                "Sample_A2": [14.0, 16.0, 26.0],
            }
        )
        result_df = source_df.copy()
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "QC_2", "QC_3", "Sample_A1", "Sample_A2"],
                "Sample_Type": ["QC", "QC", "QC", "Exposure", "Control"],
                "Batch": ["A", "A", "A", "A", "A"],
            }
        )

        plots_dir = module.generate_pca_plots(
            source_df,
            result_df,
            ["QC_1", "QC_2", "QC_3", "Sample_A1", "Sample_A2"],
            sample_info_df,
            str(tmp_path / "input.xlsx"),
            "20260323_120000",
        )

        plot_names = {path.name for path in Path(plots_dir).glob("*.png")}
        # PCA removed — no PCA plots should be generated
        assert not any("PCA" in name for name in plot_names), f"Unexpected PCA plot: {plot_names}"

    def test_generate_pca_plots_also_writes_residual_analysis(self, tmp_path):
        module = load_qc_batch_scaling_module()

        source_df = pd.DataFrame(
            {
                "FeatureID": ["F1", "F2", "F3"],
                "QC_1": [10.0, 20.0, 30.0],
                "QC_2": [11.0, 19.0, 29.0],
                "QC_3": [12.0, 18.0, 28.0],
                "Sample_A1": [13.0, 17.0, 27.0],
                "Sample_B1": [40.0, 50.0, 60.0],
            }
        )
        result_df = pd.DataFrame(
            {
                "FeatureID": ["F1", "F2", "F3"],
                "QC_1": [1.0, 1.0, 1.0],
                "QC_2": [1.1, 0.95, 0.97],
                "QC_3": [1.2, 0.9, 0.93],
                "Sample_A1": [1.3, 0.85, 0.9],
                "Sample_B1": [1.4, 1.05, 1.1],
            }
        )
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "QC_2", "QC_3", "Sample_A1", "Sample_B1"],
                "Sample_Type": ["QC", "QC", "QC", "Exposure", "Control"],
                "Batch": ["A", "A; B", "B", "A", "B"],
            }
        )

        plots_dir = module.generate_pca_plots(
            source_df,
            result_df,
            ["QC_1", "QC_2", "QC_3", "Sample_A1", "Sample_B1"],
            sample_info_df,
            str(tmp_path / "input.xlsx"),
            "20260308_130000",
        )

        plot_names = {path.name for path in Path(plots_dir).glob("*.png")}

        # PCA removed — only residual analysis should be generated
        assert not any("PCA" in name for name in plot_names), f"Unexpected PCA plot: {plot_names}"
        assert "Step3_Residual_Analysis_20260308_130000.png" in plot_names

        residual_plots = list(Path(plots_dir).glob("Step3_Residual_Analysis_*.png"))
        assert residual_plots, "Residual Analysis figure should be generated"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_creates_expected_workbook_from_step2_output(
        self,
        qc_lowess_module,
        sample_input_file,
        workbook_sheet_names,
    ):
        module = load_qc_batch_scaling_module()

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        step3_result = module.main(input_file=step2_output)
        step3_output = (
            step3_result.output_path
            if hasattr(step3_result, "output_path")
            else step3_result.get("output_path")
        )

        assert set(workbook_sheet_names(step3_output)) == {
            "QC LOWESS result",
            "SampleInfo",
            "QC_Batch_Scaling_result",
            "QC_Batch_Scaling_summary",
        }

        plots_dir = (
            step3_result.plots_dir
            if hasattr(step3_result, "plots_dir")
            else step3_result.get("plots_dir")
        )
        assert plots_dir, "QC Batch Scaling should report a plots directory"
        assert "QC_Batch_Scaling_plots" in plots_dir

        plot_files = sorted(Path(plots_dir).glob("*.png"))
        assert len(plot_files) >= 1, "QC Batch Scaling should generate plot PNG files"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_step3_output_uses_mz_rt_as_feature_column(
        self,
        qc_lowess_module,
        sample_input_file,
    ):
        module = load_qc_batch_scaling_module()

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        step3_result = module.main(input_file=step2_output)
        step3_output = (
            step3_result.output_path
            if hasattr(step3_result, "output_path")
            else step3_result.get("output_path")
        )

        result_df = pd.read_excel(step3_output, sheet_name="QC_Batch_Scaling_result", nrows=1)
        source_df = pd.read_excel(step3_output, sheet_name="QC LOWESS result", nrows=1)

        assert result_df.columns[0] == "Mz/RT"
        assert source_df.columns[0] == "Mz/RT"

    @pytest.mark.slow
    def test_main_writes_to_session_dir(self, qc_batch_scaling_module, sample_input_file, tmp_path):
        """When session_dir is provided, output goes into that directory."""
        from pathlib import Path
        from metabolomics.utils.file_io import create_session_dir

        session = create_session_dir(output_root=tmp_path)
        result = qc_batch_scaling_module.main(input_file=sample_input_file, session_dir=session)
        assert Path(result.output_path).is_relative_to(session)
        assert "Step3_" in Path(result.output_path).name

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_logs_stage_progress(
        self,
        qc_lowess_module,
        sample_input_file,
        capsys,
    ):
        module = load_qc_batch_scaling_module()

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        module.main(input_file=step2_output)

        captured = capsys.readouterr().out
        assert "QC Batch Scaling" in captured
        assert "batch membership" in captured
        assert "QC batch median scaling" in captured
        assert "residual" in captured
