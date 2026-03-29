"""
Tests for Concentration_Normalization_v2 module (Step 4).

These tests verify:
1. Input validation (requires Step 3 output format)
2. Output structure (normalized data, summary)
3. PQN normalization logic
4. Return value format
"""
import pytest
import os
import warnings
from importlib import import_module
import numpy as np
import pandas as pd

from metabolomics.utils.constants import SHEET_NAMES


class TestConcentrationNormInput:
    """Tests for input validation."""

    def test_module_loads(self, conc_norm_module):
        """Test that module can be imported."""
        assert conc_norm_module is not None
        assert hasattr(conc_norm_module, 'main')

    def test_has_required_functions(self, conc_norm_module):
        """Test that module has expected functions."""
        assert hasattr(conc_norm_module, 'main'), "Should have main function"


class TestConcentrationNormHelpers:
    def test_get_summary_sheet_name_uses_method_specific_labels(
        self,
        conc_norm_module,
    ):
        assert conc_norm_module.get_summary_sheet_name("PQN") == "PQN_summary"
        assert conc_norm_module.get_summary_sheet_name("SampleSpecific") == "SpecNorm_summary"
        assert conc_norm_module.get_summary_sheet_name("CustomMethod") == "CustomMethod_summary"

    def test_determine_correction_sheet_accepts_legacy_qc_lowess_name(
        self,
        conc_norm_module,
    ):
        legacy_df = pd.DataFrame({"FeatureID": ["100.1/1.0"], "QC_1": [10.0]})
        sheets = {"QC LOWESS result": legacy_df, SHEET_NAMES["sample_info"]: pd.DataFrame()}

        selected_df, selected_name = conc_norm_module.determine_correction_sheet(sheets)

        assert selected_name == "QC LOWESS result"
        assert selected_df is legacy_df

    def test_get_all_sample_columns_excludes_ratio_and_stat_columns(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Normal_A", "Benign_A", "Exposure_A", "QC_1"],
                "Sample_Type": ["Normal", "Benign", "Exposure", "QC"],
            }
        )
        data_df = pd.DataFrame(
            {
                "FeatureID": ["100.1/1.0"],
                "Normal_A": [10.0],
                "Benign_A": [20.0],
                "Exposure_A": [30.0],
                "QC_1": [40.0],
                "exposure_ratio": [0.5],
                "normal_ratio": [0.6],
                "control_ratio": [0.7],
                "QC_ratio": [0.8],
                "Original_CV%": [12.0],
                "Normalized_CV%": [8.0],
            }
        )

        sample_columns = conc_norm_module.get_all_sample_columns(data_df, sample_info_df)

        assert sample_columns == ["Normal_A", "Benign_A", "Exposure_A", "QC_1"]

    def test_get_all_sample_columns_avoids_unknown_ratio_pseudo_samples(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Normal_A", "Benign_A", "Exposure_A", "QC_1"],
                "Sample_Type": ["Normal", "Benign", "Exposure", "QC"],
            }
        )
        data_df = pd.DataFrame(
            {
                "FeatureID": ["100.1/1.0"],
                "Normal_A": [10.0],
                "Benign_A": [20.0],
                "Exposure_A": [30.0],
                "QC_1": [40.0],
                "exposure_ratio": [0.5],
                "normal_ratio": [0.6],
                "control_ratio": [0.7],
                "QC_ratio": [0.8],
            }
        )

        sample_columns = conc_norm_module.get_all_sample_columns(data_df, sample_info_df)
        col_to_info_row = conc_norm_module.build_sample_info_mapping(sample_columns, sample_info_df)
        sample_types = [
            conc_norm_module._lookup_sample_type(sample, sample_info_df, col_to_info_row, default="Unknown")
            for sample in sample_columns
        ]

        assert "UNKNOWN" not in sample_types

    def test_build_sample_info_mapping_prefers_normalized_name_matches(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": [
                    "Tumor tissue BC2257_DNA",
                    "Normal tissue BC2257_DNA",
                    "Breast Cancer Tissue_ pooled_QC_1",
                ],
                "Sample_Type": ["Exposure", "Normal", "QC"],
                "Batch": ["A", "A", "A"],
                "Col4": [1, 2, 3],
                "Col5": [1, 2, 3],
                "Ref": [10.0, 11.0, 12.0],
            }
        )

        mapping = conc_norm_module.build_sample_info_mapping(
            [
                "TumorBC2257_DNA",
                "NormalBC2257_DNA",
                "Breast_Cancer_Tissue_pooled_QC_1",
            ],
            sample_info_df,
        )

        assert mapping["TumorBC2257_DNA"]["Sample_Type"] == "Exposure"
        assert mapping["NormalBC2257_DNA"]["Sample_Type"] == "Normal"
        assert mapping["Breast_Cancer_Tissue_pooled_QC_1"]["Sample_Type"] == "QC"

    def test_clean_dataframe_for_excel_avoids_future_warnings_and_preserves_mixed_columns(
        self,
        conc_norm_module,
    ):
        df = pd.DataFrame(
            {
                "Mz/RT": ["Sample_Type", "100.1/1.0", "200.2/2.0"],
                "Sample_A": ["QC", 123.4, "=SUM(A1:A2)"],
                "Sample_B": ["Exposure", "#REF!", 456.7],
                "Metric": [None, 3.2, 4.1],
            }
        )

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            cleaned = conc_norm_module.clean_dataframe_for_excel(df)

        assert cleaned.loc[2, "Sample_A"] == ""
        assert cleaned.loc[1, "Sample_B"] == ""
        assert cleaned.loc[0, "Sample_A"] == "QC"
        assert cleaned.loc[0, "Sample_B"] == "Exposure"
        assert cleaned["Metric"].dtype.kind in {"f", "i"}
        assert cleaned.loc[1, "Metric"] == pytest.approx(3.2)

    def test_sample_specific_normalization_handles_pathological_reference_values(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "Sample_A", "Sample_B", "Sample_C"],
                "Sample_Type": ["QC", "Exposure", "Control", "Exposure"],
                "Batch": ["A", "A", "B", "B"],
            }
        )
        sample_columns = ["QC_1", "Sample_A", "Sample_B", "Sample_C"]
        data_matrix = np.array(
            [
                [100.0, 200.0, 300.0, 400.0],
                [50.0, 100.0, 150.0, 200.0],
            ]
        )

        corrected, info = conc_norm_module.sample_specific_normalization(
            data_matrix,
            sample_info_df,
            sample_columns,
            np.array([np.nan, 50.0, 0.0, 5000.0], dtype=float),
            correction_col_name="Creatinine_mg_dL",
        )

        assert np.allclose(corrected[:, 0], data_matrix[:, 0], equal_nan=True)
        assert corrected[0, 1] == pytest.approx((200.0 / 50.0) * 2525.0)
        assert corrected[1, 1] == pytest.approx((100.0 / 50.0) * 2525.0)
        assert np.allclose(corrected[:, 2], data_matrix[:, 2], equal_nan=True)
        assert corrected[0, 3] == pytest.approx((400.0 / 5000.0) * 2525.0)
        assert corrected[1, 3] == pytest.approx((200.0 / 5000.0) * 2525.0)
        assert info["ref_valid_count"] == 2
        assert info["ref_median"] == pytest.approx(2525.0)

        corrected_no_valid, info_no_valid = conc_norm_module.sample_specific_normalization(
            data_matrix,
            sample_info_df,
            sample_columns,
            np.array([np.nan, 0.0, np.nan, -5.0], dtype=float),
            correction_col_name="Creatinine_mg_dL",
        )

        assert np.allclose(corrected_no_valid, data_matrix, equal_nan=True)
        assert info_no_valid["ref_valid_count"] == 0
        assert np.isnan(info_no_valid["ref_median"])



class TestConcentrationNormOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_with_step3_output(self, istd_module, qc_lowess_module,
                                     qc_batch_scaling_module, conc_norm_module,
                                     sample_input_file, validate_result_dict):
        """Test Concentration Normalization with Step 3 output."""
        # Run Steps 1-3
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        # Run Step 4
        step4_result = conc_norm_module.main(input_file=step3_output)

        validation = validate_result_dict(
            step4_result,
            required_keys=['output_path']
        )

        assert validation['is_processing_result'], f"Result should be ProcessingResult: {validation['errors']}"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_file_structure(self, istd_module, qc_lowess_module,
                                    qc_batch_scaling_module, conc_norm_module,
                                    sample_input_file, validate_excel_output):
        """Test output Excel file structure."""
        # Run Steps 1-3
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        # Run Step 4
        step4_result = conc_norm_module.main(input_file=step3_output)

        assert step4_result is not None
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get('output_path')
        assert step4_output

        validation = validate_excel_output(
            step4_output,
            min_rows=1
        )

        assert validation['exists'], f"Output file should exist"
        assert validation['readable'], f"Output file should be readable"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_step4_only_generates_first_four_figures(
        self,
        istd_module,
        qc_lowess_module,
        qc_batch_scaling_module,
        conc_norm_module,
        sample_input_file,
    ):
        """Step 4 (PQN) should generate expected figure set in plots directory."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        step4_result = conc_norm_module.main(input_file=step3_output)
        plots_dir = step4_result.plots_dir if hasattr(step4_result, "plots_dir") else step4_result.get('plots_dir')

        plot_files = sorted(
            name for name in os.listdir(plots_dir)
            if name.startswith("Step4_")
        )

        # Step4 generates: CV, RLE (with Total Intensity), Density, Dratio
        assert any("CV" in name for name in plot_files), f"Missing CV in {plot_files}"
        assert any("RLE" in name for name in plot_files), f"Missing RLE in {plot_files}"
        assert not any("Boxplot" in name for name in plot_files), f"Unexpected Boxplot in {plot_files}"
        assert not any("PCA" in name or "pca" in name.lower() for name in plot_files), f"Unexpected PCA in {plot_files}"
        # Scatter plot only for SampleSpecific mode — should NOT appear in default PQN
        assert not any("Scatter" in name for name in plot_files), f"Unexpected Scatter in PQN mode: {plot_files}"

    @pytest.mark.slow
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_keeps_qc_lowess_sheet_when_step3_is_skipped(
        self,
        istd_module,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 4 should fall back to the Step 2 data sheet when Step 3 was skipped."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step2_with_extra_sheet = copy_workbook_with_extra_sheet(step2_output)

        step4_result = conc_norm_module.main(input_file=step2_with_extra_sheet)
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get('output_path')

        assert set(workbook_sheet_names(step4_output)) == {
            SHEET_NAMES["qc_lowess"],
            'SampleInfo',
            'PQN_Result',
            conc_norm_module.get_summary_sheet_name('PQN'),
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_keeps_qc_batch_scaling_sheet_when_present(
        self,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 4 should prefer the new QC batch scaling result sheet."""
        qc_batch_scaling_module = import_module("metabolomics.processors.qc_batch_scaling")

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')
        step3_with_extra_sheet = copy_workbook_with_extra_sheet(step3_output)

        step4_result = conc_norm_module.main(input_file=step3_with_extra_sheet)
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get('output_path')

        assert set(workbook_sheet_names(step4_output)) == {
            'QC_Batch_Scaling_result',
            'SampleInfo',
            'PQN_Result',
            conc_norm_module.get_summary_sheet_name('PQN'),
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_step4_output_uses_mz_rt_as_feature_column(
        self,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
    ):
        qc_batch_scaling_module = import_module("metabolomics.processors.qc_batch_scaling")

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        step4_result = conc_norm_module.main(input_file=step3_output)
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get('output_path')

        result_df = pd.read_excel(step4_output, sheet_name='PQN_Result', nrows=1)
        preserved_df = pd.read_excel(step4_output, sheet_name='QC_Batch_Scaling_result', nrows=1)

        assert result_df.columns[0] == 'Mz/RT'
        assert preserved_df.columns[0] == 'Mz/RT'


class TestConcentrationNormSessionDir:
    """Tests for session_dir support in normalization."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_writes_to_session_dir(
        self,
        istd_module,
        qc_lowess_module,
        qc_batch_scaling_module,
        conc_norm_module,
        sample_input_file,
        tmp_path,
    ):
        """When session_dir is provided, output goes into that directory."""
        from pathlib import Path
        from metabolomics.utils.file_io import create_session_dir

        # Run Steps 1-3 to produce valid Step 4 input
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        session = create_session_dir(output_root=tmp_path)
        result = conc_norm_module.main(input_file=step3_output, session_dir=session)
        assert Path(result.output_path).is_relative_to(session)
        assert "Step4_" in Path(result.output_path).name


class TestFullPipeline:
    """Integration tests for full pipeline."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_full_pipeline_completes(self, run_full_pipeline):
        """Test that full pipeline completes without errors."""
        results = run_full_pipeline

        assert 'step1' in results, "Step 1 should complete"
        assert results['step1'] is not None, "Step 1 result should not be None"

        assert 'step2' in results, "Step 2 should complete"
        assert results['step2'] is not None, "Step 2 result should not be None"

        assert 'step3' in results, "Step 3 should complete"
        assert results['step3'] is not None, "Step 3 result should not be None"

        assert 'step4' in results, "Step 4 should complete"
        assert results['step4'] is not None, "Step 4 result should not be None"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_pipeline_output_files_exist(self, run_full_pipeline):
        """Test that all pipeline output files exist."""
        results = run_full_pipeline

        for step_name, result in results.items():
            if result and hasattr(result, "output_path"):
                assert os.path.exists(result.output_path), \
                    f"{step_name} output file should exist: {result.output_path}"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_pipeline_metabolite_count_preserved(self, run_full_pipeline):
        """Test that metabolite count is approximately preserved through pipeline."""
        results = run_full_pipeline

        metabolite_counts = []
        for step_name in ['step1', 'step2', 'step3', 'step4']:
            result = results.get(step_name)
            if result and hasattr(result, "metabolites"):
                metabolite_counts.append(result.metabolites)

        if len(metabolite_counts) >= 2:
            # Metabolite count should not change dramatically
            max_count = max(metabolite_counts)
            min_count = min(metabolite_counts)

            # Allow some variation due to filtering, but not more than 50% loss
            assert min_count >= max_count * 0.5, \
                f"Metabolite count should be relatively stable: {metabolite_counts}"
