"""
Excel file I/O utilities for metabolomics data processing.

This module provides unified file loading with caching to eliminate
the dual pandas + openpyxl read pattern that was causing performance issues.
"""
import os
import pandas as pd
from openpyxl import load_workbook
from typing import Dict, Optional, Tuple, List
from pathlib import Path

from .constants import VALIDATION_THRESHOLDS, DATETIME_FORMAT_FULL

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


def get_output_root() -> Path:
    """
    Return the project-level output directory and ensure it exists.
    """
    output_root = get_project_root() / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


class ExcelDataLoader:
    """
    Unified Excel data loader with caching and validation.

    Solves the issue of loading Excel files twice (once with pandas,
    once with openpyxl). Caches loaded data for reuse.

    Usage:
        loader = ExcelDataLoader("data.xlsx")
        is_valid, errors = loader.validate_file()
        if is_valid:
            raw_df = loader.load_sheet('RawIntensity')
            sample_df = loader.load_sheet('SampleInfo')
            # Only load workbook when needed for styling
            wb = loader.get_workbook()
        loader.close()
    """

    def __init__(self, file_path: str):
        """
        Initialize the loader with a file path.

        Args:
            file_path: Path to the Excel file
        """
        self.file_path = str(file_path)
        self._excel_file: Optional[pd.ExcelFile] = None
        self._workbook = None
        self._all_sheets: Dict[str, pd.DataFrame] = {}
        self._validated = False
        self._validation_errors: List[str] = []

    def validate_file(self) -> Tuple[bool, List[str]]:
        """
        Comprehensive file validation (replaces scattered 防呆 checks).

        Performs the following checks:
        - File existence
        - File format (.xlsx or .xls)
        - File size (not empty, not too small)
        - Can be opened as Excel

        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []

        # Check existence
        if not os.path.exists(self.file_path):
            errors.append(f"找不到檔案: {self.file_path}")
            return False, errors

        # Check format
        file_ext = self.file_path.lower()
        if not (file_ext.endswith('.xlsx') or file_ext.endswith('.xls')):
            errors.append(f"輸入檔案必須是 Excel 格式 (.xlsx 或 .xls)")
            return False, errors

        # Check size
        try:
            file_size = os.path.getsize(self.file_path)
        except OSError as e:
            errors.append(f"無法讀取檔案大小: {e}")
            return False, errors

        if file_size == 0:
            errors.append("檔案是空的 (0 bytes)")
            return False, errors

        min_size = VALIDATION_THRESHOLDS.get('min_file_size_bytes', 1024)
        if file_size < min_size:
            errors.append(f"檔案太小: {file_size} bytes (最小 {min_size} bytes)")

        # Try opening with pandas
        try:
            self._excel_file = pd.ExcelFile(self.file_path)
        except Exception as e:
            errors.append(f"無法讀取 Excel 檔案: {e}")
            return False, errors

        self._validated = True
        self._validation_errors = errors
        return len(errors) == 0, errors

    def get_sheet_names(self) -> List[str]:
        """
        Get available sheet names.

        Returns:
            List of sheet names in the workbook
        """
        if not self._validated:
            self.validate_file()
        return self._excel_file.sheet_names if self._excel_file else []

    def has_sheet(self, sheet_name: str) -> bool:
        """
        Check if a sheet exists.

        Args:
            sheet_name: Name of the sheet to check

        Returns:
            True if sheet exists, False otherwise
        """
        return sheet_name in self.get_sheet_names()

    def load_all_sheets(self) -> Dict[str, pd.DataFrame]:
        """
        Load all sheets at once (cached).

        Returns:
            Dictionary mapping sheet names to DataFrames
        """
        if self._all_sheets:
            return self._all_sheets

        if not self._validated:
            is_valid, errors = self.validate_file()
            if not is_valid:
                raise ValueError(f"檔案驗證失敗: {'; '.join(errors)}")

        for sheet in self._excel_file.sheet_names:
            self._all_sheets[sheet] = pd.read_excel(
                self._excel_file, sheet_name=sheet
            )
        return self._all_sheets

    def load_sheet(self, sheet_name: str) -> Optional[pd.DataFrame]:
        """
        Load a single sheet with caching.

        Args:
            sheet_name: Name of the sheet to load

        Returns:
            DataFrame or None if sheet doesn't exist
        """
        # Check cache first
        if sheet_name in self._all_sheets:
            return self._all_sheets[sheet_name]

        if not self._validated:
            is_valid, errors = self.validate_file()
            if not is_valid:
                raise ValueError(f"檔案驗證失敗: {'; '.join(errors)}")

        if sheet_name not in self._excel_file.sheet_names:
            return None

        df = pd.read_excel(self._excel_file, sheet_name=sheet_name)
        self._all_sheets[sheet_name] = df
        return df

    def get_workbook(self):
        """
        Get openpyxl workbook (for formatting operations).

        Only loads the workbook when actually needed, avoiding
        the double-load issue.

        Returns:
            openpyxl Workbook object
        """
        if self._workbook is None:
            self._workbook = load_workbook(self.file_path)
        return self._workbook

    def close(self):
        """Release resources."""
        if self._workbook:
            try:
                self._workbook.close()
            except Exception:
                pass
            self._workbook = None
        self._excel_file = None
        self._all_sheets.clear()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


def validate_required_sheets(
    loader: ExcelDataLoader,
    required: List[str]
) -> Tuple[bool, List[str]]:
    """
    Validate that required sheets exist in the workbook.

    Args:
        loader: ExcelDataLoader instance
        required: List of required sheet names

    Returns:
        Tuple of (is_valid, list_of_error_messages)
    """
    available = set(loader.get_sheet_names())
    missing = [s for s in required if s not in available]

    if missing:
        return False, [f"缺少必要的工作表: {', '.join(missing)}"]
    return True, []


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
    from datetime import datetime

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
    output_dir = get_output_root()
    if subdir:
        output_dir = output_dir / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def build_output_path(
    prefix: str,
    timestamp: str = None,
    extension: str = ".xlsx"
) -> Path:
    """
    Build a full output file path under the project output directory.
    """
    output_dir = get_output_root()
    filename = generate_output_filename(prefix, timestamp=timestamp, extension=extension)
    return output_dir / filename


def build_plots_dir(
    subdir: str,
    timestamp: str = None,
    session_prefix: str = None
) -> Path:
    """
    Build a plots directory under the project output directory.
    """
    output_dir = get_output_root()
    plots_root = output_dir / subdir
    if session_prefix:
        session_name = f"{session_prefix}_{timestamp}" if timestamp else session_prefix
        plots_dir = plots_root / session_name
    else:
        plots_dir = plots_root
    plots_dir.mkdir(parents=True, exist_ok=True)
    return plots_dir
