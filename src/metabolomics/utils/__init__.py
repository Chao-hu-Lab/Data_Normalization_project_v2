"""
共用工具模組

包含：
- constants: 集中定義的常數 (顏色、字體大小、欄位名稱等)
- file_io: Excel 檔案讀寫工具
- sample_classification: 樣本分類工具
- data_validation: 資料驗證工具
- data_helpers: 資料處理輔助函數
- statistics: 統計分析函數 (Hotelling T² 等)
- plotting: matplotlib 繪圖設定
"""

# Constants (centralized)
from .constants import (
    COLORBLIND_COLORS,
    FONT_SIZES,
    SAMPLE_TYPE_COLORS,
    SAMPLE_TYPE_MARKERS,
    SHEET_NAMES,
    VALIDATION_THRESHOLDS,
    NON_SAMPLE_COLUMNS,
    STAT_COLUMN_KEYWORDS,
    SAMPLE_TYPE_ALIASES,
    DATETIME_FORMAT_FULL,
    DATETIME_FORMAT_SHORT,
)

# File I/O
from .file_io import (
    ExcelDataLoader,
    validate_required_sheets,
    validate_required_columns,
    generate_output_filename,
    get_output_directory,
    get_project_root,
    get_output_root,
    build_output_path,
    build_plots_dir,
)

# Sample classification
from .sample_classification import (
    SampleClassifier,
    normalize_sample_name,
    normalize_sample_type,
    identify_sample_columns,
    get_sample_type_colors,
    get_sample_type_markers,
)

# Safe math operations
from .safe_math import (
    safe_divide,
    safe_cv_percent,
    safe_cv_percent_vectorized,
    safe_log_transform,
    safe_normalize,
    extract_numeric_matrix,
)

# Data validation
from .data_validation import (
    ValidationResult,
    DataValidator,
    validate_dataframe_numeric,
    quick_validate_excel,
)

# Data helpers
from .data_helpers import get_valid_values

# Statistics
from .statistics import calculate_hotelling_t2_outliers, draw_hotelling_t2_ellipse

# Plotting
from .plotting import setup_matplotlib, plot_pca_comparison_qc_style

# Results
from .results import ProcessingResult

# Console
from .console import safe_print
