# Scenario Matrix Guide

Use these generated workbooks as targeted validation inputs for different pipeline risks.

| Scenario | File | Recommended Step(s) | What to Look For |
| --- | --- | --- | --- |
| `balanced_pipeline` | `feature_matrix_with_qc_non_group_AfterVBA.xlsx` | Step 1 / Step 2 / Step 3 PQN | End-to-end smoke test across the whole pipeline.; Step 1 should not skip and should generate all diagnostics.; Step 3 PQN should run on a realistic but not pathological matrix. |
| `strong_drift` | `strong_drift.xlsx` | Step 2 | QC trend plots should show clear drift over injection order.; LOWESS should reduce QC CV and flatten drift trajectories. |
| `nonlinear_drift` | `nonlinear_drift.xlsx` | Step 2 | LOWESS should handle non-linear QC trajectories without crashing.; Trend plots should show a visibly non-linear drift shape over injection order. |
| `random_jump` | `random_jump.xlsx` | Step 2 / Step 3 PQN | Stress robustness to sudden spikes and dips.; Check whether QC-focused methods avoid overfitting isolated jumps. |
| `carryover_memory` | `carryover_memory.xlsx` | Step 2 | Diagnostics should show local contamination clusters after strong injections.; Carryover should not be mistaken for a smooth whole-run trend. |
| `strong_batch` | `strong_batch.xlsx` | Step 3 PQN / Step 4 diagnostics (manual) | Manual Step 4 batch diagnostics should show clear pre/post separation when explicitly run.; Residual analysis should visibly tighten after manual QC batch scaling diagnostics. |
| `mixed_direction_batch_drift` | `mixed_direction_batch_drift.xlsx` | Step 2 / Step 3 | QC trajectories should slope upward in one batch and downward in another.; Step 3 should run after Step 2 without claiming cross-batch alignment; use Step 4 for manual diagnostics if needed. |
| `unstable_istd` | `unstable_istd.xlsx` | Step 1 | Step 1 ISTD tracking should reveal unstable correction compounds.; Use to verify Step 1 gate / quality diagnostics under weak ISTD conditions. |
| `istd_degradation` | `istd_degradation.xlsx` | Step 1 | ISTD tracking should show a clear downward trend over injection order.; Step 1 gating should not treat these ISTDs as fully healthy. |
| `istd_sample_interference` | `istd_sample_interference.xlsx` | Step 1 | QC-derived ISTD quality should look better than real-sample behavior.; Use to inspect whether Step 1 looks overconfident when only one sample class is affected. |
| `order_confounding` | `order_confounding.xlsx` | Step 2 / Step 3 PQN | Use when checking for over-correction risk when drift and biology align in time order.; Review whether biological separation is unintentionally flattened after correction. |
| `specnorm_friendly` | `specnorm_friendly.xlsx` | Step 3 SpecNorm+PQN / Step 3 PQN | Preferred matrix for validating SpecNorm+PQN behavior.; Compare SpecNorm+PQN against PQN on a matrix with meaningful reference values. |
| `matrix_effect_suppression` | `matrix_effect_suppression.xlsx` | Step 1 / Step 3 PQN | Target sample type should show depressed global analyte intensity.; Useful for checking whether normalization appears over-optimistic under matrix-effect bias. |
| `signal_saturation` | `signal_saturation.xlsx` | Step 3 PQN / Step 3 SpecNorm+PQN | Upper-tail intensities should be visibly compressed relative to balanced_pipeline.; Normalization quality metrics should not look unrealistically perfect under nonlinear response. |
| `structured_missingness` | `structured_missingness.xlsx` | Step 3 PQN | Structured NaNs should not crash batch statistics or normalization summaries.; Use when validating graceful degradation under non-random missingness. |
| `combined_stress` | `combined_stress.xlsx` | Step 1 / Step 2 / Step 3 PQN | Use as a broad regression stress test after major refactors.; Expect some steps to degrade gracefully rather than look ideal. |
