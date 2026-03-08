# Step 3 Residual Analysis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a legacy-compatible residual analysis diagnostic to the new Step 3 `QC Batch Scaling` workflow, while preserving overlapping QC batch memberships such as `A;B`.

**Architecture:** Keep the residual-analysis logic inside `src/metabolomics/processors/qc_batch_scaling.py` so the new Step 3 stays self-contained. Reuse the old residual math (`log2(x + 1)` + `StandardScaler` + `batch mean - global mean`) but feed it with the new batch-membership model and emit the output alongside the existing Step 3 PCA figures.

**Tech Stack:** Python, NumPy, pandas, matplotlib, scikit-learn, pytest

---

### Task 1: Lock residual membership behavior with failing tests

**Files:**
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Write the failing test**

- Add a focused test for the residual helper using sample memberships like:
  - `QC_1 -> A`
  - `QC_2 -> A;B`
  - `QC_3 -> B`
- Assert that the computed residual inputs for batch `A` include `QC_1` and `QC_2`.
- Assert that the computed residual inputs for batch `B` include `QC_2` and `QC_3`.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
FAIL because the residual helper does not exist yet.

**Step 3: Write minimal implementation**

- Add the batch-membership-aware residual calculation helpers in `src/metabolomics/processors/qc_batch_scaling.py`.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS for the new membership test.

### Task 2: Add the residual preparation and plotting helpers

**Files:**
- Modify: `src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Write the failing tests**

- Add a test for `prepare_residual_matrix(...)` that confirms:
  - negative values are clipped the same way as existing PCA prep
  - output is finite after `log2(x + 1)` and `StandardScaler`
- Add a test for the residual plotting path that confirms:
  - figure creation succeeds
  - visible batch labels are only single-batch labels such as `Batch A`, `Batch B`, `Batch C`

**Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
FAIL because the preparation and plotting helpers are still missing.

**Step 3: Write minimal implementation**

- Add:
  - `prepare_residual_matrix(df, sample_columns)`
  - `calculate_batch_residuals(scaled_matrix, sample_columns, batch_memberships)`
  - `plot_batch_residual_analysis(...)`
- Keep the title and annotations aligned with:
  - `QC Batch Scaling Residual Analysis`
- Ensure overlapping memberships are used for the residual math but not emitted as standalone legend entries.

**Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS

### Task 3: Wire residual output into the Step 3 diagnostics session

**Files:**
- Modify: `src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Write the failing test**

- Add a regression test around `generate_pca_plots(...)` that expects:
  - the batch PCA path exists
  - the sample-type PCA path exists
  - `Fig6_Residual_Analysis_<timestamp>.png` is also emitted in the same diagnostics directory

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
FAIL because the residual plot is not yet included in the diagnostics output.

**Step 3: Write minimal implementation**

- Extend `generate_pca_plots(...)` to generate the residual figure after the PCA figures.
- Reuse `sample_types` and `batch_memberships` already built in the function.
- Keep all outputs under:
  - `output/QC_Batch_Scaling_plots/<session>/`

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS

### Task 4: Verify residual behavior improves on synthetic batch-biased data

**Files:**
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Write the failing test**

- Build a small synthetic matrix with a clear batch offset before scaling.
- Run the existing Step 3 scaling logic.
- Compute residuals before and after correction.
- Assert that a summary metric such as mean absolute residual decreases after scaling.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
FAIL until the residual helper is fully connected to the scaled output path.

**Step 3: Write minimal implementation**

- Adjust residual helper behavior if needed so the synthetic residual reduction test passes without weakening the assertions.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS

### Task 5: Verify on the real workbook

**Files:**
- No source edits required if earlier tasks pass

**Step 1: Run the focused regression suite**

Run:
`pytest tests/unit/test_qc_batch_scaling.py tests/unit/test_plotting.py tests/unit/test_qc_lowess.py -q`

Expected:
PASS

**Step 2: Re-run Step 3 on the user-provided workbook**

Use:
`C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\ISTD測試\STEP4_program2_DNA_alignment_test_ISTD.xlsx`

Expected:
- Step 3 completes successfully
- `QC_Batch_Scaling_plots/<session>/Fig6_Residual_Analysis_<timestamp>.png` is generated
- the plot uses only `Batch A / Batch B / Batch C`

**Step 3: Inspect the generated figure**

- Confirm the residual figure exists in the latest `QC_Batch_Scaling_plots` session directory
- Confirm overlapping QC memberships affected the math without producing standalone legend entries like `A;B`
- Confirm the figure title uses `QC Batch Scaling`, not `Batch Effect`
