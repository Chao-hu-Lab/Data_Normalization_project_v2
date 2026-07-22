"""
Centralized constants for the Data Normalization project.

This module contains all shared constants to avoid duplication across modules.
Import from here instead of defining constants locally.
"""

from typing import Iterable, List

# ========== Color Schemes (Colorblind-friendly) ==========
COLORBLIND_COLORS = [
    '#0173B2',  # Blue
    '#DE8F05',  # Orange
    '#029E73',  # Green
    '#CC78BC',  # Purple
    '#CA9161',  # Brown
    '#949494',  # Gray
    '#ECE133',  # Yellow
    '#56B4E9'   # Light Blue
]

# Sample type specific colors
SAMPLE_TYPE_COLORS = {
    'QC': '#9370DB',       # Purple
    'Control': '#4169E1',  # Royal Blue
    'Exposure': '#DC143C', # Crimson
    'Normal': '#029E73',   # Green
    'Unknown': '#808080',  # Gray
}

# Sample type markers for scatter plots
SAMPLE_TYPE_MARKERS = {
    'QC': 'o',        # Circle
    'Control': 's',   # Square
    'Exposure': '^',  # Triangle
    'Normal': 'D',    # Diamond
    'Unknown': 'x',   # X
}

# ========== Font Settings ==========
FONT_SIZES = {
    'title': 14,
    'subtitle': 12,
    'axis_label': 11,
    'tick': 10,
    'legend': 9,
    'annotation': 9
}

# ========== Feature ID Column ==========
FEATURE_ID_COLUMN = 'Mz/RT'

# ========== Sheet Names ==========
SHEET_NAMES = {
    'raw_intensity': 'RawIntensity',
    'sample_info': 'SampleInfo',
    'istd_correction': 'ISTD_Correction',
    'qc_lowess': 'QC LOESS result',
    'qc_lowess_advanced': 'LOESS_summary',
    'qc_batch_scaling': 'QC_Batch_Scaling_result',
    'qc_batch_scaling_summary': 'QC_Batch_Scaling_summary',
    'concentration': 'ConcNormalization_Summary',
    'pqn_result': 'PQN_Result',
    'specnorm_result': 'SpecNorm_Result',
}

# Legacy workbook names still accepted on read to avoid breaking old outputs.
LEGACY_SHEET_NAMES = {
    'qc_lowess': ('QC LOWESS result',),
    'qc_lowess_advanced': ('QC_LOESS_Advanced Statistics',),
}


def sheet_name_candidates(sheet_key):
    """Return canonical sheet name followed by legacy aliases."""
    canonical = SHEET_NAMES[sheet_key]
    candidates = [canonical, *LEGACY_SHEET_NAMES.get(sheet_key, ())]
    return tuple(dict.fromkeys(candidates))


def resolve_sheet_name(sheet_names, sheet_key):
    """Resolve the first matching sheet name for a canonical sheet key."""
    for candidate in sheet_name_candidates(sheet_key):
        if candidate in sheet_names:
            return candidate
    return None


def sheet_name_matches(sheet_name, sheet_key):
    """Return True when a sheet name matches the canonical or legacy alias."""
    return sheet_name in sheet_name_candidates(sheet_key)

# ========== Validation Thresholds ==========
VALIDATION_THRESHOLDS = {
    'min_qc_samples': 3,
    'min_istd_count': 1,
    'max_cv_percent': 30.0,
    'min_file_size_bytes': 1024,
    'max_intensity_value': 1e15,
    'alpha': 0.05,  # Statistical significance level
}

# ========== Statistical Thresholds (cross-module) ==========
# Cohen's d effect size interpretation boundaries
COHENS_D_THRESHOLDS = {
    'small': 0.2,
    'medium': 0.5,
    'large': 0.8,
}

# CV% quality grading boundaries
CV_QUALITY_THRESHOLDS = {
    'excellent': 20.0,   # CV% < 20% = excellent
    'acceptable': 30.0,  # CV% < 30% = acceptable, >= 30% = poor
}

# ========== Non-Sample Columns ==========
# Step4 metadata from upstream MS Preprocessing Toolkit. These columns control
# downstream missing-value routing and must not enter calibration matrices.
STEP4_METADATA_COLUMNS = {
    'is_Presence_Absence_Marker',
    'Feature_Filter_Keep_Reasons',
    'Imputation_Tag_Reasons',
    'Feature_Filter_Delete_Reasons',
    'Detection_Profile',
    'exposure_ratio',
    'normal_ratio',
    'control_ratio',
    'QC_ratio',
}

STEP4_RATIO_METADATA_SUFFIX = '_ratio'


def is_step4_metadata_column(column_name: object) -> bool:
    """Return True when a column is upstream Step4 metadata."""
    if column_name is None:
        return False

    value = str(column_name).strip()
    if not value:
        return False

    return value in STEP4_METADATA_COLUMNS or value.lower().endswith(STEP4_RATIO_METADATA_SUFFIX)


def get_step4_metadata_columns(columns: Iterable[object]) -> List[object]:
    """Return Step4 metadata columns in their source order."""
    return [column for column in columns if is_step4_metadata_column(column)]


def is_non_sample_column(column_name: object) -> bool:
    """Return True for metadata/stat columns that must not be sample intensities."""
    if column_name is None:
        return False

    value = str(column_name).strip()
    return value in NON_SAMPLE_COLUMNS or is_step4_metadata_column(value)


# Columns that should never be treated as sample intensity columns
NON_SAMPLE_COLUMNS = {
    'Mz/RT', 'FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference', 'ISTD_Median',
    'CV%', 'QC_CV%', 'Original_CV%', 'Normalized_CV%', 'CV_Improvement%', 'Original_QC_CV%', 'Corrected_QC_CV%',
    'Original_Robust_CV%', 'Corrected_Robust_CV%', 'Robust_CV_Improvement%',
    'Variance_Test_pvalue', 'Variance_Test_qvalue', 'Wilcoxon_pvalue', 'Wilcoxon_qvalue',
    'Shapiro_pvalue', 'Kendall_Tau',
    'LOESS_R2', 'LOESS_RMSE', 'LOWESS_R2', 'LOWESS_RMSE', 'Significant_Improvement',
    'Decision', 'Trend_Status', 'frac', 'outliers_removed',
    'median_correction_factor', 'correction_factor_cv',
    'correction_factor_std', 'correction_factor_range_low',
    'correction_factor_range_high', 'Frac_Used', 'QC_CV_for_Frac',
    'Frac_Strategy', 'Fit_Strategy', 'Batch_Decision_Detail',
    'LOOCV_RMSE',
    'Linear_LOOCV_Baseline_RMSE_Log2', 'Linear_LOOCV_RMSE_Log2',
    'Linear_LOOCV_Gain', 'Linear_Drift_Amplitude_Log2',
    'Linear_Residual_RMSE_Log2', 'Linear_R2',
    'exposure_ratio', 'normal_ratio', 'control_ratio', 'QC_ratio',
    # Additional metadata columns
    'mz', 'rt', 'm/z', 'Mass', 'Retention_Time',
    'is_Presence_Absence_Marker', 'Feature_Filter_Keep_Reasons', 'Imputation_Tag_Reasons',
    'Feature_Filter_Delete_Reasons', 'Detection_Profile',
}

# Keywords that identify derived statistical columns
STAT_COLUMN_KEYWORDS = (
    'original_qc_', 'corrected_qc_', 'cv_', 'variance_', 'levene', 'mk_',
    'kendall', 'lowess_', 'loess_', 'trend_', 'wilcoxon', 'shapiro', 'significant',
    'decision', 'rmse', 'median_correction', 'correction_factor', 'robust_cv', 'qvalue'
)

# ========== Sample Type Aliases ==========
# Maps various sample type naming conventions to standardized types
SAMPLE_TYPE_ALIASES = {
    # QC variants
    'QC': 'QC', 'QC1': 'QC', 'QC2': 'QC', 'POOLED': 'QC', 'POOL': 'QC',
    # Control variants
    'CONTROL': 'Control', 'CTL': 'Control', 'CON': 'Control',
    'CTRL': 'Control', 'C': 'Control',
    # Exposure variants
    'EXPOSURE': 'Exposure', 'EXPOSED': 'Exposure',
    'EXP': 'Exposure', 'TREAT': 'Exposure', 'TREATED': 'Exposure',
    'TREATMENT': 'Exposure', 'E': 'Exposure',
    # Normal variants (independent category)
    'NORMAL': 'Normal', 'NOR': 'Normal', 'N': 'Normal',
    # Benign variants (mapped to Control)
    'BENIGN': 'Control',
    # Blank variants
    'BLANK': 'Blank', 'BLK': 'Blank', 'B': 'Blank',
}

# ========== Date/Time Formats ==========
DATETIME_FORMAT_FULL = '%Y%m%d_%H%M%S'
DATETIME_FORMAT_SHORT = '%Y%m%d_%H%M'

# ========== Plot Output Settings ==========
PLOT_DPI = 300
PLOT_FORMAT = 'png'
