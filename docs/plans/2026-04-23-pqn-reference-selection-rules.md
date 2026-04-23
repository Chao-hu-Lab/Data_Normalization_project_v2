# PQN Reference Selection Rules

**Date**

- 2026-04-23

**Purpose**

This document defines how DNP should choose the `PQN` reference spectrum under different data structures and QC designs.

It is intentionally operational. The goal is to avoid silent misuse of QC-derived PQN references when batch structure or QC design makes them scientifically unreliable.

## Core Principle

`PQN` is a **sample-wise dilution / scaling normalization** method, not a batch-correction method.

Therefore:

- the PQN reference should be chosen to stabilize sample scaling
- the PQN reference should not be used to perform implicit cross-batch harmonization
- QC-derived references are only appropriate when the QC design makes the reference scientifically comparable

## Decision Table

| Scenario | QC design | Recommended PQN reference | QC allowed in reference? | Confidence | Notes |
|----------|-----------|---------------------------|--------------------------|------------|-------|
| single-batch raw matrix | one batch, regular pooled QC inserts | **not default**; prefer QC only after drift review | conditional | medium | raw QC may still carry strong run-order drift |
| single-batch after QC-LOESS | one batch, regular pooled QC inserts | **QC-based reference** preferred when QC stability is acceptable | yes | high | best match to DNP's intended single-batch workflow |
| single-batch after QC-LOESS but QC still unstable | one batch, pooled QC exists but remains noisy | **real-sample robust median** | no, or QC as secondary sensitivity run only | medium | keep QC out of the main reference if post-LOESS QC dispersion is still high |
| cross-batch merged matrix with truly shared QC | same QC material spans all batches | **QC-based global reference** can be considered | yes | medium | only valid when QC is genuinely comparable across batches |
| cross-batch merged matrix with non-shared QC | each batch has its own pooled QC | **real-sample robust median** | no | high | do not let batch-specific QC define a global PQN reference |
| cross-batch merged matrix with non-shared QC but strong desire to retain QC information | each batch has its own pooled QC | **real-sample robust median** as primary; optional batch-equalized QC sensitivity analysis only | not in primary workflow | medium | any QC-based merged reference must be treated as exploratory, not default |

## Detailed Rules

### Rule 1: Single-batch raw matrix

If the data contains only one batch and QC injections are distributed across run order, QC can be a candidate PQN reference, but it should not be assumed safe before drift is evaluated.

Recommended handling:

- first inspect QC drift evidence
- if the raw matrix still shows clear order-dependent QC instability, do not build the final PQN reference directly from raw QC
- prefer:
  1. `ISTD` if applicable
  2. `QC-LOESS`
  3. then decide PQN reference

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

If LOESS reduces drift but QC remains too noisy, do not force a QC-derived PQN reference.

Use `real-sample robust median` when any of the following remain concerning after LOESS:

- QC CV median is still high
- too many features worsen after correction
- QC outliers dominate reference construction
- QC sample-level abundance is still visibly unstable

Suggested interpretation bands:

- `post-LOESS QC CV median < 20%`: QC reference strongly supported
- `20% to 30%`: QC reference allowed, but compare against robust-median reference
- `> 30%`: robust-median reference preferred unless there is strong additional evidence that QC remains reliable

These bands are workflow guidance, not rigid statistical laws.

### Rule 4: Cross-batch merged matrix with truly shared QC

If every batch uses the same shared QC material and that shared QC is scientifically comparable across all batches, then a global QC-derived PQN reference can be considered.

Even in this case:

- PQN is still not the main batch-correction method
- PQN should not be used as a substitute for explicit batch modeling when batch offsets are substantial

### Rule 5: Cross-batch merged matrix with non-shared QC

If each batch uses its own pooled QC and those QCs are not truly shared across batches, do **not** use global QC-derived PQN as the default reference.

Use:

- `real-sample robust median reference`

Reason:

- pooled QC from different batches is not a common anchor
- a global QC median can silently encode batch composition into the PQN reference spectrum
- unequal QC counts by batch make the problem worse

This is the default rule for DNP cross-batch merged matrices unless a stronger shared-QC design is explicitly demonstrated.

## Recommended Reference Strategies by Workflow State

| Workflow state | Reference choice |
|----------------|------------------|
| Step 2 not run yet, single batch | provisional QC allowed only after manual review; otherwise robust median |
| Step 2 complete, single batch, QC improved | QC median spectrum |
| Step 2 complete, single batch, QC still unstable | real-sample robust median |
| merged multi-batch, non-shared QC | real-sample robust median |
| merged multi-batch, shared QC proven | QC median spectrum may be used |

## DNP-Specific Policy

For DNP, use the following default policy:

1. **Single-batch workflow**
   - preferred sequence: `ISTD -> QC-LOESS -> PQN`
   - preferred PQN reference after successful LOESS: `QC-based median spectrum`
   - fallback when QC remains unstable: `real-sample robust median`

2. **Cross-batch merged workflow with non-shared QC**
   - do not use global QC-derived PQN as the main workflow default
   - use `real-sample robust median`
   - keep QC for diagnostics and batch-local drift review, not for global PQN anchoring

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
- but if post-LOESS QC CV remains around the caution band, compare it against robust-median PQN as a sensitivity check

### Example B: cross-batch merged workbook with non-shared QC

For the workbook:

- `C:\Users\user\Desktop\NTU cancer\Processed Data\DNA\Mzmine\new_test\crossbatch\STEP4_cross_batch_merged_20260423_134355.xlsx`

Observed pattern:

- QC is not shared across batches
- batch QC counts are unbalanced
- QC spectra are only moderately aligned across batches
- global QC reference would be dominated by one batch's QC structure

Interpretation:

- do not use global QC-derived PQN as default
- use `real-sample robust median` as the main PQN reference

## Implementation Guidance for DNP

When Step 3 chooses a PQN reference strategy, the decision logic should inspect at least:

- number of unique batches
- whether QC is scientifically shared across batches
- post-LOESS QC stability metrics when Step 2 output exists
- whether QC counts are balanced enough to support a global QC reference

A future implementation can encode this with explicit strategy labels such as:

- `QC_SINGLE_BATCH`
- `QC_SHARED_MULTIBATCH`
- `ROBUST_MEDIAN_FALLBACK`
- `ROBUST_MEDIAN_NONSHARED_MULTIBATCH`

## Bottom Line

- `single-batch + LOESS-corrected QC -> QC-based PQN is usually reasonable`
- `cross-batch merged + non-shared QC -> use real-sample robust median`
- `PQN` should never be allowed to become an accidental substitute for explicit batch correction
