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
from openpyxl import load_workbook
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
        assert conc_norm_module.get_summary_sheet_name("SpecNorm_PQN") == "SpecNorm_PQN_summary"
        assert conc_norm_module.get_summary_sheet_name("SampleSpecific") == "SpecNorm_PQN_summary"
        assert conc_norm_module.get_summary_sheet_name("CustomMethod") == "CustomMethod_summary"

    def test_canonicalize_normalization_method_accepts_specnorm_aliases(
        self,
        conc_norm_module,
    ):
        assert conc_norm_module.canonicalize_normalization_method("PQN") == "PQN"
        assert conc_norm_module.canonicalize_normalization_method("SpecNorm+PQN") == "SpecNorm_PQN"
        assert conc_norm_module.canonicalize_normalization_method("SpecNorm_PQN") == "SpecNorm_PQN"
        assert conc_norm_module.canonicalize_normalization_method("SampleSpecific") == "SpecNorm_PQN"

    def test_determine_correction_sheet_accepts_legacy_qc_lowess_name(
        self,
        conc_norm_module,
    ):
        legacy_df = pd.DataFrame({"FeatureID": ["100.1/1.0"], "QC_1": [10.0]})
        sheets = {"QC LOWESS result": legacy_df, SHEET_NAMES["sample_info"]: pd.DataFrame()}

        selected_df, selected_name = conc_norm_module.determine_correction_sheet(sheets)

        assert selected_name == "QC LOWESS result"
        assert selected_df is legacy_df

    def test_determine_correction_sheet_prefers_step2_over_old_qc_batch_scaling(
        self,
        conc_norm_module,
    ):
        step2_df = pd.DataFrame({"FeatureID": ["100.1/1.0"], "QC_1": [10.0]})
        old_step4_df = pd.DataFrame({"FeatureID": ["100.1/1.0"], "QC_1": [99.0]})
        sheets = {
            SHEET_NAMES["qc_batch_scaling"]: old_step4_df,
            SHEET_NAMES["qc_lowess"]: step2_df,
            SHEET_NAMES["sample_info"]: pd.DataFrame(),
        }

        selected_df, selected_name = conc_norm_module.determine_correction_sheet(sheets)

        assert selected_name == SHEET_NAMES["qc_lowess"]
        assert selected_df is step2_df

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

    def test_get_all_sample_columns_excludes_presence_absence_marker(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Sample_A", "Sample_B", "QC_1"],
                "Sample_Type": ["Exposure", "Normal", "QC"],
            }
        )
        data_df = pd.DataFrame(
            {
                "Mz/RT": ["100.1/1.0"],
                "Sample_A": [10.0],
                "Sample_B": [20.0],
                "QC_1": [30.0],
                "is_Presence_Absence_Marker": [True],
            }
        )

        sample_columns = conc_norm_module.get_all_sample_columns(data_df, sample_info_df)

        assert sample_columns == ["Sample_A", "Sample_B", "QC_1"]

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

    def test_build_sample_info_mapping_does_not_positionally_guess_equal_length_inputs(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Real_A", "Real_B"],
                "Sample_Type": ["Exposure", "Control"],
                "Batch": ["A", "B"],
            }
        )

        mapping = conc_norm_module.build_sample_info_mapping(
            ["Wrong_X", "Wrong_Y"],
            sample_info_df,
        )

        assert mapping == {}

    def test_perform_normalization_fails_closed_when_sample_mapping_is_incomplete(
        self,
        conc_norm_module,
    ):
        data_df = pd.DataFrame(
            {
                "Mz/RT": ["100.1/1.0", "200.2/2.0"],
                "Wrong_X": [10.0, 20.0],
                "Wrong_Y": [30.0, 40.0],
            }
        )
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Real_A", "Real_B"],
                "Sample_Type": ["Exposure", "Control"],
            }
        )

        with pytest.raises(ValueError, match="未找到可與 SampleInfo 對齊的有效樣本欄位"):
            conc_norm_module.perform_normalization(
                data_df,
                sample_info_df,
                file_path="dummy.xlsx",
                normalization_method="PQN",
                available_sheet_names=["RawIntensity", "SampleInfo"],
            )

    def test_perform_normalization_fails_closed_when_only_some_columns_match(
        self,
        conc_norm_module,
    ):
        data_df = pd.DataFrame(
            {
                "Mz/RT": ["100.1/1.0", "200.2/2.0"],
                "Real_A": [10.0, 20.0],
                "Wrong_Y": [30.0, 40.0],
            }
        )
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Real_A", "Real_B"],
                "Sample_Type": ["Exposure", "Control"],
            }
        )

        with pytest.raises(ValueError, match="無法可靠對齊到 SampleInfo"):
            conc_norm_module.perform_normalization(
                data_df,
                sample_info_df,
                file_path="dummy.xlsx",
                normalization_method="PQN",
                available_sheet_names=["RawIntensity", "SampleInfo"],
            )

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
        assert corrected[0, 1] == pytest.approx(200.0 / 50.0)
        assert corrected[1, 1] == pytest.approx(100.0 / 50.0)
        assert np.allclose(corrected[:, 2], data_matrix[:, 2], equal_nan=True)
        assert corrected[0, 3] == pytest.approx(400.0 / 5000.0)
        assert corrected[1, 3] == pytest.approx(200.0 / 5000.0)
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

    def test_specnorm_division_does_not_multiply_reference_median(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "Sample_A", "Sample_B"],
                "Sample_Type": ["QC", "Exposure", "Control"],
                "Batch": ["A", "A", "A"],
            }
        )
        sample_columns = ["QC_1", "Sample_A", "Sample_B"]
        data_matrix = np.array([[100.0, 200.0, 300.0]], dtype=float)

        corrected, info = conc_norm_module.specnorm_reference_division(
            data_matrix,
            sample_info_df,
            sample_columns,
            np.array([np.nan, 50.0, 150.0], dtype=float),
            correction_col_name="Creatinine_mg_dL",
        )

        assert corrected[0, 0] == pytest.approx(100.0)
        assert corrected[0, 1] == pytest.approx(4.0)
        assert corrected[0, 2] == pytest.approx(2.0)
        assert info["ref_median"] == pytest.approx(100.0)
        assert info["reference_strategy"] == "SpecNorm"

    def test_specnorm_pqn_does_not_apply_feature_median_scale_back(
        self,
        conc_norm_module,
    ):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "Sample_A", "Sample_B"],
                "Sample_Type": ["QC", "Exposure", "Control"],
                "Batch": ["A", "A", "A"],
            }
        )
        sample_columns = ["QC_1", "Sample_A", "Sample_B"]
        data_matrix = np.array(
            [
                [100.0, 200.0, 400.0],
                [50.0, 100.0, 300.0],
            ],
            dtype=float,
        )

        normalized, info = conc_norm_module.specnorm_pqn_normalization(
            data_matrix,
            sample_info_df,
            sample_columns,
            np.array([np.nan, 50.0, 100.0], dtype=float),
            correction_col_name="Creatinine_mg_dL",
        )

        assert normalized == pytest.approx(
            np.array(
                [
                    [100.0, 100.0, 80.0],
                    [50.0, 50.0, 60.0],
                ]
            )
        )
        assert info["reference_strategy"] == "SpecNorm_PQN"
        assert info["scale_back_strategy"] == "none"

    def test_build_step4_summary_context_detects_upstream_step_status(
        self,
        conc_norm_module,
    ):
        context_loess = conc_norm_module.build_step4_summary_context(
            "QC LOESS result",
            available_sheet_names=["RawIntensity", "QC LOESS result", "SampleInfo"],
        )
        context_batch = conc_norm_module.build_step4_summary_context(
            "ISTD_Correction",
            available_sheet_names=["ISTD_Correction", "SampleInfo"],
        )

        assert "已執行" in context_loess["step2_status"]
        assert "未見 ISTD_Correction" in context_loess["step1_status"]
        assert "未執行或已跳過" in context_batch["step2_status"]
        assert "可見 ISTD_Correction" in context_batch["step1_status"]

    def test_create_normalization_summary_report_uses_context_and_objective_sections(
        self,
        conc_norm_module,
    ):
        quality_metrics = {
            "median_cv_before": 20.55,
            "median_cv_after": 20.61,
            "mean_cv_before": 22.3,
            "mean_cv_after": 22.0,
            "cv_improvement": -0.06,
            "cv_improvement_pct": -0.3,
            "cv_improved_ratio": 57.8,
            "cv_wilcoxon_stat": 1107.0,
            "cv_wilcoxon_pvalue": 0.327,
            "total_cv_before": 43.97,
            "total_cv_after": 26.05,
            "total_cv_improvement": 17.92,
            "sample_corr_mean_before": 0.9627,
            "sample_corr_mean_after": 0.9627,
            "sample_corr_std_before": 0.0720,
            "sample_corr_std_after": 0.0720,
            "data_range_before": 100.0,
            "data_range_after": 90.0,
        }
        subset_metrics = {
            "qc_median_cv_before": 20.55,
            "qc_median_cv_after": 20.61,
            "qc_cv_improved_ratio": 57.8,
            "real_median_cv_before": 56.14,
            "real_median_cv_after": 55.08,
            "real_cv_improved_ratio": 57.8,
            "real_total_cv_before": 43.97,
            "real_total_cv_after": 26.05,
            "qc_total_cv_before": 14.40,
            "qc_total_cv_after": 14.24,
        }
        pqn_info = {
            "reference_strategy": "QC",
            "qc_count": 7,
            "qc_cv": 18.89,
            "real_count": 78,
            "normalization_factors_real": np.array([0.1359, 0.8, 1.3028]),
            "normalization_factors_qc": np.array([1.0]),
        }
        summary_context = {
            "source_sheet_name": "QC LOESS result",
            "step1_status": "目前工作簿未見 ISTD_Correction 工作表",
            "step3_status": "未執行或已跳過（直接使用 QC-LOESS 結果）",
        }

        report = conc_norm_module.create_normalization_summary_report(
            quality_metrics=quality_metrics,
            method_name="PQN",
            n_features=64,
            n_samples=85,
            pqn_info=pqn_info,
            group_diff_results=None,
            subset_metrics=subset_metrics,
            summary_context=summary_context,
            mapped_sample_count=85,
        )

        assert "【執行上下文】" in report
        assert "上一步輸入工作表: QC LOESS result" in report
        assert "樣本數量（含 QC）: 85" in report
        assert "名稱成功映射樣本數: 85/85" in report
        assert "PQN 因子範圍: 0.1359 – 1.3028" in report
        assert "【QC 與真實樣本分層評估】" in report
        assert "QC feature CV 中位數: 20.55% -> 20.61%" in report
        assert "真實樣本總強度CV%: 43.97% -> 26.05%" in report
        assert "【整體評分】" not in report
        assert "標準化質量評分" not in report



    def test_save_normalization_results_uses_in_memory_preserved_dataframes(
        self,
        conc_norm_module,
        tmp_path,
    ):
        normalized_df = pd.DataFrame(
            {
                "Mz/RT": ["100.1/1.0"],
                "Sample_A": [123.4],
            }
        )
        preserved_data_df = pd.DataFrame(
            {
                "Mz/RT": ["100.1/1.0"],
                "Sample_A": [55.0],
            }
        )
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Sample_A"],
                "Sample_Type": ["Exposure"],
            }
        )

        output_path = conc_norm_module.save_normalization_results(
            normalized_df=normalized_df,
            summary_report="= Summary\n【Section】\n✓ ok",
            file_path=str(tmp_path / "nonexistent_input.xlsx"),
            method_name="PQN",
            preserved_data_sheet_name=SHEET_NAMES["qc_lowess"],
            sample_info_sheet_name=SHEET_NAMES["sample_info"],
            output_dir=tmp_path,
            preserved_data_df=preserved_data_df,
            sample_info_df=sample_info_df,
            output_path=tmp_path / "step4_perf_contract.xlsx",
        )

        workbook = pd.ExcelFile(output_path)
        assert set(workbook.sheet_names) == {
            "PQN_Result",
            "PQN_summary",
            SHEET_NAMES["qc_lowess"],
            SHEET_NAMES["sample_info"],
        }

        preserved_sheet = pd.read_excel(output_path, sheet_name=SHEET_NAMES["qc_lowess"])
        assert preserved_sheet.loc[0, "Sample_A"] == pytest.approx(55.0)


class TestConcentrationNormOutput:
    """Tests for output validation."""

    @staticmethod
    def _write_step4_input_workbook(workbook_path, include_marker=True):
        raw_df = pd.DataFrame(
            {
                "Mz/RT": ["Sample_Type", "100.1/1.0", "200.2/2.0", "300.3/3.0"],
                "QC_1": ["QC", 10.0, 20.0, 30.0],
                "QC_2": ["QC", 11.0, 21.0, 31.0],
                "Sample_A": ["Exposure", 100.0, 200.0, 300.0],
                "Sample_B": ["Normal", 110.0, 210.0, 310.0],
            }
        )
        if include_marker:
            raw_df["is_Presence_Absence_Marker"] = [
                "is_Presence_Absence_Marker",
                True,
                False,
                True,
            ]

        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "QC_2", "Sample_A", "Sample_B"],
                "Sample_Type": ["QC", "QC", "Exposure", "Normal"],
            }
        )

        with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
            raw_df.to_excel(writer, sheet_name=SHEET_NAMES["raw_intensity"], index=False)
            sample_info_df.to_excel(writer, sheet_name=SHEET_NAMES["sample_info"], index=False)

    def test_main_preserves_presence_absence_marker_in_pqn_result(
        self,
        conc_norm_module,
        output_dir,
    ):
        input_path = os.path.join(output_dir, "step4_marker_input.xlsx")
        if os.path.exists(input_path):
            os.remove(input_path)
        self._write_step4_input_workbook(input_path, include_marker=True)

        step4_result = conc_norm_module.main(input_file=str(input_path))
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get("output_path")

        workbook = load_workbook(step4_output, read_only=True, data_only=True)
        try:
            ws = workbook["PQN_Result"]
            headers = [cell.value for cell in ws[1]]
            marker_col = headers.index("is_Presence_Absence_Marker") + 1

            assert ws.cell(row=2, column=marker_col).value == "is_Presence_Absence_Marker"
            assert ws.cell(row=3, column=marker_col).value is True
            assert ws.cell(row=4, column=marker_col).value is False
            assert ws.cell(row=5, column=marker_col).value is True
        finally:
            workbook.close()

    def test_main_skips_presence_absence_marker_when_missing(
        self,
        conc_norm_module,
        output_dir,
    ):
        input_path = os.path.join(output_dir, "step4_no_marker_input.xlsx")
        if os.path.exists(input_path):
            os.remove(input_path)
        self._write_step4_input_workbook(input_path, include_marker=False)

        step4_result = conc_norm_module.main(input_file=str(input_path))
        step4_output = step4_result.output_path if hasattr(step4_result, "output_path") else step4_result.get("output_path")

        result_df = pd.read_excel(step4_output, sheet_name="PQN_Result", nrows=1)

        assert "is_Presence_Absence_Marker" not in result_df.columns

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_with_step2_output(self, istd_module, qc_lowess_module,
                                     qc_batch_scaling_module, conc_norm_module,
                                     sample_input_file, validate_result_dict):
        """Test Concentration Normalization with Step 2 output."""
        # Run Steps 1-2
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        step3_result = conc_norm_module.main(input_file=step2_output)

        validation = validate_result_dict(
            step3_result,
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
        step3_result = conc_norm_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        step4_result = qc_batch_scaling_module.main(input_file=step3_output)

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
    def test_step3_only_generates_first_four_figures(
        self,
        istd_module,
        qc_lowess_module,
        qc_batch_scaling_module,
        conc_norm_module,
        sample_input_file,
    ):
        """Step 3 (PQN) should generate expected figure set in plots directory."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = conc_norm_module.main(input_file=step2_output)
        plots_dir = step3_result.plots_dir if hasattr(step3_result, "plots_dir") else step3_result.get('plots_dir')

        plot_files = sorted(
            name for name in os.listdir(plots_dir)
            if name.startswith("Step3_")
        )

        # Step3 generates: CV, RLE (with Total Intensity), Density, Dratio
        assert any("CV" in name for name in plot_files), f"Missing CV in {plot_files}"
        assert any("RLE" in name for name in plot_files), f"Missing RLE in {plot_files}"
        assert not any("Boxplot" in name for name in plot_files), f"Unexpected Boxplot in {plot_files}"
        assert not any("PCA" in name or "pca" in name.lower() for name in plot_files), f"Unexpected PCA in {plot_files}"
        # Scatter plot only for SpecNorm+PQN mode — should NOT appear in default PQN
        assert not any("Scatter" in name for name in plot_files), f"Unexpected Scatter in PQN mode: {plot_files}"

    @pytest.mark.slow
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_keeps_qc_lowess_sheet_for_step3_input(
        self,
        istd_module,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 3 should keep the selected Step 2 data sheet."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step2_with_extra_sheet = copy_workbook_with_extra_sheet(step2_output)

        step3_result = conc_norm_module.main(input_file=step2_with_extra_sheet)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        assert set(workbook_sheet_names(step3_output)) == {
            SHEET_NAMES["qc_lowess"],
            'SampleInfo',
            'PQN_Result',
            conc_norm_module.get_summary_sheet_name('PQN'),
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_ignores_old_qc_batch_scaling_sheet_when_present(
        self,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 3 should prefer Step 2 data over stale QC batch scaling sheets."""
        qc_batch_scaling_module = import_module("metabolomics.processors.qc_batch_scaling")

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = qc_batch_scaling_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')
        step3_with_extra_sheet = copy_workbook_with_extra_sheet(step3_output)

        step3_norm_result = conc_norm_module.main(input_file=step3_with_extra_sheet)
        step3_norm_output = step3_norm_result.output_path if hasattr(step3_norm_result, "output_path") else step3_norm_result.get('output_path')

        assert set(workbook_sheet_names(step3_norm_output)) == {
            SHEET_NAMES["qc_lowess"],
            'SampleInfo',
            'PQN_Result',
            conc_norm_module.get_summary_sheet_name('PQN'),
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_step3_output_uses_mz_rt_as_feature_column(
        self,
        qc_lowess_module,
        conc_norm_module,
        sample_input_file,
    ):
        qc_batch_scaling_module = import_module("metabolomics.processors.qc_batch_scaling")

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step3_result = conc_norm_module.main(input_file=step2_output)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        result_df = pd.read_excel(step3_output, sheet_name='PQN_Result', nrows=1)
        preserved_df = pd.read_excel(step3_output, sheet_name=SHEET_NAMES["qc_lowess"], nrows=1)

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

        # Run Steps 1-2 to produce valid Step 3 input
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        session = create_session_dir(output_root=tmp_path)
        result = conc_norm_module.main(input_file=step2_output, session_dir=session)
        assert Path(result.output_path).is_relative_to(session)
        assert "Step3_" in Path(result.output_path).name


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
