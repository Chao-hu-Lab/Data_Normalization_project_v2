# Step 4 PCA Real-Sample Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current Step 4 QC-centric PCA rendering with a real-sample-only PCA strategy that excludes QC, uses dynamic biological group labels, and draws both overall and per-group ellipses.

**Architecture:** Add a dedicated real-sample PCA plotting helper in the shared plotting module, then update Step 4 to route non-QC PCA output through that helper instead of the QC-centric shared plot. Keep the PCA data pipeline and sample-name matching intact; only change the plotting semantics and the tests that define them.

**Tech Stack:** Python, NumPy, matplotlib, scikit-learn, pytest

---

### Task 1: Lock the new Step 4 PCA semantics with failing tests

**Files:**
- Modify: `tests/unit/test_plotting.py`
- Modify: `tests/unit/test_normalization.py`

**Step 1: Write the failing tests**

- Add a plotting test that asserts a real-sample PCA helper includes:
  - dynamic non-QC sample types
  - `All Samples` ellipse
  - per-group ellipses only for groups with at least 3 samples
- Add a normalization regression test that confirms Step 4 PCA excludes QC and preserves dynamic non-QC groups.

**Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_plotting.py tests/unit/test_normalization.py -q`

Expected:
FAIL because the real-sample PCA helper does not exist yet and Step 4 still uses the QC-centric plotting helper.

**Step 3: Write minimal implementation**

- Add the real-sample PCA plotting helper
- Update Step 4 PCA to use it

**Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_plotting.py tests/unit/test_normalization.py -q`

Expected:
PASS

### Task 2: Implement the shared real-sample PCA plot helper

**Files:**
- Modify: `src/metabolomics/utils/plotting.py`
- Test: `tests/unit/test_plotting.py`

**Step 1: Write the failing test**

- Add focused assertions for legend content and ellipse rules.

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_plotting.py -q`

Expected:
FAIL because the helper is missing.

**Step 3: Write minimal implementation**

- Add `plot_pca_comparison_real_sample_style(...)`
- Support:
  - dynamic sample-type legend
  - `All Samples` ellipse
  - per-group ellipses only for groups with `n >= 3`

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_plotting.py -q`

Expected:
PASS

### Task 3: Switch Step 4 PCA to the new helper

**Files:**
- Modify: `src/metabolomics/processors/normalization.py`
- Test: `tests/unit/test_normalization.py`

**Step 1: Write the failing test**

- Add a regression test for Step 4 PCA metadata:
  - QC excluded
  - dynamic non-QC group set preserved

**Step 2: Run test to verify it fails**

Run:
`pytest tests/unit/test_normalization.py -q`

Expected:
FAIL because Step 4 still calls the QC-centric helper.

**Step 3: Write minimal implementation**

- Replace the Step 4 PCA plotting call with the new real-sample helper
- Keep current PCA computation and sample matching logic intact

**Step 4: Run test to verify it passes**

Run:
`pytest tests/unit/test_normalization.py -q`

Expected:
PASS

### Task 4: Verify on the real workbook

**Files:**
- No source edits required if earlier tasks pass

**Step 1: Run focused regression suite**

Run:
`pytest tests/unit/test_plotting.py tests/unit/test_sample_matching.py tests/unit/test_normalization.py -q`

Expected:
PASS

**Step 2: Re-run Step 4 on the user-provided workbook**

Use:
`C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\ISTD測試\STEP4_program2_DNA_alignment_test_ISTD.xlsx`

Expected:
- no QC points in the PCA
- dynamic non-QC groups visible
- `All Samples` ellipse present
- per-group ellipses present for sufficiently large groups

**Step 3: Inspect the generated figure**

- Confirm the output file exists in `Normalization_Figures`
- Confirm the legend matches the actual non-QC groups
- Confirm the ellipse strategy matches the design
