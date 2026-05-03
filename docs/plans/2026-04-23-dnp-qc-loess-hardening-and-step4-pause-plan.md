> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# DNP QC-LOESS Hardening and Step 4 Pause Implementation Plan

**Date**

- 2026-04-23

**Status**

- Implemented on `refactor/dnp-workflow-responsibility-core-overhaul` as of 2026-04-25.
- This file is retained as historical implementation rationale, not as the current open work queue.

**Context**

This plan converted the DNP implementation into a cleaner responsibility split:

- Step 2 remains the active QC-based drift-correction stage, but is hardened so the implementation matches the scientific intent and its own documentation more closely.
- Step 4 `QC Batch Scaling` is paused as an active scaling step because its cross-batch anchor assumption is not satisfied in the current experimental design.

The plan below is implementation-oriented and intended for a follow-up coding session.

## Goals

- keep DNP responsible for within-batch stabilization only
- harden Step 2 `QC-LOESS` so it behaves like a defensible batch-local QC drift method
- stop treating Step 4 scaling math as scientifically active
- preserve useful diagnostics wherever possible

## Non-Goals

- do not add `ComBat` to DNP
- do not redesign DNP into a general batch-correction platform
- do not hide Step 4 by deleting all code immediately; first pause it cleanly and preserve diagnostics intentionally

## Current Gaps Observed

### Step 2 gaps

1. **Cross-batch target leakage**
   - LOWESS fitting is batch-wise, but the correction target can still be `global_qc_median` across batches.
   - This makes Step 2 partially behave like cross-batch alignment.

2. **Documentation / implementation mismatch**
   - docs claim IQR-based QC outlier handling
   - docs claim weak-trend features should skip correction
   - docs claim correction-factor limits should be enforced
   - pre-refactor implementation did not fully enforce those behaviors

3. **Edge extrapolation risk**
   - interpolation outside fitted QC range currently uses edge values directly
   - long gaps near batch start or end can therefore create flat but unjustified correction factors

4. **Status logic is mostly post-hoc**
   - current logic often fits first, then labels the result as `insufficient_improvement` or `overcorrection_detected`
   - a better design should include pre-fit and pre-apply gating

### Step 4 gaps

1. **Invalid scientific anchor**
   - per-batch pooled QC medians are used as if they were directly comparable across batches
   - this is not justified when QC material differs by batch

2. **Workflow ambiguity**
   - Step 4 still looks like an endorsed normalization stage in README and workflow naming
   - users can therefore mistake it for a scientifically settled correction step

## Planned Changes

## Part A: Step 2 `QC-LOESS` hardening

### A1. Remove cross-batch target behavior

**Current issue**

`perform_lowess_normalization(...)` builds `global_qc_medians` and can pass them into `apply_lowess_correction(...)`.

**Change**

- remove the active use of cross-batch `global_qc_median` as the correction target
- define the target from batch-local QC only
- recommended target order:
  1. median of fitted batch-local QC curve
  2. median of observed valid batch-local QC values
  3. fallback `1.0` only when the feature is otherwise unusable

**Result**

Step 2 becomes a pure within-batch drift-correction module.

### A2. Add explicit QC outlier filtering before LOWESS fit

**Current issue**

The documentation describes IQR-based QC outlier handling, but the fit path currently uses all valid QC values.

**Change**

Add a helper such as:

- `filter_qc_outliers_iqr(qc_orders, qc_intensities, *, min_keep=5, min_keep_ratio=0.7)`

Recommended behavior:

1. build valid QC arrays from finite, positive values
2. compute `Q1`, `Q3`, `IQR`
3. flag QC intensities outside `[Q1 - 1.5*IQR, Q3 + 1.5*IQR]`
4. only remove flagged points if both are true:
   - remaining QC count >= 5
   - remaining QC count >= 70% of original valid QC count
5. record the following in `info`:
   - original valid QC count
   - removed outlier count
   - outlier filtering applied or skipped

**Why**

This matches the intended doc behavior and prevents single abnormal QC injections from dominating the fit.

### A3. Add a weak-trend / no-correction gate

**Current issue**

The current path almost always fits if QC count is sufficient. The status is often decided only after correction has already been attempted.

**Change**

Add a pre-application gate based on trend evidence.

Recommended rule set:

- compute Kendall's tau and p-value on the filtered QC series
- fit LOWESS candidate and compute:
  - `R2`
  - `RMSE`
  - optional normalized RMSE such as `RMSE / median(valid_y)`
- if all of the following are true, skip correction and keep original values:
  - `abs(tau) < 0.2`
  - `trend_pvalue >= 0.05`
  - `R2 < 0.1`
  - normalized drift amplitude is small

Suggested status label:

- `no_drift_detected`

**Result**

Stable features stay unchanged instead of being smoothed for no reason.

### A4. Add correction-factor clamp and clamp reporting

**Current issue**

Docs describe factor limits, but factors are not actually clamped.

**Change**

- compute raw factor as `target / fitted`
- clamp to a configurable range, recommended initial default:
  - `min_factor = 0.5`
  - `max_factor = 2.0`
- record in `info`:
  - `raw_factor_min`
  - `raw_factor_max`
  - `clamped_factor_min`
  - `clamped_factor_max`
  - `clamped_count`
  - `clamped_ratio`

Suggested status behavior:

- if `clamped_ratio` is high, mark the feature as `unstable_correction_factors`
- do not silently hide clamp-heavy features in summary

### A5. Strengthen edge-handling rules

**Current issue**

Interpolation currently reuses edge fitted values outside the QC range.

**Change**

Add an explicit policy parameter such as:

- `edge_policy = "hold" | "skip_outside"`

Recommended first implementation:

- keep current `hold` policy as default for compatibility
- but record how many corrected samples fall outside the QC span
- if too many non-QC samples sit outside the observed QC range, downgrade status to warning / partial success

Possible later upgrade:

- optionally leave outside-range samples unchanged instead of applying held factors

### A6. Restructure status logic into pre-fit / post-fit / post-apply stages

**Current issue**

Status labels are currently mixed together and are mostly derived after the fit.

**Change**

Use a staged decision model:

- **pre-fit**
  - `insufficient_qc`
  - `all_qc_invalid`
  - `outlier_filtering_left_too_few_points`
- **post-fit but pre-apply**
  - `no_drift_detected`
  - `fit_failed`
- **post-apply**
  - `success`
  - `insufficient_improvement`
  - `overcorrection_detected`
  - `unstable_correction_factors`

This makes summaries easier to interpret and test.

### A7. Expand Step 2 reporting

Add fields to the Step 2 advanced summary sheet:

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

Also add run-level summary rows for:

- number of features skipped as `no_drift_detected`
- median outlier removal count
- median clamp ratio
- fraction of features using edge extrapolation

## Part B: Step 4 pause / deprecation plan

### B1. Pause Step 4 scaling math in the active workflow

**Change**

- remove Step 4 from the default scientific workflow
- or gate it behind an explicit `experimental` / `paused` mode
- update GUI and README wording so users do not read it as recommended cross-batch normalization

### B2. Preserve diagnostics where useful

Keep the diagnostic plots and helpers that are still informative:

- residual analysis
- batch boxplots
- QC alignment diagnostics

But relabel them as diagnostics only, not as proof of valid correction.

### B3. Update workflow messaging

README and GUI text should say clearly:

- Step 4 is paused because shared-QC comparability across batches is not guaranteed in the current experimental design
- users should not interpret Step 4 scaling output as validated cross-batch correction

## Concrete Code Touch Points

### Step 2 files

Primary implementation file:

- `src/metabolomics/processors/qc_lowess.py`

Likely change areas:

- `apply_lowess_correction(...)`
- `perform_lowess_normalization(...)`
- advanced summary generation
- status aggregation and plotting summaries

Recommended helper additions:

- `filter_qc_outliers_iqr(...)`
- `detect_drift_strength(...)`
- `clamp_correction_factors(...)`
- optional `evaluate_outside_range_usage(...)`

### Step 4 files

Primary implementation file:

- `src/metabolomics/processors/qc_batch_scaling.py`

Likely change areas:

- `main(...)` gating / pause behavior
- output messaging and summary wording
- plot titles / captions where necessary

### Documentation files to update later

- `README.md`
- `docs/algorithms/qc_lowess.md`
- `docs/algorithms/normalization.md`

## Testing Plan

### Unit tests to add or revise

For `qc_lowess.py`:

1. IQR outlier filtering removes an extreme QC point only when keep-count thresholds are still satisfied.
2. IQR filtering leaves data unchanged when removal would leave too few QC points.
3. weak-trend data returns `no_drift_detected` and preserves original intensities.
4. strong-drift data still corrects successfully.
5. factor clamp applies and reports `clamped_ratio`.
6. outside-range sample counting works when non-QC samples exceed the QC order span.
7. batch-local target is used even when multiple batches exist.
8. no cross-batch `global_qc_median` alignment remains in the active path.

For `qc_batch_scaling.py`:

1. Step 4 default entry point returns a paused / skipped result, or is hidden from the active workflow.
2. diagnostic plotting helpers can still run when explicitly requested.
3. workflow text no longer claims validated cross-batch correction.

### Integration tests to add or revise

1. `mixed_direction_batch_drift`
   - Step 2 flattens within-batch drift
   - Step 2 does not intentionally force batch medians together

2. `order_confounding`
   - Step 2 does not aggressively rewrite stable features with weak drift evidence
   - biological structure remains observable after Step 2

3. paused Step 4 path
   - workflow no longer depends on `QC_Batch_Scaling_result` as an endorsed normalization output

## Suggested Implementation Order

1. refactor Step 2 target selection to batch-local only
2. add IQR outlier filtering helper and tests
3. add no-drift gate and tests
4. add factor clamp and reporting
5. add edge-usage reporting
6. update Step 2 summary sheets and run-level reporting
7. pause Step 4 in workflow entry points and messaging
8. update README and algorithm docs

## Risks

- tightening Step 2 may reduce apparent improvement on some historical datasets because weak features will now stay unchanged rather than being lightly smoothed
- tests that currently assume every eligible feature is corrected may need to be rewritten around `skip` behavior
- disabling Step 4 in the active workflow can surface stale assumptions in downstream file-selection logic and GUI labels

## Success Criteria

- Step 2 is clearly batch-local and no longer acts like cross-batch alignment
- Step 2 documentation and implementation agree on outlier handling, skip logic, and factor limits
- Step 4 is no longer presented as a validated active normalization step
- DNP workflow language becomes consistent with the scientific boundary defined in `2026-04-23-dnp-workflow-responsibility-spec.md`
