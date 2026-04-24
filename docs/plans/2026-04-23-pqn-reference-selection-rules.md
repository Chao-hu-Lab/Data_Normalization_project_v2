# PQN Reference Selection Rules

**Date**

- 2026-04-23

**Purpose**

This document defines how DNP should choose the `PQN` reference spectrum under different data structures and QC designs.

It is intentionally operational. The goal is to avoid silent misuse of QC-derived PQN references when batch structure or QC design makes them scientifically unreliable.

## 2026-04-24 Adductomics Policy Update

After review with the project PI, DNP currently targets adductomics-oriented trace analysis rather than endogenous metabolomics. Because all-sample robust median references can be dominated by sparse, low-abundance, exposure-driven features, Step 3 no longer falls back to all samples.

Current operational rule:

- if QC samples exist, build PQN reference from QC samples
- Step 2 `LOESS_summary`, QC stability, and batch sharedness remain report context
- if QC samples do not exist, stop with an explicit error
- do not use all-sample robust median as an automatic fallback

## Core Principle

`PQN` is a **sample-wise dilution / scaling normalization** method, not a batch-correction method.

Therefore:

- the PQN reference should be chosen to stabilize sample scaling
- the PQN reference should not be used to perform implicit cross-batch harmonization
- QC-derived references are only appropriate when the QC design makes the reference scientifically comparable

## Decision Table

| Scenario | QC design | Recommended PQN reference | QC allowed in reference? | Confidence | Notes |
|----------|-----------|---------------------------|--------------------------|------------|-------|
| single-batch raw matrix | one batch, regular pooled QC inserts | **QC-based reference with warning** | yes | medium | raw QC may still carry strong run-order drift |
| single-batch after QC-LOESS | one batch, regular pooled QC inserts | **QC-based reference** | yes | high | Step 2 stability is report context |
| single-batch after QC-LOESS but QC still unstable | one batch, pooled QC exists but remains noisy | **QC-based reference with warning** | yes | medium | adductomics policy disables all-sample fallback |
| cross-batch merged matrix with truly shared QC | same QC material spans all batches | **QC-based global reference** | yes | medium | report sharedness evidence; do not call this batch correction |
| cross-batch merged matrix with non-shared QC | each batch has its own pooled QC | **QC-based reference with warning** | yes | medium | all-sample fallback is disabled; report non-shared QC risk |
| no QC samples | no usable QC reference | **stop with error** | no | high | do not build all-sample robust median reference |

## Detailed Rules

### Rule 1: Single-batch raw matrix

If the data contains only one batch and QC injections are distributed across run order, QC is still the PQN reference source in the current adductomics workflow.

Recommended handling:

- first inspect QC drift evidence
- prefer `ISTD` if applicable, then `QC-LOESS`, then `PQN`
- if QC drift remains visible, report it as a warning instead of switching to all-sample reference

### Rule 2: Single-batch after QC-LOESS

This is the preferred case for QC-based PQN.

Use a QC-derived PQN reference when all of the following are broadly true:

- QC count is adequate for the batch
- QC injections span the run reasonably well
- post-LOESS QC order trend is materially reduced
- post-LOESS QC CV distribution is clearly improved relative to raw data
- QC spectra remain mutually similar

Recommended default:

- use the batch QC median spectrum as PQN reference

### Rule 3: Single-batch after QC-LOESS but QC remains unstable

For the current adductomics workflow, QC instability after LOESS is a reporting warning, not a trigger for all-sample fallback.

Use:

- QC median spectrum as the PQN reference
- Step 2 stability fields in the summary report to warn the user
- no automatic all-sample robust median fallback

### Rule 4: Cross-batch merged matrix with truly shared QC

If every batch uses the same shared QC material and that shared QC is scientifically comparable across all batches, then a global QC-derived PQN reference can be considered.

Even in this case:

- PQN is still not the main batch-correction method
- PQN should not be used as a substitute for explicit batch modeling when batch offsets are substantial

### Rule 5: Cross-batch merged matrix with non-shared QC

If each batch uses its own pooled QC and those QCs are not truly shared across batches, report the design risk explicitly.

Current adductomics policy still uses the available QC samples as the PQN reference because all-sample robust median is considered scientifically inappropriate for trace adductomics features. This must be described as a normalization reference choice, not as cross-batch correction.

## Recommended Reference Strategies by Workflow State

| Workflow state | Reference choice |
|----------------|------------------|
| Step 2 not run yet, single batch | QC median spectrum with warning |
| Step 2 complete, single batch, QC improved | QC median spectrum |
| Step 2 complete, single batch, QC still unstable | QC median spectrum with warning |
| merged multi-batch, non-shared QC | QC median spectrum with warning |
| merged multi-batch, shared QC proven | QC median spectrum |

## DNP-Specific Policy

For DNP, use the following default policy:

1. **Single-batch workflow**
   - preferred sequence: `ISTD -> QC-LOESS -> PQN`
   - PQN reference: `QC-based median spectrum`
   - unstable QC remains a report warning, not an all-sample fallback trigger

2. **Cross-batch merged workflow with non-shared QC**
   - use available QC samples as the PQN reference
   - report non-shared QC risk explicitly
   - do not describe PQN as cross-batch correction

## Current Example-Based Interpretation

### Example A: single-batch workbook after LOESS

For the workbook:

- `C:\Users\user\Desktop\NTU cancer\Processed Data\DNA\Mzmine\new_test\run_20260422_225633\Step2_QC_LOESS.xlsx`

Observed pattern:

- QC count is adequate
- QC insert spacing is regular
- LOESS materially reduces QC CV
- QC order correlation becomes much weaker after LOESS
- post-LOESS QC is improved enough to make QC-based PQN a reasonable candidate

Interpretation:

- QC-based PQN is allowed
- if post-LOESS QC CV remains around the caution band, report it as a warning rather than switching to all-sample robust median

### Example B: cross-batch merged workbook with non-shared QC

For the workbook:

- `C:\Users\user\Desktop\NTU cancer\Processed Data\DNA\Mzmine\new_test\crossbatch\STEP4_cross_batch_merged_20260423_134355.xlsx`

Observed pattern:

- QC is not shared across batches
- batch QC counts are unbalanced
- QC spectra are only moderately aligned across batches
- global QC reference would be dominated by one batch's QC structure

Interpretation:

- use available QC samples as the PQN reference
- report that QC is non-shared and that this is not cross-batch correction

## Implementation Guidance for DNP

When Step 3 chooses a PQN reference strategy, the decision logic should inspect at least:

- number of unique batches
- whether QC is scientifically shared across batches
- post-LOESS QC stability metrics when Step 2 output exists
- whether QC counts are balanced enough to support a global QC reference

A future implementation can encode this with explicit strategy labels such as:

- `QC_REFERENCE`
- `QC_REFERENCE_WITH_WARNING`
- `QC_REQUIRED_BUT_MISSING`

## Bottom Line

- `single-batch + LOESS-corrected QC -> QC-based PQN`
- `cross-batch merged + non-shared QC -> QC-based PQN with explicit warning`
- `missing QC -> stop; do not use all-sample reference`
- `PQN` should never be allowed to become an accidental substitute for explicit batch correction
