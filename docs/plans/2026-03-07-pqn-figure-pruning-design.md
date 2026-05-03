> [!IMPORTANT]
> Archived historical plan. It may describe pre-refactor Step 3/Step 4 behavior that is no longer current.
> Current workflow sources: `README.md`, `docs/TESTING.md`,
> `docs/plans/2026-04-23-dnp-workflow-responsibility-spec.md`, and
> `docs/plans/2026-04-23-pqn-reference-selection-rules.md`.

# PQN Figure Pruning Design

## Goal

In DNP Step 4, keep only the first four PQN output figures and stop generating the remaining three figures.

## Scope

- Keep:
  - `Fig1_Boxplot_*`
  - `Fig2_CV_*`
  - `Fig3_RLE_*`
  - `Fig4_PCA_*`
- Remove:
  - `Fig5_QC_Variability_*`
  - `Fig6_QC_Reproducibility_*`
  - `Fig7_Correlation_*`

## Approach

Use the smallest possible change in `src/metabolomics/processors/normalization.py`:

1. Shrink the `figure_paths` mapping to the four retained figures.
2. Remove the three corresponding plotting calls.
3. Update the terminal summary so it only lists `Fig1` to `Fig4`.

## Rationale

- This matches the requested output exactly.
- It avoids generating unused files and avoids unnecessary plotting work.
- It keeps the rest of the Step 4 pipeline unchanged.

## Testing

- Add a regression test that runs the plotting section with plotting functions stubbed and asserts that:
  - `Fig1` to `Fig4` are requested
  - `Fig5` to `Fig7` are not requested
- Run the focused normalization test and the existing Step 4-related regression tests.
