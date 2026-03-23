"""
Tests for QC_LOWESS_v2 module (Step 2).

These tests verify:
1. Input validation (requires Step 1 output format)
2. Output structure (correct sheets, columns)
3. LOWESS correction logic
4. Return value format
"""
import pytest
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

    def test_load_and_process_data_reports_actual_source_sheet(
        self,
        qc_lowess_module,
        sample_input_file,
        capsys,
    ):
        """Fallback logging should mention RawIntensity when no ISTD sheet exists."""
        qc_lowess_module.load_and_process_data(sample_input_file)

        captured = capsys.readouterr().out
        assert "成功讀取 'RawIntensity' 工作表" in captured
        assert "成功讀取 'ISTD_Correction' 工作表" not in captured


class TestQCLOWESSOutput:
    """Tests for output validation."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_main_falls_back_to_raw_intensity_when_istd_sheet_is_missing(
        self,
        qc_lowess_module,
        sample_input_file,
        workbook_sheet_names,
    ):
        """Step 2 should accept a workbook that only has RawIntensity and SampleInfo."""
        step2_result = qc_lowess_module.main(input_file=sample_input_file)

        validation_target = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        assert set(workbook_sheet_names(validation_target)) == {
            "RawIntensity",
            "QC LOWESS result",
            "QC_LOWESS_Advanced Statistics",
            "SampleInfo",
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_fallback_excludes_red_marked_istds_from_qc_lowess_result(
        self,
        istd_module,
        qc_lowess_module,
        sample_input_file,
    ):
        """When Step 1 is skipped, red-marked ISTDs should not re-enter downstream result sheets."""
        from metabolomics.utils.data_helpers import extract_sample_type_row

        raw_df, _, _, _ = istd_module.load_and_process_data(sample_input_file)
        raw_df, _ = extract_sample_type_row(raw_df, "FeatureID")
        expected_rows = len(raw_df[~raw_df["is_ISTD"]])

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        output_df = pd.read_excel(step2_output, sheet_name="QC LOWESS result")
        output_df, _ = extract_sample_type_row(output_df, output_df.columns[0])

        assert len(output_df) == expected_rows

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
        assert {'Original_QC_CV%', 'Corrected_QC_CV%'}.issubset(output_df.columns)

        numeric = output_df[['Original_QC_CV%', 'Corrected_QC_CV%']].apply(
            pd.to_numeric, errors='coerce'
        )
        cv_diff = (numeric['Original_QC_CV%'] - numeric['Corrected_QC_CV%']).dropna()
        assert not cv_diff.empty, "CV comparison should contain numeric values"
        assert (cv_diff.abs() > 1e-9).any(), "QC correction should change at least one feature CV"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_plots_are_generated(self, istd_module, qc_lowess_module, sample_input_file):
        """Test that QC-LOWESS produces plot artifacts."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')

        step2_result = qc_lowess_module.main(input_file=step1_output)

        plots_dir = step2_result.plots_dir if hasattr(step2_result, "plots_dir") else step2_result.get('plots_dir')
        assert plots_dir, "QC-LOWESS should report a plots directory"

        from pathlib import Path

        plot_files = sorted(Path(plots_dir).glob("*.png"))
        assert plot_files, "QC-LOWESS should generate PNG plots"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_output_workbook_only_keeps_required_sheets(
        self,
        istd_module,
        qc_lowess_module,
        sample_input_file,
        copy_workbook_with_extra_sheet,
        workbook_sheet_names,
    ):
        """Step 2 output should only keep the previous step sheet and required metadata."""
        step1_result = istd_module.main(input_file=sample_input_file)
        step1_output = step1_result.output_path if hasattr(step1_result, "output_path") else step1_result.get('output_path')
        step1_with_extra_sheet = copy_workbook_with_extra_sheet(step1_output)

        step2_result = qc_lowess_module.main(input_file=step1_with_extra_sheet)
        step2_output = step2_result.output_path if hasattr(step2_result, "output_path") else step2_result.get('output_path')

        expected_source_sheet = 'RawIntensity'
        if 'ISTD_Correction' in workbook_sheet_names(step1_with_extra_sheet):
            expected_source_sheet = 'ISTD_Correction'

        assert set(workbook_sheet_names(step2_output)) == {
            expected_source_sheet,
            'QC LOWESS result',
            'QC_LOWESS_Advanced Statistics',
            'SampleInfo',
        }


    @pytest.mark.slow
    def test_main_writes_to_session_dir(self, qc_lowess_module, sample_input_file, tmp_path):
        """When session_dir is provided, output goes into that directory."""
        from pathlib import Path
        from metabolomics.utils.file_io import create_session_dir

        session = create_session_dir(output_root=tmp_path)
        result = qc_lowess_module.main(input_file=sample_input_file, session_dir=session)
        assert Path(result.output_path).is_relative_to(session)
        assert "Step2_" in Path(result.output_path).name


class TestQCLOWESSHelpers:
    """Tests for helper functions."""

    def test_perform_pca_analysis_passes_multi_batch_memberships_to_plotter(
        self,
        qc_lowess_module,
        tmp_path,
        monkeypatch,
    ):
        captured = {}

        def fake_plotter(*args, **kwargs):
            captured["batch_memberships"] = kwargs.get("batch_memberships")
            output_path = kwargs.get("output_path")
            if output_path:
                from pathlib import Path

                Path(output_path).write_bytes(b"png")
            return None, (None, None)

        monkeypatch.setattr(qc_lowess_module, "plot_pca_comparison_qc_style", fake_plotter)

        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": [
                    "QC1",
                    "QC2",
                    "QC3",
                    "QC4",
                    "QC5",
                    "QC6",
                    "QC7",
                    "SampleA",
                    "SampleB",
                    "SampleC",
                ],
                "Sample_Type": [
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "Exposure",
                    "Normal",
                    "Benign",
                ],
                "Batch": ["A", "A", "A;B", "B", "B;C", "C", "C", "A", "B", "C"],
                "Injection_Order": [1, 2, 3, 4, 5, 6, 7, 2.5, 4.5, 6.5],
            }
        )
        feature_rows = []
        for idx in range(4):
            feature_rows.append(
                {
                    "FeatureID": f"100.{idx}/5.{idx}",
                    "QC1": 10.0 + idx,
                    "QC2": 20.0 + idx,
                    "QC3": 30.0 + idx,
                    "QC4": 40.0 + idx,
                    "QC5": 50.0 + idx,
                    "QC6": 60.0 + idx,
                    "QC7": 70.0 + idx,
                    "SampleA": 25.0 + idx,
                    "SampleB": 45.0 + idx,
                    "SampleC": 65.0 + idx,
                }
            )

        istd_df = pd.DataFrame(feature_rows)
        lowess_df = pd.DataFrame(feature_rows)
        sample_columns = [
            "QC1",
            "QC2",
            "QC3",
            "QC4",
            "QC5",
            "QC6",
            "QC7",
            "SampleA",
            "SampleB",
            "SampleC",
        ]

        qc_lowess_module.perform_pca_analysis(
            istd_df,
            lowess_df,
            sample_columns,
            sample_info_df,
            plots_dir=str(tmp_path),
            grouping="batch",
        )

        assert captured["batch_memberships"][2] == ("A", "B")
        assert all(";" not in label for membership in captured["batch_memberships"] for label in membership)

    def test_perform_pca_analysis_uses_rawintensity_title_when_step1_is_skipped(
        self,
        qc_lowess_module,
        tmp_path,
        monkeypatch,
    ):
        captured = {}

        def fake_plotter(*args, **kwargs):
            captured["suptitle"] = kwargs.get("suptitle")
            captured["left_title"] = kwargs.get("left_title")
            output_path = kwargs.get("output_path")
            if output_path:
                from pathlib import Path

                Path(output_path).write_bytes(b"png")
            return None, (None, None)

        monkeypatch.setattr(qc_lowess_module, "plot_pca_comparison_qc_style", fake_plotter)

        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC1", "QC2", "QC3", "QC4", "SampleA", "SampleB"],
                "Sample_Type": ["QC", "QC", "QC", "QC", "Exposure", "Control"],
                "Batch": ["A", "A", "B", "B", "A", "B"],
                "Injection_Order": [1, 2, 3, 4, 5, 6],
            }
        )
        rows = [
            {"FeatureID": "100.1/5.0", "QC1": 10, "QC2": 11, "QC3": 12, "QC4": 13, "SampleA": 20, "SampleB": 21},
            {"FeatureID": "100.2/5.1", "QC1": 14, "QC2": 15, "QC3": 16, "QC4": 17, "SampleA": 22, "SampleB": 23},
            {"FeatureID": "100.3/5.2", "QC1": 18, "QC2": 19, "QC3": 20, "QC4": 21, "SampleA": 24, "SampleB": 25},
        ]
        istd_df = pd.DataFrame(rows)
        lowess_df = pd.DataFrame(rows)
        istd_df.attrs["source_sheet_name"] = "RawIntensity"

        qc_lowess_module.perform_pca_analysis(
            istd_df,
            lowess_df,
            ["QC1", "QC2", "QC3", "QC4", "SampleA", "SampleB"],
            sample_info_df,
            plots_dir=str(tmp_path),
            grouping="sample_type",
        )

        assert "RawIntensity vs QC-LOWESS" in captured["suptitle"]
        assert captured["left_title"] == "RawIntensity"

    def test_perform_pca_analysis_skips_batch_plot_when_only_one_batch(
        self,
        qc_lowess_module,
        tmp_path,
        monkeypatch,
    ):
        captured = {"called": False}

        def fake_plotter(*args, **kwargs):
            captured["called"] = True
            return None, (None, None)

        monkeypatch.setattr(qc_lowess_module, "plot_pca_comparison_qc_style", fake_plotter)

        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC1", "QC2", "QC3", "QC4", "SampleA", "SampleB"],
                "Sample_Type": ["QC", "QC", "QC", "QC", "Exposure", "Control"],
                "Batch": ["A", "A", "A", "A", "A", "A"],
                "Injection_Order": [1, 2, 3, 4, 5, 6],
            }
        )
        rows = [
            {"FeatureID": "100.1/5.0", "QC1": 10, "QC2": 11, "QC3": 12, "QC4": 13, "SampleA": 20, "SampleB": 21},
            {"FeatureID": "100.2/5.1", "QC1": 14, "QC2": 15, "QC3": 16, "QC4": 17, "SampleA": 22, "SampleB": 23},
            {"FeatureID": "100.3/5.2", "QC1": 18, "QC2": 19, "QC3": 20, "QC4": 21, "SampleA": 24, "SampleB": 25},
        ]
        istd_df = pd.DataFrame(rows)
        lowess_df = pd.DataFrame(rows)

        result = qc_lowess_module.perform_pca_analysis(
            istd_df,
            lowess_df,
            ["QC1", "QC2", "QC3", "QC4", "SampleA", "SampleB"],
            sample_info_df,
            plots_dir=str(tmp_path),
            grouping="batch",
        )

        assert result is None
        assert captured["called"] is False

    def test_perform_lowess_supports_multi_batch_qc_membership(self, qc_lowess_module):
        """QC samples tagged as A;B should contribute to both batches instead of forming a new batch."""
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": [
                    "QC1",
                    "QC2",
                    "QC3",
                    "QC4",
                    "QC5",
                    "QC6",
                    "QC7",
                    "SampleA",
                    "SampleB",
                    "SampleC",
                ],
                "Sample_Type": [
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "Exposure",
                    "Control",
                    "Exposure",
                ],
                "Batch": ["A", "A", "A;B", "B", "B;C", "C", "C", "A", "B", "C"],
                "Injection_Order": [1, 2, 3, 4, 5, 6, 7, 2.5, 4.5, 6.5],
            }
        )
        istd_df = pd.DataFrame(
            [
                {
                    "FeatureID": "100.1/5.0",
                    "QC1": 10.0,
                    "QC2": 20.0,
                    "QC3": 30.0,
                    "QC4": 40.0,
                    "QC5": 50.0,
                    "QC6": 60.0,
                    "QC7": 70.0,
                    "SampleA": 25.0,
                    "SampleB": 45.0,
                    "SampleC": 65.0,
                }
            ]
        )
        istd_df.attrs["sample_columns"] = [
            "QC1",
            "QC2",
            "QC3",
            "QC4",
            "QC5",
            "QC6",
            "QC7",
            "SampleA",
            "SampleB",
            "SampleC",
        ]

        lowess_df, _, _, _, decision_stats, _ = qc_lowess_module.perform_lowess_normalization(
            istd_df, sample_info_df
        )

        assert decision_stats["event_counts"]["insufficient_qc"] == 0
        assert lowess_df.loc[0, "SampleA"] != pytest.approx(25.0)
        assert lowess_df.loc[0, "SampleB"] != pytest.approx(45.0)
        assert lowess_df.loc[0, "SampleC"] != pytest.approx(65.0)

    def test_get_valid_values_consistency(self, qc_lowess_module, istd_module):
        """Test that get_valid_values is consistent with ISTD module."""
        import pandas as pd

        row = pd.Series({'A': 100, 'B': 200, 'C': 0, 'D': -5})
        columns = ['A', 'B', 'C', 'D']

        values_qc = qc_lowess_module.get_valid_values(row, columns)
        values_istd = istd_module.get_valid_values(row, columns)

        # Should produce identical results
        assert values_qc == values_istd, "get_valid_values should be consistent across modules"
