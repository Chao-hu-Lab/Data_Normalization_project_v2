# QC-LOWESS 批次內 drift 校正工具

## 📋 概述

本工具針對經過 ISTD 校正的代謝組學數據執行 QC-LOWESS (Locally Weighted Scatterplot Smoothing) 的**批次內 run-order drift 校正**。它的責任邊界是分析每個 batch 內 QC 樣本的時間序列變化，建立 batch-local 漂移趨勢模型並校正同 batch 樣本，進一步提升數據穩定性。

這一版的 Step 2 **不是 cross-batch alignment 模組**。它不應使用跨批次 pooled target，也不應被解讀為成熟的 batch harmonization 工具。

## 🎯 為什麼需要 QC-LOWESS？

**ISTD vs LOWESS 的互補性:**

ISTD 校正處理「樣本層級」差異（樣本間的基質效應、離子化效率差異），而 LOWESS 處理「時間序列」差異（分析序列中的儀器漂移）。即使使用內標，質譜儀在長時間運行中仍可能因離子源污染、質量校準漂移等因素產生系統性訊號衰減或增強。QC 樣本作為時間錨點，讓我們能建模並校正這種 batch-local 時間漂移。

## 💡 LOWESS 原理簡介

LOWESS 是一種非參數局部加權回歸方法。對於每個樣本位置，LOWESS 會考慮其鄰近 QC 樣本的強度值，距離越近權重越高，擬合出一條平滑的趨勢曲線。關鍵參數 `frac` 決定「鄰域大小」：frac = 0.5 表示使用 50% 的 QC 樣本來估算局部趨勢。

## 🔧 核心功能

### 1. Batch-local target 與動態 LOWESS 參數

每個 feature 的 correction target 來自**當前 batch 的 QC 行為**，而不是跨批次 `global_qc_median`。在此基礎上，再根據 QC 樣本數量與穩定性自動選擇 `frac` 值：

| 條件 | frac 策略 |
|-----------|------|
| 有效 QC < 6 | 不擬合，該 batch × feature 維持原值 |
| 有效 QC 6–7 | 只允許通過端點、LOOCV、單調趨勢與 drift/noise gates 的 log2-linear fallback |
| 有效 QC ≥ 8 | 進入 batch-local LOWESS；仍須通過後續決策 gate |
| QC CV 高於 acceptable 門檻 | 0.8 |
| QC CV 高於 excellent 門檻 | 0.7 |
| 較穩定 QC | `clip(0.85 - n/50, 0.5, 0.75)`；有效 QC ≤10 時下限為 0.7 |

此動態策略避免樣本數不足時過擬合，或樣本充足時過度平滑，同時維持 Step 2 僅做 batch-local drift correction 的角色。

### 2. IQR 離群值檢測與擬合前 gate

在 LOWESS 擬合前，使用四分位距 (IQR) 方法識別異常 QC 樣本：
- 界限：Q1 - 1.5×IQR 至 Q3 + 1.5×IQR
- 保護機制：IQR outlier filter 只有在移除後仍保留至少 70% 且不少於 5 個 QC 時才會採用；只要篩選後剩 6–7 點，就維持原值，不會再用被全資料挑選過的 QC 執行 LOOCV fallback。

這確保 LOWESS 不被極端值誤導，同時保留足夠數據點進行可靠擬合。若離群值移除後剩餘點數不足，feature 會標記為 `outlier_filtering_left_too_few_points` 而直接跳過校正。

#### 6–7 QC 的 log-linear fallback

fallback 在 `log2(area)` 上比較 intercept-only 模型與
`log2(area) ~ Injection_Order`。只有以下條件全部成立才套用：

1. batch 的 `Injection_Order` 全部是實測、完整且唯一，有效 QC 並覆蓋第一與最後 injection order；
2. leave-one-QC-out RMSE 相對 intercept-only 至少改善 10%；
3. Kendall `|tau| >= 0.5` 且 `p < 0.05`；
4. 線性模型預測的首尾 drift amplitude 大於模型 residual RMSE。

第 2、3 點的 10%、`|tau| >= 0.5` 與 `p < 0.05` 是本專案採用的保守
操作門檻，不是文獻中的通用硬標準。若模型需要把任何 correction factor
截斷到 `[0.5, 2.0]`，該 feature 會判為不穩定並維持原值。

令 `delta = median(fitted_QC) - fitted(order)`。6–7 QC fallback 不會把
稀疏 QC 估計出的完整斜率直接套到 study samples；本專案採用 0.5
log-scale shrinkage：

`log2(corrected) = log2(area) + 0.5 × delta`。

因此實際 area-scale correction factor 是 `2^(0.5 × delta)`，也就是完整
線性 factor `2^delta` 的平方根。0.5 是本專案針對稀疏 QC 尾端風險採用的
保守操作值，不是通用文獻常數。穩定性 gate 仍先檢查未 shrink 的完整模型
factor；只要 `2^delta` 需要截斷到 `[0.5, 2.0]`，就拒絕整個 correction，
不能用 shrinkage 規避原本的 clamp 防線。`cv_after` 與
`cv_improvement` 則依實際套用 0.5 shrinkage 後的 QC 值計算。

任一 gate 未通過便維持原值，並分別記錄 endpoint、LOOCV、monotonic
trend 或 drift/noise reason。這是稀疏 QC 的保守 fallback，不是把
LOWESS 門檻降低到六點。

### 3. 趨勢顯著性驗證與 skip-correction

並非所有代謝物都需要校正。工具會先驗證是否存在顯著的時間漂移趨勢：

#### A. Mann-Kendall 趨勢檢定

這是一種非參數檢定，用於判斷時間序列是否存在單調趨勢（持續上升或下降）。它的優勢在於不需假設數據符合正態分布，對離群值也具穩健性。

**檢定輸出:**
- **p-value:** p < 0.05 表示存在顯著趨勢（95% 信心水準）
- **Kendall's tau (τ):** 範圍 -1 到 +1
  - τ → +1: 強上升趨勢
  - τ → -1: 強下降趨勢
  - τ → 0: 無明顯趨勢

**實務意義:** 如果 p ≥ 0.05 且 τ 接近 0，表示 QC 樣本在整個實驗期間非常穩定，強行校正可能引入不必要的雜訊。

#### B. R² (決定係數)

R² 衡量 LOWESS 曲線解釋 QC 數據變異的比例：

```
R² = 1 - (殘差平方和 / 總平方和)
   = 1 - Σ(觀測值 - 擬合值)² / Σ(觀測值 - 平均值)²
```

**解讀:**
- **R² = 1.0:** 完美擬合，所有 QC 點都落在趨勢線上
- **R² = 0.5:** 中等擬合，趨勢線解釋 50% 的變異
- **R² < 0.1:** 擬合不佳，可能無明顯趨勢或趨勢過於複雜

**判斷邏輯:** 當 trend 很弱、`Kendall's tau` 接近 0、`Trend_pvalue` 不顯著、`R²` 很低且 normalized drift amplitude 很小時，工具判定 `no_drift_detected`，保持原始數據不變。這避免了對穩定代謝物的過度校正。

#### C. RMSE (均方根誤差)

RMSE 衡量 LOWESS 擬合值與實際 QC 觀測值的平均偏差：

```
RMSE = √[Σ(觀測值 - 擬合值)² / n]
```

相較於 R²（相對擬合優度），RMSE 提供絕對誤差的量級。例如：
- RMSE = 100 且平均強度 = 10,000 → 相對誤差 1%（良好）
- RMSE = 100 且平均強度 = 500 → 相對誤差 20%（不佳）

兩者結合使用，R² 告訴我們「趨勢捕捉得如何」，RMSE 告訴我們「偏差有多大」。

### 4. 校正因子計算、clamp 與 edge reporting

校正過程：
1. 計算 QC 中位數作為「參考水平」
2. LOWESS 預測每個樣本位置的漂移值
3. 校正因子 = 參考水平 / 預測漂移值
4. 校正強度 = 原始強度 × 校正因子

**安全限制:** 校正因子限制在 [0.5, 2.0] 範圍內，避免極端校正導致數據失真。

只有 `Decision_Status = success` 的 batch 會把校正值寫入主輸出與 QC CV 計算來源；其他狀態（包括 `no_drift_detected` 與各種 rejection）一律保留原始強度。位於有效 QC injection-order span 之外的樣本也保留原始強度，不做 flat extrapolation 校正。

Step 2 只有在至少一個 batch × feature 實際套用校正時回傳 `SUCCEEDED`；若全部 task 都因 QC 不足而未校正，回傳 `SKIPPED / insufficient_valid_qc_for_correction`，若 QC 足夠但沒有任何 task 通過決策，回傳 `SKIPPED / no_feature_correction_applied`。

Step 2 會在擬合前，以實際矩陣中的 sample columns 產生
`Design_Identifiability` receipt。它檢查 `Sample_Type × Batch` support、
sample type/order association、design-matrix rank、scheduled QC endpoint
coverage，以及 optional `Pair_ID`、`Bridge_ID`、`QC_Pool_ID`。這是
diagnostic receipt，不是 correction gate；Step 2 自己需要的
`Injection_Order` 與 QC 條件仍由原校正 validator fail closed。即使
Step 2 因沒有 feature 通過而 `SKIPPED`，receipt 仍保留在
`ProcessingResult.extra["design_identifiability"]`。

此外，Step 2 會額外輸出：
- `Clamped_Factor_Ratio`
- `Outside_QC_Range_Count`
- `Decision_Status`

這些欄位是後續 Step 3 PQN reference selector 的正式上游契約，而不是僅供人工查看的附帶資訊。

### 5. 統計檢定框架

與 ISTD 校正相同，採用三重統計檢定評估校正效果：

#### A. 配對 t 檢定 - 檢查平均值偏移

**檢定問題:** 校正前後，QC 樣本的平均強度是否發生系統性改變？

理想的校正應該只降低變異，而不改變平均水平。我們希望看到 p > 0.05，表示校正沒有引入偏差。

**為什麼 p 值大反而好？**

假設某個代謝物在 QC 樣本中的真實平均強度是 1000。如果校正後平均值變成 1200（p < 0.05），表示校正「扭曲」了數據，可能過度補償。反之，如果校正後平均值仍接近 1000（p > 0.05），表示校正只是減少波動，保留了真實水平。

就像調整照片對比度：你希望照片更清晰（降低雜訊），但不希望改變整體亮度（保持真實性）。

#### B. Levene's 變異數齊性檢定 - 檢查變異改善

**檢定問題:** 校正前後，QC 樣本的變異程度是否有顯著差異？

Levene's test 比較兩組數據的離散程度。它使用絕對偏差的 ANOVA，不需假設正態分布，適合代謝組學中可能存在偏態的數據。

虛無假設 (H₀) 是「兩組變異數相等」。我們期望看到 p < 0.05 且校正後 CV% 降低，這才是強有力的證據證明校正顯著提升了穩定性。

**為什麼這裡 p 值小才好？**

我們想要「證明」校正前後的變異有顯著差異。如果 p < 0.05，表示我們有 95% 的信心說「變異確實改變了」。再結合 CV% 下降的事實，就能確認校正成功。

這就像評估降噪耳機效果：你需要用儀器測量證明「噪音真的顯著減少了」，而不只是感覺上好像有點安靜。

#### C. Shapiro-Wilk 正態性檢定 - 驗證前提

**檢定問題:** 配對差異是否符合正態分布？

配對 t 檢定基於「配對差異呈正態分布」的假設。Shapiro-Wilk test 檢驗這個前提。虛無假設 (H₀) 是「數據來自正態分布」。

**結果解讀:**
- **p > 0.05:** 符合正態假設，t 檢定結果可信
- **p < 0.05:** 偏離正態，t 檢定結果需謹慎看待，可能需要數據轉換或非參數檢定

如果大量代謝物的正態性檢定失敗，考慮：
1. Log 轉換原始數據再進行校正
2. 使用 Wilcoxon signed-rank test（非參數版本的配對 t 檢定）

#### 綜合判定標準

整合三個檢定結果，給出清晰判定：

- ✅ **Yes (顯著改善):**  
  CV% 改善 ≥ 10% 且 Levene's p < 0.05 且配對 t 檢定 p > 0.05  
  *變異顯著降低，平均值未偏移，校正效果理想*

- ⚠️ **Marginal (邊緣改善):**  
  CV% 改善 5-10% 或僅部分統計條件滿足  
  *有改善但不夠顯著*

- 🔵 **Yes (CV% only):**  
  CV% 有改善但統計檢定未達顯著  
  *可能因樣本數不足或改善幅度較小*

- ❌ **No (無顯著改善):**  
  CV% 改善 < 5% 或統計檢定未顯示顯著差異  
  *該代謝物可能本來就很穩定*

### 6. PCA 與異常值檢測

執行 2D 主成分分析，使用 Hotelling T² 統計量進行多變量異常值檢測。並排比較 ISTD 校正和 QC-LOWESS 校正的 PCA 圖，繪製全樣本和 QC 專用的 95% 信賴橢圓，評估校正對樣本分布的影響。

### 7. P 值與趨勢指標視覺化

生成三種統計檢定的 p 值分布直方圖，並在 Excel 中記錄每個代謝物的趨勢驗證指標（Mann-Kendall p-value, Kendall's tau, R², RMSE），提供全面的校正品質評估。

## 📊 輸入檔案要求

輸入檔案應為**經過 ISTD 校正的 Excel 檔案**（來自 ISTD Correction 工具），必須包含：

### 1. 上游資料工作表
LOWESS 校正的主要數據來源通常是 `ISTD_Correction`；若 Step 1 因 gate skip，則可退回 `RawIntensity`。無論哪個來源，Step 2 都只對可用 analyte feature 做 batch-local drift correction。

### 2. `SampleInfo` 工作表
必要欄位：
- **Sample_Name:** 必須能可靠對應資料工作表中的樣本欄
- **Sample_Type:** 必須包含 `QC` 標記
- **Injection_Order:** 記錄樣本分析順序（LOWESS 建模的關鍵）
- **Batch:** 批次欄位；Step 2 會在 batch 內各自做 drift correction

無正確 `Injection_Order` 資訊，LOWESS 無法建立可靠的時間趨勢模型。缺失或重複的 injection order 不會再被臨時序號當成校正錨點；受影響的 batch × feature 會維持原值並記錄 `invalid_injection_order`，使用者必須先修正 `SampleInfo`。

## 🚀 使用方法

### 程式化調用
```python
from metabolomics.processors import qc_lowess

result = qc_lowess.main(input_file="Step1_ISTD_Results.xlsx")
print(f"處理了 {result.metabolites} 個代謝物")
print(f"輸出檔案: {result.output_path}")
```

## 📁 輸出結果

### Excel 檔案
GUI / workflow session output:

```text
Step2_QC_LOESS.xlsx
```

Direct processor output without `session_dir`:

```text
QC_LOESS_YYYYMMDD_HHMMSS.xlsx
```

**`QC LOESS result` 工作表**
- 校正後主輸出
- QC CV% 比較
- feature-level 改善與檢定摘要

**`LOESS_summary` 工作表**
- `Decision_Status`
- `Valid_QC_Count`
- `Removed_QC_Outliers`
- `Trend_pvalue`
- `Kendall_Tau`
- `LOESS_R2`
- `LOESS_RMSE`
- `Normalized_RMSE`
- `Target_Strategy`
- `Clamped_Factor_Ratio`
- `Outside_QC_Range_Count`

這個 advanced summary sheet 是 Step 2 -> Step 3 的正式資料契約。

**顏色標記同 ISTD 工具:**
🟠 橙色: CV%  |  🔵 淡藍色: 統計 p 值  |  🟣 淡紫色: 正態性  
🟢 綠色: Yes  |  🟡 黃色: Marginal  |  🩷 粉色: No

### 圖表輸出
- **2D_PCA_ISTD_vs_LOWESS_*.png:** 並排對比，雙橢圓（全樣本 + QC），Hotelling T² 異常值標記
- **Scree_Plot_*.png:** 主成分解釋變異量
- **Pvalue_Distribution_*.png:** 三種統計檢定分布

## 🔍 結果解讀建議

### Excel 統計摘要

**Original_QC_CV% vs Corrected_QC_CV%:**
- 目標: QC CV% < 20% (可接受) 或 < 15% (良好)
- before/after 只使用兩邊同時有效的同名 QC，避免缺值造成 QC 子集合錯位
- 總覽圖只把實際套用至少一個成功 batch 的 feature（`success` 或 `partial_success`）納入 applied correction 的 CV 指標，並分開顯示 fit attempted rate、accepted batch-task rate 與校正後絕對 QC CV 分布

**Decision_Status / LOWESS_Trend_pvalue:**
- `success`: 有足夠證據支持 batch-local drift correction
- `no_drift_detected`: feature 本來就穩定，保留原值
- `insufficient_qc` / `all_qc_invalid`: QC 訊息不足，不做校正
- `invalid_injection_order`: batch 內注射順序缺失或重複，不做校正
- `outlier_filtering_left_too_few_points`: QC 離群值移除後不再足夠擬合
- `linear_fallback_outlier_filtering_not_allowed`: 稀疏 QC 經全資料挑選後不再執行 LOOCV fallback

**LOWESS_R²:**
- R² > 0.5: 擬合優良，趨勢捕捉良好
- R² 0.3-0.5: 擬合中等
- R² < 0.3: 擬合不佳，可能趨勢複雜或不明顯

**Significant_Improvement:**
- 綠色 (Yes): 校正顯著有效，推薦使用
- 黃色 (Marginal): 有改善但不顯著
- 粉色 (No): 校正無效或代謝物本來就穩定

### PCA 圖評估

**理想特徵:**
- LOWESS 校正後 QC 樣本更加聚集
- QC 橢圓面積縮小
- 異常值數量減少或持平
- 生物組別分離性維持

**警示信號:**
- QC 反而更分散
- 異常值大量增加
- 生物組別區分性消失（過度校正）

### P 值分布圖

**Levene's Test 分布:**
- 大量 p < 0.05（紅線左側）→ 多數代謝物變異顯著降低（理想）

**Paired t-test 分布:**
- 大量 p > 0.05（紅線右側）→ 平均值保持穩定，無系統偏差（理想）

**Shapiro-Wilk 分布:**
- 大量 p > 0.05 → 數據符合正態分布，t 檢定可靠

## 💡 常見問題

**Q: 為什麼有些代謝物顯示「no_significant_trend」?**

該代謝物在整個實驗中非常穩定，無明顯時間漂移。工具不會校正這些穩定代謝物，避免引入不必要變異。這是好現象。

**Q: 大部分代謝物的 LOWESS_R² 都很低怎麼辦？**

可能原因：
1. 實驗本身很穩定，QC CV% 已經 < 15%，無明顯趨勢需擬合
2. 漂移模式複雜非線性，LOWESS 難以捕捉
3. QC 樣本數不足（< 10 個），建議實驗設計時每 10-15 個樣本插入一個 QC

**Q: 校正後 CV% 反而增加？**

可能原因：
1. 該代謝物「趨勢」主要是隨機波動，非真實漂移。檢查 LOWESS_Trend_pvalue 是否 > 0.05
2. 存在極端離群值影響擬合。檢查 `outliers_removed` 欄位
3. 強度極低接近檢測限，本身就不穩定。考慮更嚴格的數據過濾

**Q: PCA 異常值應該怎麼處理？**

先調查原因：
1. 檢查原始數據是否有測量錯誤（進樣失敗、儀器故障）
2. 確認是否為真實生物學變異（極端病例）
3. 若確認為技術錯誤，可在統計分析階段排除
4. 數據預處理階段保留所有樣本，有助全面評估品質

**Q: 為什麼需要同時看配對 t 檢定和 Levene's test？**

兩者回答不同問題：
- **配對 t 檢定:** 關注「位置」→ 平均值是否改變（希望 p > 0.05）
- **Levene's test:** 關注「散佈」→ 變異是否降低（希望 p < 0.05）

只看一個不夠。例如，如果配對 t 檢定 p < 0.05，表示校正改變了平均值，這通常不是我們想要的；如果 Levene's p > 0.05，表示變異沒顯著改變，校正可能無效。

## ⚙️ 技術細節

### 依賴套件
```
pandas, numpy, openpyxl, statsmodels, scipy, scikit-learn, matplotlib
```

### 核心演算法
- **LOWESS:** statsmodels.nonparametric.lowess，3次迭代
- **離群值:** IQR 方法，1.5 倍四分位距
- **異常值:** Hotelling T² (卡方分布 95% 分位數)
- **校正因子限制:** [0.5, 2.0]

## 📝 注意事項

1. **輸入檔案:** 必須為經過 ISTD 校正的檔案
2. **Run_Order:** SampleInfo 中必須包含正確的分析順序
3. **QC 樣本數:** 建議 ≥ 10 個以確保 LOWESS 擬合可靠
4. **QC 頻率:** 建議每 10-15 個樣本插入一個 QC

---

**版本:** v6.1 Final  
**更新:** 2025  
**環境:** Python 3.8+  
**配合:** ISTD Correction 工具
