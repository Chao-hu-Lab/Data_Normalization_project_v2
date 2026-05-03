# 濃度標準化工具 (Concentration Normalization)

## 📋 概述

這個工具是 DNP active workflow 的 Step 3，預設執行 `SpecNorm+PQN`，也支援手動選擇 `PQN`。它不是 cross-batch correction 模組，也不會把 Step 4 的 QC batch scaling 當成預設 final output。本工具的核心任務，是在 Step 1/Step 2 技術穩定化之後，依據 specimen-reference 欄位與 QC reference，產生可供後續統計分析使用的 Step 3 normalized workbook。

本工具採用的是**混合標準化策略**。Step 3 預設使用 `SpecNorm+PQN`：先用 specimen-reference value 做 specimen-reference division，再使用 PQN 處理整體代謝組學譜的尺度差異，最後保留 SpecNorm+PQN 的輸出尺度，不再以原始 feature 中位數乘回。也可以手動選擇單獨使用 `PQN`。這種策略同時處理「個體樣本 reference 差異」和「群體 spectrum 尺度差異」，並避免在 DNA、蛋白質等小 reference 值情境中把強度再乘一次強度。

在本專案中，`SpecNorm` 的全名採 **Specimen-reference normalization**。它不是 spectral normalization，也不是 total-sum normalization；實作上就是「真實樣本除以 `SampleInfo` 中可信的 per-sample reference 值，QC 樣本在此階段不除」。

新版 Step 3 的責任邊界已明確收斂為 **concentration normalization**。它可以在條件合適時使用 QC 來建構 PQN reference，但不應被實作成 cross-batch correction，更不應把 non-shared QC 擴張成 global harmonization 工具。

## 🎯 為什麼我們需要濃度標準化？理解問題的本質

### 代謝組學數據中的「濃度困境」

在進入技術細節之前，讓我們先理解為什麼標準化如此重要。想像您正在進行一個研究，比較健康人和糖尿病患者的尿液代謝物。您收集了 100 個樣本，送到質譜儀分析，得到了數千個代謝物的強度數據。但這裡有一個隱藏的陷阱：這些「強度」數值並不能直接告訴您代謝物的真實生物學濃度，因為它們受到太多非生物學因素的干擾。

讓我們用一個具體的例子來說明。假設有兩個糖尿病患者 A 和 B，他們血液中的葡萄糖濃度其實是一樣的，都是 10 mmol/L（這是真實的生物學狀態）。但是，患者 A 前一天喝了很多水，他的尿液非常稀釋；患者 B 喝水較少，尿液比較濃縮。當您在質譜儀上分析這兩個尿液樣本時，會發現：

- 患者 A 的葡萄糖訊號強度：100,000（低，因為尿液稀釋）
- 患者 B 的葡萄糖訊號強度：500,000（高，因為尿液濃縮）

如果您直接比較這兩個數值，會誤以為患者 B 的葡萄糖濃度是患者 A 的五倍！但實際上，這個五倍的差異完全來自於尿液的稀釋程度差異，而非真正的代謝狀態差異。這就是「濃度困境」：質譜儀測量的是「單位體積中的分子數量」，但不同樣本的「體積濃度」本身就不同。

### 標準化的三大核心目的

理解了問題之後，我們就能明白標準化的目的了。標準化不是為了「美化數據」或「製造差異」，而是為了「還原真相」。具體來說，標準化有三個核心目的：

**第一個目的：消除非生物學的技術變異。** 這包括樣本的稀釋程度差異、總濃度差異等等。就像上面的例子，我們需要將患者 A 和 B 的數據調整到相同的「濃度基準」上，這樣才能公平比較他們的代謝狀態。這就像是在比較不同地區的房價時，您需要先將它們都換算成相同的貨幣單位一樣。

**第二個目的：提升數據的可比性和統計檢定力。** 想像一下，如果您的數據中有一半樣本很濃縮，一半很稀釋，那麼即使真正的生物學差異很明顯，也會被這些技術噪音淹沒。標準化後，技術變異降低了，真正的生物學訊號就能更清楚地浮現出來。這就像是在嘈雜的環境中聽音樂，降噪耳機可以讓您更清楚地聽到旋律。

**第三個目的：讓數據符合統計方法的假設。** 許多統計方法（如 t 檢定、ANOVA）假設數據符合某些特性，比如變異數同質性、正態分布等。原始的代謝組學數據通常不符合這些假設，但適當的標準化可以改善數據的統計特性，讓後續的統計分析更可靠。這就像是在使用一個工具之前，先確保工作環境符合這個工具的操作條件。

### 為什麼選擇混合標準化策略？單一方法的局限性

您可能會問：既然標準化這麼重要，那麼是不是有一種「萬能」的標準化方法可以解決所有問題呢？很遺憾，答案是否定的。代謝組學數據的複雜性決定了我們需要結合多種策略。讓我解釋為什麼。

**SpecNorm 的強項與弱點。** `SpecNorm+PQN` 會先用 `SampleInfo` 中具 reference 語意的數值欄位做 specimen-reference division。這個欄位可以是 `Creatinine_mg_dL`、`DNA_mg/20uL`、蛋白質含量，或其他實驗設計定義的 normalization adduct / reference；`Injection_Volume` 這類操作 metadata 會被排除。這一步能處理每個真實樣本自己的濃度、載量或萃取量差異，但不應被解讀成 batch correction。

舉個例子：如果兩個 DNA adductomics 樣本的 DNA input 不同，直接比較原始強度會把樣本載量差異混入分析。`SpecNorm+PQN` 會先除以 DNA 或其他 reference 值，再用 PQN 處理整體 spectrum 的尺度差異。

**PQN 的強項與弱項。** PQN (Probabilistic Quotient Normalization) 是一種群體導向的標準化方法。它的核心假設是：大部分代謝物在不同樣本間應該維持穩定的比例，只有少數代謝物會因為生物學差異而改變。基於這個假設，PQN 計算每個樣本相對於「參考譜」的整體稀釋因子，然後用這個因子來標準化所有代謝物。PQN 的優點是能夠處理整體尺度的系統性偏移，而且對極端值穩健（它使用中位數而非平均值）。但它的局限是：它是一種「一刀切」的方法，對所有樣本使用相同的標準化邏輯，無法針對性處理個體特異性的濃度差異。

**混合策略的協同效應。** SpecNorm（specimen-reference normalization）處理每個真實樣本的 reference 差異，而 PQN 處理整體 spectrum 的稀釋 / scale factor。兩者結合，就像是「先校正樣本載量，再校正整體譜尺度」，讓不同樣本回到更可比較的基準上。

用一個生活化的比喻：如果您要比較不同國家的人均收入，首先需要換算成相同貨幣（類似 SpecNorm 處理 reference 單位），再考慮購買力平價（類似 PQN 處理整體尺度）。兩者回答的是不同層次的可比性問題。

## 🔧 核心功能

### 1. Step 2 驅動的 reference strategy selector

工具現在會直接讀 Step 2 `LOESS_summary` / advanced statistics sheet，結合 batch 結構與 QC sharedness 回報 PQN 標準化的參考脈絡，而不是只看 `qc_count` 和 `qc_cv_median`。

目前的主策略包括：
- `QC_REFERENCE`: 有 QC 樣本時，以 QC median spectrum 作為 PQN reference

Adductomics 目前採微量分析政策：不論 Step 2 LOESS 後的穩定性如何，都不退回 all-sample robust median。Step 2 contract、QC sharedness 與 batch 設計會保留在 report 中作為解讀脈絡，但不再觸發全樣本 reference fallback。

如果工作簿沒有 QC 樣本，Step 3 會明確中止，而不是用所有樣本建立 robust median reference。

### 2. 混合標準化流程

#### 步驟 1: 樣本分類

自動識別並分類樣本：
- **QC 樣本：** 從 `Sample_Type` 欄位或樣本名稱識別
- **真實樣本：** 非 QC 的生物樣本

#### 步驟 2: SpecNorm（specimen-reference normalization，僅真實樣本）

**原理：** 使用 `SampleInfo` 中的數值型 reference 欄位，將真實樣本強度除以該樣本的 reference 值。QC 樣本不參與這個 division，因為 QC 通常沒有樣本特異性的生物 reference。

**校正公式：**
```
SpecNorm 強度 = 原始強度 / 該 specimen reference 值
```

**實例：**
- 樣本 A `DNA_mg/20uL` = 1.5
- 樣本 B `DNA_mg/20uL` = 3.0
校正後，樣本 A 的特徵強度會除以 1.5，樣本 B 會除以 3.0。舊版曾在這一步再乘回參考值中位數，也曾在 PQN 完成後進行 feature-specific scale-back；新版兩者都不做，避免把已經合理的 SpecNorm+PQN 強度再次放大。

**注意：** QC 樣本不進行 specimen-reference division，因為 QC 通常是混合或技術樣本，沒有對應的個體 reference。

#### 步驟 3: PQN 標準化（所有樣本）

**PQN 原理：**

PQN 假設大部分代謝物在樣本間應該維持穩定比例，只有少數代謝物因生物學差異而改變。它透過計算每個樣本相對於參考樣本的「商數中位數」來估算整體稀釋因子。

**演算法步驟：**

1. **選擇參考樣本：** 使用 QC median spectrum；Step 2 advanced stats 與 batch/QC 設計只作為 report context
2. **計算商數矩陣：** 每個樣本的每個代謝物除以參考值
3. **估算稀釋因子：** 取每個樣本的商數中位數
4. **標準化：** 每個樣本除以其稀釋因子

**為什麼用中位數而非平均值？** 中位數對極端值穩健，即使有少數代謝物濃度大幅改變（生物學差異），也不會影響稀釋因子的估算。

**數學表達：**
```
對於樣本 j:
  商數向量 q_j = [m_1j/m_1ref, m_2j/m_2ref, ..., m_nj/m_nref]
  標準化因子 f_j = median(q_j)
  標準化強度 m'_ij = m_ij / f_j
```

#### 步驟 4: SpecNorm+PQN rescaling

若選擇 `SpecNorm+PQN`，PQN 完成後不再對每個 feature 乘回 Step 3 input 的非 QC 實驗樣本中位數：

```
final_ij = pqn_after_specnorm_ij
```

這等同於在 rescaling 步驟選擇 `None` 或常數 `1`。在 `DNA_mg`、蛋白質含量等 reference 中位數很小但原始訊號很大的資料中，這能避免把「已除以 reference 後仍是健康大數值」的結果再乘回原始強度中位數，造成尺度災難。

### 3. 多維度品質評估

工具提供六種指標評估標準化效果：

#### A. CV% 改善（變異係數）

最直觀的評估指標，反映數據穩定性。

**計算：** CV% = (標準差 / 平均值) × 100%

**評估重點：**
- **QC CV%：** 應該降低（技術重現性提升）
- **特徵 CV% 改善比例：** 應該 > 50%（多數代謝物變異降低）

**為什麼 CV% 重要？** 低 CV% 表示技術變異小，數據品質高。標準化的主要目的之一就是降低 CV%。

#### B. 樣本總強度 CV%

評估樣本間「整體代謝組學譜強度」的均勻性。

**意義：**
- 標準化前：總強度 CV% 高，反映尿液濃度等非生物學因素的影響
- 標準化後：總強度 CV% 低，表示樣本間達到相似的「總量」基準

理想情況下，標準化後所有樣本的總強度應該接近，CV% < 10%。

#### C. 正態性改善

使用 Shapiro-Wilk 檢定評估 log 轉換後數據的正態性。

**為什麼重要？**

許多統計方法（t-test, ANOVA, 線性回歸）假設數據符合正態分布。代謝組學數據通常呈現右偏分布，標準化結合 log 轉換可以改善正態性。

**評估：**
- 標準化前正態性通過率
- 標準化後正態性通過率
- 改善幅度（%）

**結果解讀：**
- 改善 > 10%: 正態性顯著改善（為後續參數統計方法奠定基礎）
- 改善 0-10%: 輕微改善
- 改善 < 0%: 未改善（可能需要其他轉換方法）

#### D. 樣本間相關性

計算樣本間的 Spearman 相關係數矩陣，評估：
- **平均相關性：** 理想值約 0.6-0.8（樣本有相似性但保留個體差異）
- **相關性標準差：** 應該降低（樣本間相似度更均勻）

**為什麼分析相關性？**

過高的相關性標準差表示某些樣本異常相似或異常不同，可能是技術變異或離群值。標準化應該降低這種不均勻性。

#### E. PCA 分離評估

評估標準化前後 PCA 空間中的樣本分布變化：
- 標準化可能影響樣本的相對位置
- 好的標準化應該保留生物學組別的分離

**警示：** 如果標準化後不同生物學組別在 PCA 上混合，可能是過度標準化。

#### F. 標準化因子分析

檢查 PQN 標準化因子的分布：
- **範圍：** 過大範圍（如 0.1-10）可能表示樣本間稀釋差異極大
- **離群值：** 極端因子（< 0.5 或 > 2.0）的樣本需要注意

### 4. 與 Step 4 的新邊界

Step 3 現在是 active scientific workflow 的終點。GUI 的手動開啟 workbook / plots，以及正常的 downstream workbook 選擇都應以 Step 3 output 為主：
- `SpecNorm_PQN_Result`
- `PQN_Result`

`QC_Batch_Scaling_result` 只保留 legacy fallback 意義，不能再被當成預設 final normalized output。

### 5. 豐富的視覺化輸出

工具自動生成 6 類圖表，全面評估標準化效果：

**1. Density Plot（密度分佈圖）：**
- 顯示標準化前後所有樣本的強度分布
- 理想：標準化後分布更集中、重疊度更高

**2. Boxplot（盒鬚圖）：**
- 比較標準化前後每個樣本的中位數和分散程度
- 理想：標準化後箱體高度更一致

**3. Sample Total Intensity Distribution（樣本總強度分佈）：**
- 顯示每個樣本的總代謝物強度
- 理想：標準化後總強度接近，分布更窄

**4. CV% Distribution（CV% 分佈圖）：**
- 標準化前後特徵 CV% 的直方圖
- 理想：分布左移（CV% 降低）

**5. PCA Comparison（PCA 對比圖）：**
- 並排顯示標準化前後的 2D PCA 圖
- 評估樣本分布變化和組別分離性

**6. Correlation Heatmap（樣本相關性熱圖）：**
- 標準化前後樣本間 Spearman 相關性矩陣
- 理想：標準化後顏色更均勻（相關性更一致）

## 📊 輸入檔案格式

輸入檔案應為經過前處理的 Excel 檔案，包含：

### 必要工作表

**1. 數據工作表（按優先順序）：**
- `QC LOWESS result`（LOWESS 校正後）
- `ISTD_Correction`（ISTD 校正後）
- `RawIntensity`（原始數據）

新版 active path 不再把 `Combat_Corrected` 或其他 cross-batch correction sheet 視為 Step 3 的預設上游。

**2. SampleInfo 工作表：**
必要欄位：
- 第一欄：樣本名稱（必須與數據工作表列名匹配）
- `Sample_Type`: 樣本類型（標記 QC 樣本，如 "QC", "QC1"）
- `Batch`: 供 Step 3 判斷 batch 結構與 QC sharedness
- 數值型 specimen-reference 欄位：用於 `SpecNorm+PQN`，欄名需具 reference 語意，例如 `creatinine`、`dna`、`protein`、`concentration`、`reference` 或 `amount`；`Injection_Volume` 等操作 metadata 會被排除。欄名若包含 `creatinine` 會標示為 `Creatinine`，其他 reference 欄位會標示為 `Normalization_adduct`

**3. Step 2 advanced statistics sheet：**
- `LOESS_summary`（canonical）
- 或 legacy `QC_LOESS_Advanced Statistics`

Step 3 會從這張表讀取 `Decision_Status`, `Kendall_Tau`, `Trend_pvalue`, `LOESS_R2`, `LOESS_RMSE`, `Normalized_RMSE`, `Valid_QC_Count`, `Removed_QC_Outliers`, `Outside_QC_Range_Count` 等欄位。

### 注意事項

- Reference 值必須是正數；缺失或無效值不會用於真實樣本的 specimen-reference division
- 預設 `SpecNorm+PQN` 若找不到可用 specimen-reference 欄位，Step 3 會明確中止
- 若只需要 QC-based PQN，請選擇 `PQN`

## 🚀 使用方法

### 程式化調用
```python
from metabolomics.processors import normalization

result = normalization.main(
    input_file="Step2_QC_LOESS.xlsx",
    normalization_method="SpecNorm+PQN",
)
print(f"處理了 {result.metabolites} 個代謝物")
print(f"輸出檔案: {result.output_path}")
```

## 📁 輸出結果

### 輸出資料夾結構

GUI / workflow session output:

```text
run_[timestamp]/
├── Step3_Normalized_PQN.xlsx
├── Step3_Normalized_SpecNorm_PQN.xlsx
└── plots/
    ├── Step3_CV_*.png
    ├── Step3_RLE_*.png
    ├── Step3_Density_*.png
    ├── Step3_Dratio_*.png
    └── Step3_Scatter_*.png  # SpecNorm+PQN only
```

Direct processor output without `session_dir` uses timestamped files under `output/`.

### Excel 檔案內容

**`PQN_Result` / `SpecNorm_PQN_Result` 工作表：**
- 標準化後的代謝物強度數據
- 保留 `Sample_Type` 資訊行（若上游資料包含）

**`PQN_summary` / `SpecNorm_PQN_summary` 工作表：**
- 標準化方法說明
- 品質評估指標
- 參數設定記錄

輸出 workbook 也會保留上游資料工作表與 `SampleInfo`，方便追溯 Step 3 的 before/after 指標來源。

## 🔍 結果解讀建議

### 終端機統計摘要

執行完成後，終端機會輸出品質評估摘要：

```
📈 標準化質量評估摘要:
  中位數CV%改善: 22.5% → 14.8%
  CV%降低: 7.7% (34.2%)
  改善特徵比例: 68.3%
  樣本總強度CV%: 45.2% → 8.9%
  樣本間平均相關性: 0.6234 → 0.6891
  
  整體評分: 100/100 ★★★★★ (優秀)
```

**評分機制：**
- CV% 改善 > 0: +25 分
- 樣本總強度 CV% 改善 > 0: +25 分
- 相關性標準差降低: +25 分
- 改善特徵比例 > 50%: +25 分

**評級：**
- 75-100 分: ★★★★★ 優秀
- 50-74 分: ★★★★ 良好
- 25-49 分: ★★★ 尚可
- 0-24 分: ★★ 需改進

### 圖表評估

**Density Plot:**
- **理想：** 標準化後曲線高度一致、重疊度高
- **警示：** 某些樣本曲線仍明顯偏移，可能是離群值

**Boxplot:**
- **理想：** 標準化後盒體中位線接近同一水平
- **警示：** 仍有極端長鬚或離群點

**Sample Total Intensity:**
- **理想：** 標準化後分布窄且集中
- **警示：** 仍有樣本總強度差異大（可能 reference division 或 PQN 尺度校正不足）

**CV% Distribution:**
- **理想：** 標準化後直方圖左移，峰值在 10-20% 區間
- **警示：** 分布右移或雙峰（部分代謝物未改善）

**PCA Comparison:**
- **理想：** 樣本分布更緊湊但生物學組別仍可區分
- **警示：** 組別混合（過度標準化）或仍有明顯技術變異聚集

**Correlation Heatmap:**
- **理想：** 標準化後顏色更均勻（藍色較少）
- **警示：** 出現異常低相關的樣本（深藍色）

## 💡 常見問題

**Q: 什麼時候需要 `SpecNorm+PQN`？**

當每個真實樣本都有可信的數值型 specimen-reference 欄位時，例如尿液 creatinine、DNA input、蛋白質含量，或實驗定義的 normalization adduct。沒有這類 reference 時，請使用 `PQN`。

**Q: 如果沒有 reference 欄位怎麼辦？**

預設 `SpecNorm+PQN` 會中止並要求補上可用欄位。若只想執行 PQN，請在 GUI 或程式化呼叫中選擇 `PQN`。

**Q: 標準化後 CV% 反而上升？**

可能原因：
1. 原始數據已經過良好校正，標準化引入不必要調整
2. Reference 欄位不可靠或不適合目前樣本
3. QC 樣本品質不佳，PQN 參考不穩定

建議：檢查 reference 值分布、QC CV%、以及 Step 2 `LOESS_summary`。目前 adductomics 政策不會自動 fallback 到 all-sample robust median；QC 不穩定會作為 report warning。

**Q: 為什麼 QC 樣本不做 SpecNorm？**

QC 樣本通常是混合或技術樣本，沒有個體 reference 值。對 QC 進行 specimen-reference division 會引入不必要的變異。

**Q: PQN 標準化因子的合理範圍是多少？**

一般在 0.5-2.0 之間。若某個樣本的因子 < 0.3 或 > 3.0，建議：
1. 檢查該樣本的原始數據是否異常
2. 確認 reference 值是否正確
3. 考慮是否為真實的生物學極端樣本

**Q: 標準化後應該做什麼？**

標準化是數據預處理的最後一步，接下來可以進行：
1. **數據轉換：** Log transformation, Pareto scaling
2. **統計分析：** 差異代謝物鑑定（t-test, ANOVA）
3. **多變量分析：** PLS-DA, OPLS-DA
4. **功能分析：** 代謝通路富集、網路分析

## ⚙️ 技術細節

### 依賴套件
```
pandas, numpy, scipy, scikit-learn, matplotlib, openpyxl
```

### 核心演算法
- **SpecNorm（specimen-reference normalization）：** 真實樣本除以 per-sample reference 值
- **PQN 標準化：** Dieterle et al. (2006) 的 PQN 演算法
- **正態性檢定：** Shapiro-Wilk test (α = 0.05)
- **相關性分析：** Spearman rank correlation

### 參數設定
- PQN reference：有 QC 時使用 QC median spectrum；沒有 QC 時明確中止
- Step 2 context：讀取 `LOESS_summary` 作為 report context，不觸發 all-sample fallback
- 正態性顯著性水平：α = 0.05

## 📝 注意事項

1. **Reference 欄位：** 預設 `SpecNorm+PQN` 需要每個真實樣本有可信的數值型 specimen-reference
2. **Reference 值品質：** 確保 reference 測量準確，且符合目前實驗設計
3. **QC 樣本：** 建議至少 3 個 QC 樣本以獲得穩定的 PQN 參考
4. **數據前處理：** 建議先完成 ISTD 與 QC-LOWESS。新版 active path 不再預設依賴 ComBat 或其他 cross-batch correction sheet
5. **離群值處理：** 標準化前應先移除明顯的技術離群值

## 🔄 數據預處理流程建議

完整的新版 active workflow：

```
RawIntensity
    ↓
[1] ISTD Correction (消除基質效應、離子化差異)
    ↓
[2] QC-LOWESS (消除時間相關漂移)
    ↓
[3] Normalization (標準化樣本濃度和尺度) ← 本工具
    ↓
[4] QC Batch Scaling diagnostics-only (可選，不是 active correction)
    ↓
[5] Data Transformation (log, Pareto) ← 統計分析前
    ↓
Statistical Analysis
```

每個步驟都有其特定目的，順序很重要。

---

**版本:** v2.0  
**更新:** 2025  
**環境:** Python 3.8+  
**適用樣本類型:** 有可信數值型 specimen-reference 的樣本（`SpecNorm+PQN`） / 有 QC reference 的樣本（`PQN`）
