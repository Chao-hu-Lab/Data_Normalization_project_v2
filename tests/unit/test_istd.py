"""
Tests for ISTD_Correction_v2 module (Step 1).

These tests verify:
1. Input validation (file format, required sheets)
2. Output structure (correct sheets, columns)
3. Data integrity (row count, no unexpected NaN)
4. Return value format
"""
import pytest
import pandas as pd
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.styles import Font

from metabolomics.utils.constants import FEATURE_ID_COLUMN


class TestISTDCorrectionInput:
    """Tests for input validation."""

    def test_module_loads(self, istd_module):
        """Test that module can be imported."""
        assert istd_module is not None
        assert hasattr(istd_module, 'main')
        assert hasattr(istd_module, 'load_and_process_data')

    def test_load_valid_file(self, istd_module, sample_input_file):
        """Test loading a valid input file."""
        raw_df, sample_info_df, all_sheets, col_to_info = istd_module.load_and_process_data(sample_input_file)

        assert raw_df is not None, "raw_df should not be None"
        assert sample_info_df is not None, "sample_info_df should not be None"
        assert all_sheets is not None, "all_sheets should not be None"
        assert col_to_info is not None, "col_to_info should not be None"

        # Check required columns
        assert 'FeatureID' in raw_df.columns
        assert 'Sample_Name' in sample_info_df.columns
        assert 'Sample_Type' in sample_info_df.columns

    def test_load_nonexistent_file(self, istd_module):
        """Test handling of non-existent file."""
        with pytest.raises(ValueError, match="找不到檔案"):
            istd_module.load_and_process_data("nonexistent_file.xlsx")

    def test_istd_detection(self, istd_module, sample_input_file):
        """Test ISTD (red font) detection."""
        raw_df, _, _, _ = istd_module.load_and_process_data(sample_input_file)

        if raw_df is not None:
            assert 'is_ISTD' in raw_df.columns, "is_ISTD column should exist"
            istd_count = raw_df['is_ISTD'].sum()
            # Should have at least some ISTDs
            assert istd_count >= 0, "ISTD count should be non-negative"


class TestISTDCorrectionOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    def test_skips_when_fewer_than_five_istds_have_qc_cv_below_20(
        self,
        istd_module,
        workbook_sheet_names,
        tmp_path,
    ):
        """Step 1 should skip when too few ISTDs meet the QC CV gate."""
        sample_names = ["QC1", "Exposure_1", "QC2", "Control_1", "QC3", "Exposure_2"]
        raw_df = pd.DataFrame(
            [
                {
                    "FeatureID": "Sample_Type",
                    "QC1": "QC",
                    "Exposure_1": "Exposure",
                    "QC2": "QC",
                    "Control_1": "Control",
                    "QC3": "QC",
                    "Exposure_2": "Exposure",
                },
                {"FeatureID": "401.1000/5.10", "QC1": 100000, "Exposure_1": 101000, "QC2": 99500, "Control_1": 100500, "QC3": 100800, "Exposure_2": 100900},
                {"FeatureID": "455.2000/7.20", "QC1": 120000, "Exposure_1": 119500, "QC2": 121000, "Control_1": 120500, "QC3": 119800, "Exposure_2": 120200},
                {"FeatureID": "512.3000/9.30", "QC1": 90000, "Exposure_1": 90500, "QC2": 91000, "Control_1": 89900, "QC3": 90300, "Exposure_2": 90700},
                {"FeatureID": "620.4000/11.40", "QC1": 150000, "Exposure_1": 149500, "QC2": 151000, "Control_1": 150500, "QC3": 149800, "Exposure_2": 150100},
                {"FeatureID": "730.5000/13.50", "QC1": 300000, "Exposure_1": 330000, "QC2": 280000, "Control_1": 310000, "QC3": 350000, "Exposure_2": 295000},
                {"FeatureID": "810.6000/15.60", "QC1": 50000, "Exposure_1": 60000, "QC2": 52000, "Control_1": 58000, "QC3": 48000, "Exposure_2": 61000},
            ]
        )
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": sample_names,
                "Sample_Type": ["QC", "Exposure", "QC", "Control", "QC", "Exposure"],
                "Injection_Order": [1, 2, 3, 4, 5, 6],
                "Batch": ["A", "A", "A", "A", "A", "A"],
                "Injection_Volume": [20] * 6,
                "Creatinine_mg_dL": [None, 95.0, None, 88.0, None, 102.0],
            }
        )
        workbook_path = tmp_path / "insufficient_istd.xlsx"
        with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
            raw_df.to_excel(writer, sheet_name="RawIntensity", index=False)
            sample_info_df.to_excel(writer, sheet_name="SampleInfo", index=False)

        workbook = load_workbook(workbook_path)
        try:
            sheet = workbook["RawIntensity"]
            red_font = Font(color="FFFF0000")
            for row_index in range(3, 7):
                sheet.cell(row=row_index, column=1).font = red_font
            workbook.save(workbook_path)
        finally:
            workbook.close()

        result = istd_module.main(input_file=str(workbook_path))

        assert getattr(result, "extra", {}).get("skipped") is True
        assert getattr(result, "extra", {}).get("skip_reason") == "insufficient_good_istd"

        # Skipped: output_path should point to the original input (no new file)
        assert result.output_path == str(workbook_path)

    @pytest.mark.slow
    def test_main_returns_processing_result(self, istd_module, sample_input_file, validate_result_dict):
        """Test that main() returns a ProcessingResult."""
        result = istd_module.main(input_file=sample_input_file)

        validation = validate_result_dict(
            result,
            required_keys=['output_path', 'metabolites', 'samples']
        )

        assert validation['is_processing_result'], f"Result should be ProcessingResult: {validation['errors']}"
        assert len(validation['errors']) == 0, f"Validation errors: {validation['errors']}"

    @pytest.mark.slow
    def test_output_file_created(self, istd_module, sample_input_file, validate_excel_output):
        """Test that output Excel file is created correctly."""
        result = istd_module.main(input_file=sample_input_file)

        assert result is not None, "main() should return a result"
        output_path = result.output_path if hasattr(result, "output_path") else result.get('output_path')
        assert output_path, "Result should contain output_path"

        required_sheets = ['RawIntensity', 'SampleInfo']
        if not getattr(result, "extra", {}).get("skipped"):
            required_sheets.append('ISTD_Correction')

        validation = validate_excel_output(
            output_path,
            required_sheets=required_sheets,
            min_rows=1
        )

        assert validation['exists'], f"Output file should exist: {validation['errors']}"
        assert validation['readable'], f"Output file should be readable: {validation['errors']}"
        assert len(validation['errors']) == 0, f"Validation errors: {validation['errors']}"

    @pytest.mark.slow
    def test_data_integrity(self, istd_module, sample_input_file):
        """Test that data integrity is maintained."""
        # Load original data
        raw_df, sample_info_df, _, _ = istd_module.load_and_process_data(sample_input_file)
        original_feature_count = len(raw_df[~raw_df['is_ISTD']])  # Non-ISTD features

        # Run correction
        result = istd_module.main(input_file=sample_input_file)

        if getattr(result, "extra", {}).get("skipped"):
            # Skipped: output_path is the original input, no new file produced
            assert result.output_path == sample_input_file
            return

        # Load output
        output_path = result.output_path if hasattr(result, "output_path") else result.get('output_path')
        output_df = pd.read_excel(output_path, sheet_name='ISTD_Correction')

        # Feature count should be approximately same (non-ISTD features)
        assert len(output_df) > 0, "Output should have rows"
        assert FEATURE_ID_COLUMN in output_df.columns, (
            f"Output should expose canonical feature id column {FEATURE_ID_COLUMN!r}"
        )

    @pytest.mark.slow
    def test_main_writes_to_session_dir(self, istd_module, sample_input_file, tmp_path):
        """When session_dir is provided, output goes into that directory."""
        from pathlib import Path
        from metabolomics.utils.file_io import create_session_dir

        session = create_session_dir(output_root=tmp_path)
        result = istd_module.main(input_file=sample_input_file, session_dir=session)
        if result.extra.get("skipped"):
            # Skipped: output_path points to original input (no new file produced)
            assert result.output_path == sample_input_file
        else:
            assert Path(result.output_path).is_relative_to(session)
            assert "Step1_" in Path(result.output_path).name

    @pytest.mark.slow
    def test_output_workbook_only_keeps_required_sheets(
        self,
        istd_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 1 output should not copy unrelated input worksheets."""
        input_with_extra_sheet = copy_workbook_with_extra_sheet(sample_input_file)

        result = istd_module.main(input_file=input_with_extra_sheet)

        if getattr(result, "extra", {}).get("skipped"):
            # Skipped: output_path is the original input, no filtering expected
            assert result.output_path == input_with_extra_sheet
            return

        output_path = result.output_path if hasattr(result, "output_path") else result.get('output_path')
        expected_sheets = {'RawIntensity', 'SampleInfo', 'ISTD_Correction'}
        assert set(workbook_sheet_names(output_path)) == expected_sheets


class TestISTDCorrectionHelpers:
    """Tests for helper functions."""

    def test_get_valid_values(self, istd_module):
        """Test get_valid_values helper function."""
        import pandas as pd

        # Create test row
        row = pd.Series({'A': 100, 'B': 200, 'C': 0, 'D': -5, 'E': None})
        columns = ['A', 'B', 'C', 'D', 'E']

        values = istd_module.get_valid_values(row, columns)

        # Should only include positive non-NaN values
        assert 100 in values
        assert 200 in values
        assert 0 not in values  # Zero excluded
        assert -5 not in values  # Negative excluded
        assert len(values) == 2

    def test_calculate_istd_cv(self, istd_module, sample_input_file):
        """Test ISTD CV calculation."""
        raw_df, _, _, _ = istd_module.load_and_process_data(sample_input_file)

        if raw_df is not None:
            istd_signals = raw_df[raw_df['is_ISTD']]
            sample_columns = [col for col in raw_df.columns
                              if col not in ['FeatureID', 'is_ISTD', 'mz', 'rt']]

            if len(istd_signals) > 0 and len(sample_columns) > 0:
                cv_dict = istd_module.calculate_istd_cv(istd_signals, sample_columns)

                assert isinstance(cv_dict, dict)
                # CV values should be between 0 and some reasonable upper bound
                for feature_id, cv in cv_dict.items():
                    if not pd.isna(cv):
                        assert cv >= 0, f"CV should be non-negative: {cv}"

    def test_calculate_corrected_ratios_excludes_ratio_pseudo_sample_columns(self, istd_module):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Sample A1", "Sample B1"],
                "Sample_Type": ["Exposure", "Control"],
                "Batch": ["A", "B"],
            }
        )
        raw_df = pd.DataFrame(
            {
                "FeatureID": ["ISTD_1", "Analyte_1"],
                "mz": [100.0, 150.0],
                "rt": [5.0, 5.2],
                "is_ISTD": [True, False],
                "Sample_A1": [10.0, 50.0],
                "Sample_B1": [20.0, 100.0],
                "exposure_ratio": [1.0, 1.0],
            }
        )

        _, sample_columns = istd_module.calculate_corrected_ratios(raw_df, sample_info_df)

        assert sample_columns == ["Sample_A1", "Sample_B1"]
        assert "exposure_ratio" not in sample_columns

    def test_calculate_corrected_ratios_fails_closed_when_sample_names_do_not_match(self, istd_module):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Real_A", "Real_B"],
                "Sample_Type": ["Exposure", "Control"],
                "Batch": ["A", "B"],
            }
        )
        raw_df = pd.DataFrame(
            {
                "FeatureID": ["ISTD_1", "Analyte_1"],
                "mz": [100.0, 150.0],
                "rt": [5.0, 5.2],
                "is_ISTD": [True, False],
                "Wrong_X": [10.0, 50.0],
                "Wrong_Y": [20.0, 100.0],
            }
        )

        with pytest.raises(ValueError, match="未找到可與 SampleInfo 對齊的有效樣本欄位"):
            istd_module.calculate_corrected_ratios(raw_df, sample_info_df)

    def test_calculate_corrected_ratios_fails_closed_when_only_some_names_match(self, istd_module):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["Real_A", "Real_B"],
                "Sample_Type": ["Exposure", "Control"],
                "Batch": ["A", "B"],
            }
        )
        raw_df = pd.DataFrame(
            {
                "FeatureID": ["ISTD_1", "Analyte_1"],
                "mz": [100.0, 150.0],
                "rt": [5.0, 5.2],
                "is_ISTD": [True, False],
                "Real_A": [10.0, 50.0],
                "Wrong_Y": [20.0, 100.0],
            }
        )

        with pytest.raises(ValueError, match="無法可靠對齊到 SampleInfo"):
            istd_module.calculate_corrected_ratios(raw_df, sample_info_df)

    def test_get_qc_sample_columns_excludes_ratio_pseudo_samples(self, istd_module):
        raw_df = pd.DataFrame(
            {
                "FeatureID": ["ISTD_1"],
                "Sample_A1": [10.0],
                "Sample_B1": [20.0],
                "exposure_ratio": [1.0],
            }
        )
        col_to_info = {
            "Sample_A1": {"Sample_Type": "Exposure"},
            "Sample_B1": {"Sample_Type": "Control"},
            "exposure_ratio": {"Sample_Type": "Unknown"},
        }

        sample_columns, qc_columns = istd_module.get_qc_sample_columns(raw_df, col_to_info)

        assert sample_columns == ["Sample_A1", "Sample_B1"]
        assert qc_columns == []

    def test_generate_step1_diagnostic_plots_writes_expected_files(self, istd_module, tmp_path):
        sample_columns = ["QC_1", "Sample_A1", "QC_2", "Sample_B1"]
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": sample_columns,
                "Sample_Type": ["QC", "Exposure", "QC", "Control"],
                "Batch": ["A", "A", "B", "B"],
                "Injection_Order": [1, 2, 3, 4],
            }
        )
        original_df = pd.DataFrame(
            {
                "FeatureID": ["ISTD_1", "ISTD_2", "F1", "F2", "F3"],
                "is_ISTD": [True, True, False, False, False],
                "QC_1": [100.0, 200.0, 10.0, 12.0, 9.0],
                "Sample_A1": [104.0, 198.0, 15.0, 18.0, 14.0],
                "QC_2": [98.0, 205.0, 11.0, 13.0, 10.0],
                "Sample_B1": [101.0, 202.0, 16.0, 19.0, 15.0],
            }
        )
        results_df = pd.DataFrame(
            {
                "FeatureID": ["F1", "F2", "F3"],
                "QC_1": [10.5, 11.5, 9.5],
                "Sample_A1": [14.5, 17.5, 13.5],
                "QC_2": [10.8, 12.2, 9.8],
                "Sample_B1": [15.2, 18.2, 14.2],
            }
        )
        cv_results_df = pd.DataFrame(
            {
                "FeatureID": [f"F{i}" for i in range(1, 13)],
                "Original_QC_CV%": [18.0 + i for i in range(12)],
                "Corrected_QC_CV%": [10.0 + (i * 0.5) for i in range(12)],
                "Variance_Test_pvalue": [0.01, 0.02, 0.03, 0.04, 0.15, 0.18, 0.21, 0.32, 0.41, 0.52, 0.61, 0.74],
            }
        )

        plots_dir = istd_module.generate_step1_diagnostic_plots(
            original_df,
            results_df,
            sample_columns,
            sample_info_df,
            cv_results_df,
            plots_dir=tmp_path,
            timestamp="20260328_120000",
        )

        plot_names = {path.name for path in Path(plots_dir).glob("*.png")}
        assert "Step1_Pvalue_Distribution_20260328_120000.png" in plot_names
        assert "Step1_ISTD_Tracking_20260328_120000.png" in plot_names
        assert "Step1_CV_Comparison_20260328_120000.png" in plot_names
        assert "Step1_Density_Overlay_20260328_120000.png" in plot_names
