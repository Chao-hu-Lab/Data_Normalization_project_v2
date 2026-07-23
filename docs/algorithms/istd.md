# ISTD Correction Contract

## Current status

Step 1 has two different realities that must not be conflated:

1. The current processor can discover red-font ISTD rows, gate them by QC
   stability, automatically match every non-ISTD feature to one ISTD using
   RT/CV/intensity/mass weights, and apply a ratio correction.
2. That universal auto-matching behavior is legacy compatibility code. It is
   not a scientifically validated default for broad untargeted DNA
   adductomics, where a small set of spiked ISTDs is asked to represent
   hundreds of structurally unknown features.

For the current broad adductomics workflow, Step 1 should default to `SKIP`.
Skipping is a complete, explicit method decision; Step 2 can consume
`RawIntensity` directly.

The evidence and method review supporting this boundary lives in
[`2026-07-23-istd-and-batch-identifiability-review.md`](../discussions/2026-07-23-istd-and-batch-identifiability-review.md).

## Supported scientific roles

### ISTD monitoring

ISTD rows may be used to report:

- missingness and detection coverage;
- QC CV and robust CV;
- area behavior across injection order;
- RT stability, saturation, and peak-quality alarms;
- samples or run regions that require raw-data review.

Monitoring does not modify unknown-feature intensities.

### Matched analyte correction

An analyte may be corrected using an ISTD only when an explicit mapping exists
and its scope is known. A defensible mapping normally requires a matched
stable-isotope-labelled analyte, or separately validated evidence that a
surrogate shares the relevant recovery and matrix-response behavior.

The mapping and output must preserve feature-level provenance:

- analyte feature ID;
- ISTD feature ID;
- mapping type (`matched` or `validated_surrogate`);
- validation reference;
- correction status and rejection reason.

Known targeted analytes that require concentration claims belong in a
targeted/XIC assay with calibration and validation. An ISTD ratio alone does
not create a concentration.

### Abstention

When no validated mapping exists, retain the original value and record an
explicit uncorrected/skip state. Do not silently select the nearest RT ISTD or
the ISTD that makes training-QC CV look best.

## Legacy processor behavior

`src/metabolomics/processors/istd.py` currently:

- identifies ISTDs from red font in the first `RawIntensity` column;
- requires `RawIntensity`, `SampleInfo`, QC samples, and usable `Batch`
  metadata;
- skips when fewer than five ISTDs pass its QC-CV gate;
- scores candidate ISTDs using RT, QC CV, intensity, and m/z;
- applies
  `corrected = original × ISTD_median / sample_ISTD`;
- emits diagnostic plots and before/after QC summaries.

These gates can reject obviously weak ISTDs, but they do not prove that the
remaining ISTD is a valid surrogate for an unknown feature. The automatic
matching path must therefore not be described as the recommended broad
untargeted method.

Replacement of this legacy behavior should be implemented as a focused,
testable change rather than gradually adding more score weights or
exceptions.

## Input contract

The workbook must contain:

- `RawIntensity`: feature IDs in the first column and sample intensity columns;
- `SampleInfo`: `Sample_Name`, `Sample_Type`, and complete `Batch` metadata for
  the current processor;
- QC samples when Step 1 correction gates or QC diagnostics are requested.

Red font remains a legacy ISTD-role marker. A future canonical XIC handoff
should supply typed feature roles and explicit mappings so DNP does not
rediscover identity from formatting.

Missing intensities must remain missing at this stage. Do not impute values to
create ISTD or QC anchors.

## Output and workflow behavior

- `SKIPPED` must preserve the input matrix for downstream Step 2 and provide an
  actionable reason.
- A future selective implementation may return a mixed matrix containing
  matched-corrected and uncorrected features, but only with feature-level
  status/provenance.
- Step 1 output must not be interpreted as cross-batch harmonization.
- Improved training-QC CV or a visually tighter PCA is not sufficient
  validation of a surrogate correction.

## Interpretation guardrails

Do not claim that:

- one or several non-matched ISTDs provide a universal matrix-wide correction;
- RT proximity implies shared recovery or ion-suppression response;
- a generic ISTD correction resolves sample-type/injection-order confounding;
- agreement between two integrations proves biological correctness.

ISTDs can show that order-associated technical behavior exists. They cannot,
without analyte-specific response evidence and an identifiable study design,
assign an observed group difference uniquely to biology or instrument drift.

## Related contracts

- [QC-LOWESS](qc_lowess.md): feature-wise batch-local run-order correction.
- [Normalization](normalization.md): PQN and specimen-reference normalization.
- [ComBat archive](combat.md): cross-batch model correction is outside the
  active DNP workflow.
- [XIC handoff issue](https://github.com/Chao-hu-Lab/Data_Normalization_project_v2/issues/32):
  typed roles, cell states, and pre/post-correction quality ownership.
- [Matched-only Step 1 issue](https://github.com/Chao-hu-Lab/Data_Normalization_project_v2/issues/33):
  replace universal auto-matching with monitoring, selective correction, and
  abstention states.
