> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# Step 2 and Step 3 PCA Legend Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix Step 2 batch PCA legend semantics and add Step 3 QC Batch Scaling PCA figures that match the QC plotting style and preserve `Normal` in the sample-type legend.

**Architecture:** Extend the shared PCA plotting utility to understand multi-batch memberships, then update Step 2 to pass semicolon-aware memberships and add dedicated before/after PCA generation to the new Step 3 QC batch scaling processor. Keep the changes focused on plotting inputs and plotting output paths instead of changing normalization math.

**Tech Stack:** Python, pandas, NumPy, matplotlib, scikit-learn, pytest

---

### Task 1: Lock the plotting semantics with failing tests

**Files:**
- Create: `tests/unit/test_plotting.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Write the failing tests**

- Add a unit test for shared plotting helpers that asserts semicolon-delimited batch memberships only expose `A/B/C` as visible batch keys.
- Add a unit test that asserts `Normal` remains a distinct sample type label when present.
- Add a Step 3 integration assertion that `main()` reports a plots directory and creates PNG output.

**Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_plotting.py tests/unit/test_qc_batch_scaling.py -q`

Expected:
FAIL because the plotting helper does not yet expose membership-aware grouping and Step 3 does not yet generate PCA plots.

**Step 3: Write minimal implementation**

- Add shared plotting support for membership-aware batch grouping.
- Add Step 3 PCA generation and plots directory reporting.

**Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_plotting.py tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS

### Task 2: Fix Step 2 PCA batch memberships

**Files:**
- Modify: `src/metabolomics/processors/qc_lowess.py`
- Modify: `src/metabolomics/utils/plotting.py`
- Modify: `tests/unit/test_qc_lowess.py`

**Step 1: Write the failing test**

- Add a regression test that constructs batch memberships with `A;B` and verifies the PCA plotting layer receives only single batch legend keys.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_qc_lowess.py -q`

Expected:
FAIL because PCA metadata is still driven by raw batch strings.

**Step 3: Write minimal implementation**

- Parse batch memberships for PCA in `qc_lowess.py`.
- Pass membership-aware batch metadata into the shared plotting helper.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_qc_lowess.py -q`

Expected:
PASS

### Task 3: Add Step 3 QC Batch Scaling PCA outputs

**Files:**
- Modify: `src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `src/metabolomics/utils/plotting.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Write the failing test**

- Add assertions that Step 3 creates a `plots_dir`, generates at least two PCA PNG files, and stores them under `QC_Batch_Scaling_plots`.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
FAIL because Step 3 currently returns no plot artifacts.

**Step 3: Write minimal implementation**

- Build before/after PCA matrices from the selected upstream sheet and scaled result sheet.
- Generate one PCA figure grouped by batch and one grouped by sample type.
- Preserve `Normal` as a distinct plotting label.
- Return `plots_dir` in `ProcessingResult`.

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS

### Task 4: Verify the real workbook behavior

**Files:**
- No source edits required if prior tasks pass

**Step 1: Run focused regression suite**

Run:
`pytest tests/unit/test_plotting.py tests/unit/test_qc_lowess.py tests/unit/test_qc_batch_scaling.py -q`

Expected:
PASS

**Step 2: Run Step 2 and Step 3 on the provided workbook**

Run the processors on:
`C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\ISTD測試\STEP4_program2_DNA_alignment_test_ISTD.xlsx`

Expected:
- Step 2 batch PCA legend exposes only `A`, `B`, `C`
- Step 3 creates `output/QC_Batch_Scaling_plots/...`
- Step 3 sample-type PCA includes `Normal`

**Step 3: Inspect generated artifacts**

- Confirm PNG files exist
- Confirm paths come from `QC_Batch_Scaling_plots`
- Confirm no claim depends on stale `Batch_Effect_plots`
