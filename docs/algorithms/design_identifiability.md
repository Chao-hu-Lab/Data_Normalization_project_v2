# Design identifiability receipt

## Responsibility

This module answers whether the observed metadata support a proposed
biological or technical interpretation. It does not correct intensities,
remove samples, run ComBat, or authorize cross-batch scaling.

The receipt is calculated from the sample columns actually present in the
active matrix. Extra rows in `SampleInfo`, including mixed samples that are not
part of the matrix, do not enter the diagnostics.

## Required and optional metadata

Required for a complete receipt:

- `Sample_Name`
- `Sample_Type`
- `Batch`
- `Injection_Order`

Missing or invalid `Injection_Order` makes order-based evidence
`non_identifiable`; the receipt itself remains available. Step 2 separately
requires valid order metadata before performing drift correction.

Optional typed metadata:

- `Pair_ID`
- `Bridge_ID`
- `QC_Pool_ID`

Missing optional fields return `not_available`. DNP does not infer them from
sample names.

## Reported evidence

- sample counts by `Batch × Sample_Type`;
- scheduled QC count and whether QC injections bracket study samples in each
  batch;
- categorical eta-squared for `Sample_Type → Injection_Order` and
  `Batch → Injection_Order`;
- Cramér's V for `Sample_Type ↔ Batch`;
- rank, condition number, leverage, empty cells, and estimability of the
  `Batch × Sample_Type` interaction design;
- support for each observed pairwise sample-type contrast;
- optional pair, bridge, and pooled-QC coverage.

QC rows may declare semicolon-separated batch membership. Those rows are
expanded into the declared batches for scheduled-QC diagnostics; biological
samples may belong to only one batch.

## Status semantics

- `supported`: the declared scope has direct support in the observed design.
- `assumption_dependent`: limited within-batch support exists, but extending it
  to every batch or a universal effect requires assumptions.
- `non_identifiable`: the requested effect cannot be separated from the
  observed design or required metadata are unavailable.

A contrast found in only one common batch is never promoted to a universal
cross-batch effect. Even with full-rank numerical execution, a strong declared
`Sample_Type → Injection_Order` association makes the corresponding biological
contrast assumption-dependent. A shared `QC_Pool_ID` is at most
assumption-dependent evidence; different pool IDs are non-comparable.

Typed `Bridge_ID` values are evaluated as a graph over observed batches.
Global cross-batch level alignment is supported only when the bridge graph
covers and connects every observed batch. A bridge covering only A and B does
not provide evidence for an unconnected batch C, and no bridge automatically
applies a correction.

## Handoff

Step 2 exposes the receipt through
`ProcessingResult.extra["design_identifiability"]` and writes it when Step 2
produces a workbook. Step 3 recalculates the receipt and always writes the
canonical `Design_Identifiability` sheet to the active normalized workbook.
