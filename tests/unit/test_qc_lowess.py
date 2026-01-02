"""
Tests for QC_LOWESS_v2 module (Step 2).

These tests verify:
1. Input validation (requires Step 1 output format)
2. Output structure (correct sheets, columns)
3. LOWESS correction logic
4. Return value format
"""
import pytest
import os
import pandas as pd


class TestQCLOWESSInput:
    """Tests for input validation."""

    def test_module_loads(self, qc_lowess_module):
        """Test that module can be imported."""
        assert qc_lowess_module is not None
        assert hasattr(qc_lowess_module, 'main')

    def test_has_required_functions(self, qc_lowess_module):
        """Test that module has expected functions."""
        expected_functions = ['main', 'load_and_process_data', 'get_valid_values']
        for func_name in expected_functions:
            assert hasattr(qc_lowess_module, func_name), f"Missing function: {func_name}"


class TestQCLOWESSOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_with_step1_output(self, istd_module, qc_lowess_module,
                                     sample_input_file, validate_result_dict):
        """Test QC-LOWESS with Step 1 output."""
        # First run Step 1
        step1_result = istd_module.main(input_file=sample_input_file)
        assert step1_result is not None, "Step 1 should succeed"
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        assert step1_output

        # Then run Step 2
        step2_result = qc_lowess_module.main(input_file=step1_output)

        validation = validate_result_dict(
            step2_result,
            required_keys=['output_path', 'metabolites', 'samples']
        )

        assert validation['is_processing_result'], f"Result should be ProcessingResult: {validation['errors']}"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_file_structure(self, istd_module, qc_lowess_module,
                                    sample_input_file, validate_excel_output):
        """Test output Excel file structure."""
        # Run Step 1
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')

        # Run Step 2
        step2_result = qc_lowess_module.main(input_file=step1_output)

        assert step2_result is not None
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        assert step2_output

        validation = validate_excel_output(
            step2_output,
            required_sheets=['QC LOWESS result'],
            min_rows=1
        )

        assert validation['exists'], f"Output file should exist"
        assert validation['readable'], f"Output file should be readable"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_cv_improvement_tracking(self, istd_module, qc_lowess_module, sample_input_file):
        """Test that CV improvement is tracked in output."""
        # Run Step 1
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')

        # Run Step 2
        step2_result = qc_lowess_module.main(input_file=step1_output)

        # Check output contains CV statistics
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        output_df = pd.read_excel(step2_output, sheet_name='QC LOWESS result')

        # Should have CV-related columns
        cv_columns = [col for col in output_df.columns if 'CV' in col.upper()]
        assert len(cv_columns) > 0, "Output should have CV-related columns"


class TestQCLOWESSHelpers:
    """Tests for helper functions."""

    def test_get_valid_values_consistency(self, qc_lowess_module, istd_module):
        """Test that get_valid_values is consistent with ISTD module."""
        import pandas as pd

        row = pd.Series({'A': 100, 'B': 200, 'C': 0, 'D': -5})
        columns = ['A', 'B', 'C', 'D']

        values_qc = qc_lowess_module.get_valid_values(row, columns)
        values_istd = istd_module.get_valid_values(row, columns)

        # Should produce identical results
        assert values_qc == values_istd, "get_valid_values should be consistent across modules"
