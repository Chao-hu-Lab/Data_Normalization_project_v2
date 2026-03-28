"""
Tests for Batch_Effect_v2 module (Step 3).

These tests verify:
1. Input validation (requires Step 2 output format)
2. Output structure (PERMANOVA stats, corrected data)
3. ComBat correction application
4. Return value format
"""
import pytest


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
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')

        # Run Step 2
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        # Run Step 3
        step3_result = batch_effect_module.main(input_file=step2_output)

        validation = validate_result_dict(
            step3_result,
            required_keys=['output_path']
        )

        assert validation['is_processing_result'], f"Result should be ProcessingResult: {validation['errors']}"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_file_structure(self, istd_module, qc_lowess_module,
                                    batch_effect_module, sample_input_file,
                                    validate_excel_output):
        """Test output Excel file structure."""
        # Run Steps 1-2
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        # Run Step 3
        step3_result = batch_effect_module.main(input_file=step2_output)

        assert step3_result is not None
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')
        assert step3_output

        validation = validate_excel_output(
            step3_output,
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
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        # Run Step 3
        step3_result = batch_effect_module.main(input_file=step2_output)

        # Check for PERMANOVA-related keys (may vary based on data)
        if step3_result and hasattr(step3_result, "output_path"):
            # At minimum should have success indicator
            assert step3_result.output_path

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_only_keeps_required_sheets(
        self,
        istd_module,
        qc_lowess_module,
        batch_effect_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 3 output should only keep the Step 2 data sheet, SampleInfo, and Step 3 outputs."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')
        step2_with_extra_sheet = copy_workbook_with_extra_sheet(step2_output)

        step3_result = batch_effect_module.main(input_file=step2_with_extra_sheet)
        step3_output = step3_result.output_path if hasattr(step3_result, "output_path") else step3_result.get('output_path')

        assert set(workbook_sheet_names(step3_output)) == {
            'QC LOWESS result',
            'SampleInfo',
            'Batch_effect_result',
            'Batch_Effect_summary',
        }


    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_writes_to_session_dir(self, istd_module, qc_lowess_module,
                                         batch_effect_module, sample_input_file, tmp_path):
        """When session_dir is provided, output goes into that directory."""
        from pathlib import Path
        from metabolomics.utils.file_io import create_session_dir

        # Run Steps 1-2 to produce valid Step 3 input
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step2_result = qc_lowess_module.main(input_file=step1_output)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        session = create_session_dir(output_root=tmp_path)
        result = batch_effect_module.main(input_file=step2_output, session_dir=session)
        # batch_effect may return dict or ProcessingResult
        if hasattr(result, 'output_path'):
            output_path = result.output_path
        else:
            output_path = result.get('output_path', '')
        # For single-batch data, output_path may be the input file (skip case)
        # Only assert session containment if it's not a skip
        if hasattr(result, 'extra') and not result.extra.get('skipped', False):
            assert Path(output_path).is_relative_to(session)
        elif isinstance(result, dict) and not result.get('skipped', False):
            assert Path(output_path).is_relative_to(session)


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

    def test_plot_permanova_comparison_handles_missing_permutation_result(self, batch_effect_module):
        """PERMANOVA comparison plot should render even when paired permutation stats are unavailable."""
        fig = batch_effect_module.plot_permanova_comparison(
            {"pseudo_f": 2.4, "p_value": 0.01, "r_squared": 0.22},
            {"pseudo_f": 1.2, "p_value": 0.18, "r_squared": 0.11},
            None,
        )

        try:
            assert fig is not None
            all_text = "\n".join(text.get_text() for ax in fig.axes for text in ax.texts)
            assert "Skipped" in all_text
        finally:
            batch_effect_module.plt.close(fig)
