"""
Shared DataFrame helpers for metabolomics workbook processing.
"""

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from .constants import (
    FEATURE_ID_COLUMN,
    get_step4_metadata_columns,
    is_non_sample_column,
)


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
            if is_non_sample_column(col) or _is_boolean_like(df_clean[col]):
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
    source_df: pd.DataFrame,
    metadata_columns: Optional[Iterable[object]] = None,
) -> Dict[object, pd.Series]:
    """
    Collect Step4 feature-level metadata columns from a source DataFrame.
    """
    if metadata_columns is None:
        metadata_columns = get_step4_metadata_columns(source_df.columns)

    passthrough = {}
    for col_name in metadata_columns:
        if col_name in source_df.columns:
            passthrough[col_name] = source_df[col_name].copy()
    return passthrough


def _resolve_feature_identity_column(
    target_df: pd.DataFrame,
    source_df: pd.DataFrame,
    feature_col: Optional[object] = None,
) -> Optional[object]:
    """Find a stable feature identity column shared by target and source."""
    candidates = []
    if feature_col is not None:
        candidates.append(feature_col)
    candidates.extend([FEATURE_ID_COLUMN, "FeatureID"])

    if len(target_df.columns) > 0:
        candidates.append(target_df.columns[0])
    if len(source_df.columns) > 0:
        candidates.append(source_df.columns[0])

    for candidate in dict.fromkeys(candidates):
        if candidate in target_df.columns and candidate in source_df.columns:
            return candidate
    return None


def apply_feature_metadata_passthrough(
    target_df: pd.DataFrame,
    source_df: pd.DataFrame,
    metadata_columns: Optional[Iterable[object]] = None,
    feature_col: Optional[object] = None,
) -> pd.DataFrame:
    """
    Copy Step4 feature-level metadata columns from source_df to target_df.
    """
    passthrough = collect_feature_metadata_passthrough(source_df, metadata_columns=metadata_columns)
    if not passthrough:
        return target_df

    key_col = _resolve_feature_identity_column(target_df, source_df, feature_col=feature_col)
    if key_col is None:
        raise ValueError(
            "metadata pass-through requires a stable feature identity column "
            "shared by source and target dataframes"
        )

    if source_df[key_col].duplicated().any():
        raise ValueError(
            f"metadata pass-through requires unique source feature identities in '{key_col}'"
        )

    missing_mask = ~target_df[key_col].isin(source_df[key_col])
    if missing_mask.any():
        missing_values = target_df.loc[missing_mask, key_col].head(5).astype(str).tolist()
        preview = ", ".join(missing_values)
        raise ValueError(
            "metadata pass-through could not align target features to source metadata "
            f"using '{key_col}': {preview}"
        )

    metadata_columns = list(passthrough)
    source_metadata = source_df[[key_col, *metadata_columns]]
    aligned_metadata = target_df[[key_col]].merge(
        source_metadata,
        on=key_col,
        how="left",
        sort=False,
        validate="many_to_one",
    )

    for col_name in metadata_columns:
        target_df[col_name] = aligned_metadata[col_name].values
    return target_df
