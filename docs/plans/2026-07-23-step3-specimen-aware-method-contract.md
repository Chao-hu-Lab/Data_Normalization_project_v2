# Step 3 Specimen-Aware Method Contract

**Status:** Accepted
**Date:** 2026-07-23

## Problem

Step 3 currently presents `SpecNorm+PQN` as the default concentration
normalization even though the current composition is scale-invariant to the
specimen-reference division and produces the same study-sample matrix as PQN
within floating-point tolerance. It also treats the presence of a reference
column as a reason to use the hybrid, which conflates distinct specimen
estimands.

## Decision

The active Step 3 methods are alternatives:

| User choice | Internal method | Intended use | Output estimand |
| --- | --- | --- | --- |
| `PQN — urine dilution` | `PQN` | Urine or another design requiring global sample-wise dilution correction | Intensity divided by the sample PQN factor |
| `SpecNorm — tissue reference` | `SpecNorm` | Tissue or another design with a trusted per-sample reference such as DNA input | Study-sample intensity divided by its specimen reference |

- `PQN` is the safe application default. A creatinine column does not
  automatically select SpecNorm.
- `SpecNorm` is an explicit user choice. Every non-QC study sample must have a
  finite positive reference value. Missing or invalid study references fail the
  step rather than leave some samples uncorrected with incompatible units.
- QC samples are not divided by a specimen reference and remain unchanged by
  the SpecNorm calculation.
- `SpecNorm+PQN` / `SpecNorm_PQN` remain accepted only as legacy programmatic
  aliases for backward compatibility. They are removed from the active GUI
  choices and must be reported as deprecated, not as two independent
  corrections.

## Specimen Policy

- Urine: PQN is the primary post-acquisition dilution-normalization method.
  Creatinine, specific gravity, and osmolality normalization are not
  automatically layered with PQN.
- Tissue DNA adductomics: SpecNorm is the primary method when the intended
  quantity is signal per unit DNA. PQN may be used as a sensitivity analysis,
  not automatically stacked after DNA division.
- Method selection is explicit. Runtime does not infer specimen type from a
  column name.

## Public Surface

- Default method: `PQN`.
- Active GUI values: `PQN`, `SpecNorm`.
- New workbook sheets: `SpecNorm_Result`, `SpecNorm_summary`.
- New session output prefix: `Step3_Normalized_SpecNorm`.
- Existing `PQN_*` and legacy `SpecNorm_PQN_*` names remain readable.

## Verification

Release gates:

1. Shared GUI/processor default and method options match this contract.
2. A worked SpecNorm workbook divides study samples by their references and
   leaves QC values unchanged.
3. SpecNorm fails when any study reference is missing, zero, negative, or
   non-numeric.
4. PQN remains runnable without a specimen-reference column.
5. Legacy hybrid method strings still canonicalize and run for compatibility.

## Non-Goals

- Automatic specimen-type detection.
- Pairing metadata or downstream statistical-model selection.
- Removing legacy workbook-reader support.
- Changing Step 2 QC correction or Step 4 feature filtering.
