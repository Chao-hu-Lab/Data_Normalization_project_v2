"""Run frozen truth-backed evidence for the provisional six-QC fallback."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from metabolomics.processors import qc_lowess  # noqa: E402
from scripts.synthetic_matrix_vnext import (  # noqa: E402
    QC_LIMITED_ROUTING_INVARIANT_CLASSES,
    QC_LIMITED_ROUTING_RECIPE_VERSION,
    SimulationResult,
    evaluate_step2_candidate,
    generate_simulation,
    qc_limited_routing_semantic_config_digest,
)


V1_MANIFEST_PATH = (
    PROJECT_ROOT / "tests" / "baselines" / "sparse_qc_holdout_v1.json"
)
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "tests"
    / "baselines"
    / "sparse_qc_shrinkage_holdout_v2.json"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "build" / "sparse_qc_shrinkage_holdout_v2"
DEFAULT_CONTRACT = {
    "effective_qc_count": 6,
    "mild_harm_floor": -0.10,
    "max_mild_harm_rate": 0.05,
    "max_severe_harm_count": 0,
    "max_biology_sign_flip_rate": 0.0,
    "min_accepted_tasks": 50,
}
POLICY_MIN_QC = {
    "strict_8": 8,
    "current_6": 6,
}
DETAIL_PATTERN = re.compile(
    r"^(?P<batch>[^:]+):status=(?P<status>[^,]+),"
    r"fit=(?P<fit>[^,]+),valid_qc=(?P<valid_qc>\d+)$"
)
HOLDOUT_SEED_NAMESPACE = "dnp-sparse-qc-holdout-v1"


def derive_holdout_seeds(
    *,
    count: int,
    namespace: str = HOLDOUT_SEED_NAMESPACE,
    excluded_seeds: set[int] | None = None,
) -> list[int]:
    """Derive frozen seeds from a documented SHA256 namespace."""
    excluded = excluded_seeds or set()
    seeds: list[int] = []
    index = 0
    while len(seeds) < count:
        payload = f"{namespace}:{index}".encode("utf-8")
        candidate = (
            int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")
            % 2_147_483_647
        )
        if candidate not in excluded and candidate not in seeds:
            seeds.append(candidate)
        index += 1
    return seeds


def _validate_holdout_manifest(manifest: dict) -> None:
    development_seeds = set(manifest["development"]["seeds"])
    namespace = manifest["holdout"].get("namespace", HOLDOUT_SEED_NAMESPACE)
    expected_seeds = derive_holdout_seeds(
        count=len(manifest["holdout"]["seeds"]),
        namespace=namespace,
        excluded_seeds=development_seeds,
    )
    version = manifest.get("version")
    if version == 1:
        promotion_contract_valid = (
            manifest.get("promotion_target") == DEFAULT_CONTRACT
        )
        candidate_valid = True
    elif version == 2:
        promotion_contract_valid = all(
            {**target, "effective_qc_count": 6} == DEFAULT_CONTRACT
            for target in manifest.get("promotion_targets", [])
        ) and [
            target["effective_qc_count"]
            for target in manifest.get("promotion_targets", [])
        ] == [6, 7]
        candidate_valid = manifest.get("candidate") == {
            "linear_fallback_min_qc": qc_lowess.LINEAR_FALLBACK_MIN_QC,
            "linear_fallback_shrinkage": qc_lowess.LINEAR_FALLBACK_SHRINKAGE,
            "lowess_min_qc": qc_lowess.LOWESS_MIN_QC,
        }
    else:
        promotion_contract_valid = False
        candidate_valid = False
    checks = {
        "recipe_version": manifest.get("recipe_version")
        == QC_LIMITED_ROUTING_RECIPE_VERSION,
        "semantic_config_sha256": manifest.get("semantic_config_sha256")
        == qc_limited_routing_semantic_config_digest(),
        "expected_invariant_classes": manifest.get("expected_invariant_classes")
        == list(QC_LIMITED_ROUTING_INVARIANT_CLASSES),
        "holdout_seeds": manifest["holdout"]["seeds"] == expected_seeds,
        "promotion_contract": promotion_contract_valid,
        "candidate": candidate_valid,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Invalid frozen holdout manifest fields: {', '.join(failed)}")


def load_holdout_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> dict:
    """Load the frozen development/holdout manifest."""
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_holdout_manifest(manifest)
    return manifest


def evaluate_promotion_contract(
    task_results: pd.DataFrame,
    *,
    biology_sign_flip_rate: float,
    contract: dict | None = None,
) -> dict:
    """Apply the precommitted six-QC promotion contract to accepted tasks."""
    rules = {**DEFAULT_CONTRACT, **(contract or {})}
    eligible = task_results.loc[task_results["drift_kind"].ne("none")].copy()
    accepted = eligible.loc[eligible["status"].eq("success")].copy()
    gains = pd.to_numeric(accepted["recovery_gain"], errors="coerce")
    invalid_gain_count = int(gains.isna().sum())
    valid_gains = gains.dropna()
    severe_mask = valid_gains < float(rules["mild_harm_floor"])
    mild_mask = (
        (valid_gains >= float(rules["mild_harm_floor"]))
        & (valid_gains < 0)
    )
    accepted_count = int(len(accepted))
    eligible_count = int(len(eligible))
    acceptance_rate = accepted_count / eligible_count if eligible_count else np.nan
    status_counts = {
        str(status): int(count)
        for status, count in eligible["status"].value_counts().sort_index().items()
    }
    severe_count = int(severe_mask.sum())
    mild_count = int(mild_mask.sum())
    mild_rate = mild_count / accepted_count if accepted_count else np.nan

    failure_reasons = []
    if invalid_gain_count:
        failure_reasons.append("invalid_recovery_gain")
    if severe_count > int(rules["max_severe_harm_count"]):
        failure_reasons.append("severe_tail")
    if np.isfinite(mild_rate) and mild_rate > float(rules["max_mild_harm_rate"]):
        failure_reasons.append("mild_harm_rate")
    if (
        not np.isfinite(biology_sign_flip_rate)
        or biology_sign_flip_rate > float(rules["max_biology_sign_flip_rate"])
    ):
        failure_reasons.append("biology_sign_flip")

    if failure_reasons:
        decision = "fail"
    elif accepted_count < int(rules["min_accepted_tasks"]):
        decision = "insufficient_evidence"
        failure_reasons.append("accepted_task_count")
    else:
        decision = "pass"

    return {
        "decision": decision,
        "eligible_task_count": eligible_count,
        "accepted_task_count": accepted_count,
        "acceptance_rate": (
            float(acceptance_rate) if np.isfinite(acceptance_rate) else None
        ),
        "status_counts": status_counts,
        "mild_harm_count": mild_count,
        "mild_harm_rate": float(mild_rate) if np.isfinite(mild_rate) else None,
        "severe_harm_count": severe_count,
        "invalid_recovery_gain_count": invalid_gain_count,
        "minimum_recovery_gain": (
            float(valid_gains.min()) if not valid_gains.empty else None
        ),
        "median_recovery_gain": (
            float(valid_gains.median()) if not valid_gains.empty else None
        ),
        "biology_sign_flip_rate": float(biology_sign_flip_rate),
        "failure_reasons": failure_reasons,
        "contract": rules,
    }


def _log_rmse(observed: np.ndarray, target: np.ndarray) -> float:
    valid = (
        np.isfinite(observed)
        & np.isfinite(target)
        & (observed > 0)
        & (target > 0)
    )
    if not valid.any():
        return np.nan
    errors = np.log2(observed[valid]) - np.log2(target[valid])
    return float(np.sqrt(np.mean(errors**2)))


def _source_frame(result: SimulationResult) -> tuple[pd.DataFrame, list[str]]:
    sample_names = result.sample_info["Sample_Name"].tolist()
    source = pd.DataFrame(result.observed.T, columns=sample_names)
    source.insert(0, "FeatureID", result.feature_info["FeatureID"])
    source.attrs["sample_columns"] = sample_names
    return source, sample_names


def _parse_decisions(summary: pd.DataFrame) -> dict[tuple[str, str], dict[str, str]]:
    decisions = {}
    for row in summary.itertuples(index=False):
        for item in row.Batch_Decision_Detail.split("; "):
            match = DETAIL_PATTERN.match(item)
            if match:
                decisions[(row.FeatureID, match.group("batch"))] = match.groupdict()
    return decisions


def _run_processor_policy(
    result: SimulationResult,
    policy: str,
) -> tuple[np.ndarray, dict[tuple[str, str], dict[str, str]]]:
    if policy not in POLICY_MIN_QC:
        raise ValueError(f"Unknown processor policy: {policy}")
    source, sample_names = _source_frame(result)
    original_minimum = qc_lowess.LINEAR_FALLBACK_MIN_QC
    qc_lowess.LINEAR_FALLBACK_MIN_QC = POLICY_MIN_QC[policy]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            corrected, _, _, summary, _, _ = qc_lowess.perform_lowess_normalization(
                source,
                result.sample_info,
            )
    finally:
        qc_lowess.LINEAR_FALLBACK_MIN_QC = original_minimum
    matrix = corrected[sample_names].to_numpy(dtype=float).T
    return matrix, _parse_decisions(summary)


def _task_outcomes(
    result: SimulationResult,
    corrected: np.ndarray,
    decisions: dict[tuple[str, str], dict[str, str]],
    *,
    evidence_set: str,
    variant: str,
    policy: str,
) -> list[dict]:
    routing = result.truth.routing_truth
    if routing is None:
        raise ValueError("qc_limited_routing truth is required")
    records = []
    for route in routing.itertuples(index=False):
        feature_index = result.feature_info.index[
            result.feature_info["FeatureID"].eq(route.FeatureID)
        ][0]
        batch_rows = result.sample_info.index[
            result.sample_info["Batch"].eq(route.Batch)
            & result.sample_info["Sample_Type"].ne("QC")
        ].to_numpy()
        raw_rmse = _log_rmse(
            result.observed[batch_rows, feature_index],
            result.truth.step2_counterfactual[batch_rows, feature_index],
        )
        corrected_rmse = _log_rmse(
            corrected[batch_rows, feature_index],
            result.truth.step2_counterfactual[batch_rows, feature_index],
        )
        recovery_gain = (
            1.0 - corrected_rmse / raw_rmse
            if np.isfinite(raw_rmse) and raw_rmse > 1e-12
            else np.nan
        )
        if policy == "no_correction":
            decision = {"status": "not_applied", "fit": "none"}
        else:
            decision = decisions[(route.FeatureID, route.Batch)]
        records.append(
            {
                "evidence_set": evidence_set,
                "seed": result.seed,
                "variant": variant,
                "policy": policy,
                "FeatureID": route.FeatureID,
                "Batch": route.Batch,
                "effective_qc_count": route.effective_qc_count,
                "endpoint_valid": bool(route.endpoint_valid),
                "drift_kind": route.drift_kind,
                "status": decision["status"],
                "fit_strategy": decision["fit"],
                "raw_log2_rmse": raw_rmse,
                "corrected_log2_rmse": corrected_rmse,
                "recovery_gain": recovery_gain,
            }
        )
    return records


def run_characterization(
    manifest: dict,
    *,
    evidence_sets: tuple[str, ...] = ("development", "holdout"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run all frozen scenarios for no-correction, strict-8, and current-6."""
    metric_records = []
    task_records = []
    for evidence_set in evidence_sets:
        selection = manifest[evidence_set]
        for seed in selection["seeds"]:
            for variant in selection["variants"]:
                result = generate_simulation(
                    manifest["recipe"],
                    seed=int(seed),
                    variant=variant,
                )
                policies = {
                    "no_correction": (result.observed.copy(), {}),
                    "strict_8": _run_processor_policy(result, "strict_8"),
                    "current_6": _run_processor_policy(result, "current_6"),
                }
                for policy, (corrected, decisions) in policies.items():
                    metrics = evaluate_step2_candidate(result, corrected)
                    metric_records.append(
                        {
                            "evidence_set": evidence_set,
                            "seed": int(seed),
                            "variant": variant,
                            "policy": policy,
                            **metrics,
                        }
                    )
                    task_records.extend(
                        _task_outcomes(
                            result,
                            corrected,
                            decisions,
                            evidence_set=evidence_set,
                            variant=variant,
                            policy=policy,
                        )
                    )
    return pd.DataFrame(metric_records), pd.DataFrame(task_records)


def _contract_for_manifest(
    manifest: dict,
    effective_qc_count: int | None = None,
) -> dict:
    if "promotion_targets" in manifest:
        if effective_qc_count is None:
            raise ValueError("effective_qc_count is required for multi-target manifests")
        matches = [
            target
            for target in manifest["promotion_targets"]
            if target["effective_qc_count"] == effective_qc_count
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one promotion target for {effective_qc_count} QC"
            )
        return {**DEFAULT_CONTRACT, **matches[0]}
    return {**DEFAULT_CONTRACT, **manifest.get("promotion_target", {})}


def summarize_promotion(
    metrics: pd.DataFrame,
    tasks: pd.DataFrame,
    manifest: dict,
    *,
    evidence_set: str,
    effective_qc_count: int | None = None,
) -> dict:
    contract = _contract_for_manifest(manifest, effective_qc_count)
    target_tasks = tasks.loc[
        tasks["evidence_set"].eq(evidence_set)
        & tasks["policy"].eq("current_6")
        & tasks["effective_qc_count"].eq(contract["effective_qc_count"])
        & tasks["endpoint_valid"]
    ]
    sign_flip_values = pd.to_numeric(
        metrics.loc[
            metrics["evidence_set"].eq(evidence_set)
            & metrics["policy"].eq("current_6"),
            "biology_sign_flip_rate",
        ],
        errors="coerce",
    )
    maximum_sign_flip_rate = (
        float(sign_flip_values.max()) if not sign_flip_values.empty else np.nan
    )
    result = evaluate_promotion_contract(
        target_tasks,
        biology_sign_flip_rate=maximum_sign_flip_rate,
        contract=contract,
    )
    result["evidence_set"] = evidence_set
    return result


def summarize_manifest_promotions(
    metrics: pd.DataFrame,
    tasks: pd.DataFrame,
    manifest: dict,
    *,
    evidence_sets: tuple[str, ...],
) -> dict[str, dict]:
    """Evaluate every precommitted QC-count target in a manifest."""
    targets = manifest.get("promotion_targets")
    if not targets:
        decisions = {
            evidence_set: summarize_promotion(
                metrics,
                tasks,
                manifest,
                evidence_set=evidence_set,
            )
            for evidence_set in evidence_sets
        }
        if manifest.get("version") == 1:
            for decision in decisions.values():
                decision["characterization_decision"] = decision["decision"]
                decision["decision"] = "characterization_only"
                decision["promotion_eligible"] = False
                decision["failure_reasons"].append(
                    "holdout_previously_exposed"
                )
        return decisions
    decisions = {}
    for evidence_set in evidence_sets:
        for target in targets:
            qc_count = int(target["effective_qc_count"])
            decisions[f"{evidence_set}_qc{qc_count}"] = summarize_promotion(
                metrics,
                tasks,
                manifest,
                evidence_set=evidence_set,
                effective_qc_count=qc_count,
            )
            decisions[f"{evidence_set}_qc{qc_count}"][
                "promotion_eligible"
            ] = True
    return decisions


def _format_number(value, digits: int = 4) -> str:
    if value is None or not np.isfinite(value):
        return "N/A"
    return f"{value:.{digits}f}"


def build_markdown_report(
    metrics: pd.DataFrame,
    tasks: pd.DataFrame,
    decisions: dict[str, dict],
    provenance: dict[str, object] | None = None,
) -> str:
    decision_keys = list(decisions)
    lines = [
        "# Sparse-QC Holdout Characterization",
        "",
        "## Decision",
        "",
    ]
    for decision_key in decision_keys:
        label = decision_key.replace("_", " ").title()
        lines.append(f"- {label}: `{decisions[decision_key]['decision']}`")
    if any(
        key.startswith("holdout")
        and decisions[key].get("promotion_eligible", False)
        for key in decision_keys
    ):
        lines.append("- Promotion requires every holdout target to be `pass`.")
    lines.extend(
        [
            "",
            "## Sparse-QC promotion contracts",
            "",
            "| Evidence set | QC count | Eligible | Accepted | Acceptance | Mild harm | Severe harm | Minimum gain | Sign-flip rate | Decision |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for decision_key in decision_keys:
        decision = decisions[decision_key]
        lines.append(
            "| "
            f"{decision['evidence_set']} | "
            f"{decision['contract']['effective_qc_count']} | "
            f"{decision['eligible_task_count']} | "
            f"{decision['accepted_task_count']} | "
            f"{_format_number(decision['acceptance_rate'])} | "
            f"{decision['mild_harm_count']} | {decision['severe_harm_count']} | "
            f"{_format_number(decision['minimum_recovery_gain'])} | "
            f"{_format_number(decision['biology_sign_flip_rate'])} | "
            f"{decision['decision']} |"
        )

    lines.extend(["", "## Eligibility status counts", ""])
    for decision_key in decision_keys:
        counts = ", ".join(
            f"{status}={count}"
            for status, count in decisions[decision_key]["status_counts"].items()
        )
        lines.append(f"- {decision_key}: {counts or 'none'}")

    lines.extend(
        [
            "",
            "## Candidate-level medians",
            "",
            "| Evidence set | Policy | Recovery gain | False correction | Sign flip | Fold-change error |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    grouped = metrics.groupby(["evidence_set", "policy"], sort=False).median(
        numeric_only=True
    )
    for (evidence_set, policy), row in grouped.iterrows():
        lines.append(
            "| "
            f"{evidence_set} | {policy} | "
            f"{_format_number(row['median_technical_recovery_gain'])} | "
            f"{_format_number(row['false_correction_rate'])} | "
            f"{_format_number(row['biology_sign_flip_rate'])} | "
            f"{_format_number(row['median_abs_log2_fold_change_error'])} |"
        )

    detail_keys = [key for key in decision_keys if key.startswith("holdout")]
    if not detail_keys:
        detail_keys = decision_keys
    for decision_key in detail_keys:
        decision = decisions[decision_key]
        qc_count = decision["contract"]["effective_qc_count"]
        detail_tasks = tasks.loc[
            tasks["evidence_set"].eq(decision["evidence_set"])
            & tasks["policy"].eq("current_6")
            & tasks["effective_qc_count"].eq(qc_count)
            & tasks["endpoint_valid"]
            & tasks["status"].eq("success")
            & tasks["drift_kind"].ne("none")
        ].sort_values("recovery_gain")
        lines.extend(
            [
                "",
                f"## Worst accepted {qc_count}-QC tasks",
                "",
                "| Seed | Variant | FeatureID | Batch | Truth | Recovery gain |",
                "| ---: | --- | --- | --- | --- | ---: |",
            ]
        )
        for row in detail_tasks.head(10).itertuples(index=False):
            lines.append(
                f"| {row.seed} | {row.variant} | {row.FeatureID} | "
                f"{row.Batch} | {row.drift_kind} | "
                f"{_format_number(row.recovery_gain)} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This report is synthetic truth-backed evidence. It does not replace external validation on representative LC-MS data.",
            "A failed holdout stops promotion; it does not automatically change production behavior.",
            "",
        ]
    )
    if provenance:
        lines.extend(
            [
                "## Provenance",
                "",
                f"- Manifest SHA256: `{provenance['manifest_sha256']}`",
                f"- Semantic config SHA256: `{provenance['semantic_config_sha256']}`",
                f"- Generator source SHA256: `{provenance['generator_source_sha256']}`",
                f"- Processor source SHA256: `{provenance['processor_source_sha256']}`",
                f"- Runner source SHA256: `{provenance['runner_source_sha256']}`",
                f"- Git revision: `{provenance['git_revision']}`",
                f"- Working tree dirty: `{str(provenance['git_worktree_dirty']).lower()}`",
                "",
            ]
        )
    return "\n".join(lines)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_provenance(manifest_path: str | Path) -> dict[str, object]:
    """Collect fingerprints needed to attribute a generated evidence bundle."""
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
        dirty = True
    return {
        "manifest_sha256": _file_sha256(Path(manifest_path)),
        "semantic_config_sha256": qc_limited_routing_semantic_config_digest(),
        "generator_source_sha256": _file_sha256(
            PROJECT_ROOT / "scripts" / "synthetic_matrix_vnext.py"
        ),
        "processor_source_sha256": _file_sha256(
            PROJECT_ROOT / "src" / "metabolomics" / "processors" / "qc_lowess.py"
        ),
        "runner_source_sha256": _file_sha256(Path(__file__)),
        "git_revision": revision,
        "git_worktree_dirty": dirty,
    }


def write_outputs(
    output_dir: str | Path,
    metrics: pd.DataFrame,
    tasks: pd.DataFrame,
    decisions: dict[str, dict],
    provenance: dict[str, object],
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "candidate_metrics": destination / "candidate_metrics.csv",
        "task_outcomes": destination / "task_outcomes.csv",
        "promotion_decisions": destination / "promotion_decisions.json",
        "report": destination / "report.md",
    }
    metrics_with_provenance = metrics.assign(**provenance)
    tasks_with_provenance = tasks.assign(**provenance)
    metrics_with_provenance.to_csv(paths["candidate_metrics"], index=False)
    tasks_with_provenance.to_csv(paths["task_outcomes"], index=False)
    paths["promotion_decisions"].write_text(
        json.dumps(
            {**decisions, "_provenance": provenance},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    paths["report"].write_text(
        build_markdown_report(metrics, tasks, decisions, provenance),
        encoding="utf-8",
    )
    return paths


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run frozen sparse-QC development and holdout characterization."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--evidence-set",
        choices=("all", "development", "holdout"),
        default="all",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    manifest = load_holdout_manifest(args.manifest)
    evidence_sets = (
        ("development", "holdout")
        if args.evidence_set == "all"
        else (args.evidence_set,)
    )
    metrics, tasks = run_characterization(
        manifest,
        evidence_sets=evidence_sets,
    )
    decisions = summarize_manifest_promotions(
        metrics,
        tasks,
        manifest,
        evidence_sets=evidence_sets,
    )
    provenance = collect_provenance(args.manifest)
    paths = write_outputs(
        args.output_dir,
        metrics,
        tasks,
        decisions,
        provenance,
    )
    print(json.dumps({
        "decisions": {
            evidence_set: decision["decision"]
            for evidence_set, decision in decisions.items()
        },
        "outputs": {name: str(path) for name, path in paths.items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
