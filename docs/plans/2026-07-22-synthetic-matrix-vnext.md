# Synthetic Matrix vNext Execution Plan

## Decision

Replace the current smoke-oriented scenario generator with a small,
truth-bearing scientific simulation model. Fixed composite archetypes represent
realistic joint failure modes; paired perturbations inside an archetype isolate
one tuning variable without pretending real data are one-factor experiments.

This plan does not define or implement downstream imputation. Correction inputs
retain missing values.

## Review outcome

**Approved with conditions** after independent science and execution review.

- Slices A-C may proceed now; Slice D requires the first two evidence loops to
  be diagnostic and reproducible.
- Production processor files remain frozen during this generator work.
- Numerical performance targets remain characterization-only and cannot promote
  a production QC threshold in this plan.
- Missing canonical fixtures fail tests; they are never silently skipped.

### Post-Slice A-C evidence decision

The first production Step 2 characterization on `routine_recoverable`, seed
`51`, produced median technical recovery gain `0.525`, false-correction rate
`0.178`, biology sign-flip rate `0`, and median absolute group fold-change
error `0.025 log2`. These are diagnostic observations, not release claims.

Because false correction remains material even with eight scheduled and valid
QC anchors, this evidence does not justify running LOWESS on six or seven
points. The separate conservative processor boundary therefore remains:
LOWESS requires at least eight effective QC values per batch × feature, while
six-to-seven-point log-linear correction remains explicitly undecided and
unimplemented. Eight points are an eligibility floor, not a guarantee that a
feature will be corrected; all other decision gates still apply.

Slice C also confirms that endpoint-feature loss or post-filter insufficiency
leaves the affected cells unchanged and emits an observable reason. Slice D
archetypes remain future work; they are not required to promote any processor
threshold in this change.

## Problem

The current generator can create complex-looking workbooks, but it cannot prove
whether Step 1-3 moved observations closer to the intended signal:

- random feature assignments and event masks are not returned;
- scenario composition silently overwrites conflicting fields and is
  order-dependent;
- a shared RNG stream means a nominal A/B change also changes later random
  events;
- the default QC schedule lacks a final QC injection;
- tests mainly verify shape, file creation, and plot generation.

The result is useful smoke data, not a scientific oracle.

## Success criteria

The implementation is complete when all three outcomes are measurable from a
simulation result:

1. **Technical recovery gain** — on drift-positive observed cells,
   `1 - RMSE_log(corrected, technical_truth) / RMSE_log(raw, technical_truth)`.
2. **False-correction rate** — the fraction of no-drift feature×batch tasks
   whose error worsens beyond the declared synthetic tolerance.
3. **Biological preservation error** — absolute error and sign flips in planted
   group log2 fold changes.

The first implementation scores Step 2 only. Its counterfactual target is the
same simulated cell with the batch-local drift component set to one and every
other biological and technical component held fixed. Step 1 and Step 3 are
limited to status, schema, and invariant checks until separate stage-specific
counterfactuals are approved.

Metrics use the finite intersection of raw, corrected, and counterfactual cells.
They are calculated per feature×batch first, then summarized across eligible
tasks and seeds:

- recovery excludes tasks whose raw log-RMSE is below epsilon and reports the
  median of task-level gains for drift-positive strata;
- false correction covers no-drift tasks and records worsening in absolute
  log2-RMSE;
- biological preservation uses real samples with sufficient finite values and
  compares per-feature median-based group log2 fold changes against the Step 2
  counterfactual.

The values `0.25 recovery gain`, `0.05 false-correction rate`, and `0.10 log2
fold-change error` are provisional characterization targets, not simulator
release gates and not production QC thresholds. Simulator release gates are
truth reconstruction, causal invariants, deterministic pairing, schema, and
semantic fixture reproducibility. Production thresholds cannot be promoted
until development and holdout evidence are reported separately.

## Non-goals

- Reproduce complete LC-MS instrument physics.
- Build every possible Cartesian product of stress factors.
- Add, redesign, or prescribe imputation.
- Infer universal 10% or 20% sparse-QC gates from one synthetic matrix.
- Use generated data to claim clinical or biological validity.
- Delete the remaining non-AfterVBA historical workbooks in this phase.

## Dataset contract

### Workbook

Generated correction inputs contain exactly the current workflow-facing data:

- `RawIntensity`
- `SampleInfo`

Required `SampleInfo` fields include `Sample_Name`, `Sample_Type`,
`Injection_Order`, `Batch`, `Injection_Volume`, and `Creatinine_mg_dL`.
Missing measurements remain blank/NaN. No imputation values or color-only
imputation markers are written.

Every batch starts and ends with a scheduled QC. The routine design uses 24
injections per batch, 16 study samples, and eight approximately uniform QCs at
local positions `(1, 4, 7, 11, 14, 17, 20, 24)`.

### In-memory truth ledger

The truth ledger is a test/debug artifact, not another user-facing data stage.
It records:

- latent biological abundance before technical effects;
- reconstructable component matrices and the explicit Step 2 counterfactual
  with batch-local drift removed and every other component preserved;
- feature strata: ISTD, biological-null, positive effect, negative effect;
- per feature×batch drift assignment and expected routing class;
- batch, ionization, matrix-effect, carryover, and saturation components;
- missingness reason and mask;
- outlier and QC-outlier coordinates;
- pooled-QC composition/detectability metadata;
- seed and named RNG stream identifiers.

`SimulationResult` returns the observed matrix, sample metadata, feature
metadata, and this ledger together. Optional debug export goes under `build/`;
tests do not depend on a second tracked workbook.

## Causal generation order

1. Generate study-sample identities, balanced biological strata, batch
   assignment, injection schedule, and pooled-QC membership.
2. Generate latent study abundance with explicit null/positive/negative
   biological strata.
3. Build the pooled-QC latent profile as the equal-volume arithmetic mean of
   contributing study-sample linear abundances, then create QC replicates as
   separate injections. Dilution and membership remain explicit ledger fields.
4. Generate position-indexed per-injection technical fields: sample-wide
   ionization, batch-local drift, batch offsets, and measurement noise.
5. Apply class-dependent matrix effects and ISTD interference to the relevant
   study/QC injections according to the named recipe.
6. Apply sequence-dependent carryover, explicit jump/outlier events, and the
   detector response/saturation curve. Every event is recorded before
   detection.
7. Generate detection and integration outcomes from the final response and
   stored random uniforms; create NaNs and record exactly one primary reason.

Every intermediate response is reconstructable from the ledger. No pooled-QC
value is derived from an already corrupted observation, and no mechanism order
changes implicitly because another random call was added.

## Randomness contract

Use one root `SeedSequence` and named child streams for:

- schedule;
- biological truth;
- measurement noise;
- missingness/detection;
- outliers;
- carryover;
- feature assignments.

Paired variants reuse the same latent sample truth, position-indexed technical
draws, and underlying random uniforms while changing only the declared
perturbation. Derived signals, detection probabilities, missing masks, and
outlier outcomes are recomputed and may legitimately differ. Tests compare
hashes only for inputs/uniforms that the perturbation contract says must remain
fixed.

Arbitrary `scenarioA+scenarioB` merging is removed from scientific regression;
conflicting mechanism settings must be expressed as a reviewed named recipe.

## Composite archetypes

### 1. `routine_recoverable`

Contains batch shift, moderate batch-local nonlinear drift, heteroscedastic
noise, sparse intensity-dependent missingness, a few QC/study outliers, stable
ISTDs, and balanced biology/order.

Expected semantics:

- all batches satisfy scheduled endpoint-QC and eight-QC design;
- Step 1-3 can complete;
- drift-positive tasks improve against truth;
- no-drift tasks normally remain unchanged;
- planted biology stays within the preservation gate.

### 2. `qc_limited_routing`

Starts from eight scheduled QCs but assigns feature-level QC detectability so
the same matrix contains effective counts `4, 5, 6, 7, 8+`. It mixes linear
drift, nonlinear drift, no drift, middle-QC missingness, endpoint feature
missingness, and QC outliers.

Expected semantics:

- scheduled batch endpoints are valid;
- feature-level endpoint loss never extrapolates;
- per feature×batch routing reasons are observable;
- any applied correction means Step 2 `SUCCESS`;
- no applied corrections means Step 2 `SKIPPED`.

This archetype characterizes 6-7 QC linear gates; it does not preselect 10% or
20% before evidence is generated.

### 3. `biology_order_twin`

Produces two matrices with identical latent sample biology, position-indexed
technical draws, and random uniforms:

- `balanced`: study classes are interleaved;
- `confounded`: class and injection order are highly, but not perfectly,
  correlated.

Both retain endpoint QCs, drift, batch effects, and modest missingness. Because
the sample-to-position mapping changes, derived signals and detection outcomes
are allowed to differ.

Expected semantics:

- technical recovery remains comparable between twins when QC evidence is
  sufficient;
- the confounded twin does not suffer materially greater biological
  attenuation;
- Step 3 does not claim to solve experimental confounding.

### 4. `lod_matrix_carryover`

Contains subgroup-specific true signals, pooled-QC dilution near LOD,
class-specific matrix suppression, high-signal carryover, upper-tail
saturation, and intensity-dependent MNAR missingness.

Expected semantics:

- artificial QC anchors are never created;
- QC-undetectable features remain uncorrected with explicit reasons;
- a successful workflow is not interpreted as reliable quantitation for
  unsupported features.

### 5. `observable_insufficiency_control`

Uses only conditions the pipeline can observe: insufficient effective QC,
feature-level endpoint loss, duplicate/invalid order, or all-invalid QC.

Expected semantics:

- conservative skip/unchanged outcomes are required;
- reasons must identify the observable failed precondition;
- this scenario is excluded from average recovery scores.

Hidden QC mismatch/nonrepresentativeness remains a separate diagnostic stratum
inside `lod_matrix_carryover`. It is scored for harm against truth but does not
require the pipeline to emit a routing reason for information it cannot see.

## Paired perturbations

Within the fixed archetypes, tests may vary one named lever while reusing every
other truth/event assignment:

- drift amplitude: low / medium / high;
- confounding strength: balanced / high / near-complete;
- effective QC stratum: 4 / 5 / 6 / 7 / 8+;
- detection pressure: low / medium / high;
- batch shift: none / moderate / strong.

Development characterization uses seeds `51`, `137`, and `911`. A frozen
holdout manifest uses multiple undisclosed-to-the-tuning-loop seeds and a
parameter region not used for candidate selection. The manifest records recipe
version, semantic config digest, and expected invariant classes. A fresh-context
reviewer runs the holdout after candidate selection and reports development and
holdout results separately.

## Implementation sequence

Production processor paths are frozen during this generator plan. The existing
QC-boundary edits remain a separate dirty-worktree concern; vNext changes only
the generator, generator/scenario tests, fixture plumbing, and documentation.
`uv.lock` is never touched.

### Slice A — bootstrap, contracts, and canonical fixture

- Introduce typed simulation result/truth structures.
- Add named RNG streams and the reviewed causal order.
- Fix endpoint-QC scheduling and preserve NaNs.
- Track one deterministic current-format workbook:
  `data/synthetic_correction_input.xlsx`.
- Immediately migrate `tests/conftest.py` and file-I/O tests to the new fixture;
  a missing canonical fixture is a test failure, never a skip.
- Compare regenerated fixtures by semantic digest: sheet order, headers,
  sample/feature identifiers, numeric values within tolerance, NaN mask, and
  required ISTD styles. Do not compare XLSX bytes.

Verification gate:

- same seed reconstructs the same ledger and semantic workbook digest;
- every batch starts/ends with QC;
- workbook schema, ISTD markers, and NaNs survive round-trip;
- focused fixture/file-I/O tests pass before any claim about the full suite.

### Slice B — `routine_recoverable` vertical evidence loop

- Implement only `routine_recoverable` and one paired drift perturbation.
- Add truth reconstruction and Step 2 counterfactual scoring.
- Add generator-property, pairing, and metric reconciliation tests.

Verification gate:

- unperturbed latent inputs/uniforms match across the pair;
- pooled QC is reproducible from study latent truth;
- carryover cannot cross a batch boundary;
- hand-checked Step 2 RMSE and fold-change calculations match the report.

### Slice C — `qc_limited_routing` vertical evidence loop

- Implement effective QC strata `4, 5, 6, 7, 8+`, endpoint loss, middle-QC
  missingness, no/linear/nonlinear drift, and QC outliers in one matrix.
- Emit per feature×batch truth routing class and compare it with observed Step 2
  status/reason without preselecting a production threshold.

Verification gate:

- all strata and endpoint cases are present and reconstructable;
- observable insufficiency never produces extrapolated correction;
- routing and harm diagnostics identify feature, batch, seed, and truth stratum.

### Slice D — migration completion and expanded characterization

- Implement `biology_order_twin`, `lod_matrix_carryover`, and
  `observable_insufficiency_control` only after Slices B/C are diagnostic.
- Generate all noncanonical scenario workbooks under `build/`.
- Update remaining scenario tests, README, manifests, and screenshot
  instructions away from `AfterVBA`.
- Remove the obsolete sparse-QC prototype after its useful decision fields are
  represented by truth-ledger tests.
- Run development seeds and emit compact characterization CSVs under `build/`.
- Freeze and run the multi-seed holdout through a fresh-context reviewer.

Verification gate:

- no live code/docs/tests reference `AfterVBA`;
- full relevant suite passes without skipped canonical-fixture tests;
- dev/holdout reports are separate and every failure is attributable;
- no production threshold changes unless evidence passes and the remaining
  scientific decision is explicit.

## Failure modes and safeguards

| Failure mode | Detection | Safeguard |
| --- | --- | --- |
| Simulator favors the current algorithm | Blind recipes/seeds fail or alternate model wins only on tuned seeds | Keep blind seeds and both linear/nonlinear truth strata |
| Complex scenario becomes non-diagnostic | No expected per-stratum outcome | Reject recipe until expected semantics are defined |
| A/B changes unrelated random events | Paired mask hashes differ | Named RNG streams and invariant tests |
| Correction removes planted biology | Fold-change error/sign flips | Biology preservation release gate |
| Stable features are made worse | False-correction rate | No-drift strata and explicit unchanged decisions |
| Missingness is treated as invented low values | Ledger mismatch or non-NaN correction input | Round-trip NaN invariant and no imputation code |
| Binary fixture drifts from generator | Semantic digest mismatch | Compare sheet/schema/IDs/values/NaN/style, never XLSX bytes |

## Rollback and stopping rules

- Generator refactoring freezes production processor paths until the scientific
  contracts pass; overlapping existing edits are preserved and not reformatted.
- Existing production behavior remains unchanged if characterization fails.
- If the truth target for a processor cannot be stated unambiguously, stop at
  generator diagnostics and do not score that processor as failed.
- Git history is the rollback for removed legacy fixtures; no compatibility
  adapter is added for historical `AfterVBA` input.

## Review gate

Implementation may begin only after one independent review confirms:

- no blocker remains in problem framing, causal ordering, truth definition,
  acceptance metrics, or fixture migration;
- the plan avoids arbitrary scenario overlay and uncontrolled scope expansion;
- tests can distinguish simulator defects, pipeline defects, and intentionally
  non-identifiable inputs.
