# PRD / Issue：Codebase design 邊界與模組命名健康檢查

- 狀態：In progress（以整合 #33／#34 後的 tree 校準；slice 1 已實作）
- 類型：Engineering / maintainability（characterization parity，不改行為）
- 範圍：`src/metabolomics/` 的套件邊界與命名，不含科學演算法變更
- 產出目標：一份可執行的重新分類提案；本文件本身**只讀不改** production 程式碼
- 觀察基準：`codex/integrate-issues-33-34`（含 #33 explicit ISTD mapping 與
  #34 design-identifiability receipt）

---

## 1. 背景與動機

DNP v2 的科學契約（Step 1–4 的責任邊界、fail-closed 規則、ISTD mapping 與
identifiability receipt）已在整合後的 `README.md`、`AGENTS.md`、
`docs/algorithms/` 對齊。
但**程式碼的封裝邊界（package/module 命名與歸屬）落後於科學契約**：好幾個模組
的所在位置與名稱，會誤導讀者（人或 agent）對「這是什麼、屬於哪一層」的判斷。

本檢查只看 codebase design 面向：分類是否對、邊界是否誠實、命名是否名實相符。
不評估數值正確性，也不要求改變任何 runtime 行為。

## 2. 現狀（observed facts）

套件結構（`src/metabolomics/`）：

```
processors/   istd, qc_lowess, normalization, qc_batch_scaling   （Step 1–4）
gui/          Tkinter legacy app + workflow compatibility shim + theme tokens
gui_qt/       active PySide6 app/controller/view support
utils/        17 個 Python 模組，混合通用 helper 與 domain contract
adapters/     preprocessing_to_dnp
```

入口點：`Data_Normalization_program_v2.py` 與 `python -m metabolomics` 都啟動
`metabolomics.gui_qt.app`。

## 3. 健康的部分（先講對的，避免過度否定）

這些邊界是**乾淨、可保留**的，重構時不要動：

- **`processors/` 分層正確**：4 個 processor 之間**無 cross-processor import**、
  **無 `processor → gui` 反向依賴**；依賴只向下流到 `utils/`。對外契約
  （`.main(...) → ProcessingResult`，`status` 為 `WorkflowOutcome`，序列化後為
  `"succeeded"|"skipped"`）穩定且與 README「Python API」一致。命名對齊 workflow contract
  （`qc_batch_scaling` = Step 4、`qc_lowess` = Step 2 …）。
- **`adapters/preprocessing_to_dnp`**：邊界誠實，明確表達「外部 ms-preprocessing
  格式 → DNP input 格式」的轉換責任，命名與 docstring 一致。
- **`utils/__init__` 的 lazy facade**：以 `__getattr__` 延遲載入、curated 匯出。
  哪些模組未被 facade 收錄是 observed fact；是否代表刻意的 domain 分類仍是 inference。

## 4. 問題（design smells，依嚴重度排序）

### P1 — `gui/` 仍混合「legacy surface + compatibility shim + Qt 資源」

`gui/` 這個名字目前同時代表三種不同的東西：

| 檔案 | 實際身分 | 誰在用 |
| --- | --- | --- |
| `gui/app.py`（`import tkinter`） | **非 production entrypoint 的 legacy GUI** | production code 不 import；多個 GUI／isolated-import tests 仍引用 |
| `gui/workflow.py` | `metabolomics.workflow` 的 compatibility re-export | 僅相容性測試；production internal imports 已移除 |
| `gui/theme.py` | 目前實際為 Qt-only design tokens | active `gui_qt/app.py`、`gui_qt/qss.py` |

後果：

1. **legacy surface 與 active surface 難以區分**：兩個入口點都不碰
   `gui/app.py`，但它仍被多個測試 import。證據支持「非出貨 legacy GUI」，
   不足以在本 issue 直接判定可刪。
2. **workflow state 的主要錯位已由 slice 1 解決**：`WorkflowState` /
   `StepState` 現在住在 `metabolomics.workflow`；舊 GUI 路徑只為未知外部 consumer
   暫留 shim，不再是 production dependency。
3. **theme 邊界仍名實不符**：active GUI 是 `gui_qt/`，workflow dependency 已移出，
   但 Qt app／QSS 仍必須從名為 `gui` 的 legacy 容器取得 theme tokens。

### P2 — `gui/` vs `gui_qt/` 沒有任何命名說明誰是 canonical

新讀者（或 agent）光看名字會合理假設 `gui` 是主 GUI、`gui_qt` 是某個變體，
實際完全相反。兩個平行 GUI 套件並存、且命名暗示與事實顛倒，是導航陷阱。

### P3 — `utils/` 是 grab-bag，把「通用 helper」和「領域子系統」壓平成同一層

`utils/` 底下同時住著兩種本質不同的東西：

- **真·通用 helper**（與 metabolomics 領域無關，可複用）：
  `safe_math`、`file_io`、`constants`、`console`、`data_helpers`、
  `excel_colors`、`excel_format`。
- **實為領域邏輯 / 產品面**（誤貼為 utils）：
  - `design_identifiability`：有 README 專段（Step 2/3 的
    `Design_Identifiability` receipt）、`docs/algorithms/design_identifiability.md`、
    以及 `AGENTS.md` 的科學 guardrail。這是**一級科學診斷子系統**，不是 util。
  - `istd_mapping`：定義 `ISTD_Mapping` workbook schema、feature-level provenance、
    monitoring receipt 與 correction rejection states；同樣是 Step 1 domain module。
  - `sample_classification`、`data_validation`：領域規則集中地。
  - `normalization_contract`：Step 3 method 的**共享契約來源**，被
    `processors/normalization` 與 `metabolomics.workflow` 同時消費——是 domain contract 而非 util。
  - `workbook_input`：workbook 輸入 policy。

**內部證據顯示 facade 的收錄範圍與檔案樹不一致**：`utils/__init__` 匯出了
`safe_math`、`file_io`、`sample_classification` 等，但未收錄
`design_identifiability`、`data_validation`、`workbook_input`、
`normalization_contract`、`istd_mapping`（這些只能用完整路徑 import）。
「未收錄」本身不證明原作者刻意分類，但目錄名 `utils` 確實讓「哪些是可複用
薄工具、哪些是有科學契約的深模組」在檔案樹上不可見。

### P4（Minor）— 文件語言與註解風格不一致

部分模組 docstring 用中文（`plotting`、`statistics`），部分用英文，屬 cosmetic，
不影響邊界；列出供一併決定風格基準，優先度最低。

## 5. 影響（誰受影響、可觀察損失）

- **人類維護者**：workflow 狀態機已移到 canonical top-level module；剩餘主要問題是
  `gui/` 仍同時承載 legacy app、compatibility shim 與 Qt-only theme，而科學
  identifiability 邏輯仍在 `utils/`。
- **AI agent 導航**：命名是 agent 決定「該讀哪個檔」的主要訊號。`gui` 含非 GUI、
  `utils` 含深科學模組，會讓 agent 讀錯層或漏讀契約。
- **契約可發現性**：`normalization_contract`、`design_identifiability` 這類有文件
  背書的產品面，被埋在 `utils/` 使其權重被低估，增加「繞過契約」的風險。

## 6. 漸進 slices（decision-oriented）

以下為獨立、漸進、可回滾的 slices。第一個 slice 已收斂，其餘仍需後續決策。

1. **第一個 slice：只搬 toolkit-agnostic workflow state（已實作）**
   - 已把 `gui/workflow.py` 的實作上移為 `metabolomics/workflow.py`。
   - active Qt、legacy Tk 與內部測試已改 import canonical path。
   - `metabolomics.gui.workflow` 暫留 compatibility re-export；不假設 repo 外沒有
     consumer，也不在這個 slice 決定 Tkinter 去留。
   - 不動 processor、workbook schema、科學演算法、theme 或 domain utils。
   - Characterization：canonical 與 legacy import 的 class/function identity 相同；
     production internal imports 已不再依賴 legacy path。
2. **後續才拆其他 GUI 身分**
   - `theme.py` 移到共用 UI 資源位置（或併入 `gui_qt/`，若確定不再有第二個 GUI）。
   - `gui/app.py`（Tkinter）依 `2026-04-25-dead-code-cleanup-plan.md` 決定退役或
     明確標記 legacy，並處理只為它存在的測試。
3. **消除 `gui` / `gui_qt` 命名歧義**：確認單一 canonical GUI 後，讓名稱直接反映
   （例如 active GUI 就叫 `gui/`，legacy 明確加 `_legacy` 或移除）。
4. **把 `utils/` 的深模組正名**：將 `design_identifiability`、`istd_mapping`、
   `normalization_contract` 等有科學契約者移入語意明確的位置（如 `metabolomics/design/`、
   `metabolomics/contracts/` 或各自的 domain 套件），`utils/` 只留真·通用 helper。
   以 `utils/__init__` facade 現有的「收 / 不收」清單作為第一版切分依據。
5. **（Minor）**統一 docstring 語言基準。

## 7. 驗收條件（Engineering：characterization parity）

- 屬 pure move / rename：**不改任何 runtime 行為**，`processors` 對外契約
  （`.main() → ProcessingResult`、輸出 workbook 內容）逐位一致。
- 通過既有 gate：
  `python -m pytest -m "not slow and not integration" -q`、scenario smoke、
  `ruff --select F401,F841,F821`、`git diff --check`。
- production internal imports 要一次更新到 canonical path；若 public usage 尚未
  調查，舊路徑保留明確 compatibility shim 與單一相容性測試。
- **不 bundle behavior change**：命名/搬移 PR 不夾帶演算法或 I/O 修改。

## 8. 停止條件 / 非目標

- 不在本 issue 內改任何科學演算法或 Step 邊界（那是 #33 等既有 issue 的範圍）。
- 不為「未來可能的第三個 GUI」預留抽象；抽象需 ≥2 個現存呼叫者才建。
- 若某項搬移會牽動 public API 且無足夠測試覆蓋，先補 characterization 測試再動。

## 9. 開放問題（需人決定）

1. active GUI 是否確定長期只有 PySide6 一套？目前 observable entrypoints 都是
   PySide6，但這仍決定 `gui/` 是否可直接正名、
   `theme` 是否併入 `gui_qt`。
2. `gui/app.py` Tkinter legacy：退役 vs 保留為對照？（連動其專屬測試去留。）
3. domain contracts 的最終新家：`domain/`、`contracts/`，或按 Step 分包；
   第一個 workflow-state slice 不依賴這個決定。

## 附錄：證據索引

- 入口點：`Data_Normalization_program_v2.py:9`、`src/metabolomics/__main__.py` → `gui_qt.app`
- `workflow.py:1` 是 canonical toolkit-agnostic state；
  `gui/workflow.py` 僅 compatibility re-export
- `gui/app.py:1` `import tkinter`；無 production importer，測試仍直接或間接引用
- `gui_qt/controller.py`、`gui_qt/app.py` 與 legacy `gui/app.py` import
  `metabolomics.workflow`
- `utils/design_identifiability.py`、`utils/istd_mapping.py`、
  `utils/sample_classification.py`、`utils/data_validation.py`
- `utils/__init__.py` facade 未收 `design_identifiability` / `data_validation` /
  `workbook_input` / `normalization_contract` / `istd_mapping`
- `processors/` 無 cross-processor、無 processor→gui import（健康基準）
