"""
Adapter B: Convert DNP output → Metaboanalyst_clone input format.

Transformations:
1. Read final normalized data from SpecNorm_PQN_Result, PQN_Result, or legacy QC_Batch_Scaling_result
2. Remove statistical columns (Mean, SD, CV%, etc.)
3. Write cleaned data as the FIRST sheet (Metaboanalyst reads first sheet by default)
4. Copy SampleInfo sheet (needed for SpecNorm)

Uses pandas ExcelWriter with the openpyxl engine for workbook output.
"""

from pathlib import Path

import pandas as pd

from metabolomics.utils.constants import (
    FEATURE_ID_COLUMN,
    NON_SAMPLE_COLUMNS,
    STAT_COLUMN_KEYWORDS,
    SHEET_NAMES,
)


def _is_stat_column(col_name: str) -> bool:
    """Check if a column is a statistical/metadata column that should be removed."""
    if col_name in NON_SAMPLE_COLUMNS and col_name != FEATURE_ID_COLUMN:
        return True
    col_lower = col_name.lower()
    return any(kw in col_lower for kw in STAT_COLUMN_KEYWORDS)


def convert_dnp_to_metaboanalyst(input_path: str, output_path: str) -> str:
    """
    Convert DNP output to Metaboanalyst-compatible format.

    Parameters
    ----------
    input_path : str
        Path to DNP output Excel file.
    output_path : str
        Path for the converted output file.

    Returns
    -------
    str
        The output file path.

    Raises
    ------
    FileNotFoundError
        If input file does not exist.
    ValueError
        If no supported normalized result sheet is found.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # --- Read available sheets ---
    xls = pd.ExcelFile(str(input_path))
    result_candidates = [
        'SpecNorm_PQN_Result',
        SHEET_NAMES['pqn_result'],
        SHEET_NAMES.get('qc_batch_scaling', 'QC_Batch_Scaling_result'),
    ]
    result_sheet = next(
        (sheet_name for sheet_name in result_candidates if sheet_name in xls.sheet_names),
        None,
    )
    if result_sheet is None:
        raise ValueError(
            f"No supported DNP result sheet found. Tried {result_candidates}. "
            f"Available: {xls.sheet_names}"
        )

    # --- Read final result data ---
    df = pd.read_excel(xls, sheet_name=result_sheet)

    # --- Filter out statistical columns ---
    keep_cols = [FEATURE_ID_COLUMN]  # Always keep feature ID first
    for col in df.columns:
        if col == FEATURE_ID_COLUMN:
            continue
        if not _is_stat_column(col):
            keep_cols.append(col)

    df_clean = df[keep_cols]

    # --- Write output: cleaned data as FIRST sheet ---
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(str(output_path), engine='openpyxl') as writer:
        df_clean.to_excel(writer, sheet_name='Data', index=False)

        # --- Copy SampleInfo sheet if present ---
        sample_info_name = SHEET_NAMES['sample_info']
        if sample_info_name in xls.sheet_names:
            df_info = pd.read_excel(xls, sheet_name=sample_info_name)
            df_info.to_excel(writer, sheet_name=sample_info_name, index=False)

    xls.close()

    return str(output_path)
