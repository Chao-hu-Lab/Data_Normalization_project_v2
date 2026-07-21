import pandas as pd
import numpy as np
import os
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter
import statsmodels.api as sm
from scipy.stats import levene, kendalltau, wilcoxon
import matplotlib.pyplot as plt
import warnings
from collections import Counter

warnings.filterwarnings('ignore')

# ========== 匯入共用模組 ==========
from metabolomics.utils.data_helpers import (
    get_valid_values,
    apply_feature_metadata_passthrough,
)
from metabolomics.utils.plotting import setup_matplotlib
from metabolomics.utils.constants import (
    NON_SAMPLE_COLUMNS,
    SHEET_NAMES,
    DATETIME_FORMAT_FULL,
    FEATURE_ID_COLUMN,
    CV_QUALITY_THRESHOLDS,
    is_non_sample_column,
)
from metabolomics.utils.sample_classification import (
    normalize_sample_name,
    normalize_sample_type,
    identify_sample_columns,
    parse_batch_labels as shared_parse_batch_labels,
)
from metabolomics.utils.file_io import (
    build_output_path,
    build_plots_dir,
    get_output_root,
    resolve_session_dir,
)
from metabolomics.utils.data_validation import DataValidator, require_valid
from metabolomics.utils.excel_colors import cell_has_red_font
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome
from metabolomics.utils.console import safe_print as print
from metabolomics.utils.excel_format import (
    SECTION_DIVIDER_FILL,
    SECTION_LABEL_FILL,
    SECTION_TITLE_FILL,
    STRUCTURE_FONT_COLOR,
    apply_band_fill,
    apply_cv_quality_fill,
    apply_header_fill,
    apply_improvement_fill,
    apply_number_format,
    apply_significance_fill,
)

# 設定 matplotlib
setup_matplotlib()

# Sheet name constant
QC_LOWESS_ADVANCED_SHEET = SHEET_NAMES.get('qc_lowess_advanced', "LOESS_summary")
# For backward compatibility, alias the old constant names
DEFAULT_NON_SAMPLE_COLUMNS = NON_SAMPLE_COLUMNS


def parse_batch_labels(value):
    """Parse semicolon-separated batch labels and trim whitespace."""
    return shared_parse_batch_labels(value)


def collect_red_marked_feature_ids(file_path, sheet_name):
    """Collect red-font feature IDs from the first column of a worksheet.

    Uses ``read_only=True`` for streaming parsing – avoids loading the
    entire DOM tree into memory, which is critical for large matrices.
    """
    workbook = load_workbook(file_path, read_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            return set()

        worksheet = workbook[sheet_name]
        feature_ids = set()
        for row in worksheet.iter_rows(min_row=2, max_col=1):
            cell = row[0]
            if cell.value is None:
                continue
            if cell_has_red_font(cell):
                feature_ids.add(str(cell.value).strip())
        return feature_ids
    finally:
        workbook.close()


def exclude_fallback_istd_rows(data_df, file_path, source_sheet_name):
    """Exclude red-marked ISTD rows when Step 2 falls back to RawIntensity."""
    if source_sheet_name != SHEET_NAMES['raw_intensity']:
        return data_df

    print("\n⚠️ Step 1 未產生 'ISTD_Correction'，Step 2 改用 'RawIntensity' 作為上游來源。")
    red_marked_feature_ids = collect_red_marked_feature_ids(file_path, source_sheet_name)
    if not red_marked_feature_ids:
        print("   - 未偵測到紅字 ISTD 標記，QC-LOESS 將把所有列視為一般 feature。")
        data_df.attrs['excluded_fallback_istd_count'] = 0
        return data_df

    istd_mask = data_df['FeatureID'].astype(str).str.strip().isin(red_marked_feature_ids)
    excluded_count = int(istd_mask.sum())
    if excluded_count == 0:
        print("   - RawIntensity 中沒有對應到紅字 ISTD 的資料列，QC-LOESS 將把所有列視為一般 feature。")
        data_df.attrs['excluded_fallback_istd_count'] = 0
        return data_df

    filtered_df = data_df.loc[~istd_mask].copy()
    filtered_df.attrs.update(data_df.attrs)
    filtered_df.attrs['excluded_fallback_istd_count'] = excluded_count
    filtered_df.attrs['fallback_istd_feature_ids'] = sorted(red_marked_feature_ids)

    print(f"   - 偵測到 {excluded_count} 個紅字 ISTD；它們會保留在 'RawIntensity'，但不會進入 '{SHEET_NAMES['qc_lowess']}'。")
    print(f"   - QC-LOESS 實際處理特徵數: {len(filtered_df)}")

    if filtered_df.empty:
        raise ValueError("排除紅字 ISTD 後沒有可供 QC-LOESS 的 feature")

    return filtered_df


def _frac_floor(n_valid_qc: int) -> float:
    """Return minimum frac to prevent LOWESS overfitting for small QC counts."""
    if n_valid_qc <= 5:
        return 1.0
    if n_valid_qc <= 6:
        return 0.85
    if n_valid_qc <= 7:
        return 0.80
    if n_valid_qc <= 10:
        return 0.70
    return 0.0


def _loocv_rmse(x: np.ndarray, y: np.ndarray, frac: float, it: int = 2) -> float:
    """Compute LOWESS leave-one-out RMSE for small QC sets."""
    n_points = len(x)
    errors = np.empty(n_points, dtype=float)
    for i in range(n_points):
        mask = np.ones(n_points, dtype=bool)
        mask[i] = False
        x_train = x[mask]
        y_train = y[mask]
        if x_train.size < 3:
            errors[i] = 0.0
            continue
        fit = sm.nonparametric.lowess(
            y_train,
            x_train,
            frac=frac,
            it=it,
            return_sorted=True,
        )
        pred = float(np.interp(x[i], fit[:, 0], fit[:, 1]))
        errors[i] = (y[i] - pred) ** 2
    return float(np.sqrt(np.mean(errors)))


def filter_qc_outliers_iqr(qc_orders, qc_intensities, *, min_keep=5, min_keep_ratio=0.7):
    """Filter QC outliers by IQR when enough points remain for a defensible fit."""
    qc_orders_arr = np.asarray(qc_orders, dtype=float)
    qc_intensities_arr = np.asarray(qc_intensities, dtype=float)
    valid_mask = (
        np.isfinite(qc_orders_arr)
        & np.isfinite(qc_intensities_arr)
        & (qc_intensities_arr > 0)
    )
    valid_x = qc_orders_arr[valid_mask]
    valid_y = qc_intensities_arr[valid_mask]

    meta = {
        'original_valid_count': int(valid_x.size),
        'valid_qc_count': int(valid_x.size),
        'removed_outlier_count': 0,
        'outlier_filter_applied': False,
        'outlier_filter_blocked': False,
    }

    if valid_x.size == 0:
        return valid_x, valid_y, meta

    q1 = np.nanpercentile(valid_y, 25)
    q3 = np.nanpercentile(valid_y, 75)
    iqr = q3 - q1
    if not np.isfinite(iqr) or iqr <= 0:
        return valid_x, valid_y, meta

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    keep_mask = (valid_y >= lower) & (valid_y <= upper)
    removed_count = int((~keep_mask).sum())
    if removed_count == 0:
        return valid_x, valid_y, meta

    remaining_count = int(keep_mask.sum())
    keep_ratio = remaining_count / valid_x.size if valid_x.size else 0.0
    if remaining_count < min_keep or keep_ratio < min_keep_ratio:
        meta['outlier_filter_blocked'] = True
        return valid_x, valid_y, meta

    filtered_x = valid_x[keep_mask]
    filtered_y = valid_y[keep_mask]
    meta['valid_qc_count'] = int(filtered_x.size)
    meta['removed_outlier_count'] = removed_count
    meta['outlier_filter_applied'] = True
    return filtered_x, filtered_y, meta




def apply_lowess_correction(qc_orders, qc_intensities, all_orders, all_intensities, debug_flag=None):
    """對單一批次特徵執行 QC-LOWESS 校正並回傳詳細統計。

    Args:
        qc_orders: QC 樣本的 injection order
        qc_intensities: QC 樣本的強度值
        all_orders: 所有樣本的 injection order
        all_intensities: 所有樣本的強度值
        debug_flag: 除錯標記
    """
    info = {
        'status': 'failed',
        'cv_before': np.nan,
        'cv_after': np.nan,
        'cv_improvement': np.nan,
        'raw_factor_min': np.nan,
        'raw_factor_max': np.nan,
        'clamped_factor_min': np.nan,
        'clamped_factor_max': np.nan,
        'clamped_count': 0,
        'clamped_ratio': np.nan,
        'outside_qc_range_count': 0,
        'valid_qc_count': 0,
        'removed_outlier_count': 0,
        'outlier_filter_applied': False,
        'target_strategy': 'unknown',
        'normalized_rmse': np.nan,
        'correction_factor_stats': {},
        'trend_validation': {
            'trend_pvalue': np.nan,
            'trend_tau': np.nan,
            'r_squared': np.nan,
            'rmse': np.nan
        },
        'frac_used': np.nan,
        'qc_cv_for_frac': np.nan,
        'frac_strategy': 'unknown',
        'loocv_rmse': np.nan,
    }

    if all_orders is None or all_intensities is None:
        return [], info

    all_orders_arr = np.asarray(all_orders, dtype=float)
    all_intensities_arr = np.asarray(all_intensities, dtype=float)
    if all_orders_arr.size == 0:
        return all_intensities_arr.tolist(), info

    qc_orders_arr = np.asarray(qc_orders, dtype=float)
    qc_intensities_arr = np.asarray(qc_intensities, dtype=float)
    valid_mask = np.isfinite(qc_orders_arr) & np.isfinite(qc_intensities_arr) & (qc_intensities_arr > 0)
    valid_x = qc_orders_arr[valid_mask]
    valid_y = qc_intensities_arr[valid_mask]

    if valid_x.size == 0:
        info['status'] = 'all_qc_invalid'
        info['frac_strategy'] = 'all_qc_invalid'
        return all_intensities_arr.tolist(), info

    filtered_x, filtered_y, outlier_meta = filter_qc_outliers_iqr(qc_orders, qc_intensities)
    info['valid_qc_count'] = outlier_meta['valid_qc_count']
    info['removed_outlier_count'] = outlier_meta['removed_outlier_count']
    info['outlier_filter_applied'] = outlier_meta['outlier_filter_applied']

    if outlier_meta['outlier_filter_blocked']:
        info['status'] = 'outlier_filtering_left_too_few_points'
        info['frac_strategy'] = 'outlier_filtering_left_too_few_points'
        return all_intensities_arr.tolist(), info

    valid_x = filtered_x
    valid_y = filtered_y

    if valid_x.size < 5 or np.unique(valid_x).size < 2:
        info['status'] = 'insufficient_qc'
        info['frac_strategy'] = 'insufficient_qc'
        return all_intensities_arr.tolist(), info

    # ===== 動態 frac 策略 =====
    def compute_qc_cv(values):
        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values) & (values > 0)]
        if values.size < 2:
            return 100.0
        mean_val = np.nanmean(values)
        if not np.isfinite(mean_val) or mean_val <= 0:
            return 100.0
        std_val = np.nanstd(values, ddof=1)
        if not np.isfinite(std_val):
            return 100.0
        return float(std_val / mean_val * 100)

    qc_cv_for_frac = compute_qc_cv(valid_y)
    qc_cv_for_frac = 100.0 if not np.isfinite(qc_cv_for_frac) else qc_cv_for_frac

    if qc_cv_for_frac > CV_QUALITY_THRESHOLDS['acceptable']:
        frac = 0.8
        frac_strategy = 'high_variation'
    elif qc_cv_for_frac > CV_QUALITY_THRESHOLDS['excellent']:
        frac = 0.7
        frac_strategy = 'medium_variation'
    else:
        dynamic_frac = 0.85 - (valid_x.size / 50.0)
        frac = float(np.clip(dynamic_frac, 0.5, 0.75))
        frac_strategy = 'low_variation_dynamic'

    floor = _frac_floor(valid_x.size)
    if frac < floor:
        frac = floor
        frac_strategy += '_floor_applied'

    if valid_x.size <= 10:
        loocv_rmse_val = _loocv_rmse(valid_x, valid_y, frac)
        raw_std = float(np.std(valid_y, ddof=1))
        if raw_std > 0 and loocv_rmse_val < raw_std * 0.10:
            original_frac = frac
            for bump in (0.1, 0.2, 0.3):
                candidate = min(original_frac + bump, 1.0)
                new_rmse = _loocv_rmse(valid_x, valid_y, candidate)
                if new_rmse >= raw_std * 0.10:
                    frac = candidate
                    loocv_rmse_val = new_rmse
                    frac_strategy += '_loocv_bumped'
                    break
            else:
                frac = 1.0
                loocv_rmse_val = _loocv_rmse(valid_x, valid_y, frac)
                frac_strategy += '_loocv_maxed'

    info['frac_used'] = float(frac)
    info['qc_cv_for_frac'] = float(qc_cv_for_frac)
    info['frac_strategy'] = frac_strategy
    if valid_x.size <= 10:
        info['loocv_rmse'] = float(loocv_rmse_val)

    lowess_result = sm.nonparametric.lowess(valid_y, valid_x, frac=frac, it=2, return_sorted=True)
    x_fit, y_fit = lowess_result[:, 0], lowess_result[:, 1]

    median_qc = np.nanmedian(y_fit)
    info['target_strategy'] = 'batch_local_fit_median'
    if not np.isfinite(median_qc) or median_qc <= 0:
        median_qc = np.nanmedian(valid_y)
        info['target_strategy'] = 'batch_local_observed_qc_median'
    if not np.isfinite(median_qc) or median_qc <= 0:
        median_qc = 1.0
        info['target_strategy'] = 'unity_fallback'

    def predict(x_new):
        if not np.isfinite(x_new):
            return np.nan
        return float(np.interp(x_new, x_fit, y_fit, left=y_fit[0], right=y_fit[-1]))

    min_factor = 0.5
    max_factor = 2.0
    corrected = []
    raw_factors = []
    clamped_factors = []
    outside_qc_range_count = 0
    qc_span_min = float(np.nanmin(valid_x))
    qc_span_max = float(np.nanmax(valid_x))
    for order, intensity in zip(all_orders_arr, all_intensities_arr):
        if not np.isfinite(intensity):
            corrected.append(np.nan)
            continue
        if intensity <= 0:
            corrected.append(float(intensity))
            continue
        if np.isfinite(order) and (order < qc_span_min or order > qc_span_max):
            outside_qc_range_count += 1
            corrected.append(float(intensity))
            continue
        fitted = predict(order)
        if not np.isfinite(fitted) or fitted <= 0 or fitted < median_qc * 0.01:
            corrected.append(float(intensity))
            continue
        raw_factor = float(median_qc / fitted)
        clamped_factor = float(np.clip(raw_factor, min_factor, max_factor))
        raw_factors.append(raw_factor)
        clamped_factors.append(clamped_factor)
        corrected.append(float(intensity * clamped_factor))

    qc_pred = np.array([predict(x) for x in valid_x], dtype=float)
    qc_pred = np.where(np.isfinite(qc_pred) & (qc_pred > 0), qc_pred, np.nan)
    qc_raw_factors = np.where(np.isfinite(qc_pred), median_qc / qc_pred, 1.0)
    qc_factors = np.clip(qc_raw_factors, min_factor, max_factor)
    qc_corrected = valid_y * qc_factors

    def calc_cv(values):
        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values) & (values > 0)]
        if values.size < 2:
            return np.nan
        mean_val = np.mean(values)
        if mean_val == 0:
            return np.nan
        return float(np.std(values, ddof=1) / mean_val * 100)

    original_cv = calc_cv(valid_y)
    corrected_cv = calc_cv(qc_corrected)
    cv_improvement = original_cv - corrected_cv if np.isfinite(original_cv) and np.isfinite(corrected_cv) else np.nan
    raw_factor_array = np.asarray(raw_factors, dtype=float)
    factor_array = np.asarray(clamped_factors, dtype=float)
    factor_cv = calc_cv(factor_array) if factor_array.size >= 2 else np.nan

    try:
        trend_tau, trend_pvalue = kendalltau(valid_x, valid_y)
    except Exception:
        trend_tau, trend_pvalue = (np.nan, np.nan)

    qc_predicted = np.array([predict(x) for x in valid_x], dtype=float)
    qc_predicted = np.where(np.isfinite(qc_predicted), qc_predicted, np.nanmedian(valid_y))
    ss_res = np.nansum((valid_y - qc_predicted) ** 2)
    ss_tot = np.nansum((valid_y - np.nanmean(valid_y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    rmse = np.sqrt(np.nanmean((valid_y - qc_predicted) ** 2))
    median_valid_y = float(np.nanmedian(valid_y)) if valid_y.size else np.nan
    normalized_rmse = (
        float(rmse / median_valid_y)
        if np.isfinite(rmse) and np.isfinite(median_valid_y) and median_valid_y > 0
        else np.nan
    )
    normalized_drift_amplitude = (
        float((np.nanmax(qc_predicted) - np.nanmin(qc_predicted)) / median_valid_y)
        if np.isfinite(median_valid_y) and median_valid_y > 0
        else np.nan
    )

    status = 'success'
    if (
        np.isfinite(trend_tau)
        and np.isfinite(trend_pvalue)
        and np.isfinite(r_squared)
        and np.isfinite(normalized_drift_amplitude)
        and abs(trend_tau) < 0.2
        and trend_pvalue >= 0.05
        and r_squared < 0.1
        and normalized_drift_amplitude < 0.05
    ):
        corrected = all_intensities_arr.tolist()
        qc_corrected = valid_y.copy()
        corrected_cv = original_cv
        cv_improvement = 0.0
        status = 'no_drift_detected'
    elif not np.isfinite(original_cv) or not np.isfinite(corrected_cv):
        status = 'failed'
    elif cv_improvement < -1:
        status = 'overcorrection_detected'
    elif factor_array.size >= 3 and np.isfinite(factor_cv) and factor_cv > 50:
        status = 'unstable_correction_factors'
    elif not np.isfinite(cv_improvement) or cv_improvement < 2:
        status = 'insufficient_improvement'

    info['status'] = status
    info['cv_before'] = original_cv
    info['cv_after'] = corrected_cv
    info['cv_improvement'] = cv_improvement
    info['raw_factor_min'] = float(np.nanmin(raw_factor_array)) if raw_factor_array.size else np.nan
    info['raw_factor_max'] = float(np.nanmax(raw_factor_array)) if raw_factor_array.size else np.nan
    info['clamped_factor_min'] = float(np.nanmin(factor_array)) if factor_array.size else np.nan
    info['clamped_factor_max'] = float(np.nanmax(factor_array)) if factor_array.size else np.nan
    info['clamped_count'] = int(
        np.sum(~np.isclose(raw_factor_array, factor_array, rtol=1e-9, atol=1e-12))
    ) if raw_factor_array.size and factor_array.size else 0
    info['clamped_ratio'] = (
        float(info['clamped_count'] / factor_array.size)
        if factor_array.size
        else np.nan
    )
    info['outside_qc_range_count'] = outside_qc_range_count
    info['normalized_rmse'] = normalized_rmse
    info['correction_factor_stats'] = {
        'median': float(np.nanmedian(factor_array)) if factor_array.size else np.nan,
        'cv_percent': factor_cv,
        'min': float(np.nanmin(factor_array)) if factor_array.size else np.nan,
        'max': float(np.nanmax(factor_array)) if factor_array.size else np.nan
    }
    info['trend_validation'] = {
        'trend_pvalue': trend_pvalue,
        'trend_tau': trend_tau,
        'r_squared': r_squared,
        'rmse': rmse
    }

    if debug_flag:
        delta = cv_improvement if np.isfinite(cv_improvement) else float('nan')
        frac_val = info.get('frac_used', np.nan)
        qc_cv_val = info.get('qc_cv_for_frac', np.nan)
        strategy = info.get('frac_strategy', 'unknown')
        print(f"     [DEBUG] Feature {debug_flag}: status={status}, ΔCV={delta:.2f}%")
        print(f"              - QC CV% = {qc_cv_val:.2f}%")
        print(f"              - Frac used = {frac_val:.3f}")
        print(f"              - Strategy = {strategy}")

        # 儲存繪圖數據用於趨勢擬合圖
        info['plot_data'] = {
            'qc_orders': valid_x.tolist(),
            'qc_raw': valid_y.tolist(),
            'qc_corrected': qc_corrected.tolist(),
            'lowess_x': x_fit.tolist(),
            'lowess_y': y_fit.tolist(),
            'all_orders': all_orders_arr.tolist(),
            'all_raw': all_intensities_arr.tolist(),
            'all_corrected': corrected,
            'median_qc': float(median_qc)
        }

    return corrected, info

def perform_lowess_normalization(istd_df, sample_info_df):
    """執行分批次的 QC-LOWESS 正規化流程。"""
    try:
        if istd_df is None or istd_df.empty:
            raise ValueError("ISTD_Correction 數據為空")

        if sample_info_df is None or sample_info_df.empty:
            raise ValueError("SampleInfo 數據為空")

        # 支援 'Mz/RT' 或 'FeatureID' 作為特徵ID欄位
        if FEATURE_ID_COLUMN in istd_df.columns and FEATURE_ID_COLUMN != 'FeatureID':
            istd_df = istd_df.rename(columns={FEATURE_ID_COLUMN: 'FeatureID'})
        elif 'FeatureID' not in istd_df.columns:
            first_col = istd_df.columns[0]
            print(f"⚠️ 未找到 'FeatureID' 欄位，使用第一欄 '{first_col}' 作為特徵ID")
            istd_df = istd_df.rename(columns={first_col: 'FeatureID'})

        if 'Sample_Name' not in sample_info_df.columns or 'Sample_Type' not in sample_info_df.columns:
            raise ValueError("SampleInfo 缺少必要欄位 (Sample_Name, Sample_Type)")

        sample_columns = istd_df.attrs.get('sample_columns')
        if not sample_columns:
            sample_columns, _ = identify_sample_columns(istd_df, sample_info_df)

        sample_columns = [col for col in sample_columns if col in istd_df.columns]
        if not sample_columns:
            raise ValueError("找不到有效的樣本欄位")

        sample_info_norm = sample_info_df.copy()
        sample_info_norm['_norm_name'] = sample_info_norm['Sample_Name'].map(normalize_sample_name)
        sample_info_norm = sample_info_norm[sample_info_norm['_norm_name'].astype(bool)]
        sample_meta = sample_info_norm.drop_duplicates('_norm_name').set_index('_norm_name')
        col_to_meta = {
            col: normalize_sample_name(col)
            for col in sample_columns
            if normalize_sample_name(col) in sample_meta.index
        }
        missing_meta = [col for col in sample_columns if col not in col_to_meta]

        if missing_meta and len(missing_meta) == len(sample_columns):
            print("⚠️  SampleInfo 與 ISTD_Correction 的樣本名稱格式不同，改用欄位名稱推斷樣本類型")
        elif missing_meta:
            print("⚠️  警告：以下樣本在 SampleInfo 中找不到對應資訊，將被排除：")
            for name in missing_meta[:5]:
                print(f"     - {name}")
            if len(missing_meta) > 5:
                print(f"     ... 還有 {len(missing_meta) - 5} 個樣本")
            sample_columns = [col for col in sample_columns if col in col_to_meta]

        if not sample_columns:
            raise ValueError("無法匹配 SampleInfo 與 ISTD_Correction 的樣本欄位")

        # 判斷 QC 樣本：優先從 SampleInfo 查找，如找不到則從欄位名稱關鍵字判斷
        qc_samples = []
        for sample in sample_columns:
            meta_key = col_to_meta.get(sample)
            if meta_key in sample_meta.index:
                if 'QC' in str(sample_meta.loc[meta_key].get('Sample_Type', '')).upper():
                    qc_samples.append(sample)
            elif 'QC' in sample.upper() or 'POOLED' in sample.upper():
                qc_samples.append(sample)

        if len(qc_samples) < 5:
            raise ValueError(f"QC 樣本不足 ({len(qc_samples)} < 5)，無法進行校正")

        batch_groups = {}
        missing_order_samples = []
        for sample in sample_columns:
            meta_name = col_to_meta.get(sample, sample)
            if meta_name not in sample_meta.index:
                continue
            meta_row = sample_meta.loc[meta_name]
            order = meta_row.get('Injection_Order')
            if pd.isna(order):
                missing_order_samples.append(sample)
            sample_type = normalize_sample_type(meta_row.get('Sample_Type', ''))
            batches = parse_batch_labels(meta_row.get('Batch', 'Batch1')) or ['Batch1']

            if sample_type != 'QC' and len(batches) != 1:
                raise ValueError(f"Non-QC sample '{sample}' must belong to a single batch")

            for batch_name in batches:
                batch_entry = batch_groups.setdefault(
                    batch_name,
                    {'samples': [], 'qc_samples': [], 'injection_orders': {}}
                )
                if sample not in batch_entry['samples']:
                    batch_entry['samples'].append(sample)

                if sample_type == 'QC' and sample not in batch_entry['qc_samples']:
                    batch_entry['qc_samples'].append(sample)

                batch_order = order
                if pd.isna(batch_order):
                    batch_order = len(batch_entry['injection_orders']) + 1
                batch_entry['injection_orders'][sample] = batch_order

        active_batches = {k: v for k, v in batch_groups.items() if v['samples']}
        if not active_batches:
            raise ValueError("找不到可供處理的批次樣本")

        print("\n📊 數據概覽：")
        print(f"  - 特徵數: {len(istd_df)}")
        print(f"  - 樣本總數: {len(sample_columns)}")
        print(f"  - QC 樣本數: {len(qc_samples)}")
        print(f"  - 批次數: {len(active_batches)}")
        for batch, info in active_batches.items():
            print(f"    • Batch {batch}: {len(info['samples'])} samples (QC: {len(info['qc_samples'])})")

        if missing_order_samples:
            print(f"⚠️  提示：{len(missing_order_samples)} 個樣本缺少 Injection_Order，已套用臨時序號")

        print("\n🔍 計算 QC CV% 以選擇調試特徵...")
        # Vectorized CV% calculation - much faster than iterrows()
        from metabolomics.utils.safe_math import safe_cv_percent_vectorized

        valid_qc_cols = [c for c in qc_samples if c in istd_df.columns]
        if valid_qc_cols:
            qc_data = istd_df[valid_qc_cols].apply(pd.to_numeric, errors='coerce').values
            cv_values = safe_cv_percent_vectorized(qc_data, axis=1, min_samples=2)
            feature_ids = istd_df['FeatureID'].values
            # Build list of (feature_id, cv_value) for features with valid CV
            feature_cvs = [
                (fid, cv) for fid, cv in zip(feature_ids, cv_values)
                if not np.isnan(cv)
            ]
        else:
            feature_cvs = []

        debug_features = []
        if feature_cvs:
            feature_cvs_sorted = sorted(feature_cvs, key=lambda x: x[1])
            debug_features = [feature_cvs_sorted[0][0]]
            debug_features.append(feature_cvs_sorted[len(feature_cvs_sorted) // 2][0])
            debug_features.append(feature_cvs_sorted[-1][0])
            debug_features = list(dict.fromkeys(debug_features))
            print("   • 調試特徵:")
            for fid in debug_features:
                matching = [cv for cv in feature_cvs if cv[0] == fid]
                if matching:
                    print(f"     - {fid} (CV% = {matching[0][1]:.2f}%)")

        def normalize_feature_for_batch(feature_row, batch_name, batch_info, debug_flag):
            samples = batch_info['samples']
            injection_orders = batch_info['injection_orders']
            valid_samples = [s for s in samples if s in injection_orders]
            if not valid_samples:
                return {
                    'status': 'failed',
                    'corrected_samples': {},
                    'trend_validation': None,
                    'qc_samples': []
                }

            batch_data = []
            for sample in valid_samples:
                order = injection_orders[sample]
                intensity = feature_row.get(sample, np.nan)
                if pd.isna(intensity):
                    intensity = np.nan
                else:
                    intensity = float(intensity)
                batch_data.append((sample, order, intensity))

            batch_data.sort(key=lambda x: x[1])
            all_sample_names = [d[0] for d in batch_data]
            all_orders = [d[1] for d in batch_data]
            all_intensities = [d[2] for d in batch_data]

            qc_batch_samples = [s for s in batch_info['qc_samples'] if s in all_sample_names]
            qc_indices = [all_sample_names.index(s) for s in qc_batch_samples]
            qc_orders = [all_orders[i] for i in qc_indices]
            qc_intensities = [all_intensities[i] for i in qc_indices]

            corrected_intensities, info = apply_lowess_correction(
                qc_orders, qc_intensities, all_orders, all_intensities, debug_flag
            )

            corrected_map = dict(zip(all_sample_names, corrected_intensities))
            result = {
                'status': info.get('status', 'unknown'),
                'corrected_samples': corrected_map,
                'trend_validation': info.get('trend_validation', None),
                'step2_metrics': info,
                'qc_samples': qc_batch_samples,
                'frac_info': {
                    'frac_used': info.get('frac_used', np.nan),
                    'qc_cv_for_frac': info.get('qc_cv_for_frac', np.nan),
                    'frac_strategy': info.get('frac_strategy', 'unknown')
                }
            }
            # 如果有繪圖數據（僅限 debug 特徵），則加入
            if 'plot_data' in info:
                result['plot_data'] = info['plot_data']
            return result

        def safe_nanmedian(values):
            if not values:
                return np.nan
            arr = np.array(values, dtype=float)
            if arr.size == 0 or np.all(np.isnan(arr)):
                return np.nan
            return float(np.nanmedian(arr))

        def choose_frac_strategy(strategies):
            if not strategies:
                return 'unknown'
            valid_strategies = [s for s in strategies if isinstance(s, str)]
            if not valid_strategies:
                return 'unknown'
            strategy_counter = Counter(valid_strategies)
            priority = ['high_variation', 'medium_variation', 'low_variation_dynamic',
                        'insufficient_qc', 'unknown']
            for key in priority:
                if key in strategy_counter:
                    return key
                for strategy in valid_strategies:
                    if strategy.startswith(key):
                        return strategy
            return strategy_counter.most_common(1)[0][0]

        def choose_target_strategy(strategies):
            valid_strategies = [s for s in strategies if isinstance(s, str) and s]
            if not valid_strategies:
                return 'unknown'
            strategy_counter = Counter(valid_strategies)
            return strategy_counter.most_common(1)[0][0]

        status_categories = [
            'success', 'insufficient_qc', 'all_qc_invalid',
            'outlier_filtering_left_too_few_points', 'no_drift_detected',
            'insufficient_improvement',
            'unstable_correction_factors', 'overcorrection_detected',
            'failed', 'unknown'
        ]
        decision_stats = {key: 0 for key in status_categories}
        decision_stats['partial_success'] = 0
        decision_stats['event_counts'] = {key: 0 for key in status_categories}
        decision_stats['per_batch'] = {}
        decision_stats['total_features'] = len(istd_df)
        decision_stats['total_batches'] = len(active_batches)
        decision_stats['total_feature_batch_tasks'] = len(active_batches) * len(istd_df)

        all_results = []
        qc_corrected_values = {}
        trend_stats = []
        feature_all_success = 0
        feature_no_drift = 0
        feature_partial_success = 0
        feature_no_success = 0
        frac_usage_counter = Counter()
        frac_value_list = []
        trend_plot_data = {}  # 儲存趨勢擬合圖的數據

        for idx, row in istd_df.iterrows():
            feature_id = row['FeatureID']
            debug_flag = feature_id if feature_id in debug_features else None

            result_row = {'FeatureID': feature_id}
            for sample in sample_columns:
                result_row[sample] = row[sample]

            qc_corrected_dict = {sample: row[sample] for sample in qc_samples if sample in row.index}
            corrected_candidates = {}
            batch_metric_buffer = []
            batch_statuses = []
            frac_value_buffer = []
            frac_cv_buffer = []
            frac_strategy_buffer = []

            for batch_name, batch_info in active_batches.items():
                batch_result = normalize_feature_for_batch(row, batch_name, batch_info, debug_flag)
                status = batch_result['status']
                batch_statuses.append(status)

                decision_stats['event_counts'].setdefault(status, 0)
                decision_stats['event_counts'][status] += 1
                batch_entry = decision_stats['per_batch'].setdefault(batch_name, {})
                batch_entry[status] = batch_entry.get(status, 0) + 1

                corrected_map = batch_result['corrected_samples']
                if status == 'success' and corrected_map:
                    for sample, value in corrected_map.items():
                        corrected_candidates.setdefault(sample, []).append(value)

                step2_metrics = batch_result.get('step2_metrics') or {}
                if step2_metrics:
                    batch_metric_buffer.append(step2_metrics)

                frac_info = batch_result.get('frac_info') or {}
                frac_value_buffer.append(frac_info.get('frac_used'))
                frac_cv_buffer.append(frac_info.get('qc_cv_for_frac'))
                frac_strategy_buffer.append(frac_info.get('frac_strategy'))

                # 收集趨勢擬合圖數據（僅限 debug 特徵）
                if debug_flag and 'plot_data' in batch_result:
                    trend_plot_data[(feature_id, batch_name)] = batch_result['plot_data']

            for sample in sample_columns:
                if sample in corrected_candidates:
                    result_row[sample] = safe_nanmedian(corrected_candidates[sample])

            for sample in qc_corrected_dict:
                if sample in corrected_candidates:
                    qc_corrected_dict[sample] = safe_nanmedian(corrected_candidates[sample])

            stable_batch_statuses = {'success', 'no_drift_detected'}
            success_batches = sum(status in stable_batch_statuses for status in batch_statuses)
            all_batches_no_drift = (
                len(batch_statuses) == len(active_batches)
                and all(status == 'no_drift_detected' for status in batch_statuses)
            )
            if all_batches_no_drift:
                decision_stats['no_drift_detected'] += 1
                feature_no_drift += 1
            elif success_batches == len(active_batches):
                decision_stats['success'] += 1
                feature_all_success += 1
            elif success_batches > 0:
                decision_stats['partial_success'] += 1
                feature_partial_success += 1
            else:
                failure_priority = [
                    status for status in status_categories
                    if status not in stable_batch_statuses and status in batch_statuses
                ]
                failure_key = failure_priority[0] if failure_priority else 'failed'
                decision_stats[failure_key] += 1
                feature_no_success += 1

            frac_values_clean = [val for val in frac_value_buffer if val is not None]
            frac_cvs_clean = [val for val in frac_cv_buffer if val is not None]
            feature_frac_used = safe_nanmedian(frac_values_clean)
            feature_qc_cv = safe_nanmedian(frac_cvs_clean)
            feature_frac_strategy = choose_frac_strategy(frac_strategy_buffer)
            if all_batches_no_drift:
                feature_status = 'no_drift_detected'
            elif success_batches == len(active_batches):
                feature_status = 'success'
            elif success_batches > 0:
                feature_status = 'partial_success'
            else:
                feature_status = failure_key

            if np.isfinite(feature_frac_used):
                frac_value_list.append(feature_frac_used)
            frac_usage_counter[feature_frac_strategy] += 1

            trend_stats.append({
                'FeatureID': feature_id,
                'Valid_QC_Count': safe_nanmedian([m.get('valid_qc_count', np.nan) for m in batch_metric_buffer]),
                'Removed_QC_Outliers': int(np.nansum([m.get('removed_outlier_count', 0) for m in batch_metric_buffer])),
                'Outlier_Filter_Applied': any(bool(m.get('outlier_filter_applied', False)) for m in batch_metric_buffer),
                'Trend_pvalue': safe_nanmedian([m.get('trend_validation', {}).get('trend_pvalue', np.nan) for m in batch_metric_buffer]),
                'Kendall_Tau': safe_nanmedian([m.get('trend_validation', {}).get('trend_tau', np.nan) for m in batch_metric_buffer]),
                'LOESS_R2': safe_nanmedian([m.get('trend_validation', {}).get('r_squared', np.nan) for m in batch_metric_buffer]),
                'LOESS_RMSE': safe_nanmedian([m.get('trend_validation', {}).get('rmse', np.nan) for m in batch_metric_buffer]),
                'Normalized_RMSE': safe_nanmedian([m.get('normalized_rmse', np.nan) for m in batch_metric_buffer]),
                'Target_Strategy': choose_target_strategy([m.get('target_strategy') for m in batch_metric_buffer]),
                'Clamped_Factor_Ratio': safe_nanmedian([m.get('clamped_ratio', np.nan) for m in batch_metric_buffer]),
                'Outside_QC_Range_Count': int(np.nansum([m.get('outside_qc_range_count', 0) for m in batch_metric_buffer])),
                'Decision_Status': feature_status,
                'Frac_Used': feature_frac_used,
                'QC_CV_for_Frac': feature_qc_cv,
                'Frac_Strategy': feature_frac_strategy
            })

            all_results.append(result_row)
            qc_corrected_values[feature_id] = qc_corrected_dict

            if (idx + 1) % 500 == 0:
                print(f"  進度: {idx + 1}/{len(istd_df)} features")

        print("\n  ✓ 批次化 LOESS 校正完成")
        print("\n  📊 特徵層級統計：")
        print(f"     ✅ 全批次均成功: {feature_all_success} ({feature_all_success/len(istd_df)*100:.1f}%)")
        print(f"     ○ 全批次無需校正: {feature_no_drift} ({feature_no_drift/len(istd_df)*100:.1f}%)")
        print(f"     ⚠️ 部分批次成功: {feature_partial_success} ({feature_partial_success/len(istd_df)*100:.1f}%)")
        print(f"     ❌ 無成功批次: {feature_no_success} ({feature_no_success/len(istd_df)*100:.1f}%)")

        print("\n  📊 決策細節 (以批次為單位)：")
        total_tasks = decision_stats['total_feature_batch_tasks'] or 1
        for status, count in decision_stats['event_counts'].items():
            if count == 0:
                continue
            print(f"     • {status}: {count} ({count/total_tasks*100:.1f}%)")

        print("\n  📊 Frac 使用統計：")
        total_features = len(istd_df) or 1
        high_count = frac_usage_counter.get('high_variation', 0)
        medium_count = frac_usage_counter.get('medium_variation', 0)
        low_count = frac_usage_counter.get('low_variation_dynamic', 0)
        other_count = max(total_features - (high_count + medium_count + low_count), 0)
        frac_mean = float(np.nanmean(frac_value_list)) if frac_value_list else np.nan
        frac_median = float(np.nanmedian(frac_value_list)) if frac_value_list else np.nan

        def frac_pct(count):
            return (count / total_features * 100) if total_features else 0

        def fmt_frac_value(value):
            return f"{value:.2f}" if np.isfinite(value) else "N/A"

        print(f"     - 高變異策略 (frac=0.8): {high_count} ({frac_pct(high_count):.1f}%)")
        print(f"     - 中等變異策略 (frac=0.7): {medium_count} ({frac_pct(medium_count):.1f}%)")
        print(f"     - 低變異動態策略 (frac=0.5~0.75): {low_count} ({frac_pct(low_count):.1f}%)")
        if other_count:
            print(f"     - 其他（資料不足）: {other_count} ({frac_pct(other_count):.1f}%)")
        print(f"     - Frac 平均值: {fmt_frac_value(frac_mean)}")
        print(f"     - Frac 中位數: {fmt_frac_value(frac_median)}")

        lowess_df = pd.DataFrame(all_results)
        trend_stats_df = pd.DataFrame(trend_stats)

        decision_stats['frac_usage_counter'] = dict(frac_usage_counter)
        decision_stats['frac_value_list'] = frac_value_list

        return lowess_df, sample_columns, qc_corrected_values, trend_stats_df, decision_stats, trend_plot_data

    except Exception as e:
        print(f"❌ LOESS 校正失敗: {e}")
        import traceback
        traceback.print_exc()
        raise


    # ========== 數據載入 ==========
def get_valid_values(row, columns):
    """從 DataFrame 的一行中提取有效值（>0 且非 NaN）"""
    values = []
    for col in columns:
        if col in row.index:
            try:
                val = float(row[col])
                if not pd.isna(val) and val > 0:
                    values.append(val)
            except (ValueError, TypeError):
                pass
    return values


def load_and_process_data(file_path):
    """載入並驗證數據（含完整防呆檢查）"""
    try:
        validator = DataValidator()
        require_valid(
            validator.validate_file_path(file_path),
            context="Step 2 input file",
        )
        file_path = os.fspath(file_path)

        # ===== 防呆1: 文件存在性檢查 =====
        if not os.path.exists(file_path):
            raise ValueError(f"找不到檔案 '{file_path}'")

        # ===== 防呆2: 文件格式檢查 =====
        if not (file_path.endswith('.xlsx') or file_path.endswith('.xls')):
            raise ValueError(f"輸入檔案必須是 Excel 格式 (.xlsx 或 .xls)，但提供了 {file_path}")

        # ===== 防呆3: 文件大小檢查 =====
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError("檔案大小為 0 bytes，可能是空檔案")
        elif file_size < 1024:  # 小於 1KB
            print(f"⚠️  警告：檔案大小僅 {file_size} bytes，可能不是有效的 Excel 檔案")

        print(f"📄 檔案大小: {file_size / 1024:.2f} KB")

        # ===== 防呆4: Excel 文件有效性檢查 =====
        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as e:
            raise ValueError(f"無法讀取 Excel 檔案，可能已損壞或格式不正確: {e}") from e

        # ===== 防呆5: 必要工作表檢查 =====
        print(f"📋 找到的工作表: {', '.join(excel_file.sheet_names)}")

        require_valid(
            validator.validate_required_sheets(
                excel_file.sheet_names,
                required_sheets=[SHEET_NAMES['sample_info']],
                context="Step 2 input workbook",
            ),
            context="Step 2 workbook sheets",
        )

        required_sheets = [SHEET_NAMES['sample_info']]
        missing_sheets = [sheet for sheet in required_sheets if sheet not in excel_file.sheet_names]

        if missing_sheets:
            raise ValueError(
                f"輸入檔案缺少必要的工作表: {', '.join(missing_sheets)}。"
                f" 找到的工作表: {', '.join(excel_file.sheet_names)}。"
                f" QC-LOESS 校正需要至少包含 RawIntensity 或 ISTD_Correction"
            )

        # ===== 防呆6: SampleInfo 完整性檢查 =====
        source_sheet_name = (
            SHEET_NAMES['istd_correction']
            if SHEET_NAMES['istd_correction'] in excel_file.sheet_names
            else SHEET_NAMES['raw_intensity']
        )

        sample_info_df = pd.read_excel(excel_file, sheet_name=SHEET_NAMES['sample_info'])
        print(f"✓ 成功讀取 '{SHEET_NAMES['sample_info']}' 工作表，包含 {len(sample_info_df)} 筆樣本資訊")

        if sample_info_df.empty:
            raise ValueError(f"'{SHEET_NAMES['sample_info']}' 工作表為空")

        require_valid(
            validator.validate_sample_info(
                sample_info_df,
                required_columns=['Sample_Name', 'Sample_Type', 'Injection_Order'],
            ),
            context="Step 2 SampleInfo",
        )

        required_columns = ['Sample_Name', 'Sample_Type', 'Injection_Order']
        missing_cols = [col for col in required_columns if col not in sample_info_df.columns]

        if missing_cols:
            raise ValueError(
                f"'{SHEET_NAMES['sample_info']}' 缺少必要欄位: {', '.join(missing_cols)}。"
                f" 找到的欄位: {', '.join(sample_info_df.columns.tolist())}"
            )

        # ===== 防呆6-1: Batch 欄位處理 =====
        if 'Batch' not in sample_info_df.columns:
            sample_info_df['Batch'] = 'Batch1'
            print(f"⚠️  警告：'{SHEET_NAMES['sample_info']}' 缺少 'Batch' 欄位，已建立預設 Batch1")
        else:
            batch_na_mask = sample_info_df['Batch'].isna()
            if batch_na_mask.any():
                fill_value = 'Unknown'
                sample_info_df.loc[batch_na_mask, 'Batch'] = fill_value
                print(f"⚠️  警告：發現 {batch_na_mask.sum()} 個樣本缺少 Batch，已填入 '{fill_value}'")

        batch_summary = sample_info_df['Batch'].astype(str).value_counts().to_dict()

        # ===== 防呆7: 樣本名稱重複檢查 =====
        duplicate_samples = sample_info_df[sample_info_df['Sample_Name'].duplicated()]
        if not duplicate_samples.empty:
            print(f"⚠️  警告：'{SHEET_NAMES['sample_info']}' 中發現重複的樣本名稱:")
            for idx, row in duplicate_samples.iterrows():
                print(f"     - {row['Sample_Name']}")
            print(f"   建議：請檢查樣本名稱是否正確")

        # ===== 防呆8: 樣本類型檢查 =====
        sample_types = sample_info_df['Sample_Type'].unique()
        print(f"📊 樣本類型: {', '.join([str(t) for t in sample_types])}")

        qc_count = sample_info_df[sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)].shape[0]
        if qc_count == 0:
            raise ValueError("未找到 QC 樣本（Sample_Type 中無 'QC' 字樣）。QC-LOESS 校正需要至少 5 個 QC 樣本")
        elif qc_count < 5:
            print(f"⚠️  警告：QC 樣本數量不足 ({qc_count} < 5)")
            print(f"   提示：建議至少有 5 個 QC 樣本以確保校正準確性")
        else:
            print(f"✓ 找到 {qc_count} 個 QC 樣本")

        # ===== 防呆9: Injection_Order 有效性檢查 =====
        if 'Injection_Order' in sample_info_df.columns:
            invalid_orders = sample_info_df[pd.isna(sample_info_df['Injection_Order'])]
            if not invalid_orders.empty:
                print(f"⚠️  警告：發現 {len(invalid_orders)} 個樣本缺少 Injection_Order:")
                for idx, row in invalid_orders.head(5).iterrows():
                    print(f"     - {row['Sample_Name']}")
                if len(invalid_orders) > 5:
                    print(f"     ... 還有 {len(invalid_orders) - 5} 個樣本")

            # 檢查 Injection_Order 是否為數值
            try:
                sample_info_df['Injection_Order'] = pd.to_numeric(sample_info_df['Injection_Order'], errors='coerce')
                invalid_count = sample_info_df['Injection_Order'].isna().sum()
                if invalid_count > 0:
                    print(f"⚠️  警告：{invalid_count} 個樣本的 Injection_Order 無法轉換為數值")
            except Exception as e:
                print(f"⚠️  警告：Injection_Order 數據類型檢查失敗: {e}")

            # 針對缺失的注射順序提供連續的替補值，避免後續流程中止
            order_na_mask = sample_info_df['Injection_Order'].isna()
            if order_na_mask.any():
                existing_max = sample_info_df['Injection_Order'].max()
                if pd.isna(existing_max):
                    existing_max = 0
                filler = np.arange(1, order_na_mask.sum() + 1) + existing_max
                sample_info_df.loc[order_na_mask, 'Injection_Order'] = filler
                print(f"⚠️  警告：已為缺少 Injection_Order 的樣本指派遞增序號，請於 SampleInfo 中確認")

        # ===== 防呆10: ISTD_Correction 基本檢查 =====
        istd_df = pd.read_excel(excel_file, sheet_name=source_sheet_name)
        print(f"✓ 成功讀取 '{source_sheet_name}' 工作表，包含 {len(istd_df)} 個特徵")

        if istd_df.empty:
            raise ValueError(f"'{source_sheet_name}' 工作表為空")

        require_valid(
            validator.validate_raw_intensity(
                istd_df,
                sample_names=sample_info_df['Sample_Name'].tolist(),
                require_sample_match=True,
            ),
            context=f"Step 2 {source_sheet_name}",
        )

        # 支援 'Mz/RT' 或 'FeatureID' 作為特徵ID欄位
        if FEATURE_ID_COLUMN in istd_df.columns and FEATURE_ID_COLUMN != 'FeatureID':
            istd_df = istd_df.rename(columns={FEATURE_ID_COLUMN: 'FeatureID'})
        elif 'FeatureID' not in istd_df.columns:
            first_col = istd_df.columns[0]
            print(f"⚠️ 未找到 'FeatureID' 欄位，使用第一欄 '{first_col}' 作為特徵ID")
            istd_df = istd_df.rename(columns={first_col: 'FeatureID'})

        # ===== 提取 Sample_Type 資訊行（不參與數值計算，保存時回插）=====
        from metabolomics.utils.data_helpers import extract_sample_type_row
        istd_df, sample_type_row = extract_sample_type_row(istd_df, 'FeatureID')
        if sample_type_row is not None:
            print(f"✓ 偵測到 Sample_Type 資訊行，已提取保存（不參與計算）")

        # ===== 防呆11: FeatureID 重複檢查 =====
        duplicate_features = istd_df[istd_df['FeatureID'].duplicated(keep=False)]
        if not duplicate_features.empty:
            print(f"⚠️  警告：'{SHEET_NAMES['istd_correction']}' 中發現重複的 FeatureID:")
            dup_ids = duplicate_features['FeatureID'].unique()
            for fid in dup_ids[:5]:
                print(f"     - {fid}")
            if len(dup_ids) > 5:
                print(f"     ... 還有 {len(dup_ids) - 5} 個重複的 FeatureID")
            print(f"   建議：請檢查數據是否正確，腳本將保留第一次出現的記錄")

        # ===== 防呆12: 樣本欄位檢查 =====
        sample_columns, dropped_columns = identify_sample_columns(istd_df, sample_info_df)

        if len(sample_columns) == 0:
            raise ValueError(f"'{SHEET_NAMES['istd_correction']}' 中沒有匹配 {SHEET_NAMES['sample_info']} 的樣本欄位")

        print(f"✓ 找到 {len(sample_columns)} 個樣本欄位（來自 SampleInfo）")

        if dropped_columns:
            print(f"⚠️  警告：偵測到 {len(dropped_columns)} 個推定統計欄位，已自動排除：")
            for col in dropped_columns[:5]:
                print(f"     - {col}")
            if len(dropped_columns) > 5:
                print(f"     ... 還有 {len(dropped_columns) - 5} 個欄位")

        # ===== 防呆13: 樣本名稱匹配檢查 =====
        sample_names_in_info = set(sample_info_df['Sample_Name'].map(normalize_sample_name))
        sample_names_in_istd = {normalize_sample_name(col) for col in sample_columns}

        missing_in_istd = sample_names_in_info - sample_names_in_istd
        missing_in_info = sample_names_in_istd - sample_names_in_info

        if missing_in_istd:
            print(f"⚠️  警告：以下樣本在 SampleInfo 中有記錄，但在 {source_sheet_name} 中找不到:")
            for name in list(missing_in_istd)[:5]:
                print(f"     - {name}")
            if len(missing_in_istd) > 5:
                print(f"     ... 還有 {len(missing_in_istd) - 5} 個樣本")

        if missing_in_info:
            print(f"⚠️  警告：以下樣本在 {source_sheet_name} 中有數據，但在 SampleInfo 中找不到:")
            for name in list(missing_in_info)[:5]:
                print(f"     - {name}")
            if len(missing_in_info) > 5:
                print(f"     ... 還有 {len(missing_in_info) - 5} 個樣本")

        # ===== 防呆14: 強制轉換樣本欄位為數值 =====
        for col in sample_columns:
            istd_df[col] = pd.to_numeric(istd_df[col], errors='coerce')

        # ===== 防呆15: 全為 NaN 或 0 的列檢查 =====
        empty_columns = []
        for col in sample_columns:
            non_zero_count = (istd_df[col] > 0).sum()
            if non_zero_count == 0:
                empty_columns.append(col)

        if empty_columns:
            print(f"⚠️  警告：以下樣本的所有數值都是 0 或 NaN:")
            for col in empty_columns[:5]:
                print(f"     - {col}")
            if len(empty_columns) > 5:
                print(f"     ... 還有 {len(empty_columns) - 5} 個樣本")

        print(f"✓ {source_sheet_name} 數據類型檢查：樣本欄位已轉換為數值型")

        # ===== 防呆16: 數值範圍檢查 =====
        negative_count = 0
        extreme_high_count = 0

        for col in sample_columns:
            negative_values = (istd_df[col] < 0).sum()
            if negative_values > 0:
                negative_count += 1
                print(f"⚠️  警告：樣本 '{col}' 包含 {negative_values} 個負值")

            # 檢查極端高值（> 1e12）
            extreme_values = (istd_df[col] > 1e12).sum()
            if extreme_values > 0:
                extreme_high_count += 1
                print(f"⚠️  警告：樣本 '{col}' 包含 {extreme_values} 個極端高值 (> 1e12)")

        if negative_count > 0:
            print(f"   提示：已將負值設為 0")
            for col in sample_columns:
                istd_df[col] = istd_df[col].clip(lower=0)

        # 載入 RawIntensity（可選）
        raw_df = None
        if SHEET_NAMES['raw_intensity'] in excel_file.sheet_names:
            try:
                raw_df = pd.read_excel(excel_file, sheet_name=SHEET_NAMES['raw_intensity'])
                print(f"✓ 已載入 '{SHEET_NAMES['raw_intensity']}' 工作表（可選）")
            except Exception as e:
                print(f"⚠️  警告：無法載入 '{SHEET_NAMES['raw_intensity']}' 工作表: {e}")

        print(f"\n{'='*70}")
        print(f"✓ 數據載入完成")
        print(f"  - 特徵數: {len(istd_df)}")
        print(f"  - 樣本數: {len(sample_info_df)}")
        print(f"  - QC 樣本數: {qc_count}")
        if batch_summary:
            print(f"  - 批次分佈: {', '.join([f'{batch}:{count}' for batch, count in batch_summary.items()])}")
        print(f"{'='*70}\n")

        # 將識別出的樣本欄位保存於 DataFrame attrs，供後續流程使用
        istd_df = exclude_fallback_istd_rows(istd_df, file_path, source_sheet_name)
        istd_df.attrs['sample_columns'] = sample_columns
        istd_df.attrs['excluded_non_sample_columns'] = dropped_columns
        istd_df.attrs['source_sheet_name'] = source_sheet_name

        return raw_df, istd_df, sample_info_df, sample_type_row

    except Exception as e:
        print(f"❌ 載入數據失敗（未預期的錯誤）: {e}")
        import traceback
        traceback.print_exc()
        raise


# ========== ✅ 修正：統計檢定（Levene's test + 整體 Wilcoxon test）==========
def calculate_qc_cv_with_statistical_test(istd_df, lowess_df, sample_columns, sample_info_df, qc_corrected_values):
    """計算 QC CV% 並進行正確的統計檢定"""

    istd_df = istd_df.reset_index(drop=True)
    lowess_df = lowess_df.reset_index(drop=True)

    min_length = min(len(istd_df), len(lowess_df))
    istd_df = istd_df.iloc[:min_length]
    lowess_df = lowess_df.iloc[:min_length]

    print(f"\n{'='*70}")
    print(f"🔬 統計檢定")
    print(f"{'='*70}")

    # 識別 QC 樣本（優先從 SampleInfo 查找，若名稱不匹配則從欄位名稱判斷）
    if 'Sample_Type' in sample_info_df.columns:
        qc_names_from_info = sample_info_df[
            sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)
        ]['Sample_Name'].tolist()
        qc_columns = [col for col in qc_names_from_info if col in sample_columns]
    else:
        qc_columns = []

    # 如果 SampleInfo 名稱匹配不上，回退到從欄位名稱關鍵字判斷
    if not qc_columns:
        qc_columns = [col for col in sample_columns if 'QC' in col.upper() or 'POOLED' in col.upper()]
    print(f"  - QC 樣本數: {len(qc_columns)}")

    if len(qc_columns) == 0:
        print(f"  ❌ 錯誤：未找到任何 QC 樣本！")
        return pd.DataFrame()

    cv_results = []
    all_cv_improvements = []  # ✅ 收集所有 CV% 改善值（用於整體評估）

    print(f"\n  💡 統計方法:")
    print(f"     • Levene's test: 檢測方差是否顯著改變（單一特徵）")
    print(f"     • Wilcoxon test: 檢測 CV% 是否整體顯著降低（所有特徵）")

    for idx in range(len(istd_df)):
        try:
            istd_row = istd_df.iloc[idx]
            lowess_row = lowess_df.iloc[idx]
            feature_id = istd_row['FeatureID']

            if feature_id in qc_corrected_values:
                qc_corrected_dict = qc_corrected_values[feature_id]
                corrected_source = qc_corrected_dict
            else:
                corrected_source = lowess_row

            raw_qc = np.array(
                [pd.to_numeric(istd_row.get(qc), errors='coerce') for qc in qc_columns],
                dtype=float,
            )
            corrected_qc = np.array(
                [pd.to_numeric(corrected_source.get(qc), errors='coerce') for qc in qc_columns],
                dtype=float,
            )
            joint_valid = (
                np.isfinite(raw_qc)
                & np.isfinite(corrected_qc)
                & (raw_qc > 0)
                & (corrected_qc > 0)
            )
            qc_values_istd = raw_qc[joint_valid]
            qc_values_lowess = corrected_qc[joint_valid]

            if len(qc_values_istd) < 3:
                cv_results.append({
                    'FeatureID': feature_id,
                    'Original_QC_CV%': np.nan,
                    'Corrected_QC_CV%': np.nan,
                    'CV_Improvement%': np.nan,
                    'Original_Robust_CV%': np.nan,
                    'Corrected_Robust_CV%': np.nan,
                    'Robust_CV_Improvement%': np.nan,
                    'Variance_Test_pvalue': np.nan
                })
                continue

            # ========== 計算 CV% ==========
            original_cv = (np.std(qc_values_istd, ddof=1) / np.mean(qc_values_istd)) * 100
            corrected_cv = (np.std(qc_values_lowess, ddof=1) / np.mean(qc_values_lowess)) * 100
            cv_improvement = original_cv - corrected_cv

            # Robust CV (MAD/median) — 適用於非常態質譜數據
            orig_med = np.nanmedian(qc_values_istd)
            corr_med = np.nanmedian(qc_values_lowess)
            orig_mad = np.nanmedian(np.abs(qc_values_istd - orig_med))
            corr_mad = np.nanmedian(np.abs(qc_values_lowess - corr_med))
            original_robust_cv = (orig_mad / orig_med * 100) if orig_med > 0 else np.nan
            corrected_robust_cv = (corr_mad / corr_med * 100) if corr_med > 0 else np.nan
            robust_cv_improvement = original_robust_cv - corrected_robust_cv if np.isfinite(original_robust_cv) and np.isfinite(corrected_robust_cv) else np.nan

            # ✅ 收集 CV% 改善值（用於整體評估）
            if not np.isnan(cv_improvement):
                all_cv_improvements.append(cv_improvement)

            # ========== ✅ Levene's test（單一特徵）==========
            try:
                levene_stat, levene_pvalue = levene(qc_values_istd, qc_values_lowess)
            except Exception:
                levene_pvalue = np.nan

            cv_results.append({
                'FeatureID': feature_id,
                'Original_QC_CV%': original_cv,
                'Corrected_QC_CV%': corrected_cv,
                'CV_Improvement%': cv_improvement,
                'Original_Robust_CV%': original_robust_cv,
                'Corrected_Robust_CV%': corrected_robust_cv,
                'Robust_CV_Improvement%': robust_cv_improvement,
                'Variance_Test_pvalue': levene_pvalue
            })

            if (idx + 1) % 100 == 0:
                print(f"  處理進度: {idx + 1}/{len(istd_df)} features")

        except Exception as e:
            print(f"  ⚠️ 處理特徵 {idx} 時發生錯誤: {e}")
            continue

    cv_results_df = pd.DataFrame(cv_results)

    # ========== ✅ 整體評估：Wilcoxon test ==========
    print(f"\n{'='*70}")
    print(f"📊 整體校正效果評估")
    print(f"{'='*70}")

    if len(all_cv_improvements) >= 10:
        try:
            # 檢測 CV% 改善是否整體 > 0
            w_stat, w_pvalue = wilcoxon(all_cv_improvements, alternative='greater')

            print(f"\n  ✅ Wilcoxon Signed-Rank Test (整體評估):")
            print(f"     H₀: CV% 改善的中位數 = 0")
            print(f"     H₁: CV% 改善的中位數 > 0")
            print(f"     統計量: {w_stat:.2f}")
            print(f"     P-value: {w_pvalue:.4e}")

            if w_pvalue < 0.001:
                print(f"     結論: LOESS 校正顯著降低了 QC CV% (p < 0.001) ✅✅✅")
            elif w_pvalue < 0.01:
                print(f"     結論: LOESS 校正顯著降低了 QC CV% (p < 0.01) ✅✅")
            elif w_pvalue < 0.05:
                print(f"     結論: LOESS 校正顯著降低了 QC CV% (p < 0.05) ✅")
            else:
                print(f"     結論: LOESS 校正未顯著降低 QC CV% (p ≥ 0.05) ❌")

            # 描述性統計
            median_improvement = np.median(all_cv_improvements)
            mean_improvement = np.mean(all_cv_improvements)
            positive_improvements = np.sum(np.array(all_cv_improvements) > 0)

            print(f"\n  📊 CV% 改善的描述性統計:")
            print(f"     中位數改善: {median_improvement:.2f}%")
            print(f"     平均改善: {mean_improvement:.2f}%")
            print(f"     改善特徵比例: {positive_improvements}/{len(all_cv_improvements)} ({positive_improvements/len(all_cv_improvements)*100:.1f}%)")

        except Exception as e:
            print(f"  ⚠️ 整體評估失敗: {e}")
    else:
        print(f"  ⚠️ 有效特徵數不足 ({len(all_cv_improvements)} < 10)，跳過整體評估")

    print(f"{'='*70}\n")

    return cv_results_df


def plot_qc_cv_overview(cv_results_df, decision_stats, plots_dir, timestamp):
    """繪製 QC CV% 校正效果總覽圖（三面板）。

    Panel 1: applied features 的 Before/After QC CV% scatter
    Panel 2: applied features 的校正後絕對 QC CV% 分布
    Panel 3: fit、accepted batch tasks、applied features 中 QC CV 改善的比例
    """
    if cv_results_df is None or cv_results_df.empty:
        print("  ⚠ cv_results_df 為空，跳過 QC CV Overview")
        return

    plot_values = cv_results_df[
        ['Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%']
    ].apply(pd.to_numeric, errors='coerce')
    decision_status = cv_results_df.get(
        'Decision_Status',
        pd.Series('unknown', index=cv_results_df.index, dtype=object),
    ).fillna('unknown')
    applied_mask = decision_status.isin({'success', 'partial_success'})
    paired_mask = plot_values[['Original_QC_CV%', 'Corrected_QC_CV%']].notna().all(axis=1)
    applied_pairs = plot_values.loc[applied_mask & paired_mask]
    applied_improvements = plot_values.loc[
        applied_mask & plot_values['CV_Improvement%'].notna(),
        'CV_Improvement%',
    ].to_numpy()

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(20, 6.5))

    # ===== Panel 1: applied Before vs After scatter =====
    if not applied_pairs.empty:
        cv_b = applied_pairs['Original_QC_CV%'].to_numpy()
        cv_a = applied_pairs['Corrected_QC_CV%'].to_numpy()
        ax1.scatter(cv_b, cv_a, alpha=0.5, s=25, color='steelblue', edgecolors='none')
        lim = max(float(np.max(cv_b)), float(np.max(cv_a)), 1.0) * 1.05
        ax1.plot([0, lim], [0, lim], 'r--', linewidth=1.5, label='No change')
        ax1.set_xlim(0, lim)
        ax1.set_ylim(0, lim)
        improved = int(np.sum(cv_a < cv_b))
        ax1.text(
            0.05, 0.95,
            f'Applied features with lower QC CV: {improved}/{len(cv_b)} '
            f'({improved/len(cv_b)*100:.0f}%)',
            transform=ax1.transAxes, fontsize=10, va='top',
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8),
        )
        ax1.legend(fontsize=9, loc='lower right')
    else:
        ax1.text(
            0.5, 0.5, 'No applied features with paired QC CV values',
            ha='center', va='center', transform=ax1.transAxes, fontsize=11,
        )
    ax1.set_xlabel('QC CV% Before LOESS', fontsize=11, fontweight='bold')
    ax1.set_ylabel('QC CV% After LOESS', fontsize=11, fontweight='bold')
    ax1.set_title('Applied Feature QC CV% Change', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.set_aspect('equal', adjustable='box')

    # ===== Panel 2: applied absolute corrected QC CV =====
    corrected_applied = applied_pairs['Corrected_QC_CV%'].to_numpy()
    cv_bands = [
        int(np.sum(corrected_applied <= 20)),
        int(np.sum((corrected_applied > 20) & (corrected_applied <= 30))),
        int(np.sum(corrected_applied > 30)),
    ]
    ax2.bar(['≤20%', '20–30%', '>30%'], cv_bands,
            color=['#2ca02c', '#ffbf00', '#d62728'], alpha=0.8)
    for idx, count in enumerate(cv_bands):
        ax2.text(idx, count + 0.05, str(count), ha='center', fontsize=10, fontweight='bold')
    ax2.set_xlabel('Corrected QC CV% Band', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Applied Feature Count', fontsize=11, fontweight='bold')
    ax2.set_title('Applied Feature Absolute QC CV%', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')

    # ===== Panel 3: distinct fit / acceptance / outcome rates =====
    event_counts = decision_stats.get('event_counts', {})
    total_tasks = int(decision_stats.get('total_feature_batch_tasks', 0) or sum(event_counts.values()))
    fit_result_statuses = {
        'success', 'no_drift_detected', 'insufficient_improvement',
        'unstable_correction_factors', 'overcorrection_detected',
    }
    fit_attempted = sum(int(event_counts.get(status, 0)) for status in fit_result_statuses)
    accepted_batch_tasks = int(event_counts.get('success', 0))
    applied_cv_total = len(applied_pairs)
    applied_cv_improved = int(np.sum(applied_improvements > 0))
    rates = [
        fit_attempted / total_tasks * 100 if total_tasks else 0.0,
        accepted_batch_tasks / total_tasks * 100 if total_tasks else 0.0,
        applied_cv_improved / applied_cv_total * 100 if applied_cv_total else 0.0,
    ]
    labels = ['Fit attempted', 'Accepted batch tasks', 'QC CV improved\namong applied features']
    denominators = [total_tasks, total_tasks, applied_cv_total]
    numerators = [fit_attempted, accepted_batch_tasks, applied_cv_improved]
    bars = ax3.bar(labels, rates, color=['#4C72B0', '#2ca02c', '#55a868'], alpha=0.85)
    for bar, rate, numerator, denominator in zip(bars, rates, numerators, denominators):
        ax3.text(
            bar.get_x() + bar.get_width() / 2,
            rate + 1,
            f'{numerator}/{denominator}\n({rate:.0f}%)',
            ha='center', fontsize=9, fontweight='bold',
        )
    ax3.set_ylim(0, 110)
    ax3.set_ylabel('Rate (%)', fontsize=11, fontweight='bold')
    ax3.set_title('Fit, Acceptance, and QC CV Outcome', fontsize=13, fontweight='bold')
    ax3.tick_params(axis='x', labelrotation=10)
    ax3.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()

    os.makedirs(plots_dir, exist_ok=True)
    output_path = os.path.join(plots_dir, f'Step2_QC_CV_Overview_{timestamp}.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  ✓ QC CV Overview 圖已儲存")


# ========== P 值分佈圖（只繪製 Levene's test，目前停用）==========
def plot_pvalue_distribution(cv_results_df, plots_dir, timestamp):
    """繪製 Levene's test p 值分佈圖（含防呆檢查）"""
    try:
        # ===== 防呆1: 輸入數據檢查 =====
        if cv_results_df is None or cv_results_df.empty:
            print("  ⚠️  警告：CV 結果數據為空，無法繪製 p 值分佈圖")
            return

        if 'Variance_Test_pvalue' not in cv_results_df.columns:
            print("  ⚠️  警告：找不到 Variance_Test_pvalue 欄位，無法繪製 p 值分佈圖")
            return

        # ===== 防呆2: 輸出目錄檢查 =====
        if plots_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.join(script_dir, 'output', 'QC_LOESS_plots')
            os.makedirs(base_dir, exist_ok=True)
            plots_dir = os.path.join(base_dir, f"QC_LOESS_{timestamp}")

        try:
            os.makedirs(plots_dir, exist_ok=True)
        except Exception as e:
            print(f"  ⚠️  警告：無法創建輸出目錄: {e}")
            return

        if not os.access(plots_dir, os.W_OK):
            print(f"  ⚠️  警告：沒有寫入權限到目錄: {plots_dir}")
            return

        levene_pvalues = cv_results_df['Variance_Test_pvalue'].dropna()

        if len(levene_pvalues) < 10:
            print("  ⚠️ 有效 p 值數量不足，跳過 p 值分佈圖")
            return

        # 只繪製 Levene's test 的 p 值分佈
        fig, ax = plt.subplots(1, 1, figsize=(10, 7))

        ax.hist(levene_pvalues, bins=20, color='steelblue', edgecolor='black', alpha=0.7)
        ax.axhline(y=len(levene_pvalues)/20, color='red', linestyle='--', linewidth=2,
                   label='Uniform Distribution Expected')
        ax.set_xlabel('P-value (Levene\'s Test)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Frequency', fontsize=12, fontweight='bold')
        ax.set_title('P-value Distribution\n(Variance Homogeneity Test)',
                     fontsize=14, fontweight='bold')
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='--')

        # Kolmogorov-Smirnov 檢定
        from scipy.stats import kstest
        ks_stat, ks_pvalue = kstest(levene_pvalues, 'uniform')

        textstr = f'Kolmogorov-Smirnov Test:\n'
        textstr += f'Statistic = {ks_stat:.4f}\n'
        textstr += f'P-value = {ks_pvalue:.4f}\n'
        if ks_pvalue > 0.05:
            textstr += 'Result: Uniform ✓'
        else:
            textstr += 'Result: Non-uniform ✗'

        ax.text(0.98, 0.97, textstr, transform=ax.transAxes,
                fontsize=10, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.tight_layout()

        pvalue_plot_path = os.path.join(plots_dir, f'Step2_Pvalue_Distribution_Levene_{timestamp}.png')

        # ===== 防呆: 圖表保存檢查 =====
        try:
            plt.savefig(pvalue_plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            # 驗證文件是否成功保存
            if not os.path.exists(pvalue_plot_path):
                print(f"\n⚠️  警告：P 值分佈圖保存失敗，找不到輸出檔案")
                return
            else:
                plot_size = os.path.getsize(pvalue_plot_path)
                if plot_size == 0:
                    print(f"\n⚠️  警告：P 值分佈圖大小為 0 bytes")
                    return

            print(f"\n✓ P 值分佈圖已儲存: {pvalue_plot_path}")
            print(f"  - 圖表大小: {plot_size / 1024:.2f} KB")
        except Exception as e:
            plt.close()
            print(f"\n⚠️  警告：保存 P 值分佈圖時發生錯誤: {e}")
            return
        print(f"  - Kolmogorov-Smirnov 檢定: KS={ks_stat:.4f}, p={ks_pvalue:.4f}")
        if ks_pvalue > 0.05:
            print(f"  - 結論: p 值分佈接近均勻分佈 ✓")
        else:
            print(f"  - 結論: p 值分佈偏離均勻分佈 ✗")

    except Exception as e:
        print(f"  ⚠️ 繪製 p 值分佈圖時發生錯誤: {e}")
        import traceback
        traceback.print_exc()


def plot_lowess_trend_fitting(trend_data_dict, plots_dir, timestamp, max_per_page=6):
    """繪製 LOWESS 擬合趨勢圖（同一特徵一張圖）。

    目的：讓同一個 feature 在不同 batch 的趨勢能直接比較。

    Args:
        trend_data_dict: dict, {(feature_id, batch_name): plot_data}
        plots_dir: 輸出目錄
        timestamp: 時間戳記
        max_per_page: 保留參數（舊版多特徵拼頁用）；新版不使用。
    """
    try:
        if not trend_data_dict:
            print("  ⚠️  警告：沒有趨勢擬合數據可繪製")
            return

        # 確保輸出目錄存在
        if plots_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.join(script_dir, 'output', 'QC_LOESS_plots')
            os.makedirs(base_dir, exist_ok=True)
            plots_dir = os.path.join(base_dir, f"QC_LOESS_{timestamp}")

        try:
            os.makedirs(plots_dir, exist_ok=True)
        except Exception as e:
            print(f"  ⚠️  警告：無法創建輸出目錄: {e}")
            return

        if not os.access(plots_dir, os.W_OK):
            print(f"  ⚠️  警告：沒有寫入權限到目錄: {plots_dir}")
            return

        # 將數據按 feature 分組（同特徵一張圖）
        feature_grouped = {}
        for (feature_id, batch_name), plot_data in trend_data_dict.items():
            feature_grouped.setdefault(feature_id, []).append((batch_name, plot_data))

        total_features = len(feature_grouped)
        print(f"\n📊 繪製 LOESS 擬合趨勢圖（同特徵一張）：{total_features} 個特徵...")

        feature_count = 0
        for feature_id, batch_items in feature_grouped.items():
            # 依 batch 名稱排序
            batch_items_sorted = sorted(batch_items, key=lambda x: str(x[0]))
            n_batches = len(batch_items_sorted)

            if n_batches == 0:
                continue

            # 每個 batch 一列：左 Raw+Fit、右 Before vs After
            fig, axes = plt.subplots(
                n_batches,
                2,
                figsize=(14, max(4.2, 4.2 * n_batches)),
                squeeze=False,
            )

            for row_idx, (batch_name, plot_data) in enumerate(batch_items_sorted):
                try:
                    qc_orders = np.array(plot_data['qc_orders'])
                    qc_raw = np.array(plot_data['qc_raw'])
                    qc_corrected = np.array(plot_data['qc_corrected'])
                    lowess_x = np.array(plot_data['lowess_x'])
                    lowess_y = np.array(plot_data['lowess_y'])
                    median_qc = plot_data['median_qc']

                    ax1 = axes[row_idx, 0]
                    ax2 = axes[row_idx, 1]

                    # ===== 左圖：Raw vs LOESS =====
                    ax1.scatter(
                        qc_orders,
                        qc_raw,
                        c='#0173B2',
                        s=55,
                        alpha=0.75,
                        edgecolors='black',
                        linewidth=0.8,
                        label='QC Raw',
                        zorder=3,
                    )
                    ax1.plot(lowess_x, lowess_y, 'r-', linewidth=2, label='LOESS Fit', zorder=2)
                    ax1.axhline(
                        y=median_qc,
                        color='green',
                        linestyle='--',
                        linewidth=1.5,
                        label=f'Median={median_qc:.1f}',
                        zorder=1,
                    )
                    ax1.set_xlabel('Injection Order', fontsize=10)
                    ax1.set_ylabel('Intensity', fontsize=10)
                    ax1.set_title(f'Batch: {batch_name}  |  Raw + LOESS Fit', fontsize=11, fontweight='bold')
                    ax1.legend(fontsize=8, loc='best')
                    ax1.grid(True, alpha=0.3, linestyle='--')

                    # ===== 右圖：Before vs After =====
                    ax2.scatter(
                        qc_orders,
                        qc_raw,
                        c='#F0E442',
                        s=65,
                        alpha=1.0,
                        edgecolors='black',
                        linewidth=0.8,
                        label='Raw',
                        zorder=2,
                    )
                    ax2.scatter(
                        qc_orders,
                        qc_corrected,
                        c='#D55E00',
                        s=55,
                        alpha=0.95,
                        edgecolors='black',
                        linewidth=0.8,
                        label='Corrected',
                        zorder=3,
                    )
                    ax2.axhline(y=median_qc, color='green', linestyle='--', linewidth=1.5, label='Target', zorder=1)
                    ax2.set_xlabel('Injection Order', fontsize=10)
                    ax2.set_ylabel('Intensity', fontsize=10)
                    ax2.set_title('Before vs After Correction', fontsize=11, fontweight='bold')
                    ax2.legend(fontsize=8, loc='best')
                    ax2.grid(True, alpha=0.3, linestyle='--')

                except Exception as e:
                    print(f"  ⚠️  警告：繪製 {feature_id} / {batch_name} 時發生錯誤: {e}")
                    continue

            fig.suptitle(f'LOESS Trend Fitting (Feature = {feature_id})', fontsize=14, fontweight='bold', y=0.99)
            plt.tight_layout(rect=[0, 0, 1, 0.97])

            safe_feature = str(feature_id).replace('/', '_').replace('\\', '_').replace(':', '_')
            plot_path = os.path.join(plots_dir, f'Step2_Trend_Fitting_Feature_{safe_feature}_{timestamp}.png')
            plt.savefig(plot_path, dpi=200, bbox_inches='tight')
            plt.close(fig)

            feature_count += 1
            if os.path.exists(plot_path):
                plot_size = os.path.getsize(plot_path)
                if plot_size > 0:
                    print(f"  ✓ 已保存: {safe_feature} ({n_batches} batches) - {plot_size / 1024:.1f} KB")
                else:
                    print(f"  ⚠️  警告：{safe_feature} 圖表大小為 0 bytes")
            else:
                print(f"  ⚠️  警告：{safe_feature} 圖表保存失敗")

        print(f"✓ LOESS 擬合趨勢圖繪製完成（共 {feature_count} 張，一特徵一張）")

    except Exception as e:
        print(f"  ⚠️ 繪製 LOESS 擬合趨勢圖時發生錯誤: {e}")
        import traceback
        traceback.print_exc()




# ========== ✅ 修正：保存結果到 Excel（移除 Wilcoxon_pvalue）==========
def save_results_to_excel(raw_df, istd_df, lowess_df, sample_info_df, sample_columns,
                          output_file, input_file, qc_corrected_values,
                          trend_stats_df, decision_stats, plots_dir=None, trend_plot_data=None,
                          sample_type_row=None):
    """保存結果到 Excel（含完整防呆檢查）"""
    try:
        # ===== 防呆1: 輸入數據有效性檢查 =====
        if istd_df is None or istd_df.empty:
            print(f"❌ 錯誤：ISTD_Correction 數據為空，無法保存")
            return False

        if lowess_df is None or lowess_df.empty:
            print(f"❌ 錯誤：LOESS 校正結果為空，無法保存")
            return False

        if sample_info_df is None or sample_info_df.empty:
            print(f"❌ 錯誤：SampleInfo 數據為空，無法保存")
            return False

        # ===== 防呆2: 輸出路徑有效性檢查 =====
        output_dir = os.path.dirname(output_file)
        if not os.path.exists(output_dir):
            print(f"⚠️  警告：輸出目錄不存在，嘗試創建: {output_dir}")
            try:
                os.makedirs(output_dir, exist_ok=True)
                print(f"✓ 成功創建輸出目錄")
            except Exception as e:
                print(f"❌ 錯誤：無法創建輸出目錄: {e}")
                return False

        # ===== 防呆3: 輸出目錄可寫性檢查 =====
        if not os.access(output_dir, os.W_OK):
            print(f"❌ 錯誤：沒有寫入權限到目錄: {output_dir}")
            return False

        # ===== 防呆4: 輸入文件有效性檢查 =====
        if not os.path.exists(input_file):
            print(f"❌ 錯誤：找不到輸入檔案: {input_file}")
            return False
        cv_results_df = calculate_qc_cv_with_statistical_test(
            istd_df,
            lowess_df,
            sample_columns,
            sample_info_df,
            qc_corrected_values
        )

        # ✅ 主表：只保留 Levene's test 和 CV%
        lowess_with_cv = lowess_df.merge(cv_results_df, on='FeatureID', how='left')
        lowess_with_cv = apply_feature_metadata_passthrough(lowess_with_cv, istd_df)

        # ✅ 主表欄位順序（移除 Wilcoxon_pvalue 和 Significant_Improvement）
        cols_order = [
            'Original_QC_CV%',
            'Corrected_QC_CV%',
            'CV_Improvement%',
            'Variance_Test_pvalue'  # 只保留 Levene's test
        ]
        other_cols = [col for col in lowess_with_cv.columns if col not in cols_order]
        lowess_with_cv = lowess_with_cv[other_cols + cols_order]

        # ✅ 副表：進階統計指標
        advanced_stats_df = lowess_df[['FeatureID']].merge(
            trend_stats_df, on='FeatureID', how='left'
        )

        def _fmt(value, digits=2, pct=False):
            if value is None:
                return "N/A"
            try:
                value = float(value)
            except (TypeError, ValueError):
                return str(value)
            if not np.isfinite(value):
                return "N/A"
            suffix = "%" if pct else ""
            return f"{value:.{digits}f}{suffix}"

        total_count = len(cv_results_df)
        cv_before = pd.to_numeric(cv_results_df['Original_QC_CV%'], errors='coerce')
        cv_after = pd.to_numeric(cv_results_df['Corrected_QC_CV%'], errors='coerce')
        cv_improvement = pd.to_numeric(cv_results_df['CV_Improvement%'], errors='coerce')
        variance_p = pd.to_numeric(cv_results_df['Variance_Test_pvalue'], errors='coerce')
        tau_values = pd.to_numeric(trend_stats_df.get('Kendall_Tau'), errors='coerce')
        trend_pvalues = pd.to_numeric(trend_stats_df.get('Trend_pvalue'), errors='coerce')
        r2_values = pd.to_numeric(trend_stats_df.get('LOESS_R2'), errors='coerce')
        rmse_values = pd.to_numeric(trend_stats_df.get('LOESS_RMSE'), errors='coerce')
        normalized_rmse_values = pd.to_numeric(trend_stats_df.get('Normalized_RMSE'), errors='coerce')
        valid_qc_counts = pd.to_numeric(trend_stats_df.get('Valid_QC_Count'), errors='coerce')
        removed_outliers = pd.to_numeric(trend_stats_df.get('Removed_QC_Outliers'), errors='coerce')
        clamped_ratios = pd.to_numeric(trend_stats_df.get('Clamped_Factor_Ratio'), errors='coerce')
        outside_range_counts = pd.to_numeric(trend_stats_df.get('Outside_QC_Range_Count'), errors='coerce')
        frac_values = pd.to_numeric(trend_stats_df.get('Frac_Used'), errors='coerce')
        frac_strategy_counts = (
            trend_stats_df['Frac_Strategy'].fillna('unknown').value_counts().to_dict()
            if 'Frac_Strategy' in trend_stats_df.columns else {}
        )
        wilcoxon_pvalue = np.nan
        valid_cv_mask = ~(cv_before.isna() | cv_after.isna())
        if valid_cv_mask.sum() >= 3:
            try:
                wilcoxon_pvalue = float(
                    wilcoxon(
                        cv_before[valid_cv_mask],
                        cv_after[valid_cv_mask],
                        alternative='greater',
                    ).pvalue
                )
            except (ValueError, TypeError):
                wilcoxon_pvalue = np.nan

        frac_range_value = "N/A"
        if np.isfinite(frac_values).any():
            frac_range_value = (
                f"{_fmt(np.nanmin(frac_values), digits=2)} - "
                f"{_fmt(np.nanmax(frac_values), digits=2)}"
            )

        evaluable_cv_improvement = cv_improvement.dropna()
        median_cv_improvement = (
            float(np.nanmedian(evaluable_cv_improvement))
            if not evaluable_cv_improvement.empty
            else np.nan
        )
        improved_ratio = (
            float((evaluable_cv_improvement > 0).mean() * 100)
            if not evaluable_cv_improvement.empty
            else np.nan
        )
        feature_status = cv_results_df['FeatureID'].map(
            trend_stats_df.set_index('FeatureID')['Decision_Status']
        )
        applied_feature_mask = feature_status.isin({'success', 'partial_success'})
        applied_cv_improvement = cv_improvement[applied_feature_mask].dropna()
        applied_improved_ratio = (
            float((applied_cv_improvement > 0).mean() * 100)
            if not applied_cv_improvement.empty
            else np.nan
        )
        if (
            np.isfinite(median_cv_improvement)
            and median_cv_improvement >= 10
            and np.isfinite(wilcoxon_pvalue)
            and wilcoxon_pvalue < 0.05
            and improved_ratio >= 70
        ):
            overall_readout = "Strong feature-level improvement"
        elif np.isfinite(median_cv_improvement) and median_cv_improvement > 0 and improved_ratio >= 50:
            overall_readout = "Moderate feature-level improvement"
        elif np.isfinite(median_cv_improvement) and median_cv_improvement > 0:
            overall_readout = "Limited feature-level improvement"
        else:
            overall_readout = "No convincing feature-level improvement"

        summary_pairs = [
            ("LOESS Summary", ""),
            ("Overview", ""),
            ("Report generated", datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            ("Upstream sheet", istd_df.attrs.get('source_sheet_name', SHEET_NAMES['istd_correction'])),
            ("Features processed", total_count),
            ("Overall readout", overall_readout),
            ("QC reproducibility", ""),
            ("Median QC CV before", _fmt(np.nanmedian(cv_before), pct=True)),
            ("Median QC CV after", _fmt(np.nanmedian(cv_after), pct=True)),
            ("Median QC CV improvement", _fmt(median_cv_improvement, pct=True)),
            ("Wilcoxon p-value", _fmt(wilcoxon_pvalue, digits=4)),
            (
                "QC CV improved (all evaluable)",
                _fmt(improved_ratio, digits=1, pct=True),
            ),
            (
                "QC CV >5% improved (all evaluable)",
                _fmt(
                    (evaluable_cv_improvement > 5).mean() * 100
                    if not evaluable_cv_improvement.empty else np.nan,
                    digits=1,
                    pct=True,
                ),
            ),
            ("Worsened features (all evaluable)", int((evaluable_cv_improvement < 0).sum())),
            ("Features with applied correction", int(applied_feature_mask.sum())),
            (
                "QC CV improved among applied features",
                _fmt(applied_improved_ratio, digits=1, pct=True),
            ),
            ("Batch execution", ""),
            ("All-batch success", decision_stats.get('success', 0)),
            ("All-batch no drift detected", decision_stats.get('no_drift_detected', 0)),
            ("Partial success", decision_stats.get('partial_success', 0)),
            (
                "No successful batch",
                total_count
                - decision_stats.get('success', 0)
                - decision_stats.get('no_drift_detected', 0)
                - decision_stats.get('partial_success', 0),
            ),
            ("Variance and fit diagnostics", ""),
            (
                "Variance test p<0.05",
                _fmt((variance_p < 0.05).mean() * 100 if total_count else np.nan, digits=1, pct=True),
            ),
            ("Trend p-value median", _fmt(np.nanmedian(trend_pvalues), digits=4)),
            ("Kendall tau median", _fmt(np.nanmedian(tau_values), digits=4)),
            ("LOESS R2 median", _fmt(np.nanmedian(r2_values), digits=4)),
            ("LOESS RMSE median", _fmt(np.nanmedian(rmse_values), digits=2)),
            ("Normalized RMSE median", _fmt(np.nanmedian(normalized_rmse_values), digits=4)),
            ("Valid QC count median", _fmt(np.nanmedian(valid_qc_counts), digits=1)),
            ("Median removed QC outliers", _fmt(np.nanmedian(removed_outliers), digits=1)),
            ("Median clamp ratio", _fmt(np.nanmedian(clamped_ratios), digits=4)),
            (
                "Features using edge extrapolation",
                _fmt((outside_range_counts > 0).mean() * 100 if total_count else np.nan, digits=1, pct=True),
            ),
            ("Frac diagnostics", ""),
            ("Frac median", _fmt(np.nanmedian(frac_values), digits=2)),
            ("Frac range", frac_range_value),
        ]
        for strategy, count in frac_strategy_counts.items():
            summary_pairs.append((f"Frac strategy: {strategy}", count))

        print(f"\n📋 開始處理 Excel 檔案...")
        print(f"  - 載入原始檔案: {os.path.basename(input_file)}")

        def sanitize_excel_df(df):
            if df is None:
                return None
            return df.replace([np.inf, -np.inf], np.nan)

        istd_export = sanitize_excel_df(istd_df)
        lowess_export = sanitize_excel_df(lowess_with_cv)
        advanced_export = sanitize_excel_df(advanced_stats_df)
        sample_info_export = sanitize_excel_df(sample_info_df)
        source_sheet_name = istd_df.attrs.get('source_sheet_name', SHEET_NAMES['istd_correction'])
        source_export = istd_export
        source_export_is_original = False

        if source_sheet_name == SHEET_NAMES['raw_intensity'] and raw_df is not None:
            source_export = sanitize_excel_df(raw_df.copy())
            source_export_is_original = True

        # ===== 回插 Sample_Type 資訊行（若有）=====
        if sample_type_row is not None:
            from metabolomics.utils.data_helpers import insert_sample_type_row
            if not source_export_is_original:
                source_export = insert_sample_type_row(source_export, sample_type_row)
            lowess_export = insert_sample_type_row(lowess_export, sample_type_row)

        sheets_to_write = [
            (source_sheet_name, source_export),
            (SHEET_NAMES['qc_lowess'], lowess_export),
            (QC_LOWESS_ADVANCED_SHEET, advanced_export),
            (SHEET_NAMES['sample_info'], sample_info_export),
        ]

        # 輸出時將內部欄名 'FeatureID' 還原為 FEATURE_ID_COLUMN
        def _rename_feature_col(df):
            if 'FeatureID' in df.columns and FEATURE_ID_COLUMN != 'FeatureID':
                return df.rename(columns={'FeatureID': FEATURE_ID_COLUMN})
            return df

        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            for sheet_name, df in sheets_to_write:
                _rename_feature_col(df).to_excel(writer, sheet_name=sheet_name, index=False)

        workbook = load_workbook(output_file)

        scientific_format = '0.00E+00'
        advanced_table_width = len(advanced_export.columns)

        if SHEET_NAMES['sample_info'] in workbook.sheetnames:
            apply_header_fill(workbook[SHEET_NAMES['sample_info']])

        # 主表顏色標記
        if SHEET_NAMES['qc_lowess'] in workbook.sheetnames:
            worksheet = workbook[SHEET_NAMES['qc_lowess']]
            header = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            header_map = {name: idx + 1 for idx, name in enumerate(header) if name}

            apply_header_fill(worksheet)

            for col_name in header:
                if not col_name or is_non_sample_column(col_name):
                    continue
                apply_number_format(worksheet, header_map[col_name], scientific_format)

            for col_name in ['Original_QC_CV%', 'Corrected_QC_CV%']:
                if col_name in header_map:
                    apply_cv_quality_fill(worksheet, header_map[col_name])
                    apply_number_format(worksheet, header_map[col_name], '0.00')

            if 'CV_Improvement%' in header_map:
                apply_improvement_fill(worksheet, header_map['CV_Improvement%'])
                apply_number_format(worksheet, header_map['CV_Improvement%'], '+0.00;-0.00')

            if 'Variance_Test_pvalue' in header:
                col_idx = header.index('Variance_Test_pvalue') + 1
                apply_significance_fill(worksheet, col_idx)
                apply_number_format(worksheet, col_idx, '0.0000')

        # 副表顏色標記
        if QC_LOWESS_ADVANCED_SHEET in workbook.sheetnames:
            worksheet = workbook[QC_LOWESS_ADVANCED_SHEET]
            header = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            header_map = {name: idx + 1 for idx, name in enumerate(header) if name}

            apply_header_fill(worksheet, max_col=advanced_table_width)

            if 'Kendall_Tau' in header_map:
                apply_band_fill(
                    worksheet,
                    header_map['Kendall_Tau'],
                    excellent=0.3,
                    acceptable=0.5,
                    use_abs=True,
                )
                apply_number_format(worksheet, header_map['Kendall_Tau'], '0.000')

            if 'LOESS_R2' in header_map:
                apply_band_fill(
                    worksheet,
                    header_map['LOESS_R2'],
                    excellent=0.9,
                    acceptable=0.7,
                    higher_is_better=True,
                )
                apply_number_format(worksheet, header_map['LOESS_R2'], '0.000')

            if 'LOESS_RMSE' in header_map:
                apply_number_format(worksheet, header_map['LOESS_RMSE'], '0.00')

            if 'Frac_Used' in header_map:
                apply_number_format(worksheet, header_map['Frac_Used'], '0.00')

            if 'QC_CV_for_Frac' in header_map:
                apply_cv_quality_fill(worksheet, header_map['QC_CV_for_Frac'])
                apply_number_format(worksheet, header_map['QC_CV_for_Frac'], '0.00')

            summary_col = advanced_table_width + 3
            value_col = summary_col + 1

            for row_idx, (label, value) in enumerate(summary_pairs, start=1):
                label_cell = worksheet.cell(row=row_idx, column=summary_col, value=label)
                value_cell = worksheet.cell(row=row_idx, column=value_col, value=value)
                label_cell.alignment = Alignment(horizontal='left')
                value_cell.alignment = Alignment(horizontal='left')
                value_cell.font = Font(color=STRUCTURE_FONT_COLOR)

                if row_idx == 1:
                    label_cell.font = Font(bold=True, size=12, color=STRUCTURE_FONT_COLOR)
                    label_cell.fill = SECTION_TITLE_FILL
                    value_cell.value = None
                    value_cell.fill = SECTION_TITLE_FILL
                    value_cell.font = Font(color=STRUCTURE_FONT_COLOR, bold=True, size=12)
                elif value == "":
                    label_cell.font = Font(bold=True, color=STRUCTURE_FONT_COLOR)
                    label_cell.fill = SECTION_DIVIDER_FILL
                    value_cell.value = None
                    value_cell.fill = SECTION_DIVIDER_FILL
                    value_cell.font = Font(color=STRUCTURE_FONT_COLOR, bold=True)
                else:
                    label_cell.font = Font(bold=True, color=STRUCTURE_FONT_COLOR)
                    label_cell.fill = SECTION_LABEL_FILL
                    if isinstance(value, (int, float)) and not pd.isna(value):
                        value_cell.number_format = '0.00'

            worksheet.column_dimensions[get_column_letter(summary_col)].width = 28
            worksheet.column_dimensions[get_column_letter(value_col)].width = 24

        # ===== 防呆5: 文件保存檢查 =====
        try:
            workbook.save(output_file)
            print(f"✓ 成功保存 Excel 檔案")
        except PermissionError:
            print(f"❌ 錯誤：無法保存檔案，可能檔案已被其他程式開啟")
            print(f"   請關閉檔案後重試: {output_file}")
            workbook.close()
            return False
        except Exception as e:
            print(f"❌ 錯誤：保存檔案時發生錯誤: {e}")
            workbook.close()
            return False

        workbook.close()

        # ===== 防呆6: 文件保存驗證 =====
        if not os.path.exists(output_file):
            print(f"❌ 錯誤：檔案保存失敗，找不到輸出檔案: {output_file}")
            return False

        # 檢查文件大小
        output_size = os.path.getsize(output_file)
        if output_size == 0:
            print(f"❌ 錯誤：輸出檔案大小為 0 bytes")
            return False
        elif output_size < 1024:
            print(f"⚠️  警告：輸出檔案大小異常小 ({output_size} bytes)")

        print(f"✓ 輸出檔案大小: {output_size / 1024:.2f} KB")

        # ✅ 統計報告
        print(f"\n{'='*70}")
        print(f"✓ QC LOESS 結果已保存:")
        print(f"  {output_file}")
        print(f"{'='*70}")

        total_count = len(cv_results_df)

        print(f"\n📊 核心統計摘要（主表）:")
        print(f"  - 總特徵數: {total_count}")

        # CV% 改善統計
        cv_improvements = cv_results_df['CV_Improvement%'].dropna()
        if len(cv_improvements) > 0:
            print(f"\n  📈 CV% 改善:")
            print(f"     平均: {cv_improvements.mean():.2f}%")
            print(f"     中位數: {cv_improvements.median():.2f}%")
            print(f"     範圍: {cv_improvements.min():.2f}% ~ {cv_improvements.max():.2f}%")

            improved = (cv_improvements > 5).sum()
            similar = ((cv_improvements >= -5) & (cv_improvements <= 5)).sum()
            worse = (cv_improvements < -5).sum()

            print(f"\n  分類:")
            print(f"     顯著改善 (>5%): {improved} ({improved/len(cv_improvements)*100:.1f}%)")
            print(f"     持平 (±5%): {similar} ({similar/len(cv_improvements)*100:.1f}%)")
            print(f"     變差 (<-5%): {worse} ({worse/len(cv_improvements)*100:.1f}%)")

        # Levene's test 統計
        levene_valid = cv_results_df['Variance_Test_pvalue'].notna().sum()
        levene_sig = ((cv_results_df['Variance_Test_pvalue'] < 0.05) &
                      (cv_results_df['Variance_Test_pvalue'].notna())).sum()

        print(f"\n  🔬 Levene's Test（方差齊性）:")
        print(f"     成功執行: {levene_valid}/{total_count} ({levene_valid/total_count*100:.1f}%)")
        if levene_valid > 0:
            print(f"     方差顯著改變 (p < 0.05): {levene_sig}/{levene_valid} ({levene_sig/levene_valid*100:.1f}%)")

        # 校正決策統計
        feature_total = decision_stats.get('total_features', total_count)
        feature_success = decision_stats.get('success', 0)
        feature_no_drift = decision_stats.get('no_drift_detected', 0)
        feature_partial = decision_stats.get('partial_success', 0)
        feature_no_success = max(
            feature_total - feature_success - feature_no_drift - feature_partial,
            0,
        )

        def pct(value, base):
            return (value / base * 100) if base else 0

        print(f"\n📊 校正決策統計:")
        print(f"  ✅ 全批次成功: {feature_success} ({pct(feature_success, feature_total):.1f}%)")
        print(f"  ○ 全批次無需校正: {feature_no_drift} ({pct(feature_no_drift, feature_total):.1f}%)")
        print(f"  ⚠️ 部分批次成功: {feature_partial} ({pct(feature_partial, feature_total):.1f}%)")
        print(f"  ❌ 無成功批次: {feature_no_success} ({pct(feature_no_success, feature_total):.1f}%)")

        print(f"\n  無成功批次的主要原因:")
        for key, label in [
            ('insufficient_qc', 'QC 樣本不足'),
            ('insufficient_improvement', 'CV% 改善不足 (<2%)'),
            ('unstable_correction_factors', '校正因子不穩定'),
            ('overcorrection_detected', '檢測到過度校正'),
            ('failed', '其他錯誤')
        ]:
            value = decision_stats.get(key, 0)
            if value:
                print(f"    • {label}: {value}")

        event_counts = decision_stats.get('event_counts')
        if event_counts:
            total_events = decision_stats.get('total_feature_batch_tasks', sum(event_counts.values()))
            print(f"\n  批次層級決策 (feature × batch):")
            for status, count in event_counts.items():
                if count:
                    print(f"    • {status}: {count} ({pct(count, total_events):.1f}%)")

        per_batch_stats = decision_stats.get('per_batch')
        if per_batch_stats:
            print(f"\n  各批次摘要:")
            for batch_name, stats_dict in per_batch_stats.items():
                batch_total = sum(stats_dict.values())
                batch_success = stats_dict.get('success', 0)
                print(f"    • Batch {batch_name}: 成功 {batch_success}/{batch_total} ({pct(batch_success, batch_total):.1f}%)")

        frac_counter = decision_stats.get('frac_usage_counter') or {}
        frac_values_global = decision_stats.get('frac_value_list', [])
        if frac_counter:
            total_features = decision_stats.get('total_features', total_count) or 1
            high_count = frac_counter.get('high_variation', 0)
            medium_count = frac_counter.get('medium_variation', 0)
            low_count = frac_counter.get('low_variation_dynamic', 0)
            other_count = max(total_features - (high_count + medium_count + low_count), 0)
            frac_mean = float(np.nanmean(frac_values_global)) if frac_values_global else np.nan
            frac_median = float(np.nanmedian(frac_values_global)) if frac_values_global else np.nan

            def frac_pct(count):
                return (count / total_features * 100) if total_features else 0

            def fmt_frac_value(value):
                return f"{value:.2f}" if np.isfinite(value) else "N/A"

            print(f"\n  📊 Frac 使用統計：")
            print(f"     - 高變異策略 (frac=0.8): {high_count} ({frac_pct(high_count):.1f}%)")
            print(f"     - 中等變異策略 (frac=0.7): {medium_count} ({frac_pct(medium_count):.1f}%)")
            print(f"     - 低變異動態策略 (frac=0.5~0.75): {low_count} ({frac_pct(low_count):.1f}%)")
            if other_count:
                print(f"     - 其他（資料不足）: {other_count} ({frac_pct(other_count):.1f}%)")
            print(f"     - Frac 平均值: {fmt_frac_value(frac_mean)}")
            print(f"     - Frac 中位數: {fmt_frac_value(frac_median)}")

        tau_valid = trend_stats_df['Kendall_Tau'].notna().sum()

        print(f"\n📊 進階統計（副表）:")
        print(f"  Kendall's tau:")
        print(f"    成功估計: {tau_valid}/{total_count} ({tau_valid/total_count*100:.1f}%)")
        if tau_valid > 0:
            tau_values = trend_stats_df['Kendall_Tau'].dropna()
            print(f"    中位數: {np.median(tau_values):.4f}")
            print(f"    平均值: {np.mean(tau_values):.4f}")

        # R² 統計
        r2_valid = trend_stats_df['LOESS_R2'].notna().sum()
        if r2_valid > 0:
            r2_values = trend_stats_df['LOESS_R2'].dropna()
            print(f"\n  LOESS 擬合優度 R²:")
            print(f"    中位數: {np.median(r2_values):.4f}")
            print(f"    平均值: {np.mean(r2_values):.4f}")

        print(f"\n💡 提示:")
        print(f"  - 主表 ({SHEET_NAMES['qc_lowess']}): Levene's test + CV%（單一特徵）")
        print(f"  - 副表 ({QC_LOWESS_ADVANCED_SHEET}): Kendall's tau + R²/RMSE（進階評估）")
        print(f"  - Frac 參數已依代謝物穩定性與 QC 數量動態調整")
        print(f"  - 新增 Frac_Used / QC_CV_for_Frac / Frac_Strategy 可於 {QC_LOWESS_ADVANCED_SHEET} 交叉檢視")
        print(f"  - 整體評估: Wilcoxon test 已在終端機顯示")
        print(f"\n{'='*70}\n")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M')

        # QC CV% 校正效果總覽圖
        try:
            overview_df = cv_results_df.merge(
                trend_stats_df[['FeatureID', 'Decision_Status']],
                on='FeatureID',
                how='left',
            )
            plot_qc_cv_overview(overview_df, decision_stats, plots_dir, timestamp)
        except Exception as e:
            print(f"  ⚠ QC CV Overview 圖生成失敗: {e}")

        # LOESS 擬合趨勢圖（僅限 debug 特徵）
        if trend_plot_data:
            plot_lowess_trend_fitting(trend_plot_data, plots_dir, timestamp)

        return True

    except Exception as e:
        print(f"❌ 儲存 Excel 時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False


# ========== 主程式 ==========
def main(input_file=None, session_dir=None):
    """主程式入口"""
    print("QC-LOESS 批次效應校正")

    if input_file is None:
        raise ValueError("input_file is required; GUI must provide the file path.")

    session_dir = resolve_session_dir(input_file=input_file, session_dir=session_dir)
    output_dir = get_output_root(input_file=input_file)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"\n✓ 已建立 'output' 資料夾: {output_dir}")

    file_path = input_file

    print(f"  輸入: {os.path.basename(file_path)}")

    raw_df, istd_df, sample_info_df, sample_type_row = load_and_process_data(file_path)
    lowess_df, sample_columns, qc_corrected_values, trend_stats_df, decision_stats, trend_plot_data = (
        perform_lowess_normalization(istd_df, sample_info_df)
    )

    timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
    if session_dir is not None:
        from metabolomics.utils.file_io import session_output_path, session_plots_dir
        output_file = session_output_path(session_dir, step=2, prefix="QC_LOESS")
        _plots_dir = session_plots_dir(session_dir)
    else:
        output_file = build_output_path("QC_LOESS", input_file=input_file, timestamp=timestamp)
        _plots_dir = build_plots_dir(
            "QC_LOESS_plots",
            input_file=input_file,
            timestamp=timestamp,
            session_prefix="QC_LOESS"
        )

    success = save_results_to_excel(
        raw_df, istd_df, lowess_df, sample_info_df,
        sample_columns, output_file, file_path,
        qc_corrected_values, trend_stats_df, decision_stats,
        plots_dir=_plots_dir, trend_plot_data=trend_plot_data,
        sample_type_row=sample_type_row
    )

    if not success:
        print("❌ 結果保存失敗")
        raise RuntimeError(f"Failed to save QC-LOESS results: {output_file}")

    print(f"\n  ✓ QC-LOESS 完成 → {os.path.basename(output_file)}")

    metabolites_count = len(lowess_df)
    samples_count = len(sample_columns)

    return ProcessingResult(
        file_path=file_path,
        output_path=str(output_file),
        plots_dir=str(_plots_dir),
        metabolites=metabolites_count,
        samples=samples_count,
        status=WorkflowOutcome.SUCCEEDED,
    )


if __name__ == "__main__":
    main()
