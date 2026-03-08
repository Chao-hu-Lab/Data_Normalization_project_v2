# Shared Sample Column Detection Design

**Context**

The project already has a shared sample-column detection helper in
`src/metabolomics/utils/sample_classification.py`, but not every processor uses it.
Step 4 normalization still relies on a local `get_all_sample_columns(...)` function in
`src/metabolomics/processors/normalization.py`, and that local rule set is weaker than the
shared one. As a result, pseudo-sample statistics such as:

- `exposure_ratio`
- `normal_ratio`
- `control_ratio`
- `QC_ratio`

can be misclassified as real samples and flow into PCA, where they appear as `Unknown`.

The user wants these ratio/statistical columns removed as non-sample fields, and wants the
rule applied project-wide rather than patching only Step 4.

## Goals

- Establish a single project-wide source of truth for sample-column detection.
- Ensure ratio/statistical columns are never treated as real samples.
- Reuse the existing shared constants:
  - `NON_SAMPLE_COLUMNS`
  - `STAT_COLUMN_KEYWORDS`
- Remove Step 4's local duplicate filtering logic.
- Bring Step 1 onto the same base sample-column selection semantics where practical.

## Root Cause

The non-sample rules are already centrally defined in:

- `src/metabolomics/utils/constants.py`

and are already consumed by:

- `src/metabolomics/utils/sample_classification.py`

However, `src/metabolomics/processors/normalization.py` bypasses that shared helper and uses
its own local keyword list in `get_all_sample_columns(...)`. That local list does not exclude
the `*_ratio` fields, so those columns enter Step 4 as if they were true samples.

This is not a plotting bug. It is a sample-column identification bug.

## Design

### 1. One shared source of truth

Use `identify_sample_columns(df, sample_info_df)` in:

- `src/metabolomics/utils/sample_classification.py`

as the project-wide source of truth for deciding which columns are real samples.

That helper already combines:

- normalized `SampleInfo` name matching
- `NON_SAMPLE_COLUMNS`
- `STAT_COLUMN_KEYWORDS`

This is the correct abstraction layer for the behavior the user wants.

### 2. Step 4 must delegate instead of maintaining local rules

`src/metabolomics/processors/normalization.py` should no longer maintain its own
`exclude_keywords` list for sample detection.

Instead:

- keep `get_all_sample_columns(...)` only as a thin wrapper if needed for compatibility
- make it delegate to `identify_sample_columns(...)`
- return only the shared-helper result

This removes duplicated logic and fixes the immediate `*_ratio` misclassification.

### 3. Step 1 should align with the same base sample-detection semantics

`src/metabolomics/processors/istd.py` still contains local sample-column filtering logic.
That logic can keep its step-specific exclusions such as:

- `is_ISTD`
- `Sample_Type`

but the base list of candidate sample columns should come from the same shared helper so that
ratio/statistical pseudo-samples are excluded everywhere consistently.

This change should be minimal:

- reuse shared sample detection first
- then apply Step 1-specific constraints only if still necessary

### 4. Scope boundaries

This change should not:

- alter any normalization algorithm
- alter any ISTD correction math
- alter Step 2 or Step 3 computational behavior
- change sample-type normalization rules

It should only change which columns are eligible to be treated as real samples.

## Expected Behavior After Change

- Step 4 PQN PCA should no longer show `Unknown` caused by `*_ratio` pseudo-samples.
- Step 4 real-sample PCA should retain:
  - `Normal`
  - `Control`
  - `Exposure`
  when those groups are actually present.
- Step 1 should no longer be able to accidentally absorb pseudo-sample ratio/statistics columns.

## Testing

- Add shared helper regression coverage proving that:
  - real sample columns are kept
  - `exposure_ratio`
  - `normal_ratio`
  - `control_ratio`
  - `QC_ratio`
  - `Original_CV%`
  - `Normalized_CV%`
    are excluded
- Add Step 4 regression coverage verifying:
  - no `Unknown` legend item from pseudo-sample ratio columns
  - `Normal / Control / Exposure` still appear when present
- Add Step 1 regression coverage verifying pseudo-sample statistic columns are not treated as real sample inputs

## Recommendation

Implement this as a sample-detection unification task, not as a Step 4-only fix.

That solves the immediate PQN PCA problem while also preventing the same class of bug from
reappearing in Step 1 or future processors that consume workbook sample columns.
