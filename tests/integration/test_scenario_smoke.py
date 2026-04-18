from pathlib import Path

import pytest

from metabolomics.utils.file_io import create_session_dir
from scripts.generate_batcheffect_data import SCENARIO_LIBRARY, generate_scenario_workbook


def _prepare_scenario_run(tmp_path: Path, scenario_name: str) -> tuple[str, Path]:
    input_path = tmp_path / "scenario_inputs" / f"{scenario_name}.xlsx"
    session_root = tmp_path / "scenario_outputs" / scenario_name
    generate_scenario_workbook(SCENARIO_LIBRARY[scenario_name], input_path)
    session_dir = create_session_dir(
        output_root=session_root,
        timestamp=f"{scenario_name}_session",
    )
    return str(input_path), session_dir


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
def test_step1_scenario_smoke(istd_module, tmp_path):
    input_file, session_dir = _prepare_scenario_run(tmp_path, "unstable_istd")

    result = istd_module.main(input_file=input_file, session_dir=session_dir)

    _assert_result_in_session(result, session_dir, "Step1_")
    assert (session_dir / "plots").exists()


@pytest.mark.integration
@pytest.mark.parametrize("scenario_name", ["strong_drift", "random_jump", "order_confounding"])
def test_step2_scenarios_smoke(istd_module, qc_lowess_module, tmp_path, scenario_name):
    input_file, session_dir = _prepare_scenario_run(tmp_path, scenario_name)

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")


@pytest.mark.integration
def test_step3_scenario_smoke(istd_module, qc_lowess_module, qc_batch_scaling_module, tmp_path):
    input_file, session_dir = _prepare_scenario_run(tmp_path, "strong_batch")

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)
    from metabolomics.processors import normalization
    step3_result = normalization.main(input_file=step2_result.output_path, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")
    _assert_result_in_session(step3_result, session_dir, "Step3_")


@pytest.mark.integration
@pytest.mark.parametrize(
    ("scenario_name", "normalization_method", "expected_fragment"),
    [
        ("balanced_pipeline", "PQN", "Normalized_PQN"),
        ("order_confounding", "PQN", "Normalized_PQN"),
        ("specnorm_friendly", "SpecNorm+PQN", "Normalized_SpecNorm_PQN"),
    ],
)
def test_step4_scenarios_smoke(
    istd_module,
    qc_lowess_module,
    qc_batch_scaling_module,
    conc_norm_module,
    tmp_path,
    scenario_name,
    normalization_method,
    expected_fragment,
):
    input_file, session_dir = _prepare_scenario_run(tmp_path, scenario_name)

    step1_result = istd_module.main(input_file=input_file, session_dir=session_dir)
    step2_result = qc_lowess_module.main(input_file=step1_result.output_path, session_dir=session_dir)
    step3_result = conc_norm_module.main(
        input_file=step2_result.output_path,
        session_dir=session_dir,
        normalization_method=normalization_method,
    )
    step4_result = qc_batch_scaling_module.main(input_file=step3_result.output_path, session_dir=session_dir)

    _assert_step1_result_allows_skip(step1_result, input_file, session_dir)
    _assert_result_in_session(step2_result, session_dir, "Step2_")
    _assert_result_in_session(step3_result, session_dir, "Step3_")
    _assert_result_in_session(step4_result, session_dir, "Step4_")
    assert expected_fragment in Path(step3_result.output_path).name
