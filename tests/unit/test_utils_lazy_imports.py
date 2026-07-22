import os
import subprocess
import sys
from pathlib import Path


EXPECTED_EXPORTS = {
    "COLORBLIND_COLORS",
    "FONT_SIZES",
    "SAMPLE_TYPE_COLORS",
    "SAMPLE_TYPE_MARKERS",
    "SHEET_NAMES",
    "VALIDATION_THRESHOLDS",
    "NON_SAMPLE_COLUMNS",
    "STEP4_METADATA_COLUMNS",
    "STAT_COLUMN_KEYWORDS",
    "SAMPLE_TYPE_ALIASES",
    "DATETIME_FORMAT_FULL",
    "DATETIME_FORMAT_SHORT",
    "get_step4_metadata_columns",
    "is_non_sample_column",
    "is_step4_metadata_column",
    "generate_output_filename",
    "get_output_directory",
    "get_project_root",
    "get_output_root",
    "build_output_path",
    "build_plots_dir",
    "SampleClassifier",
    "normalize_sample_name",
    "normalize_sample_type",
    "identify_sample_columns",
    "get_sample_type_colors",
    "get_sample_type_markers",
    "safe_divide",
    "safe_cv_percent",
    "safe_cv_percent_vectorized",
    "safe_log_transform",
    "safe_normalize",
    "extract_numeric_matrix",
    "get_valid_values",
    "calculate_hotelling_t2_outliers",
    "draw_hotelling_t2_ellipse",
    "setup_matplotlib",
    "plot_pca_comparison_qc_style",
    "ProcessingResult",
    "safe_print",
    "constants",
    "file_io",
    "sample_classification",
    "safe_math",
    "data_helpers",
    "statistics",
    "plotting",
    "results",
    "console",
}


def _run_isolated_import(code: str) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )


def test_utils_public_exports_are_preserved():
    from metabolomics import utils

    assert set(utils.__all__) == EXPECTED_EXPORTS
    assert EXPECTED_EXPORTS <= set(dir(utils))

    from metabolomics.utils import ProcessingResult, SHEET_NAMES
    from metabolomics.utils.results import ProcessingResult as DirectProcessingResult

    assert ProcessingResult is DirectProcessingResult
    assert SHEET_NAMES


def test_importing_lightweight_utils_does_not_load_scientific_stacks():
    result = _run_isolated_import(
        """
import sys
from metabolomics.utils import ProcessingResult, SHEET_NAMES

heavy_modules = {"pandas", "scipy", "matplotlib"}
loaded = sorted(
    name for name in heavy_modules
    if name in sys.modules
)
if loaded:
    raise AssertionError(f"unexpected heavy imports: {loaded}")
print(ProcessingResult.__name__, bool(SHEET_NAMES))
"""
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ProcessingResult True"


def test_package_submodule_import_still_works():
    result = _run_isolated_import(
        """
from metabolomics.utils import normalization_contract
print(normalization_contract.__name__)
"""
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "metabolomics.utils.normalization_contract"


def test_legacy_submodule_attributes_and_star_import_are_preserved():
    result = _run_isolated_import(
        """
import metabolomics.utils as utils

assert utils.constants.__name__ == "metabolomics.utils.constants"
namespace = {}
exec("from metabolomics.utils import *", namespace)
assert namespace["plotting"] is utils.plotting
assert namespace["ProcessingResult"] is utils.ProcessingResult
print(len(utils.__all__))
"""
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(len(EXPECTED_EXPORTS))
