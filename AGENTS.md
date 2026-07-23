# Data Normalization Project Contract

## Authority Routing

- Active workflow boundary: `README.md`.
- Step 1 scientific contract and legacy implementation status:
  `docs/algorithms/istd.md`.
- Step 2 feature-wise QC correction contract:
  `docs/algorithms/qc_lowess.md`.
- Design-identifiability receipt contract:
  `docs/algorithms/design_identifiability.md`.
- Step 3 specimen-aware normalization contract:
  `docs/algorithms/normalization.md`.
- Cross-batch correction boundary: `docs/algorithms/combat.md`.
- ISTD and batch-identifiability evidence review:
  `docs/discussions/2026-07-23-istd-and-batch-identifiability-review.md`.

Do not copy the full method rationale into this file. Update the authoritative
document and keep this file as a router plus guardrails.

## Scientific Guardrails

- Broad untargeted/adductomics runs must not treat the legacy RT/CV-weighted
  ISTD auto-matcher as a validated universal correction. Default to
  monitoring-only output; correct only features with an explicit
  analyte-to-ISTD mapping and validation reference. Step 1 is `SKIPPED` only
  when the input contains no ISTD.
- ISTD monitoring, matched analyte correction, validated surrogate correction,
  and abstention are different states. Outputs and tests must not collapse them
  into one generic "ISTD corrected" state.
- Step 2 is batch-local, feature-wise run-order correction. It does not perform
  cross-batch harmonization. Missing QC or invalid `Batch` /
  `Injection_Order` metadata must fail closed with an actionable reason.
- Effective QC count and endpoint coverage are feature-level properties:
  6-7 valid QC may enter the gated log-linear fallback; at least 8 may enter
  LOWESS; insufficient or rejected features retain their original values and
  an explicit decision status.
- Step 4 is diagnostics-only. Do not reactivate QC median batch scaling or
  ComBat as an automatic correction path without a new, validated product
  contract.
- A highly associated sample type, batch, and injection order is an
  identifiability warning. Correction software cannot turn a confounded design
  into independent biological and technical effects.

## Test And Artifact Boundaries

- Repository datasets are synthetic fixtures, not real study data. Correction
  fixtures must preserve missing values until the correction stage, include
  endpoint QC where the scenario requires it, and declare every simulated
  technical and biological effect.
- Generated matrices, plots, real-workbook diagnostics, and throwaway
  prototypes belong under `build/` or explicit local Git excludes. Do not
  commit private research workbooks or one-off diagnostic scripts.
- Validate scientific behavior, not only successful execution: inspect
  feature-level routing, correction acceptance/rejection, endpoint behavior,
  ground-truth recovery where available, and raw-versus-corrected sensitivity.
