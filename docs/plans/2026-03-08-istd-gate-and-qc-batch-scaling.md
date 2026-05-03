> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# ISTD Gate and QC Batch Scaling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Step 1 ISTD eligibility gate, let Step 2 fall back to `RawIntensity` when ISTD is skipped, and replace Step 3 ComBat with a new QC median batch scaling processor that supports multi-batch QC samples.

**Architecture:** Keep Step 1 and Step 2 changes minimal inside existing processors, but implement Step 3 as a new `qc_batch_scaling.py` processor. Reuse current workbook-slimming behavior and Step 4 fallback logic, while introducing new sheet names and a new batch parser that supports semicolon-separated QC batch membership.

**Tech Stack:** Python, pandas, numpy, openpyxl, pytest

---

### Task 1: Lock the new Step 1 and Step 2 control flow with tests

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_istd.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_qc_lowess.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/conftest.py`

**Step 1: Write the failing tests**

Add a Step 1 regression test that builds a workbook with:

- at least one marked ISTD
- fewer than 5 ISTDs meeting `QC_CV% < 20`
- valid `RawIntensity`
- valid `SampleInfo`

Expected assertions:

- `result.skipped is True`
- `result.skip_reason == 'insufficient_good_istd'`
- output workbook sheets are exactly:
  - `RawIntensity`
  - `SampleInfo`

Add a Step 2 regression test that uses the Step 1 skipped workbook as input and verifies:

- Step 2 runs successfully
- Step 2 reads from `RawIntensity`
- output workbook contains:
  - `RawIntensity`
  - `SampleInfo`
  - `QC LOWESS result`
  - `QC_LOWESS_Advanced Statistics`

**Step 2: Run tests to confirm failure**

Run:

```bash
pytest tests/unit/test_istd.py -k "skip or good_istd" -q
pytest tests/unit/test_qc_lowess.py -k "rawintensity or fallback or skip" -q
```

Expected: failures showing Step 1 does not yet skip and Step 2 does not yet fall back.

**Step 3: Commit the failing-test checkpoint**

```bash
git add tests/unit/test_istd.py tests/unit/test_qc_lowess.py tests/conftest.py
git commit -m "test: cover ISTD skip gate and Step 2 fallback"
```

### Task 2: Implement the Step 1 ISTD quality gate

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/istd.py`
- Test: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_istd.py`

**Step 1: Add the minimum-good-ISTD decision**

Inside the Step 1 main flow:

- identify QC sample columns using existing logic
- compute each ISTD's QC CV%
- count good ISTDs with `cv < CV_QUALITY_THRESHOLDS['excellent']`
- if the count is `< 5`, short-circuit the processor

Implementation sketch:

```python
good_istd_ids = [
    feature_id
    for feature_id, cv in istd_cv.items()
    if pd.notna(cv) and cv < CV_QUALITY_THRESHOLDS['excellent']
]

if len(good_istd_ids) < 5:
    save_skipped_istd_workbook(raw_df, sample_info_df, output_file)
    return ProcessingResult(
        output_path=output_file,
        skipped=True,
        skip_reason="insufficient_good_istd",
        metrics={
            "total_istd": len(istd_cv),
            "good_istd": len(good_istd_ids),
        },
    )
```

Add a small helper to save the skipped workbook in the same slim format used elsewhere.

**Step 2: Run the focused test**

Run:

```bash
pytest tests/unit/test_istd.py -k "skip or good_istd" -q
```

Expected: pass.

**Step 3: Commit**

```bash
git add src/metabolomics/processors/istd.py tests/unit/test_istd.py
git commit -m "feat: skip ISTD correction when too few good ISTDs"
```

### Task 3: Implement Step 2 fallback to `RawIntensity`

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/qc_lowess.py`
- Test: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_qc_lowess.py`

**Step 1: Update input sheet selection**

Adjust Step 2 loading so it prefers:

1. `ISTD_Correction`
2. `RawIntensity`

and still requires `SampleInfo`.

If `ISTD_Correction` is missing because Step 1 was skipped, Step 2 must proceed from `RawIntensity` without special user action.

**Step 2: Run the focused test**

Run:

```bash
pytest tests/unit/test_qc_lowess.py -k "rawintensity or fallback or skip" -q
```

Expected: pass.

**Step 3: Commit**

```bash
git add src/metabolomics/processors/qc_lowess.py tests/unit/test_qc_lowess.py
git commit -m "feat: allow QC LOWESS to fall back to RawIntensity"
```

### Task 4: Lock batch parsing and multi-batch QC semantics with tests

**Files:**
- Create: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_qc_batch_scaling.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/conftest.py`

**Step 1: Write failing tests for the new Step 3 semantics**

Add tests for:

- parsing:

```python
assert parse_batch_labels("A;B") == ["A", "B"]
assert parse_batch_labels("A; B") == ["A", "B"]
assert parse_batch_labels(" A ; B ") == ["A", "B"]
```

- QC assignment:

```python
batch_to_qc = build_batch_qc_map(sample_info_df)
assert "Breast Cancer Tissue_pooled_QC_3" in batch_to_qc["A"]
assert "Breast Cancer Tissue_pooled_QC_3" in batch_to_qc["B"]
```

- invalid real sample:

```python
with pytest.raises(ValueError, match="single batch"):
    validate_non_qc_batch_assignments(sample_info_df)
```

- batch scaling math:

```python
scaled = scale_feature_by_batch_qc_median(feature_values, batch_to_samples, batch_to_qc)
assert scaled["sample_A"] == pytest.approx(raw_a / median_a)
assert scaled["sample_B"] == pytest.approx(raw_b / median_b)
```

**Step 2: Run the new test file and confirm failure**

Run:

```bash
pytest tests/unit/test_qc_batch_scaling.py -q
```

Expected: fail because the module does not yet exist.

**Step 3: Commit the test scaffold**

```bash
git add tests/unit/test_qc_batch_scaling.py tests/conftest.py
git commit -m "test: cover QC batch scaling batch parsing semantics"
```

### Task 5: Implement the new `qc_batch_scaling.py` processor

**Files:**
- Create: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/utils/constants.py`
- Test: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_qc_batch_scaling.py`

**Step 1: Build the parser and scaling helpers**

Add helpers for:

- `parse_batch_labels(value)`
- `is_qc_sample(sample_type)`
- `build_batch_membership(sample_info_df)`
- `validate_non_qc_batch_assignments(sample_info_df)`
- `compute_batch_qc_medians(feature_row, batch_to_qc)`
- `scale_feature_by_batch_qc_median(feature_row, batch_to_samples, batch_to_qc)`

Recommended parsing logic:

```python
parts = [part.strip() for part in str(value).split(";")]
labels = [part for part in parts if part]
```

**Step 2: Implement the processor main flow**

The processor should:

- read upstream sheet with priority:
  - `QC LOWESS result`
  - `ISTD_Correction`
  - `RawIntensity`
- read `SampleInfo`
- validate batch assignments
- scale each feature by per-batch QC median
- compute before/after QC CV%
- save a slim workbook with:
  - selected upstream sheet
  - `SampleInfo`
  - `QC_Batch_Scaling_result`
  - `QC_Batch_Scaling_summary`

**Step 3: Run focused tests**

Run:

```bash
pytest tests/unit/test_qc_batch_scaling.py -q
```

Expected: pass.

**Step 4: Commit**

```bash
git add src/metabolomics/processors/qc_batch_scaling.py src/metabolomics/utils/constants.py tests/unit/test_qc_batch_scaling.py
git commit -m "feat: add QC batch scaling processor"
```

### Task 6: Repoint GUI and Step 4 to the new Step 3

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/gui/app.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/normalization.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_normalization.py`

**Step 1: Update wiring**

In the GUI:

- rename Step 3 label to `Step 3: QC Batch Scaling`
- change module path from `metabolomics.processors.batch_effect` to `metabolomics.processors.qc_batch_scaling`

In Step 4:

- update data sheet priority to:
  1. `QC_Batch_Scaling_result`
  2. `Batch_effect_result`
  3. `QC LOWESS result`
  4. `ISTD_Correction`
  5. `RawIntensity`

**Step 2: Extend tests**

Add a Step 4 test that feeds a workbook with `QC_Batch_Scaling_result` and verifies:

- Step 4 selects it as the upstream data sheet
- Step 4 preserves it in the output workbook

**Step 3: Run focused tests**

Run:

```bash
pytest tests/unit/test_normalization.py -k "qc_batch_scaling or sheet" -q
```

Expected: pass.

**Step 4: Commit**

```bash
git add src/metabolomics/gui/app.py src/metabolomics/processors/normalization.py tests/unit/test_normalization.py
git commit -m "feat: wire Step 3 to QC batch scaling"
```

### Task 7: Add real-workbook regression coverage

**Files:**
- Verify only

**Step 1: Run focused regression suite**

Run:

```bash
pytest tests/unit/test_istd.py tests/unit/test_qc_lowess.py tests/unit/test_qc_batch_scaling.py tests/unit/test_normalization.py -q
```

Expected: pass.

**Step 2: Run manual Step 1 through Step 4 verification using the provided workbook**

Input:

```text
C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\ISTD測試\STEP4_program2_DNA_alignment_test_ISTD.xlsx
```

Verify:

- Step 1 either skips with the expected reason or produces `ISTD_Correction`
- Step 2 runs successfully on the Step 1 output
- Step 3 produces `QC_Batch_Scaling_result`
- `Breast Cancer Tissue_pooled_QC_3` and `Breast Cancer Tissue_pooled_QC_5` are counted in both relevant batch QC pools
- Step 4 accepts the Step 3 workbook without sheet-selection errors

**Step 3: Capture key evidence**

Record:

- Step 1 skip decision and good ISTD count
- per-batch parsed QC membership
- Step 3 workbook sheet names
- any per-feature invalid-median counts

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add ISTD gate and QC batch scaling workflow"
```

### Task 8: Optional cleanup after verification

**Files:**
- Verify only

**Step 1: Review whether legacy `batch_effect.py` remains referenced anywhere**

Run:

```bash
rg -n "batch_effect|Batch_effect_result|Batch_Effect_summary" src tests
```

Expected: only compatibility fallbacks and legacy references remain.

**Step 2: Decide on cleanup scope**

If compatibility references are still needed, keep the file in place.
If there are dead references that are no longer justified, remove them in a separate follow-up change rather than in the main implementation.
