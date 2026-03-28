# Data Normalization Workflow v2

Metabolomics data normalization pipeline for mass spectrometry data processing.

## System Requirements

- Python 3.8+
- Windows / macOS / Linux

### Dependencies

```
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
   ```bash
   pip install pandas numpy scipy scikit-learn matplotlib openpyxl psutil
   ```
3. Run the GUI:
   ```bash
   python Data_Normalization_program_v2.py
   ```
   Windows quick start: double-click `run_gui.bat`.

## Workflow Overview

The pipeline consists of 4 sequential steps:

| Step | Module | Description |
|------|--------|-------------|
| 1 | ISTD Correction | Internal standard correction using weighted ISTD selection |
| 2 | QC-LOWESS | QC-based trend correction using LOWESS smoothing |
| 3 | Batch Effect | Batch effect correction using ComBat algorithm |
| 4 | Concentration Normalization | PQN (Probabilistic Quotient Normalization) |

### Step 1: ISTD Correction
- Selects optimal ISTD for each metabolite based on RT proximity (60%), CV% (25%), intensity (10%), and m/z (5%)
- Applies ratio-based correction using ISTD median
- Generates PCA plots with Hotelling T2 outlier detection

### Step 2: QC-LOWESS
- Applies locally weighted scatterplot smoothing based on QC samples
- Performs Levene's test and Wilcoxon test for improvement validation
- Only applies correction when CV% improvement >= 2%

### Step 3: Batch Effect Correction
- Uses PERMANOVA to assess batch effects
- Applies ComBat algorithm for batch correction
- Validates correction with paired permutation test

### Step 4: Concentration Normalization
- Two-stage normalization: sample-specific (creatinine) + PQN
- Uses QC samples as reference when available (>= 3 QC with CV% < 30%)
- Falls back to robust median if insufficient QC samples

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
| `Sample_Name` | Must match column names in RawIntensity |
| `Sample_Type` | e.g., `QC`, `Control`, `Exposed`, `Blank` |
| `Batch` | (Optional) Batch number for batch effect correction |

## Output Structure

```
output/
├── ISTD_Results_[timestamp].xlsx
├── QC_LOWESS_[timestamp].xlsx
├── Combat_corrected_[timestamp].xlsx
├── Normalized_PQN_SampleSpecific_[timestamp].xlsx
├── ISTD_Correction_plots/
│   └── [timestamp]/
│       └── *.png
├── QC_LOWESS_plots/
├── Batch_Effect_plots/
└── Normalization_Figures/
```

## Usage

### GUI Mode (Recommended)
```bash
python Data_Normalization_program_v2.py
```
Windows quick start: double-click `run_gui.bat`.


1. Click **Browse** to select input file
2. Click **Auto Run** to execute all steps, or run each step individually
3. Use **Excel** and **Plot** buttons to view outputs

### CLI Mode (Individual Steps)
```python
from ISTD_Correction_v2 import main as istd_main
from QC_LOWESS_v2 import main as qc_main
from Batch_Effect_v2 import main as batch_main
from Concentration_Normalization_v2 import main as conc_main

result1 = istd_main(input_file="your_data.xlsx")
result2 = qc_main(input_file=result1['output_path'])
result3 = batch_main(input_file=result2['output_path'])
result4 = conc_main(input_file=result3['output_path'])
```

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
| "Sample name mismatch" | Verify SampleInfo names match RawIntensity columns |

## License

This project is for research purposes.

## Version History

- v2.0: Complete rewrite with modern GUI, enhanced statistical validation
