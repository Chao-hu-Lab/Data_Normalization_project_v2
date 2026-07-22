# Data Normalization Workflow v2

Data Normalization Workflow v2 (DNP) is a Python workflow for LC-MS metabolomics matrix preprocessing. It applies internal-standard correction, batch-local QC-LOESS drift correction, and concentration normalization, then leaves cross-batch scaling as an explicit diagnostics-only step.

The current active scientific workflow ends at **Step 3**. Step 4 remains visible in the GUI for manual diagnostics, but it is not an endorsed correction output and is not run by Auto Run.

## Contents

- [Preview](#preview)
- [Workflow Contract](#workflow-contract)
- [Install](#install)
- [Quick Start](#quick-start)
- [Example Workbooks](#example-workbooks)
- [Input Workbook Contract](#input-workbook-contract)
- [Outputs](#outputs)
- [Python API](#python-api)
- [CLI Status](#cli-status)
- [Testing](#testing)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Preview

GUI preview: pending verified capture.

The first screenshot will show the main workflow screen with `data/synthetic_correction_input.xlsx` loaded, `PQN` selected, and Auto Run ready. Screenshot capture rules live in [docs/assets](docs/assets/README.md).

| Asset | Intended capture |
| --- | --- |
| `docs/assets/dnp-gui-overview.png` | Main GUI after selecting `data/synthetic_correction_input.xlsx`, with `PQN` selected and Auto Run ready. |
| `docs/assets/dnp-step3-session.png` | Optional output/session view showing the Step 3 workbook and generated plots. |

## Workflow Contract

| Step | Module | Status | Responsibility |
| --- | --- | --- | --- |
| 1 | ISTD Correction | Active | Correct sample-level internal-standard behavior and mark skipped ISTD paths explicitly. |
| 2 | QC-LOESS | Active | Correct within-batch run-order drift using batch-local QC anchors; 6–7 effective QC may use the gated log-linear fallback, while ≥8 may use LOWESS. |
| 3 | Concentration Normalization | Active | Choose `PQN` (default; urine/global dilution) or `SpecNorm` (explicit tissue-reference division); this is the final normalized output. |
| 4 | QC Batch Scaling | Manual diagnostics only | Emit batch diagnostics when explicitly requested with `diagnostics_only=True`; not part of Auto Run. |

Important boundaries:

- Step 2 does not align batches against a cross-batch QC target.
- Step 3 may use QC samples to build a PQN reference, but it is not a batch-correction module.
- Step 3 fails closed when QC samples are missing for the active adductomics policy.
- Step 4 active scaling is paused; use it only for residual analysis, QC alignment plots, and batch boxplots.
- Sample columns must map reliably to `SampleInfo`; unmapped sample columns fail closed.

## Install

### Runtime

```powershell
pip install -r requirements.txt
```

Runtime dependencies are tracked in [requirements.txt](requirements.txt). The core stack is:

- `pandas`
- `numpy`
- `openpyxl`
- `scipy`
- `scikit-learn`
- `statsmodels`
- `matplotlib`
- `PySide6` (Qt for Python)

### Development

```powershell
pip install -r requirements-dev.txt
```

CI targets Python 3.11 and 3.12. Installing `requirements.txt` provides the PySide6 runtime used by the desktop GUI.

## Quick Start

Launch the PySide6/Qt GUI from the repository root:

```powershell
python Data_Normalization_program_v2.py
```

Typical GUI flow:

1. Click **Browse** and select a current-format Excel workbook.
2. Keep the default Step 3 method `PQN` for urine/global dilution, or explicitly choose `SpecNorm` for tissue data with a trusted per-sample reference.
3. Click **Auto Run** to execute the active workflow through Step 3.
4. Open the Step 3 workbook or plots from the GUI.
5. Run Step 4 only when you explicitly need diagnostics-only batch reports.

For a first local smoke run, use `data/synthetic_correction_input.xlsx`; it is deterministic synthetic data with endpoint QCs, unfilled missing values, ISTD markers, and a reference column that can exercise the explicit `SpecNorm` path.

## Example Workbooks

The tracked smoke-test workbook is generated from a reviewed simulation contract. It is not real experimental data and does not contain pre-correction imputation.

| Path | Use for | Notes |
| --- | --- | --- |
| `data/synthetic_correction_input.xlsx` | First GUI and regression smoke run | Rebuild with `python scripts/synthetic_matrix_vnext.py`; same seed must preserve the semantic workbook digest. |
| `build/scenario_matrices/` | Generated stress scenarios | Untracked outputs from `python scripts/generate_batcheffect_data.py --all`. |

Future larger examples should go under [data/examples](data/examples/README.md) or be linked from this section with file size and provenance. Do not add private research workbooks to the repository.

## Input Workbook Contract

DNP expects a current-format Excel workbook (`.xlsx` or `.xls`). Missing intensities must remain blank at the correction stages; imputation belongs after correction and before statistical methods that require a complete matrix.

Required sheets:

| Sheet | Required columns / content |
| --- | --- |
| `RawIntensity` | First column is the feature ID (`Mz/RT` or legacy `FeatureID`); sample columns contain feature intensities. |
| `SampleInfo` | At minimum `Sample_Name` and `Sample_Type`; Step 2 also requires `Injection_Order`; `Batch` is used for batch-local handling and diagnostics. |

`RawIntensity` details:

- Feature IDs use the `m/z/RT` style, for example `150.0583/2.35`.
- ISTD features are marked with red font in the first column.
- Optional `Sample_Type` metadata rows are preserved and excluded from numeric calculations.

`SampleInfo` details:

| Column | Purpose |
| --- | --- |
| `Sample_Name` | Must match data-sheet sample columns exactly or through the shared sample-name normalization rules. |
| `Sample_Type` | Common values include `QC`, `Control`, `Exposure`, `Normal`, and `Blank`. |
| `Injection_Order` | Required by Step 2; values must be complete and unique within each batch. |
| `Batch` | Used for Step 2 batch-local correction and Step 4 diagnostics. |
| named numeric specimen-reference | Required only for explicit `SpecNorm` (and the legacy hybrid); common names include `DNA_ug/20uL`, protein amount, concentration, reference, or amount columns. Every non-QC sample must contain a positive finite value. Operational metadata such as `Injection_Volume` is ignored. |

## Outputs

GUI and workflow runs write into a timestamped session directory:

```text
output/
└── run_[timestamp]/
    ├── Step1_ISTD_Results.xlsx
    ├── Step2_QC_LOESS.xlsx
    ├── Step3_Normalized_PQN.xlsx
    ├── Step3_Normalized_SpecNorm.xlsx
    ├── Step4_QC_Batch_Scaling.xlsx  # optional diagnostics-only output
    └── plots/
        └── *.png
```

The active normalized result is the Step 3 workbook. Step 4 output, when present, is diagnostic evidence only.

Individual processor calls without a session directory still fall back to timestamped files under `output/`.

## Python API

The processor entry points are intentionally stable:

```python
from metabolomics.processors import istd, normalization, qc_batch_scaling, qc_lowess

result1 = istd.main(input_file="your_data.xlsx")
result2 = qc_lowess.main(input_file=result1.output_path)
result3 = normalization.main(
    input_file=result2.output_path,
    normalization_method="PQN",  # urine/global dilution default
)

# Tissue DNA example: signal per unit DNA.
result3_tissue = normalization.main(
    input_file=result2.output_path,
    normalization_method="SpecNorm",
)

# Optional diagnostics-only Step 4.
result4 = qc_batch_scaling.main(
    input_file=result3.output_path,
    diagnostics_only=True,
)
```

Each processor returns a `ProcessingResult` with `status="succeeded"` or `status="skipped"`.
Skipped results include a `reason` and pass through a valid `.output_path`; validation,
calculation, and save failures raise exceptions. The GUI workflow owns the separate
`failed` and `cancelled` outcomes. Downstream code should read `.output_path`, not infer filenames.

Supported Step 3 method names:

- `PQN`
- `SpecNorm`

Legacy programmatic aliases `SpecNorm+PQN` and `SpecNorm_PQN` remain accepted
for backward compatibility, but are not active GUI choices.

`SpecNorm` means specimen-reference normalization in this project: real samples are divided by a trusted per-sample reference value from `SampleInfo`; QC samples are not divided in this stage.

Method selection is explicit and specimen-aware rather than column-driven: tissue DNA-input `SpecNorm` may follow the distinct feature-level QC correction, while urine defaults to PQN. The legacy `SpecNorm+PQN` implementation is scale-invariant to the specimen-reference division for samples with valid references, so it is not described as two independent corrections; see [Normalization Algorithm](docs/algorithms/normalization.md#依-specimen-type-選擇方法tissue-specnormurine-pqn).

## CLI Status

The repository currently has GUI launchers and maintenance scripts, but not a first-class end-user CLI for arbitrary Step 1-3 workflow runs.

Supported entry points:

- `python Data_Normalization_program_v2.py`: launch the PySide6/Qt GUI from the repository root.
- `python -m metabolomics`: launch the PySide6/Qt package entry point when `src/` is on `PYTHONPATH` or the package is installed.
- Python processor API: call `istd.main(...)`, `qc_lowess.main(...)`, and `normalization.main(...)` from automation code.
- `scripts/run_cleanup_acceptance_workflow.py` and `scripts/verify_workbook_equivalence.py`: acceptance and regression utilities, not general user-facing workflow commands.

## Testing

Recommended local gates:

```powershell
python -m pytest -m "not slow and not integration" -q
python -m pytest .\tests\integration\test_scenario_smoke.py -q
python -m ruff check src tests scripts Data_Normalization_program_v2.py --select F401,F841,F821
git diff --check
```

For output-affecting processor changes, run the real-workbook acceptance workflow and workbook equivalence checker described in [docs/TESTING.md](docs/TESTING.md).

## Documentation

- [Testing Guide](docs/TESTING.md): test layers, scenario smoke, and acceptance workbook equivalence.
- [ISTD Algorithm](docs/algorithms/istd.md): Step 1 input contract, ISTD matching, and output interpretation.
- [QC-LOWESS Algorithm](docs/algorithms/qc_lowess.md): Step 2 batch-local drift correction contract.
- [Normalization Algorithm](docs/algorithms/normalization.md): Step 3 `PQN` / `SpecNorm` behavior and output sheets.
- [Workflow Responsibility Spec](docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md): active responsibility boundary for Steps 1-4.
- [PQN Reference Rules](docs/plans/2026-04-23-pqn-reference-selection-rules.md): active adductomics QC-reference policy.
- [ComBat Archive](docs/algorithms/combat.md): why ComBat is outside DNP's active boundary.
- `python scripts/generate_batcheffect_data.py --all`: generate the disposable scenario matrix set and manifest under `build/scenario_matrices/`.

Most dated planning notes under `docs/plans/` and `docs/superpowers/plans/` are archived records. The two active 2026-04-23 contract references listed above are exceptions until they are migrated into a dedicated contract directory.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing `RawIntensity` or `SampleInfo` | Confirm the workbook follows the current input contract and contains both required sheets. |
| No ISTD found | Confirm ISTD feature IDs are marked with red font in the first column of `RawIntensity`. |
| Sample name mismatch | Align `SampleInfo.Sample_Name` with data-sheet sample columns; DNP fails closed instead of silently guessing. |
| Step 2 cannot start | Confirm `SampleInfo` has `Sample_Name`, `Sample_Type`, and `Injection_Order`, and contains QC samples. |
| `SpecNorm` cannot start | Confirm every non-QC sample has a positive finite value in a trusted named specimen-reference column, or choose `PQN` when reference division is not the intended estimand. |
| Auto Run stops before Step 4 | This is expected. Auto Run ends at Step 3; Step 4 is manual diagnostics-only. |

## License

This project is for research purposes.
