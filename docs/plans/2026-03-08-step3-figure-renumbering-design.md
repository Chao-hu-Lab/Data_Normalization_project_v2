# Step 3 Figure Renumbering Design

**Context**

The new Step 3 `QC Batch Scaling` workflow currently emits only three figures, but the output
filenames still inherit the numbering pattern from the legacy `batch_effect.py` module:

- `Fig2_PCA_by_batch`
- `Fig4_PCA_by_sample_type`
- `Fig6_Residual_Analysis`

This is misleading because the new Step 3 no longer emits the legacy `Fig1/3/5` outputs.
The user wants the new Step 3 figure numbering to match the actual number of figures generated.

## Goals

- Renumber the new Step 3 figures so they appear as a clean consecutive series.
- Keep the current figure content, titles, and output directory unchanged.
- Avoid touching legacy `batch_effect.py`.

## Design

### 1. Renumber only the new Step 3 outputs

Only change filenames emitted by:

- `src/metabolomics/processors/qc_batch_scaling.py`

Do not change anything in:

- `src/metabolomics/processors/batch_effect.py`

The legacy module can keep its historical numbering because it represents a different diagnostic set.

### 2. Use consecutive numbering for the actual three diagnostics

The new Step 3 output filenames should become:

- `Fig1_PCA_by_batch_<timestamp>.png`
- `Fig2_PCA_by_sample_type_<timestamp>.png`
- `Fig3_Residual_Analysis_<timestamp>.png`

This matches the current Step 3 diagnostic set exactly:

1. batch PCA
2. sample-type PCA
3. residual analysis

### 3. Keep directory and figure semantics unchanged

Do not change:

- plot content
- plot titles
- plot generation order
- output root directory
- session folder naming

The figures should still be written under:

- `output/QC_Batch_Scaling_plots/<session>/`

This keeps the change intentionally narrow and low-risk.

## Compatibility

- Existing old run directories will still contain `Fig2/4/6`; they are historical outputs and do not need migration.
- New Step 3 runs will produce `Fig1/2/3`.
- No workbook output, sheet naming, or downstream processing depends on these figure filenames, so this should not affect Step 4 or Excel output.

## Testing

- Update Step 3 plotting regression tests to expect:
  - `Fig1_PCA_by_batch_*`
  - `Fig2_PCA_by_sample_type_*`
  - `Fig3_Residual_Analysis_*`
- Remove assumptions tied to `Fig6_Residual_Analysis_*`
- Re-run Step 3 on the real workbook and confirm the latest diagnostics directory contains only the new consecutive numbering

## Recommendation

Implement this as a naming-only cleanup in `qc_batch_scaling.py`.

That fixes the user-facing confusion without reopening any of the statistical or plotting behavior.
