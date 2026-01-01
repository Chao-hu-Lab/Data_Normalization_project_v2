"""
Centralized constants for the Data Normalization project.

This module contains all shared constants to avoid duplication across modules.
Import from here instead of defining constants locally.
"""

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
    'Unknown': '#808080',  # Gray
}

# Sample type markers for scatter plots
SAMPLE_TYPE_MARKERS = {
    'QC': 'o',        # Circle
    'Control': 's',   # Square
    'Exposure': '^',  # Triangle
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

# ========== Sheet Names ==========
SHEET_NAMES = {
    'raw_intensity': 'RawIntensity',
    'sample_info': 'SampleInfo',
    'istd_correction': 'ISTD_Correction',
    'qc_lowess': 'QC LOWESS result',
    'qc_lowess_advanced': 'QC_LOWESS_Advanced Statistics',
    'batch_effect': 'Batch_effect_result',
    'batch_summary': 'Batch_Effect_summary',
    'concentration': 'ConcNormalization_Summary',
}

# ========== Validation Thresholds ==========
VALIDATION_THRESHOLDS = {
    'min_qc_samples': 3,
    'min_istd_count': 1,
    'max_cv_percent': 30.0,
    'min_file_size_bytes': 1024,
    'max_intensity_value': 1e15,
    'alpha': 0.05,  # Statistical significance level
}

# ========== Non-Sample Columns ==========
# Columns that should never be treated as sample intensity columns
NON_SAMPLE_COLUMNS = {
    'FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference', 'ISTD_Median',
    'QC_CV%', 'Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%',
    'Variance_Test_pvalue', 'Wilcoxon_pvalue', 'Wilcoxon_qvalue',
    'Shapiro_pvalue', 'MK_Trend_pvalue', 'Kendall_Tau',
    'LOWESS_R2', 'LOWESS_RMSE', 'Significant_Improvement',
    'Decision', 'Trend_Status', 'frac', 'outliers_removed',
    'median_correction_factor', 'correction_factor_cv',
    'correction_factor_std', 'correction_factor_range_low',
    'correction_factor_range_high', 'Frac_Used', 'QC_CV_for_Frac',
    'Frac_Strategy',
    # Additional metadata columns
    'mz', 'rt', 'm/z', 'Mass', 'Retention_Time',
}

# Keywords that identify derived statistical columns
STAT_COLUMN_KEYWORDS = (
    'original_qc_', 'corrected_qc_', 'cv_', 'variance_', 'levene', 'mk_',
    'kendall', 'lowess_', 'trend_', 'wilcoxon', 'shapiro', 'significant',
    'decision', 'rmse', 'median_correction', 'correction_factor'
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
    # Blank variants
    'BLANK': 'Blank', 'BLK': 'Blank', 'B': 'Blank',
}

# ========== Date/Time Formats ==========
DATETIME_FORMAT_FULL = '%Y%m%d_%H%M%S'
DATETIME_FORMAT_SHORT = '%Y%m%d_%H%M'

# ========== Plot Output Settings ==========
PLOT_DPI = 300
PLOT_FORMAT = 'png'
