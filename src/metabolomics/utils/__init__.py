"""Shared utility interfaces, loaded only when their public names are used."""

from importlib import import_module
from typing import Any


_EXPORTS = {
    # Constants
    "COLORBLIND_COLORS": ("constants", "COLORBLIND_COLORS"),
    "FONT_SIZES": ("constants", "FONT_SIZES"),
    "SAMPLE_TYPE_COLORS": ("constants", "SAMPLE_TYPE_COLORS"),
    "SAMPLE_TYPE_MARKERS": ("constants", "SAMPLE_TYPE_MARKERS"),
    "SHEET_NAMES": ("constants", "SHEET_NAMES"),
    "VALIDATION_THRESHOLDS": ("constants", "VALIDATION_THRESHOLDS"),
    "NON_SAMPLE_COLUMNS": ("constants", "NON_SAMPLE_COLUMNS"),
    "STEP4_METADATA_COLUMNS": ("constants", "STEP4_METADATA_COLUMNS"),
    "STAT_COLUMN_KEYWORDS": ("constants", "STAT_COLUMN_KEYWORDS"),
    "SAMPLE_TYPE_ALIASES": ("constants", "SAMPLE_TYPE_ALIASES"),
    "DATETIME_FORMAT_FULL": ("constants", "DATETIME_FORMAT_FULL"),
    "DATETIME_FORMAT_SHORT": ("constants", "DATETIME_FORMAT_SHORT"),
    "get_step4_metadata_columns": ("constants", "get_step4_metadata_columns"),
    "is_non_sample_column": ("constants", "is_non_sample_column"),
    "is_step4_metadata_column": ("constants", "is_step4_metadata_column"),
    # File I/O
    "generate_output_filename": ("file_io", "generate_output_filename"),
    "get_output_directory": ("file_io", "get_output_directory"),
    "get_project_root": ("file_io", "get_project_root"),
    "get_output_root": ("file_io", "get_output_root"),
    "build_output_path": ("file_io", "build_output_path"),
    "build_plots_dir": ("file_io", "build_plots_dir"),
    # Sample classification
    "SampleClassifier": ("sample_classification", "SampleClassifier"),
    "normalize_sample_name": ("sample_classification", "normalize_sample_name"),
    "normalize_sample_type": ("sample_classification", "normalize_sample_type"),
    "identify_sample_columns": ("sample_classification", "identify_sample_columns"),
    "get_sample_type_colors": ("sample_classification", "get_sample_type_colors"),
    "get_sample_type_markers": ("sample_classification", "get_sample_type_markers"),
    # Safe math operations
    "safe_divide": ("safe_math", "safe_divide"),
    "safe_cv_percent": ("safe_math", "safe_cv_percent"),
    "safe_cv_percent_vectorized": ("safe_math", "safe_cv_percent_vectorized"),
    "safe_log_transform": ("safe_math", "safe_log_transform"),
    "safe_normalize": ("safe_math", "safe_normalize"),
    "extract_numeric_matrix": ("safe_math", "extract_numeric_matrix"),
    # Data helpers
    "get_valid_values": ("data_helpers", "get_valid_values"),
    # Statistics
    "calculate_hotelling_t2_outliers": (
        "statistics",
        "calculate_hotelling_t2_outliers",
    ),
    "draw_hotelling_t2_ellipse": ("statistics", "draw_hotelling_t2_ellipse"),
    # Plotting
    "setup_matplotlib": ("plotting", "setup_matplotlib"),
    "plot_pca_comparison_qc_style": ("plotting", "plot_pca_comparison_qc_style"),
    # Results
    "ProcessingResult": ("results", "ProcessingResult"),
    # Console
    "safe_print": ("console", "safe_print"),
}

_SUBMODULES = (
    "constants",
    "file_io",
    "sample_classification",
    "safe_math",
    "data_helpers",
    "statistics",
    "plotting",
    "results",
    "console",
)

__all__ = (*_EXPORTS, *_SUBMODULES)


def __getattr__(name: str) -> Any:
    """Resolve a public utility without importing unrelated utility modules."""
    if name in _SUBMODULES:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value

    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
