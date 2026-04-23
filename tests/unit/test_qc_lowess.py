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
import numpy as np
import os
import shutil
from openpyxl import load_workbook
from openpyxl.styles import Font

from metabolomics.utils.constants import SHEET_NAMES


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

    def test_collect_red_marked_feature_ids_accepts_argb_red(self, qc_lowess_module, tmp_path):
        """Fallback red-font parsing should accept ARGB red strings from openpyxl."""
        raw_df = pd.DataFrame(
            {
                "Mz/RT": ["Sample_Type", "100.1/1.0", "200.2/2.0"],
                "QC_1": ["QC", 10.0, 20.0],
                "QC_2": ["QC", 11.0, 21.0],
                "QC_3": ["QC", 9.0, 19.0],
            }
        )
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC_1", "QC_2", "QC_3"],
                "Sample_Type": ["QC", "QC", "QC"],
            }
        )
        workbook_path = tmp_path / "argb_red_fallback.xlsx"
        with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
            raw_df.to_excel(writer, sheet_name="RawIntensity", index=False)
            sample_info_df.to_excel(writer, sheet_name="SampleInfo", index=False)

        workbook = load_workbook(workbook_path)
        try:
            sheet = workbook["RawIntensity"]
            sheet["A3"].font = Font(color="00FF0000")
            workbook.save(workbook_path)
        finally:
            workbook.close()

        detected = qc_lowess_module.collect_red_marked_feature_ids(
            str(workbook_path),
            SHEET_NAMES["raw_intensity"],
        )

        assert detected == {"100.1/1.0"}


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
            SHEET_NAMES["qc_lowess"],
            SHEET_NAMES["qc_lowess_advanced"],
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

        output_df = pd.read_excel(step2_output, sheet_name=SHEET_NAMES["qc_lowess"])
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
            required_sheets=[SHEET_NAMES["qc_lowess"]],
            min_rows=1
        )

        assert validation['exists'], f"Output file should exist"
        assert validation['readable'], f"Output file should be readable"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_qc_lowess_result_preserves_presence_absence_marker(
        self,
        qc_lowess_module,
        sample_input_file,
        output_dir,
    ):
        input_path = os.path.join(output_dir, "qc_lowess_marker_input.xlsx")
        if os.path.exists(input_path):
            os.remove(input_path)
        shutil.copy2(sample_input_file, input_path)

        workbook = load_workbook(input_path)
        try:
            worksheet = workbook["RawIntensity"]
            marker_col = worksheet.max_column + 1
            worksheet.cell(row=1, column=marker_col, value="is_Presence_Absence_Marker")
            worksheet.cell(row=2, column=marker_col, value="is_Presence_Absence_Marker")
            worksheet.cell(row=3, column=marker_col, value=True)
            worksheet.cell(row=4, column=marker_col, value=False)
            worksheet.cell(row=5, column=marker_col, value=True)
            workbook.save(input_path)
        finally:
            workbook.close()

        step2_result = qc_lowess_module.main(input_file=input_path)
        step2_output = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        result_wb = load_workbook(step2_output, read_only=True, data_only=True)
        try:
            ws = result_wb[SHEET_NAMES["qc_lowess"]]
            headers = [cell.value for cell in ws[1]]
            marker_idx = headers.index("is_Presence_Absence_Marker") + 1
            assert ws.cell(row=2, column=marker_idx).value == "is_Presence_Absence_Marker"
            assert ws.cell(row=3, column=marker_idx).value is True
            assert ws.cell(row=4, column=marker_idx).value is False
            assert ws.cell(row=5, column=marker_idx).value is True
        finally:
            result_wb.close()

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
        output_df = pd.read_excel(step2_output, sheet_name=SHEET_NAMES["qc_lowess"])

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
            SHEET_NAMES["qc_lowess"],
            SHEET_NAMES["qc_lowess_advanced"],
            'SampleInfo',
        }

    @pytest.mark.slow
    @pytest.mark.integration
    def test_loess_summary_sheet_keeps_feature_table_and_adds_summary_block(
        self,
        qc_lowess_module,
        sample_input_file,
    ):
        from openpyxl import load_workbook

        step2_result = qc_lowess_module.main(input_file=sample_input_file)
        step2_output = (
            step2_result.output_path
            if hasattr(step2_result, "output_path")
            else step2_result.get("output_path")
        )

        workbook = load_workbook(step2_output, read_only=False)
        try:
            worksheet = workbook[SHEET_NAMES["qc_lowess_advanced"]]
            assert worksheet["A1"].value == "Mz/RT"
            assert worksheet["J1"].value == "LOESS Summary"
            summary_labels = [worksheet[f"J{row_idx}"].value for row_idx in range(1, worksheet.max_row + 1)]
            assert "Overview" in summary_labels
            assert "Features processed" in summary_labels
            assert "Overall readout" in summary_labels

            features_row = next(
                row_idx
                for row_idx, label in enumerate(summary_labels, start=1)
                if label == "Features processed"
            )
            assert worksheet.cell(row=features_row, column=11).value is not None
        finally:
            workbook.close()


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
                    "QC8",
                    "QC9",
                    "QC10",
                    "QC11",
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
                    "QC",
                    "QC",
                    "QC",
                    "QC",
                    "Exposure",
                    "Control",
                    "Exposure",
                ],
                "Batch": [
                    "A",
                    "A",
                    "A;B",
                    "A",
                    "B",
                    "B",
                    "B;C",
                    "C",
                    "C",
                    "C",
                    "A;B;C",
                    "A",
                    "B",
                    "C",
                ],
                "Injection_Order": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 3.5, 6.5, 9.5],
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
                    "QC8": 80.0,
                    "QC9": 90.0,
                    "QC10": 100.0,
                    "QC11": 110.0,
                    "SampleA": 35.0,
                    "SampleB": 65.0,
                    "SampleC": 95.0,
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
            "QC8",
            "QC9",
            "QC10",
            "QC11",
            "SampleA",
            "SampleB",
            "SampleC",
        ]

        lowess_df, _, _, _, decision_stats, _ = qc_lowess_module.perform_lowess_normalization(
            istd_df, sample_info_df
        )

        assert decision_stats["event_counts"]["insufficient_qc"] == 0
        assert lowess_df.loc[0, "SampleA"] != pytest.approx(35.0)
        assert lowess_df.loc[0, "SampleB"] != pytest.approx(65.0)
        assert lowess_df.loc[0, "SampleC"] != pytest.approx(95.0)

    def test_trend_stats_schema_keeps_kendall_tau_only(self, qc_lowess_module):
        sample_info_df = pd.DataFrame(
            {
                "Sample_Name": ["QC1", "QC2", "QC3", "QC4", "QC5", "SampleA"],
                "Sample_Type": ["QC", "QC", "QC", "QC", "QC", "Exposure"],
                "Batch": ["A", "A", "A", "A", "A", "A"],
                "Injection_Order": [1, 2, 3, 4, 5, 6],
            }
        )
        istd_df = pd.DataFrame(
            [
                {
                    "FeatureID": "100.1/5.0",
                    "QC1": 10.0,
                    "QC2": 12.0,
                    "QC3": 14.0,
                    "QC4": 16.0,
                    "QC5": 18.0,
                    "SampleA": 20.0,
                }
            ]
        )
        istd_df.attrs["sample_columns"] = ["QC1", "QC2", "QC3", "QC4", "QC5", "SampleA"]

        _, _, _, trend_stats_df, _, _ = qc_lowess_module.perform_lowess_normalization(
            istd_df, sample_info_df
        )

        assert "Kendall_Tau" in trend_stats_df.columns
        assert "MK_Trend_pvalue" not in trend_stats_df.columns

    def test_get_valid_values_consistency(self, qc_lowess_module, istd_module):
        """Test that get_valid_values is consistent with ISTD module."""
        import pandas as pd

        row = pd.Series({'A': 100, 'B': 200, 'C': 0, 'D': -5})
        columns = ['A', 'B', 'C', 'D']

        values_qc = qc_lowess_module.get_valid_values(row, columns)
        values_istd = istd_module.get_valid_values(row, columns)

        # Should produce identical results
        assert values_qc == values_istd, "get_valid_values should be consistent across modules"


class TestFracFloorAndLoocv:
    """Tests for the LOWESS anti-overfitting guards."""

    def test_apply_lowess_correction_populates_kendall_tau(self, qc_lowess_module):
        qc_orders = np.array([1, 2, 3, 4, 5, 6], dtype=float)
        qc_intensities = np.array([100.0, 104.0, 109.0, 115.0, 122.0, 130.0], dtype=float)
        all_orders = qc_orders.copy()
        all_intensities = qc_intensities.copy()

        _, info = qc_lowess_module.apply_lowess_correction(
            qc_orders.tolist(),
            qc_intensities.tolist(),
            all_orders.tolist(),
            all_intensities.tolist(),
        )

        trend_validation = info["trend_validation"]
        assert np.isfinite(trend_validation["trend_tau"])
        assert -1.0 <= trend_validation["trend_tau"] <= 1.0

    def test_frac_floor_values(self, qc_lowess_module):
        floor = qc_lowess_module._frac_floor
        assert floor(4) == 1.0
        assert floor(5) == 1.0
        assert floor(6) == 0.85
        assert floor(7) == 0.80
        assert floor(10) == 0.70
        assert floor(11) == 0.0
        assert floor(20) == 0.0

    def test_loocv_rmse_returns_positive_float(self, qc_lowess_module):
        rng = np.random.default_rng(42)
        x = np.arange(7, dtype=float)
        y = 1000.0 + 50.0 * x + rng.normal(0, 20, 7)

        rmse = qc_lowess_module._loocv_rmse(x, y, frac=0.8)

        assert isinstance(rmse, float)
        assert rmse > 0

    def test_five_qc_points_gets_frac_floor_and_nonzero_cv(self, qc_lowess_module):
        """With only 5 valid QC points, frac floor forces 1.0 to prevent overfitting."""
        rng = np.random.default_rng(99)
        n_qc = 5
        n_total = 30
        qc_orders = np.linspace(1, n_total, n_qc)
        qc_intensities = 10000.0 + np.linspace(0, 3000, n_qc) + rng.normal(0, 200, n_qc)
        all_orders = np.arange(1, n_total + 1, dtype=float)
        all_intensities = 10000.0 + rng.normal(0, 500, n_total)

        corrected, info = qc_lowess_module.apply_lowess_correction(
            qc_orders.tolist(),
            qc_intensities.tolist(),
            all_orders.tolist(),
            all_intensities.tolist(),
        )

        assert info["frac_used"] == 1.0
        assert "floor_applied" in info["frac_strategy"] or "loocv" in info["frac_strategy"]

        qc_indices = [i for i, order in enumerate(all_orders) if order in qc_orders]
        corrected_qc = np.array([corrected[i] for i in qc_indices], dtype=float)
        corrected_qc = corrected_qc[np.isfinite(corrected_qc) & (corrected_qc > 0)]
        if corrected_qc.size >= 2:
            cv = float(np.std(corrected_qc, ddof=1) / np.mean(corrected_qc) * 100.0)
            assert cv > 0.5, f"Corrected QC CV% should be > 0.5 but got {cv:.4f}"

    def test_large_qc_count_skips_loocv(self, qc_lowess_module):
        """With n > 10 QC points, LOOCV should not be triggered."""
        rng = np.random.default_rng(123)
        n_qc = 20
        n_total = 60
        qc_orders = np.linspace(1, n_total, n_qc)
        qc_intensities = 50000.0 + rng.normal(0, 2000, n_qc)
        all_orders = np.arange(1, n_total + 1, dtype=float)
        all_intensities = 50000.0 + rng.normal(0, 3000, n_total)

        _, info = qc_lowess_module.apply_lowess_correction(
            qc_orders.tolist(),
            qc_intensities.tolist(),
            all_orders.tolist(),
            all_intensities.tolist(),
        )

        assert np.isnan(info.get("loocv_rmse", np.nan))
        assert "loocv" not in info["frac_strategy"]
        assert "floor" not in info["frac_strategy"]

    def test_insufficient_qc_threshold_raised_to_five(self, qc_lowess_module):
        """4 valid QC points should now be rejected as insufficient."""
        qc_orders = [1.0, 5.0, 10.0, 15.0]
        qc_intensities = [1000.0, 1100.0, 1200.0, 1300.0]
        all_orders = list(range(1, 21))
        all_intensities = [1000.0] * 20

        _, info = qc_lowess_module.apply_lowess_correction(
            qc_orders,
            qc_intensities,
            all_orders,
            all_intensities,
        )

        assert info["status"] == "insufficient_qc"
