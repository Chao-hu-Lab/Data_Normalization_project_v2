"""
matplotlib 繪圖設定

包含共用的繪圖設定和色彩定義。
"""
import os
import re
import sys

# Use a non-interactive backend by default to avoid Tk/Tcl dependency
# (common in CI / minimal Python installs). Users can override by setting
# the environment variable MPLBACKEND before running.
import matplotlib

if not os.environ.get('MPLBACKEND'):
    matplotlib.use('Agg', force=True)

import matplotlib.pyplot as plt

import numpy as np

# Import shared constants
from .constants import FONT_SIZES, COLORBLIND_COLORS, SAMPLE_TYPE_COLORS, SAMPLE_TYPE_MARKERS
from .sample_classification import normalize_sample_type


def normalize_batch_memberships(batch_labels=None, batch_memberships=None):
    """Normalize raw batch labels into per-sample tuple memberships."""
    raw_entries = batch_memberships if batch_memberships is not None else batch_labels
    if raw_entries is None:
        return None

    normalized = []
    for entry in raw_entries:
        if entry is None:
            parts = []
        elif isinstance(entry, str):
            parts = [part.strip() for part in entry.split(';') if part.strip()]
        elif isinstance(entry, (list, tuple, set)):
            parts = []
            for item in entry:
                parts.extend([part.strip() for part in str(item).split(';') if part.strip()])
        else:
            parts = [str(entry).strip()] if str(entry).strip() else []

        if not parts:
            parts = ['Unknown']

        normalized.append(tuple(dict.fromkeys(parts)))

    return normalized


def build_batch_group_indices(batch_memberships):
    """Build batch -> sample index mapping from normalized memberships."""
    normalized = normalize_batch_memberships(batch_memberships=batch_memberships) or []
    group_indices = {}

    for index, memberships in enumerate(normalized):
        for batch in memberships:
            group_indices.setdefault(batch, []).append(index)

    return {batch: group_indices[batch] for batch in sorted(group_indices)}


def slugify_plot_label(label):
    """Convert a user-facing label into a stable ASCII filename token."""
    text = re.sub(r'[^A-Za-z0-9]+', '_', str(label).strip())
    text = re.sub(r'_+', '_', text).strip('_')
    return text or 'Unknown'


def build_pca_comparison_suptitle(left_label, right_label, grouping=None):
    """Create a consistent user-facing PCA comparison title."""
    title = f"2D PCA Comparison: {left_label} vs {right_label}"
    if grouping == "batch":
        return f"{title} (Grouped by Batch)"
    if grouping == "sample_type":
        return f"{title} (Grouped by Sample Type)"
    return title


def build_pca_comparison_filename(step_label, left_label, right_label, grouping=None, timestamp=None):
    """Create a consistent PCA figure filename across workflow steps."""
    parts = [
        slugify_plot_label(step_label),
        "PCA",
        slugify_plot_label(left_label),
        "vs",
        slugify_plot_label(right_label),
    ]
    if grouping:
        parts.extend(["grouped_by", slugify_plot_label(grouping)])
    if timestamp:
        parts.append(str(timestamp))
    return "_".join(parts) + ".png"


def get_visible_sample_types(sample_types):
    """Return sample types in a stable, user-facing legend order."""
    priority = {
        'QC': 0,
        'Normal': 1,
        'Control': 2,
        'Exposure': 3,
        'Blank': 4,
        'Unknown': 5,
    }
    return sorted(set(sample_types), key=lambda t: (priority.get(t, 99), t))


def build_sample_type_group_indices(sample_types, exclude_types=None):
    """Build sample-type -> sample index mapping in stable display order."""
    exclude = {normalize_sample_type(t) for t in (exclude_types or set())}
    normalized_types = [normalize_sample_type(t) for t in sample_types]

    group_indices = {}
    for index, sample_type in enumerate(normalized_types):
        if sample_type in exclude:
            continue
        group_indices.setdefault(sample_type, []).append(index)

    ordered_types = get_visible_sample_types(group_indices.keys())
    return {sample_type: group_indices[sample_type] for sample_type in ordered_types}


def plot_pca_comparison_qc_style(
    scores_left,
    scores_right,
    var_left,
    var_right,
    sample_names,
    sample_types,
    batch_labels=None,
    batch_memberships=None,
    *,
    grouping='batch',
    suptitle=None,
    left_title=None,
    right_title=None,
    left_threshold_text=None,
    right_threshold_text=None,
    qc_outlier_names_left=None,
    qc_outlier_names_right=None,
    output_path=None,
    dpi=300,
):
    """Create a QC_LOWESS-style 2-panel PCA comparison plot.

    This is a shared plotting utility to keep PCA figure style consistent across
    subprograms (legend, figsize, layout).

    Parameters
    ----------
    scores_left, scores_right : array-like, shape (n_samples, 2)
        PCA scores (PC1/PC2) for left/right panels.
    var_left, var_right : array-like, shape (2,)
        Explained variance ratios for PC1/PC2.
    sample_names : list[str]
        Sample names aligned with rows of scores.
    sample_types : list[str]
        Each is one of: 'QC', 'Control', 'Exposure' (case-insensitive allowed).
    batch_labels : list[str] | None
        Batch label per sample; required when grouping='batch'.
    grouping : {'batch','sample_type'}
        Controls confidence ellipse mode.
    qc_outlier_names_left/right : set[str] | None
        Names of QC samples marked as outliers for each panel.
    output_path : str | os.PathLike | None
        If provided, saves the figure.

    Returns
    -------
    (fig, (ax_left, ax_right))
    """
    from .statistics import draw_hotelling_t2_ellipse

    scores_left = np.asarray(scores_left)
    scores_right = np.asarray(scores_right)
    var_left = np.asarray(var_left)
    var_right = np.asarray(var_right)

    if scores_left.shape[1] != 2 or scores_right.shape[1] != 2:
        raise ValueError('scores_left/scores_right must be (n_samples, 2)')
    if len(sample_names) != scores_left.shape[0] or len(sample_names) != scores_right.shape[0]:
        raise ValueError('sample_names length must match number of rows in scores')
    if len(sample_types) != len(sample_names):
        raise ValueError('sample_types length must match sample_names')

    if grouping not in ('batch', 'sample_type'):
        raise ValueError("grouping must be 'batch' or 'sample_type'")
    if grouping == 'batch':
        raw_batches = batch_memberships if batch_memberships is not None else batch_labels
        if raw_batches is None or len(raw_batches) != len(sample_names):
            raise ValueError(
                "batch_labels or batch_memberships is required for grouping='batch' and must align with sample_names"
            )

    qc_outlier_names_left = set(qc_outlier_names_left or [])
    qc_outlier_names_right = set(qc_outlier_names_right or [])

    sample_types_norm = [normalize_sample_type(t) for t in sample_types]

    # Dynamic color/marker maps based on actual types present
    color_map = dict(SAMPLE_TYPE_COLORS)  # copy defaults
    markers = dict(SAMPLE_TYPE_MARKERS)

    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(20, 8))
    if suptitle:
        fig.suptitle(suptitle, fontsize=16, y=0.98, fontweight='bold')

    if grouping == 'batch':
        normalized_batch_memberships = normalize_batch_memberships(
            batch_labels=batch_labels,
            batch_memberships=batch_memberships,
        )
        batch_group_indices = build_batch_group_indices(normalized_batch_memberships)
        unique_batches = list(batch_group_indices)
        batch_colors = COLORBLIND_COLORS * ((len(unique_batches) // len(COLORBLIND_COLORS)) + 1)
        batch_color_map = {batch: batch_colors[i] for i, batch in enumerate(unique_batches)}
    else:
        normalized_batch_memberships = None
        batch_group_indices = {}
        unique_batches = []
        batch_color_map = {}

    def scatter_panel(ax, scores, var, title_text, threshold_text, qc_outliers):
        for i, sample in enumerate(sample_names):
            s_type = sample_types_norm[i]
            color = color_map.get(s_type, SAMPLE_TYPE_COLORS.get('Unknown', '#808080'))
            marker = markers.get(s_type, SAMPLE_TYPE_MARKERS.get('Unknown', 'x'))
            is_outlier = (s_type == 'QC') and (sample in qc_outliers)

            if is_outlier:
                edgecolor = 'red'
                linewidth = 3
                size = 150
                alpha = 0.9
            else:
                edgecolor = 'black'
                linewidth = 1
                size = 100
                alpha = 0.7

            ax.scatter(
                scores[i, 0], scores[i, 1],
                c=[color], marker=marker,
                s=size, alpha=alpha,
                edgecolors=edgecolor, linewidths=linewidth,
            )

        all_bounds = []
        if grouping == 'batch':
            for batch in unique_batches:
                batch_indices = batch_group_indices.get(batch, [])
                if len(batch_indices) >= 3:
                    batch_scores = scores[batch_indices]
                    bounds = draw_hotelling_t2_ellipse(
                        ax,
                        batch_scores,
                        label=f'95% CI (Batch {batch})',
                        edgecolor=batch_color_map[batch],
                        linestyle='-',
                        linewidth=2.5,
                    )
                    if bounds is not None:
                        all_bounds.append(bounds)
        else:
            bounds_all = draw_hotelling_t2_ellipse(
                ax,
                scores,
                label='95% CI (All Samples)',
                edgecolor='gray',
                linestyle='--',
                linewidth=3,
            )
            if bounds_all is not None:
                all_bounds.append(bounds_all)

            qc_indices = [i for i, t in enumerate(sample_types_norm) if t == 'QC']
            if len(qc_indices) >= 3:
                qc_scores = scores[qc_indices]
                bounds_qc = draw_hotelling_t2_ellipse(
                    ax,
                    qc_scores,
                    label='95% CI (QC Only)',
                    edgecolor='#9370DB',
                    linestyle='-',
                    linewidth=3,
                )
                if bounds_qc is not None:
                    all_bounds.append(bounds_qc)

        if all_bounds:
            x_min = min(b[0] for b in all_bounds)
            x_max = max(b[1] for b in all_bounds)
            y_min = min(b[2] for b in all_bounds)
            y_max = max(b[3] for b in all_bounds)
        else:
            x_min, x_max = np.min(scores[:, 0]), np.max(scores[:, 0])
            y_min, y_max = np.min(scores[:, 1]), np.max(scores[:, 1])

        x_range = (x_max - x_min) or 1
        y_range = (y_max - y_min) or 1
        ax.set_xlim(x_min - x_range * 0.2, x_max + x_range * 0.2)
        ax.set_ylim(y_min - y_range * 0.2, y_max + y_range * 0.2)

        ax.set_xlabel(f'PC1 ({var[0]*100:.1f}%)', fontsize=12, fontweight='bold')
        ax.set_ylabel(f'PC2 ({var[1]*100:.1f}%)', fontsize=12, fontweight='bold')

        title_lines = [title_text]
        if threshold_text:
            title_lines.append(threshold_text)
        ax.set_title('\n'.join(title_lines), fontsize=14, fontweight='bold', pad=15)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        ax.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        ax.grid(True, alpha=0.3, linestyle='--')

    scatter_panel(
        ax_left,
        scores_left,
        var_left,
        left_title or 'Left',
        left_threshold_text,
        qc_outlier_names_left,
    )
    scatter_panel(
        ax_right,
        scores_right,
        var_right,
        right_title or 'Right',
        right_threshold_text,
        qc_outlier_names_right,
    )

    # Build legend dynamically from the sample types actually present
    unique_types = get_visible_sample_types(sample_types_norm)
    sample_legend_elements = []
    for stype in unique_types:
        sample_legend_elements.append(
            plt.Line2D([0], [0],
                       marker=markers.get(stype, 'x'), color='w',
                       markerfacecolor=color_map.get(stype, '#808080'),
                       markersize=10, label=stype,
                       markeredgecolor='black', markeredgewidth=1)
        )
    # Always add QC Outlier entry if QC is present
    if 'QC' in unique_types:
        sample_legend_elements.append(
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#9370DB',
                       markersize=10, label='QC Outlier', markeredgecolor='red', markeredgewidth=3),
        )

    if grouping == 'batch':
        ellipse_legend_elements = [
            plt.Line2D([0], [0], linestyle='-', color=batch_color_map[batch],
                       linewidth=2.5, label=f'95% CI (Batch {batch})')
            for batch in unique_batches
        ]
    else:
        ellipse_legend_elements = [
            plt.Line2D([0], [0], linestyle='-', color='#9370DB', linewidth=3, label='95% CI (QC Only)'),
            plt.Line2D([0], [0], linestyle='--', color='gray', linewidth=3, label='95% CI (All Samples)'),
        ]

    for ax in (ax_left, ax_right):
        legend1 = ax.legend(
            handles=sample_legend_elements,
            loc='upper left',
            fontsize=9,
            title='Sample Type',
            title_fontsize=10,
            frameon=True,
            fancybox=True,
            shadow=True,
        )
        ax.add_artist(legend1)
        ax.legend(
            handles=ellipse_legend_elements,
            loc='upper right',
            fontsize=9,
            title='Confidence Ellipse',
            title_fontsize=10,
            frameon=True,
            fancybox=True,
            shadow=True,
        )

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    if output_path is not None:
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight')

    return fig, (ax_left, ax_right)


def plot_pca_comparison_real_sample_style(
    scores_left,
    scores_right,
    var_left,
    var_right,
    sample_names,
    sample_types,
    *,
    suptitle=None,
    left_title=None,
    right_title=None,
    output_path=None,
    dpi=300,
):
    """Create a 2-panel PCA comparison plot for real samples only."""
    from .statistics import draw_hotelling_t2_ellipse

    scores_left = np.asarray(scores_left)
    scores_right = np.asarray(scores_right)
    var_left = np.asarray(var_left)
    var_right = np.asarray(var_right)

    if scores_left.shape[1] != 2 or scores_right.shape[1] != 2:
        raise ValueError('scores_left/scores_right must be (n_samples, 2)')
    if len(sample_names) != scores_left.shape[0] or len(sample_names) != scores_right.shape[0]:
        raise ValueError('sample_names length must match number of rows in scores')
    if len(sample_types) != len(sample_names):
        raise ValueError('sample_types length must match sample_names')

    sample_types_norm = [normalize_sample_type(t) for t in sample_types]
    group_indices = build_sample_type_group_indices(sample_types_norm, exclude_types={'QC'})
    visible_types = list(group_indices)
    non_qc_indices = [index for sample_type, indices in group_indices.items() for index in indices]

    color_map = dict(SAMPLE_TYPE_COLORS)
    markers = dict(SAMPLE_TYPE_MARKERS)

    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(20, 8))
    if suptitle:
        fig.suptitle(suptitle, fontsize=16, y=0.98, fontweight='bold')

    def scatter_panel(ax, scores, var, title_text):
        for index, sample in enumerate(sample_names):
            sample_type = sample_types_norm[index]
            if sample_type == 'QC':
                continue

            color = color_map.get(sample_type, SAMPLE_TYPE_COLORS.get('Unknown', '#808080'))
            marker = markers.get(sample_type, SAMPLE_TYPE_MARKERS.get('Unknown', 'x'))
            ax.scatter(
                scores[index, 0],
                scores[index, 1],
                c=[color],
                marker=marker,
                s=100,
                alpha=0.7,
                edgecolors='black',
                linewidths=1,
            )

        all_bounds = []
        if len(non_qc_indices) >= 3:
            all_scores = scores[non_qc_indices]
            bounds_all = draw_hotelling_t2_ellipse(
                ax,
                all_scores,
                label='95% CI (All Samples)',
                edgecolor='gray',
                linestyle='--',
                linewidth=3,
            )
            if bounds_all is not None:
                all_bounds.append(bounds_all)
        else:
            all_scores = scores

        ellipse_types = []
        for sample_type in visible_types:
            indices = group_indices.get(sample_type, [])
            if len(indices) < 3:
                continue
            ellipse_types.append(sample_type)
            bounds = draw_hotelling_t2_ellipse(
                ax,
                scores[indices],
                label=f'95% CI ({sample_type})',
                edgecolor=color_map.get(sample_type, '#808080'),
                linestyle='-',
                linewidth=2.5,
            )
            if bounds is not None:
                all_bounds.append(bounds)

        if all_bounds:
            x_min = min(b[0] for b in all_bounds)
            x_max = max(b[1] for b in all_bounds)
            y_min = min(b[2] for b in all_bounds)
            y_max = max(b[3] for b in all_bounds)
        else:
            x_min, x_max = np.min(all_scores[:, 0]), np.max(all_scores[:, 0])
            y_min, y_max = np.min(all_scores[:, 1]), np.max(all_scores[:, 1])

        x_range = (x_max - x_min) or 1
        y_range = (y_max - y_min) or 1
        ax.set_xlim(x_min - x_range * 0.2, x_max + x_range * 0.2)
        ax.set_ylim(y_min - y_range * 0.2, y_max + y_range * 0.2)

        ax.set_xlabel(f'PC1 ({var[0]*100:.1f}%)', fontsize=12, fontweight='bold')
        ax.set_ylabel(f'PC2 ({var[1]*100:.1f}%)', fontsize=12, fontweight='bold')
        ax.set_title(title_text, fontsize=14, fontweight='bold', pad=15)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        ax.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        ax.grid(True, alpha=0.3, linestyle='--')

        return ellipse_types

    left_ellipse_types = scatter_panel(ax_left, scores_left, var_left, left_title or 'Left')
    right_ellipse_types = scatter_panel(ax_right, scores_right, var_right, right_title or 'Right')

    sample_legend_elements = [
        plt.Line2D(
            [0],
            [0],
            marker=markers.get(sample_type, 'x'),
            color='w',
            markerfacecolor=color_map.get(sample_type, '#808080'),
            markersize=10,
            label=sample_type,
            markeredgecolor='black',
            markeredgewidth=1,
        )
        for sample_type in visible_types
    ]

    ellipse_types = []
    for sample_type in left_ellipse_types + right_ellipse_types:
        if sample_type not in ellipse_types:
            ellipse_types.append(sample_type)
    ellipse_legend_elements = [
        plt.Line2D([0], [0], linestyle='--', color='gray', linewidth=3, label='95% CI (All Samples)'),
        *[
            plt.Line2D(
                [0],
                [0],
                linestyle='-',
                color=color_map.get(sample_type, '#808080'),
                linewidth=2.5,
                label=f'95% CI ({sample_type})',
            )
            for sample_type in ellipse_types
        ],
    ]

    for ax in (ax_left, ax_right):
        legend1 = ax.legend(
            handles=sample_legend_elements,
            loc='upper left',
            fontsize=9,
            title='Sample Type',
            title_fontsize=10,
            frameon=True,
            fancybox=True,
            shadow=True,
        )
        ax.add_artist(legend1)
        ax.legend(
            handles=ellipse_legend_elements,
            loc='upper right',
            fontsize=9,
            title='Confidence Ellipse',
            title_fontsize=10,
            frameon=True,
            fancybox=True,
            shadow=True,
        )

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    if output_path is not None:
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight')

    return fig, (ax_left, ax_right)


# COLORBLIND_COLORS is imported from .constants


def setup_matplotlib():
    """
    設定 matplotlib 全域參數

    - 關閉 LaTeX 渲染
    - 根據作業系統設定適當的字體
    - 設定預設樣式

    Returns:
    --------
    dict : 包含設定資訊的字典
    """
    # 關閉 LaTeX
    plt.rcParams['text.usetex'] = False
    plt.rcParams['mathtext.default'] = 'regular'

    # 根據作業系統設定字體
    if sys.platform == 'darwin':
        plt.rcParams['font.family'] = 'Helvetica'
    else:
        plt.rcParams['font.family'] = 'Arial'

    return {
        'font_family': plt.rcParams['font.family'],
        'platform': sys.platform
    }
