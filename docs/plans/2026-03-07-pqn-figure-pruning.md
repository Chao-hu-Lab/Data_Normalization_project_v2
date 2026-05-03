> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# PQN Figure Pruning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep only Fig1 to Fig4 in DNP Step 4 PQN output and stop generating Fig5 to Fig7.

**Architecture:** The change stays local to the Step 4 plotting orchestration in `normalization.py`. A focused regression test will lock the figure file naming and ensure the removed plotting branches are not invoked.

**Tech Stack:** Python, pytest, pandas, numpy

---

### Task 1: Add regression coverage for Step 4 figure selection

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_normalization.py`
- Test: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_normalization.py`

**Step 1: Write the failing test**

Add a focused unit test that monkeypatches the Step 4 plotting functions and records output filenames. Assert that only `Fig1_` through `Fig4_` are requested.

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_normalization.py -k figure -q --basetemp=.pytest_tmp_norm_red`

Expected: FAIL because Step 4 still builds or invokes `Fig5` to `Fig7`.

**Step 3: Write minimal implementation**

Trim the `figure_paths` dictionary and remove the plotting calls for QC variability, QC reproducibility, and correlation heatmap.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_normalization.py -k figure -q --basetemp=.pytest_tmp_norm_green`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/unit/test_normalization.py src/metabolomics/processors/normalization.py docs/plans/2026-03-07-pqn-figure-pruning-design.md docs/plans/2026-03-07-pqn-figure-pruning.md
git commit -m "refactor: keep only first four PQN figures in step 4"
```

### Task 2: Verify Step 4 still runs successfully

**Files:**
- Modify: `C:/Users/user/Desktop/Data_Normalization_project_v2/src/metabolomics/processors/normalization.py`
- Test: `C:/Users/user/Desktop/Data_Normalization_project_v2/tests/unit/test_normalization.py`

**Step 1: Run focused verification**

Run: `pytest tests/unit/test_normalization.py -q --basetemp=.pytest_tmp_norm_full`

Expected: PASS for the targeted coverage.

**Step 2: Re-run the reported Step 4 scenario if needed**

Run Step 4 against the known DNP input chain and confirm only Fig1 to Fig4 appear in the output directory.

**Step 3: Commit**

```bash
git add tests/unit/test_normalization.py src/metabolomics/processors/normalization.py
git commit -m "refactor: remove unused PQN step 4 figures"
```
