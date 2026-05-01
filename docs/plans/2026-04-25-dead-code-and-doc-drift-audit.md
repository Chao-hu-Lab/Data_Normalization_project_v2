# 2026-04-25 Dead Code and Doc Drift Audit

## Scope

This audit scanned the current DNP branch for:

- dead-code candidates
- legacy compatibility paths
- stale workflow documentation
- semantic mismatches between docs/comments and current Step 1-4 behavior

No uncertain runtime code was removed in this pass.

## Already Fixed in This Pass

These were high-confidence documentation/comment mismatches and were updated directly:

| File | Issue | Action |
| --- | --- | --- |
| `docs/algorithms/combat.md` | Described ComBat as an active DNP workflow tool even though DNP no longer has an active ComBat stage. | Replaced with an archived note and current workflow pointers. |
| `docs/REFACTORING_PLAN.md` | Old refactor plan referenced `test_batch_effect.py`, `Batch_Effect_plots`, `Step3_Batch_Effect`, and old GUI line numbers. | Replaced with an archived note and current planning sources. |
| `src/metabolomics/adapters/__init__.py` | Claimed adapters are deprecated/removed even though GUI and tests still use adapter modules directly. | Updated package note to describe current direct-module import behavior. |
| `src/metabolomics/gui/app.py` | Stale TODO said adapters were removed. | Removed the stale comment. |

## High-Confidence Dead-Code Candidates

These have no direct references from `src`, `tests`, `scripts`, or the GUI wiring found by `rg` / AST scan. They should still be removed only after confirmation because some may be public compatibility APIs.

| Candidate | Evidence | Risk | Suggested Action |
| --- | --- | --- | --- |
| `src/metabolomics/processors/istd.py:1714` `save_skipped_istd_results_to_excel(...)` | No direct references found. Current Step 1 skip handling appears to be implemented through `main(...)` result flow, not this helper. | Medium: could be a planned manual helper. | Confirm whether any external script calls it; if not, remove with a focused test around ISTD skip output. |
| `src/metabolomics/processors/normalization.py:843` `is_numeric_value(...)` | No direct references found. | Low. | Remove if no external use. |
| `src/metabolomics/processors/normalization.py:853` `get_non_qc_columns(...)` | No direct references found. Similar responsibilities are now handled by shared sample classification helpers. | Medium. | Remove after confirming no manual notebooks/scripts import it. |
| `src/metabolomics/processors/normalization.py:873` `get_sample_columns_only(...)` | No direct references found. | Medium. | Remove after confirming no external use. |
| `src/metabolomics/processors/normalization.py:1907` `select_file()` | No direct references found. GUI uses its own file selection path. | Low. | Remove if CLI/manual file picker support is no longer needed. |
| `src/metabolomics/processors/qc_batch_scaling.py:676` `generate_pca_plots(...)` | Only historical docs mention it; production calls use `generate_step3_plots(...)`. | Medium: explicitly labeled backward-compatible alias. | Confirm whether compatibility alias is still needed; otherwise remove and update old docs. |
| `src/metabolomics/utils/statistics.py:84` `calculate_hotelling_t2_outliers_internal(...)` | No direct references found. | Low to medium. | Remove if not intended as public fallback. |
| `src/metabolomics/utils/file_io.py:159` `validate_required_columns(...)` | No direct references found. | Low. | Remove if not part of public utility API. |
| `src/metabolomics/utils/safe_math.py:222` `get_valid_numeric_values(...)` | No direct references found. | Low. | Remove if not part of public utility API. |
| `src/metabolomics/utils/constants.py` `SHEET_NAMES['batch_effect']` / `SHEET_NAMES['batch_summary']` | No current references found outside the constants table. Names still point to old Batch Effect sheets. | Medium: could support old workbooks if external code imports constants. | Confirm whether old `Batch_effect_result` / `Batch_Effect_summary` support is still required; otherwise remove these keys. |

## Public Helper / Compatibility Candidates

These look unused from production code but are covered by tests or intentionally public. Do not remove without an explicit compatibility decision.

| Candidate | Evidence | Suggested Decision |
| --- | --- | --- |
| `src/metabolomics/processors/normalization.py:529` `sample_specific_normalization(...)` | No production references, but unit tests cover it as a backward-compatible alias for `SpecNorm+PQN`. | Keep unless legacy `SampleSpecific` support is intentionally dropped. |
| `src/metabolomics/processors/normalization.py:582` `get_all_sample_columns(...)` | No production references, but unit tests exercise the contract. | Keep if external scripts may call it; otherwise migrate tests to shared helper and remove. |
| `src/metabolomics/utils/sample_classification.py` convenience methods `get_batch`, `get_qc_samples`, `get_control_samples`, `get_exposure_samples`, `get_normal_samples`, `get_type_counts` | No direct production references, but they are part of the `SampleClassifier` public surface. | Keep unless `SampleClassifier` API is intentionally narrowed. |
| `src/metabolomics/utils/plotting.py:397` `plot_pca_comparison_real_sample_style(...)` | Tested but no production reference found in current branch. It may be retained for planned Step 4/diagnostics plotting. | Confirm whether future diagnostics still need it. |
| `src/metabolomics/utils/plotting.py:73` `build_pca_comparison_suptitle(...)` and `:83` `build_pca_comparison_filename(...)` | No direct references found. | Remove if not planned for upcoming plot naming cleanup. |
| `src/metabolomics/utils/data_validation.py` `DataValidator` and helper validators | No current production references found. | Decide whether this is a future validation layer or an abandoned extraction. |

## Reserved Extension Point Review

Second-pass review separates true reserved extension points from compatibility shims and stale remnants.

| Candidate | Classification | Reasoning | Cleanup Decision |
| --- | --- | --- | --- |
| `src/metabolomics/utils/data_validation.py` `DataValidator`, `ValidationResult`, and `quick_validate_excel(...)` | Reserved extension point, but currently unwired | The module is explicitly written as a centralized validation layer. Current Step 1 and Step 2 still contain their own inline defensive checks, so this is an extracted layer that was never connected. | Keep only if the upcoming refactor will centralize validation around it; otherwise delete the whole module in one focused cleanup. |
| `src/metabolomics/utils/sample_classification.py` `SampleClassifier` convenience object and methods | Reserved public facade | The current production path mainly uses function-level helpers such as `identify_sample_columns(...)`, but `SampleClassifier` is exported from `metabolomics.utils` and represents a natural future API for richer sample type / batch lookups. | Keep if preserving a public utility surface matters. If not, remove the class separately from the function helpers. |
| `src/metabolomics/utils/plotting.py` `plot_pca_comparison_real_sample_style(...)` | Reserved diagnostics extension point | It is covered by tests and tied to dated Step 4 real-sample PCA plans. Current active Step 4 is paused/diagnostics-only, so this is not active wiring, but it is plausible future diagnostics code. | Keep if Step 4 diagnostics will include real-sample PCA. If Step 4 remains non-plotting or QC-only, remove with its test and archive the dated plan note. |
| `src/metabolomics/utils/plotting.py` `build_pca_comparison_suptitle(...)` / `build_pca_comparison_filename(...)` | Weak reserved extension point | These helpers support a future consistent plot naming/title convention, but no current code uses them. | Keep only if plot naming cleanup is planned; otherwise remove with low risk. |
| `src/metabolomics/processors/normalization.py` `sample_specific_normalization(...)` | Compatibility shim, not an extension point | It is a backward-compatible alias for `SpecNorm` division and is tested through the legacy `SampleSpecific` path. The active UI and docs use `SpecNorm+PQN`. | Decide whether old `SampleSpecific` imports/method strings must keep working. If not, remove alias, canonicalization entries, and compatibility tests together. |
| `src/metabolomics/processors/normalization.py` `get_all_sample_columns(...)` | Compatibility wrapper, not an extension point | It delegates to the shared `identify_sample_columns(...)` helper and is retained mainly because tests exercise the wrapper. | Safe to remove after migrating tests and any docs to `identify_sample_columns(...)`. |
| `src/metabolomics/processors/qc_batch_scaling.py` `generate_pca_plots(...)` | Compatibility alias, not an extension point | It only forwards to `generate_step3_plots(...)`. Current production calls use the new name. | Remove if external scripts do not call the old name; update historical docs or mark them archived. |
| `src/metabolomics/processors/istd.py` `save_skipped_istd_results_to_excel(...)` | Stale remnant | Current Step 1 skip path intentionally returns a skipped `ProcessingResult` and does not produce a Step 1 workbook. Step 2 handles fallback from the original input and filters ISTDs itself. | Remove after keeping/expanding the existing Step 1 skip and Step 2 fallback tests. |
| `src/metabolomics/processors/normalization.py` `is_numeric_value(...)`, `get_non_qc_columns(...)`, `get_sample_columns_only(...)`, and `select_file()` | Stale remnants | Numeric/sample filtering responsibilities moved to shared helpers, and GUI/entry points now require explicit file paths. | Remove as high-confidence cleanup. |
| `src/metabolomics/utils/statistics.py` `calculate_hotelling_t2_outliers_internal(...)` | Stale duplicate | The public `calculate_hotelling_t2_outliers(...)` already supports internal-reference behavior when `all_scores` is omitted. | Remove after checking tests still cover the public helper. |
| `src/metabolomics/utils/file_io.py` `validate_required_columns(...)` and `src/metabolomics/utils/safe_math.py` `get_valid_numeric_values(...)` | Utility leftovers, not strong extension points | They are standalone helpers with no active callers. Similar validation and matrix extraction behavior exists elsewhere. | Remove unless the validation-layer refactor explicitly adopts them. |
| `src/metabolomics/utils/constants.py` `SHEET_NAMES['batch_effect']` / `SHEET_NAMES['batch_summary']` | Stale workflow constants | They reference old Batch Effect output sheets that are not part of the current active Step 1-4 contract. | Remove with stale docs cleanup unless old workbook compatibility requires these keys. |

## Import / Lint Cleanup Candidates

`uv run ruff check src tests scripts Data_Normalization_program_v2.py` found many style issues. The actionable dead-code subset is unused imports / unused locals:

| Area | Examples | Suggested Action |
| --- | --- | --- |
| Adapter export | `src/metabolomics/adapters/dnp_to_metaboanalyst.py` imports `openpyxl` and `dataframe_to_rows` but does not use them. | Remove in a small cleanup commit. |
| GUI imports | `src/metabolomics/gui/app.py` imports `importlib.util`, `psutil`, `re`, and `tempfile` without current use. | Remove after one GUI import test. |
| ISTD imports | `src/metabolomics/processors/istd.py` has unused imports such as `FONT_SIZES`, `COLORBLIND_COLORS`, `VALIDATION_THRESHOLDS`, `SampleClassifier`, and a local `normalize_sample_type`. | Remove carefully; this file has many historical paths. |
| Utility imports | `src/metabolomics/utils/data_validation.py`, `file_io.py`, `plotting.py` have unused imports. | Remove in utility cleanup pass. |
| Test locals/imports | Several tests have unused imports or locals. | Safe cleanup, but keep separate from runtime code cleanup. |

## Stale Historical Docs Not Modified

These are old implementation plans under `docs/plans` and `docs/superpowers/plans`. They still mention `batch_effect.py`, old Step 4 normalization outputs, or old ComBat plans. I did not rewrite them because they are dated historical planning artifacts.

Examples:

- `docs/superpowers/plans/2026-03-21-session-based-output.md`
- `docs/plans/2026-03-08-istd-gate-and-qc-batch-scaling.md`
- `docs/plans/2026-03-08-istd-gate-and-qc-batch-scaling-design.md`
- `docs/plans/2026-03-07-four-step-workbook-slimming.md`
- `docs/plans/2026-03-08-step2-step3-pca-legend-design.md`

Suggested action:

- Leave as historical records, or add a standard `Archived historical plan` banner to all March plan files in one documentation-only commit.

## Cache / Artifact Directories

The workspace contains local generated artifacts:

- `__pycache__/`
- `.ruff_cache/`
- nested `__pycache__/` under `src`, `tests`, and `scripts`
- pytest/build caches under `build/pytest`
- historical worktrees under `.worktrees`

These appear to be ignored/generated artifacts. I did not delete them in this pass because recursive cleanup would be destructive and should be explicitly approved.

## Recommended Next Cleanup Order

1. Remove high-confidence unused imports and unused locals.
2. Remove confirmed dead helpers from `normalization.py`, `file_io.py`, `safe_math.py`, and `statistics.py`.
3. Decide whether `data_validation.py` is a future validation layer or an abandoned extraction.
4. Decide whether compatibility aliases such as `sample_specific_normalization(...)` and `generate_pca_plots(...)` are still required.
5. Optionally add archive banners to older dated plan files instead of rewriting their contents.
