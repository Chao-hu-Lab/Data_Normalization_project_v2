"""
Shared DataFrame helpers for metabolomics workbook processing.
"""

import numpy as np
import pandas as pd

from .constants import NON_SAMPLE_COLUMNS


def get_valid_values(row, columns):
    """
    Return numeric values > 0 from the requested row/columns.
    """
    values = []
    for col in columns:
        if hasattr(row, "index"):
            if col not in row.index:
                continue
        elif col not in row:
            continue

        try:
            val = float(row[col])
            if not pd.isna(val) and val > 0:
                values.append(val)
        except (ValueError, TypeError):
            pass
    return values


def extract_sample_type_row(df, feature_col="Mz/RT"):
    """
    Extract the embedded Sample_Type row and coerce only numeric intensity columns.
    """

    def _is_boolean_like(series):
        non_null = series.dropna()
        if non_null.empty:
            return False
        return non_null.map(lambda value: isinstance(value, (bool, np.bool_))).all()

    mask = df[feature_col].astype(str).str.strip().str.lower() == "sample_type"
    if mask.any():
        type_row = df[mask].iloc[0].to_dict()
        df_clean = df[~mask].reset_index(drop=True)
        for col in df_clean.columns:
            if col == feature_col:
                continue
            if col in NON_SAMPLE_COLUMNS or _is_boolean_like(df_clean[col]):
                continue
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce")
        return df_clean, type_row
    return df, None


def insert_sample_type_row(df, type_row, feature_col="Mz/RT"):
    """
    Insert the preserved Sample_Type row back to the top of a DataFrame.
    """
    if type_row is None:
        return df
    row_data = {}
    for col in df.columns:
        if col == feature_col:
            row_data[col] = "Sample_Type"
        else:
            row_data[col] = type_row.get(col, "")
    type_df = pd.DataFrame([row_data], columns=df.columns)
    return pd.concat([type_df, df], ignore_index=True)


def collect_feature_metadata_passthrough(
    source_df,
    metadata_columns=("is_Presence_Absence_Marker",),
):
    """
    Collect whitelisted feature-level metadata columns from a source DataFrame.
    """
    passthrough = {}
    for col_name in metadata_columns:
        if col_name in source_df.columns:
            passthrough[col_name] = source_df[col_name].copy()
    return passthrough


def apply_feature_metadata_passthrough(
    target_df,
    source_df,
    metadata_columns=("is_Presence_Absence_Marker",),
):
    """
    Copy whitelisted feature-level metadata columns from source_df to target_df.
    """
    passthrough = collect_feature_metadata_passthrough(source_df, metadata_columns=metadata_columns)
    for col_name, values in passthrough.items():
        target_df[col_name] = values.values
    return target_df
