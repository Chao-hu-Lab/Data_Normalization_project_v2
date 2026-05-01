import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import os
import re
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows
from datetime import datetime
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde, spearmanr, wilcoxon

from metabolomics.utils.plotting import setup_matplotlib
from metabolomics.utils.constants import (
    SHEET_NAMES,
    DATETIME_FORMAT_FULL,
    VALIDATION_THRESHOLDS,
    COHENS_D_THRESHOLDS,
    CV_QUALITY_THRESHOLDS,
    NON_SAMPLE_COLUMNS,
    is_non_sample_column,
    resolve_sheet_name,
)
from metabolomics.utils.sample_classification import (
    build_sample_info_mapping as shared_build_sample_info_mapping,
    identify_candidate_sample_columns,
    normalize_sample_name,
)
from metabolomics.utils.file_io import (
    build_plots_dir,
    get_output_root,
    generate_output_filename,
    resolve_session_dir,
)
from metabolomics.utils.data_helpers import apply_feature_metadata_passthrough
from metabolomics.utils.results import ProcessingResult
from metabolomics.utils.console import safe_print as print

warnings.filterwarnings('ignore')

# ========== Matplotlib Global Settings ==========
# Use centralized setup
setup_matplotlib()

METHOD_ALIASES = {
    'PQN': 'PQN',
    'SPECNORM+PQN': 'SpecNorm_PQN',
    'SPECNORM_PQN': 'SpecNorm_PQN',
    'SPECNORM PQN': 'SpecNorm_PQN',
}

NORMALIZATION_SUMMARY_SHEETS = {
    'PQN': 'PQN_summary',
    'SpecNorm_PQN': 'SpecNorm_PQN_summary',
}
SUMMARY_REPORT_SEPARATOR = "-" * 80

# Unified color scheme for sample type grouping across all plots
SAMPLE_TYPE_COLORS = {
    'CONTROL': '#3498DB',
    'EXPOSURE': '#E74C3C',
    'QC': '#F39C12',
    'UNKNOWN': '#95A5A6',
}


def canonicalize_normalization_method(method_name):
    """Normalize user-facing and legacy method names to internal names."""
    if method_name is None:
        return 'PQN'
    raw_method = str(method_name).strip()
    key = raw_method.upper().replace('-', '_')
    key = " ".join(key.split())
    return METHOD_ALIASES.get(key, raw_method)


def get_summary_sheet_name(method_name):
    """Return the Step 3 summary sheet name for the selected method."""
    canonical_method = canonicalize_normalization_method(method_name)
    return NORMALIZATION_SUMMARY_SHEETS.get(canonical_method, f"{canonical_method}_summary")

def _lookup_sample_type(sample, sample_info_df, col_to_info_row=None, default='UNKNOWN'):
    """Helper: look up sample type using col_to_info_row mapping or fallback."""
    if col_to_info_row and sample in col_to_info_row:
        return str(col_to_info_row[sample].get('Sample_Type', default)).upper()
    # Direct lookup fallback
    rows = sample_info_df[sample_info_df.iloc[:, 0] == sample]
    if not rows.empty:
        return str(rows.iloc[0].get('Sample_Type', default)).upper()
    # Normalized-name fallback for common cross-tool naming differences
    norm_sample = normalize_sample_name(sample)
    if norm_sample:
        norm_rows = sample_info_df[
            sample_info_df.iloc[:, 0].map(normalize_sample_name) == norm_sample
        ]
        if not norm_rows.empty:
            return str(norm_rows.iloc[0].get('Sample_Type', default)).upper()
    # Column-name keyword fallback
    s_upper = str(sample).upper()
    if any(kw in s_upper for kw in ['QC', 'POOLED']):
        return 'QC'
    return default.upper()


def build_sample_info_mapping(sample_columns, sample_info_df):
    """Compatibility wrapper for shared SampleInfo mapping logic."""
    return shared_build_sample_info_mapping(sample_columns, sample_info_df)

# ==================== 標準化方法 ====================

def _lookup_sample_info_row(sample, sample_info_df, col_to_info_row=None):
    """Look up a SampleInfo row using mapping, exact name, then normalized name."""
    if col_to_info_row and sample in col_to_info_row:
        return col_to_info_row[sample]

    sample_name_col = sample_info_df.columns[0]
    exact_rows = sample_info_df[sample_info_df[sample_name_col] == sample]
    if not exact_rows.empty:
        return exact_rows.iloc[0]

    norm_sample = normalize_sample_name(sample)
    if not norm_sample:
        return None

    normalized_rows = sample_info_df[
        sample_info_df[sample_name_col].map(normalize_sample_name) == norm_sample
    ]
    if normalized_rows.empty:
        return None
    return normalized_rows.iloc[0]

def _parse_batch_labels(value):
    """Parse batch labels from SampleInfo while tolerating simple delimiters."""
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    normalized = (
        text.replace("|", ",")
        .replace("/", ",")
        .replace(";", ",")
        .replace("+", ",")
    )
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _find_batch_column(sample_info_df):
    """Return the Batch column name or raise when Step 3 batch metadata is missing."""
    for col in sample_info_df.columns:
        if "batch" in str(col).strip().lower():
            return col
    raise ValueError(
        "SampleInfo must include a Batch column for Step 3 reference selection."
    )


def _derive_qc_name_family(sample_name):
    """Derive a conservative QC material family key from sample naming."""
    normalized_name = normalize_sample_name(sample_name)
    if not normalized_name:
        return None
    if "qc" not in normalized_name and "pool" not in normalized_name:
        return None
    family = re.sub(r"\d+$", "", normalized_name)
    return family or normalized_name


def _infer_shared_qc_from_names(qc_samples, sample_batches, expected_batches):
    """Prove shared QC only when each batch exposes at least one common QC name family."""
    if not expected_batches:
        return False, []

    batch_to_families = {batch: set() for batch in expected_batches}
    for sample in qc_samples:
        family = _derive_qc_name_family(sample)
        if family is None:
            continue
        for batch in sample_batches.get(sample, ()):
            if batch in batch_to_families:
                batch_to_families[batch].add(family)

    if any(not families for families in batch_to_families.values()):
        return False, []

    shared_families = set.intersection(*batch_to_families.values())
    return bool(shared_families), sorted(shared_families)


def _analyze_batch_design(sample_columns, sample_info_df, col_to_info_row=None):
    """Infer batch count and whether QC is shared across batches."""
    batch_col = _find_batch_column(sample_info_df)
    sample_batches = {}
    for sample in sample_columns:
        info_row = _lookup_sample_info_row(
            sample,
            sample_info_df,
            col_to_info_row=col_to_info_row,
        )
        if info_row is None:
            raise ValueError(
                f"Missing SampleInfo row for sample '{sample}' while inferring Step 3 batch design."
            )
        raw_batch = info_row.get(batch_col)
        memberships = _parse_batch_labels(raw_batch)
        if not memberships:
            raise ValueError(
                f"Missing Batch metadata for sample '{sample}' in Step 3 batch-design analysis."
            )
        sample_batches[sample] = tuple(dict.fromkeys(memberships))

    qc_samples = [
        sample for sample in sample_columns
        if _lookup_sample_type(sample, sample_info_df, col_to_info_row, default="UNKNOWN") == "QC"
    ]
    real_samples = [sample for sample in sample_columns if sample not in qc_samples]

    all_batches = sorted({batch for batches in sample_batches.values() for batch in batches})
    qc_batches = sorted({batch for sample in qc_samples for batch in sample_batches.get(sample, ())})
    real_batches = sorted({batch for sample in real_samples for batch in sample_batches.get(sample, ())})
    qc_shared_across_batches, shared_qc_name_families = _infer_shared_qc_from_names(
        qc_samples,
        sample_batches,
        expected_batches=all_batches,
    )
    qc_shared_across_batches = (
        len(all_batches) <= 1
        or qc_shared_across_batches
    )

    return {
        "batch_count": len(all_batches),
        "all_batches": all_batches,
        "qc_batches": qc_batches,
        "real_batches": real_batches,
        "qc_shared_across_batches": qc_shared_across_batches,
        "shared_qc_name_families": shared_qc_name_families,
    }


def _summarize_step2_contract(step2_advanced_stats_df):
    """Summarize Step 2 advanced statistics for Step 3 reference selection."""
    required_columns = {
        "Decision_Status",
        "Valid_QC_Count",
        "Removed_QC_Outliers",
        "Outside_QC_Range_Count",
        "Trend_pvalue",
        "Kendall_Tau",
        "LOESS_R2",
        "LOESS_RMSE",
        "Normalized_RMSE",
    }
    if step2_advanced_stats_df is None or step2_advanced_stats_df.empty:
        return {
            "available": False,
            "missing_columns": sorted(required_columns),
        }

    missing_columns = sorted(required_columns - set(step2_advanced_stats_df.columns))
    if missing_columns:
        return {
            "available": False,
            "missing_columns": missing_columns,
        }

    decision_status = (
        step2_advanced_stats_df["Decision_Status"].fillna("unknown").astype(str).str.strip()
    )
    stable_statuses = {"success", "no_drift_detected"}
    stable_mask = decision_status.isin(stable_statuses)
    normalized_rmse = pd.to_numeric(
        step2_advanced_stats_df["Normalized_RMSE"], errors="coerce"
    )
    tau_values = pd.to_numeric(step2_advanced_stats_df["Kendall_Tau"], errors="coerce").abs()
    trend_pvalues = pd.to_numeric(step2_advanced_stats_df["Trend_pvalue"], errors="coerce")
    valid_qc_counts = pd.to_numeric(step2_advanced_stats_df["Valid_QC_Count"], errors="coerce")
    outside_counts = pd.to_numeric(
        step2_advanced_stats_df["Outside_QC_Range_Count"], errors="coerce"
    )

    stable_ratio = float(stable_mask.mean()) if len(decision_status) else np.nan
    median_normalized_rmse = float(np.nanmedian(normalized_rmse))
    median_abs_tau = float(np.nanmedian(tau_values))
    median_trend_pvalue = float(np.nanmedian(trend_pvalues))
    median_valid_qc_count = float(np.nanmedian(valid_qc_counts))
    valid_outside_counts = outside_counts.dropna()
    edge_extrapolation_ratio = (
        float((valid_outside_counts > 0).mean())
        if not valid_outside_counts.empty
        else np.nan
    )
    qc_stable = bool(
        np.isfinite(stable_ratio)
        and stable_ratio >= 0.7
        and np.isfinite(median_valid_qc_count)
        and median_valid_qc_count >= VALIDATION_THRESHOLDS["min_qc_samples"]
        and np.isfinite(median_normalized_rmse)
        and median_normalized_rmse <= 0.10
        and np.isfinite(median_abs_tau)
        and median_abs_tau <= 0.20
        and np.isfinite(median_trend_pvalue)
        and median_trend_pvalue >= 0.05
        and np.isfinite(edge_extrapolation_ratio)
        and edge_extrapolation_ratio <= 0.25
    )

    return {
        "available": True,
        "missing_columns": [],
        "qc_stable": qc_stable,
        "stable_ratio": stable_ratio,
        "median_normalized_rmse": median_normalized_rmse,
        "median_abs_tau": median_abs_tau,
        "median_trend_pvalue": median_trend_pvalue,
        "median_valid_qc_count": median_valid_qc_count,
        "edge_extrapolation_ratio": edge_extrapolation_ratio,
    }


def enhanced_pqn_normalization(data_matrix, sample_info_df, sample_columns,
                               col_to_info_row=None, step2_advanced_stats_df=None):
    """
    PQN 標準化：優先使用 QC 樣本作為參考

    Parameters:
    -----------
    data_matrix : np.ndarray
        Feature × Sample intensity matrix.
    sample_info_df : pd.DataFrame
        Sample metadata.
    sample_columns : list[str]
        Sample column names matching data_matrix columns.
    col_to_info_row : dict, optional
        Mapping from data column name to SampleInfo row (Series).
        Used when column names don't match SampleInfo names.
    """
    print(f"\n執行 PQN 標準化（樣本數: {len(sample_columns)}）：")

    # ========== Step 1: 分離 QC 和真實樣本 ==========
    sample_types = {}
    for sample in sample_columns:
        info_row = col_to_info_row.get(sample) if col_to_info_row else None
        if info_row is not None:
            sample_type = str(info_row.get('Sample_Type', ''))
            sample_types[sample] = sample_type.upper()
        else:
            # Fallback: try exact match
            sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
            if not sample_row.empty:
                sample_type = str(sample_row.iloc[0].get('Sample_Type', ''))
                sample_types[sample] = sample_type.upper()
            else:
                # Fallback: detect QC from column name keywords
                if any(kw in str(sample).upper() for kw in ['QC', 'POOLED']):
                    sample_types[sample] = 'QC'
                else:
                    sample_types[sample] = 'UNKNOWN'

    qc_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] == 'QC']
    real_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] != 'QC']

    from collections import Counter
    type_counts = Counter(sample_types.values())

    qc_count = len(qc_indices)
    real_count = len(real_indices)
    print(f"  樣本分類: QC={qc_count}, 真實={real_count}")

    # ========== Step 2: 評估 QC 樣本質量 ==========
    qc_cv_median = np.nan
    reference_strategy = 'NONE'
    reference_rationale = ""
    batch_design = _analyze_batch_design(
        sample_columns,
        sample_info_df,
        col_to_info_row=col_to_info_row,
    )
    step2_contract = _summarize_step2_contract(step2_advanced_stats_df)

    if qc_count <= 0:
        raise ValueError(
            "PQN requires QC samples for adductomics mode; all-sample robust median fallback is disabled."
        )

    qc_data = data_matrix[:, qc_indices]
    qc_cv = calculate_rsd(qc_data)
    qc_cv_median = np.nanmedian(qc_cv)
    reference_strategy = 'QC_REFERENCE'
    if not step2_contract['available']:
        reference_rationale = (
            "Step 2 contract unavailable; adductomics policy still uses QC-derived reference and disables all-sample fallback."
        )
    elif batch_design['batch_count'] > 1 and not batch_design['qc_shared_across_batches']:
        reference_rationale = (
            "Multi-batch QC is not proven shared; adductomics policy still uses available QC samples as reference and disables all-sample fallback."
        )
    elif batch_design['batch_count'] > 1:
        reference_rationale = (
            "Multi-batch shared-QC evidence recorded; adductomics policy uses QC-derived reference and disables all-sample fallback."
        )
    elif step2_contract['qc_stable']:
        reference_rationale = (
            "Single-batch design with stable post-LOESS QC uses a QC-derived reference."
        )
    else:
        reference_rationale = (
            "Post-LOESS QC stability is limited; adductomics policy still uses QC-derived reference and disables all-sample fallback."
        )

    # 決定參考譜
    if reference_strategy in ('QC', 'QC_LIMITED', 'QC_REFERENCE'):
        reference_sample = np.nanmedian(data_matrix[:, qc_indices], axis=1)
        print(f"  參考策略: {reference_strategy}（QC median CV%={qc_cv_median:.1f}%）")
    else:
        raise RuntimeError(f"Unsupported PQN reference strategy in adductomics mode: {reference_strategy}")
    if reference_rationale:
        print(f"  參考理由: {reference_rationale}")

    # 對所有樣本計算 quotient 並正規化
    quotients = data_matrix / reference_sample[:, np.newaxis]
    quotients = np.where(np.isfinite(quotients), quotients, np.nan)
    normalization_factors = np.nanmedian(quotients, axis=0)

    final_data = data_matrix / normalization_factors

    # 分別提取 real / QC 的因子用於報告
    normalization_factors_real = normalization_factors[real_indices] if real_count > 0 else np.array([])
    normalization_factors_qc = normalization_factors[qc_indices] if qc_count > 0 else None

    factor_range = f"{np.nanmin(normalization_factors_real):.4f}–{np.nanmax(normalization_factors_real):.4f}" if real_count > 0 else "N/A"
    print(f"  ✓ PQN 完成（因子範圍: {factor_range}）")

    # 返回資訊
    pqn_info = {
        'reference_strategy': reference_strategy,
        'reference_rationale': reference_rationale,
        'qc_count': qc_count,
        'qc_cv': qc_cv_median,
        'real_count': real_count,
        'normalization_factors_real': normalization_factors_real,
        'normalization_factors_qc': normalization_factors_qc,
        'step2_contract_available': step2_contract['available'],
        'step2_contract_missing_columns': step2_contract.get('missing_columns', []),
        'step2_qc_stable': step2_contract.get('qc_stable'),
        'batch_count': batch_design['batch_count'],
        'qc_shared_across_batches': batch_design['qc_shared_across_batches'],
    }

    return final_data, pqn_info


def specnorm_reference_division(data_matrix, sample_info_df, sample_columns,
                                reference_values, col_to_info_row=None,
                                correction_col_name=None):
    """
    SpecNorm reference division.

    以每個樣本附帶的參考量值（如肌酐濃度、DNA 質量、蛋白質濃度等）
    做除法。僅校正真實樣本；QC 樣本保留原值。

    Parameters:
    -----------
    data_matrix : np.ndarray
        Feature × Sample intensity matrix.
    sample_info_df : pd.DataFrame
        Sample metadata.
    sample_columns : list[str]
        Sample column names matching data_matrix columns.
    reference_values : np.ndarray
        Per-sample reference values (e.g. creatinine, DNA mass, protein conc.).
    col_to_info_row : dict, optional
        Mapping from data column name to SampleInfo row.
    correction_col_name : str, optional
        校正欄位名稱，用於 log 顯示。
    """
    ref_label = correction_col_name or "reference"
    print(f"\n執行 SpecNorm reference division（校正依據: {ref_label}）：")

    # ========== Step 1: 分離 QC 和真實樣本 ==========
    sample_types = {}
    for sample in sample_columns:
        sample_types[sample] = _lookup_sample_type(
            sample, sample_info_df, col_to_info_row, default='UNKNOWN'
        )

    qc_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] == 'QC']
    real_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] != 'QC']

    qc_count = len(qc_indices)
    real_count = len(real_indices)
    print(f"  樣本分類: QC={qc_count}, 真實={real_count}")

    # ========== Step 2: 參考物質校正（僅針對真實樣本）==========
    real_data = data_matrix[:, real_indices]
    real_reference_values = reference_values[real_indices]

    valid_ref_mask = np.isfinite(real_reference_values) & (real_reference_values > 0)

    if np.sum(valid_ref_mask) < len(real_reference_values) * 0.5:
        print(f"    ⚠ 警告：有效 {ref_label} 值不足 50% ({np.sum(valid_ref_mask)}/{len(real_reference_values)})")

    real_data_corrected = real_data.copy()
    median_ref = np.nan
    if np.any(valid_ref_mask):
        median_ref = float(np.nanmedian(real_reference_values[valid_ref_mask]))
        real_data_corrected[:, valid_ref_mask] = (
            real_data[:, valid_ref_mask] / real_reference_values[valid_ref_mask]
        )
    else:
        print(f"    ⚠ 警告：找不到可用的 {ref_label} 值，保留原始真實樣本強度。")

    # ========== Step 3: 合併結果 ==========
    final_data = data_matrix.copy()
    final_data[:, real_indices] = real_data_corrected

    median_label = f"{median_ref:.2f}" if np.isfinite(median_ref) else "nan"
    print(f"  ✓ SpecNorm division 完成（{ref_label} median={median_label}, 校正={np.sum(valid_ref_mask)}/{len(real_reference_values)}）")

    spec_info = {
        'reference_strategy': 'SpecNorm',
        'qc_count': qc_count,
        'qc_cv': np.nan,
        'real_count': real_count,
        'normalization_factors_real': real_reference_values,
        'normalization_factors_qc': None,
        'ref_col_name': ref_label,
        'ref_median': float(median_ref) if np.isfinite(median_ref) else np.nan,
        'ref_valid_count': int(np.sum(valid_ref_mask)),
    }

    return final_data, spec_info


def specnorm_pqn_normalization(data_matrix, sample_info_df, sample_columns,
                               reference_values, col_to_info_row=None,
                               correction_col_name=None,
                               step2_advanced_stats_df=None):
    """Run SpecNorm division, then PQN without post-PQN scale-back."""
    specnorm_data, spec_info = specnorm_reference_division(
        data_matrix,
        sample_info_df,
        sample_columns,
        reference_values,
        col_to_info_row=col_to_info_row,
        correction_col_name=correction_col_name,
    )
    pqn_data, pqn_info = enhanced_pqn_normalization(
        specnorm_data,
        sample_info_df,
        sample_columns,
        col_to_info_row=col_to_info_row,
        step2_advanced_stats_df=step2_advanced_stats_df,
    )
    final_data = pqn_data.copy()

    hybrid_info = dict(pqn_info)
    hybrid_info.update({
        'reference_strategy': 'SpecNorm_PQN',
        'specnorm_info': spec_info,
        'pqn_info': pqn_info,
        'ref_col_name': spec_info.get('ref_col_name', correction_col_name or 'reference'),
        'ref_median': spec_info.get('ref_median', np.nan),
        'ref_valid_count': spec_info.get('ref_valid_count', 0),
        'scale_back_strategy': 'none',
        'scale_back_valid_features': 0,
        'scale_back_missing_features': 0,
    })

    print("  ✓ SpecNorm+PQN 完成（scale-back=none）")
    return final_data, hybrid_info


def calculate_cohens_d(group1, group2):
    """
    計算 Cohen's d (effect size)

    Parameters:
    -----------
    group1 : np.ndarray
        第一組數據
    group2 : np.ndarray
        第二組數據

    Returns:
    --------
    float : Cohen's d 值
    """
    n1 = len(group1)
    n2 = len(group2)

    if n1 < 2 or n2 < 2:
        return np.nan

    mean1 = np.mean(group1)
    mean2 = np.mean(group2)

    var1 = np.var(group1, ddof=1)
    var2 = np.var(group2, ddof=1)

    # Pooled standard deviation
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))

    if pooled_std == 0:
        return np.nan

    # Cohen's d
    d = (mean1 - mean2) / pooled_std

    return d

def evaluate_group_difference_preservation(original_data, normalized_data,
                                           sample_info_df, sample_columns,
                                           col_to_info_row=None):
    """
    評估標準化對組間差異的影響

    基於 Sample_Type: CONTROL vs EXPOSURE

    Parameters:
    -----------
    original_data : np.ndarray
        原始數據矩陣 (特徵 x 樣本)
    normalized_data : np.ndarray
        標準化後數據矩陣 (特徵 x 樣本)
    sample_info_df : pd.DataFrame
        樣本資訊表
    sample_columns : list
        樣本名稱列表

    Returns:
    --------
    dict or None : 組間差異評估結果
    """

    # 1. 提取組別資訊
    sample_groups = np.array([
        _lookup_sample_type(s, sample_info_df, col_to_info_row)
        for s in sample_columns
    ])

    # 2. 識別 CONTROL 和 EXPOSURE
    control_indices = np.where(sample_groups == 'CONTROL')[0]
    exposure_indices = np.where(sample_groups == 'EXPOSURE')[0]

    if len(control_indices) == 0 or len(exposure_indices) == 0:
        print(f"\n【組間差異評估】")
        print(f"  ⚠ 警告: 未找到 CONTROL 或 EXPOSURE 組別")
        print(f"    找到的組別類型: {np.unique(sample_groups)}")
        print(f"  跳過組間差異評估")
        return None

    print(f"\n【組間差異評估】")
    print(f"  Control 組樣本數: {len(control_indices)}")
    print(f"  Exposure 組樣本數: {len(exposure_indices)}")

    # 3. 計算 Cohen's d
    n_features = original_data.shape[0]
    cohens_d_before = []
    cohens_d_after = []

    print(f"  計算 Effect Size (Cohen's d)...", end="")

    for i in range(n_features):
        # 標準化前
        control_before = original_data[i, control_indices]
        exposure_before = original_data[i, exposure_indices]

        control_before = control_before[~np.isnan(control_before)]
        exposure_before = exposure_before[~np.isnan(exposure_before)]

        d_before = calculate_cohens_d(control_before, exposure_before)
        cohens_d_before.append(d_before)

        # 標準化後
        control_after = normalized_data[i, control_indices]
        exposure_after = normalized_data[i, exposure_indices]

        control_after = control_after[~np.isnan(control_after)]
        exposure_after = exposure_after[~np.isnan(exposure_after)]

        d_after = calculate_cohens_d(control_after, exposure_after)
        cohens_d_after.append(d_after)

        if (i + 1) % 100 == 0:
            print(f"\r  計算 Effect Size... {i+1}/{n_features}", end="")

    print(f"\r  ✓ 計算完成 ({n_features}/{n_features})")

    cohens_d_before = np.array(cohens_d_before)
    cohens_d_after = np.array(cohens_d_after)

    # 4. 分析 Effect Size 變化
    valid_mask = ~(np.isnan(cohens_d_before) | np.isnan(cohens_d_after))

    d_before_valid = cohens_d_before[valid_mask]
    d_after_valid = cohens_d_after[valid_mask]

    # 計算相對變化（百分比）
    d_change = np.abs(d_after_valid) - np.abs(d_before_valid)
    d_change_pct = (d_change / (np.abs(d_before_valid) + 1e-10)) * 100

    # 分類
    enhanced = np.sum(d_change > 0)  # Effect size 增強
    stable = np.sum(np.abs(d_change_pct) <= 10)  # 變化 < 10%
    mild_reduction = np.sum((d_change_pct < -10) & (d_change_pct >= -30))
    severe_reduction = np.sum(d_change_pct < -30)

    total = len(d_change)

    # 平均保留率
    avg_preservation = np.mean(np.abs(d_after_valid) / (np.abs(d_before_valid) + 1e-10)) * 100

    # ========== 全域統計摘要與描述性標記 ==========
    wilcoxon_stat = np.nan
    wilcoxon_pvalue = np.nan
    wilcoxon_performed = False
    wilcoxon_significant = False
    flagged_features = []
    effect_size_flagged_ratio = np.nan
    scoreable_flagged_ratio = np.nan

    flagged_mask = d_change_pct < -30
    flagged_indices = np.where(valid_mask)[0][flagged_mask]
    for idx in flagged_indices:
        flagged_features.append({
            'feature_index': idx,
            'cohens_d_before': cohens_d_before[idx],
            'cohens_d_after': cohens_d_after[idx],
            'change_pct': ((np.abs(cohens_d_after[idx]) - np.abs(cohens_d_before[idx])) /
                         (np.abs(cohens_d_before[idx]) + 1e-10)) * 100,
        })

    if total > 0:
        effect_size_flagged_ratio = len(flagged_features) / total

    # 檢查是否有足夠的有效特徵進行統計檢驗
    if total >= 3:
        try:
            # 全域 Wilcoxon signed-rank test (配對雙尾檢驗)
            # 僅作為整體摘要，不代表 per-feature inference
            try:
                wilcoxon_stat, wilcoxon_pvalue = wilcoxon(
                    np.abs(d_before_valid),
                    np.abs(d_after_valid),
                    alternative='two-sided'
                )
                wilcoxon_performed = True
                wilcoxon_significant = bool(wilcoxon_pvalue < 0.05)
                if wilcoxon_significant:
                    scoreable_flagged_ratio = effect_size_flagged_ratio

            except Exception as e:
                print(f"  ⚠ Wilcoxon 檢驗警告: {e}")
                # 如果檢驗失敗（例如所有差異為0），保持 NaN 值
                pass

        except ImportError as e:
            print(f"  ⚠ 統計檢驗套件導入失敗: {e}")
            print(f"     請確保已安裝 scipy 和 statsmodels")
    else:
        print(f"  ⚠ 有效特徵數 ({total}) 不足，跳過統計檢驗（至少需要 3 個）")

    print(f"\n  【Effect Size 變化統計】")
    print(f"  分析特徵數: {total}")
    print(f"  - 增強: {enhanced} ({enhanced/total*100:.1f}%)")
    print(f"  - 穩定 (±10%): {stable} ({stable/total*100:.1f}%)")
    print(f"  - 輕度減弱 (-10% ~ -30%): {mild_reduction} ({mild_reduction/total*100:.1f}%)")
    print(f"  - 顯著減弱 (< -30%): {severe_reduction} ({severe_reduction/total*100:.1f}%)")
    print(f"\n  平均 Effect Size 保留率: {avg_preservation:.1f}%")

    # 輸出統計檢驗結果
    if not np.isnan(wilcoxon_pvalue):
        print(f"\n  【統計檢驗】")
        print(f"  Global Wilcoxon signed-rank test:")
        print(f"  - 統計量: {wilcoxon_stat:.2f}")
        print(f"  - p-value: {wilcoxon_pvalue:.4f}")

        if wilcoxon_pvalue < 0.05:
            median_change_pct = np.median(d_change_pct)
            if median_change_pct < 0:
                print(f"  - 結論: ✗ Cohen's d 中位數顯著下降 ({median_change_pct:.1f}%)")
            else:
                print(f"  - 結論: ✓ Cohen's d 中位數顯著上升 ({median_change_pct:.1f}%)")
        else:
            print(f"  - 結論: ○ Cohen's d 中位數變化不顯著")

    if len(flagged_features) > 0:
        print(f"\n  【標記特徵】")
        print(f"  Effect size 明顯下降的特徵數: {len(flagged_features)} ({effect_size_flagged_ratio*100:.1f}%)")
        print(f"  (描述性標準: |Cohen's d| 下降 > 30%)")

    # 評估
    if severe_reduction / total > 0.1:
        print(f"\n  結論: ⚠⚠ 超過 10% 的特徵顯著減弱，需要檢查")
    elif severe_reduction / total > 0.05:
        print(f"  結論: ⚠ 約 5-10% 的特徵顯著減弱，建議關注")
    elif avg_preservation > 90:
        print(f"  結論: ✓✓ 組間差異保留優秀")
    elif avg_preservation > 80:
        print(f"  結論: ✓ 組間差異保留良好")
    else:
        print(f"  結論: ○ 組間差異保留尚可")

    return {
        'cohens_d_before': cohens_d_before,
        'cohens_d_after': cohens_d_after,
        'enhanced': enhanced,
        'stable': stable,
        'mild_reduction': mild_reduction,
        'severe_reduction': severe_reduction,
        'avg_preservation': avg_preservation,
        'total': total,
        'control_count': len(control_indices),
        'exposure_count': len(exposure_indices),
        # 全域統計摘要（非 per-feature inference）
        'wilcoxon_stat': wilcoxon_stat,
        'wilcoxon_pvalue': wilcoxon_pvalue,
        'wilcoxon_performed': wilcoxon_performed,
        'wilcoxon_significant': wilcoxon_significant,
        'flagged_features': flagged_features,
        'effect_size_flagged_ratio': effect_size_flagged_ratio,
        'scoreable_flagged_ratio': scoreable_flagged_ratio
    }

# ==================== 輔助函數 ====================

def calculate_cv_per_feature(data_matrix):
    """
    計算每個特徵的CV%

    Parameters:
    -----------
    data_matrix : np.ndarray
        數據矩陣 (特徵 x 樣本)

    Returns:
    --------
    cv_values : np.ndarray
        每個特徵的CV%
    """
    mean = np.nanmean(data_matrix, axis=1)
    std = np.nanstd(data_matrix, axis=1)
    cv = (std / mean) * 100
    return cv

def calculate_rsd(data_matrix):
    """計算相對標準偏差 (RSD%)"""
    mean = np.nanmean(data_matrix, axis=1, keepdims=True)
    std = np.nanstd(data_matrix, axis=1, keepdims=True)
    rsd = (std / mean) * 100
    return rsd.flatten()

def calculate_sample_correlation(data_matrix):
    """計算樣本間的 Spearman rank 相關性（適用於非常態質譜數據）"""
    # 移除含有NaN的特徵
    valid_features = ~np.isnan(data_matrix).any(axis=1)
    clean_data = data_matrix[valid_features, :]

    if clean_data.shape[0] < 3:
        return np.nan, np.nan

    corr_matrix, _ = spearmanr(clean_data, axis=0)
    if np.isscalar(corr_matrix) or (hasattr(corr_matrix, 'ndim') and corr_matrix.ndim == 0):
        return float(corr_matrix), 0.0
    mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
    correlations = corr_matrix[mask]
    return np.mean(correlations), np.std(correlations)

# ==================== 視覺化函數 ====================


def plot_intensity_vs_reference(original_data, normalized_data, sample_columns,
                                reference_values, output_path, ref_col_name,
                                sample_info_df=None, col_to_info_row=None):
    """
    散點圖：樣本總強度 vs 參考物質量值（校正前後對比）

    校正前應呈正相關斜線，校正後應變水平。
    僅適用於 SpecNorm+PQN 模式。
    """
    print("  繪製 Total Intensity vs Reference 散點圖...")

    # 計算每個樣本的非缺失特徵中位強度
    def sample_median_intensity(data):
        medians = []
        for j in range(data.shape[1]):
            col = data[:, j]
            valid = col[np.isfinite(col) & (col > 0)]
            medians.append(np.median(valid) if valid.size > 0 else np.nan)
        return np.array(medians)

    med_before = sample_median_intensity(original_data)
    med_after = sample_median_intensity(normalized_data)

    # 辨識樣本類型（著色用）
    sample_types = []
    for s in sample_columns:
        st = _lookup_sample_type(s, sample_info_df, col_to_info_row) if sample_info_df is not None else 'UNKNOWN'
        sample_types.append(st)

    # 只畫有有效參考值的真實樣本（排除 QC）
    mask = np.isfinite(reference_values) & (reference_values > 0) & np.array([t != 'QC' for t in sample_types])

    if np.sum(mask) < 3:
        print("    ⚠ 有效樣本不足，跳過散點圖")
        return

    ref_valid = reference_values[mask]
    med_before_valid = med_before[mask]
    med_after_valid = med_after[mask]
    types_valid = [sample_types[i] for i in range(len(sample_types)) if mask[i]]

    # 分組著色
    unique_types = sorted(set(types_valid))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    for ax, med_vals, title in [
        (ax1, med_before_valid, f'Before Correction'),
        (ax2, med_after_valid, f'After Correction (SpecNorm+PQN)'),
    ]:
        for t in unique_types:
            t_mask = np.array([tt == t for tt in types_valid])
            color = SAMPLE_TYPE_COLORS.get(t, SAMPLE_TYPE_COLORS['UNKNOWN'])
            ax.scatter(ref_valid[t_mask], med_vals[t_mask],
                       c=color, label=t, alpha=0.7, s=50, edgecolors='k', linewidth=0.5)

        # 趨勢線
        finite_mask = np.isfinite(med_vals)
        if np.sum(finite_mask) >= 3:
            z = np.polyfit(ref_valid[finite_mask], med_vals[finite_mask], 1)
            p = np.poly1d(z)
            x_line = np.linspace(ref_valid.min(), ref_valid.max(), 100)
            ax.plot(x_line, p(x_line), 'r--', linewidth=2, alpha=0.8)
            # Pearson r
            r, pval = spearmanr(ref_valid[finite_mask], med_vals[finite_mask])
            ax.text(0.05, 0.95, f'ρ = {r:.3f} (p = {pval:.2e})',
                    transform=ax.transAxes, fontsize=10, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        ax.set_xlabel(ref_col_name, fontsize=12, fontweight='bold')
        ax.set_ylabel('Median Intensity (non-NA features)', fontsize=12, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    fig.suptitle(f'Sample Intensity vs {ref_col_name}', fontsize=16, fontweight='bold')
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ 散點圖已儲存: {Path(output_path).name}")


def plot_dratio_density(original_data, normalized_data, sample_columns,
                        sample_info_df, output_path, col_to_info_row=None):
    """
    D-ratio 密度圖：MAD_QC / MAD_Bio

    D-ratio < 1 表示技術雜訊小於生物變異（好）。
    < 0.5 為良好，< 0.3 為優秀。
    """
    print("  繪製 D-ratio 密度圖...")

    sample_types = np.array([
        _lookup_sample_type(s, sample_info_df, col_to_info_row)
        for s in sample_columns
    ])
    qc_mask = sample_types == 'QC'
    bio_mask = ~qc_mask

    if np.sum(qc_mask) < 2 or np.sum(bio_mask) < 3:
        print("    ⚠ QC 或生物樣本不足，跳過 D-ratio")
        return

    def compute_dratio(data):
        qc_data = data[:, qc_mask]
        bio_data = data[:, bio_mask]
        ratios = []
        for i in range(data.shape[0]):
            qc_vals = qc_data[i, :][np.isfinite(qc_data[i, :])]
            bio_vals = bio_data[i, :][np.isfinite(bio_data[i, :])]
            if qc_vals.size < 2 or bio_vals.size < 3:
                ratios.append(np.nan)
                continue
            mad_qc = np.median(np.abs(qc_vals - np.median(qc_vals)))
            mad_bio = np.median(np.abs(bio_vals - np.median(bio_vals)))
            if mad_bio == 0:
                ratios.append(np.nan)
            else:
                ratios.append(mad_qc / mad_bio)
        return np.array(ratios)

    dr_before = compute_dratio(original_data)
    dr_after = compute_dratio(normalized_data)

    # 過濾有效值
    dr_before_valid = dr_before[np.isfinite(dr_before)]
    dr_after_valid = dr_after[np.isfinite(dr_after)]

    if dr_before_valid.size < 10 or dr_after_valid.size < 10:
        print("    ⚠ 有效 D-ratio 值不足，跳過繪圖")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for vals, label, color in [
        (dr_before_valid, 'Before', '#ea4335'),
        (dr_after_valid, 'After', '#4285f4'),
    ]:
        vals_clipped = vals[vals < 3]  # 截斷極端值方便顯示
        if vals_clipped.size < 5:
            continue
        kde = gaussian_kde(vals_clipped, bw_method=0.3)
        x = np.linspace(0, 3, 300)
        ax.plot(x, kde(x), linewidth=2, label=label, color=color)
        ax.fill_between(x, kde(x), alpha=0.15, color=color)

    ax.axvline(x=0.5, color='orange', linestyle='--', linewidth=1.5, label='Good threshold (0.5)')
    ax.axvline(x=1.0, color='red', linestyle='--', linewidth=1.5, label='D-ratio = 1.0')

    pct_before = 100 * np.sum(dr_before_valid < 0.5) / dr_before_valid.size
    pct_after = 100 * np.sum(dr_after_valid < 0.5) / dr_after_valid.size
    ax.text(0.95, 0.95,
            f'D-ratio < 0.5:\n  Before: {pct_before:.1f}%\n  After: {pct_after:.1f}%',
            transform=ax.transAxes, fontsize=11, verticalalignment='top',
            horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    ax.set_xlabel('D-ratio (MAD_QC / MAD_Bio)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Density', fontsize=12, fontweight='bold')
    ax.set_title('D-ratio Distribution: Technical Noise vs Biological Variance', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ D-ratio 圖已儲存: {Path(output_path).name}")


def plot_density_comparison(original_data, normalized_data, sample_columns, output_path,
                            method_name, sample_info_df=None, col_to_info_row=None):
    """
    NaN-aware KDE 密度圖：按樣本類型分組著色，排除 NaN 後繪製核密度。

    每個樣本類型（Control / Exposure / QC）匯聚成一條 KDE 曲線，
    而非逐樣本疊加直方圖，大幅提升可讀性。
    """
    # 辨識樣本類型
    sample_types = []
    for s in sample_columns:
        st = _lookup_sample_type(s, sample_info_df, col_to_info_row) if sample_info_df is not None else 'UNKNOWN'
        sample_types.append(st)

    unique_types = sorted(set(sample_types))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    for ax, data, title in [
        (ax1, original_data, 'Before Normalization'),
        (ax2, normalized_data, f'After Normalization ({method_name})'),
    ]:
        for grp in unique_types:
            col_indices = [i for i, t in enumerate(sample_types) if t == grp]
            # 匯集該組所有有效值
            pooled = []
            for idx in col_indices:
                col = data[:, idx]
                valid = col[np.isfinite(col) & (col > 0)]
                pooled.append(valid)
            pooled = np.concatenate(pooled) if pooled else np.array([])
            if pooled.size < 10:
                continue
            log_vals = np.log10(pooled)
            kde = gaussian_kde(log_vals, bw_method=0.3)
            x = np.linspace(np.nanmin(log_vals), np.nanmax(log_vals), 300)
            color = SAMPLE_TYPE_COLORS.get(grp, SAMPLE_TYPE_COLORS['UNKNOWN'])
            ax.plot(x, kde(x), linewidth=2, label=f'{grp} (n={len(col_indices)})', color=color)
            ax.fill_between(x, kde(x), alpha=0.12, color=color)

        ax.set_xlabel('Log10(Intensity)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Density', fontsize=12, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  ✓ 密度圖已儲存: {Path(output_path).name}")

def plot_rle(original_data, normalized_data, sample_names, output_path, method_name,
             sample_info_df=None, col_to_info_row=None):
    """
    繪製 RLE (Relative Log Expression) Plot + Sample Total Intensity

    RLE 是組學數據正規化品質評估的黃金標準，顯示每個樣本相對於中位數的偏差分佈。
    第三面板為樣本總強度 before/after 對比長條圖。

    Args:
        original_data: 原始數據矩陣 (features × samples)
        normalized_data: 正規化後數據矩陣 (features × samples)
        sample_names: 樣本名稱列表
        output_path: 輸出路徑
        method_name: 正規化方法名稱
        sample_info_df: 樣本資訊 DataFrame（用於 sample type 著色）
        col_to_info_row: 欄位名稱到 sample_info 列的映射 dict
    """
    print(f"\n  繪製 RLE Plot...")

    # 計算 RLE
    def calculate_rle(data):
        valid_features = ~np.all((data == 0) | np.isnan(data), axis=1)
        data_valid = data[valid_features, :]
        if data_valid.shape[0] == 0:
            return None
        data_masked = np.where(data_valid > 0, data_valid, np.nan)
        data_log = np.log2(data_masked)
        median_per_feature = np.nanmedian(data_log, axis=1, keepdims=True)
        return data_log - median_per_feature

    original_rle = calculate_rle(original_data)
    normalized_rle = calculate_rle(normalized_data)

    if original_rle is None or normalized_rle is None:
        print("    ⚠ RLE 計算失敗，跳過繪圖")
        return

    # 樣本分組著色
    if sample_info_df is not None:
        sample_groups = [
            _lookup_sample_type(s, sample_info_df, col_to_info_row)
            for s in sample_names
        ]
    else:
        sample_groups = ['UNKNOWN'] * len(sample_names)

    fig_width = max(20, len(sample_names) * 0.6)
    fig = plt.figure(figsize=(fig_width, 22))
    gs = fig.add_gridspec(3, 1, height_ratios=[3, 3, 2], hspace=0.32)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    # ===== Panel 1: Original RLE =====
    bp1 = ax1.boxplot(
        [original_rle[:, i][~np.isnan(original_rle[:, i])] for i in range(original_rle.shape[1])],
        labels=sample_names, patch_artist=True, widths=0.6, showfliers=False,
    )
    for patch, group in zip(bp1['boxes'], sample_groups):
        patch.set_facecolor(SAMPLE_TYPE_COLORS.get(group, SAMPLE_TYPE_COLORS['UNKNOWN']))
        patch.set_alpha(0.7)
    for median_line in bp1['medians']:
        median_line.set(color='red', linewidth=2)

    ax1.axhline(y=0, color='green', linestyle='--', linewidth=2, label='Ideal (RLE = 0)', zorder=1)
    ax1.set_ylabel('RLE (Log2 Ratio)', fontsize=12, fontweight='bold')
    ax1.set_title(f'RLE Plot — Before {method_name} Normalization', fontsize=14, fontweight='bold')
    ax1.tick_params(axis='x', rotation=90, labelsize=8)
    for tick_label, group in zip(ax1.get_xticklabels(), sample_groups):
        tick_label.set_color(SAMPLE_TYPE_COLORS.get(group, SAMPLE_TYPE_COLORS['UNKNOWN']))
        tick_label.set_fontweight('bold')
    ax1.legend(fontsize=10, loc='upper right')
    ax1.grid(True, alpha=0.3, linestyle='--', axis='y')

    original_mad = np.nanmedian([np.nanmedian(np.abs(original_rle[:, i])) for i in range(original_rle.shape[1])])
    ax1.text(0.02, 0.96, f'MAD: {original_mad:.4f}',
             transform=ax1.transAxes, fontsize=11, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    # ===== Panel 2: Normalized RLE =====
    bp2 = ax2.boxplot(
        [normalized_rle[:, i][~np.isnan(normalized_rle[:, i])] for i in range(normalized_rle.shape[1])],
        labels=sample_names, patch_artist=True, widths=0.6, showfliers=False,
    )
    for patch, group in zip(bp2['boxes'], sample_groups):
        patch.set_facecolor(SAMPLE_TYPE_COLORS.get(group, SAMPLE_TYPE_COLORS['UNKNOWN']))
        patch.set_alpha(0.7)
    for median_line in bp2['medians']:
        median_line.set(color='blue', linewidth=2)

    ax2.axhline(y=0, color='green', linestyle='--', linewidth=2, label='Ideal (RLE = 0)', zorder=1)
    ax2.set_ylabel('RLE (Log2 Ratio)', fontsize=12, fontweight='bold')
    ax2.set_title(f'RLE Plot — After {method_name} Normalization', fontsize=14, fontweight='bold')
    ax2.tick_params(axis='x', rotation=90, labelsize=8)
    for tick_label, group in zip(ax2.get_xticklabels(), sample_groups):
        tick_label.set_color(SAMPLE_TYPE_COLORS.get(group, SAMPLE_TYPE_COLORS['UNKNOWN']))
        tick_label.set_fontweight('bold')
    ax2.legend(fontsize=10, loc='upper right')
    ax2.grid(True, alpha=0.3, linestyle='--', axis='y')

    normalized_mad = np.nanmedian([np.nanmedian(np.abs(normalized_rle[:, i])) for i in range(normalized_rle.shape[1])])
    improvement = ((original_mad - normalized_mad) / original_mad * 100) if original_mad > 0 else 0
    ax2.text(0.02, 0.96, f'MAD: {normalized_mad:.4f}  (↓{improvement:.1f}%)',
             transform=ax2.transAxes, fontsize=11, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='lightgreen' if improvement > 0 else 'wheat', alpha=0.8))

    # ===== Panel 3: Sample Total Intensity =====
    original_totals = np.nansum(original_data, axis=0)
    normalized_totals = np.nansum(normalized_data, axis=0)
    total_median_before = np.nanmedian(original_totals)
    total_median_after = np.nanmedian(normalized_totals)

    positions = np.arange(len(sample_names))
    bar_width = 0.42
    ax3.bar(positions - bar_width / 2, original_totals, width=bar_width,
            color='#4C72B0', alpha=0.75, label='Before')
    ax3.bar(positions + bar_width / 2, normalized_totals, width=bar_width,
            color='#ED553B', alpha=0.75, label=f'After ({method_name})')

    ax3.axhline(y=total_median_before, color='#4C72B0', linestyle='--', linewidth=1.5,
                alpha=0.8, label=f'Before median: {total_median_before:.2e}')
    ax3.axhline(y=total_median_after, color='#ED553B', linestyle='--', linewidth=1.5,
                alpha=0.8, label=f'After median: {total_median_after:.2e}')

    ax3.set_ylabel('Total Intensity', fontsize=12, fontweight='bold')
    ax3.set_title('Sample Total Intensity Overview', fontsize=14, fontweight='bold')
    ax3.set_xticks(positions)
    ax3.set_xticklabels(sample_names, rotation=90, fontsize=8)
    for tick_label, group in zip(ax3.get_xticklabels(), sample_groups):
        tick_label.set_color(SAMPLE_TYPE_COLORS.get(group, SAMPLE_TYPE_COLORS['UNKNOWN']))
        tick_label.set_fontweight('bold')
    ax3.grid(True, alpha=0.25, axis='y')
    ax3.legend(fontsize=9, loc='upper right', ncol=2)

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  ✓ RLE + Total Intensity Plot 已儲存")


def plot_cv_comparison(original_cv, normalized_cv, output_path, method_name):
    """
    繪製CV%分佈對比圖 (Fig 2 - Improved)

    改進項目：
    - 標題加警示信息
    - 增加閾值線 (20%, 30%, 50%)
    - 圖中只保留讀圖必要元素，統計摘要留在 console / Excel
    """
    # Keep a normal presentation size now that statistical summaries live outside the PNG.
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18.5, 5.6))

    # 移除 NaN 值
    original_cv_clean = original_cv[~np.isnan(original_cv)]
    normalized_cv_clean = normalized_cv[~np.isnan(normalized_cv)]

    # 確保兩者長度一致（用於配對檢驗）
    min_len = min(len(original_cv_clean), len(normalized_cv_clean))
    original_cv_clean = original_cv_clean[:min_len]
    normalized_cv_clean = normalized_cv_clean[:min_len]

    # 計算統計量
    median_improvement = np.median(original_cv_clean) - np.median(normalized_cv_clean)

    # Wilcoxon 配對檢驗
    try:
        w_stat, p_value = wilcoxon(original_cv_clean, normalized_cv_clean)
        if p_value < 0.001:
            sig_mark = '***'
        elif p_value < 0.01:
            sig_mark = '**'
        elif p_value < 0.05:
            sig_mark = '*'
        else:
            sig_mark = 'n.s.'
    except (ValueError, TypeError) as e:
        # ValueError: sample too small or all values identical
        # TypeError: invalid input types
        w_stat, p_value = np.nan, np.nan
        sig_mark = 'N/A'

    # Cohen's d (效應量)
    pooled_std = np.sqrt((np.var(original_cv_clean, ddof=1) + np.var(normalized_cv_clean, ddof=1)) / 2)
    cohens_d = (np.mean(original_cv_clean) - np.mean(normalized_cv_clean)) / pooled_std

    # 效應量解讀
    abs_d = abs(cohens_d)
    if abs_d < COHENS_D_THRESHOLDS['small']:
        effect_interpretation = 'Negligible'
    elif abs_d < COHENS_D_THRESHOLDS['medium']:
        effect_interpretation = 'Small'
    elif abs_d < COHENS_D_THRESHOLDS['large']:
        effect_interpretation = 'Medium'
    else:
        effect_interpretation = 'Large'

    # 閾值定義
    THRESHOLDS = {
        'good': 20,        # 綠色
        'acceptable': 30,  # 橙色
        'poor': 50         # 紅色
    }

    # === 1. 標準化前CV%分佈 ===
    ax1.hist(original_cv_clean, bins=50, color='steelblue', alpha=0.7, edgecolor='black')
    ax1.axvline(x=np.median(original_cv_clean), color='red', linestyle='--',
                linewidth=2, label=f'Median: {np.median(original_cv_clean):.2f}%')

    # 增加閾值線
    ax1.axvline(x=THRESHOLDS['good'], color='#27AE60', linestyle=':', linewidth=2,
                label=f'Good (<{THRESHOLDS["good"]}%)', alpha=0.7)
    ax1.axvline(x=THRESHOLDS['acceptable'], color='#F39C12', linestyle=':', linewidth=2,
                label=f'Acceptable (<{THRESHOLDS["acceptable"]}%)', alpha=0.7)
    ax1.axvline(x=THRESHOLDS['poor'], color='#E74C3C', linestyle=':', linewidth=2,
                label=f'Poor (>{THRESHOLDS["poor"]}%)', alpha=0.7)

    ax1.set_xlabel('CV%', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # === 2. 標準化後CV%分佈 ===
    ax2.hist(normalized_cv_clean, bins=50, color='coral', alpha=0.7, edgecolor='black')
    ax2.axvline(x=np.median(normalized_cv_clean), color='red', linestyle='--',
                linewidth=2, label=f'Median: {np.median(normalized_cv_clean):.2f}%')

    # 增加閾值線
    ax2.axvline(x=THRESHOLDS['good'], color='#27AE60', linestyle=':', linewidth=2,
                label=f'Good (<{THRESHOLDS["good"]}%)', alpha=0.7)
    ax2.axvline(x=THRESHOLDS['acceptable'], color='#F39C12', linestyle=':', linewidth=2,
                label=f'Acceptable (<{THRESHOLDS["acceptable"]}%)', alpha=0.7)
    ax2.axvline(x=THRESHOLDS['poor'], color='#E74C3C', linestyle=':', linewidth=2,
                label=f'Poor (>{THRESHOLDS["poor"]}%)', alpha=0.7)

    ax2.set_xlabel('CV%', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # === 3. CV%改善分佈 ===
    cv_improvement = original_cv_clean - normalized_cv_clean
    ax3.hist(cv_improvement, bins=50, color='green', alpha=0.7, edgecolor='black')
    ax3.axvline(x=0, color='black', linestyle='-', linewidth=2, label='No change')
    ax3.axvline(x=np.median(cv_improvement), color='red', linestyle='--',
                linewidth=2, label=f'Median: {np.median(cv_improvement):.2f}%')

    ax3.set_xlabel('CV% Improvement', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax3.set_title('CV% Improvement Distribution', fontsize=14, fontweight='bold')
    ax3.legend(fontsize=10)
    ax3.grid(True, alpha=0.3)

    fig.suptitle(
        f'Coefficient of Variation (CV%) Comparison ({method_name})',
        fontsize=16,
        y=0.98,
        fontweight='bold',
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  ✓ CV%分佈圖已儲存 (Fig 2 - Improved)")

# ==================== 評估函數 ====================

def evaluate_normalization_quality(original_data, normalized_data):
    """綜合評估標準化質量"""
    results = {}

    # 1. CV% 評估
    original_cv = calculate_rsd(original_data)
    normalized_cv = calculate_rsd(normalized_data)

    results['median_cv_before'] = np.nanmedian(original_cv)
    results['median_cv_after'] = np.nanmedian(normalized_cv)
    results['mean_cv_before'] = np.nanmean(original_cv)
    results['mean_cv_after'] = np.nanmean(normalized_cv)
    results['cv_improvement'] = results['median_cv_before'] - results['median_cv_after']
    results['cv_improvement_pct'] = (results['cv_improvement'] / results['median_cv_before']) * 100 if results['median_cv_before'] > 0 else 0

    try:
        valid_mask = ~(np.isnan(original_cv) | np.isnan(normalized_cv))
        if np.sum(valid_mask) >= 3:
            cv_wilcoxon = wilcoxon(
                original_cv[valid_mask],
                normalized_cv[valid_mask],
                alternative='greater',
            )
            results['cv_wilcoxon_stat'] = float(cv_wilcoxon.statistic)
            results['cv_wilcoxon_pvalue'] = float(cv_wilcoxon.pvalue)
        else:
            results['cv_wilcoxon_stat'] = np.nan
            results['cv_wilcoxon_pvalue'] = np.nan
    except (ValueError, TypeError):
        results['cv_wilcoxon_stat'] = np.nan
        results['cv_wilcoxon_pvalue'] = np.nan

    # CV%改善的特徵比例
    cv_improved = np.sum((original_cv - normalized_cv) > 0)
    cv_total = len(original_cv[~np.isnan(original_cv)])
    results['cv_improved_ratio'] = (cv_improved / cv_total) * 100 if cv_total > 0 else 0

    # 2. 樣本總強度變異
    original_totals = np.nansum(original_data, axis=0)
    normalized_totals = np.nansum(normalized_data, axis=0)

    results['total_cv_before'] = (np.std(original_totals) / np.mean(original_totals)) * 100
    results['total_cv_after'] = (np.std(normalized_totals) / np.mean(normalized_totals)) * 100
    results['total_cv_improvement'] = results['total_cv_before'] - results['total_cv_after']

    # 3. 樣本間相關性
    corr_mean_before, corr_std_before = calculate_sample_correlation(original_data)
    corr_mean_after, corr_std_after = calculate_sample_correlation(normalized_data)

    results['sample_corr_mean_before'] = corr_mean_before
    results['sample_corr_mean_after'] = corr_mean_after
    results['sample_corr_std_before'] = corr_std_before
    results['sample_corr_std_after'] = corr_std_after

    # 4. 數據範圍評估
    results['data_range_before'] = np.nanmax(original_data) - np.nanmin(original_data)
    results['data_range_after'] = np.nanmax(normalized_data) - np.nanmin(normalized_data)

    return results


def evaluate_subset_quality(
    original_data,
    normalized_data,
    sample_columns,
    sample_info_df,
    col_to_info_row=None,
):
    """Evaluate normalization effects separately for QC and real-sample subsets."""
    subset_indices = {
        'qc': [
            i for i, sample in enumerate(sample_columns)
            if _lookup_sample_type(sample, sample_info_df, col_to_info_row) == 'QC'
        ],
        'real': [
            i for i, sample in enumerate(sample_columns)
            if _lookup_sample_type(sample, sample_info_df, col_to_info_row) != 'QC'
        ],
    }

    results = {}
    for label, indices in subset_indices.items():
        results[f'{label}_sample_count'] = len(indices)
        if len(indices) < 2:
            results[f'{label}_median_cv_before'] = np.nan
            results[f'{label}_median_cv_after'] = np.nan
            results[f'{label}_cv_improvement'] = np.nan
            results[f'{label}_cv_improvement_pct'] = np.nan
            results[f'{label}_cv_improved_ratio'] = np.nan
            results[f'{label}_total_cv_before'] = np.nan
            results[f'{label}_total_cv_after'] = np.nan
            results[f'{label}_total_cv_improvement'] = np.nan
            continue

        before_subset = original_data[:, indices]
        after_subset = normalized_data[:, indices]

        before_cv = calculate_rsd(before_subset)
        after_cv = calculate_rsd(after_subset)

        results[f'{label}_median_cv_before'] = np.nanmedian(before_cv)
        results[f'{label}_median_cv_after'] = np.nanmedian(after_cv)
        results[f'{label}_cv_improvement'] = (
            results[f'{label}_median_cv_before'] - results[f'{label}_median_cv_after']
        )
        results[f'{label}_cv_improvement_pct'] = (
            results[f'{label}_cv_improvement'] / results[f'{label}_median_cv_before'] * 100
            if results[f'{label}_median_cv_before'] > 0 else np.nan
        )

        valid_feature_count = np.sum(~np.isnan(before_cv) & ~np.isnan(after_cv))
        improved_feature_count = np.sum((before_cv - after_cv) > 0)
        results[f'{label}_cv_improved_ratio'] = (
            improved_feature_count / valid_feature_count * 100
            if valid_feature_count > 0 else np.nan
        )

        before_totals = np.nansum(before_subset, axis=0)
        after_totals = np.nansum(after_subset, axis=0)
        results[f'{label}_total_cv_before'] = (
            np.std(before_totals, ddof=1) / np.mean(before_totals) * 100
            if len(before_totals) >= 2 and np.mean(before_totals) != 0 else np.nan
        )
        results[f'{label}_total_cv_after'] = (
            np.std(after_totals, ddof=1) / np.mean(after_totals) * 100
            if len(after_totals) >= 2 and np.mean(after_totals) != 0 else np.nan
        )
        results[f'{label}_total_cv_improvement'] = (
            results[f'{label}_total_cv_before'] - results[f'{label}_total_cv_after']
        )

    return results


def build_step4_summary_context(source_sheet_name, available_sheet_names=None):
    """Summarize the Step 3 execution context for human-readable reporting."""
    available_sheet_names = list(available_sheet_names or [])

    resolved_qc_loess_name = resolve_sheet_name(available_sheet_names, 'qc_lowess')
    if source_sheet_name in {
        SHEET_NAMES['qc_lowess'],
        resolved_qc_loess_name,
    }:
        step2_status = "已執行（使用 QC-LOESS 結果）"
    elif source_sheet_name == SHEET_NAMES['istd_correction']:
        step2_status = "未執行或已跳過（直接使用 ISTD_Correction 結果）"
    elif source_sheet_name == SHEET_NAMES['raw_intensity']:
        step2_status = "未執行或已跳過（直接使用 RawIntensity）"
    else:
        step2_status = "無法由目前輸入工作簿明確判定"

    if SHEET_NAMES['istd_correction'] in available_sheet_names:
        step1_status = "目前工作簿可見 ISTD_Correction 工作表"
    elif SHEET_NAMES['raw_intensity'] in available_sheet_names:
        step1_status = "目前工作簿未見 ISTD_Correction 工作表"
    else:
        step1_status = "目前工作簿未保留 Step 1 線索"

    return {
        'source_sheet_name': source_sheet_name,
        'step1_status': step1_status,
        'step2_status': step2_status,
    }

def create_normalization_summary_report(
    quality_metrics,
    method_name,
    n_features,
    n_samples,
    pqn_info=None,
    group_diff_results=None,
    subset_metrics=None,
    summary_context=None,
    mapped_sample_count=None,
):
    """
    建立增強版標準化摘要報告（基於非參數統計方法）

    Parameters:
    -----------
    quality_metrics : dict
        標準化質量指標
    method_name : str
        標準化方法名稱
    n_features : int
        特徵數量
    n_samples : int
        樣本數量
    pqn_info : dict, optional
        PQN 相關資訊
    group_diff_results : dict, optional
        組間差異評估結果

    Returns:
    --------
    str : 格式化的報告文字
    """
    report = []
    report.append(SUMMARY_REPORT_SEPARATOR)
    report.append(f"標準化效果摘要報告 - {method_name}")
    report.append(f"報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(SUMMARY_REPORT_SEPARATOR)

    summary_context = summary_context or {}
    subset_metrics = subset_metrics or {}

    # ========== 執行上下文 ==========
    report.append("")
    report.append("【執行上下文】")
    if summary_context.get('source_sheet_name'):
        report.append(f"上一步輸入工作表: {summary_context['source_sheet_name']}")
    report.append("本摘要的 before/after 指標 = 上一步輸入結果 vs Step 3 輸出")
    if summary_context.get('step1_status'):
        report.append(f"Step 1 線索: {summary_context['step1_status']}")
    if summary_context.get('step2_status'):
        report.append(f"Step 2 狀態: {summary_context['step2_status']}")

    # ========== 基本資訊 ==========
    report.append("")
    report.append("【基本資訊】")
    report.append(f"標準化方法: {method_name}")
    report.append(f"特徵數量: {n_features}")
    report.append(f"樣本數量（含 QC）: {n_samples}")
    if mapped_sample_count is not None:
        report.append(f"名稱成功映射樣本數: {mapped_sample_count}/{n_samples}")
    if pqn_info:
        report.append(f"QC 樣本數量: {pqn_info['qc_count']}")
        report.append(f"真實樣本數量: {pqn_info['real_count']}")

    # ========== 標準化參考資訊 ==========
    if pqn_info:
        report.append("")
        strategy = pqn_info['reference_strategy']
        if strategy == 'SpecNorm_PQN':
            ref_label = pqn_info.get('ref_col_name', 'reference')
            report.append(f"【SpecNorm+PQN 校正資訊（{ref_label}）】")
            report.append(f"真實樣本數量: {pqn_info['real_count']}")
            report.append(f"QC 樣本數量: {pqn_info['qc_count']}（不參與 SpecNorm division）")
            report.append(f"{ref_label} 中位數: {pqn_info['ref_median']:.2f}")
            report.append(f"有效樣本數: {pqn_info['ref_valid_count']}/{pqn_info['real_count']}")
            scale_back_strategy = pqn_info.get('scale_back_strategy', 'unknown')
            report.append(f"Scale-back: {scale_back_strategy}")
            if scale_back_strategy == 'none':
                report.append("輸出尺度: SpecNorm division 後 PQN 尺度（不乘回原始 feature 中位數）")
            else:
                report.append(
                    "Scale-back 可用特徵數: "
                    f"{pqn_info.get('scale_back_valid_features', 0)}/{n_features}"
                )
        else:
            report.append("【PQN 參考樣本資訊】")
            report.append(f"參考策略: {strategy}")
            if pqn_info.get("reference_rationale"):
                report.append(f"參考理由: {pqn_info['reference_rationale']}")

            if pqn_info['qc_count'] > 0 and not np.isnan(pqn_info['qc_cv']):
                report.append(f"QC 中位數 CV%: {pqn_info['qc_cv']:.2f}%")
                if pqn_info['qc_cv'] < CV_QUALITY_THRESHOLDS['excellent']:
                    report.append("QC 質量評估: ✓✓ 優秀")
                elif pqn_info['qc_cv'] < CV_QUALITY_THRESHOLDS['acceptable']:
                    report.append("QC 質量評估: ✓ 良好")
                else:
                    report.append("QC 質量評估: ⚠ 需改進")
            real_factors = np.asarray(pqn_info.get('normalization_factors_real', []), dtype=float)
            if real_factors.size > 0 and np.isfinite(real_factors).any():
                report.append(
                    "PQN 因子範圍: "
                    f"{np.nanmin(real_factors):.4f} – {np.nanmax(real_factors):.4f}"
                )

    # ========== CV% 評估 ==========
    report.append("")
    report.append("【Feature CV 變化（全部樣本）】")
    report.append("上一步輸入:")
    report.append(f"  - 中位數CV%: {quality_metrics['median_cv_before']:.2f}%")
    report.append(f"  - 平均CV%: {quality_metrics['mean_cv_before']:.2f}%")
    report.append("Step 3 輸出:")
    report.append(f"  - 中位數CV%: {quality_metrics['median_cv_after']:.2f}%")
    report.append(f"  - 平均CV%: {quality_metrics['mean_cv_after']:.2f}%")
    report.append("變化:")
    report.append(f"  - CV%降低: {quality_metrics['cv_improvement']:.2f}%")
    report.append(f"  - 改善百分比: {quality_metrics['cv_improvement_pct']:.2f}%")
    report.append(f"  - CV%改善的特徵比例: {quality_metrics['cv_improved_ratio']:.1f}%")
    if not np.isnan(quality_metrics.get('cv_wilcoxon_pvalue', np.nan)):
        report.append(f"  - Wilcoxon p-value: {quality_metrics['cv_wilcoxon_pvalue']:.4g}")

    if subset_metrics:
        report.append("")
        report.append("【QC 與真實樣本分層評估】")
        if not np.isnan(subset_metrics.get('qc_median_cv_before', np.nan)):
            report.append(
                f"QC feature CV 中位數: "
                f"{subset_metrics['qc_median_cv_before']:.2f}% -> "
                f"{subset_metrics['qc_median_cv_after']:.2f}%"
            )
            report.append(
                f"  - QC CV 改善特徵比例: {subset_metrics['qc_cv_improved_ratio']:.1f}%"
            )
        else:
            report.append("QC feature CV: 樣本數不足，未提供分層統計")

        if not np.isnan(subset_metrics.get('real_median_cv_before', np.nan)):
            report.append(
                f"真實樣本 feature CV 中位數: "
                f"{subset_metrics['real_median_cv_before']:.2f}% -> "
                f"{subset_metrics['real_median_cv_after']:.2f}%"
            )
            report.append(
                f"  - 真實樣本 CV 改善特徵比例: {subset_metrics['real_cv_improved_ratio']:.1f}%"
            )
        else:
            report.append("真實樣本 feature CV: 樣本數不足，未提供分層統計")

    # ========== 樣本總強度變異 ==========
    report.append("")
    report.append("【樣本總強度變異（全部樣本）】")
    report.append(f"上一步輸入總強度CV%: {quality_metrics['total_cv_before']:.2f}%")
    report.append(f"Step 3 輸出總強度CV%: {quality_metrics['total_cv_after']:.2f}%")
    report.append(f"總強度CV%改善: {quality_metrics['total_cv_improvement']:.2f}%")
    if subset_metrics:
        if not np.isnan(subset_metrics.get('real_total_cv_before', np.nan)):
            report.append(
                f"真實樣本總強度CV%: "
                f"{subset_metrics['real_total_cv_before']:.2f}% -> "
                f"{subset_metrics['real_total_cv_after']:.2f}%"
            )
        if not np.isnan(subset_metrics.get('qc_total_cv_before', np.nan)):
            report.append(
                f"QC 總強度CV%: "
                f"{subset_metrics['qc_total_cv_before']:.2f}% -> "
                f"{subset_metrics['qc_total_cv_after']:.2f}%"
            )

    # ========== 樣本間相關性 ==========
    report.append("")
    report.append("【樣本間相關性（全部樣本）】")
    if not np.isnan(quality_metrics['sample_corr_mean_before']):
        report.append("上一步輸入:")
        report.append(f"  - 平均相關性: {quality_metrics['sample_corr_mean_before']:.4f}")
        report.append(f"  - 相關性標準差: {quality_metrics['sample_corr_std_before']:.4f}")
        report.append("Step 3 輸出:")
        report.append(f"  - 平均相關性: {quality_metrics['sample_corr_mean_after']:.4f}")
        report.append(f"  - 相關性標準差: {quality_metrics['sample_corr_std_after']:.4f}")
    else:
        report.append("  - 數據不足，無法計算樣本間相關性")

    # ========== 組間差異保留評估 ==========
    if group_diff_results:
        report.append("")
        report.append("【組間差異保留評估】(Control vs Exposure)")
        report.append(f"Control 組樣本數: {group_diff_results['control_count']}")
        report.append(f"Exposure 組樣本數: {group_diff_results['exposure_count']}")
        report.append(f"分析特徵數: {group_diff_results['total']}")
        report.append(f"Effect Size 變化統計:")
        report.append(f"  - 增強: {group_diff_results['enhanced']} ({group_diff_results['enhanced']/group_diff_results['total']*100:.1f}%)")
        report.append(f"  - 穩定 (±10%): {group_diff_results['stable']} ({group_diff_results['stable']/group_diff_results['total']*100:.1f}%)")
        report.append(f"  - 輕度減弱 (-10% ~ -30%): {group_diff_results['mild_reduction']} ({group_diff_results['mild_reduction']/group_diff_results['total']*100:.1f}%)")
        report.append(f"  - 顯著減弱 (< -30%): {group_diff_results['severe_reduction']} ({group_diff_results['severe_reduction']/group_diff_results['total']*100:.1f}%)")
        report.append(f"平均 Effect Size 保留率: {group_diff_results['avg_preservation']:.1f}%")

        if group_diff_results.get('wilcoxon_performed'):
            report.append(f"Global Wilcoxon p-value: {group_diff_results['wilcoxon_pvalue']:.4f}")
            if group_diff_results.get('wilcoxon_significant'):
                report.append("全域檢定結論: |Cohen's d| 整體分佈有顯著變化")
            else:
                report.append("全域檢定結論: |Cohen's d| 整體分佈無顯著變化")
        else:
            report.append("Global Wilcoxon p-value: N/A（有效特徵數不足或檢定未成功執行）")

        effect_size_flagged_ratio = group_diff_results.get('effect_size_flagged_ratio')
        if effect_size_flagged_ratio is not None and not np.isnan(effect_size_flagged_ratio):
            report.append(
                f"Effect size 明顯下降特徵比例: {effect_size_flagged_ratio*100:.1f}% "
                f"(描述性標準: |Cohen's d| 下降 > 30%)"
            )

        if group_diff_results['severe_reduction'] / group_diff_results['total'] > 0.1:
            report.append("評估: ⚠⚠ 部分特徵差異顯著減弱，需檢查")
        elif group_diff_results['avg_preservation'] > 90:
            report.append("評估: ✓✓ 組間差異保留優秀")
        elif group_diff_results['avg_preservation'] > 80:
            report.append("評估: ✓ 組間差異保留良好")
        else:
            report.append("評估: ○ 組間差異保留尚可")

    # ========== 整體判讀 ==========
    report.append("")
    report.append("【整體判讀】")
    feature_p = quality_metrics.get('cv_wilcoxon_pvalue', np.nan)
    if quality_metrics['cv_improvement'] > 0 and quality_metrics['cv_improvement_pct'] >= 10:
        report.append("✓ feature-level reproducibility 有明顯改善")
    elif quality_metrics['cv_improvement'] > 0:
        if not np.isnan(feature_p) and feature_p < 0.05:
            report.append("✓ feature-level reproducibility 有小幅但可檢出的改善")
        else:
            report.append("○ feature-level reproducibility 僅有限改善")
    else:
        report.append("⚠ feature-level reproducibility 未見改善")

    if quality_metrics['total_cv_improvement'] > 10:
        report.append("✓✓ global intensity scaling 改善明顯")
    elif quality_metrics['total_cv_improvement'] > 0:
        report.append("✓ global intensity scaling 有所改善")
    else:
        report.append("⚠ global intensity scaling 未見改善")

    if not np.isnan(quality_metrics['sample_corr_std_before']):
        if quality_metrics['sample_corr_std_after'] < quality_metrics['sample_corr_std_before']:
            report.append("✓ 樣本間相關性更一致")
        else:
            report.append("○ 樣本間相關性結構大致維持不變")

    if group_diff_results:
        if group_diff_results['severe_reduction'] / group_diff_results['total'] > 0.1:
            report.append("⚠ 組間差異有明顯流失風險，建議檢查受影響特徵")
        elif group_diff_results['avg_preservation'] > 90:
            report.append("✓✓ 組間差異保留良好")
        else:
            report.append("○ 組間差異保留度尚可")

    # ========== 建議與注意事項 ==========
    report.append("")
    report.append("【建議與注意事項】")

    # 方法相關建議
    if pqn_info:
        if pqn_info['reference_strategy'] == 'SpecNorm_PQN':
            ref_label = pqn_info.get('ref_col_name', 'reference')
            if pqn_info['ref_valid_count'] < pqn_info['real_count'] * 0.9:
                missing = pqn_info['real_count'] - pqn_info['ref_valid_count']
                report.append(f"⚠ 注意：有 {missing} 個樣本缺少有效 {ref_label} 值，未被校正")
        else:
            if pqn_info['qc_count'] < 3:
                report.append("⚠ 建議：QC 樣本數量較少，建議至少使用 3 個 QC 樣本以提高標準化穩定性")
            if not np.isnan(pqn_info['qc_cv']) and pqn_info['qc_cv'] > 25:
                report.append("⚠ 建議：QC CV% 較高，可能需要檢查實驗技術重現性")

    # 組間差異相關建議
    if group_diff_results:
        if group_diff_results['severe_reduction'] > 0:
            report.append(f"⚠ 注意：有 {group_diff_results['severe_reduction']} 個特徵的組間差異顯著減弱")
            report.append("  建議：檢查這些特徵是否受標準化影響過大，可能需要特別處理")

        if group_diff_results['avg_preservation'] < 80:
            report.append("⚠ 建議：組間差異保留率較低，建議檢查標準化方法是否適合您的數據")

    # CV% 改善相關建議
    if quality_metrics['cv_improved_ratio'] < 50:
        report.append("⚠ 建議：僅不到一半的特徵 CV% 得到改善，可能需要考慮其他標準化方法")

    if (
        quality_metrics['cv_improvement_pct'] <= 10 and
        quality_metrics['total_cv_improvement'] > 10
    ):
        report.append("○ 提示：本次結果較像全域尺度穩定化，而非強烈提升 feature-level reproducibility")

    report.append("")
    report.append("=" * 80)

    return "\n".join(report)

# ==================== 檔案處理函數 ====================

def load_excel_sheets(file_path):
    """載入Excel檔案的所有工作表"""
    try:
        xl_file = pd.ExcelFile(file_path)
        sheet_names = xl_file.sheet_names

        sheets = {}
        for sheet_name in sheet_names:
            sheets[sheet_name] = pd.read_excel(file_path, sheet_name=sheet_name)

        return sheets, sheet_names
    except Exception as e:
        print(f"讀取Excel檔案時發生錯誤: {e}")
        return None, None

def determine_correction_sheet(sheets):
    """按指定順序確定要標準化的資料工作表"""
    for sheet_key in [
        'qc_lowess',
        'istd_correction',
        'raw_intensity',
    ]:
        sheet_name = resolve_sheet_name(sheets.keys(), sheet_key)
        if sheet_name is not None:
            print(f"✓ 依優先順序選擇工作表: {sheet_name}")
            return sheets[sheet_name], sheet_name

    print("警告：未找到指定的資料工作表")
    return None, None


def find_sample_info_sheet(sheets):
    """尋找包含樣本資訊的工作表"""
    possible_names = [SHEET_NAMES['sample_info'], 'Sample_Info', 'sample_info', 'Sample Info']

    for name in possible_names:
        if name in sheets:
            return sheets[name], name

    for sheet_name, df in sheets.items():
        if any(col for col in df.columns if 'normalization' in str(col).lower() or 'sample_type' in str(col).lower()):
            return df, sheet_name

    return None, None


def find_correction_column(df):
    """在樣本資訊工作表尋找可用於 SpecNorm 的 reference concentration 欄位。"""
    if df.shape[1] < 1:
        print("警告：樣本資訊工作表欄位不足")
        return None, None

    excluded_names = {
        'sample_name',
        'method_sample_name',
        'sample_type',
        'injection_order',
        'batch',
        'injection_volume',
    }
    preferred_keywords = (
        'creatinine',
        'dna_mg',
        'dna',
        'protein',
        'concentration',
        'conc',
        'normalization',
        'reference',
        'amount',
    )

    def _column_key(col):
        return re.sub(r'[^a-z0-9]+', '_', str(col).strip().lower()).strip('_')

    def _is_numeric_reference_candidate(col):
        col_key = _column_key(col)
        if col_key in excluded_names:
            return False
        if not any(keyword in col_key for keyword in preferred_keywords):
            return False

        valid_values = df[col].dropna()
        if len(valid_values) == 0:
            return False
        numeric_values = pd.to_numeric(valid_values, errors='coerce')
        return numeric_values.notna().mean() > 0.5

    def _candidate_priority(col):
        col_key = _column_key(col)
        if 'creatinine' in col_key:
            return 0
        if 'dna' in col_key:
            return 1
        if 'protein' in col_key:
            return 2
        if 'concentration' in col_key or 'conc' in col_key:
            return 3
        return 4

    candidates = [col for col in df.columns if _is_numeric_reference_candidate(col)]
    if candidates:
        correction_col = sorted(
            candidates,
            key=lambda col: (_candidate_priority(col), df.columns.get_loc(col)),
        )[0]
        correction_type = (
            'Creatinine'
            if 'creatinine' in _column_key(correction_col)
            else 'Normalization_adduct'
        )
        print(f"✓ 偵測到校正欄位: {correction_col} (類型: {correction_type})")
        return correction_col, correction_type

    print("錯誤：找不到可用於校正的欄位")
    return None, None


def clean_dataframe_for_excel(df):
    """清理DataFrame以避免Excel格式問題"""
    cleaned_df = df.copy()
    error_values = ['#REF!', '#VALUE!', '#NAME?', '#DIV/0!', '#N/A', '#NULL!', '#NUM!']

    for col in cleaned_df.columns:
        series = cleaned_df[col].copy()
        if not pd.api.types.is_object_dtype(series.dtype):
            series = series.astype(object)

        str_series = series.astype(str)

        # 移除公式
        mask_formula = str_series.str.startswith('=')
        if mask_formula.any():
            series = series.mask(mask_formula, '')

        # 移除Excel錯誤值
        error_mask = series.isin(error_values)
        if error_mask.any():
            series = series.mask(error_mask, '')

        if col == cleaned_df.columns[0]:
            cleaned_df[col] = series
            continue

        non_empty = series[series.notna() & (series != '')]
        if non_empty.empty:
            cleaned_df[col] = series
            continue

        numeric_non_empty = pd.to_numeric(non_empty, errors='coerce')
        if numeric_non_empty.notna().all():
            numeric_series = pd.to_numeric(series.replace('', pd.NA), errors='coerce')
            cleaned_df[col] = numeric_series.where(numeric_series.notna(), None)
        else:
            cleaned_df[col] = series

    return cleaned_df

from metabolomics.utils.excel_format import (  # noqa: E302
    PASS_FONT_COLOR,
    STRUCTURE_FONT_COLOR,
    WARN_FONT_COLOR,
    apply_header_fill,
    apply_number_format,
)

# ==================== 主要處理函數 ====================


def _extract_reference_values(sample_columns, col_to_info_row, correction_col):
    """從 SampleInfo 中提取每個樣本的參考物質濃度。"""
    reference_values = []
    for sample in sample_columns:
        info_row = col_to_info_row.get(sample)
        if info_row is not None and pd.notna(info_row.get(correction_col)):
            try:
                ref_val = float(info_row[correction_col])
                reference_values.append(ref_val if ref_val > 0 else np.nan)
            except (ValueError, TypeError, KeyError):
                reference_values.append(np.nan)
        else:
            reference_values.append(np.nan)

    reference_values = np.array(reference_values)

    # 排除 QC 樣本後統計有效比例
    non_qc_mask = np.array([
        not (str(col_to_info_row[s].get('Sample_Type', '')).upper() == 'QC')
        if s in col_to_info_row else
        not any(kw in str(s).upper() for kw in ['QC', 'POOLED'])
        for s in sample_columns
    ])
    non_qc_count = int(np.sum(non_qc_mask))
    valid_count = int(np.sum(~np.isnan(reference_values) & (reference_values > 0)))
    print(f"✓ 有效參考值數量: {valid_count}/{non_qc_count} (排除 {len(sample_columns) - non_qc_count} 個 QC 樣本)")

    if non_qc_count > 0 and valid_count < non_qc_count * 0.3:
        print("❌ 警告：有效參考值不足 30%，無法執行 SpecNorm+PQN 標準化")
        return None

    return reference_values


def perform_normalization(data_df, sample_info_df, file_path,
                          plots_dir=None, source_sheet_name=None,
                          normalization_method='PQN', correction_col=None,
                          available_sheet_names=None,
                          step2_advanced_stats_df=None):
    """
    執行標準化處理

    Parameters:
    -----------
    normalization_method : str
        'PQN' or 'SpecNorm_PQN'
    correction_col : str, optional
        SpecNorm_PQN 模式下使用的校正欄位名稱
    """
    method_name = canonicalize_normalization_method(normalization_method)
    normalization_method = method_name

    print(f"\n" + "="*70)
    print(f"開始執行 Step 3 {method_name} 標準化處理...")
    print("="*70)

    candidate_columns, dropped_columns = identify_candidate_sample_columns(data_df)
    col_to_info_row = build_sample_info_mapping(candidate_columns, sample_info_df)
    sample_columns = [col for col in candidate_columns if col in col_to_info_row]

    if dropped_columns:
        print(f"⚠ 已排除 {len(dropped_columns)} 個推定統計欄位，不納入 Step 3 標準化。")

    print(f"✓ 樣本數量（含QC）: {len(sample_columns)}")

    if len(sample_columns) == 0:
        raise ValueError(
            "未找到可與 SampleInfo 對齊的有效樣本欄位，"
            "請確認資料工作表欄名與 SampleInfo.Sample_Name 一致。"
        )

    unmatched_samples = [sample for sample in candidate_columns if sample not in col_to_info_row]
    if unmatched_samples:
        preview = ", ".join(unmatched_samples[:5])
        if len(unmatched_samples) > 5:
            preview += f" ... 還有 {len(unmatched_samples) - 5} 個"
        raise ValueError(
            "以下資料欄位無法可靠對齊到 SampleInfo，已停止標準化以避免錯誤樣本語義流入下游: "
            f"{preview}"
        )

    # 準備數據矩陣 (特徵 x 樣本) - Vectorized (much faster than iterrows)
    feature_ids = data_df[data_df.columns[0]].tolist()
    # Extract sample columns and convert to numeric matrix directly
    valid_sample_cols = [c for c in sample_columns if c in data_df.columns]
    data_matrix = data_df[valid_sample_cols].apply(pd.to_numeric, errors='coerce').values
    print(f"✓ 數據矩陣形狀: {data_matrix.shape} (特徵 x 樣本)")

    # 保存原始數據用於對比
    original_data = data_matrix.copy()

    print(f"  名稱匹配: {len(col_to_info_row)}/{len(sample_columns)}")

    # ========== 根據方法分流 ==========
    reference_values = None  # only set for SpecNorm_PQN
    if normalization_method == 'SpecNorm_PQN':
        # 提取參考值
        reference_values = _extract_reference_values(
            sample_columns, col_to_info_row, correction_col
        )
        if reference_values is None:
            return None

        normalized_data, pqn_info = specnorm_pqn_normalization(
            data_matrix, sample_info_df, sample_columns,
            reference_values, col_to_info_row=col_to_info_row,
            correction_col_name=correction_col,
            step2_advanced_stats_df=step2_advanced_stats_df,
        )
    else:
        # PQN（預設）
        normalized_data, pqn_info = enhanced_pqn_normalization(
            data_matrix, sample_info_df, sample_columns,
            col_to_info_row=col_to_info_row,
            step2_advanced_stats_df=step2_advanced_stats_df,
        )

    print(f"✓ 標準化完成")

    # 統一輸出目錄與圖表路徑
    output_dir = get_output_root(input_file=file_path)
    run_timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
    method_slug = method_name.replace(' ', '_')

    if plots_dir is not None:
        figures_dir = plots_dir
        figure_paths = {
            "cv": Path(figures_dir) / f"Step3_CV_{method_slug}.png",
            "rle": Path(figures_dir) / f"Step3_RLE_{method_slug}.png",
            "density": Path(figures_dir) / f"Step3_Density_{method_slug}.png",
            "dratio": Path(figures_dir) / f"Step3_Dratio_{method_slug}.png",
        }
        if normalization_method == 'SpecNorm_PQN':
            figure_paths["scatter"] = Path(figures_dir) / f"Step3_Scatter_{method_slug}.png"
    else:
        figures_dir = build_plots_dir(
            "Normalization_Figures",
            input_file=file_path,
            timestamp=run_timestamp,
            session_prefix=method_slug
        )
        figure_paths = {
            "cv": figures_dir / generate_output_filename(
                f"Step3_CV_{method_slug}", timestamp=run_timestamp, extension=".png"
            ),
            "rle": figures_dir / generate_output_filename(
                f"Step3_RLE_{method_slug}", timestamp=run_timestamp, extension=".png"
            ),
            "density": figures_dir / generate_output_filename(
                f"Step3_Density_{method_slug}", timestamp=run_timestamp, extension=".png"
            ),
            "dratio": figures_dir / generate_output_filename(
                f"Step3_Dratio_{method_slug}", timestamp=run_timestamp, extension=".png"
            ),
        }
        if normalization_method == 'SpecNorm_PQN':
            figure_paths["scatter"] = figures_dir / generate_output_filename(
                f"Step3_Scatter_{method_slug}", timestamp=run_timestamp, extension=".png"
            )
    print(f"✓ Excel 將輸出到: {output_dir}")
    print(f"✓ 本次圖表輸出目錄: {figures_dir}")
    # 分離有效樣本用於評估
    valid_sample_mask = ~np.all(np.isnan(normalized_data), axis=0)
    original_data_valid = original_data[:, valid_sample_mask]
    normalized_data_valid = normalized_data[:, valid_sample_mask]
    sample_columns_valid = [sample_columns[i] for i in range(len(sample_columns)) if valid_sample_mask[i]]

    # ========== 評估標準化質量 ==========
    print("\n評估標準化質量...")
    quality_metrics = evaluate_normalization_quality(original_data_valid, normalized_data_valid)
    subset_metrics = evaluate_subset_quality(
        original_data_valid,
        normalized_data_valid,
        sample_columns_valid,
        sample_info_df,
        col_to_info_row=col_to_info_row,
    )

    # ========== 組間差異保留評估 ==========
    try:
        group_diff_results = evaluate_group_difference_preservation(
            original_data_valid, normalized_data_valid, sample_info_df, sample_columns_valid,
            col_to_info_row=col_to_info_row
        )
    except Exception as e:
        print(f"  ⚠ 組間差異評估失敗: {e}")
        group_diff_results = None

    # ========== 生成視覺化圖表 ==========
    print("\n生成視覺化圖表...")

    # 1. CV% 分佈圖
    original_cv = calculate_cv_per_feature(original_data_valid)
    normalized_cv = calculate_cv_per_feature(normalized_data_valid)
    plot_cv_comparison(
        original_cv, normalized_cv,
        figure_paths["cv"],
        method_name
    )

    # 2. RLE Plot + Sample Total Intensity（正規化品質評估黃金標準）
    try:
        plot_rle(
            original_data_valid, normalized_data_valid, sample_columns_valid,
            figure_paths["rle"],
            method_name,
            sample_info_df=sample_info_df,
            col_to_info_row=col_to_info_row,
        )
    except Exception as e:
        print(f"  ⚠ RLE Plot 生成失敗: {e}")

    # 4. NaN-aware KDE 密度圖
    try:
        plot_density_comparison(
            original_data_valid, normalized_data_valid, sample_columns_valid,
            figure_paths["density"],
            method_name,
            sample_info_df=sample_info_df,
            col_to_info_row=col_to_info_row,
        )
    except Exception as e:
        print(f"  ⚠ 密度圖生成失敗: {e}")

    # 6. D-ratio 密度圖（技術雜訊 vs 生物變異）
    try:
        plot_dratio_density(
            original_data_valid, normalized_data_valid, sample_columns_valid,
            sample_info_df, figure_paths["dratio"],
            col_to_info_row=col_to_info_row,
        )
    except Exception as e:
        print(f"  ⚠ D-ratio 圖生成失敗: {e}")

    # 7. Total Intensity vs Reference 散點圖（僅 SpecNorm+PQN）
    if reference_values is not None and "scatter" in figure_paths:
        try:
            plot_intensity_vs_reference(
                original_data_valid, normalized_data_valid, sample_columns_valid,
                reference_values[valid_sample_mask],
                figure_paths["scatter"],
                correction_col or 'Reference',
                sample_info_df=sample_info_df,
                col_to_info_row=col_to_info_row,
            )
        except Exception as e:
            print(f"  ⚠ 散點圖生成失敗: {e}")

    # 創建結果DataFrame（只包含樣本數據和CV%）
    normalized_df = pd.DataFrame()
    normalized_df[data_df.columns[0]] = feature_ids

    # 添加標準化後的樣本數據
    for i, col in enumerate(sample_columns):
        normalized_df[col] = normalized_data[:, i]

    # Step 8 output rule: keep CV metrics with unified Original/Normalized naming.
    # Keep unified CV naming for sample-level metrics; keep single QC_CV% only.
    original_cv_full = calculate_cv_per_feature(original_data)
    normalized_cv_full = calculate_cv_per_feature(normalized_data)

    normalized_df['Original_CV%'] = original_cv_full
    normalized_df['Normalized_CV%'] = normalized_cv_full
    normalized_df['CV_Improvement%'] = original_cv_full - normalized_cv_full


    qc_indices_for_cv = [
        i for i, s in enumerate(sample_columns)
        if _lookup_sample_type(s, sample_info_df, col_to_info_row) == 'QC'
    ]
    if len(qc_indices_for_cv) > 0:
        normalized_df['QC_CV%'] = calculate_cv_per_feature(normalized_data[:, qc_indices_for_cv])
    else:
        normalized_df['QC_CV%'] = np.nan

    normalized_df = apply_feature_metadata_passthrough(normalized_df, data_df)

    # ========== 生成摘要報告 ==========
    summary_report = create_normalization_summary_report(
        quality_metrics, method_name, len(feature_ids), len(sample_columns),
        pqn_info=pqn_info,
        group_diff_results=group_diff_results,
        subset_metrics=subset_metrics,
        summary_context=build_step4_summary_context(
            source_sheet_name,
            available_sheet_names=available_sheet_names,
        ),
        mapped_sample_count=len(col_to_info_row),
    )

    print(f"\n{summary_report}")

    return normalized_df, summary_report, method_name, output_dir, quality_metrics, figures_dir

def save_normalization_results(
    normalized_df,
    summary_report,
    file_path,
    method_name,
    preserved_data_sheet_name,
    sample_info_sheet_name,
    output_dir,
    preserved_data_df=None,
    sample_info_df=None,
    output_path=None,
):
    """儲存標準化結果到Excel檔案"""
    try:
        summary_sheet_name = get_summary_sheet_name(method_name)
        if output_path is None:
            timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
            output_filename = generate_output_filename(
                f"Normalized_{method_name}", timestamp=timestamp, extension=".xlsx"
            )
            output_path = output_dir / output_filename

        # 創建新工作簿
        wb_new = Workbook()
        wb_new.remove(wb_new.active)

        # 1. 儲存標準化後的資料
        ws_normalized = wb_new.create_sheet(title=f'{method_name}_Result')

        cleaned_normalized_df = clean_dataframe_for_excel(normalized_df)
        for r_idx, row in enumerate(dataframe_to_rows(cleaned_normalized_df, index=False, header=True), 1):
            for c_idx, value in enumerate(row, 1):
                cell = ws_normalized.cell(row=r_idx, column=c_idx, value=value)
                if r_idx == 1:
                    cell.font = Font(bold=True, size=11)
                    cell.alignment = Alignment(horizontal='center', vertical='center')
        apply_header_fill(ws_normalized)

        normalized_headers = [cell.value for cell in ws_normalized[1]]
        normalized_header_map = {name: idx + 1 for idx, name in enumerate(normalized_headers) if name}
        for col_name in normalized_headers:
            if not col_name or is_non_sample_column(col_name):
                continue
            apply_number_format(ws_normalized, normalized_header_map[col_name], '0.00E+00')

        # 自動調整列寬
        for column in ws_normalized.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except (TypeError, AttributeError):
                    # TypeError: cell.value is None or non-stringable
                    # AttributeError: cell has no value attribute
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws_normalized.column_dimensions[column_letter].width = adjusted_width

        # 2. 儲存摘要報告
        ws_summary = wb_new.create_sheet(title=summary_sheet_name)
        summary_rows = summary_report.split('\n')
        for r_idx, row_text in enumerate(summary_rows, 1):
            cell_value = row_text
            if row_text.startswith('='):
                cell_value = f" {row_text}"
            cell = ws_summary.cell(row=r_idx, column=1, value=cell_value)
            if '=' in row_text and r_idx <= 3:
                cell.font = Font(bold=True, size=12)
            elif '【' in row_text:
                cell.font = Font(bold=True, size=11, color=STRUCTURE_FONT_COLOR)
            elif '✓' in row_text:
                cell.font = Font(color=PASS_FONT_COLOR)
            elif '⚠' in row_text:
                cell.font = Font(color=WARN_FONT_COLOR)

        ws_summary.column_dimensions['A'].width = 80

        # 3. 保留上一步資料工作表與 SampleInfo（直接使用記憶體中的 DataFrame）
        df_map = {
            preserved_data_sheet_name: preserved_data_df,
            sample_info_sheet_name: sample_info_df,
        }
        preserved_sheet_names = []
        for sheet_name in [preserved_data_sheet_name, sample_info_sheet_name]:
            preserved_df = df_map.get(sheet_name)
            if not sheet_name or preserved_df is None or sheet_name in preserved_sheet_names:
                continue

            ws_preserved = wb_new.create_sheet(title=sheet_name[:31])
            preserved_sheet_names.append(sheet_name)

            cleaned_preserved_df = clean_dataframe_for_excel(preserved_df)
            for r_idx, row in enumerate(dataframe_to_rows(cleaned_preserved_df, index=False, header=True), 1):
                for c_idx, value in enumerate(row, 1):
                    ws_preserved.cell(row=r_idx, column=c_idx, value=value)

            apply_header_fill(ws_preserved)

            preserved_headers = [cell.value for cell in ws_preserved[1]]
            preserved_header_map = {name: idx + 1 for idx, name in enumerate(preserved_headers) if name}
            for col_name in preserved_headers:
                if not col_name or is_non_sample_column(col_name):
                    continue
                apply_number_format(ws_preserved, preserved_header_map[col_name], '0.00E+00')

            for column in ws_preserved.columns:
                max_length = max(
                    (len(str(cell.value)) for cell in column if cell.value is not None),
                    default=8,
                )
                ws_preserved.column_dimensions[column[0].column_letter].width = min(max_length + 2, 50)

        # 儲存新工作簿
        wb_new.save(output_path)

        print(f"\n✓ 結果已儲存至: {output_path}")
        print(f"\n包含工作表:")
        print(f"  1. {method_name}_Result (標準化後資料)")
        print(f"  2. {summary_sheet_name} (摘要報告)")
        for index, sheet_name in enumerate(preserved_sheet_names, start=3):
            print(f"  {index}. {sheet_name} (保留輸入資料)")

        return str(output_path)

    except Exception as e:
        print(f"儲存檔案時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==================== 主程式 ====================

def main(input_file=None, session_dir=None, normalization_method='PQN'):
    """
    主函數 - 支援 GUI 和獨立運行

    Parameters:
    -----------
    input_file : str, optional
        輸入檔案路徑（由 GUI 傳入）
    session_dir : str or Path, optional
        Session directory for pipeline-aware output.
    normalization_method : str
        'PQN' or 'SpecNorm_PQN'（由 GUI 傳入）

    Returns:
    --------
    ProcessingResult
    """
    print("=" * 80)
    normalization_method = canonicalize_normalization_method(normalization_method)
    print("  代謝體學 Step 3 標準化程式 v4.1")
    print(f"  標準化方法: {normalization_method}")
    print("  - 視覺化評估工具（盒鬚圖、CV%分佈、RLE、Density、D-ratio 等）")
    print("=" * 80)

    if input_file is None:
        raise ValueError("input_file is required; GUI must provide the file path.")

    session_dir = resolve_session_dir(input_file=input_file, session_dir=session_dir)


    # 驗證檔案是否存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"找不到檔案: {input_file}")

    print(f"\n✓ 選擇的檔案: {Path(input_file).name}")

    # 載入Excel工作表
    sheets, sheet_names = load_excel_sheets(input_file)
    if not sheets:
        raise Exception("無法載入 Excel 工作表")

    print(f"✓ 找到 {len(sheet_names)} 個工作表")

    # 尋找樣本資訊工作表
    sample_info_df, sample_info_sheet_name = find_sample_info_sheet(sheets)
    if sample_info_df is None:
        print("❌ 錯誤：找不到包含樣本資訊的工作表")
        raise Exception("找不到樣本資訊工作表")

    print(f"✓ 使用樣本資訊工作表: {sample_info_sheet_name}")

    # SpecNorm_PQN 模式需要校正欄位
    correction_col = None
    if normalization_method == 'SpecNorm_PQN':
        correction_col, correction_type = find_correction_column(sample_info_df)
        if not correction_col:
            raise ValueError(
                "SampleInfo 中找不到 SpecNorm+PQN 所需的校正欄位。\n"
                "請確認 SampleInfo 工作表的第 F 欄（或之後）包含數值型校正資料\n"
                "（例如 Creatinine 濃度、Normalization adduct 等）。"
            )
        print(f"✓ 校正欄位: {correction_col} (類型: {correction_type})")

    # 確定要標準化的資料工作表
    data_df, data_sheet_name = determine_correction_sheet(sheets)
    if data_df is None:
        print("❌ 錯誤：找不到要標準化的資料工作表")
        raise Exception("找不到資料工作表")

    print(f"✓ 使用資料工作表: {data_sheet_name}")

    step2_advanced_stats_df = None
    step2_advanced_sheet_name = resolve_sheet_name(sheet_names, "qc_lowess_advanced")
    if step2_advanced_sheet_name is not None:
        step2_advanced_stats_df = sheets[step2_advanced_sheet_name]
        print(f"✓ 使用 Step 2 advanced stats: {step2_advanced_sheet_name}")

    # 提取 Sample_Type 資訊行（不參與數值計算，保存時回插）
    from metabolomics.utils.data_helpers import extract_sample_type_row
    feature_col = data_df.columns[0]
    data_df, sample_type_row = extract_sample_type_row(data_df, feature_col)
    if sample_type_row is not None:
        print(f"✓ 偵測到 Sample_Type 資訊行，已提取保存（不參與計算）")

    # Determine session-aware paths
    if session_dir is not None:
        from metabolomics.utils.file_io import session_output_path, session_plots_dir
        _session_plots = session_plots_dir(session_dir)
    else:
        _session_plots = None

    # 執行標準化
    result = perform_normalization(
        data_df,
        sample_info_df,
        input_file,
        plots_dir=_session_plots,
        source_sheet_name=data_sheet_name,
        normalization_method=normalization_method,
        correction_col=correction_col,
        available_sheet_names=sheet_names,
        step2_advanced_stats_df=step2_advanced_stats_df,
    )

    if result is None:
        print("\n❌ 標準化失敗")
        raise Exception("標準化失敗")

    normalized_df, summary_report, method_name, output_dir, quality_metrics, figures_dir = result



    # 回插 Sample_Type 資訊行到 normalized_df（若有）
    if sample_type_row is not None:
        from metabolomics.utils.data_helpers import insert_sample_type_row
        normalized_df = insert_sample_type_row(normalized_df, sample_type_row, feature_col)

    # Build session-aware output path
    if session_dir is not None:
        _save_path = session_output_path(session_dir, step=3, prefix=f"Normalized_{method_name}")
    else:
        _save_path = None

    # 儲存結果
    print("\n儲存結果...")
    output_path = save_normalization_results(
        normalized_df,
        summary_report,
        input_file,
        method_name,
        data_sheet_name,
        sample_info_sheet_name,
        output_dir,
        preserved_data_df=data_df,
        sample_info_df=sample_info_df,
        output_path=_save_path,
    )

    if not output_path:
        raise Exception("儲存結果失敗")

    print(f"\n  ✓ Step 3 完成 → {Path(output_path).name}")
    print(f"    CV%: {quality_metrics['median_cv_before']:.1f}% → {quality_metrics['median_cv_after']:.1f}%"
          f" (改善 {quality_metrics['cv_improvement_pct']:.0f}%, {quality_metrics['cv_improved_ratio']:.0f}% features)")
    print(f"    上游基準: {data_sheet_name}")
    print(f"    總強度CV%: {quality_metrics['total_cv_before']:.1f}% → {quality_metrics['total_cv_after']:.1f}%")

    # 🎯 返回統計資訊給 GUI
    # 從 normalized_df 中提取樣本數量（排除第一列 FeatureID）
    sample_count = len(normalized_df.columns) - 1
    metabolite_count = len(normalized_df)

    return ProcessingResult(
        file_path=input_file,
        output_path=str(output_path),
        plots_dir=str(figures_dir),
        metabolites=metabolite_count,
        samples=sample_count
    )


if __name__ == "__main__":
    # 🔧 獨立運行時不傳入 input_file，會顯示對話框
    main()
