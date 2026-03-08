# Step 3 Residual Analysis Design

**Context**

Step 3 has already been rewritten from legacy `ComBat` to `QC Batch Scaling`, and its new PCA plots now follow the updated multi-batch QC membership rules. The old `batch_effect.py` module still contains one diagnostic figure that remains useful after the algorithm change: the residual analysis plot that shows per-batch feature means relative to the global mean before and after correction.

The user wants that residual analysis to be retained in the new Step 3 implementation, with the same overlapping batch behavior already established elsewhere in the pipeline:

- `A;B` QC samples contribute to both batch `A` and batch `B`
- visible batch labels in the figure should still be only `A / B / C`
- the figure should live under the new `QC_Batch_Scaling_plots` output tree

## Goals

- Add a residual analysis diagnostic to the new `QC Batch Scaling` Step 3 flow.
- Preserve the residual plot's interpretation from the legacy workflow so historical reading habits still apply.
- Respect overlapping QC batch memberships such as `A;B` and `B;C`.
- Keep all titles and output names aligned with `QC Batch Scaling`, not `Batch Effect` or `ComBat`.

## Design

### 1. Reuse the legacy residual math, not the legacy module

Do not call back into `batch_effect.py`.

Instead, port the residual-analysis math into `src/metabolomics/processors/qc_batch_scaling.py` so the new Step 3 remains self-contained. The residual definition should stay compatible with the old plot:

- start from the Step 3 input matrix for `before`
- start from `QC_Batch_Scaling_result` for `after`
- transform both matrices with `log2(x + 1)`
- standardize features with `StandardScaler`
- for each batch and each feature, compute:
  - `batch mean - global mean`

This preserves the old figure's interpretation: systematic batch bias appears as structured deviation away from zero, and successful correction should pull those residuals closer to a random scatter around zero.

### 2. Apply overlapping batch membership consistently

Residual calculation should follow the same batch-membership semantics already used in Step 2 and Step 3 PCA:

- each sample column maps to one or more batch memberships
- QC rows such as `A;B` and `B;C` contribute to every listed batch
- those overlapping QC samples should not create standalone visual batch labels

The visible batches in the residual plot should therefore remain single-batch categories only:

- `Batch A`
- `Batch B`
- `Batch C`

### 3. Add a dedicated Step 3 residual plotting helper

Add small, focused helpers inside `src/metabolomics/processors/qc_batch_scaling.py`:

- `prepare_residual_matrix(df, sample_columns)`
- `calculate_batch_residuals(scaled_matrix, sample_columns, batch_memberships)`
- `plot_batch_residual_analysis(...)`

This keeps the residual logic close to the Step 3 data pipeline and avoids overloading the shared plotting module with one-off batch-scaling diagnostics.

The figure should remain a two-panel comparison:

- left: before correction
- right: after correction

Suggested title:

- `QC Batch Scaling Residual Analysis`

Suggested output filename:

- `Fig6_Residual_Analysis_<timestamp>.png`

### 4. Integrate residual output into the Step 3 diagnostics session

`generate_pca_plots(...)` in `qc_batch_scaling.py` should become the unified Step 3 diagnostics entry point:

- keep the existing batch PCA
- keep the existing sample-type PCA
- append the new residual analysis plot

All three figures should be written into the same session directory under:

- `output/QC_Batch_Scaling_plots/<session>/`

This keeps Step 3 diagnostics grouped together and avoids reviving the legacy `Batch_Effect_plots` output branch.

## Error Handling

- If a batch has no valid members after metadata alignment, skip that batch rather than crashing.
- If too few usable features remain after log transform and scaling, skip residual plotting rather than failing the whole Step 3 run.
- If overlapping batch membership exists, include the sample in every relevant batch residual calculation, but only expose the single batch names in the legend.

## Testing

- Add unit coverage that proves `A;B` contributes to both `A` and `B` residual calculations.
- Add residual plotting coverage that confirms only `Batch A / Batch B / Batch C` appear in the figure labels.
- Add a synthetic regression test where batch-biased data becomes less biased after scaling and the residual magnitude decreases.
- Re-run Step 3 on the user-provided workbook and verify that:
  - `Fig6_Residual_Analysis_<timestamp>.png` is generated
  - the plot lives under `QC_Batch_Scaling_plots`
  - the visible batch labels remain single-batch labels only
