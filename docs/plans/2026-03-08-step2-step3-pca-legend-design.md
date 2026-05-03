> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Step 2 and Step 3 PCA Legend Alignment Design

**Context**

The current Step 2 PCA batch plot still treats semicolon-delimited batch labels such as `A;B` as a distinct visible batch. This creates incorrect legend entries and ellipse grouping. At the same time, the new Step 3 `qc_batch_scaling.py` processor does not generate its own PCA figures, which leaves only legacy `batch_effect.py` PCA artifacts available for comparison and causes confusion about the current workflow.

The test workbook also contains `Sample_Type` values `Exposure`, `Normal`, `Benign`, and `QC`. The intended plotting behavior is to preserve `Normal` as its own visible sample type while still normalizing `Benign` into `Control`.

## Goals

- Step 2 batch PCA legends must only show single batch names such as `A`, `B`, `C`.
- Multi-batch QC samples such as `A;B` must contribute to both batch ellipses without appearing as their own legend entry.
- Step 3 must generate fresh PCA figures under a dedicated `QC_Batch_Scaling_plots` directory.
- Step 3 sample-type PCA must use the same shared plotting style as QC LOWESS and must show `Normal` whenever it exists in `SampleInfo`.
- Legacy `Batch_Effect_plots` should no longer be the only visible Step 3 PCA output.

## Design

### 1. Shared plotting semantics

Extend the shared PCA plotting utility in `src/metabolomics/utils/plotting.py` so batch grouping can work from per-sample batch memberships instead of only one flat label string.

- Keep `batch_labels` for backwards compatibility.
- Add a new optional `batch_memberships` parameter aligned with samples.
- When `grouping='batch'`, visible legend keys are built from the flattened single-batch memberships, not from the raw original label string.
- Ellipse membership is determined by inclusion in the membership list, so a QC sample tagged `A;B` contributes to both `A` and `B`.

### 2. Step 2 PCA

In `src/metabolomics/processors/qc_lowess.py`:

- Parse batch labels for PCA using the same semicolon-aware logic already used in LOWESS correction.
- Pass normalized batch memberships into the shared plotting utility.
- Preserve the existing sample type classification for plotting, including `Normal` as a distinct sample type.

### 3. Step 3 PCA

In `src/metabolomics/processors/qc_batch_scaling.py`:

- Add PCA figure generation for before/after QC batch scaling.
- Output figures into `output/QC_Batch_Scaling_plots/QC_Batch_Scaling_<timestamp>/`.
- Generate two figures:
  - grouped by batch
  - grouped by sample type
- Reuse the shared QC LOWESS-style plotting utility so the layout, legend structure, and ellipse styling remain consistent with the rest of the pipeline.
- Titles must refer to `QC Batch Scaling`, not `Batch Effect` or `Correction` in the old ComBat sense.

### 4. Sample type display

Plotting must display actual normalized sample types present in the data:

- `QC` stays `QC`
- `Benign` normalizes to `Control`
- `Normal` stays `Normal`
- `Exposure` stays `Exposure`

This means a sample-type legend can legitimately contain both `Control` and `Normal`.

## Testing

- Add unit coverage for shared batch-membership plotting preparation:
  - `A;B` does not create a visible `A;B` batch legend entry
  - the same sample participates in both `A` and `B` ellipse memberships
- Add Step 2 regression coverage to confirm PCA metadata passes multi-batch membership through correctly.
- Add Step 3 integration coverage to confirm:
  - a plots directory is reported
  - PCA PNG files are generated
  - the new plots live under `QC_Batch_Scaling_plots`
- Re-run Step 2 and Step 3 using the provided workbook to confirm:
  - Step 2 batch figure only shows `A/B/C`
  - Step 3 figures are newly generated and no longer rely on legacy `Batch_Effect_plots`
  - Step 3 sample-type legend includes `Normal`
