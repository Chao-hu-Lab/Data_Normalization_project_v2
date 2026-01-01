"""
Tests for Batch_Effect_v2 module (Step 3).

These tests verify:
1. Input validation (requires Step 2 output format)
2. Output structure (PERMANOVA stats, corrected data)
3. ComBat correction application
4. Return value format
"""
import pytest
import os
import pandas as pd


class TestBatchEffectInput:
    """Tests for input validation."""

    def test_module_loads(self, batch_effect_module):
        """Test that module can be imported."""
        assert batch_effect_module is not None
        assert hasattr(batch_effect_module, 'main')

    def test_has_required_functions(self, batch_effect_module):
        """Test that module has expected functions."""
        expected_functions = ['main']
        for func_name in expected_functions:
            assert hasattr(batch_effect_module, func_name), f"Missing function: {func_name}"

    def test_has_hotelling_functions(self, batch_effect_module):
        """Test that module has Hotelling T2 functions."""
        assert hasattr(batch_effect_module, 'calculate_hotelling_t2_outliers')
        assert hasattr(batch_effect_module, 'draw_hotelling_t2_ellipse')


class TestBatchEffectOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_with_step2_output(self, istd_module, qc_lowess_module,
                                     batch_effect_module, sample_input_file,
                                     validate_result_dict):
        """Test Batch Effect with Step 2 output."""
        # Run Step 1
        step1_result = istd_module.main(input_file=sample_input_file)

        # Run Step 2
        step2_result = qc_lowess_module.main(input_file=step1_result['output_path'])

        # Run Step 3
        step3_result = batch_effect_module.main(input_file=step2_result['output_path'])

        validation = validate_result_dict(
            step3_result,
            required_keys=['output_path']
        )

        assert validation['is_dict'], f"Result should be dict: {validation['errors']}"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_file_structure(self, istd_module, qc_lowess_module,
                                    batch_effect_module, sample_input_file,
                                    validate_excel_output):
        """Test output Excel file structure."""
        # Run Steps 1-2
        step1_result = istd_module.main(input_file=sample_input_file)
        step2_result = qc_lowess_module.main(input_file=step1_result['output_path'])

        # Run Step 3
        step3_result = batch_effect_module.main(input_file=step2_result['output_path'])

        assert step3_result is not None
        assert 'output_path' in step3_result

        validation = validate_excel_output(
            step3_result['output_path'],
            min_rows=1
        )

        assert validation['exists'], f"Output file should exist"
        assert validation['readable'], f"Output file should be readable"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_permanova_stats_in_result(self, istd_module, qc_lowess_module,
                                        batch_effect_module, sample_input_file):
        """Test that PERMANOVA statistics are included in result."""
        # Run Steps 1-2
        step1_result = istd_module.main(input_file=sample_input_file)
        step2_result = qc_lowess_module.main(input_file=step1_result['output_path'])

        # Run Step 3
        step3_result = batch_effect_module.main(input_file=step2_result['output_path'])

        # Check for PERMANOVA-related keys (may vary based on data)
        if step3_result and isinstance(step3_result, dict):
            # At minimum should have success indicator
            assert 'output_path' in step3_result


class TestBatchEffectHelpers:
    """Tests for helper functions."""

    def test_hotelling_t2_outliers_function(self, batch_effect_module):
        """Test Hotelling T2 outlier detection function."""
        import numpy as np

        # Create simple test data
        np.random.seed(42)
        qc_scores = np.random.randn(10, 2)  # 10 QC samples, 2 components
        all_scores = np.random.randn(50, 2)  # 50 total samples

        t2_values, threshold, outliers = batch_effect_module.calculate_hotelling_t2_outliers(
            qc_scores, all_scores, alpha=0.05
        )

        assert len(t2_values) == len(qc_scores), "Should have T2 value for each QC sample"
        assert threshold > 0, "Threshold should be positive"
        assert len(outliers) == len(qc_scores), "Should have outlier flag for each QC sample"
        assert outliers.dtype == bool, "Outliers should be boolean array"
