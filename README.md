# Data Normalization Workflow v2

Metabolomics data normalization pipeline for mass spectrometry data processing.

## System Requirements

- Python 3.8+
- Windows / macOS / Linux

### Dependencies

```text
pandas
numpy
scipy
scikit-learn
matplotlib
openpyxl
tkinter (built-in)
psutil
```

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```powershell
   pip install pandas numpy scipy scikit-learn matplotlib openpyxl psutil
   ```
3. Run the GUI:
   ```powershell
   python Data_Normalization_program_v2.py
   ```
   Windows quick start: double-click `run_gui.bat`.

## Workflow Overview

The pipeline consists of 4 sequential steps:

| Step | Module | Description |
|------|--------|-------------|
| 1 | ISTD Correction | Internal standard correction using weighted ISTD selection |
| 2 | QC-LOESS | QC-based trend correction using LOESS smoothing |
| 3 | Concentration Normalization | `PQN` or `SpecNorm+PQN` normalization |
| 4 | QC Batch Scaling | QC batch median alignment after concentration normalization |

### Step 1: ISTD Correction
- Selects optimal ISTD for each metabolite based on RT proximity (60%), CV% (25%), intensity (10%), and m/z (5%)
- Applies ratio-based correction using ISTD median
- Generates PCA plots with Hotelling T2 outlier detection

### Step 2: QC-LOESS
- Applies locally weighted scatterplot smoothing based on QC samples
- Performs Levene's test and Wilcoxon test for improvement validation
- Only applies correction when CV% improvement >= 2%

### Step 3: Concentration Normalization
- Supports both `PQN` and `SpecNorm+PQN`
- `PQN` prefers QC-driven reference behavior when reliable and falls back to robust median summaries
- `SpecNorm+PQN` divides real samples by a reference column such as `Creatinine_mg_dL`, runs PQN, then scales each feature back by its real-sample non-missing median
- Sample columns must map reliably to `SampleInfo`; unmapped or ambiguously matched sample names now fail closed

### Step 4: QC Batch Scaling
- Builds batch membership from `SampleInfo`
- Aligns batch-level QC medians after Step 3 normalization
- Preserves Step 3 outputs while adding batch diagnostic plots and residual checks

## Input File Format

### Required Format
- Excel file (.xlsx or .xls)
- **Must be VBA-formatted** (preprocessed with accompanying VBA macro)

### Required Sheets

| Sheet Name | Description |
|------------|-------------|
| `RawIntensity` | Feature intensity matrix (rows: features, columns: samples) |
| `SampleInfo` | Sample metadata with `Sample_Name` and `Sample_Type` columns |

### RawIntensity Sheet Format
- First column: `FeatureID` (format: `m/z/RT`, e.g., `150.0583/2.35`)
- ISTD features: Mark with **red font color** in FeatureID column
- Remaining columns: Sample intensities

### SampleInfo Sheet Format

| Column | Description |
|--------|-------------|
| `Sample_Name` | Must match the data sheet sample columns reliably |
| `Sample_Type` | e.g., `QC`, `Control`, `Exposed`, `Blank` |
| `Batch` | (Optional) Batch number for batch effect correction |
| `Creatinine_mg_dL` | Optional reference column for `SpecNorm+PQN` normalization |

## Output Structure

```
output/
├── ISTD_Results_[timestamp].xlsx
├── QC_LOESS_[timestamp].xlsx
├── Normalized_PQN_[timestamp].xlsx / Normalized_SpecNorm_PQN_[timestamp].xlsx
├── QC_Batch_Scaling_[timestamp].xlsx
├── ISTD_Correction_plots/
│   └── [timestamp]/
│       └── *.png
├── QC_LOESS_plots/
├── Normalization_Figures/
└── QC_Batch_Scaling_plots/
```

## Usage

### GUI Mode (Recommended)
```powershell
python Data_Normalization_program_v2.py
```
Windows quick start: double-click `run_gui.bat`.


1. Click **Browse** to select input file
2. Click **Auto Run** to execute all steps, or run each step individually
3. Use **Excel** and **Plot** buttons to view outputs

### CLI Mode (Individual Steps)
```python
from metabolomics.processors import istd, qc_lowess, qc_batch_scaling, normalization

result1 = istd.main(input_file="your_data.xlsx")
result2 = qc_lowess.main(input_file=result1.output_path)
result3 = normalization.main(input_file=result2.output_path, normalization_method="PQN")
result4 = qc_batch_scaling.main(input_file=result3.output_path)
```

Each step returns a `ProcessingResult`, so downstream steps should read `.output_path`.

## Test Data

Sample test files are provided in `data/`:
- `feature_matrix_control_exposed_AfterVBA.xlsx`
- `feature_matrix_with_qc_AfterVBA.xlsx`

For the current regression workflow and scenario-based smoke tests, see [docs/TESTING.md](docs/TESTING.md).

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Missing RawIntensity sheet" | Ensure Excel file has been VBA-formatted |
| "No ISTD found" | Mark ISTD FeatureIDs with red font color |
| "Sample name mismatch" | Verify `SampleInfo.Sample_Name` matches the data sheet columns; Step 1 and Step 4 now stop instead of silently guessing |
| "`SpecNorm+PQN` cannot start" | Ensure `SampleInfo` contains a usable reference column such as `Creatinine_mg_dL` |

## License

This project is for research purposes.

## Version History

- v2.0: Complete rewrite with modern GUI, enhanced statistical validation
