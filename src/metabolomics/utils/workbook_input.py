"""Centralized workbook input policy for downstream processing steps."""

from dataclasses import dataclass
from enum import Enum
import os
from types import TracebackType

import pandas as pd

from .constants import SHEET_NAMES, resolve_sheet_name


class WorkbookPurpose(str, Enum):
    QC_LOWESS = "qc_lowess"
    NORMALIZATION = "normalization"
    BATCH_DIAGNOSTICS = "batch_diagnostics"


class MissingSampleInfoSheetError(ValueError):
    """Raised when the required sample metadata sheet cannot be resolved."""

    def __init__(self, sheet_names: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.sheet_names = sheet_names


class MissingSourceSheetError(ValueError):
    """Raised when no supported upstream data sheet can be resolved."""


class WorkbookReadError(Exception):
    """Wrap a workbook engine failure without hiding policy errors."""

    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class LoadedWorkbook:
    source_df: pd.DataFrame
    sample_info_df: pd.DataFrame
    source_sheet: str
    sample_info_sheet: str
    sheet_names: tuple[str, ...]
    optional_sheets: dict[str, pd.DataFrame]


_NORMALIZATION_SAMPLE_INFO_NAMES = (
    SHEET_NAMES["sample_info"],
    "Sample_Info",
    "sample_info",
    "Sample Info",
)


def select_processor_source_sheet(
    sheet_names: list[str] | tuple[str, ...],
    purpose: WorkbookPurpose,
) -> str:
    """Resolve the upstream data sheet according to one processor's policy."""
    if purpose is WorkbookPurpose.QC_LOWESS:
        for sheet_key in ("istd_correction", "raw_intensity"):
            sheet_name = SHEET_NAMES[sheet_key]
            if sheet_name in sheet_names:
                return sheet_name
        raise MissingSourceSheetError

    if purpose is WorkbookPurpose.BATCH_DIAGNOSTICS:
        for sheet_name in (
            "SpecNorm_PQN_Result",
            SHEET_NAMES.get("pqn_result", "PQN_Result"),
        ):
            if sheet_name in sheet_names:
                return sheet_name

    for sheet_key in ("qc_lowess", "istd_correction", "raw_intensity"):
        sheet_name = resolve_sheet_name(sheet_names, sheet_key)
        if sheet_name is not None:
            return sheet_name

    raise MissingSourceSheetError


def _select_sample_info_sheet(
    excel_file: pd.ExcelFile,
    purpose: WorkbookPurpose,
) -> str:
    sheet_names = excel_file.sheet_names
    if purpose in {
        WorkbookPurpose.QC_LOWESS,
        WorkbookPurpose.BATCH_DIAGNOSTICS,
    }:
        sample_info_sheet = SHEET_NAMES["sample_info"]
        if sample_info_sheet in sheet_names:
            return sample_info_sheet
        raise MissingSampleInfoSheetError(tuple(sheet_names))

    for sheet_name in _NORMALIZATION_SAMPLE_INFO_NAMES:
        if sheet_name in sheet_names:
            return sheet_name

    for sheet_name in sheet_names:
        columns = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=0).columns
        if any(
            "normalization" in str(column).lower()
            or "sample_type" in str(column).lower()
            for column in columns
        ):
            return sheet_name

    raise MissingSampleInfoSheetError(tuple(sheet_names))


class ProcessorWorkbookInput:
    """Own one workbook catalog and defer source loading until metadata is valid."""

    def __init__(
        self,
        input_file: str | os.PathLike[str],
        purpose: WorkbookPurpose,
    ) -> None:
        self.input_file = os.fspath(input_file)
        self.purpose = purpose
        self._excel_file: pd.ExcelFile | None = None
        self._loaded_sheets: dict[str, pd.DataFrame] = {}
        self._sheet_names: tuple[str, ...] = ()
        self._sample_info_sheet = ""
        self._sample_info_df: pd.DataFrame | None = None

    def __enter__(self) -> "ProcessorWorkbookInput":
        if not os.path.exists(self.input_file):
            raise FileNotFoundError(self.input_file)

        try:
            self._excel_file = pd.ExcelFile(self.input_file)
        except Exception as error:
            raise WorkbookReadError(str(error), stage="catalog") from error

        try:
            self._sheet_names = tuple(self._excel_file.sheet_names)
            self._sample_info_sheet = _select_sample_info_sheet(
                self._excel_file,
                self.purpose,
            )
            self._sample_info_df = self._read_sheet(self._sample_info_sheet)
        except MissingSampleInfoSheetError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise WorkbookReadError(str(error), stage="sample_info") from error

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def sheet_names(self) -> tuple[str, ...]:
        self._require_open()
        return self._sheet_names

    @property
    def sample_info_sheet(self) -> str:
        self._require_open()
        return self._sample_info_sheet

    @property
    def sample_info_df(self) -> pd.DataFrame:
        self._require_open()
        assert self._sample_info_df is not None
        return self._sample_info_df

    def load(self) -> LoadedWorkbook:
        """Resolve and materialize source data after caller metadata validation."""
        self._require_open()
        source_sheet = select_processor_source_sheet(self._sheet_names, self.purpose)

        try:
            source_df = self._read_sheet(source_sheet)
            optional_sheets: dict[str, pd.DataFrame] = {}
            if self.purpose is WorkbookPurpose.NORMALIZATION:
                advanced_sheet = resolve_sheet_name(
                    self._sheet_names,
                    "qc_lowess_advanced",
                )
                if advanced_sheet is not None:
                    optional_sheets[advanced_sheet] = self._read_sheet(advanced_sheet)
        except Exception as error:
            raise WorkbookReadError(str(error), stage="source") from error

        return LoadedWorkbook(
            source_df=source_df,
            sample_info_df=self.sample_info_df,
            source_sheet=source_sheet,
            sample_info_sheet=self._sample_info_sheet,
            sheet_names=self._sheet_names,
            optional_sheets=optional_sheets,
        )

    def close(self) -> None:
        if self._excel_file is not None:
            self._excel_file.close()
            self._excel_file = None

    def _read_sheet(self, sheet_name: str) -> pd.DataFrame:
        self._require_open()
        if sheet_name not in self._loaded_sheets:
            self._loaded_sheets[sheet_name] = pd.read_excel(
                self._excel_file,
                sheet_name=sheet_name,
            )
        return self._loaded_sheets[sheet_name]

    def _require_open(self) -> None:
        if self._excel_file is None:
            raise RuntimeError("ProcessorWorkbookInput must be used as a context manager")
