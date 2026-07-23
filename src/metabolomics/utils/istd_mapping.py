"""ISTD monitoring and explicit feature-to-ISTD correction contracts."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from metabolomics.utils.constants import CV_QUALITY_THRESHOLDS
from metabolomics.utils.safe_math import safe_cv_percent
from metabolomics.utils.sample_classification import (
    build_sample_info_mapping,
    identify_candidate_sample_columns,
    normalize_sample_type,
)


ISTD_MAPPING_SHEET = "ISTD_Mapping"
ISTD_MONITORING_SHEET = "ISTD_Monitoring"
ISTD_MAPPING_COLUMNS = (
    "Analyte_Feature_ID",
    "ISTD_Feature_ID",
    "Mapping_Type",
    "Validation_Reference",
)
ISTD_PROVENANCE_COLUMNS = (
    "Mapped_ISTD",
    "Mapping_Type",
    "Validation_Reference",
    "ISTD_Correction_Status",
    "ISTD_Correction_Reason",
)
ALLOWED_MAPPING_TYPES = {"matched", "validated_surrogate"}


def validate_istd_mapping(
    mapping_df: pd.DataFrame | None,
    intensity_df: pd.DataFrame,
) -> pd.DataFrame:
    """Validate identities and normalize an optional ISTD mapping sheet."""

    if mapping_df is None or mapping_df.empty:
        return pd.DataFrame(columns=ISTD_MAPPING_COLUMNS)
    missing_columns = [
        column for column in ISTD_MAPPING_COLUMNS if column not in mapping_df.columns
    ]
    if missing_columns:
        raise ValueError(
            "ISTD_Mapping is missing required columns: "
            + ", ".join(missing_columns)
        )
    if "FeatureID" not in intensity_df.columns or "is_ISTD" not in intensity_df.columns:
        raise ValueError("ISTD mapping validation requires FeatureID and is_ISTD")
    normalized_feature_ids = intensity_df["FeatureID"].astype(str)
    duplicate_feature_mask = normalized_feature_ids.duplicated(keep=False)
    if duplicate_feature_mask.any():
        duplicates = sorted(
            normalized_feature_ids.loc[duplicate_feature_mask].unique()
        )
        raise ValueError(
            "Explicit ISTD mapping requires unique RawIntensity FeatureID values; "
            "duplicates: "
            + ", ".join(duplicates)
        )

    mapping = mapping_df.loc[:, ISTD_MAPPING_COLUMNS].copy()
    for column in ISTD_MAPPING_COLUMNS:
        mapping[column] = mapping[column].fillna("").astype(str).str.strip()
    mapping = mapping.loc[
        mapping[list(ISTD_MAPPING_COLUMNS)].ne("").any(axis=1)
    ].reset_index(drop=True)
    if mapping.empty:
        return mapping

    duplicate_mask = mapping["Analyte_Feature_ID"].duplicated(keep=False)
    if duplicate_mask.any():
        duplicates = sorted(mapping.loc[duplicate_mask, "Analyte_Feature_ID"].unique())
        raise ValueError(
            "ISTD_Mapping contains duplicate analyte entries: "
            + ", ".join(duplicates)
        )

    feature_ids = set(normalized_feature_ids)
    istd_ids = set(
        intensity_df.loc[intensity_df["is_ISTD"], "FeatureID"].astype(str)
    )
    analyte_ids = feature_ids - istd_ids
    unknown_analytes = sorted(
        set(mapping["Analyte_Feature_ID"]) - analyte_ids
    )
    if unknown_analytes:
        raise ValueError(
            "ISTD_Mapping contains unknown analyte feature IDs: "
            + ", ".join(unknown_analytes)
        )

    unknown_donors = sorted(set(mapping["ISTD_Feature_ID"]) - feature_ids)
    if unknown_donors:
        raise ValueError(
            "ISTD_Mapping contains unknown ISTD feature IDs: "
            + ", ".join(unknown_donors)
        )
    non_istd_donors = sorted(set(mapping["ISTD_Feature_ID"]) - istd_ids)
    if non_istd_donors:
        raise ValueError(
            "ISTD_Mapping donor is not marked as ISTD: "
            + ", ".join(non_istd_donors)
        )

    mapping["Mapping_Type"] = mapping["Mapping_Type"].str.lower()
    invalid_types = sorted(
        set(mapping["Mapping_Type"]) - ALLOWED_MAPPING_TYPES
    )
    if invalid_types:
        raise ValueError(
            "ISTD_Mapping Mapping_Type must be matched or validated_surrogate; "
            "found: "
            + ", ".join(invalid_types)
        )
    return mapping


def _resolve_sample_columns(
    intensity_df: pd.DataFrame,
    sample_info_df: pd.DataFrame,
) -> tuple[list[str], dict[str, pd.Series]]:
    candidate_columns, _ = identify_candidate_sample_columns(
        intensity_df,
        extra_non_sample_columns={
            "is_ISTD",
            "Sample_Type",
            "sample_type",
            *ISTD_PROVENANCE_COLUMNS,
        },
    )
    mapping = build_sample_info_mapping(candidate_columns, sample_info_df)
    sample_columns = [
        column for column in candidate_columns if column in mapping
    ]
    unmatched = [
        column for column in candidate_columns if column not in mapping
    ]
    if not sample_columns:
        raise ValueError("No intensity columns can be aligned to SampleInfo")
    if unmatched:
        raise ValueError(
            "Intensity columns cannot be aligned to SampleInfo: "
            + ", ".join(map(str, unmatched[:10]))
        )
    return sample_columns, mapping


def _positive_numeric(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return np.where(np.isfinite(numeric) & (numeric > 0), numeric, np.nan)


def build_istd_monitoring_table(
    intensity_df: pd.DataFrame,
    sample_info_df: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize area stability without modifying analyte intensities."""

    if "is_ISTD" not in intensity_df.columns:
        raise ValueError("ISTD monitoring requires an is_ISTD column")
    istd_rows = intensity_df.loc[intensity_df["is_ISTD"]].copy()
    sample_columns, sample_mapping = _resolve_sample_columns(
        intensity_df,
        sample_info_df,
    )
    qc_columns = [
        sample
        for sample in sample_columns
        if normalize_sample_type(
            sample_mapping[sample].get("Sample_Type", "")
        )
        == "QC"
    ]
    orders = pd.Series(
        {
            sample: pd.to_numeric(
                sample_mapping[sample].get("Injection_Order", np.nan),
                errors="coerce",
            )
            for sample in sample_columns
        }
    )
    if orders.notna().all():
        order_status = "available"
    elif orders.notna().any():
        order_status = "incomplete"
    else:
        order_status = "not_available"

    rows = []
    for _, istd_row in istd_rows.iterrows():
        all_values = _positive_numeric(istd_row[sample_columns])
        qc_values = _positive_numeric(istd_row[qc_columns])
        valid_mask = np.isfinite(all_values)
        qc_valid_mask = np.isfinite(qc_values)
        qc_cv = safe_cv_percent(qc_values, min_samples=2)

        order_values = orders.reindex(sample_columns).to_numpy(dtype=float)
        order_mask = valid_mask & np.isfinite(order_values)
        area_order_rho = float("nan")
        area_order_pvalue = float("nan")
        if order_status == "available" and order_mask.sum() >= 3:
            correlation = spearmanr(
                order_values[order_mask],
                all_values[order_mask],
            )
            area_order_rho = float(correlation.statistic)
            area_order_pvalue = float(correlation.pvalue)

        alarms = []
        if (~valid_mask).any():
            alarms.append("missing_area")
        if order_status != "available":
            alarms.append(f"order_{order_status}")
        if qc_valid_mask.sum() < 2:
            qc_status = "insufficient_qc"
            alarms.append("insufficient_qc")
        elif np.isfinite(qc_cv) and qc_cv < CV_QUALITY_THRESHOLDS["excellent"]:
            qc_status = "stable"
        else:
            qc_status = "unstable"
            alarms.append("qc_cv_high")
        if np.isfinite(area_order_rho) and abs(area_order_rho) >= 0.70:
            alarms.append("strong_area_order_association")

        rows.append(
            {
                "FeatureID": str(istd_row["FeatureID"]),
                "Valid_Count": int(valid_mask.sum()),
                "Missing_Count": int((~valid_mask).sum()),
                "QC_Valid_Count": int(qc_valid_mask.sum()),
                "QC_Missing_Count": int((~qc_valid_mask).sum()),
                "QC_CV%": float(qc_cv),
                "QC_Status": qc_status,
                "Area_Order_Spearman": area_order_rho,
                "Area_Order_pvalue": area_order_pvalue,
                "Order_Status": order_status,
                "RT_Status": "not_available_from_current_matrix",
                "Alarm_Codes": ";".join(alarms),
            }
        )
    return pd.DataFrame(rows)


def calculate_selective_istd_correction(
    intensity_df: pd.DataFrame,
    sample_info_df: pd.DataFrame,
    *,
    mapping_df: pd.DataFrame | None,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Apply only explicit, stable feature-to-ISTD mappings."""

    if intensity_df is None or intensity_df.empty:
        raise ValueError("ISTD correction input is empty")
    if sample_info_df is None or sample_info_df.empty:
        raise ValueError("SampleInfo is empty")

    mapping = validate_istd_mapping(mapping_df, intensity_df)
    sample_columns, _ = _resolve_sample_columns(intensity_df, sample_info_df)
    monitoring = build_istd_monitoring_table(intensity_df, sample_info_df)
    monitoring_by_id = monitoring.set_index("FeatureID")
    istd_by_id = intensity_df.loc[intensity_df["is_ISTD"]].set_index("FeatureID")
    analytes = intensity_df.loc[
        ~intensity_df["is_ISTD"]
        & intensity_df["FeatureID"].astype(str).str.lower().ne("sample_type")
    ]
    mapping_by_analyte = (
        mapping.set_index("Analyte_Feature_ID")
        if not mapping.empty
        else pd.DataFrame(columns=ISTD_MAPPING_COLUMNS).set_index(
            "Analyte_Feature_ID"
        )
    )

    results = []
    status_counts: Counter[str] = Counter()
    for _, analyte_row in analytes.iterrows():
        analyte_id = str(analyte_row["FeatureID"])
        raw_values = pd.to_numeric(
            analyte_row[sample_columns],
            errors="coerce",
        ).to_numpy(dtype=float)
        output_values = raw_values.copy()
        mapped_istd = ""
        mapping_type = "none"
        validation_reference = ""
        correction_status = "uncorrected_no_mapping"
        correction_reason = "no_explicit_mapping"
        donor_rt = float("nan")
        donor_median = float("nan")

        if analyte_id in mapping_by_analyte.index:
            mapping_row = mapping_by_analyte.loc[analyte_id]
            mapped_istd = str(mapping_row["ISTD_Feature_ID"])
            mapping_type = str(mapping_row["Mapping_Type"])
            validation_reference = str(mapping_row["Validation_Reference"])
            donor_row = istd_by_id.loc[mapped_istd]
            donor_rt = float(pd.to_numeric(donor_row.get("rt"), errors="coerce"))
            donor_values = _positive_numeric(donor_row[sample_columns])
            donor_median = float(np.nanmedian(donor_values))
            donor_status = monitoring_by_id.loc[mapped_istd, "QC_Status"]

            if not validation_reference:
                correction_status = (
                    "uncorrected_rejected_surrogate"
                    if mapping_type == "validated_surrogate"
                    else "uncorrected_missing_validation_reference"
                )
                correction_reason = "missing_validation_reference"
            elif donor_status != "stable":
                correction_status = "uncorrected_unstable_istd"
                correction_reason = f"donor_qc_status_{donor_status}"
            else:
                required_donor_mask = np.isfinite(raw_values)
                donor_complete = np.all(
                    (~required_donor_mask) | np.isfinite(donor_values)
                )
                if not donor_complete or not np.isfinite(donor_median):
                    correction_status = "uncorrected_incomplete_istd"
                    correction_reason = "donor_missing_where_analyte_observed"
                else:
                    output_values[required_donor_mask] = (
                        raw_values[required_donor_mask]
                        / donor_values[required_donor_mask]
                        * donor_median
                    )
                    correction_status = (
                        "corrected_matched_istd"
                        if mapping_type == "matched"
                        else "corrected_validated_surrogate"
                    )
                    correction_reason = "explicit_mapping_accepted"

        analyte_rt = float(
            pd.to_numeric(analyte_row.get("rt"), errors="coerce")
        )
        result_row = {
            "FeatureID": analyte_id,
            "RT": analyte_rt,
            "ISTD": mapped_istd,
            "ISTD_RT": donor_rt,
            "RT_Difference": (
                analyte_rt - donor_rt
                if np.isfinite(analyte_rt) and np.isfinite(donor_rt)
                else float("nan")
            ),
            "ISTD_Median": donor_median,
            "Mapped_ISTD": mapped_istd,
            "Mapping_Type": mapping_type,
            "Validation_Reference": validation_reference,
            "ISTD_Correction_Status": correction_status,
            "ISTD_Correction_Reason": correction_reason,
        }
        result_row.update(dict(zip(sample_columns, output_values)))
        results.append(result_row)
        status_counts[correction_status] += 1

    results_df = pd.DataFrame(results)
    corrected_features = int(
        sum(
            count
            for status, count in status_counts.items()
            if status.startswith("corrected_")
        )
    )
    return results_df, sample_columns, {
        "istd_mode": (
            "selective_correction"
            if corrected_features > 0
            else "monitoring_only"
        ),
        "corrected_features": corrected_features,
        "uncorrected_features": int(len(results_df) - corrected_features),
        "mapping_rows": int(len(mapping)),
        "status_counts": dict(status_counts),
        "monitored_istds": int(len(monitoring)),
    }
