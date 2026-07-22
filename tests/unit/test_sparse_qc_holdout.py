from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from metabolomics.processors import qc_lowess
from scripts.sparse_qc_holdout import (
    DEFAULT_CONTRACT,
    _log_rmse,
    _task_outcomes,
    derive_holdout_seeds,
    evaluate_promotion_contract,
    load_holdout_manifest,
    run_characterization,
    summarize_promotion,
)
from scripts.synthetic_matrix_vnext import (
    QC_LIMITED_ROUTING_INVARIANT_CLASSES,
    QC_LIMITED_ROUTING_RECIPE_VERSION,
    generate_simulation,
    qc_limited_routing_semantic_config_digest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "tests" / "baselines" / "sparse_qc_holdout_v1.json"


def _accepted_rows(gains: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "status": ["success"] * len(gains),
            "drift_kind": ["linear"] * len(gains),
            "recovery_gain": gains,
        }
    )


def test_promotion_contract_allows_at_most_five_percent_mild_harm():
    result = evaluate_promotion_contract(
        _accepted_rows([0.25] * 95 + [-0.05] * 5),
        biology_sign_flip_rate=0.0,
        contract=DEFAULT_CONTRACT,
    )

    assert result["decision"] == "pass"
    assert result["mild_harm_count"] == 5
    assert result["severe_harm_count"] == 0


def test_promotion_contract_counts_exact_floor_as_mild_not_severe():
    result = evaluate_promotion_contract(
        _accepted_rows([0.25] * 95 + [-0.10] * 5),
        biology_sign_flip_rate=0.0,
        contract=DEFAULT_CONTRACT,
    )

    assert result["decision"] == "pass"
    assert result["mild_harm_count"] == 5
    assert result["severe_harm_count"] == 0


@pytest.mark.parametrize("severe_gain", [-0.100001, -0.30])
def test_promotion_contract_fails_on_any_severe_tail(severe_gain):
    result = evaluate_promotion_contract(
        _accepted_rows([0.25] * 99 + [severe_gain]),
        biology_sign_flip_rate=0.0,
        contract=DEFAULT_CONTRACT,
    )

    assert result["decision"] == "fail"
    assert "severe_tail" in result["failure_reasons"]


def test_promotion_contract_reports_insufficient_evidence_before_fifty_accepts():
    result = evaluate_promotion_contract(
        _accepted_rows([0.25] * 49),
        biology_sign_flip_rate=0.0,
        contract=DEFAULT_CONTRACT,
    )

    assert result["decision"] == "insufficient_evidence"
    assert "accepted_task_count" in result["failure_reasons"]


def test_promotion_contract_fails_on_biology_sign_flip():
    result = evaluate_promotion_contract(
        _accepted_rows([0.25] * 100),
        biology_sign_flip_rate=0.01,
        contract=DEFAULT_CONTRACT,
    )

    assert result["decision"] == "fail"
    assert "biology_sign_flip" in result["failure_reasons"]


def test_holdout_manifest_is_frozen_and_disjoint_from_development_seeds():
    manifest = load_holdout_manifest(MANIFEST_PATH)

    assert manifest["version"] == 1
    assert manifest["recipe"] == "qc_limited_routing"
    assert manifest["development"]["seeds"] == [51, 137, 911]
    assert manifest["development"]["variants"] == ["baseline"]
    assert manifest["holdout"]["variants"] == ["baseline", "drift_low", "drift_high"]
    assert manifest["holdout"]["seeds"] == derive_holdout_seeds(
        count=20,
        excluded_seeds=set(manifest["development"]["seeds"]),
    )
    assert len(set(manifest["holdout"]["seeds"])) == 20
    assert not set(manifest["development"]["seeds"]) & set(manifest["holdout"]["seeds"])
    assert manifest["promotion_target"] == DEFAULT_CONTRACT
    assert manifest["recipe_version"] == QC_LIMITED_ROUTING_RECIPE_VERSION
    assert (
        manifest["semantic_config_sha256"]
        == qc_limited_routing_semantic_config_digest()
    )
    assert manifest["expected_invariant_classes"] == list(
        QC_LIMITED_ROUTING_INVARIANT_CLASSES
    )


def test_summarize_promotion_counts_only_eligible_accepted_tasks():
    manifest = deepcopy(load_holdout_manifest(MANIFEST_PATH))
    manifest["promotion_target"]["min_accepted_tasks"] = 1
    metrics = pd.DataFrame(
        [{"evidence_set": "holdout", "policy": "current_6", "biology_sign_flip_rate": 0.0}]
    )
    base = {
        "evidence_set": "holdout",
        "policy": "current_6",
        "effective_qc_count": 6,
        "endpoint_valid": True,
        "status": "success",
        "drift_kind": "linear",
        "recovery_gain": 0.2,
    }
    tasks = pd.DataFrame(
        [
            base,
            {**base, "status": "skipped"},
            {**base, "drift_kind": "none"},
            {**base, "effective_qc_count": 7},
            {**base, "endpoint_valid": False},
            {**base, "evidence_set": "development"},
            {**base, "policy": "strict_8"},
        ]
    )

    decision = summarize_promotion(
        metrics,
        tasks,
        manifest,
        evidence_set="holdout",
    )

    assert decision["decision"] == "pass"
    assert decision["accepted_task_count"] == 1


def test_development_characterization_compares_all_three_policies():
    manifest = deepcopy(load_holdout_manifest(MANIFEST_PATH))
    manifest["development"] = {"seeds": [51], "variants": ["baseline"]}

    original_minimum = qc_lowess.LINEAR_FALLBACK_MIN_QC
    metrics, tasks = run_characterization(manifest, evidence_sets=("development",))
    decision = summarize_promotion(
        metrics,
        tasks,
        manifest,
        evidence_set="development",
    )

    assert set(metrics["policy"]) == {"no_correction", "strict_8", "current_6"}
    assert set(tasks["policy"]) == {"no_correction", "strict_8", "current_6"}
    assert set(tasks["effective_qc_count"]) == {4, 5, 6, 7, 8}
    assert decision["decision"] in {"fail", "insufficient_evidence"}
    eligible_six = tasks.loc[
        tasks["effective_qc_count"].eq(6)
        & tasks["endpoint_valid"]
        & tasks["drift_kind"].ne("none")
    ]
    paired = eligible_six.pivot(
        index=["FeatureID", "Batch"],
        columns="policy",
        values=["status", "fit_strategy"],
    )
    activated = paired.loc[
        paired[("status", "current_6")].eq("success")
        & paired[("fit_strategy", "current_6")].eq("log_linear_fallback")
    ]
    assert not activated.empty
    assert activated[("status", "strict_8")].ne("success").all()
    assert qc_lowess.LINEAR_FALLBACK_MIN_QC == original_minimum


def test_task_recovery_rmse_uses_study_samples_not_fitting_qcs():
    result = generate_simulation("qc_limited_routing", seed=51)
    outcomes = _task_outcomes(
        result,
        result.observed.copy(),
        {},
        evidence_set="development",
        variant="baseline",
        policy="no_correction",
    )
    first = next(row for row in outcomes if row["drift_kind"] == "linear")
    feature_index = result.feature_info.index[
        result.feature_info["FeatureID"].eq(first["FeatureID"])
    ][0]
    study_rows = result.sample_info.index[
        result.sample_info["Batch"].eq(first["Batch"])
        & result.sample_info["Sample_Type"].ne("QC")
    ].to_numpy()
    expected = _log_rmse(
        result.observed[study_rows, feature_index],
        result.truth.step2_counterfactual[study_rows, feature_index],
    )
    all_batch_rows = result.sample_info.index[
        result.sample_info["Batch"].eq(first["Batch"])
    ].to_numpy()
    all_rows_rmse = _log_rmse(
        result.observed[all_batch_rows, feature_index],
        result.truth.step2_counterfactual[all_batch_rows, feature_index],
    )

    assert first["raw_log2_rmse"] == pytest.approx(expected)
    assert expected != pytest.approx(all_rows_rmse)
