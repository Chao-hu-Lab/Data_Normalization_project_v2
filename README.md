# Data Normalization Workflow v2

Data Normalization Workflow v2 (DNP) is a fail-closed LC-MS matrix
preprocessing workflow. It supports explicit ISTD monitoring/correction,
batch-local QC drift correction, specimen-aware normalization, and design
identifiability diagnostics without pretending that an unidentifiable study
design has been repaired.

The endorsed workflow ends at **Step 3**. Step 4 remains available only as a
manual diagnostics surface.

## What DNP does

| Step | Method | Current responsibility |
| --- | --- | --- |
| 1 | ISTD Monitoring / Selective Correction | Monitor marked ISTDs. Preserve raw analyte values by default; correct only explicitly mapped features whose donor passes quality gates. |
| 2 | QC-LOWESS / linear fallback | Correct feature-wise, within-batch run-order drift. Six or seven effective QC points may use gated log-linear correction; eight or more may use LOWESS. |
| 3 | `PQN` or `SpecNorm` | Produce the final normalized matrix. `PQN` is the urine/global-dilution default; `SpecNorm` is explicit specimen-reference division for tissue data. |
| 4 | QC Batch Scaling diagnostics | Report residual batch behavior when explicitly requested. It does not produce an endorsed corrected matrix. |

Steps 2 and 3 also write a `Design_Identifiability` receipt. It reports which
sample-type contrasts are supported, assumption-dependent, or
non-identifiable from the available batch, order, QC-pool, pair, and bridge
metadata. The receipt never modifies intensities.

## Quick start

Install the runtime dependencies:

```powershell
pip install -r requirements.txt
```

Launch the PySide6 desktop application:

```powershell
python Data_Normalization_program_v2.py
```

Typical workflow:

1. Select a current-format Excel workbook.
2. Keep `PQN` for urine/global dilution, or choose `SpecNorm` when tissue
   samples have a trusted per-sample reference.
3. Run Auto Run. It executes Steps 1–3 and stops before Step 4.
4. Use the Step 3 workbook as the normalized result.
5. Run Step 4 manually only when residual batch diagnostics are needed.

For a deterministic smoke test, use
`data/synthetic_correction_input.xlsx`. It is synthetic, contains endpoint
QCs and unfilled missing values, and is not real study data.

## Scientific boundaries

- Step 1 does not automatically assign unknown features to the nearest or
  statistically convenient ISTD.
- The legacy RT/CV/intensity/mass auto-matcher is programmatic compatibility
  code and is not exposed by the GUI.
- No `ISTD_Mapping` means monitoring-only success. No detected ISTD means Step
  1 is skipped and Step 2 receives the original `RawIntensity` workbook.
- The current matrix does not contain sample-level RT observations. Step 1
  therefore reports RT stability as unavailable instead of inventing a trend.
- Step 2 is batch-local run-order correction, not cross-batch harmonization.
- Step 3 may use QC samples to build a PQN reference, but it is not a batch
  correction method.
- Step 4 is diagnostics-only. Active ComBat or QC-median batch scaling is
  outside the current product boundary.
- Missing intensities remain missing during correction. Imputation belongs
  after correction and before statistical methods that require a complete
  matrix.
- Strong sample-type/batch/order association is an identifiability warning.
  Software cannot uniquely separate biology from drift when the design does
  not contain the required contrast.

## Input workbook

DNP's current workbook contract uses `.xlsx`.

### Required sheets

| Sheet | Contract |
| --- | --- |
| `RawIntensity` | First column is `Mz/RT` or legacy `FeatureID`; remaining sample columns contain intensities. ISTD feature IDs are marked with red font. |
| `SampleInfo` | Contains `Sample_Name` and `Sample_Type`. Step 2 also requires complete batch-local `Injection_Order`; `Batch` is required by the current correction and diagnostic policies. |

### Optional Step 1 mapping

`ISTD_Mapping` enables selective feature correction:

| Column | Meaning |
| --- | --- |
| `Analyte_Feature_ID` | Feature to evaluate for correction. Each analyte may appear once. |
| `ISTD_Feature_ID` | Explicit donor feature marked as an ISTD in `RawIntensity`. |
| `Mapping_Type` | `matched` or `validated_surrogate`. |
| `Validation_Reference` | SOP, assay record, or other provenance supporting the mapping. |

Mappings fail closed when feature identities are ambiguous, the donor is
unstable, or donor values are unavailable where the analyte is observed.
Rejected and unmapped features retain their raw values.

### Sample metadata

| Column | Use |
| --- | --- |
| `Sample_Name` | Matches an intensity column through the shared sample-name rules. |
| `Sample_Type` | Common values include `QC`, `Control`, `Exposure`, `Normal`, and `Blank`. |
| `Injection_Order` | Required by Step 2; complete and unique within each batch. |
| `Batch` | Defines batch-local correction and design diagnostics. |
| `Pair_ID` | Optional typed pairing metadata. DNP does not infer pairs from sample names. |
| `Bridge_ID` | Optional same-sample cross-batch bridge identifier. |
| `QC_Pool_ID` | Optional pooled-QC composition identifier. Different pools are not treated as interchangeable scale anchors. |
| specimen-reference column | Required for `SpecNorm`; every non-QC sample must have a positive finite value in a trusted DNA, protein, concentration, reference, or amount column. |

Unmapped sample columns and missing required metadata raise actionable errors
instead of falling back to column position or guessed labels.

## Outputs

GUI and workflow runs use a timestamped session directory:

```text
output/
└── run_[timestamp]/
    ├── Step1_ISTD_Results.xlsx
    ├── Step2_QC_LOESS.xlsx
    ├── Step3_Normalized_PQN.xlsx
    ├── Step3_Normalized_SpecNorm.xlsx
    ├── Step4_QC_Batch_Scaling.xlsx   # optional, diagnostics-only
    └── plots/
        └── *.png
```

Important workbook receipts:

- `ISTD_Monitoring`: ISTD missingness, QC CV, area/order association, RT/order
  availability, and alarms.
- `ISTD_Correction`: mixed corrected/uncorrected analyte matrix with mapped
  ISTD, mapping type, validation reference, status, and reason per feature.
- `Design_Identifiability`: metadata-only support assessment written by Steps
  2 and 3.

Each processor returns a `ProcessingResult`. Downstream automation should read
`result.output_path` rather than infer filenames.

## Python API

```python
from metabolomics.processors import istd, normalization, qc_lowess

step1 = istd.main(input_file="your_data.xlsx")
step2 = qc_lowess.main(input_file=step1.output_path)
step3 = normalization.main(
    input_file=step2.output_path,
    normalization_method="PQN",  # or "SpecNorm"
)

print(step3.status.value)  # "succeeded" or "skipped"
print(step3.output_path)
```

Supported Step 3 method names are `PQN` and `SpecNorm`. Legacy aliases
`SpecNorm+PQN` and `SpecNorm_PQN` remain accepted programmatically but are not
GUI choices.

Optional Step 4 diagnostics:

```python
from metabolomics.processors import qc_batch_scaling

diagnostics = qc_batch_scaling.main(
    input_file=step3.output_path,
    diagnostics_only=True,
)
```

## Development and verification

Install development dependencies:

```powershell
pip install -r requirements-dev.txt
```

Recommended gates:

```powershell
python -m pytest -m "not slow and not integration" -q
python -m pytest .\tests\integration\test_scenario_smoke.py -q
python -m ruff check src tests scripts Data_Normalization_program_v2.py
git diff --check
```

For output-affecting processor changes, also run the real-workbook acceptance
and workbook-equivalence checks described in [docs/TESTING.md](docs/TESTING.md).
Do not commit private research workbooks or one-off diagnostic outputs.

## Documentation

- [Testing Guide](docs/TESTING.md)
- [ISTD Monitoring and Selective Correction](docs/algorithms/istd.md)
- [QC-LOWESS](docs/algorithms/qc_lowess.md)
- [Design Identifiability](docs/algorithms/design_identifiability.md)
- [Normalization](docs/algorithms/normalization.md)
- [ComBat boundary](docs/algorithms/combat.md)
- [Workflow responsibility spec](docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md)
- [PQN reference rules](docs/plans/2026-04-23-pqn-reference-selection-rules.md)
- [Specimen-aware Step 3 contract](docs/plans/2026-07-23-step3-specimen-aware-method-contract.md)

Most dated files under `docs/plans/` and `docs/superpowers/plans/` are archived
decision records. Follow the authority routing in `AGENTS.md` for current
contracts.
