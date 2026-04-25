# Dead Code Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove confirmed stale code, compatibility shims, stale constants, and stale docs without changing active Step 1-3 workflow output.

**Architecture:** Treat this as behavior-preserving cleanup. First establish a real-workbook baseline, then remove one cleanup class at a time, run targeted tests, and compare before/after Excel outputs semantically rather than byte-for-byte.

**Tech Stack:** Python, pytest, pandas/openpyxl, PowerShell, git, ruff.

---

## Scope Decisions

### Remove In This Cleanup

- `src/metabolomics/processors/istd.py` `save_skipped_istd_results_to_excel(...)`
- `src/metabolomics/processors/normalization.py` `is_numeric_value(...)`
- `src/metabolomics/processors/normalization.py` `get_non_qc_columns(...)`
- `src/metabolomics/processors/normalization.py` `get_sample_columns_only(...)`
- `src/metabolomics/processors/normalization.py` `select_file()`
- `src/metabolomics/utils/statistics.py` `calculate_hotelling_t2_outliers_internal(...)`
- `src/metabolomics/utils/file_io.py` `validate_required_columns(...)`
- `src/metabolomics/utils/safe_math.py` `get_valid_numeric_values(...)`
- `src/metabolomics/utils/constants.py` stale `SHEET_NAMES['batch_effect']` and `SHEET_NAMES['batch_summary']`
- Compatibility-only aliases if tests confirm no active workflow dependency:
  - `src/metabolomics/processors/normalization.py` `sample_specific_normalization(...)`
  - `src/metabolomics/processors/normalization.py` `get_all_sample_columns(...)`
  - `src/metabolomics/processors/qc_batch_scaling.py` `generate_pca_plots(...)`
- Unused imports and locals surfaced by targeted `ruff` checks in files touched by this cleanup.

### Preserve For Now As Reserved Extension Points

- `src/metabolomics/utils/data_validation.py` `DataValidator`, `ValidationResult`, and `quick_validate_excel(...)`
- `src/metabolomics/utils/sample_classification.py` `SampleClassifier` public facade and convenience methods
- `src/metabolomics/utils/plotting.py` `plot_pca_comparison_real_sample_style(...)`

These are not active wiring today, but they are plausible future extension points. Do not delete them in this pass unless a separate architecture decision explicitly narrows the public utility surface.

## Acceptance Workbook

Use this real workbook as one required acceptance fixture:

`C:\Users\user\Desktop\NTU cancer\Processed Data\DNA\Mzmine\new_test\ALL_metabcombiner_fh_format_20260422_213805_combined_fix.xlsx`

Observed structure:

- `RawIntensity`: 150 rows x 91 columns
- `SampleInfo`: 86 rows x 6 columns
- `SampleInfo` columns: `Sample_Name`, `Sample_Type`, `Injection_Order`, `Batch`, `Injection_Volume`, `DNA_mg/20uL`

This workbook must be used for the `SpecNorm+PQN` acceptance run because it has a numeric sixth-column normalization reference.

## Target Outcome

- Runtime behavior stays unchanged for active workflow Step 1 -> Step 2 -> Step 3.
- Step 4 remains paused/diagnostics-only; cleanup must not re-enable it in Auto Run.
- Dead-code search no longer finds removed runtime symbols outside archived docs, this plan, or the audit note.
- Tests no longer preserve obsolete compatibility contracts unless deliberately retained.
- Stale documentation no longer describes removed helpers or old active Batch Effect/ComBat workflow semantics as current behavior.

## Acceptance Criteria

1. Baseline and post-cleanup runs on the acceptance workbook both complete through Step 3 for `SpecNorm+PQN`.
2. The post-cleanup Step 3 workbook is semantically equal to the baseline Step 3 workbook:
   - identical sheet names, excluding intentionally ignored volatile metadata
   - identical row and column counts per compared sheet
   - identical column labels and row order
   - identical text/category values after normal Excel blank/NaN normalization
   - numeric values equal with `rtol=1e-12`, `atol=1e-9`, and `equal_nan=True`
3. Step 2 `LOESS_summary` presence and content remain semantically equal between baseline and post-cleanup runs.
4. Step 1 skip behavior, if triggered by the workbook, remains the same: same skipped/non-skipped state and same downstream input path semantics.
5. Step 4 Auto Run policy remains unchanged: GUI Auto Run terminal step is still Step 3, and Step 4 remains manual diagnostics-only.
6. Targeted tests pass:
   - `tests/unit/test_istd.py`
   - `tests/unit/test_qc_lowess.py`
   - `tests/unit/test_normalization.py`
   - `tests/unit/test_qc_batch_scaling.py`
   - `tests/unit/test_sample_matching.py`
   - `tests/unit/test_plotting.py`
   - `tests/unit/test_gui_step_flow.py`
   - `tests/integration/test_scenario_smoke.py`
7. Targeted import/bridge tests pass:
   - `tests/unit/test_imports_without_ms_core.py`
   - `tests/unit/test_bridge_launch.py`
8. `git diff --check` reports no whitespace errors.
9. Targeted `ruff` on touched runtime files has no newly introduced unused imports or undefined names. Full-repo `ruff` is allowed to remain red only for pre-existing unrelated issues and must be summarized if run.

## Task 1: Commit Current Documentation/Audit State

**Files:**
- Commit existing docs/audit changes before runtime cleanup.

**Step 1: Review current diff**

Run:

```powershell
git status --short
git diff -- docs/REFACTORING_PLAN.md docs/algorithms/combat.md src/metabolomics/adapters/__init__.py src/metabolomics/gui/app.py docs/plans/2026-04-25-dead-code-and-doc-drift-audit.md docs/plans/2026-04-25-dead-code-cleanup-plan.md
```

Expected: only documentation/comment/audit/plan changes.

**Step 2: Validate formatting**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

**Step 3: Commit**

Run:

```powershell
git add docs/REFACTORING_PLAN.md docs/algorithms/combat.md src/metabolomics/adapters/__init__.py src/metabolomics/gui/app.py docs/plans/2026-04-25-dead-code-and-doc-drift-audit.md docs/plans/2026-04-25-dead-code-cleanup-plan.md
git commit -m "docs: add dead-code cleanup audit and plan"
```

Expected: one docs commit, no runtime behavior change.

## Task 2: Establish Real-Workbook Baseline

**Files:**
- Create: `scripts/verify_workbook_equivalence.py`
- Create: `scripts/run_cleanup_acceptance_workflow.py`

**Step 1: Add acceptance runner**

Create a script that runs:

1. `istd.main(input_file=..., session_dir=...)`
2. `qc_lowess.main(input_file=step1.output_path, session_dir=...)`
3. `normalization.main(input_file=step2.output_path, session_dir=..., normalization_method=...)`

The runner must print JSON containing:

- `method`
- `session_dir`
- `step1.output_path`
- `step1.extra`
- `step2.output_path`
- `step3.output_path`

**Step 2: Add workbook equivalence comparator**

Create a comparator that accepts two workbook paths and compares all shared sheets with strict semantic equality:

- sheet names must match exactly
- columns and shape must match exactly
- text values compare after treating empty Excel cells and pandas `NaN` consistently
- numeric values compare with `rtol=1e-12`, `atol=1e-9`, `equal_nan=True`

The comparator must fail closed with a non-zero exit code and a concise mismatch report.

**Step 3: Generate baseline outputs**

Run:

```powershell
python scripts/run_cleanup_acceptance_workflow.py --input "C:\Users\user\Desktop\NTU cancer\Processed Data\DNA\Mzmine\new_test\ALL_metabcombiner_fh_format_20260422_213805_combined_fix.xlsx" --method "SpecNorm+PQN" --session-dir ".cleanup_acceptance\baseline_specnorm_pqn"
```

Expected: the command produces a Step 3 output path.

**Step 4: Commit verifier scripts**

Run targeted checks, then commit:

```powershell
python -m pytest tests/unit/test_imports_without_ms_core.py tests/unit/test_bridge_launch.py -q
git add scripts/verify_workbook_equivalence.py scripts/run_cleanup_acceptance_workflow.py
git commit -m "test: add cleanup equivalence verification tools"
```

Expected: verifier scripts are available before code deletion begins.

## Task 3: Remove High-Confidence Runtime Remnants

**Files:**
- Modify: `src/metabolomics/processors/istd.py`
- Modify: `src/metabolomics/processors/normalization.py`
- Modify: `src/metabolomics/utils/statistics.py`
- Modify: `src/metabolomics/utils/file_io.py`
- Modify: `src/metabolomics/utils/safe_math.py`
- Modify: `src/metabolomics/utils/constants.py`

**Step 1: Remove stale helpers**

Delete only the confirmed stale helpers listed in "Remove In This Cleanup". Do not touch reserved extension points.

**Step 2: Update tests that only preserve removed internals**

If a test directly imports a removed helper, migrate the assertion to the active public path. Do not add new compatibility tests for removed names.

**Step 3: Run targeted tests**

Run:

```powershell
python -m pytest tests/unit/test_istd.py tests/unit/test_qc_lowess.py tests/unit/test_normalization.py tests/unit/test_sample_matching.py -q
```

Expected: pass.

**Step 4: Run real-workbook candidate outputs**

Run:

```powershell
python scripts/run_cleanup_acceptance_workflow.py --input "C:\Users\user\Desktop\NTU cancer\Processed Data\DNA\Mzmine\new_test\ALL_metabcombiner_fh_format_20260422_213805_combined_fix.xlsx" --method "SpecNorm+PQN" --session-dir ".cleanup_acceptance\candidate_specnorm_pqn"
```

Expected: the command produces a Step 3 output path.

**Step 5: Compare baseline and candidate workbooks**

Run:

```powershell
python scripts/verify_workbook_equivalence.py --baseline ".cleanup_acceptance\baseline_specnorm_pqn\Step3_Normalized_SpecNorm_PQN.xlsx" --candidate ".cleanup_acceptance\candidate_specnorm_pqn\Step3_Normalized_SpecNorm_PQN.xlsx"
```

Expected: the comparison passes.

**Step 6: Commit**

Run:

```powershell
git add src/metabolomics/processors/istd.py src/metabolomics/processors/normalization.py src/metabolomics/utils/statistics.py src/metabolomics/utils/file_io.py src/metabolomics/utils/safe_math.py src/metabolomics/utils/constants.py tests
git commit -m "refactor: remove stale runtime helpers"
```

## Task 4: Remove Compatibility Shims

**Files:**
- Modify: `src/metabolomics/processors/normalization.py`
- Modify: `src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `tests/unit/test_normalization.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`
- Modify: relevant docs that mention `SampleSpecific` or `generate_pca_plots(...)` as active/current API.

**Step 1: Remove old aliases**

Remove:

- `sample_specific_normalization(...)`
- `SampleSpecific` canonicalization entries
- `get_all_sample_columns(...)` wrapper if all tests have migrated to `identify_sample_columns(...)`
- `generate_pca_plots(...)`

**Step 2: Update tests**

Replace compatibility-name tests with active API tests:

- `SpecNorm+PQN` / `SpecNorm_PQN`
- `identify_sample_columns(...)`
- `generate_step3_plots(...)`

**Step 3: Run targeted tests**

Run:

```powershell
python -m pytest tests/unit/test_normalization.py tests/unit/test_qc_batch_scaling.py tests/unit/test_sample_matching.py tests/unit/test_plotting.py -q
```

Expected: pass.

**Step 4: Repeat real-workbook equivalence**

Repeat Task 3 Step 4 and Step 5 after this deletion.

Expected: Step 3 output remains semantically identical to baseline for `SpecNorm+PQN`.

**Step 5: Commit**

Run:

```powershell
git add src/metabolomics/processors/normalization.py src/metabolomics/processors/qc_batch_scaling.py tests docs
git commit -m "refactor: remove obsolete compatibility shims"
```

## Task 5: Remove Unused Imports And Stale Docs

**Files:**
- Modify: runtime files touched in Tasks 3-4
- Modify: docs that still describe removed names as current behavior

**Step 1: Run targeted ruff**

Run:

```powershell
ruff check src/metabolomics/processors/istd.py src/metabolomics/processors/normalization.py src/metabolomics/processors/qc_batch_scaling.py src/metabolomics/utils/statistics.py src/metabolomics/utils/file_io.py src/metabolomics/utils/safe_math.py src/metabolomics/utils/constants.py src/metabolomics/gui/app.py src/metabolomics/adapters/dnp_to_metaboanalyst.py
```

Expected: no unused imports or undefined names in touched files. If unrelated legacy lint remains, document it and do not bulk-fix.

**Step 2: Search for removed names**

Run:

```powershell
rg -n "save_skipped_istd_results_to_excel|is_numeric_value|get_non_qc_columns|get_sample_columns_only|select_file\(|calculate_hotelling_t2_outliers_internal|validate_required_columns|get_valid_numeric_values|sample_specific_normalization|SampleSpecific|generate_pca_plots|Batch_effect_result|Batch_Effect_summary" src tests README.md docs
```

Expected: no active-code references. Remaining matches must be limited to archived plans/audit notes or must be removed.

**Step 3: Run GUI flow tests**

Run:

```powershell
python -m pytest tests/unit/test_gui_step_flow.py tests/unit/test_imports_without_ms_core.py tests/unit/test_bridge_launch.py -q
```

Expected: pass, including Step 4 paused/diagnostics-only Auto Run policy.

**Step 4: Commit**

Run:

```powershell
git add src tests docs README.md
git commit -m "chore: remove stale references after dead-code cleanup"
```

## Task 6: Final Verification And Review

**Files:**
- No planned code edits unless verification exposes an issue.

**Step 1: Run final targeted suite**

Run:

```powershell
python -m pytest tests/unit/test_istd.py tests/unit/test_qc_lowess.py tests/unit/test_normalization.py tests/unit/test_qc_batch_scaling.py tests/unit/test_sample_matching.py tests/unit/test_plotting.py tests/unit/test_gui_step_flow.py tests/unit/test_imports_without_ms_core.py tests/unit/test_bridge_launch.py tests/integration/test_scenario_smoke.py -q
```

Expected: pass.

**Step 2: Repeat real-workbook equivalence one final time**

Repeat Task 3 Step 4 and Step 5 against fresh final candidate directories:

- `.cleanup_acceptance\final_specnorm_pqn`

Expected: the final Step 3 workbook remains semantically equal to baseline.

**Step 3: Check diff hygiene**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors. Worktree contains only intended changes before the final commit, or is clean after final commit.

**Step 4: Code review**

Review the final diff for:

- accidental behavior changes in Step 1-3
- deleted tests that removed real coverage instead of compatibility-only coverage
- stale docs that still describe old Batch Effect/ComBat/current Step 4 semantics
- unsafe broad cleanup or unrelated formatting churn

**Step 5: Final commit if needed**

Run:

```powershell
git add src tests docs scripts README.md
git commit -m "chore: finalize dead-code cleanup verification"
```

Expected: cleanup branch is split into small reviewable commits and ready for PR update.
