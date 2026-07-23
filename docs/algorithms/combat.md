# ComBat 批次效應校正工具（Archived）

這份文件保留作為歷史參考，不代表目前 DNP active workflow。

目前 DNP 的責任邊界是：

- Step 1 `ISTD Correction`: sample-level matrix / ionization stabilization
- Step 2 `QC-LOESS`: batch-local run-order drift correction
- Step 3 `PQN` / `SpecNorm`: active concentration normalization endpoint
- Step 4 `QC Batch Scaling`: paused for active scientific correction; retained only as diagnostics-only

`ComBat` 或其他 model-based cross-batch correction 不屬於目前 DNP active normalization boundary。若後續需要 cross-batch statistical harmonization，應在 DNP 外部作為獨立分析步驟設計、記錄與驗證，不應由 DNP workflow 默默執行。

## 為什麼 archived

舊版文件把 ComBat 描述成 DNP 流程的一部分，並建議：

```text
ISTD 校正 -> QC-LOWESS 校正 -> ComBat 校正
```

這已經不符合目前實作。現在 Auto Run 會停在 Step 3，Step 4 只保留 diagnostics-only，沒有 active ComBat processor，也沒有預設 cross-batch correction sheet。

## 目前要看哪些文件

- [README.md](../../README.md)
- [normalization.md](normalization.md)
- [qc_lowess.md](qc_lowess.md)
- [2026-04-23-dnp-workflow-responsibility-spec.md](../plans/2026-04-23-dnp-workflow-responsibility-spec.md)
- [2026-04-23-pqn-reference-selection-rules.md](../plans/2026-04-23-pqn-reference-selection-rules.md)
