import os
from datetime import datetime

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from metabolomics.utils.constants import COLORBLIND_COLORS, DATETIME_FORMAT_FULL, FEATURE_ID_COLUMN, SHEET_NAMES
from metabolomics.utils.data_helpers import extract_sample_type_row, insert_sample_type_row
from metabolomics.utils.excel_format import copy_sheet_formatting_only
from metabolomics.utils.file_io import build_output_path, build_plots_dir
from metabolomics.utils.plotting import (
    build_batch_group_indices,
    plot_pca_comparison_qc_style,
    setup_matplotlib,
)
from metabolomics.utils.results import ProcessingResult
from metabolomics.utils.sample_classification import (
    identify_sample_columns,
    normalize_sample_name,
    normalize_sample_type,
)
from metabolomics.utils.statistics import calculate_hotelling_t2_outliers


RESULT_SHEET_NAME = SHEET_NAMES.get("qc_batch_scaling", "QC_Batch_Scaling_result")
SUMMARY_SHEET_NAME = SHEET_NAMES.get("qc_batch_scaling_summary", "QC_Batch_Scaling_summary")

setup_matplotlib()
import matplotlib.pyplot as plt


def parse_batch_labels(value):
    """Parse semicolon-separated batch labels and trim whitespace."""
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def build_batch_membership(sample_info_df, sample_columns=None):
    """Build batch-to-QC and batch-to-sample mappings from SampleInfo."""
    batch_to_qc = {}
    batch_to_samples = {}
    column_lookup = {}

    if sample_columns:
        column_lookup = {
            normalize_sample_name(column): column
            for column in sample_columns
        }

    for _, row in sample_info_df.iterrows():
        sample_name = str(row["Sample_Name"]).strip()
        if column_lookup:
            sample_name = column_lookup.get(normalize_sample_name(sample_name))
            if not sample_name:
                continue
        sample_type = normalize_sample_type(row.get("Sample_Type", ""))
        batches = parse_batch_labels(row.get("Batch", ""))

        if sample_type != "QC" and len(batches) != 1:
            raise ValueError("Non-QC samples must belong to a single batch")

        for batch in batches:
            batch_to_samples.setdefault(batch, []).append(sample_name)
            if sample_type == "QC":
                batch_to_qc.setdefault(batch, []).append(sample_name)

    return batch_to_qc, batch_to_samples


def scale_feature_by_batch_qc_median(feature_row, batch_to_qc, batch_to_samples):
    """Scale one feature row by each batch's QC median."""
    scaled = dict(feature_row)
    medians = {}
    sample_scaled_values = {}

    for batch, qc_samples in batch_to_qc.items():
        qc_values = pd.to_numeric(
            pd.Series([feature_row.get(sample, np.nan) for sample in qc_samples]),
            errors="coerce",
        )
        qc_values = qc_values[np.isfinite(qc_values) & (qc_values > 0)]
        batch_median = float(np.median(qc_values)) if not qc_values.empty else np.nan
        medians[batch] = batch_median

        if not np.isfinite(batch_median) or batch_median <= 0:
            continue

        for sample in batch_to_samples.get(batch, []):
            value = pd.to_numeric(pd.Series([feature_row.get(sample, np.nan)]), errors="coerce").iloc[0]
            if np.isfinite(value) and value > 0:
                sample_scaled_values.setdefault(sample, []).append(float(value / batch_median))

    for sample, candidates in sample_scaled_values.items():
        if candidates:
            scaled[sample] = float(np.median(candidates))

    return scaled, medians


def select_source_sheet(sheet_names):
    """Pick the best upstream sheet for Step 3."""
    for sheet_name in (
        SHEET_NAMES["qc_lowess"],
        SHEET_NAMES["istd_correction"],
        SHEET_NAMES["raw_intensity"],
    ):
        if sheet_name in sheet_names:
            return sheet_name
    raise ValueError("No supported upstream data sheet found for QC batch scaling")


def load_and_process_data(input_file):
    """Load the selected upstream data sheet and SampleInfo."""
    if not os.path.exists(input_file):
        raise FileNotFoundError(input_file)

    excel_file = pd.ExcelFile(input_file)
    if SHEET_NAMES["sample_info"] not in excel_file.sheet_names:
        raise ValueError(f"Missing required sheet: {SHEET_NAMES['sample_info']}")

    source_sheet_name = select_source_sheet(excel_file.sheet_names)
    sample_info_df = pd.read_excel(excel_file, sheet_name=SHEET_NAMES["sample_info"])
    data_df = pd.read_excel(excel_file, sheet_name=source_sheet_name)

    feature_col = data_df.columns[0]
    data_df, sample_type_row = extract_sample_type_row(data_df, feature_col)
    if FEATURE_ID_COLUMN in data_df.columns and FEATURE_ID_COLUMN != "FeatureID":
        data_df = data_df.rename(columns={FEATURE_ID_COLUMN: "FeatureID"})
    elif "FeatureID" not in data_df.columns:
        data_df = data_df.rename(columns={feature_col: "FeatureID"})

    sample_columns, _ = identify_sample_columns(data_df, sample_info_df)
    data_df.attrs["sample_columns"] = sample_columns
    data_df.attrs["source_sheet_name"] = source_sheet_name

    return data_df, sample_info_df, sample_columns, source_sheet_name, sample_type_row


def scale_dataframe_by_qc_medians(data_df, sample_columns, batch_to_qc, batch_to_samples):
    """Apply QC median scaling feature by feature."""
    result_df = data_df.copy()
    invalid_median_counts = {batch: 0 for batch in batch_to_qc}

    for idx, row in data_df.iterrows():
        scaled_row, medians = scale_feature_by_batch_qc_median(row, batch_to_qc, batch_to_samples)
        for sample in sample_columns:
            if sample in scaled_row:
                result_df.at[idx, sample] = scaled_row[sample]
        for batch, median in medians.items():
            if not np.isfinite(median) or median <= 0:
                invalid_median_counts[batch] += 1

    return result_df, invalid_median_counts


def build_summary_df(source_sheet_name, batch_to_qc, batch_to_samples, invalid_median_counts):
    """Build a simple summary sheet for QC batch scaling."""
    rows = [
        {"Section": "run", "Item": "source_sheet", "Value": source_sheet_name},
        {"Section": "run", "Item": "batch_count", "Value": len(batch_to_qc)},
    ]

    for batch in sorted(batch_to_samples):
        rows.append(
            {
                "Section": "batch",
                "Item": batch,
                "Value": f"qc={len(batch_to_qc.get(batch, []))}; samples={len(batch_to_samples.get(batch, []))}; invalid_feature_medians={invalid_median_counts.get(batch, 0)}",
            }
        )

    return pd.DataFrame(rows)


def build_plot_metadata(sample_columns, sample_info_df):
    """Build sample type and batch metadata aligned with sample columns."""
    sample_info_norm = sample_info_df.copy()
    sample_info_norm["_norm_name"] = sample_info_norm["Sample_Name"].map(normalize_sample_name)
    sample_info_norm = sample_info_norm[sample_info_norm["_norm_name"].astype(bool)]
    sample_meta = sample_info_norm.drop_duplicates("_norm_name").set_index("_norm_name")

    sample_types = []
    batch_memberships = []
    qc_indices = []

    for index, sample in enumerate(sample_columns):
        meta_key = normalize_sample_name(sample)
        if meta_key in sample_meta.index:
            raw_type = str(sample_meta.loc[meta_key].get("Sample_Type", "Unknown"))
            raw_batch = sample_meta.loc[meta_key].get("Batch", "Unknown")
        else:
            raw_type = "Unknown"
            raw_batch = "Unknown"

        sample_type = normalize_sample_type(raw_type)
        memberships = tuple(parse_batch_labels(raw_batch) or ["Unknown"])

        sample_types.append(sample_type)
        batch_memberships.append(memberships)

        if sample_type == "QC":
            qc_indices.append(index)

    return sample_types, batch_memberships, qc_indices


def prepare_pca_matrix(df, sample_columns):
    """Build a PCA-ready matrix from the selected sample columns."""
    data_matrix = (
        df[sample_columns]
        .apply(pd.to_numeric, errors="coerce")
        .T
        .to_numpy(dtype=float)
    )
    data_matrix = np.nan_to_num(data_matrix, nan=0.0, posinf=0.0, neginf=0.0)
    data_matrix[data_matrix < 0] = 0

    non_zero_features = np.any(data_matrix != 0, axis=0)
    data_matrix = data_matrix[:, non_zero_features]
    if data_matrix.shape[1] < 2:
        return None

    data_matrix = np.log2(data_matrix + 1)
    return StandardScaler().fit_transform(data_matrix)


def prepare_residual_matrix(df, sample_columns):
    """Build a standardized sample-by-feature matrix for residual analysis."""
    data_matrix = (
        df[sample_columns]
        .apply(pd.to_numeric, errors="coerce")
        .T
        .to_numpy(dtype=float)
    )
    data_matrix = np.nan_to_num(data_matrix, nan=0.0, posinf=0.0, neginf=0.0)
    data_matrix[data_matrix < 0] = 0

    non_zero_features = np.any(data_matrix != 0, axis=0)
    data_matrix = data_matrix[:, non_zero_features]
    if data_matrix.shape[1] < 1:
        return None

    data_matrix = np.log2(data_matrix + 1)
    return StandardScaler().fit_transform(data_matrix)


def calculate_batch_residuals(scaled_matrix, sample_columns, batch_memberships):
    """Calculate per-batch residuals against the global mean for each feature."""
    if scaled_matrix is None:
        return {}
    if scaled_matrix.shape[0] != len(sample_columns):
        raise ValueError("scaled_matrix rows must align with sample_columns")

    group_indices = build_batch_group_indices(batch_memberships)
    if not group_indices:
        return {}

    global_mean = np.mean(scaled_matrix, axis=0)
    residuals = {}

    for batch, indices in group_indices.items():
        if not indices:
            continue
        batch_data = scaled_matrix[indices]
        if batch_data.size == 0:
            continue
        batch_mean = np.mean(batch_data, axis=0)
        residuals[batch] = batch_mean - global_mean

    return residuals


def plot_batch_residual_analysis(
    residuals_before,
    residuals_after,
    *,
    output_path=None,
    dpi=300,
):
    """Plot before/after residual scatter for each batch."""
    unique_batches = sorted(set(residuals_before) | set(residuals_after))
    colors = COLORBLIND_COLORS * ((len(unique_batches) // len(COLORBLIND_COLORS)) + 1)
    batch_color_map = {batch: colors[i] for i, batch in enumerate(unique_batches)}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    for batch in unique_batches:
        before = residuals_before.get(batch)
        if before is not None and len(before):
            ax1.scatter(
                np.arange(len(before)),
                before,
                color=batch_color_map[batch],
                alpha=0.6,
                s=30,
                label=f"Batch {batch}",
            )

        after = residuals_after.get(batch)
        if after is not None and len(after):
            ax2.scatter(
                np.arange(len(after)),
                after,
                color=batch_color_map[batch],
                alpha=0.6,
                s=30,
                label=f"Batch {batch}",
            )

    for ax, title in (
        (ax1, "Before Correction\n(Systematic batch bias visible)"),
        (ax2, "After Correction\n(Random scatter around zero = good)"),
    ):
        ax.axhline(y=0, color="red", linestyle="--", linewidth=2, label="Zero Line")
        ax.set_xlabel("Feature Index", fontsize=12, fontweight="bold")
        ax.set_ylabel("Residual (Batch Mean - Global Mean)", fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)

    all_residuals = []
    for values in list(residuals_before.values()) + list(residuals_after.values()):
        if values is not None and len(values):
            all_residuals.extend(np.asarray(values, dtype=float).tolist())

    y_max = max(np.abs(all_residuals)) if all_residuals else 1.0
    ax1.set_ylim(-y_max * 1.1, y_max * 1.1)
    ax2.set_ylim(-y_max * 1.1, y_max * 1.1)

    plt.suptitle("QC Batch Scaling Residual Analysis", fontsize=16, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.96])

    if output_path is not None:
        plt.savefig(output_path, dpi=dpi, bbox_inches="tight")

    return fig


def generate_pca_plots(source_df, result_df, sample_columns, sample_info_df, input_file, timestamp):
    """Generate before/after PCA plots for QC Batch Scaling."""
    plots_dir = build_plots_dir(
        "QC_Batch_Scaling_plots",
        input_file=input_file,
        timestamp=timestamp,
        session_prefix="QC_Batch_Scaling",
    )

    if len(sample_columns) < 3:
        return str(plots_dir)

    source_matrix = prepare_pca_matrix(source_df, sample_columns)
    result_matrix = prepare_pca_matrix(result_df, sample_columns)
    if source_matrix is None or result_matrix is None:
        return str(plots_dir)

    pca_source = PCA(n_components=2)
    pca_result = PCA(n_components=2)
    scores_source = pca_source.fit_transform(source_matrix)
    scores_result = pca_result.fit_transform(result_matrix)
    var_source = pca_source.explained_variance_ratio_
    var_result = pca_result.explained_variance_ratio_

    sample_types, batch_memberships, qc_indices = build_plot_metadata(sample_columns, sample_info_df)
    qc_sample_names = [sample_columns[i] for i in qc_indices]

    if len(qc_indices) >= 3:
        qc_scores_source = scores_source[qc_indices]
        qc_scores_result = scores_result[qc_indices]
        _, source_threshold, source_outliers = calculate_hotelling_t2_outliers(
            qc_scores_source, scores_source, alpha=0.05
        )
        _, result_threshold, result_outliers = calculate_hotelling_t2_outliers(
            qc_scores_result, scores_result, alpha=0.05
        )
        qc_outliers_left = {
            qc_sample_names[i] for i in range(len(qc_sample_names)) if i < len(source_outliers) and source_outliers[i]
        }
        qc_outliers_right = {
            qc_sample_names[i] for i in range(len(qc_sample_names)) if i < len(result_outliers) and result_outliers[i]
        }
    else:
        source_threshold = np.nan
        result_threshold = np.nan
        qc_outliers_left = set()
        qc_outliers_right = set()

    batch_plot_path = os.path.join(plots_dir, f"Fig1_PCA_by_batch_{timestamp}.png")
    plot_pca_comparison_qc_style(
        scores_source,
        scores_result,
        var_source,
        var_result,
        sample_columns,
        sample_types,
        batch_memberships=batch_memberships,
        grouping="batch",
        suptitle="2D PCA Comparison: Before vs After QC Batch Scaling (Grouped by Batch)",
        left_title="Before QC Batch Scaling",
        right_title="After QC Batch Scaling",
        left_threshold_text=(f"Hotelling T² Threshold: {source_threshold:.2f}" if len(qc_indices) >= 3 else None),
        right_threshold_text=(f"Hotelling T² Threshold: {result_threshold:.2f}" if len(qc_indices) >= 3 else None),
        qc_outlier_names_left=qc_outliers_left,
        qc_outlier_names_right=qc_outliers_right,
        output_path=batch_plot_path,
        dpi=300,
    )

    sample_type_plot_path = os.path.join(plots_dir, f"Fig2_PCA_by_sample_type_{timestamp}.png")
    plot_pca_comparison_qc_style(
        scores_source,
        scores_result,
        var_source,
        var_result,
        sample_columns,
        sample_types,
        grouping="sample_type",
        suptitle="2D PCA Comparison: Before vs After QC Batch Scaling (Grouped by Sample Type)",
        left_title="Before QC Batch Scaling",
        right_title="After QC Batch Scaling",
        left_threshold_text=(f"Hotelling T² Threshold: {source_threshold:.2f}" if len(qc_indices) >= 3 else None),
        right_threshold_text=(f"Hotelling T² Threshold: {result_threshold:.2f}" if len(qc_indices) >= 3 else None),
        qc_outlier_names_left=qc_outliers_left,
        qc_outlier_names_right=qc_outliers_right,
        output_path=sample_type_plot_path,
        dpi=300,
    )

    residual_source = prepare_residual_matrix(source_df, sample_columns)
    residual_result = prepare_residual_matrix(result_df, sample_columns)
    if residual_source is not None and residual_result is not None:
        residuals_before = calculate_batch_residuals(
            residual_source,
            sample_columns,
            batch_memberships,
        )
        residuals_after = calculate_batch_residuals(
            residual_result,
            sample_columns,
            batch_memberships,
        )
        if residuals_before and residuals_after:
            residual_plot_path = os.path.join(plots_dir, f"Fig3_Residual_Analysis_{timestamp}.png")
            plot_batch_residual_analysis(
                residuals_before,
                residuals_after,
                output_path=residual_plot_path,
                dpi=300,
            )

    return str(plots_dir)


def save_results_to_excel(
    source_df,
    result_df,
    sample_info_df,
    summary_df,
    output_file,
    input_file,
    source_sheet_name,
    sample_type_row=None,
):
    """Save the new Step 3 workbook, keeping only the selected upstream sheet."""
    source_export = source_df.copy()
    result_export = result_df.copy()

    def _rename_feature_col_for_output(df):
        if "FeatureID" in df.columns and FEATURE_ID_COLUMN != "FeatureID":
            return df.rename(columns={"FeatureID": FEATURE_ID_COLUMN})
        return df

    source_export = _rename_feature_col_for_output(source_export)
    result_export = _rename_feature_col_for_output(result_export)

    if sample_type_row is not None:
        source_export = insert_sample_type_row(source_export, sample_type_row, feature_col=FEATURE_ID_COLUMN)
        result_export = insert_sample_type_row(result_export, sample_type_row, feature_col=FEATURE_ID_COLUMN)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        source_export.to_excel(writer, sheet_name=source_sheet_name, index=False)
        sample_info_df.to_excel(writer, sheet_name=SHEET_NAMES["sample_info"], index=False)
        result_export.to_excel(writer, sheet_name=RESULT_SHEET_NAME, index=False)
        summary_df.to_excel(writer, sheet_name=SUMMARY_SHEET_NAME, index=False)

    original_wb = load_workbook(input_file)
    new_wb = load_workbook(output_file)
    try:
        if source_sheet_name in original_wb.sheetnames and source_sheet_name in new_wb.sheetnames:
            copy_sheet_formatting_only(original_wb[source_sheet_name], new_wb[source_sheet_name])
        new_wb.save(output_file)
    finally:
        original_wb.close()
        new_wb.close()


def main(input_file=None):
    """Run QC batch scaling on the selected upstream sheet."""
    if not input_file:
        raise ValueError("input_file is required")

    data_df, sample_info_df, sample_columns, source_sheet_name, sample_type_row = load_and_process_data(input_file)
    batch_to_qc, batch_to_samples = build_batch_membership(
        sample_info_df,
        sample_columns=sample_columns,
    )
    result_df, invalid_median_counts = scale_dataframe_by_qc_medians(
        data_df, sample_columns, batch_to_qc, batch_to_samples
    )
    summary_df = build_summary_df(source_sheet_name, batch_to_qc, batch_to_samples, invalid_median_counts)

    timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
    plots_dir = generate_pca_plots(
        data_df,
        result_df,
        sample_columns,
        sample_info_df,
        input_file,
        timestamp,
    )
    output_file = build_output_path("QC_Batch_Scaling", input_file=input_file, timestamp=timestamp)
    save_results_to_excel(
        data_df,
        result_df,
        sample_info_df,
        summary_df,
        output_file,
        input_file,
        source_sheet_name,
        sample_type_row=sample_type_row,
    )

    return ProcessingResult(
        file_path=input_file,
        output_path=str(output_file),
        metabolites=len(result_df),
        samples=len(sample_columns),
        plots_dir=plots_dir,
        extra={"batches": len(batch_to_qc)},
    )
