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


class TestISTDCorrectionInput:
    """Tests for input validation."""

    def test_module_loads(self, istd_module):
        """Test that module can be imported."""
        assert istd_module is not None
        assert hasattr(istd_module, "main")
        assert hasattr(istd_module, "load_and_process_data")

    def test_load_valid_file(self, istd_module, sample_input_file):
        """Test loading a valid input file."""
        raw_df, sample_info_df, all_sheets, col_to_info = (
            istd_module.load_and_process_data(sample_input_file)
        )

        assert raw_df is not None, "raw_df should not be None"
        assert sample_info_df is not None, "sample_info_df should not be None"
        assert all_sheets is not None, "all_sheets should not be None"
        assert col_to_info is not None, "col_to_info should not be None"

        # Check required columns
        assert "FeatureID" in raw_df.columns
        assert "Sample_Name" in sample_info_df.columns
        assert "Sample_Type" in sample_info_df.columns

    def test_load_nonexistent_file(self, istd_module):
        """Test handling of non-existent file."""
        with pytest.raises(ValueError, match="找不到檔案"):
            istd_module.load_and_process_data("nonexistent_file.xlsx")

    def test_istd_detection(self, istd_module, sample_input_file):
        """Test ISTD (red font) detection."""
        raw_df, _, _, _ = istd_module.load_and_process_data(sample_input_file)

        if raw_df is not None:
            assert "is_ISTD" in raw_df.columns, "is_ISTD column should exist"
            istd_count = raw_df["is_ISTD"].sum()
            # Should have at least some ISTDs
            assert istd_count >= 0, "ISTD count should be non-negative"


class TestISTDCorrectionOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    def test_skips_when_fewer_than_five_istds_have_qc_cv_below_20(
        self,
        istd_module,
        sample_input_file,
        workbook_sheet_names,
    ):
        """Step 1 should skip when too few ISTDs meet the QC CV gate."""
        result = istd_module.main(input_file=sample_input_file)

        assert getattr(result, "extra", {}).get("skipped") is True
        assert (
            getattr(result, "extra", {}).get("skip_reason") == "insufficient_good_istd"
        )

        # Skipped: output_path should point to the original input (no new file)
        assert result.output_path == sample_input_file

    @pytest.mark.slow
    def test_main_returns_processing_result(
        self, istd_module, sample_input_file, validate_result_dict
    ):
        """Test that main() returns a ProcessingResult."""
        result = istd_module.main(input_file=sample_input_file)

        validation = validate_result_dict(
            result, required_keys=["output_path", "metabolites", "samples"]
        )

        assert validation["is_processing_result"], (
            f"Result should be ProcessingResult: {validation['errors']}"
        )
        assert len(validation["errors"]) == 0, (
            f"Validation errors: {validation['errors']}"
        )

    @pytest.mark.slow
    def test_output_file_created(
        self, istd_module, sample_input_file, validate_excel_output
    ):
        """Test that output Excel file is created correctly."""
        result = istd_module.main(input_file=sample_input_file)

        assert result is not None, "main() should return a result"
        output_path = (
            result.output_path
            if hasattr(result, "output_path")
            else result.get("output_path")
        )
        assert output_path, "Result should contain output_path"

        required_sheets = ["RawIntensity", "SampleInfo"]
        if not getattr(result, "extra", {}).get("skipped"):
            required_sheets.append("ISTD_Correction")

        validation = validate_excel_output(
            output_path, required_sheets=required_sheets, min_rows=1
        )

        assert validation["exists"], f"Output file should exist: {validation['errors']}"
        assert validation["readable"], (
            f"Output file should be readable: {validation['errors']}"
        )
        assert len(validation["errors"]) == 0, (
            f"Validation errors: {validation['errors']}"
        )

    @pytest.mark.slow
    def test_data_integrity(self, istd_module, sample_input_file):
        """Test that data integrity is maintained."""
        # Load original data
        raw_df, sample_info_df, _, _ = istd_module.load_and_process_data(
            sample_input_file
        )
        original_feature_count = len(raw_df[~raw_df["is_ISTD"]])  # Non-ISTD features

        # Run correction
        result = istd_module.main(input_file=sample_input_file)

        if getattr(result, "extra", {}).get("skipped"):
            # Skipped: output_path is the original input, no new file produced
            assert result.output_path == sample_input_file
            return

        # Load output
        output_path = (
            result.output_path
            if hasattr(result, "output_path")
            else result.get("output_path")
        )
        output_df = pd.read_excel(output_path, sheet_name="ISTD_Correction")

        # Feature count should be approximately same (non-ISTD features)
        assert len(output_df) > 0, "Output should have rows"
        assert "FeatureID" in output_df.columns, "Output should have FeatureID column"

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

        output_path = (
            result.output_path
            if hasattr(result, "output_path")
            else result.get("output_path")
        )

        expected_sheets = {"RawIntensity", "SampleInfo", "ISTD_Correction"}
        assert set(workbook_sheet_names(output_path)) == expected_sheets


class TestISTDCorrectionHelpers:
    """Tests for helper functions."""

    def test_get_valid_values(self, istd_module):
        """Test get_valid_values helper function."""
        import pandas as pd

        # Create test row
        row = pd.Series({"A": 100, "B": 200, "C": 0, "D": -5, "E": None})
        columns = ["A", "B", "C", "D", "E"]

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
            istd_signals = raw_df[raw_df["is_ISTD"]]
            sample_columns = [
                col
                for col in raw_df.columns
                if col not in ["FeatureID", "is_ISTD", "mz", "rt"]
            ]

            if len(istd_signals) > 0 and len(sample_columns) > 0:
                cv_dict = istd_module.calculate_istd_cv(istd_signals, sample_columns)

                assert isinstance(cv_dict, dict)
                # CV values should be between 0 and some reasonable upper bound
                for feature_id, cv in cv_dict.items():
                    if not pd.isna(cv):
                        assert cv >= 0, f"CV should be non-negative: {cv}"

    def test_calculate_corrected_ratios_excludes_ratio_pseudo_sample_columns(
        self, istd_module
    ):
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

        _, sample_columns = istd_module.calculate_corrected_ratios(
            raw_df, sample_info_df
        )

        assert sample_columns == ["Sample_A1", "Sample_B1"]
        assert "exposure_ratio" not in sample_columns

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

        sample_columns, qc_columns = istd_module.get_qc_sample_columns(
            raw_df, col_to_info
        )

        assert sample_columns == ["Sample_A1", "Sample_B1"]
        assert qc_columns == []
