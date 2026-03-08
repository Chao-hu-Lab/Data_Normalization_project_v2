# Four-Step Workbook Slimming Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Slim each pipeline workbook so it only keeps the previous step's required data sheet, `SampleInfo`, and the current step's outputs.

**Architecture:** Apply narrow save-path changes inside each processor. Preserve existing data selection rules, especially Step 4's fallback from `Batch_effect_result` to `QC LOWESS result`, but stop copying unrelated worksheets into downstream files.

**Tech Stack:** Python, pandas, openpyxl, pytest

---

### Task 1: Lock sheet-retention behavior with regression tests

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_istd.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_qc_lowess.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_batch_effect.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_normalization.py`

**Step 1: Write failing tests**

Add tests that:

- create a temporary workbook with an extra sheet before each step
- run the relevant step
- assert the output workbook contains only the expected retained sheets

Include two Step 4 paths:

- input contains `Batch_effect_result`
- input does not contain `Batch_effect_result` but does contain `QC LOWESS result`

**Step 2: Run targeted tests to verify failure**

Run:

```bash
pytest tests/unit/test_istd.py -k sheet -q
pytest tests/unit/test_qc_lowess.py -k sheet -q
pytest tests/unit/test_batch_effect.py -k sheet -q
pytest tests/unit/test_normalization.py -k sheet -q
```

Expected: failures showing extra worksheets are still being copied.

### Task 2: Slim Step 1 and Step 2 workbook outputs

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/istd.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/qc_lowess.py`

**Step 1: Implement minimal save-path changes**

- Step 1 writes only `RawIntensity`, `SampleInfo`, and `ISTD_Correction`
- Step 2 writes only `ISTD_Correction`, `QC LOWESS result`, `QC_LOWESS_Advanced Statistics`, and `SampleInfo`

**Step 2: Re-run focused tests**

Run:

```bash
pytest tests/unit/test_istd.py -k sheet -q
pytest tests/unit/test_qc_lowess.py -k sheet -q
```

Expected: both pass.

### Task 3: Slim Step 3 and Step 4 workbook outputs

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/batch_effect.py`
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/normalization.py`

**Step 1: Implement minimal save-path changes**

- Step 3 copies only `QC LOWESS result` from input and writes `SampleInfo`, `Batch_effect_result`, and `Batch_Effect_summary`
- Step 4 save function accepts the selected upstream sheet name and preserves only that sheet, `SampleInfo`, result, and summary
- Update sheet-list console messages to match the new workbook contents

**Step 2: Re-run focused tests**

Run:

```bash
pytest tests/unit/test_batch_effect.py -k sheet -q
pytest tests/unit/test_normalization.py -k sheet -q
```

Expected: both pass.

### Task 4: Verify the end-to-end workflow and real Step 4 input

**Files:**
- Verify only

**Step 1: Run focused pipeline tests**

Run:

```bash
pytest tests/unit/test_istd.py tests/unit/test_qc_lowess.py tests/unit/test_batch_effect.py tests/unit/test_normalization.py -q
```

Expected: relevant tests pass.

**Step 2: Run manual verification on the provided workbook**

Run Step 4 against:

```text
C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\STEP4_program2_DNA_alignment_20260306_235927.xlsx
```

Expected output workbook sheets:

- `RawIntensity`
- `SampleInfo`
- normalization result sheet
- `ConcNormalization_Summary`
