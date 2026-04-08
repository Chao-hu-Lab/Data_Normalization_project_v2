"""
Sample classification utilities for metabolomics data.

This module consolidates the 26+ instances of sample type detection
logic that were scattered across the processing modules.
"""
import pandas as pd
import re
from typing import Collection, Dict, List, Optional, Tuple

from .constants import NON_SAMPLE_COLUMNS, STAT_COLUMN_KEYWORDS, SAMPLE_TYPE_ALIASES


def _normalized_stat_keywords() -> List[str]:
    """Normalize statistical keywords for robust substring matching."""
    return [normalize_sample_name(keyword) for keyword in STAT_COLUMN_KEYWORDS]


def normalize_sample_name(name) -> str:
    """
    Normalize a sample name for consistent comparisons.

    Args:
        name: Sample name (can be any type)

    Returns:
        Lowercase stripped string, or empty string if NaN
    """
    if pd.isna(name):
        return ''

    value = str(name).strip()
    if not value:
        return ''

    # Normalize common cross-tool naming differences:
    # - DNA_program1_TumorBC2257_DNA vs Tumor tissue BC2257_DNA
    # - Breast Cancer Tissue_ pooled_QC_1 vs Breast_Cancer_Tissue_pooled_QC_1
    value = re.sub(r'^(?:dna|rna)_program\d+_', '', value, flags=re.IGNORECASE)
    value = re.sub(r'(?i)\bdna\s*(?:\+|and)\s*rna\b', 'dna and rna', value)
    value = re.sub(r'([a-z])([A-Z])', r'\1 \2', value)
    value = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', value)
    value = re.sub(r'([A-Za-z])(\d)', r'\1 \2', value)
    value = re.sub(r'(\d)([A-Za-z])', r'\1 \2', value)
    value = value.lower()

    parts = re.split(r'[\s_\-/*+()]+', value)
    filtered_parts = [part for part in parts if part and part not in {'tissue'}]
    return ''.join(filtered_parts)


def normalize_sample_type(sample_type: str) -> str:
    """
    Normalize a sample type to a standard category.

    Args:
        sample_type: Raw sample type string

    Returns:
        One of: 'QC', 'Control', 'Exposure', 'Blank', 'Unknown'
    """
    if pd.isna(sample_type):
        return 'Unknown'

    type_upper = str(sample_type).strip().upper()

    # Direct match in aliases
    if type_upper in SAMPLE_TYPE_ALIASES:
        return SAMPLE_TYPE_ALIASES[type_upper]

    # Partial match for keywords
    if 'QC' in type_upper or 'POOL' in type_upper:
        return 'QC'
    if any(k in type_upper for k in ('CONTROL', 'CTL', 'CON', 'BENIGN')):
        return 'Control'
    if any(k in type_upper for k in ('EXPOSURE', 'EXPOSED', 'EXP', 'TREAT')):
        return 'Exposure'
    if any(k in type_upper for k in ('NORMAL', 'NOR')):
        return 'Normal'
    if any(k in type_upper for k in ('BLANK', 'BLK')):
        return 'Blank'

    return 'Unknown'


class SampleClassifier:
    """
    Unified sample classification logic.

    Consolidates 26+ instances of sample type detection scattered
    across the processing modules into a single, consistent implementation.

    Usage:
        classifier = SampleClassifier(sample_info_df)
        sample_type = classifier.get_sample_type('Sample_001')
        qc, control, exposure, other = classifier.classify_columns(sample_columns)
    """

    def __init__(self, sample_info_df: pd.DataFrame):
        """
        Initialize classifier with SampleInfo DataFrame.

        Args:
            sample_info_df: DataFrame with Sample_Name and Sample_Type columns
        """
        self.sample_info = sample_info_df
        self._lookup: Dict[str, str] = {}
        self._batch_lookup: Dict[str, Optional[str]] = {}
        self._build_lookups()

    def _build_lookups(self):
        """Build normalized sample name to type/batch lookups."""
        # Determine column names (may vary by file)
        name_col = None
        type_col = None
        batch_col = None

        for col in self.sample_info.columns:
            col_lower = str(col).lower()
            if 'sample_name' in col_lower or col == self.sample_info.columns[0]:
                name_col = col
            if 'sample_type' in col_lower or 'type' in col_lower:
                type_col = col
            if 'batch' in col_lower:
                batch_col = col

        if name_col is None:
            name_col = self.sample_info.columns[0]

        for _, row in self.sample_info.iterrows():
            name = normalize_sample_name(row.get(name_col, ''))
            if not name:
                continue

            # Get and normalize sample type
            raw_type = str(row.get(type_col, '')) if type_col else ''
            self._lookup[name] = normalize_sample_type(raw_type)

            # Get batch info
            if batch_col and pd.notna(row.get(batch_col)):
                self._batch_lookup[name] = str(row[batch_col])
            else:
                self._batch_lookup[name] = None

    def get_sample_type(self, sample_name: str) -> str:
        """
        Get normalized sample type for a sample name.

        Args:
            sample_name: Sample name to look up

        Returns:
            One of: 'QC', 'Control', 'Exposure', 'Blank', 'Unknown'
        """
        key = normalize_sample_name(sample_name)
        return self._lookup.get(key, 'Unknown')

    def get_batch(self, sample_name: str) -> Optional[str]:
        """
        Get batch information for a sample.

        Args:
            sample_name: Sample name to look up

        Returns:
            Batch identifier or None
        """
        key = normalize_sample_name(sample_name)
        return self._batch_lookup.get(key)

    def classify_columns(
        self,
        columns: List[str]
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        """
        Classify columns into QC, Control, Exposure, and Other.
        Note: Normal samples are classified as separate from Control.

        Args:
            columns: List of column names to classify

        Returns:
            Tuple of (qc_columns, control_columns, exposure_columns, other_columns)
        """
        qc, control, exposure, other = [], [], [], []

        for col in columns:
            sample_type = self.get_sample_type(col)
            if sample_type == 'QC':
                qc.append(col)
            elif sample_type in ('Control', 'Normal'):
                control.append(col)
            elif sample_type == 'Exposure':
                exposure.append(col)
            else:
                other.append(col)

        return qc, control, exposure, other

    def get_sample_indices(
        self,
        columns: List[str],
        sample_type: str
    ) -> List[int]:
        """
        Get indices of columns matching a sample type.

        Args:
            columns: List of column names
            sample_type: Type to filter by ('QC', 'Control', 'Exposure')

        Returns:
            List of indices
        """
        return [
            i for i, col in enumerate(columns)
            if self.get_sample_type(col) == sample_type
        ]

    def get_samples_by_type(
        self,
        columns: List[str],
        sample_type: str
    ) -> List[str]:
        """
        Get column names matching a sample type.

        Args:
            columns: List of column names
            sample_type: Type to filter by ('QC', 'Control', 'Exposure')

        Returns:
            List of column names
        """
        return [
            col for col in columns
            if self.get_sample_type(col) == sample_type
        ]

    def get_qc_samples(self, columns: List[str]) -> List[str]:
        """Convenience method to get QC sample columns."""
        return self.get_samples_by_type(columns, 'QC')

    def get_control_samples(self, columns: List[str]) -> List[str]:
        """Convenience method to get Control sample columns."""
        return self.get_samples_by_type(columns, 'Control')

    def get_exposure_samples(self, columns: List[str]) -> List[str]:
        """Convenience method to get Exposure sample columns."""
        return self.get_samples_by_type(columns, 'Exposure')

    def get_normal_samples(self, columns: List[str]) -> List[str]:
        """Convenience method to get Normal sample columns."""
        return self.get_samples_by_type(columns, 'Normal')

    def get_type_counts(self, columns: List[str]) -> Dict[str, int]:
        """
        Count samples by type.

        Args:
            columns: List of column names

        Returns:
            Dictionary mapping type to count
        """
        from collections import Counter
        types = [self.get_sample_type(col) for col in columns]
        return dict(Counter(types))


def build_sample_info_mapping(
    sample_columns: List[str],
    sample_info_df: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """Map data columns to SampleInfo rows, preferring exact and normalized-name matches."""
    info_name_col = sample_info_df.columns[0]
    info_names = sample_info_df[info_name_col].astype(str).tolist()

    mapping: Dict[str, pd.Series] = {}
    exact_lookup: Dict[str, pd.Series] = {}
    normalized_lookup: Dict[str, pd.Series] = {}

    for _, row in sample_info_df.iterrows():
        exact_lookup.setdefault(str(row.get(info_name_col, '')), row)

        norm_name = normalize_sample_name(row.get(info_name_col, ''))
        if norm_name and norm_name not in normalized_lookup:
            normalized_lookup[norm_name] = row

    for sample in sample_columns:
        if sample in exact_lookup:
            mapping[sample] = exact_lookup[sample]

    for sample in sample_columns:
        if sample in mapping:
            continue
        norm_sample = normalize_sample_name(sample)
        if norm_sample in normalized_lookup:
            mapping[sample] = normalized_lookup[norm_sample]

    unmatched_samples = [sample for sample in sample_columns if sample not in mapping]
    if not unmatched_samples:
        return mapping

    def _extract_tokens(name: str) -> Tuple[set[str], set[str]]:
        value = str(name).strip().lower()
        value = re.sub(r'^(dna|rna)_program\d+_', '', value)
        parts = re.split(r'[\s_\-/]+', value)
        tokens = set()
        numbers = set()
        for part in parts:
            sub = re.findall(r'[a-z]+|[0-9]+', part)
            tokens.update(sub)
            combo = re.findall(r'[a-z]+\d+', part)
            tokens.update(combo)
            nums = re.findall(r'\d{3,}', part)
            numbers.update(nums)
        generic = {'tissue', 'cancer', 'breast', 'pooled', 'fat', 'dna', 'rna', 'and', 'program1'}
        return tokens - generic, numbers

    for sample in unmatched_samples:
        sample_tokens, sample_nums = _extract_tokens(sample)
        best_match = None
        best_score = 0

        for info_name in info_names:
            info_tokens, info_nums = _extract_tokens(info_name)
            num_overlap = len(sample_nums & info_nums)
            token_overlap = len(sample_tokens & info_tokens)

            if num_overlap > 0:
                score = 100 + num_overlap * 10 + token_overlap
            else:
                score = token_overlap

            if score > best_score:
                best_score = score
                best_match = info_name

        if best_match is not None and best_score >= 2:
            matched_rows = sample_info_df[sample_info_df[info_name_col].astype(str) == str(best_match)]
            if not matched_rows.empty:
                mapping[sample] = matched_rows.iloc[0]

    return mapping


def identify_sample_columns(
    df: pd.DataFrame,
    sample_info_df: pd.DataFrame
) -> Tuple[List[str], List[str]]:
    """
    Identify valid sample intensity columns from a DataFrame.

    Uses SampleInfo to match column names and filters out known
    non-sample columns (metadata, statistics, etc.).

    Args:
        df: DataFrame containing potential sample columns
        sample_info_df: SampleInfo DataFrame with Sample_Name column

    Returns:
        Tuple of (sample_columns, dropped_columns)
    """
    # Build lookup of valid sample names
    name_col = sample_info_df.columns[0]  # Usually Sample_Name
    sample_names = sample_info_df[name_col].astype(str).str.strip()
    sample_lookup = {normalize_sample_name(name) for name in sample_names}

    # Normalize non-sample column names
    non_sample_lower = {normalize_sample_name(col) for col in NON_SAMPLE_COLUMNS}
    stat_keywords = _normalized_stat_keywords()

    sample_columns = []
    dropped_columns = []

    for col in df.columns:
        col_norm = normalize_sample_name(col)

        # Skip known non-sample columns
        if col_norm in non_sample_lower:
            continue

        # Match against SampleInfo
        if col_norm in sample_lookup:
            sample_columns.append(col)
        else:
            # Check for statistical column patterns
            if any(keyword and keyword in col_norm for keyword in stat_keywords):
                dropped_columns.append(col)

    return sample_columns, dropped_columns


def identify_candidate_sample_columns(
    df: pd.DataFrame,
    extra_non_sample_columns: Optional[Collection[str]] = None,
) -> Tuple[List[str], List[str]]:
    """
    Identify all non-metadata columns that could be sample intensity columns.

    This is stricter than exact SampleInfo matching: it keeps unknown candidate
    columns so downstream processors can fail closed instead of silently dropping
    partially unmatched sample data.

    Args:
        df: DataFrame containing potential sample columns

    Returns:
        Tuple of (candidate_columns, dropped_columns)
    """
    non_sample_columns = set(NON_SAMPLE_COLUMNS)
    if extra_non_sample_columns:
        non_sample_columns.update(str(col) for col in extra_non_sample_columns)

    non_sample_lower = {normalize_sample_name(col) for col in non_sample_columns}
    stat_keywords = _normalized_stat_keywords()

    candidate_columns = []
    dropped_columns = []

    for col in df.columns:
        col_norm = normalize_sample_name(col)

        if col_norm in non_sample_lower:
            continue

        if any(keyword and keyword in col_norm for keyword in stat_keywords):
            dropped_columns.append(col)
            continue

        candidate_columns.append(col)

    return candidate_columns, dropped_columns


def get_sample_type_colors(sample_types: List[str]) -> List[str]:
    """
    Get colors for a list of sample types.

    Args:
        sample_types: List of sample type strings

    Returns:
        List of color hex codes
    """
    from .constants import SAMPLE_TYPE_COLORS

    return [
        SAMPLE_TYPE_COLORS.get(normalize_sample_type(t), SAMPLE_TYPE_COLORS['Unknown'])
        for t in sample_types
    ]


def get_sample_type_markers(sample_types: List[str]) -> List[str]:
    """
    Get markers for a list of sample types.

    Args:
        sample_types: List of sample type strings

    Returns:
        List of marker strings
    """
    from .constants import SAMPLE_TYPE_MARKERS

    return [
        SAMPLE_TYPE_MARKERS.get(normalize_sample_type(t), SAMPLE_TYPE_MARKERS['Unknown'])
        for t in sample_types
    ]
