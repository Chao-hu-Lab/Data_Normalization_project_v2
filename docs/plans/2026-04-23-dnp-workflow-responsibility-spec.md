# DNP Workflow Responsibility Spec

**Date**

- 2026-04-23

**Status**

- Implemented on `refactor/dnp-workflow-responsibility-core-overhaul` as of 2026-04-25.
- Treat this as the design rationale for the current boundary, not as an open implementation TODO.

**Context**

`Data_Normalization_project_v2` (DNP) should focus on normalization and within-batch technical stabilization. Cross-batch statistical alignment is no longer part of DNP's active responsibility boundary.

This document was written before the responsibility refactor landed. The current branch now implements the intended boundaries:

- Step 2 `QC-LOESS` uses batch-local LOWESS targets and reports advanced per-feature status in `LOESS_summary`.
- Step 3 exposes `PQN` (default) and explicit `SpecNorm` as alternative
  specimen-aware estimands. The legacy `SpecNorm+PQN` hybrid remains
  compatibility-only and is not an active GUI/default method.
- Step 4 `QC Batch Scaling` is paused for active scientific correction and remains available only through explicit diagnostics-only execution.

This document defines the intended responsibility boundary for each active DNP step.

## High-Level Workflow Boundary

| Step | Name | Primary purpose | Allowed to use QC? | Batch-aware? | Should do cross-batch alignment? |
|------|------|-----------------|--------------------|--------------|----------------------------------|
| 1 | ISTD Monitoring / Selective Correction | monitor internal standards and apply only validated analyte-to-ISTD mappings; the current broad auto-matcher is legacy compatibility | yes | no | no |
| 2 | QC-LOESS | correct within-batch run-order drift using QC anchors | yes | yes | no |
| 3 | Concentration Normalization (`PQN` / `SpecNorm`) | correct sample-wise dilution or divide by an explicit specimen-reference measurement, depending on the selected estimand | yes, but only for PQN reference construction and QC evaluation | optional metadata-aware, not batch-correction-aware | no |
| 4 | QC Batch Diagnostics | inspect residual batch/QC behavior without applying active cross-batch scaling | yes | yes | no |

## Intended Responsibility by Step

### Step 1: ISTD Monitoring / Selective Correction

**Responsible for**

- monitoring ISTD missingness, RT, area, and run-order stability
- correcting an analyte only when an explicit matched or separately validated
  surrogate mapping exists
- preserving run-order and batch structure for later steps

**Not responsible for**

- drift correction over injection order
- cross-batch alignment
- biological-group preservation logic
- assigning every unknown feature to a nearest-RT or score-selected ISTD

**Operational notes**

- Broad untargeted/adductomics runs should skip the legacy universal auto-match
  path when no validated feature-level mapping exists.
- Step 1 may also be skipped when ISTD quality is insufficient.
- Step 2 must remain valid when Step 1 output is unavailable.

### Step 2: QC-LOESS

**Responsible for**

- modeling signal drift as a function of `Injection_Order`
- fitting one drift curve per feature per batch
- using batch-local QC samples as time anchors
- correcting within-batch drift without changing cross-batch location/scale on purpose

**Must do**

- parse `SampleInfo.Batch` and split data into batch-local correction tasks
- fit LOWESS independently inside each batch
- define the correction target from batch-local QC behavior, not from a cross-batch pooled target
- leave features unchanged when drift evidence is too weak or QC support is inadequate

**Must not do**

- combine all batches into one run-order curve
- use QC-LOESS to force different batches onto a shared absolute QC level
- behave like a batch-effect alignment tool

**Practical interpretation**

Step 2 is valid even when each batch has its own pooled QC material, because the method only assumes that QC samples are internally comparable within a batch over time.

### Step 3: Concentration Normalization (`PQN` / `SpecNorm`)

**Responsible for**

- selecting one declared sample-wise dilution/concentration estimand
- building a robust sample-scaling reference spectrum for `PQN`
- dividing real samples by an explicit trusted specimen-reference measurement
  for `SpecNorm`

**Current behavior in code**

- `SpecNorm` divides only real samples by a per-sample reference value from `SampleInfo`.
- QC samples are excluded from the `SpecNorm` division stage.
- `PQN` uses a QC-derived reference when QC samples exist.
- `PQN` is the default method; `SpecNorm` is an explicit alternative rather
  than an automatically chained preprocessing stage.
- Legacy `SpecNorm+PQN` aliases remain programmatically accepted for
  compatibility, but are not an active GUI/default method.
- If QC samples are missing, Step 3 stops with an explicit error; the all-sample robust median fallback is disabled for adductomics.

**Must not do**

- act as a replacement for batch correction
- assume that QC use in PQN means batch-aware correction
- perform explicit cross-batch harmonization

**Design interpretation**

Step 3 can remain global if the reference spectrum is intended to capture dilution structure rather than batch structure. However, if QC composition differs materially by batch, a global QC-derived PQN reference may import batch bias into the reference spectrum. That risk should be evaluated explicitly rather than silently treated as batch correction.

### Step 4: QC Batch Diagnostics

**Current status**

- diagnostics-only; paused for active scientific scaling

**Reason**

The current method assumes that per-batch QC medians are comparable across batches and can therefore be used as cross-batch anchors. That assumption is not valid when each batch uses its own QC material rather than one shared QC source.

**Conclusion**

- Step 4 should not be treated as an active normalization step for scientific reporting.
- Its diagnostics remain useful, but its scaling math should be considered suspended unless the experiment uses a truly shared QC reference across batches.

## Responsibility Table: Methods vs Bias Types

| Bias type | Step 1 ISTD | Step 2 QC-LOESS | Step 3 PQN / SpecNorm | Step 4 QC Batch Diagnostics |
|-----------|-------------|-----------------|---------------------------|-------------------------|
| sample-specific matrix effect | only for validated matched/selective correction | no | sometimes indirect | no |
| within-batch run-order drift | no | yes | no | no |
| dilution / concentration scaling | no | no | yes | no |
| cross-batch location/scale offset | no | no by design | no | diagnostics only |
| confounded biological-vs-batch structure | no | no | no | no |

## Active Design Rules

1. DNP should remain responsible for **within-batch technical stabilization**, not for cross-batch statistical harmonization.
2. Step 2 should stay in DNP, but only as a **batch-local QC drift correction** method.
3. Step 3 should stay in DNP as a **concentration normalization** step, not a batch module.
4. Step 4 should be **disabled or clearly labeled experimental / paused** until shared-QC assumptions are actually satisfied.
5. Cross-batch model-based correction such as `ComBat` belongs outside DNP's active normalization boundary.

## Implementation Outcome

- Active workflow dependence on Step 4 scaling output has been removed.
- Step 4 diagnostic plots are retained behind explicit diagnostics-only execution.
- Step 2 correction targets are batch-local.
- Step 3 reporting states which PQN reference strategy was used and warns that QC use does not imply batch correction.

## Documentation Contract

- README workflow description should mark Step 4 as paused / diagnostics-only.
- Step 2 docs should describe QC-LOESS as batch-local drift correction only.
- Step 3 docs should clarify that QC use in PQN does not imply batch-aware correction.
- Any legacy language that implies DNP performs mature cross-batch correction should remain archived or be removed from active docs.
