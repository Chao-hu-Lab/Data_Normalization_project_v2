# Four-Step Workbook Slimming Design

## Goal

Reduce Excel output size across the four-step normalization pipeline by keeping only the immediately required input sheet, `SampleInfo`, and the current step's result sheets.

## Scope

- Step 1 output keeps only:
  - `RawIntensity`
  - `SampleInfo`
  - `ISTD_Correction`
- Step 2 output keeps only:
  - `ISTD_Correction`
  - `SampleInfo`
  - `QC LOWESS result`
  - `QC_LOWESS_Advanced Statistics`
- Step 3 output keeps only:
  - `QC LOWESS result`
  - `SampleInfo`
  - `Batch_effect_result`
  - `Batch_Effect_summary`
- Step 4 output keeps only:
  - the actual selected upstream data sheet
  - `SampleInfo`
  - normalization result sheet
  - `ConcNormalization_Summary`

## Special Case: Batch Effect May Be Skipped

Step 3 can return the Step 2 workbook unchanged when batch correction is skipped because:

- there is only one batch, or
- batch and sample type are confounded

Step 4 must therefore preserve the actual input sheet it selected for normalization rather than assuming `Batch_effect_result` always exists. The existing sheet priority remains:

1. `Batch_effect_result`
2. `QC LOWESS result`
3. `ISTD_Correction`
4. `RawIntensity`

## Approach

Keep the change local to each processor's save path rather than introducing a new shared abstraction.

1. Step 1: stop writing every sheet from `all_sheets`; write only `RawIntensity` and `SampleInfo`, then add `ISTD_Correction`
2. Step 2: stop carrying `RawIntensity`; write only `ISTD_Correction`, `QC LOWESS result`, advanced statistics, and `SampleInfo`
3. Step 3: stop copying all input worksheets; copy only `QC LOWESS result` and write the current step's sheets
4. Step 4: pass the selected upstream sheet name into the save function and only preserve that sheet plus `SampleInfo`
5. Update console output so listed sheets match the actual saved workbook contents

## Rationale

- The workbook should contain only what the next step needs.
- This avoids cumulative workbook growth across the pipeline.
- Localized changes keep statistical logic untouched and reduce regression risk.
- Step 4 stays robust when Step 3 is skipped because it preserves whichever sheet it actually used.

## Testing

- Add regression tests that inject an extra worksheet into each step input and verify the extra sheet is not copied forward.
- Verify Step 4 preserves `Batch_effect_result` when present.
- Verify Step 4 preserves `QC LOWESS result` when Batch Effect is skipped and that it does not require `Batch_effect_result`.
- Run focused pytest cases for Steps 1-4 and a manual verification using:
  - `C:\Users\user\Desktop\MS Data process package\ms-preprocessing-toolkit\OUTPUT\DNP\STEP4_program2_DNA_alignment_20260306_235927.xlsx`
