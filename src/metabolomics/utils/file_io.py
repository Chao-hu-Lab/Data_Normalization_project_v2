"""
Excel file I/O utilities for metabolomics data processing.

Provides output path generation, directory management, and column validation helpers.
"""
from datetime import datetime
import os

import pandas as pd
from openpyxl import load_workbook
from typing import Dict, Optional, Tuple, List
from pathlib import Path

from .constants import VALIDATION_THRESHOLDS, DATETIME_FORMAT_FULL


TEST_MATRIX_SUBDIRS = {"scenario_matrices", "test_matrices"}


def is_pytest_running() -> bool:
    """Return True when code is executing inside pytest."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))

def get_project_root() -> Path:
    """
    Resolve the project root based on the package location.

    Falls back to the current working directory if the expected layout
    is not found.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "src":
            return parent.parent
    return Path.cwd()


def infer_output_root_from_input(input_file: Optional[str] = None) -> Optional[Path]:
    """
    Infer the output root from an input file path.

    If the input file is already inside an ``output`` tree, reuse that output
    directory so downstream steps stay in the same session workspace.
    """
    if not input_file:
        return None

    input_path = Path(input_file).resolve()
    if not input_path.exists():
        return None

    search_start = input_path if input_path.is_dir() else input_path.parent

    for parent in (search_start, *search_start.parents):
        if parent.name.startswith("run_"):
            output_root = parent.parent
            output_root.mkdir(parents=True, exist_ok=True)
            return output_root

    for parent in (search_start, *search_start.parents):
        if parent.name == "output":
            search_start.mkdir(parents=True, exist_ok=True)
            return search_start

    return None


def infer_isolated_output_root_from_input(input_file: Optional[str] = None) -> Optional[Path]:
    """
    Route repository test/scenario inputs to a dedicated output subtree.

    This keeps synthetic validation runs separate from regular user analyses.
    """
    if not input_file:
        return None

    input_path = Path(input_file).resolve()
    if not input_path.exists():
        return None

    project_root = get_project_root().resolve()
    try:
        relative_path = input_path.relative_to(project_root)
    except ValueError:
        if is_pytest_running():
            return project_root / "output" / "test_data_runs" / input_path.stem
        return None

    relative_parts = relative_path.parts[:-1] if input_path.is_file() else relative_path.parts
    if len(relative_parts) >= 2 and relative_parts[0] == "data" and relative_parts[1] in TEST_MATRIX_SUBDIRS:
        return project_root / "output" / "test_data_runs" / input_path.stem

    if is_pytest_running() and relative_parts and relative_parts[0] == "data":
        return project_root / "output" / "test_data_runs" / input_path.stem

    if relative_parts and relative_parts[0] == "tests":
        return project_root / "output" / "test_data_runs" / input_path.stem

    return None


def infer_session_dir_from_input(input_file: Optional[str] = None) -> Optional[Path]:
    """
    Reuse an existing session directory when the upstream file already lives in one.
    """
    if not input_file:
        return None

    input_path = Path(input_file).resolve()
    if not input_path.exists():
        return None

    search_start = input_path if input_path.is_dir() else input_path.parent
    for parent in (search_start, *search_start.parents):
        if parent.name.startswith("run_") and (parent / "plots").exists():
            return parent

    return None


def resolve_session_dir(
    input_file: Optional[str] = None,
    session_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Resolve the effective session directory for a pipeline run.

    Priority:
    1. Explicit ``session_dir``
    2. Reuse the upstream run directory when input already belongs to a session
    3. Under pytest, auto-create a session so tests use step-scoped outputs
    """
    if session_dir is not None:
        return Path(session_dir)

    inferred_session = infer_session_dir_from_input(input_file=input_file)
    if inferred_session is not None:
        return inferred_session

    if is_pytest_running():
        return create_session_dir(output_root=get_output_root(input_file=input_file))

    return None


def get_output_root(input_file: Optional[str] = None) -> Path:
    """
    Return the project-level output directory and ensure it exists.
    """
    output_root = infer_output_root_from_input(input_file)
    if output_root is None:
        output_root = infer_isolated_output_root_from_input(input_file)
    if output_root is None:
        output_root = get_project_root() / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def validate_required_columns(
    df: pd.DataFrame,
    required: List[str],
    sheet_name: str = "DataFrame"
) -> Tuple[bool, List[str]]:
    """
    Validate that required columns exist in a DataFrame.

    Args:
        df: DataFrame to validate
        required: List of required column names
        sheet_name: Name of the sheet (for error messages)

    Returns:
        Tuple of (is_valid, list_of_error_messages)
    """
    missing = [c for c in required if c not in df.columns]
    if missing:
        return False, [f"'{sheet_name}' 缺少必要欄位: {', '.join(missing)}"]
    return True, []


def generate_output_filename(
    prefix: str,
    input_file: str = None,
    timestamp: str = None,
    extension: str = ".xlsx"
) -> str:
    """
    Generate a timestamped output filename.

    Args:
        prefix: Prefix for the filename (e.g., "ISTD_Results")
        input_file: Optional input file to base the name on
        timestamp: Optional timestamp string (uses current time if not provided)
        extension: File extension (default: .xlsx)

    Returns:
        Generated filename string
    """
    if timestamp is None:
        timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)

    if input_file:
        # Append to existing filename pattern
        input_base = Path(input_file).stem
        return f"{input_base}_{prefix}_{timestamp}{extension}"
    else:
        return f"{prefix}_{timestamp}{extension}"


def get_output_directory(
    input_file: str = None,
    subdir: str = None
) -> Path:
    """
    Get the output directory for a given input file.

    Creates the directory if it doesn't exist.

    Args:
        input_file: Input file path (unused; retained for compatibility)
        subdir: Optional subdirectory name (e.g., "plots")

    Returns:
        Path object for the output directory
    """
    output_dir = get_output_root(input_file=input_file)
    if subdir:
        output_dir = output_dir / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def build_output_path(
    prefix: str,
    input_file: str = None,
    timestamp: str = None,
    extension: str = ".xlsx"
) -> Path:
    """
    Build a full output file path under the project output directory.
    """
    output_dir = get_output_root(input_file=input_file)
    filename = generate_output_filename(prefix, timestamp=timestamp, extension=extension)
    return output_dir / filename


def build_plots_dir(
    subdir: str,
    input_file: str = None,
    timestamp: str = None,
    session_prefix: str = None
) -> Path:
    """
    Build a plots directory under the project output directory.
    """
    output_dir = get_output_root(input_file=input_file)
    plots_root = output_dir / subdir
    if session_prefix:
        session_name = f"{session_prefix}_{timestamp}" if timestamp else session_prefix
        plots_dir = plots_root / session_name
    else:
        plots_dir = plots_root
    plots_dir.mkdir(parents=True, exist_ok=True)
    return plots_dir


def create_session_dir(output_root: Path = None, timestamp: str = None) -> Path:
    """
    Create a timestamped session directory for a pipeline run.

    Structure: output_root/run_{timestamp}/plots/
    """
    if output_root is None:
        output_root = get_output_root()
    if timestamp is None:
        timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)

    session_dir = Path(output_root) / f"run_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "plots").mkdir(exist_ok=True)
    return session_dir


def session_output_path(
    session_dir: Path, step: int, prefix: str, extension: str = ".xlsx"
) -> Path:
    """Return the output file path within a session directory."""
    return Path(session_dir) / f"Step{step}_{prefix}{extension}"


def session_plots_dir(session_dir: Path) -> Path:
    """Return the plots subdirectory within a session directory."""
    plots = Path(session_dir) / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    return plots
