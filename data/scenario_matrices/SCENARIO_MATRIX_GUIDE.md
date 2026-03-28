# Scenario Matrix Guide

Use these generated workbooks as targeted validation inputs for different pipeline risks.

| Scenario | File | Recommended Step(s) | What to Look For |
| --- | --- | --- | --- |
| `balanced_pipeline` | `feature_matrix_with_qc_non_group_AfterVBA.xlsx` | Step 1 / Step 2 / Step 3 / Step 4 PQN | End-to-end smoke test across the whole pipeline.; Step 1 should not skip and should generate all diagnostics.; Step 4 PQN should run on a realistic but not pathological matrix. |
| `strong_drift` | `strong_drift.xlsx` | Step 2 | QC trend plots should show clear drift over injection order.; LOWESS should reduce QC CV and flatten drift trajectories. |
| `random_jump` | `random_jump.xlsx` | Step 2 / Step 4 PQN | Stress robustness to sudden spikes and dips.; Check whether QC-focused methods avoid overfitting isolated jumps. |
| `strong_batch` | `strong_batch.xlsx` | Step 3 / Step 4 PQN | Step 3 batch alignment and by-batch boxplots should show clear pre/post separation.; Residual analysis should visibly tighten after batch scaling. |
| `unstable_istd` | `unstable_istd.xlsx` | Step 1 | Step 1 ISTD tracking should reveal unstable correction compounds.; Use to verify Step 1 gate / quality diagnostics under weak ISTD conditions. |
| `order_confounding` | `order_confounding.xlsx` | Step 2 / Step 4 PQN | Use when checking for over-correction risk when drift and biology align in time order.; Review whether biological separation is unintentionally flattened after correction. |
| `specnorm_friendly` | `specnorm_friendly.xlsx` | Step 4 SampleSpecific / Step 4 PQN | Preferred matrix for validating SampleSpecific / SpecNorm behavior.; Compare SampleSpecific against PQN on a matrix with meaningful reference values. |
| `combined_stress` | `combined_stress.xlsx` | Step 1 / Step 2 / Step 3 / Step 4 PQN | Use as a broad regression stress test after major refactors.; Expect some steps to degrade gracefully rather than look ideal. |
