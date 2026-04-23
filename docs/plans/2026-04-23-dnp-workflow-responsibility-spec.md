# DNP Workflow Responsibility Spec

**Date**

- 2026-04-23

**Context**

`Data_Normalization_project_v2` (DNP) should focus on normalization and within-batch technical stabilization. Cross-batch statistical alignment is no longer part of DNP's active responsibility boundary.

The current codebase still contains behaviors that blur these boundaries:

- Step 2 `QC-LOESS` is already batch-wise in its LOWESS fitting path, but it can still use a cross-batch `global_qc_median` target.
- Step 3 `SpecNorm+PQN` uses QC samples when building a PQN reference spectrum, but it is not a batch-correction module.
- Step 4 `QC Batch Scaling` performs cross-batch alignment using per-batch QC medians, which is not theoretically valid when each batch uses its own pooled QC material rather than a shared QC reference.

This document defines the intended responsibility boundary for each active DNP step.

## High-Level Workflow Boundary

| Step | Name | Primary purpose | Allowed to use QC? | Batch-aware? | Should do cross-batch alignment? |
|------|------|-----------------|--------------------|--------------|----------------------------------|
| 1 | ISTD Correction | correct sample-level ionization / matrix effects using internal standards | yes | no | no |
| 2 | QC-LOESS | correct within-batch run-order drift using QC anchors | yes | yes | no |
| 3 | Concentration Normalization (`PQN` / `SpecNorm+PQN`) | correct sample-wise dilution / concentration scaling | yes, but only for PQN reference construction and QC evaluation | optional metadata-aware, not batch-correction-aware | no |
| 4 | QC Batch Scaling | cross-batch QC-median alignment | yes | yes | yes, but currently deprecated / paused |

## Intended Responsibility by Step

### Step 1: ISTD Correction

**Responsible for**

- correcting analyte intensity using internal-standard relationships
- reducing sample-specific matrix and ionization artifacts
- preserving run-order and batch structure for later steps

**Not responsible for**

- drift correction over injection order
- cross-batch alignment
- biological-group preservation logic

**Operational notes**

- Step 1 may be skipped when ISTD quality is insufficient.
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

### Step 3: Concentration Normalization (`PQN` / `SpecNorm+PQN`)

**Responsible for**

- correcting sample-wise dilution / concentration differences
- building a robust sample-scaling reference spectrum
- optionally dividing real samples by a per-sample reference column such as `Creatinine_mg_dL`

**Current behavior in code**

- `SpecNorm` divides only real samples by a per-sample reference value from `SampleInfo`.
- QC samples are excluded from the `SpecNorm` division stage.
- `PQN` currently prefers a QC-derived global reference spectrum when QC quality is acceptable; otherwise it falls back to a global median reference.

**Must not do**

- act as a replacement for batch correction
- assume that QC use in PQN means batch-aware correction
- perform explicit cross-batch harmonization

**Design interpretation**

Step 3 can remain global if the reference spectrum is intended to capture dilution structure rather than batch structure. However, if QC composition differs materially by batch, a global QC-derived PQN reference may import batch bias into the reference spectrum. That risk should be evaluated explicitly rather than silently treated as batch correction.

### Step 4: QC Batch Scaling

**Current status**

- paused / deprecated for active scientific use

**Reason**

The current method assumes that per-batch QC medians are comparable across batches and can therefore be used as cross-batch anchors. That assumption is not valid when each batch uses its own QC material rather than one shared QC source.

**Conclusion**

- Step 4 should not be treated as an active normalization step for scientific reporting.
- Its diagnostics remain useful, but its scaling math should be considered suspended unless the experiment uses a truly shared QC reference across batches.

## Responsibility Table: Methods vs Bias Types

| Bias type | Step 1 ISTD | Step 2 QC-LOESS | Step 3 PQN / SpecNorm+PQN | Step 4 QC Batch Scaling |
|-----------|-------------|-----------------|---------------------------|-------------------------|
| sample-specific matrix effect | yes | no | sometimes indirect | no |
| within-batch run-order drift | no | yes | no | no |
| dilution / concentration scaling | no | no | yes | no |
| cross-batch location/scale offset | no | no by design | no | yes, but paused |
| confounded biological-vs-batch structure | no | no | no | no |

## Active Design Rules

1. DNP should remain responsible for **within-batch technical stabilization**, not for cross-batch statistical harmonization.
2. Step 2 should stay in DNP, but only as a **batch-local QC drift correction** method.
3. Step 3 should stay in DNP as a **concentration normalization** step, not a batch module.
4. Step 4 should be **disabled or clearly labeled experimental / paused** until shared-QC assumptions are actually satisfied.
5. Cross-batch model-based correction such as `ComBat` belongs outside DNP's active normalization boundary.

## Immediate Consequences for the Codebase

- Remove or disable active workflow dependence on Step 4 scaling outputs.
- Retain Step 4 diagnostic plots only if they are relabeled as diagnostics rather than normalization proof.
- Refactor Step 2 so its correction target is batch-local instead of global.
- Clarify in Step 3 reporting that `SpecNorm+PQN` is not a batch-correction stage.

## Documentation Updates Required

- README workflow description should mark Step 4 as paused / deprecated.
- Step 2 docs should describe QC-LOESS as batch-local drift correction only.
- Step 3 docs should clarify that QC use in PQN does not imply batch-aware correction.
- Any legacy language that implies DNP performs mature cross-batch correction should be removed.
