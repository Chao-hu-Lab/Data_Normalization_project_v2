# Testing Guide

This repository now includes a small regression workflow for validating the active Step 1-3 workflow plus explicit Step 4 diagnostics-only scenarios with synthetic scenario matrices.

## Standard Gates

Use these three layers as the default confidence ladder:

| Gate | Purpose | Command |
| --- | --- | --- |
| Fast tests | Routine unit and non-slow regression coverage | `python -m pytest -m "not slow and not integration" -q` |
| Scenario smoke | Representative Step 1, Step 2, Step 3, and Step 4 diagnostics-only scenarios | `python -m pytest .\tests\integration\test_scenario_smoke.py -q` |
| Acceptance workbook equivalence | Real-workbook Step 3 semantic equivalence after output-affecting processor changes | `python .\scripts\run_cleanup_acceptance_workflow.py --input "<workbook.xlsx>" --method "SpecNorm+PQN" --session-dir "<baseline_or_candidate_dir>"` then `python .\scripts\verify_workbook_equivalence.py --baseline "<baseline_step3.xlsx>" --candidate "<candidate_step3.xlsx>"` |

The active scientific workflow ends at Step 3. Step 4 remains available only for manual diagnostics-only checks and should not be required for routine Step 3 artifact readiness.

## Quick Decision Table

| If you are doing... | Run this layer | Command |
| --- | --- | --- |
| Small wiring/path/output change, or a quick sanity check | Layer 1: path contract | `python -m pytest .\tests\unit\test_file_io.py -q` |
| Sample identity / `SampleInfo` alignment changes | Layer 1b: fail-closed sample mapping | `python -m pytest .\tests\unit\test_sample_matching.py -q` |
| Normal day-to-day pipeline edits | Layer 2: core smoke | `python -m pytest .\tests\integration\test_scenario_smoke.py -q` |
| Scenario logic changes, edge-case handling, normalization/batch logic refactors, or pre-release validation | Layer 3: deeper regression | `python -m pytest .\tests\integration\test_scenario_regression.py -q` |

## Recommended Quick Checks

Run these commands from the repository root after changing normalization logic, output handling, or pipeline wiring:

```powershell
python -m pytest .\tests\unit\test_file_io.py -q
python -m pytest .\tests\unit\test_sample_matching.py -q
python -m pytest .\tests\integration\test_scenario_smoke.py -q
```

What they cover:

- `test_file_io.py`: output root routing, session directory naming, and test-data isolation
- `test_sample_matching.py`: sample column detection and `SampleInfo` alignment fail-closed behavior
- `test_scenario_smoke.py`: representative Step 1, Step 2, Step 3, and Step 4 diagnostics-only scenarios

After larger algorithm changes, scenario-generator changes, or before a release, also run:

```powershell
python -m pytest .\tests\integration\test_scenario_regression.py -q
```

This second-layer regression suite covers:

- generator-shape checks for `istd_degradation` and `structured_missingness`
- Step 1 regression for `istd_degradation`
- Step 2 regression for `nonlinear_drift` and `carryover_memory`
- Step 3 PQN regression for `structured_missingness`
- advanced generator signatures for `matrix_effect_suppression`, `istd_sample_interference`, `mixed_direction_batch_drift`, and `signal_saturation`
- Step 1 regression for `istd_sample_interference`
- Step 4 diagnostics-only regression for `mixed_direction_batch_drift`
- Step 3 PQN regression for `matrix_effect_suppression` and `signal_saturation`

Current scenario coverage in `test_scenario_smoke.py`:

| Scenario | Main target |
| --- | --- |
| `unstable_istd` | Step 1 |
| `strong_drift` | Step 2 |
| `random_jump` | Step 2 |
| `order_confounding` | Step 2 and Step 3 PQN |
| `strong_batch` | Step 4 diagnostics-only |
| `balanced_pipeline` | Step 3 PQN |
| `specnorm_friendly` | Step 3 SpecNorm+PQN |

## Scenario Matrices

Generated scenario workbooks and their manifest are written to `build/scenario_matrices/`; they are disposable test artifacts, not tracked fixtures.

Common validation targets:

- `unstable_istd`: Step 1 diagnostics and ISTD gate behavior
- `istd_degradation`: Step 1 order-dependent ISTD decay
- `strong_drift`: Step 2 QC-LOESS correction
- `nonlinear_drift`: Step 2 piecewise / non-linear drift behavior
- `carryover_memory`: Step 2 local carryover tails after strong injections
- `order_confounding`: order-biased biology risk in Step 2 / Step 3
- `strong_batch`: Step 4 diagnostics-only batch alignment checks
- `structured_missingness`: Step 3 / Step 4 diagnostics-only NaN-heavy structured missingness
- `balanced_pipeline`: full pipeline smoke test with PQN
- `specnorm_friendly`: Step 3 SpecNorm+PQN behavior
- `matrix_effect_suppression`: Step 1 / Step 3 matrix-effect bias on one sample class
- `istd_sample_interference`: Step 1 real-sample-only ISTD interference with QC looking better
- `mixed_direction_batch_drift`: Step 2 / Step 4 diagnostics-only opposite QC drift directions by batch
- `signal_saturation`: Step 3 nonlinear upper-tail compression / detector saturation

To regenerate the full scenario set:

```powershell
python .\scripts\generate_batcheffect_data.py --all
```

## Output Isolation

Synthetic and test-oriented inputs are intentionally separated from normal analysis outputs.

If the input file is under:

- `build/scenario_matrices/` (when tests provide an explicit session directory)
- `data/test_matrices/`
- `tests/`

then outputs are written under:

```text
output/test_data_runs/<input_file_stem>/
```

This prevents regression runs from mixing with real project outputs.

## Sparse-QC Promotion Evidence

The six-QC fallback has a frozen truth-backed promotion contract and holdout.
Run it without changing production thresholds:

```powershell
uv run python .\scripts\sparse_qc_holdout.py
```

The command compares no correction, strict-eight, and the current six-QC floor
across development and frozen holdout scenarios. It writes candidate metrics,
task-level outcomes, decisions, and a Markdown summary under
`build/sparse_qc_holdout/`. A failed holdout is a valid scientific result and
does not make the command itself fail. The promotion gate scores recovery on
study samples only; QC points used for fitting remain diagnostic rather than
part of the primary RMSE. Every evidence file includes or references manifest,
semantic-config, source, and Git fingerprints.

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
3. Run `python -m pytest .\tests\unit\test_sample_matching.py -q` if the change touched sample detection, naming, or `SampleInfo` mapping.
4. Run `python -m pytest .\tests\integration\test_scenario_smoke.py -q`.
5. If these pass, the main scenario regression is in a good state.

## Known Windows Note

On some Windows setups, `pytest` may fail before assertions run with:

```text
PermissionError: [WinError 5] ... build\pytest\tmp
```

When this happens, treat it as a temp-directory harness issue first, not an immediate pipeline regression. A good fallback is:

1. Run the focused unit suites above.
2. Run `python -m pytest .\tests\integration\test_scenario_regression.py -q`.
3. Run the scenario workflow manually from a PowerShell-created workspace to verify Step 1 through Step 3 end to end, then invoke Step 4 only in diagnostics-only mode if you need its reports.

Current repo rule:

- Keep pytest cache under `build/pytest/cache`
- Use the repo-local custom `tmp_path` fixture from `tests/conftest.py`
- Temp fixture sessions now live under `build/pytest/tmp-fixtures/`
- Do not reintroduce a global `--basetemp=...` in `pytest.ini` on this Windows environment unless the underlying Python/pytest ACL behavior is verified

## Notes

- The scenario smoke suite is intentionally small and representative, not exhaustive.
- If you want to inspect generated outputs manually, check the session directories created during the test run or generate the scenario matrices directly with the script above.
- When validating real analysis data, continue using the normal GUI or pipeline flow; the isolated `test_data_runs` area is only for synthetic/test inputs.
