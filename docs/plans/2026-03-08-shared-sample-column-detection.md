> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Shared Sample Column Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify sample-column detection across the project so ratio/statistical fields such as `exposure_ratio`, `normal_ratio`, `control_ratio`, and `QC_ratio` are never treated as real samples.

**Architecture:** Use `identify_sample_columns(...)` in `src/metabolomics/utils/sample_classification.py` as the single source of truth for sample detection. Update Step 4 normalization and the relevant Step 1 ISTD path to delegate to that shared helper instead of maintaining local filtering rules.

**Tech Stack:** Python, pandas, pytest

---

### Task 1: Lock shared non-sample filtering with failing tests

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_sample_matching.py`

**Step 1: Write the failing test**

Add a regression test that builds a DataFrame with:

- true sample columns from `SampleInfo`
- pseudo-sample/stat columns:
  - `exposure_ratio`
  - `normal_ratio`
  - `control_ratio`
  - `QC_ratio`
  - `Original_CV%`
  - `Normalized_CV%`

Assert that `identify_sample_columns(...)` returns only the real sample columns.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_sample_matching.py -q`

Expected:
FAIL if any pseudo-sample/stat columns are still included or if the shared helper lacks coverage for the exact problematic inputs.

**Step 3: Write minimal implementation**

- Update constants or helper logic only if the failing test proves a shared-rule gap.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_sample_matching.py -q`

Expected:
PASS

### Task 2: Replace Step 4 local sample detection with the shared helper

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/normalization.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_normalization.py`

**Step 1: Write the failing test**

Add a Step 4 regression test that exercises `get_all_sample_columns(...)` or the nearest Step 4 entry point with:

- normal real sample columns
- ratio/stat columns

Assert that the returned sample-column set excludes the pseudo-sample ratio/stat columns.

Also add a PCA-facing regression that confirms the Step 4 legend set does not contain `Unknown`
when those ratio columns are present but should have been filtered out.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_normalization.py -k "sample_columns or ratio or unknown" -q`

Expected:
FAIL because Step 4 still uses its own local filtering logic.

**Step 3: Write minimal implementation**

- Import `identify_sample_columns`
- Change `get_all_sample_columns(...)` to delegate to the shared helper
- Preserve function signature if other Step 4 code still calls it

Implementation shape:

```python
def get_all_sample_columns(df, sample_info_df):
    sample_columns, _ = identify_sample_columns(df, sample_info_df)
    return [col for col in sample_columns if col in df.columns]
```

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_normalization.py -k "sample_columns or ratio or unknown" -q`

Expected:
PASS

### Task 3: Align Step 1 ISTD sample detection with the shared helper

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/istd.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_istd.py`

**Step 1: Write the failing test**

Add a regression test for the Step 1 path that includes pseudo-sample ratio/stat columns in the
input workbook structure and asserts they are not treated as real sample columns.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_istd.py -k "ratio or pseudo or sample_columns" -q`

Expected:
FAIL because Step 1 still relies on local column filtering.

**Step 3: Write minimal implementation**

- Reuse `identify_sample_columns(...)` to build the base sample-column set
- Apply any Step 1-specific exclusions only after shared sample detection has run

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_istd.py -k "ratio or pseudo or sample_columns" -q`

Expected:
PASS

### Task 4: Run the focused regression suite

**Files:**
- No new source edits if previous tasks pass

**Step 1: Run focused tests**

Run:
`pytest tests/unit/test_sample_matching.py tests/unit/test_normalization.py tests/unit/test_istd.py -q`

Expected:
PASS

**Step 2: Fix only shared sample-detection regressions if any appear**

- Do not change normalization or ISTD algorithms
- Only adjust sample-column detection behavior

**Step 3: Re-run the suite**

Run:
`pytest tests/unit/test_sample_matching.py tests/unit/test_normalization.py tests/unit/test_istd.py -q`

Expected:
PASS

### Task 5: Verify on the real DNP workbook

**Files:**
- No source edits required if earlier tasks pass

**Step 1: Re-run the relevant real workflow**

Use the current DNP Step 3 output as Step 4 input, or re-run the full path from the user workbook if needed.

Expected:
- Step 4 completes
- the latest PQN PCA figure does not include ratio-derived `Unknown`
- the legend still contains `Normal`, `Control`, and `Exposure` when present

**Step 2: Inspect the generated PCA figure**

- Confirm no pseudo-sample legend entry appears
- Confirm the ratio/stat columns are absent from the sample-count logic

**Step 3: Report the final verified output path**

- Provide the latest figure path and note the verified legend groups
