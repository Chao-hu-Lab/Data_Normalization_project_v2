# ISTD Correction Contract

## Current status

Step 1 defaults to ISTD monitoring plus selective, mapping-gated correction:

1. Red-font ISTD rows are monitored for missingness, QC CV, and area/order
   association.
2. An analyte is corrected only when `ISTD_Mapping` explicitly assigns a
   `matched` or `validated_surrogate` donor with a validation reference and
   the donor passes feature-level quality checks.
3. Unmapped or rejected features retain their original values and missingness
   state, with an explicit status and reason.

The universal RT/CV/intensity/mass auto-matcher remains available only through
the programmatic `legacy_auto_match=True` compatibility flag. It is not the
GUI default and cannot be combined with `ISTD_Mapping`.

The evidence and method review supporting this boundary lives in
[`2026-07-23-istd-and-batch-identifiability-review.md`](../discussions/2026-07-23-istd-and-batch-identifiability-review.md).

## Supported scientific roles

### ISTD monitoring

ISTD rows may be used to report:

- missingness and detection coverage;
- QC CV and robust CV;
- area behavior across injection order;
- RT stability when sample-level RT data are available;
- samples or run regions that require raw-data review.

Monitoring does not modify unknown-feature intensities.
The current matrix contains one static feature RT rather than sample-level RT,
so the monitoring receipt records `not_available_from_current_matrix` instead
of claiming RT stability.
Missing or partial `Injection_Order` is likewise recorded in `Order_Status`;
the processor does not substitute workbook column position or draw an
order-trend plot when the order is incomplete.

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

## Correction rule and rejection gates

Accepted mappings apply:

`corrected = original × ISTD_median / sample_ISTD`

The entire analyte feature remains raw when:

- no explicit mapping exists;
- a surrogate lacks a validation reference;
- the donor's QC CV is not below 20%;
- the donor is missing or non-positive wherever that analyte is observed.

The last rule prevents a single output feature from switching estimands across
samples or acquiring new missing values because of correction.

## Input contract

The workbook must contain:

- `RawIntensity`: feature IDs in the first column and sample intensity columns;
- `SampleInfo`: `Sample_Name`, `Sample_Type`, and complete `Batch` metadata for
  the current processor;
- QC samples when Step 1 correction gates or QC diagnostics are requested.
- optional `ISTD_Mapping`, with one row per analyte and the columns
  `Analyte_Feature_ID`, `ISTD_Feature_ID`, `Mapping_Type`, and
  `Validation_Reference`.

Red font remains a legacy ISTD-role marker. A future canonical XIC handoff
should supply typed feature roles and explicit mappings so DNP does not
rediscover identity from formatting.

Missing intensities must remain missing at this stage. Do not impute values to
create ISTD or QC anchors.

## Output and workflow behavior

- With no detected ISTD, `SKIPPED` preserves the input workbook for Step 2 and
  reports `no_istd_detected`.
- With ISTDs but no accepted mappings, Step 1 succeeds in `monitoring_only`
  mode and writes an analyte matrix identical to raw input.
- A selective result may mix corrected and uncorrected features only because
  each row carries `Mapped_ISTD`, `Mapping_Type`, `Validation_Reference`,
  `ISTD_Correction_Status`, and `ISTD_Correction_Reason`.
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
