from pathlib import Path

import numpy as np
import pytest

from metabolomics.utils.file_io import create_session_dir
from scripts.generate_batcheffect_data import (
    SCENARIO_LIBRARY,
    SEED,
    build_feature_metadata,
    build_sample_info,
    generate_scenario_workbook,
    simulate_intensity_matrix,
)


def _prepare_persistent_scenario_run(project_root: str, scenario_name: str) -> tuple[str, Path]:
    root = Path(project_root) / "build" / "scenario_regression" / scenario_name
    input_path = root / f"{scenario_name}.xlsx"
    session_root = root / "outputs"
    generate_scenario_workbook(SCENARIO_LIBRARY[scenario_name], input_path)
    session_dir = create_session_dir(
        output_root=session_root,
        timestamp=f"{scenario_name}_regression",
    )
    return str(input_path), session_dir


def _build_scenario_arrays(scenario_name: str):
    rng = np.random.default_rng(SEED)
    config = SCENARIO_LIBRARY[scenario_name]
    sample_info_df = build_sample_info(rng, config)
    feature_df = build_feature_metadata(rng, config)
    intensity_matrix, _ = simulate_intensity_matrix(sample_info_df, feature_df, rng, config)
    return config, sample_info_df, feature_df, intensity_matrix


def _assert_result_in_session(result, session_dir: Path, expected_step_prefix: str) -> None:
    assert result is not None
    assert Path(result.output_path).exists()
    assert Path(result.output_path).parent == session_dir
    assert Path(result.output_path).name.startswith(expected_step_prefix)


def _assert_step1_result_allows_skip(result, input_file: str, session_dir: Path) -> None:
    assert result is not None
    assert Path(result.output_path).exists()

    if getattr(result, "extra", {}).get("skipped"):
        assert Path(result.output_path) == Path(input_file)
        assert getattr(result, "extra", {}).get("skip_reason") == "insufficient_good_istd"
        return

    _assert_result_in_session(result, session_dir, "Step1_")


@pytest.mark.integration
def test_istd_degradation_generator_has_negative_istd_order_slopes():
    _, sample_info_df, feature_df, intensity_matrix = _build_scenario_arrays("istd_degradation")

    orders = sample_info_df["Injection_Order"].to_numpy(dtype=float)
    scaled_orders = (orders - orders.min()) / (orders.max() - orders.min())
    istd_indices = np.where(feature_df["is_istd"].to_numpy(dtype=bool))[0]

    slopes = []
    for feature_index in istd_indices:
        values = intensity_matrix[:, feature_index]
        finite_mask = np.isfinite(values)
        slopes.append(np.polyfit(scaled_orders[finite_mask], values[finite_mask], 1)[0])

    negative_fraction = float(np.mean(np.array(slopes) < 0))

    assert negative_fraction >= 0.8
    assert float(np.median(slopes)) < 0


@pytest.mark.integration
def test_structured_missingness_generator_concentrates_missingness_in_target_group():
    config, sample_info_df, feature_df, intensity_matrix = _build_scenario_arrays("structured_missingness")

    analyte_mask = ~feature_df["is_istd"].to_numpy(dtype=bool)
    target_sample_mask = (
        sample_info_df["Batch"].eq(config.structured_missing_batch)
        & sample_info_df["Sample_Type"].eq(config.structured_missing_sample_type)
    ).to_numpy(dtype=bool)

    target_missing_rate = float(np.isnan(intensity_matrix[target_sample_mask][:, analyte_mask]).mean())
    background_missing_rate = float(np.isnan(intensity_matrix[~target_sample_mask][:, analyte_mask]).mean())

    assert target_missing_rate > 0.15
    assert target_missing_rate > background_missing_rate * 3


@pytest.mark.integration
def test_matrix_effect_suppression_generator_depresses_target_sample_type():
    _, sample_info_df, feature_df, intensity_matrix = _build_scenario_arrays("matrix_effect_suppression")

    analyte_mask = ~feature_df["is_istd"].to_numpy(dtype=bool)
    exposure_mask = sample_info_df["Sample_Type"].eq("Exposure").to_numpy(dtype=bool)
    control_mask = sample_info_df["Sample_Type"].eq("Control").to_numpy(dtype=bool)

    exposure_median = float(np.nanmedian(intensity_matrix[exposure_mask][:, analyte_mask]))
    control_median = float(np.nanmedian(intensity_matrix[control_mask][:, analyte_mask]))

    assert exposure_median < control_median * 0.85


@pytest.mark.integration
def test_istd_sample_interference_generator_preserves_qc_but_hits_exposure_samples():
    _, sample_info_df, feature_df, intensity_matrix = _build_scenario_arrays("istd_sample_interference")

    istd_mask = feature_df["is_istd"].to_numpy(dtype=bool)
    exposure_mask = sample_info_df["Sample_Type"].eq("Exposure").to_numpy(dtype=bool)
    control_mask = sample_info_df["Sample_Type"].eq("Control").to_numpy(dtype=bool)
    qc_mask = sample_info_df["Sample_Type"].eq("QC").to_numpy(dtype=bool)

    exposure_median = float(np.nanmedian(intensity_matrix[exposure_mask][:, istd_mask]))
    control_median = float(np.nanmedian(intensity_matrix[control_mask][:, istd_mask]))
    qc_cvs = []
    for feature_index in np.where(istd_mask)[0]:
        values = intensity_matrix[qc_mask, feature_index]
        values = values[np.isfinite(values)]
        qc_cvs.append(values.std(ddof=1) / values.mean() * 100)

    assert exposure_median < control_median * 0.8
    assert float(np.nanmedian(qc_cvs)) < 20.0


@pytest.mark.integration
def test_mixed_direction_batch_drift_generator_has_opposite_qc_trend_directions():
    config, sample_info_df, feature_df, intensity_matrix = _build_scenario_arrays("mixed_direction_batch_drift")

    injection_orders = sample_info_df["Injection_Order"].to_numpy(dtype=float)
    analyte_mask = ~feature_df["is_istd"].to_numpy(dtype=bool)
    slopes = []

    for batch in config.batches:
        qc_mask = (
            sample_info_df["Batch"].eq(batch)
            & sample_info_df["Sample_Type"].eq("QC")
        ).to_numpy(dtype=bool)
        qc_totals = np.nanmedian(intensity_matrix[qc_mask][:, analyte_mask], axis=1)
        slopes.append(float(np.polyfit(injection_orders[qc_mask], qc_totals, 1)[0]))

    assert any(slope > 0 for slope in slopes)
    assert any(slope < 0 for slope in slopes)


@pytest.mark.integration
def test_signal_saturation_generator_compresses_upper_tail_against_balanced_pipeline():
    _, sample_info_df_sat, feature_df_sat, intensity_matrix_sat = _build_scenario_arrays("signal_saturation")
    _, sample_info_df_base, feature_df_base, intensity_matrix_base = _build_scenario_arrays("balanced_pipeline")

    non_qc_mask = sample_info_df_sat["Sample_Type"].ne("QC").to_numpy(dtype=bool)
    analyte_mask = ~feature_df_sat["is_istd"].to_numpy(dtype=bool)

    sat_ratio = float(
        np.nanquantile(intensity_matrix_sat[non_qc_mask][:, analyte_mask], 0.995)
        / np.nanquantile(intensity_matrix_sat[non_qc_mask][:, analyte_mask], 0.90)
    )
    base_ratio = float(
        np.nanquantile(intensity_matrix_base[non_qc_mask][:, analyte_mask], 0.995)
        / np.nanquantile(intensity_matrix_base[non_qc_mask][:, analyte_mask], 0.90)
    )

    assert sat_ratio < base_ratio * 0.9


@pytest.mark.integration
def test_step1_regression_scenario_runs_for_istd_degradation(istd_module, project_root):
    input_file, session_dir = _prepare_persistent_scenario_run(project_root, "istd_degradation")

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    assert any((session_dir / "plots").glob("Step1_*.png"))


@pytest.mark.integration
def test_step1_regression_scenario_runs_for_istd_sample_interference(istd_module, project_root):
    input_file, session_dir = _prepare_persistent_scenario_run(project_root, "istd_sample_interference")

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    assert Path(step1_result.output_path).exists()


@pytest.mark.integration
@pytest.mark.parametrize("scenario_name", ["nonlinear_drift", "carryover_memory"])
def test_step2_regression_scenarios_run_and_emit_plots(
    istd_module,
    qc_lowess_module,
    project_root,
    scenario_name,
):
    input_file, session_dir = _prepare_persistent_scenario_run(project_root, scenario_name)

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")
    assert any((session_dir / "plots").glob("Step2_*.png"))


@pytest.mark.integration
def test_mixed_direction_batch_drift_runs_through_step3(
    istd_module,
    qc_lowess_module,
    qc_batch_scaling_module,
    project_root,
):
    input_file, session_dir = _prepare_persistent_scenario_run(project_root, "mixed_direction_batch_drift")

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)
    step3_result = qc_batch_scaling_module.main(input_file=step2_result.output_path, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")
    _assert_result_in_session(step3_result, session_dir, "Step3_")
    assert any((session_dir / "plots").glob("Step3_*.png"))


@pytest.mark.integration
@pytest.mark.parametrize("scenario_name", ["matrix_effect_suppression", "signal_saturation"])
def test_advanced_step4_regression_scenarios_run_with_pqn(
    istd_module,
    qc_lowess_module,
    qc_batch_scaling_module,
    conc_norm_module,
    project_root,
    scenario_name,
):
    input_file, session_dir = _prepare_persistent_scenario_run(project_root, scenario_name)

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)
    step3_result = qc_batch_scaling_module.main(input_file=step2_result.output_path, session_dir=session_dir)
    step4_result = conc_norm_module.main(
        input_file=step3_result.output_path,
        session_dir=session_dir,
        normalization_method="PQN",
    )

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")
    _assert_result_in_session(step3_result, session_dir, "Step3_")
    _assert_result_in_session(step4_result, session_dir, "Step4_")
    assert "Normalized_PQN" in Path(step4_result.output_path).name


@pytest.mark.integration
def test_structured_missingness_runs_through_step4_pqn(
    istd_module,
    qc_lowess_module,
    qc_batch_scaling_module,
    conc_norm_module,
    project_root,
):
    input_file, session_dir = _prepare_persistent_scenario_run(project_root, "structured_missingness")

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)
    step3_result = qc_batch_scaling_module.main(input_file=step2_result.output_path, session_dir=session_dir)
    step4_result = conc_norm_module.main(
        input_file=step3_result.output_path,
        session_dir=session_dir,
        normalization_method="PQN",
    )

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")
    _assert_result_in_session(step3_result, session_dir, "Step3_")
    _assert_result_in_session(step4_result, session_dir, "Step4_")
    assert "Normalized_PQN" in Path(step4_result.output_path).name
