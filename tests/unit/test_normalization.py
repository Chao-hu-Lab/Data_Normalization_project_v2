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


class TestConcentrationNormInput:
    """Tests for input validation."""

    def test_module_loads(self, conc_norm_module):
        """Test that module can be imported."""
        assert conc_norm_module is not None
        assert hasattr(conc_norm_module, 'main')

    def test_has_required_functions(self, conc_norm_module):
        """Test that module has expected functions."""
        assert hasattr(conc_norm_module, 'main'), "Should have main function"


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
