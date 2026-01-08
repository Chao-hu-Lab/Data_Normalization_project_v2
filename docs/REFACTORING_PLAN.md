# Data Normalization Project v2 - Refactoring Plan

## Overview
Gradual refactoring approach to improve code quality while maintaining stability.

---

## Phase 1: Zero-Risk Changes
**Risk Level:** None
**Estimated Impact:** ~50 lines

### 1.1 README Rewrite
- [ ] Replace current 4-line notes with proper documentation
- [ ] Include: project description, requirements, installation, usage, workflow steps

### 1.2 Remove Unused Variables (Data_Normalization_program_v2.py)
- [ ] Line 91: Remove `self.progress_running = False`
- [ ] Line 106: Remove `self.output_buffer = []`

### 1.3 Clean Up Redundant Pass Statement
- [ ] Line 857-858: Remove empty pass in `set_progress()`

---

## Phase 2: Test Framework Setup
**Risk Level:** None (additive only)
**Purpose:** Establish baseline before refactoring

### 2.1 Create Test Structure
```
tests/
├── __init__.py
├── conftest.py              # pytest fixtures
├── test_data/               # symlink to test files
├── test_istd_correction.py
├── test_qc_lowess.py
├── test_batch_effect.py
└── test_concentration_norm.py
```

### 2.2 Baseline Tests (per module)
Each module needs tests for:
- [ ] Input validation (file exists, correct format)
- [ ] Output structure (correct sheets, columns)
- [ ] Data integrity (row count preserved, no NaN explosion)
- [ ] Return value format (dict with expected keys)

### 2.3 Test Data
Available test files:
- `data/feature_matrix_control_exposed_AfterVBA.xlsx`
- `data/feature_matrix_with_qc_AfterVBA.xlsx`

---

## Phase 3: Extract Common Utilities
**Risk Level:** Medium
**Prerequisite:** Phase 2 tests passing

### 3.1 Create Utils Module Structure
```
utils/
├── __init__.py
├── common.py           # get_valid_values, warnings setup
├── data_loader.py      # load_and_process_data (parameterized)
├── statistics.py       # Hotelling T², FDR correction
├── plotting.py         # draw_hotelling_t2_ellipse, matplotlib config
└── excel_format.py     # Excel styling utilities
```

### 3.2 Extraction Order (safest first)

#### Step 3.2.1: `get_valid_values()` - IDENTICAL
Location: ISTD_Correction_v2.py:34, QC_LOWESS_v2.py:663
```python
def get_valid_values(row, columns):
    """Helper: Extract valid float values from row"""
    values = []
    for col in columns:
        if col in row:
            try:
                val = float(row[col])
                if not pd.isna(val) and val > 0:
                    values.append(val)
            except ValueError:
                pass
    return values
```
**Action:** Extract to `utils/common.py`

#### Step 3.2.2: `draw_hotelling_t2_ellipse()` - IDENTICAL
Locations: ISTD:934, QC:1807, Batch:1231
**Action:** Extract to `utils/plotting.py`

#### Step 3.2.3: `calculate_hotelling_t2_outliers()` - NEARLY IDENTICAL
Locations: ISTD:784, QC:1763, Batch:1157
**Note:** Batch_Effect has TWO versions - need to merge first
**Action:**
1. First merge Batch_Effect's two functions
2. Then extract to `utils/statistics.py`

#### Step 3.2.4: Matplotlib Configuration - IDENTICAL
All 4 subprograms have:
```python
warnings.filterwarnings('ignore')
plt.rcParams['text.usetex'] = False
plt.rcParams['mathtext.default'] = 'regular'
# font family detection...
```
**Action:** Extract to `utils/plotting.py` as `configure_matplotlib()`

#### Step 3.2.5: `apply_fdr_correction()` - Check for duplicates
**Action:** Verify if duplicated, extract if so

### 3.3 Verification After Each Extraction
After extracting each function:
1. Run all Phase 2 tests
2. Verify output files are byte-identical (or numerically equivalent)
3. Commit changes with descriptive message

---

## Phase 4: GUI & Output Structure Optimization
**Risk Level:** Medium-High
**Prerequisite:** Phase 3 complete

### 4.1 Consolidate Duplicate GUI Methods
- [ ] Merge `select_input_file()` and `select_initial_file()`
- [ ] Review `open_step_folder()` vs `open_step_plots()` overlap

### 4.2 Output Directory Restructuring (Optional)
Current:
```
output/
├── *.xlsx (mixed)
├── ISTD_Correction_plots/
├── QC_LOWESS_plots/
├── Batch_Effect_plots/
└── Normalization_Figures/
```

Proposed:
```
output/
└── [timestamp]_[input_filename]/
    ├── Step1_ISTD/
    ├── Step2_QC_LOWESS/
    ├── Step3_Batch_Effect/
    └── Step4_Normalization/
```

**Note:** This requires updating:
- All `main()` functions' output path logic
- GUI's `open_step_excel()` and `open_step_plots()`
- `step_outputs` dictionary structure

---

## Risk Mitigation Checklist

Before each phase:
- [ ] Create git branch: `git checkout -b refactor-phase-X`
- [ ] Ensure all tests pass on main branch
- [ ] Backup current working state

After each change:
- [ ] Run test suite
- [ ] Manual smoke test with GUI
- [ ] Compare output files with baseline

If issues found:
- [ ] Revert to last known good state
- [ ] Analyze what went wrong
- [ ] Adjust approach

---

## Estimated Timeline

| Phase | Complexity | Dependencies |
|-------|------------|--------------|
| Phase 1 | Low | None |
| Phase 2 | Medium | Phase 1 |
| Phase 3 | High | Phase 2 tests passing |
| Phase 4 | High | Phase 3 complete |

---

## Files Changed Summary

### Phase 1
- `README.md` (rewrite)
- `Data_Normalization_program_v2.py` (minor deletions)

### Phase 2
- New `tests/` directory
- New `pytest.ini` or `pyproject.toml`

### Phase 3
- New `utils/` directory
- `ISTD_Correction_v2.py` (import changes)
- `QC_LOWESS_v2.py` (import changes)
- `Batch_Effect_v2.py` (import changes, merge functions)
- `Concentration_Normalization_v2.py` (import changes)

### Phase 4
- `Data_Normalization_program_v2.py` (GUI methods)
- All 4 subprograms (output path logic)
