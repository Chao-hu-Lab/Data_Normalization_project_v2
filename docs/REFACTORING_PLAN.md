# Refactoring Plan（Archived）

這份文件是早期重構草案，保留作為歷史參考，不再代表目前 DNP 架構或工作流。

目前 active workflow 已經改成：

- Step 1: `ISTD Correction`
- Step 2: `QC-LOESS`
- Step 3: `PQN` / `SpecNorm+PQN` active concentration normalization
- Step 4: `QC Batch Scaling` paused; manual diagnostics-only

舊版草案中的下列內容已過時：

- `test_batch_effect.py`
- `Batch_Effect_plots`
- `Step3_Batch_Effect`
- `Step4_Normalization`
- 以 ComBat / Batch Effect 作為 active workflow stage 的描述
- `Data_Normalization_program_v2.py` 舊 GUI 行號與未使用變數清單

## Current Planning Sources

後續實作與 review 應以這些文件為準：

- [README.md](../README.md)
- [docs/algorithms/qc_lowess.md](algorithms/qc_lowess.md)
- [docs/algorithms/normalization.md](algorithms/normalization.md)
- [docs/TESTING.md](TESTING.md)
- [docs/plans/2026-04-23-dnp-workflow-responsibility-master-plan.md](plans/2026-04-23-dnp-workflow-responsibility-master-plan.md)
- [docs/plans/2026-04-23-pqn-reference-selection-rules.md](plans/2026-04-23-pqn-reference-selection-rules.md)
