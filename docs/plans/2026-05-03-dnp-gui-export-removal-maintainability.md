# DNP GUI Export Removal And Maintainability Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 移除 DNP → MetaboAnalyst export/launch 路徑，收斂 Step 3 method contract，並把 SpecNorm+PQN 的 reference/error guidance 放回 Log panel。

**Architecture:** GUI 只負責執行 DNP active workflow 與開啟本專案產物。Step 3 method/default contract 由 shared utility 提供，GUI 與 processor 共用。Log panel 是詳細診斷與 validation reason 的唯一長文案位置，radio button 區域保持精簡。

**Tech Stack:** Python, Tkinter, pytest, ruff.

---

## Summary

- 完整移除 `Export After Step 3`、`Export to MetaboAnalyst`、DNP-to-MA adapter、GUI launch/export path。
- 保留 manual handoff：使用現有 per-step `Open Excel` / `Open Plots` 開啟 Step 3 workbook 與 plots。
- 保留 inbound bridge：`startup_bridge.py`、`bootstrap_paths.py`、`python -m metabolomics` 啟動相關邏輯不因 export 移除而刪除。
- Step 3 default 仍是 `SpecNorm+PQN`，但 method selector 不顯示 reference detection 或 disabled reason。詳細原因寫入 Log panel / log file。

## Key Changes

- GUI header 改為三個 controls：`Auto Run`、`Stop`、`Reset Workflow`。移除 export button、export button tokens、export readiness state。
- Workflow helper 只保留 step names、step order、method options、Auto Run terminal step；移除 `get_primary_export_step_name()` 與 `is_export_ready()`。
- 刪除 DNP-to-MA adapter 與 GUI export/launch methods；保留 inbound startup bridge 與 preprocessing import adapter。
- 新增 `src/metabolomics/utils/normalization_contract.py`，集中 Step 3 default method、method options、aliases、canonicalization、summary sheet-name helper。
- 移除 Step 3 method radio 旁的長說明；SpecNorm+PQN reference 欄位偵測、被忽略的 `Injection_Volume`、缺 reference 時改用 `PQN` 的建議寫入 Log panel。
- Step failure dialog 改成短訊息：step failed、查看 Log panel、是否 retry；完整錯誤與 traceback 保留在 log。

## Test Plan

- Focused unit tests:
  - `tests/unit/test_gui_workflow.py`
  - `tests/unit/test_gui_step_flow.py`
  - `tests/unit/test_gui_logging.py`
  - `tests/unit/test_bridge_launch.py`
  - `tests/unit/test_imports_without_ms_core.py`
  - `tests/unit/test_normalization_contract.py`
  - `tests/unit/test_normalization.py`
- Required commands:
  - `python -m pytest tests\unit\test_gui_workflow.py tests\unit\test_gui_step_flow.py tests\unit\test_gui_logging.py tests\unit\test_bridge_launch.py tests\unit\test_imports_without_ms_core.py tests\unit\test_normalization.py -q`
  - `python -m pytest tests\integration\test_scenario_smoke.py -q`
  - `python -m ruff check src tests scripts Data_Normalization_program_v2.py --select F401,F841,F821`
  - `python -m pytest -m "not slow and not integration" -q`
  - `git diff --check`
- Search gate:
  - `rg -n "Export After Step 3|Export to MetaboAnalyst|dnp_to_metaboanalyst|bridge_to_ma" src tests README.md docs/TESTING.md docs/algorithms`
  - Expected: no matches.

## Assumptions

- Full deletion of DNP-to-MA export is intended, not a temporary hide.
- No external notebook/manual script is treated as public API for `convert_dnp_to_metaboanalyst`.
- Manual handoff means opening DNP artifacts directly, not creating a replacement global export button.
- `SpecNorm+PQN` remains the Step 3 default.
- Long guidance belongs in logs, not in method selector copy.
