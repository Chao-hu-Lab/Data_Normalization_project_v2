# DNP Workflow Responsibility Refactor Master Execution Plan

> **For Claude:** Treat this file as the single execution plan for the refactor. Use the three 2026-04-23 planning docs as design references, but drive implementation order, test updates, and documentation updates from this file only.

**Goal:** Refactor DNP so the active workflow cleanly matches the new responsibility boundary: Step 2 is a batch-local QC drift correction module, Step 3 is a concentration normalization module with explicit PQN reference selection rules, and Step 4 is paused as an active scientific correction step while retaining diagnostics where justified.

**Architecture:** Keep the current processor split (`istd.py`, `qc_lowess.py`, `normalization.py`, `qc_batch_scaling.py`) and refactor in place. Do not introduce a new workflow framework. Instead, tighten each step's contract, then rewire GUI, adapter, README, and tests so all workflow surfaces agree on the new scientific boundary.

**Tech Stack:** Python, pandas, numpy, scipy, statsmodels, openpyxl, Tkinter, pytest

**Design References:**
- `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`
- `docs/plans/2026-04-23-dnp-qc-loess-hardening-and-step4-pause-plan.md`
- `docs/plans/2026-04-23-pqn-reference-selection-rules.md`

---

### Task 1: Lock the new Step 2 responsibility boundary with failing tests

**Files:**
- Modify: `tests/unit/test_qc_lowess.py`

**Step 1: Add failing tests for the new Step 2 contract**

Add focused unit coverage for:

- batch-local target selection instead of any cross-batch `global_qc_median`
- `no_drift_detected` skip behavior for weak-trend features
- IQR outlier filtering behavior
- correction-factor clamp reporting
- outside-range sample counting / warning metadata
- staged status outcomes such as:
  - `insufficient_qc`
  - `all_qc_invalid`
  - `outlier_filtering_left_too_few_points`
  - `no_drift_detected`
  - `success`
  - `unstable_correction_factors`

**Step 2: Run focused tests to confirm failure**

Run:

```powershell
uv run pytest tests/unit/test_qc_lowess.py -q
```

Expected:
FAIL because the current implementation still accepts `global_qc_median`, lacks pre-apply drift gating, and does not expose the required reporting fields.

### Task 2: Remove cross-batch target leakage from Step 2

**Files:**
- Modify: `src/metabolomics/processors/qc_lowess.py`
- Test: `tests/unit/test_qc_lowess.py`

**Step 1: Remove the active `global_qc_median` path**

- Remove `global_qc_median` from `apply_lowess_correction(...)`
- Stop computing and passing per-feature global QC medians in `perform_lowess_normalization(...)`
- Define the correction target using batch-local data only, with this order:
  1. median of the fitted batch-local QC curve
  2. median of observed valid batch-local QC values
  3. fallback `1.0`

**Step 2: Keep the implementation batch-local**

- Preserve per-batch LOWESS fitting
- Ensure Step 2 never intentionally aligns batches to a shared absolute QC level

**Step 3: Run focused tests**

Run:

```powershell
uv run pytest tests/unit/test_qc_lowess.py -k "global or batch_local or target" -q
```

Expected:
PASS

### Task 3: Add pre-fit QC filtering and pre-apply no-drift gating

**Files:**
- Modify: `src/metabolomics/processors/qc_lowess.py`
- Test: `tests/unit/test_qc_lowess.py`

**Step 1: Add QC outlier filtering helper**

Implement a helper such as:

- `filter_qc_outliers_iqr(qc_orders, qc_intensities, *, min_keep=5, min_keep_ratio=0.7)`

Required behavior:

- build finite positive QC arrays
- compute `Q1`, `Q3`, `IQR`
- flag values outside `Q1 - 1.5*IQR` to `Q3 + 1.5*IQR`
- only remove outliers if both keep-count rules remain satisfied
- return filtering metadata for reporting

**Step 2: Add no-drift detection before correction is applied**

- compute Kendall's tau and p-value on the filtered QC series
- compute LOWESS fit quality metrics such as `R2`, `RMSE`, and normalized RMSE
- if drift evidence is weak, return original intensities with status `no_drift_detected`

**Step 3: Restructure staged status logic**

Split status decisions into:

- pre-fit
- post-fit / pre-apply
- post-apply

Do not keep a fit-first-evaluate-later flow as the main path.

**Step 4: Run focused tests**

Run:

```powershell
uv run pytest tests/unit/test_qc_lowess.py -k "outlier or drift or no_drift or status" -q
```

Expected:
PASS

### Task 4: Add factor clamp, edge reporting, and Step 2 advanced summary fields

**Files:**
- Modify: `src/metabolomics/processors/qc_lowess.py`
- Test: `tests/unit/test_qc_lowess.py`

**Step 1: Clamp correction factors**

- compute raw factor as `target / fitted`
- clamp to a configurable range
- report:
  - `raw_factor_min`
  - `raw_factor_max`
  - `clamped_factor_min`
  - `clamped_factor_max`
  - `clamped_count`
  - `clamped_ratio`

**Step 2: Add edge-usage reporting**

- keep `hold` behavior for compatibility in the first pass
- record how many corrected samples fall outside the observed QC range
- expose a warning-oriented field such as `Outside_QC_Range_Count`

**Step 3: Expand advanced statistics output**

Add Step 2 reporting fields aligned with the plan docs, including:

- `Valid_QC_Count`
- `Removed_QC_Outliers`
- `Outlier_Filter_Applied`
- `Trend_pvalue`
- `Kendall_Tau`
- `LOESS_R2`
- `LOESS_RMSE`
- `Normalized_RMSE`
- `Target_Strategy`
- `Clamped_Factor_Ratio`
- `Outside_QC_Range_Count`
- `Decision_Status`

**Step 4: Freeze the Step 2 -> Step 3 data contract**

Step 3 must read Step 2 decision inputs from the Step 2 advanced statistics sheet rather than silently recomputing a second set of QC stability heuristics.

Define the Step 2 advanced sheet as the canonical upstream contract for at least:

- per-feature `Decision_Status`
- per-feature `Kendall_Tau`
- per-feature `Trend_pvalue`
- per-feature `LOESS_R2`
- per-feature `LOESS_RMSE`
- per-feature `Normalized_RMSE`
- per-feature `Valid_QC_Count`
- per-feature `Removed_QC_Outliers`
- per-feature `Outside_QC_Range_Count`

If Step 3 later needs more information to choose PQN strategy, extend this Step 2 sheet first. Do not add a parallel hidden metrics path inside Step 3.

**Step 5: Run focused tests**

Run:

```powershell
uv run pytest tests/unit/test_qc_lowess.py -k "clamp or outside or summary or advanced" -q
```

Expected:
PASS

### Task 5: Lock the new Step 3 PQN reference strategy with failing tests

**Files:**
- Modify: `tests/unit/test_normalization.py`

**Step 1: Add failing tests for reference strategy selection**

Add regression coverage for:

- single-batch post-LOESS stable QC -> QC-based reference
- single-batch post-LOESS unstable QC -> robust median fallback
- multi-batch with non-shared QC -> robust median fallback
- shared-QC multi-batch case -> QC-based strategy allowed only when explicitly supported
- Step 3 reading required QC stability signals from the Step 2 advanced statistics sheet
- summary/report output reflecting the chosen strategy and rationale

Prefer strategy labels that encode the workflow intent explicitly, for example:

- `QC_SINGLE_BATCH`
- `QC_SHARED_MULTIBATCH`
- `ROBUST_MEDIAN_FALLBACK`
- `ROBUST_MEDIAN_NONSHARED_MULTIBATCH`

**Step 2: Run focused tests to confirm failure**

Run:

```powershell
uv run pytest tests/unit/test_normalization.py -k "reference_strategy or pqn" -q
```

Expected:
FAIL because current PQN strategy selection mostly depends on QC count and QC CV only.

### Task 6: Implement explicit PQN reference selection rules in Step 3

**Files:**
- Modify: `src/metabolomics/processors/normalization.py`
- Test: `tests/unit/test_normalization.py`

**Step 1: Introduce an explicit strategy selector**

Refactor Step 3 so PQN reference selection inspects at least:

- number of unique batches
- whether QC is scientifically shared across batches
- post-LOESS QC stability metrics read from the Step 2 advanced statistics sheet
- whether QC counts are balanced enough to justify a global QC reference

Do not re-derive a second hidden version of these metrics inside Step 3 unless the value is a trivial aggregation of fields already present in the Step 2 advanced sheet.

If Step 3 lacks enough information to make the decision cleanly, add the missing field(s) to the Step 2 advanced statistics sheet first, then consume them from there.

**Step 2: Keep Step 3 within the normalization boundary**

- Step 3 may use QC for reference construction when justified
- Step 3 must not act like batch correction
- multi-batch non-shared QC must default to robust median rather than global QC-derived PQN

**Step 3: Update Step 3 summary/report wording**

Make the generated report explain:

- which reference strategy was chosen
- why it was chosen
- when QC was intentionally excluded from the primary PQN reference

**Step 4: Run focused tests**

Run:

```powershell
uv run pytest tests/unit/test_normalization.py -k "reference_strategy or summary_context or report" -q
```

Expected:
PASS

### Task 7: Pause Step 4 as an active workflow step while preserving diagnostics

**Files:**
- Modify: `src/metabolomics/processors/qc_batch_scaling.py`
- Modify: `tests/unit/test_qc_batch_scaling.py`

**Step 1: Change Step 4 default behavior**

Refactor `qc_batch_scaling.main(...)` so the default entry path is paused / skipped for active scientific correction.

Acceptable first-pass behavior:

- return a `ProcessingResult` with `skipped=True`
- set an explicit reason such as `paused_nonshared_qc_design`
- preserve diagnostics only through an explicit interface such as `diagnostics_only=True`

Define this interface up front:

- `qc_batch_scaling.main(..., diagnostics_only=False)` -> default paused path, no active scaling math
- `qc_batch_scaling.main(..., diagnostics_only=True)` -> diagnostic-only path, allowed to emit plots / diagnostic workbook outputs, but must not be presented as active correction

**Step 2: Retain diagnostics intentionally**

Keep useful outputs such as:

- residual analysis
- QC alignment plots
- batch boxplots or similar comparisons

But relabel them as diagnostics, not validated correction proof.

**Step 3: Update Step 4 messaging and summary wording**

The processor should state clearly that:

- Step 4 scaling math is paused
- the current design does not justify cross-batch QC anchoring
- diagnostics may still be emitted for review

**Step 4: Run focused tests**

Run:

```powershell
uv run pytest tests/unit/test_qc_batch_scaling.py -q
```

Expected:
PASS with updated paused-path expectations.

### Task 8: Rewire GUI, export, and bridge behavior to the new workflow boundary

**Files:**
- Modify: `src/metabolomics/gui/app.py`
- Modify: `src/metabolomics/adapters/dnp_to_metaboanalyst.py`
- Modify: `tests/unit/test_gui_step_flow.py`
- Modify: `tests/unit/test_bridge_launch.py`

**Step 1: Update GUI workflow semantics**

- keep the Step 4 card visible, but mark it explicitly as paused / diagnostics-only
- remove Step 4 from the default `Auto Run` path so normal workflow execution stops after Step 3
- allow Step 4 manual invocation only as an explicit diagnostics run that calls the `diagnostics_only=True` path
- update export readiness so normal export does not depend on Step 4 completion
- replace wording such as `Export After Step 4`

**Step 2: Update export source priority**

The workflow should prefer the current Step 3 run output resolved from workflow state / current run context rather than any paused Step 4 artifact.

The adapter should prefer active normalized outputs rather than paused Step 4 output.

Recommended priority:

1. current Step 3 output selected by workflow state or current run context
2. `SpecNorm_PQN_Result`
3. `PQN_Result`
4. `QC_Batch_Scaling_result` only as an explicit diagnostic fallback, not the default final result

**Step 3: Update focused tests**

Add or revise tests to verify:

- GUI export can become ready after Step 3
- Step 4 no longer defines the active workflow finish line
- MetaboAnalyst export prefers Step 3 output over Step 4 diagnostic output

**Step 4: Run focused tests**

Run:

```powershell
uv run pytest tests/unit/test_gui_step_flow.py tests/unit/test_bridge_launch.py -q
```

Expected:
PASS

### Task 9: Migrate pipeline fixtures and integration tests to the paused-Step-4 contract

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/integration/test_scenario_smoke.py`
- Modify: `tests/integration/test_scenario_regression.py`

**Step 1: Update the cached pipeline fixture**

Refactor the shared pipeline fixture so:

- Step 3 is the active scientific endpoint
- Step 4 is optional and diagnostic-only
- downstream tests do not assume `run_full_pipeline()["step4"]` is the default final scientific result

**Step 2: Update integration expectations**

Rewrite old Step 4 assumptions explicitly, including:

- scenarios that previously treated Step 4 as required correction output
- workflow completion semantics
- expected final workbook selection

Where diagnostics are still relevant, invoke Step 4 explicitly in diagnostics-only mode instead of relying on the old default active path.

**Step 3: Run integration-focused checks**

Run:

```powershell
uv run pytest tests/integration/test_scenario_smoke.py tests/integration/test_scenario_regression.py -q
```

Expected:
PASS against the new paused-Step-4 workflow contract.

### Task 10: Update README and algorithm docs to match the new boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/algorithms/qc_lowess.md`
- Modify: `docs/algorithms/normalization.md`

**Step 1: Update workflow description**

- describe Step 2 as batch-local QC drift correction only
- describe Step 3 as concentration normalization only
- describe Step 4 as paused / deprecated for active scientific use

**Step 2: Remove misleading language**

Delete or rewrite any language implying:

- mature cross-batch correction inside DNP
- QC-LOESS as a cross-batch alignment method
- QC-derived PQN as globally safe by default

**Step 3: Verify docs align with code**

Do not document behaviors that are still absent from implementation.

### Task 11: Run focused regression suites and one manual workflow check

**Files:**
- No source edits required if earlier tasks pass

**Step 1: Run targeted suites**

Run:

```powershell
uv run pytest tests/unit/test_qc_lowess.py tests/unit/test_normalization.py tests/unit/test_qc_batch_scaling.py tests/unit/test_gui_step_flow.py tests/unit/test_bridge_launch.py -q
```

Expected:
PASS

**Step 2: Manual workflow verification**

Verify manually that:

- Step 3 remains the active completion point for scientific normalization
- Step 4 appears as paused / diagnostic-only if still surfaced
- `Auto Run` stops after Step 3
- export uses Step 3 output by default
- generated summaries no longer claim cross-batch correction inside DNP

### Task 12: Final cleanup and convergence pass

**Files:**
- Review the touched files from Tasks 1-11

**Step 1: Perform a review pass**

Check for:

- stale Step 4 naming in GUI or docs
- stale status labels in Step 2 tests or summaries
- adapter logic still preferring paused outputs
- unnecessary complexity introduced during refactor

**Step 2: Run one final focused verification set**

Run:

```powershell
uv run pytest tests/unit/test_qc_lowess.py tests/unit/test_normalization.py tests/unit/test_qc_batch_scaling.py tests/unit/test_gui_step_flow.py tests/unit/test_bridge_launch.py -q
```

Expected:
PASS

---

## Implementation Notes

- Do not start by deleting Step 4 code; first pause it cleanly and preserve diagnostics intentionally.
- Do not broaden DNP into a cross-batch modeling platform.
- Do not run a full monolithic suite first; stay with focused test shards that match the changed contract.
- When a test encodes the old active-Step-4 workflow, rewrite the test around the new paused-boundary contract instead of preserving stale behavior.

## Completion Criteria

The refactor is complete when all of the following are true:

- Step 2 is batch-local and no longer uses cross-batch targets
- Step 2 implementation and docs agree on filtering, skip logic, clamp behavior, and reporting
- Step 3 chooses PQN reference strategies explicitly and does not silently act like batch correction
- Step 4 is paused as an active correction step and retained only as diagnostic-only functionality where justified
- GUI, export, adapter, README, and tests all treat Step 3 as the active scientific workflow endpoint
