"""Design-identifiability diagnostics for correction and downstream handoff."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from metabolomics.utils.constants import SHEET_NAMES
from metabolomics.utils.sample_classification import (
    SampleInfoIndex,
    normalize_sample_type,
    parse_batch_labels,
)


STRONG_ORDER_ASSOCIATION_ETA_SQUARED = 0.70


class DesignStatus(str, Enum):
    """Evidence status for one proposed interpretation or correction scope."""

    SUPPORTED = "supported"
    ASSUMPTION_DEPENDENT = "assumption_dependent"
    NON_IDENTIFIABLE = "non_identifiable"


@dataclass(frozen=True)
class DesignIdentifiabilityReceipt:
    """Machine-readable design diagnostics plus workbook-ready detail tables."""

    summary: dict[str, Any]
    reasons: tuple[str, ...]
    batch_sample_counts: pd.DataFrame
    qc_coverage: pd.DataFrame
    associations: pd.DataFrame
    design_diagnostics: pd.DataFrame
    contrasts: pd.DataFrame

    def to_processing_extra(self) -> dict[str, Any]:
        """Return a JSON-safe receipt for ``ProcessingResult.extra``."""

        return _json_safe({
            "schema_version": "1.0",
            "diagnostic_only": True,
            "summary": self.summary,
            "reasons": list(self.reasons),
            "batch_sample_counts": self.batch_sample_counts.to_dict("records"),
            "qc_coverage": self.qc_coverage.to_dict("records"),
            "associations": self.associations.to_dict("records"),
            "design_diagnostics": self.design_diagnostics.to_dict("records"),
            "contrasts": self.contrasts.to_dict("records"),
        })

    def to_excel_sheets(self) -> dict[str, pd.DataFrame]:
        """Return one canonical long-form workbook receipt."""

        frames = [
            pd.DataFrame(
                [
                    {
                        "Record_Type": "summary",
                        "Metric": key,
                        "Value": value,
                    }
                    for key, value in self.summary.items()
                ]
            ),
            self.batch_sample_counts.assign(
                Record_Type="batch_sample_count",
                Metric="sample_count",
                Value=lambda frame: frame["Sample_Count"],
            ),
            self.qc_coverage.assign(Record_Type="qc_coverage"),
            self.associations.assign(Record_Type="association"),
            self.design_diagnostics.assign(Record_Type="design_diagnostics"),
            self.contrasts.assign(Record_Type="contrast"),
        ]
        if self.reasons:
            frames.append(
                pd.DataFrame(
                    [
                        {
                            "Record_Type": "reason",
                            "Metric": f"reason_{index}",
                            "Value": reason,
                        }
                        for index, reason in enumerate(self.reasons, start=1)
                    ]
                )
            )
        return {
            SHEET_NAMES["design_identifiability"]: pd.concat(
                frames,
                ignore_index=True,
                sort=False,
            )
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, np.generic):
        value = value.item()
    if value is pd.NA or value is None:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _eta_squared(labels: pd.Series, values: pd.Series) -> float:
    frame = pd.DataFrame({"label": labels, "value": values}).dropna()
    if frame.empty or frame["label"].nunique() < 2:
        return float("nan")
    total_mean = frame["value"].mean()
    total_ss = float(((frame["value"] - total_mean) ** 2).sum())
    if total_ss <= 0:
        return 0.0
    between_ss = sum(
        len(group) * float((group["value"].mean() - total_mean) ** 2)
        for _, group in frame.groupby("label", sort=False)
    )
    return float(np.clip(between_ss / total_ss, 0.0, 1.0))


def _cramers_v(left: pd.Series, right: pd.Series) -> float:
    table = pd.crosstab(left, right)
    if table.empty or min(table.shape) < 2:
        return float("nan")
    chi2 = float(chi2_contingency(table, correction=False)[0])
    observations = float(table.to_numpy().sum())
    denominator = observations * min(table.shape[0] - 1, table.shape[1] - 1)
    if denominator <= 0:
        return float("nan")
    return float(np.sqrt(chi2 / denominator))


def _normalize_and_validate(
    sample_info_df: pd.DataFrame,
    sample_columns: list[str] | tuple[str, ...] | None,
) -> pd.DataFrame:
    required = {"Sample_Name", "Sample_Type", "Batch"}
    missing = sorted(required - set(sample_info_df.columns))
    if missing:
        raise ValueError(
            "Design identifiability requires SampleInfo columns: "
            + ", ".join(sorted(required))
            + f"; missing: {', '.join(missing)}"
        )

    frame = sample_info_df.copy()
    if sample_columns is not None:
        index = SampleInfoIndex(frame)
        mapped = index.map_rows(sample_columns)
        missing_samples = [sample for sample in sample_columns if sample not in mapped]
        if missing_samples:
            raise ValueError(
                "Design identifiability could not map matrix samples to SampleInfo: "
                + ", ".join(map(str, missing_samples[:10]))
            )
        frame = pd.DataFrame(
            [mapped[sample].to_dict() for sample in sample_columns]
        )

    frame["Sample_Name"] = frame["Sample_Name"].astype("string").str.strip()

    def preserve_unknown_subtype(value: object) -> str:
        if pd.isna(value):
            return ""
        raw = str(value).strip()
        normalized = normalize_sample_type(raw)
        if normalized == "Unknown" and raw.upper() != "UNKNOWN":
            return raw
        return normalized

    frame["Sample_Type"] = frame["Sample_Type"].map(preserve_unknown_subtype)
    frame["Batch"] = frame["Batch"].astype("string").str.strip()
    if "Injection_Order" not in frame.columns:
        frame["Injection_Order"] = np.nan
    frame["Injection_Order"] = pd.to_numeric(
        frame["Injection_Order"],
        errors="coerce",
    )

    invalid_name = frame["Sample_Name"].isna() | frame["Sample_Name"].eq("")
    invalid_type = frame["Sample_Type"].astype("string").str.strip().eq("")
    invalid_batch = frame["Batch"].isna() | frame["Batch"].eq("")
    if invalid_name.any() or invalid_type.any() or invalid_batch.any():
        raise ValueError(
            "Design identifiability requires non-empty Sample_Name, Sample_Type, "
            "and Batch for every sample"
        )
    if frame["Sample_Name"].duplicated().any():
        raise ValueError("Design identifiability requires unique Sample_Name values")
    finite_order = np.isfinite(frame["Injection_Order"])
    order_available = bool(finite_order.all())
    frame.attrs["injection_order_available"] = order_available
    frame.attrs["injection_order_reason"] = (
        ""
        if order_available
        else "Injection_Order is missing or non-numeric"
    )
    return frame


def _build_qc_coverage(
    frame: pd.DataFrame,
    order_available: bool,
) -> pd.DataFrame:
    rows = []
    for batch, batch_frame in frame.groupby("Batch", sort=True):
        qc_frame = batch_frame.loc[batch_frame["Sample_Type"].eq("QC")]
        study_frame = batch_frame.loc[
            ~batch_frame["Sample_Type"].isin({"QC", "Blank"})
        ]
        study_min = (
            float(study_frame["Injection_Order"].min())
            if order_available and not study_frame.empty
            else float("nan")
        )
        study_max = (
            float(study_frame["Injection_Order"].max())
            if order_available and not study_frame.empty
            else float("nan")
        )
        first_qc = (
            float(qc_frame["Injection_Order"].min())
            if order_available and not qc_frame.empty
            else float("nan")
        )
        last_qc = (
            float(qc_frame["Injection_Order"].max())
            if order_available and not qc_frame.empty
            else float("nan")
        )
        endpoint_covered = bool(
            order_available
            and not qc_frame.empty
            and not study_frame.empty
            and first_qc <= study_min
            and last_qc >= study_max
        )
        qc_count = int(len(qc_frame))
        if qc_count >= 6 and endpoint_covered:
            status = DesignStatus.SUPPORTED.value
        elif qc_count > 0:
            status = DesignStatus.ASSUMPTION_DEPENDENT.value
        else:
            status = DesignStatus.NON_IDENTIFIABLE.value
        rows.append(
            {
                "Batch": str(batch),
                "QC_Count": qc_count,
                "Study_First_Order": study_min,
                "Study_Last_Order": study_max,
                "First_QC_Order": first_qc,
                "Last_QC_Order": last_qc,
                "Endpoint_Covered": endpoint_covered,
                "Within_Batch_Drift_Status": status,
            }
        )
    return pd.DataFrame(rows)


def _expand_batch_memberships(frame: pd.DataFrame) -> pd.DataFrame:
    """Expand typed multi-batch QC membership without duplicating study samples."""

    rows = []
    for _, row in frame.iterrows():
        labels = parse_batch_labels(row["Batch"])
        if not labels:
            raise ValueError("Design identifiability requires a valid Batch label")
        if row["Sample_Type"] != "QC" and len(labels) != 1:
            raise ValueError(
                "Only QC samples may declare multiple Batch memberships"
            )
        for label in labels:
            expanded = row.to_dict()
            expanded["Batch"] = label
            rows.append(expanded)
    expanded_frame = pd.DataFrame(rows)
    expanded_frame.attrs.update(frame.attrs)
    if (
        expanded_frame.attrs["injection_order_available"]
        and expanded_frame.duplicated(["Batch", "Injection_Order"]).any()
    ):
        expanded_frame.attrs["injection_order_available"] = False
        expanded_frame.attrs["injection_order_reason"] = (
            "Injection_Order is duplicated within at least one batch"
        )
    return expanded_frame


def _build_design_diagnostics(
    study: pd.DataFrame,
    order_available: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    batch_levels = sorted(study["Batch"].unique())
    type_levels = sorted(study["Sample_Type"].unique())
    batch_dummy = pd.get_dummies(
        study["Batch"],
        prefix="Batch",
        drop_first=True,
        dtype=float,
    )
    type_dummy = pd.get_dummies(
        study["Sample_Type"],
        prefix="SampleType",
        drop_first=True,
        dtype=float,
    )
    design = pd.DataFrame({"Intercept": np.ones(len(study))}, index=study.index)
    design = pd.concat([design, batch_dummy, type_dummy], axis=1)
    if order_available:
        order = study["Injection_Order"].astype(float)
        order_std = float(order.std(ddof=0))
        design["Injection_Order_z"] = (
            (order - float(order.mean())) / order_std
            if order_std > 0
            else 0.0
        )
    for batch_column in batch_dummy.columns:
        for type_column in type_dummy.columns:
            design[f"{batch_column}:{type_column}"] = (
                batch_dummy[batch_column] * type_dummy[type_column]
            )

    matrix = design.to_numpy(dtype=float)
    rank = int(np.linalg.matrix_rank(matrix))
    column_count = int(matrix.shape[1])
    condition_number = (
        float(np.linalg.cond(matrix))
        if matrix.size
        else float("nan")
    )
    leverage = (
        np.diag(matrix @ np.linalg.pinv(matrix))
        if matrix.size
        else np.asarray([], dtype=float)
    )

    counts = (
        study.groupby(["Batch", "Sample_Type"], observed=True)
        .size()
        .reindex(
            pd.MultiIndex.from_product(
                [batch_levels, type_levels],
                names=["Batch", "Sample_Type"],
            ),
            fill_value=0,
        )
    )
    empty_cells = int((counts == 0).sum())
    full_rank = bool(rank == column_count)
    interaction_estimable = bool(full_rank and empty_cells == 0)
    details = pd.DataFrame(
        [
            {"Metric": "Study_Sample_Count", "Value": int(len(study))},
            {"Metric": "Design_Column_Count", "Value": column_count},
            {"Metric": "Design_Rank", "Value": rank},
            {"Metric": "Full_Rank", "Value": full_rank},
            {"Metric": "Condition_Number", "Value": condition_number},
            {"Metric": "Empty_Batch_Sample_Type_Cells", "Value": empty_cells},
            {
                "Metric": "Max_Leverage",
                "Value": float(np.max(leverage)) if leverage.size else float("nan"),
            },
            {"Metric": "Interaction_Estimable", "Value": interaction_estimable},
        ]
    )
    return details, {
        "design_rank": rank,
        "design_column_count": column_count,
        "design_full_rank": full_rank,
        "design_condition_number": condition_number,
        "empty_batch_sample_type_cells": empty_cells,
        "max_leverage": (
            float(np.max(leverage)) if leverage.size else float("nan")
        ),
        "interaction_estimable": interaction_estimable,
    }


def _build_contrasts(
    study: pd.DataFrame,
    *,
    order_available: bool,
) -> pd.DataFrame:
    columns = [
        "Left_Sample_Type",
        "Right_Sample_Type",
        "Supporting_Batches",
        "Supporting_Batch_Count",
        "Total_Batch_Count",
        "Order_Eta_Squared",
        "Status",
        "Universal_Cross_Batch_Effect",
        "Reason",
    ]
    batch_levels = sorted(study["Batch"].unique())
    sample_types = sorted(study["Sample_Type"].unique())
    rows = []
    for left, right in combinations(sample_types, 2):
        pair_frame = study.loc[study["Sample_Type"].isin({left, right})]
        pair_order_eta = (
            _eta_squared(
                pair_frame["Sample_Type"],
                pair_frame["Injection_Order"],
            )
            if order_available
            else float("nan")
        )
        strong_pair_order_association = bool(
            np.isfinite(pair_order_eta)
            and pair_order_eta >= STRONG_ORDER_ASSOCIATION_ETA_SQUARED
        )
        supporting_batches = []
        for batch, batch_frame in study.groupby("Batch", sort=True):
            present = set(batch_frame["Sample_Type"])
            if left in present and right in present:
                supporting_batches.append(str(batch))
        support_count = len(supporting_batches)
        if support_count == len(batch_levels):
            status = DesignStatus.SUPPORTED
            reason = "Both sample types have within-batch support in every batch"
        elif support_count > 0:
            status = DesignStatus.ASSUMPTION_DEPENDENT
            reason = (
                "Within-batch support exists only in a subset of batches; "
                "do not promote it to a universal cross-batch effect"
            )
        else:
            status = DesignStatus.NON_IDENTIFIABLE
            reason = "The sample types never coexist within a batch"
        if status is DesignStatus.SUPPORTED and strong_pair_order_association:
            status = DesignStatus.ASSUMPTION_DEPENDENT
            reason = (
                "Both sample types are observed, but Sample_Type is strongly "
                "associated with Injection_Order"
            )
        rows.append(
            {
                "Left_Sample_Type": left,
                "Right_Sample_Type": right,
                "Supporting_Batches": ",".join(supporting_batches),
                "Supporting_Batch_Count": support_count,
                "Total_Batch_Count": len(batch_levels),
                "Order_Eta_Squared": pair_order_eta,
                "Status": status.value,
                "Universal_Cross_Batch_Effect": bool(
                    status is DesignStatus.SUPPORTED
                ),
                "Reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _optional_metadata_summary(
    frame: pd.DataFrame,
    study: pd.DataFrame,
) -> dict[str, Any]:
    pair_status = "not_available"
    complete_pairs = 0
    if "Pair_ID" in study.columns:
        pair_rows = study.dropna(subset=["Pair_ID"]).copy()
        pair_rows["Pair_ID"] = pair_rows["Pair_ID"].astype("string").str.strip()
        pair_rows = pair_rows.loc[pair_rows["Pair_ID"].ne("")]
        if not pair_rows.empty:
            pair_status = "available"
            complete_pairs = int(
                (
                    pair_rows.groupby("Pair_ID")["Sample_Type"].nunique()
                    >= 2
                ).sum()
            )

    bridge_status = "not_available"
    cross_batch_bridges = 0
    batch_levels = set(frame["Batch"].astype(str))
    bridge_graph = {batch: set() for batch in batch_levels}
    bridged_batches: set[str] = set()
    if "Bridge_ID" in study.columns:
        bridge_rows = study.dropna(subset=["Bridge_ID"]).copy()
        bridge_rows["Bridge_ID"] = (
            bridge_rows["Bridge_ID"].astype("string").str.strip()
        )
        bridge_rows = bridge_rows.loc[bridge_rows["Bridge_ID"].ne("")]
        if not bridge_rows.empty:
            bridge_status = "available"
            for _, bridge_group in bridge_rows.groupby("Bridge_ID"):
                bridge_batches = set(bridge_group["Batch"].astype(str))
                if len(bridge_batches) < 2:
                    continue
                cross_batch_bridges += 1
                bridged_batches.update(bridge_batches)
                for batch in bridge_batches:
                    bridge_graph[batch].update(bridge_batches - {batch})

    unseen = set(batch_levels)
    bridge_components = 0
    while unseen:
        bridge_components += 1
        stack = [unseen.pop()]
        while stack:
            current = stack.pop()
            neighbours = bridge_graph[current] & unseen
            unseen.difference_update(neighbours)
            stack.extend(neighbours)
    bridge_coverage_complete = bool(
        len(batch_levels) <= 1
        or (
            bridged_batches == batch_levels
            and bridge_components == 1
        )
    )

    pool_comparability = "unknown"
    qc_rows = frame.loc[frame["Sample_Type"].eq("QC")]
    if "QC_Pool_ID" in qc_rows.columns:
        declared = qc_rows.dropna(subset=["QC_Pool_ID"]).copy()
        declared["QC_Pool_ID"] = (
            declared["QC_Pool_ID"].astype("string").str.strip()
        )
        declared = declared.loc[declared["QC_Pool_ID"].ne("")]
        batch_count = int(frame["Batch"].nunique())
        if not declared.empty and declared["Batch"].nunique() == batch_count:
            pool_sets = declared.groupby("Batch")["QC_Pool_ID"].agg(
                lambda values: tuple(sorted(set(values)))
            )
            pool_comparability = (
                "comparable"
                if pool_sets.nunique() == 1
                else "non_comparable"
            )

    return {
        "pair_metadata_status": pair_status,
        "complete_cross_type_pair_count": complete_pairs,
        "bridge_metadata_status": bridge_status,
        "cross_batch_bridge_count": cross_batch_bridges,
        "bridged_batch_count": len(bridged_batches),
        "bridge_component_count": bridge_components,
        "bridge_coverage_complete": bridge_coverage_complete,
        "qc_pool_comparability": pool_comparability,
    }


def build_design_identifiability_receipt(
    sample_info_df: pd.DataFrame,
    sample_columns: list[str] | tuple[str, ...] | None = None,
) -> DesignIdentifiabilityReceipt:
    """Assess which biological and technical contrasts the design can support."""

    source_frame = _normalize_and_validate(sample_info_df, sample_columns)
    frame = _expand_batch_memberships(source_frame)
    order_available = bool(frame.attrs["injection_order_available"])
    order_reason = str(frame.attrs["injection_order_reason"])
    study = frame.loc[
        ~frame["Sample_Type"].isin({"QC", "Blank"})
    ].copy()
    if study.empty:
        raise ValueError("Design identifiability requires at least one non-QC sample")

    counts = (
        frame.groupby(["Batch", "Sample_Type"], observed=True)
        .size()
        .rename("Sample_Count")
        .reset_index()
    )
    qc_coverage = _build_qc_coverage(frame, order_available)
    design_diagnostics, design_summary = _build_design_diagnostics(
        study,
        order_available,
    )
    optional = _optional_metadata_summary(frame, study)

    sample_type_order_eta = (
        _eta_squared(study["Sample_Type"], study["Injection_Order"])
        if order_available
        else float("nan")
    )
    batch_order_eta = (
        _eta_squared(study["Batch"], study["Injection_Order"])
        if order_available
        else float("nan")
    )
    sample_type_batch_v = _cramers_v(study["Sample_Type"], study["Batch"])
    strong_order_association = bool(
        np.isfinite(sample_type_order_eta)
        and sample_type_order_eta >= STRONG_ORDER_ASSOCIATION_ETA_SQUARED
    )
    contrasts = _build_contrasts(
        study,
        order_available=order_available,
    )
    associations = pd.DataFrame(
        [
            {
                "Left": "Sample_Type",
                "Right": "Injection_Order",
                "Method": "eta_squared",
                "Scope": "study_samples",
                "Value": sample_type_order_eta,
            },
            {
                "Left": "Batch",
                "Right": "Injection_Order",
                "Method": "eta_squared",
                "Scope": "study_samples",
                "Value": batch_order_eta,
            },
            {
                "Left": "Sample_Type",
                "Right": "Batch",
                "Method": "cramers_v",
                "Scope": "study_samples",
                "Value": sample_type_batch_v,
            },
        ]
    )

    qc_statuses = set(qc_coverage["Within_Batch_Drift_Status"])
    if qc_statuses == {DesignStatus.SUPPORTED.value}:
        within_batch_status = DesignStatus.SUPPORTED
    elif DesignStatus.SUPPORTED.value in qc_statuses:
        within_batch_status = DesignStatus.ASSUMPTION_DEPENDENT
    elif qc_statuses == {DesignStatus.NON_IDENTIFIABLE.value}:
        within_batch_status = DesignStatus.NON_IDENTIFIABLE
    else:
        within_batch_status = DesignStatus.ASSUMPTION_DEPENDENT

    batch_count = int(frame["Batch"].nunique())
    if batch_count == 1:
        cross_batch_status = DesignStatus.SUPPORTED
    elif optional["bridge_coverage_complete"]:
        cross_batch_status = DesignStatus.SUPPORTED
    elif optional["qc_pool_comparability"] == "comparable":
        cross_batch_status = DesignStatus.ASSUMPTION_DEPENDENT
    else:
        cross_batch_status = DesignStatus.NON_IDENTIFIABLE

    reasons = []
    if not order_available:
        reasons.append(order_reason)
    if not design_summary["interaction_estimable"]:
        reasons.append(
            "Batch × Sample_Type interaction is not estimable from the observed support"
        )
    if sample_type_order_eta >= STRONG_ORDER_ASSOCIATION_ETA_SQUARED:
        reasons.append(
            "Sample_Type is strongly associated with Injection_Order"
        )
    if within_batch_status is not DesignStatus.SUPPORTED:
        reasons.append(
            "At least one batch lacks sufficient endpoint-covered QC support"
        )
    if cross_batch_status is not DesignStatus.SUPPORTED:
        reasons.append(
            "Cross-batch level alignment lacks a repeated same-sample bridge"
        )
    if optional["qc_pool_comparability"] == "non_comparable":
        reasons.append(
            "Declared pooled-QC composition differs across batches"
        )

    if not order_available or not design_summary["interaction_estimable"] or (
        not contrasts.empty
        and contrasts["Status"].eq(DesignStatus.NON_IDENTIFIABLE.value).all()
    ):
        overall_status = DesignStatus.NON_IDENTIFIABLE
    elif (
        within_batch_status is not DesignStatus.SUPPORTED
        or cross_batch_status is not DesignStatus.SUPPORTED
        or strong_order_association
        or (
            not contrasts.empty
            and not contrasts["Status"].eq(DesignStatus.SUPPORTED.value).all()
        )
    ):
        overall_status = DesignStatus.ASSUMPTION_DEPENDENT
    else:
        overall_status = DesignStatus.SUPPORTED

    summary = {
        "overall_status": overall_status.value,
        "sample_count": int(len(source_frame)),
        "study_sample_count": int(len(study)),
        "batch_count": batch_count,
        "sample_type_count": int(study["Sample_Type"].nunique()),
        "injection_order_status": (
            "available" if order_available else "unavailable"
        ),
        "sample_type_order_eta_squared": sample_type_order_eta,
        "batch_order_eta_squared": batch_order_eta,
        "sample_type_batch_cramers_v": sample_type_batch_v,
        "within_batch_qc_drift_status": within_batch_status.value,
        "cross_batch_level_alignment_status": cross_batch_status.value,
        **design_summary,
        **optional,
    }
    return DesignIdentifiabilityReceipt(
        summary=summary,
        reasons=tuple(reasons),
        batch_sample_counts=counts,
        qc_coverage=qc_coverage,
        associations=associations,
        design_diagnostics=design_diagnostics,
        contrasts=contrasts,
    )
