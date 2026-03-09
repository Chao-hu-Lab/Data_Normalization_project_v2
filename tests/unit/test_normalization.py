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
from importlib import import_module
import pandas as pd


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

    def test_plot_pca_with_confidence_ellipse_excludes_qc_and_uses_dynamic_groups(
        self,
        conc_norm_module,
        tmp_path,
        monkeypatch,
    ):
        captured = {}

        def fake_plotter(*args, **kwargs):
            captured["sample_names"] = args[4]
            captured["sample_types"] = args[5]
            output_path = kwargs.get("output_path")
            if output_path:
                with open(output_path, "wb") as handle:
                    handle.write(b"png")
            return None, (None, None)

        monkeypatch.setattr(conc_norm_module, "plot_pca_comparison_real_sample_style", fake_plotter)

        original_data = pd.DataFrame(
            {
                "QC_1": [10.0, 11.0, 12.0],
                "Normal_A": [20.0, 21.0, 22.0],
                "Benign_A": [30.0, 31.0, 32.0],
                "Exposure_A": [40.0, 41.0, 42.0],
            }
        ).to_numpy()
        normalized_data = original_data * 1.1
        sample_names = ["QC_1", "Normal_A", "Benign_A", "Exposure_A"]
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "Normal_A", "Benign_A", "Exposure_A"],
                "Sample_Type": ["QC", "Normal", "Benign", "Exposure"],
            }
        )
        col_to_info_row = {
            name: sample_info_df.iloc[index]
            for index, name in enumerate(sample_names)
        }

        conc_norm_module.plot_pca_with_confidence_ellipse(
            original_data,
            normalized_data,
            sample_names,
            sample_info_df,
            tmp_path / "step4_pca.png",
            "PQN_SampleSpecific",
            exclude_qc=True,
            col_to_info_row=col_to_info_row,
        )

        assert captured["sample_names"] == ["Normal_A", "Benign_A", "Exposure_A"]
        assert captured["sample_types"] == ["Normal", "Control", "Exposure"]


class TestConcentrationNormOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_with_step3_output(self, istd_module, qc_lowess_module,
                                     batch_effect_module, conc_norm_module,
                                     sample_input_file, validate_result_dict):
        """Test Concentration Normalization with Step 3 output."""
        # Run Steps 1-3
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = batch_effect_module.main(input_file=step2_output)
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
                                    batch_effect_module, conc_norm_module,
                                    sample_input_file, validate_excel_output):
        """Test output Excel file structure."""
        # Run Steps 1-3
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = batch_effect_module.main(input_file=step2_output)
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
        batch_effect_module,
        conc_norm_module,
        sample_input_file,
    ):
        """Step 4 should only emit Fig1-Fig4 in the plots directory."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = batch_effect_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        step4_result = conc_norm_module.main(input_file=step3_output)
        plots_dir = step4_result.plots_dir if hasattr(step4_result, "plots_dir") else step4_result.get('plots_dir')

        plot_files = os.listdir(plots_dir)

        assert any(name.startswith("Fig1_") for name in plot_files)
        assert any(name.startswith("Fig2_") for name in plot_files)
        assert any(name.startswith("Fig3_") for name in plot_files)
        assert any(name.startswith("Fig4_") for name in plot_files)
        assert not any(name.startswith("Fig5_") for name in plot_files)
        assert not any(name.startswith("Fig6_") for name in plot_files)
        assert not any(name.startswith("Fig7_") for name in plot_files)

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_keeps_batch_effect_sheet_when_present(
        self,
        istd_module,
        qc_lowess_module,
        batch_effect_module,
        conc_norm_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 4 should preserve the actual Step 3 data sheet when Batch Effect ran."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = batch_effect_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')
        step3_with_extra_sheet = copy_workbook_with_extra_sheet(step3_output)

        step4_result = conc_norm_module.main(input_file=step3_with_extra_sheet)
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get('output_path')

        assert set(workbook_sheet_names(step4_output)) == {
            'Batch_effect_result',
            'SampleInfo',
            'PQN_SampleSpecific_Result',
            'ConcNormalization_Summary',
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_keeps_qc_lowess_sheet_when_batch_effect_is_skipped(
        self,
        istd_module,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 4 should fall back to the Step 2 data sheet when Batch Effect was skipped."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step2_with_extra_sheet = copy_workbook_with_extra_sheet(step2_output)

        step4_result = conc_norm_module.main(input_file=step2_with_extra_sheet)
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get('output_path')

        assert set(workbook_sheet_names(step4_output)) == {
            'QC LOWESS result',
            'SampleInfo',
            'PQN_SampleSpecific_Result',
            'ConcNormalization_Summary',
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
            'PQN_SampleSpecific_Result',
            'ConcNormalization_Summary',
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

        result_df = pd.read_excel(step4_output, sheet_name='PQN_SampleSpecific_Result', nrows=1)
        preserved_df = pd.read_excel(step4_output, sheet_name='QC_Batch_Scaling_result', nrows=1)

        assert result_df.columns[0] == 'Mz/RT'
        assert preserved_df.columns[0] == 'Mz/RT'


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
