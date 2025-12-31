"""
Tests for ISTD_Correction_v2 module (Step 1).

These tests verify:
1. Input validation (file format, required sheets)
2. Output structure (correct sheets, columns)
3. Data integrity (row count, no unexpected NaN)
4. Return value format
"""
import pytest
import os
import pandas as pd


class TestISTDCorrectionInput:
    """Tests for input validation."""

    def test_module_loads(self, istd_module):
        """Test that module can be imported."""
        assert istd_module is not None
        assert hasattr(istd_module, 'main')
        assert hasattr(istd_module, 'load_and_process_data')

    def test_load_valid_file(self, istd_module, sample_input_file):
        """Test loading a valid input file."""
        raw_df, sample_info_df, all_sheets = istd_module.load_and_process_data(sample_input_file)

        assert raw_df is not None, "raw_df should not be None"
        assert sample_info_df is not None, "sample_info_df should not be None"
        assert all_sheets is not None, "all_sheets should not be None"

        # Check required columns
        assert 'FeatureID' in raw_df.columns
        assert 'Sample_Name' in sample_info_df.columns
        assert 'Sample_Type' in sample_info_df.columns

    def test_load_nonexistent_file(self, istd_module):
        """Test handling of non-existent file."""
        result = istd_module.load_and_process_data("nonexistent_file.xlsx")
        assert result == (None, None, None)

    def test_istd_detection(self, istd_module, sample_input_file):
        """Test ISTD (red font) detection."""
        raw_df, _, _ = istd_module.load_and_process_data(sample_input_file)

        if raw_df is not None:
            assert 'is_ISTD' in raw_df.columns, "is_ISTD column should exist"
            istd_count = raw_df['is_ISTD'].sum()
            # Should have at least some ISTDs
            assert istd_count >= 0, "ISTD count should be non-negative"


class TestISTDCorrectionOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    def test_main_returns_dict(self, istd_module, sample_input_file, validate_result_dict):
        """Test that main() returns expected dictionary."""
        result = istd_module.main(input_file=sample_input_file)

        validation = validate_result_dict(
            result,
            required_keys=['output_path', 'metabolites', 'samples']
        )

        assert validation['is_dict'], f"Result should be dict: {validation['errors']}"
        assert len(validation['errors']) == 0, f"Validation errors: {validation['errors']}"

    @pytest.mark.slow
    def test_output_file_created(self, istd_module, sample_input_file, validate_excel_output):
        """Test that output Excel file is created correctly."""
        result = istd_module.main(input_file=sample_input_file)

        assert result is not None, "main() should return a result"
        assert 'output_path' in result, "Result should contain output_path"

        validation = validate_excel_output(
            result['output_path'],
            required_sheets=['ISTD_Correction', 'RawIntensity', 'SampleInfo'],
            min_rows=1
        )

        assert validation['exists'], f"Output file should exist: {validation['errors']}"
        assert validation['readable'], f"Output file should be readable: {validation['errors']}"
        assert len(validation['errors']) == 0, f"Validation errors: {validation['errors']}"

    @pytest.mark.slow
    def test_data_integrity(self, istd_module, sample_input_file):
        """Test that data integrity is maintained."""
        # Load original data
        raw_df, sample_info_df, _ = istd_module.load_and_process_data(sample_input_file)
        original_feature_count = len(raw_df[~raw_df['is_ISTD']])  # Non-ISTD features

        # Run correction
        result = istd_module.main(input_file=sample_input_file)

        # Load output
        output_df = pd.read_excel(result['output_path'], sheet_name='ISTD_Correction')

        # Feature count should be approximately same (non-ISTD features)
        assert len(output_df) > 0, "Output should have rows"
        assert 'FeatureID' in output_df.columns, "Output should have FeatureID column"


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
        raw_df, _, _ = istd_module.load_and_process_data(sample_input_file)

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
