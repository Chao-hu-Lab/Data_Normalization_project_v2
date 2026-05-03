> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Step 4 PCA Real-Sample Strategy Design

**Context**

Step 4 currently excludes QC samples before PCA, but still reuses a QC-centric plotting strategy. That produces a figure whose ellipse semantics are inherited from earlier QC-focused steps and therefore are not well aligned with the actual purpose of Step 4. Step 4 should evaluate the biological structure of real samples after normalization, not QC drift.

The user has confirmed three requirements:

- QC must be completely excluded from Step 4 PCA.
- Visible groups must be determined dynamically from the actual data, because future datasets may not use fixed labels such as `Normal / Control / Exposure`.
- The figure should contain both an `All Samples` ellipse and per-group ellipses.

## Goals

- Step 4 PCA must operate on real samples only.
- Step 4 PCA legend must dynamically reflect the actual non-QC groups present after sample-type normalization.
- Step 4 PCA must show:
  - one overall `All Samples` ellipse
  - one ellipse per non-QC group when that group has enough samples
- Step 4 PCA should keep the same general visual quality as the other steps without inheriting QC-specific semantics.

## Design

### 1. Separate Step 4 plotting semantics from QC-centric plotting

Do not keep forcing Step 4 through `plot_pca_comparison_qc_style(...)`.

Instead, add a new shared helper in `src/metabolomics/utils/plotting.py`, for example:

- `plot_pca_comparison_real_sample_style(...)`

This helper is specifically for PCA views where:

- QC has already been removed
- grouping is based on biological sample types
- the figure should emphasize overall structure and between-group structure

### 2. Step 4 grouping behavior

In `src/metabolomics/processors/normalization.py`:

- Keep `exclude_qc=True`
- Build sample groups from the existing, corrected sample-info mapping
- Normalize group labels through the existing sample-type normalization layer
- Pass only non-QC groups into the new plotting helper

The visible legend should be dynamic. If the data contains `Normal`, `Benign`, and `Exposure`, the legend should resolve to:

- `Normal`
- `Control` (from `Benign`)
- `Exposure`

If future data contains different normalized classes, the figure should adapt automatically.

### 3. Ellipse rules

The new Step 4 PCA helper should always draw:

- `All Samples` dashed ellipse

It should also draw:

- one ellipse per non-QC group if that group has at least 3 samples

If a group has fewer than 3 samples:

- still plot its points
- omit its ellipse

This avoids creating statistically misleading ellipses from undersized groups.

### 4. Figure titles and legend structure

Step 4 titles should explicitly communicate that the view is based on real samples after normalization. Suggested title pattern:

- `2D PCA Comparison: Before vs After Normalization (Real Samples Only)`

Legend structure should be:

- `Sample Type` legend for the real groups
- `Confidence Ellipse` legend for:
  - `95% CI (All Samples)`
  - `95% CI (<group>)` for each eligible group

There should be no `QC` or `QC Outlier` legend entry in Step 4 PCA.

## Testing

- Add unit tests for the new real-sample plotting helper:
  - QC is absent from the visible legend
  - dynamic group types are preserved
  - `All Samples` ellipse is always included
  - per-group ellipses only appear for groups with `n >= 3`
- Add Step 4 regression coverage to confirm sample groups from `SampleInfo` are passed through correctly after QC removal
- Re-run Step 4 on the user-provided workbook and verify:
  - no QC points appear
  - `Normal` appears when present
  - `All Samples` and per-group ellipses are both present
