> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# ISTD Gate and QC Batch Scaling Design

## Goal

Add a front-end eligibility gate to Step 1 ISTD correction, and replace Step 3 ComBat-based batch correction with a new QC-based batch scaling method that uses per-batch QC medians.

## Scope

- Step 1 adds a pre-check on ISTD quality before running correction.
- Step 2 must continue when Step 1 is skipped.
- Step 3 is reworked into a new `QC Batch Scaling` processor.
- `Batch` parsing must support QC samples assigned to multiple batches with semicolon-separated values such as `A;B` or `A; B`.
- Step 4 must accept the new Step 3 result sheet.

## Requirements

### Step 1 Gate

- Use QC samples to calculate `QC_CV%` for each ISTD.
- A "good" ISTD is one with `QC_CV% < 20`.
- If the number of good ISTDs is less than 5, Step 1 is skipped.
- When skipped:
  - do not create `ISTD_Correction`
  - write only `RawIntensity` and `SampleInfo`
  - return `ProcessingResult(skipped=True, skip_reason='insufficient_good_istd')`

### Step 2 Fallback

- Step 2 keeps its current preferred input sheet order.
- If `ISTD_Correction` does not exist because Step 1 was skipped, Step 2 must fall back to `RawIntensity`.

### Step 3 Method Change

- Replace ComBat with a new QC-based ratio scaling method.
- For each feature and each batch:
  - collect the QC samples assigned to that batch
  - compute the median QC intensity for that feature within that batch
  - scale every sample in that batch by `sample_intensity / batch_qc_median`
- The method is QC-driven and batch-local. It does not fit a global empirical Bayes model and does not depend on exposure/control balance within a batch.

### Multi-Batch QC Samples

- `Batch` values may contain multiple assignments separated by `;`.
- Parsing must normalize whitespace:
  - `A;B`
  - `A; B`
  - ` A ; B `
  - all mean the same batch list: `['A', 'B']`
- QC samples may belong to multiple batches.
- Non-QC samples must belong to exactly one batch. A non-QC sample with `A;B` is invalid and should raise an error.
- Multi-batch QC samples contribute to each listed batch's QC median set.

Example:

- Batch A QC set: `QC_1`, `QC_2`, `QC_3`
- Batch B QC set: `QC_3`, `QC_4`, `QC_5`

Then `QC_3` contributes to both batch A and batch B median calculations.

## Proposed Architecture

### New Processor

Create a new Step 3 processor:

- `src/metabolomics/processors/qc_batch_scaling.py`

This processor replaces the current Step 3 module in the GUI and in normal downstream execution.

### Naming

- GUI step label changes from `Step 3: Batch Correction` to `Step 3: QC Batch Scaling`
- Add new sheet names in constants:
  - `qc_batch_scaling`: `QC_Batch_Scaling_result`
  - `qc_batch_scaling_summary`: `QC_Batch_Scaling_summary`

To preserve compatibility during migration:

- Step 4 should first look for `QC_Batch_Scaling_result`
- then fall back to `Batch_effect_result`
- then `QC LOWESS result`

The legacy `batch_effect.py` stays in the repository for rollback and reference, but it is no longer the active Step 3 path.

## Data Flow

### Step 1

1. Load `RawIntensity` and `SampleInfo`
2. Identify ISTD rows from red-marked `FeatureID`
3. Compute ISTD QC CV%
4. Count good ISTDs (`QC_CV% < 20`)
5. If fewer than 5:
   - skip correction
   - save a slim workbook with only `RawIntensity` and `SampleInfo`
6. Otherwise continue with current ISTD correction flow

### Step 3

1. Load the preferred upstream data sheet:
   - `QC LOWESS result`
   - otherwise `ISTD_Correction`
   - otherwise `RawIntensity`
2. Parse `SampleInfo.Batch` into normalized batch lists
3. Build:
   - `batch -> qc_samples`
   - `sample -> single_batch` for non-QC samples
4. For each feature:
   - compute per-batch QC median
   - divide all samples in each batch by that median
5. Save:
   - upstream data sheet
   - `SampleInfo`
   - `QC_Batch_Scaling_result`
   - `QC_Batch_Scaling_summary`

## Validation Rules

### Step 1

- If no QC samples exist, keep the current failure behavior.
- If ISTDs exist but fewer than 5 meet the quality threshold, skip instead of failing.
- The summary must report:
  - total ISTDs
  - good ISTDs
  - skip decision

### Step 3

- Every non-QC sample must map to exactly one batch after parsing.
- Every batch must have enough QC values to compute medians for scaling.
- The minimum QC count per batch should be 2. Fewer than 2 is treated as invalid input for scaling.
- A feature/batch median of zero or NaN must not silently create invalid scaled values; the processor should either:
  - fail fast for structurally invalid input, or
  - keep a clear fallback rule and report it in summary.

Recommended first implementation:

- fail if a batch has fewer than 2 QC samples
- for per-feature zero/NaN batch QC median, leave affected values unchanged and record the event in summary

This keeps the processor usable on imperfect data without hiding structural metadata problems.

## Reporting Changes

### Remove ComBat-Centric Reporting

The new Step 3 should not keep ComBat-oriented metrics that no longer match the algorithm:

- PERMANOVA
- PERMDISP
- paired permutation test
- Cohen's d batch separation summaries
- confounding-based ComBat skip logic

### Keep or Replace with Method-Accurate Reporting

Keep reporting that still makes sense:

- before/after QC CV%
- per-batch QC counts
- PCA plots before/after scaling
- Hotelling T² QC outlier overview if still useful

Add method-specific reporting:

- parsed batch membership summary
- multi-batch QC membership summary
- count of per-feature batch medians that were unavailable or invalid
- scaling factor distribution summary

## Testing Strategy

### Unit and Regression Tests

- Step 1 gate test:
  - if good ISTDs `< 5`, result is skipped and no `ISTD_Correction` sheet is written
- Step 2 fallback test:
  - Step 2 successfully runs from a workbook that contains `RawIntensity` and `SampleInfo` only
- Batch parser test:
  - `A;B`, `A; B`, and ` A ; B ` parse identically
- Multi-batch QC assignment test:
  - `QC_3` is included in both batch A and batch B QC pools
- Non-QC multi-batch validation test:
  - a real sample assigned `A;B` raises an error
- Step 3 output workbook test:
  - only the selected upstream data sheet, `SampleInfo`, result, and summary are written
- Step 4 compatibility test:
  - Step 4 accepts `QC_Batch_Scaling_result`

### Manual Verification

Use the provided workbook:

- `C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\ISTD測試\STEP4_program2_DNA_alignment_test_ISTD.xlsx`

Important named cases:

- `Breast Cancer Tissue_pooled_QC_3`
- `Breast Cancer Tissue_pooled_QC_5`

The verification should explicitly confirm that these QC samples are counted in both relevant batch QC median sets.

## Risks

- Replacing Step 3 changes both algorithmic behavior and reporting, so stale ComBat assumptions in GUI text, tests, or downstream selection logic can cause subtle regressions.
- Skip behavior in Step 1 changes pipeline control flow and must be reflected in Step 2 input selection.
- Multi-batch QC support adds a new parsing rule that can fail silently if whitespace normalization is missed.

## Recommendation

Implement the change as a new Step 3 processor rather than patching the existing ComBat module. This keeps the new method semantically clean, reduces hidden legacy assumptions, and makes testing the new behavior easier.
