# Testing Guide

This repository now includes a small regression workflow for validating the 4-step normalization pipeline with synthetic scenario matrices.

## Quick Decision Table

| If you are doing... | Run this layer | Command |
| --- | --- | --- |
| Small wiring/path/output change, or a quick sanity check | Layer 1: path contract | `python -m pytest .\tests\unit\test_file_io.py -q` |
| Normal day-to-day pipeline edits | Layer 2: core smoke | `python -m pytest .\tests\integration\test_scenario_smoke.py -q` |
| Scenario logic changes, edge-case handling, normalization/batch logic refactors, or pre-release validation | Layer 3: deeper regression | `python -m pytest .\tests\integration\test_scenario_regression.py -q` |

## Recommended Quick Checks

Run these two commands from the repository root after changing normalization logic, output handling, or pipeline wiring:

```powershell
python -m pytest .\tests\unit\test_file_io.py -q
python -m pytest .\tests\integration\test_scenario_smoke.py -q
```

What they cover:

- `test_file_io.py`: output root routing, session directory naming, and test-data isolation
- `test_scenario_smoke.py`: representative Step 1, Step 2, Step 3, and Step 4 end-to-end scenarios

After larger algorithm changes, scenario-generator changes, or before a release, also run:

```powershell
python -m pytest .\tests\integration\test_scenario_regression.py -q
```

This second-layer regression suite covers:

- generator-shape checks for `istd_degradation` and `structured_missingness`
- Step 1 regression for `istd_degradation`
- Step 2 regression for `nonlinear_drift` and `carryover_memory`
- Step 4 PQN regression for `structured_missingness`
- advanced generator signatures for `matrix_effect_suppression`, `istd_sample_interference`, `mixed_direction_batch_drift`, and `signal_saturation`
- Step 1 regression for `istd_sample_interference`
- Step 3 regression for `mixed_direction_batch_drift`
- Step 4 PQN regression for `matrix_effect_suppression` and `signal_saturation`

Current scenario coverage in `test_scenario_smoke.py`:

| Scenario | Main target |
| --- | --- |
| `unstable_istd` | Step 1 |
| `strong_drift` | Step 2 |
| `random_jump` | Step 2 |
| `order_confounding` | Step 2 and Step 4 PQN |
| `strong_batch` | Step 3 |
| `balanced_pipeline` | Step 4 PQN |
| `specnorm_friendly` | Step 4 SampleSpecific |

## Scenario Matrices

Generated scenario workbooks live in [data/scenario_matrices/SCENARIO_MATRIX_GUIDE.md](../data/scenario_matrices/SCENARIO_MATRIX_GUIDE.md).

Common validation targets:

- `unstable_istd`: Step 1 diagnostics and ISTD gate behavior
- `istd_degradation`: Step 1 order-dependent ISTD decay
- `strong_drift`: Step 2 QC-LOWESS correction
- `nonlinear_drift`: Step 2 piecewise / non-linear drift behavior
- `carryover_memory`: Step 2 local carryover tails after strong injections
- `order_confounding`: order-biased biology risk in Step 2 / Step 4
- `strong_batch`: Step 3 batch alignment diagnostics
- `structured_missingness`: Step 3 / Step 4 NaN-heavy structured missingness
- `balanced_pipeline`: full pipeline smoke test with PQN
- `specnorm_friendly`: Step 4 SampleSpecific / SpecNorm behavior
- `matrix_effect_suppression`: Step 1 / Step 4 matrix-effect bias on one sample class
- `istd_sample_interference`: Step 1 real-sample-only ISTD interference with QC looking better
- `mixed_direction_batch_drift`: Step 2 / Step 3 opposite QC drift directions by batch
- `signal_saturation`: Step 4 nonlinear upper-tail compression / detector saturation

To regenerate the full scenario set:

```powershell
python .\scripts\generate_batcheffect_data.py --all
```

## Output Isolation

Synthetic and test-oriented inputs are intentionally separated from normal analysis outputs.

If the input file is under:

- `data/scenario_matrices/`
- `data/test_matrices/`
- `tests/`

then outputs are written under:

```text
output/test_data_runs/<input_file_stem>/
```

This prevents regression runs from mixing with real project outputs.

## Recommended Testing Order

For normal development, prefer **simple to complex**, not the other way around.

Recommended order:

1. Run the focused unit/path check: `test_file_io.py`
2. Run the representative single-risk and step-targeted scenarios in `test_scenario_smoke.py`
3. Run `test_scenario_regression.py` when the change touched scenario generation, batch logic, normalization logic, or step-specific edge handling
4. Only then run broader stress cases such as `combined_stress` if the change touched shared logic or you want higher confidence before release

Why this order works better:

- When a focused scenario fails, the likely broken step is immediately obvious
- When a complex stacked scenario fails first, you usually still need to go back and decompose the problem
- The representative smoke suite is fast enough for routine work, while combined stress tests are better for refactors and release checks

Use complex scenarios first only when you want a quick "did anything major break?" answer. For actual debugging, go back to the step-targeted scenarios.

## Typical Workflow

For everyday development:

1. Change code.
2. Run `python -m pytest .\tests\unit\test_file_io.py -q`.
3. Run `python -m pytest .\tests\integration\test_scenario_smoke.py -q`.
4. If both pass, the main scenario regression is in a good state.

## Notes

- The scenario smoke suite is intentionally small and representative, not exhaustive.
- If you want to inspect generated outputs manually, check the session directories created during the test run or generate the scenario matrices directly with the script above.
- When validating real analysis data, continue using the normal GUI or pipeline flow; the isolated `test_data_runs` area is only for synthetic/test inputs.
