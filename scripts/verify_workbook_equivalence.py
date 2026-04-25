"""Compare two Excel workbooks with strict semantic equality."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook


@dataclass
class Mismatch:
    sheet: str
    message: str


def _sheet_names(path: Path) -> list[str]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return workbook.sheetnames
    finally:
        workbook.close()


def _read_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name, dtype=object)


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    if pd.isna(value):
        return True
    return isinstance(value, str) and value.strip() == ""


def _as_number(value: object) -> float | None:
    if _is_blank(value):
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values_equal(left: object, right: object, *, rtol: float, atol: float) -> bool:
    if _is_blank(left) and _is_blank(right):
        return True

    left_number = _as_number(left)
    right_number = _as_number(right)
    if left_number is not None and right_number is not None:
        return bool(
            np.isclose(
                left_number,
                right_number,
                rtol=rtol,
                atol=atol,
                equal_nan=True,
            )
        )

    return str(left) == str(right)


def _compare_sheet(
    baseline_path: Path,
    candidate_path: Path,
    sheet_name: str,
    *,
    rtol: float,
    atol: float,
) -> Mismatch | None:
    baseline = _read_sheet(baseline_path, sheet_name)
    candidate = _read_sheet(candidate_path, sheet_name)

    if baseline.shape != candidate.shape:
        return Mismatch(
            sheet=sheet_name,
            message=f"shape differs: baseline={baseline.shape}, candidate={candidate.shape}",
        )

    if list(baseline.columns) != list(candidate.columns):
        return Mismatch(
            sheet=sheet_name,
            message="column labels differ",
        )

    baseline_values = baseline.to_numpy(dtype=object)
    candidate_values = candidate.to_numpy(dtype=object)
    rows, cols = baseline_values.shape
    for row_index in range(rows):
        for col_index in range(cols):
            left = baseline_values[row_index, col_index]
            right = candidate_values[row_index, col_index]
            if not _values_equal(left, right, rtol=rtol, atol=atol):
                column = baseline.columns[col_index]
                return Mismatch(
                    sheet=sheet_name,
                    message=(
                        f"value differs at row={row_index + 2}, column={column!r}: "
                        f"baseline={left!r}, candidate={right!r}"
                    ),
                )

    return None


def compare_workbooks(
    baseline_path: Path,
    candidate_path: Path,
    *,
    rtol: float,
    atol: float,
) -> list[Mismatch]:
    baseline_sheets = _sheet_names(baseline_path)
    candidate_sheets = _sheet_names(candidate_path)
    if baseline_sheets != candidate_sheets:
        return [
            Mismatch(
                sheet="<workbook>",
                message=(
                    "sheet names differ: "
                    f"baseline={baseline_sheets}, candidate={candidate_sheets}"
                ),
            )
        ]

    mismatches: list[Mismatch] = []
    for sheet_name in baseline_sheets:
        mismatch = _compare_sheet(
            baseline_path,
            candidate_path,
            sheet_name,
            rtol=rtol,
            atol=atol,
        )
        if mismatch is not None:
            mismatches.append(mismatch)
            break

    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two workbooks for cleanup acceptance equivalence.",
    )
    parser.add_argument("--baseline", required=True, help="Baseline workbook path.")
    parser.add_argument("--candidate", required=True, help="Candidate workbook path.")
    parser.add_argument("--rtol", type=float, default=1e-12)
    parser.add_argument("--atol", type=float, default=1e-9)
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline).resolve()
    candidate_path = Path(args.candidate).resolve()
    for path in (baseline_path, candidate_path):
        if not path.exists():
            parser.error(f"Workbook does not exist: {path}")

    mismatches = compare_workbooks(
        baseline_path,
        candidate_path,
        rtol=args.rtol,
        atol=args.atol,
    )
    if mismatches:
        for mismatch in mismatches:
            print(f"{mismatch.sheet}: {mismatch.message}", file=sys.stderr)
        return 1

    print("workbooks are semantically equivalent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
