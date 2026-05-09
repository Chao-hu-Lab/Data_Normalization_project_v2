# QC-based 校正方法演進評估

**日期**：2026-05-09
**接續**：[2026-05-09-istd-method-review.md](./2026-05-09-istd-method-review.md)
**對照**：[../algorithms/qc_lowess.md](../algorithms/qc_lowess.md)（Step 2 既有實作規格）
**研究方向**：DNA Adductomics
**Cohort**：Breast Cancer Tissue, n=85（30 Exposure + 28 Normal + 20 Control + 7 QC），單批次
**Pipeline**：mzMine → metabCombiner → DNP（本 repo）
**MS 方法**：CID-only

---

## 框架

ISTD 方法評估（前一份討論）結論為**對本 cohort 跳過 Step 1**。沒有 ISTD 校正後，pipeline 對 systematic drift 的唯一防線是 **Step 2 QC-LOWESS**（既有實作）。

本文件：
1. 盤點 Step 2 QC-LOWESS 的既有設計
2. 對比 2024-2025 QC-based 文獻最新發展
3. 標記**演進 gap**（既有實作未涵蓋之處）
4. 給出「是否要演進 vs 維持現狀」的決策依據

**本文件不包含實作建議；不在 codebase 產生任何程式碼變動。**

---

## TL;DR

- Step 2 QC-LOWESS **已涵蓋文獻多數推薦的 safeguards**（trend gate、IQR、clamp、三重統計檢定、PCA T²）
- **三個 gap 值得關注**：
  1. 動態 frac 在 QC=7 退化為 frac=1.0（接近線性回歸）
  2. 沒有 **D-ratio post-check**（Broadhurst 2018 推薦的關鍵驗證指標）
  3. 沒有 **leave-one-QC-out 驗證**（小 QC 數的 overfitting 護欄）
- 文獻最新方法（QC-RSC、QC-RFSC、Robust QC-RLSC）**對本 cohort 的增量有限**——主要是把 LOWESS 換成 spline / RF，但底層問題（QC 只有 7 個）方法換哪個都改不了
- **推薦結論**：維持 Step 2 QC-LOWESS，**選擇性引入兩道輕量護欄**（D-ratio 驗證 + leave-one-QC-out），而非整體更換引擎

---

## 1. Step 2 QC-LOWESS 既有設計盤點

來源：`docs/algorithms/qc_lowess.md` v6.1 Final

| 設計面向 | 既有實作 | 對應文獻概念 |
|---|---|---|
| **核心演算法** | statsmodels LOWESS，3 次迭代 | QC-RLSC（Dunn 2011, Kirwan 2013）的 LOWESS 變種 |
| **Trend gate** | Mann-Kendall 檢定 + R² + normalized drift amplitude | Boysen 2018「raw RSD 低就不校正」的 QC-based 對應 |
| **Outlier 處理** | IQR 1.5×，移除後保留 ≥70% 或 ≥5 個 QC | 2025 robust QC-RLSC 的「outlier downweighting」（IRLS）的離散版本 |
| **Smoothing parameter** | 依 QC 數量動態：<8 用 frac=1.0，8-11 用 0.8，≥20 用 0.4 | Kirwan 2013 推薦做法（避免 over-smooth / under-smooth） |
| **校正因子安全限制** | clamp [0.5, 2.0] | 對應 Boysen 40% threshold 的另一面（不允許極端校正） |
| **Post-correction 驗證** | 配對 t / Levene / Shapiro-Wilk 三重檢定 | 比 D-ratio 更嚴格——但**不是同一個東西**（見 §3） |
| **異常值偵測** | PCA + Hotelling T² | Mahalanobis distance 的 multivariate 版本 |
| **失敗 fallback** | `Decision_Status` 欄位含 5 種失敗模式（`no_drift_detected`, `insufficient_qc`, `all_qc_invalid`, `outlier_filtering_left_too_few_points`, `success`）| Metanorm-style adaptive fallback 的離散實作 |
| **下游契約** | `LOESS_summary` 含 `Clamped_Factor_Ratio`, `Outside_QC_Range_Count`, `Decision_Status` 給 Step 3 PQN | （工程設計，非文獻概念） |

**結論**：Step 2 在 2014-2018 年發表的 QC-LOWESS / QC-RLSC 黃金標準上，是工程化得**比文獻範例更完整**的實作。

---

## 2. 文獻最新發展（2024-2025）

### 2.1 候選新方法

| 方法 | 來源 | 對 QC-LOWESS 的差異 | 對你的潛在意義 |
|---|---|---|---|
| **QC-RSC**（Spline 取代 LOWESS）| Kirwan 2013, `pmp::QCRSC` | spline 對非線性 drift 比 LOWESS 略強 | 你 LOWESS R² 通常 0.3-0.5 之間時 spline 可能略好；R²>0.5 時兩者相當 |
| **QC-RFSC**（RF 取代 LOWESS）| Luan 2018, `statTarget` / MetaboAnalyst | RF 對 **非單調 drift** 強，文獻 RSD<30% 比例 52%→91% | RF 在 QC=7 時樹數有限，**overfit 風險高** |
| **Robust QC-RLSC + GCV** | Anderson 2025 bioRxiv | (a) IRLS outlier downweighting；(b) GCV 取代 LOOCV | (a) 你已用 IQR 達成（離散版）；(b) GCV 是真正未涵蓋的改進 |
| **Metanorm（GAM-based）**| ACS Measure Sci Au 2024 | GAM 取代 LOWESS + adaptive fallback | 你已有 5 種 `Decision_Status` fallback，差別不大 |

### 2.2 落選方法（不適合本 cohort）

| 方法 | 落選理由 |
|---|---|
| **SERRF** | 需 ≥500 樣本，n=85 會 overfit |
| **SERDA** | 主驗證在 GC-MS；autoencoder 為大樣本設計 |
| **NormAE** | 文獻警告 >95% feature inflated variance；壓制低 intensity 對 DNA adductomics 是災難 |
| **WaveICA / WaveICA 2.0** | wavelets 為 multi-batch 分解設計，single batch 缺分解空間 |
| **hRUV / ComBat-Met** | 多批次校正方法，single batch 不適用 |
| **RUV-2 / RUV-random** | 需 negative control metabolites，DNA adductomics 領域沒公認候選 |

### 2.3 文獻共識（2024 QComics + 2023 Lippa + 2018 Broadhurst）

| 條目 | 文獻推薦 | 你的現況 |
|---|---|---|
| QC 最少數量 | ≥8（excluding conditioning），ML 類 ≥10 | **7（邊緣偏少）** |
| QC 排布密度 | 1 QC per 3-10 biological samples | 1:12（**邊緣偏稀**） |
| 校正後 QC RSD 目標 | < 20%（LC-MS）| 部分 feature 應可達成 |
| **D-ratio post-check** | < 50% | **目前未實作** |
| QC representativeness | PCA 上 QC 應落在 sample cluster 中央 | Step 2 的 PCA 圖已視覺化但**沒程式化檢核** |

---

## 3. 三個演進 Gap（如果未來要做的話）

### 3.1 Gap A：動態 frac 在 QC=7 退化問題

**現況**：`docs/algorithms/qc_lowess.md` 動態 frac 表第一行為「QC<8 → frac=1.0」。

**問題**：frac=1.0 表示「用全部 QC」，等同退化為**全域回歸**而非**局部加權回歸**。LOWESS 的核心優勢（local polynomial）在 QC=7 時消失。

**文獻對應**：Anderson 2025 提出 GCV 取代 LOOCV，正是為了解決小 QC 數的 smoothing parameter 選擇問題。

**演進選項**：
- **選項 A1（保守）**：保留 frac=1.0 的 fallback，但加註明確警告（已部分達成——`Decision_Status='insufficient_qc'`）
- **選項 A2（積極）**：QC<8 時**改用 spline + GCV**（QC-RSC 風格），對 small-N 較穩定
- **選項 A3（演進）**：引入 2025 IRLS-GCV 變種

**對本 cohort 的實質影響**：未知，需 §5 的小規模驗證實驗才能量化。

### 3.2 Gap B：沒有 D-ratio post-check

**現況**：Step 2 已有 paired t / Levene / Shapiro 三重檢定，但**沒有計算 D-ratio**。

**為何 D-ratio 重要**：
- D-ratio 定義：`std(QC) / std(samples)` per feature
- **Levene's test 比的是「校正前後 QC 變異有沒有改變」**——即「校正有沒有效」
- **D-ratio 比的是「校正後 technical variance 是否仍小於 biological variance」**——即「校正完還能不能用來做生物學分析」
- **這兩件事不同**——你可能 Levene 顯著改善（校正有效）但 D-ratio > 50%（biological signal 還是被 technical noise 蓋過）

**文獻支持**：
- Broadhurst 2018 *Metabolomics*：D-ratio < 50% 為 biological-meaningful 的硬指標
- 2025 bioRxiv 開放原文：D-ratio 是「resistance to overfitting」的核心衡量

**演進選項**：
- **B1（最低成本）**：在 `LOESS_summary` 增加 `D_Ratio_Original` / `D_Ratio_Corrected` 欄位（純度量，不影響校正流程）
- **B2（決策化）**：將 D-ratio < 50% 加入 `Significant_Improvement` 的判定條件
- **B3（gate 化）**：D-ratio 校正後 > 校正前的 feature → 自動 fallback to original（類似 Boysen 40% 護欄的 QC-based 版）

### 3.3 Gap C：沒有 leave-one-QC-out 驗證

**現況**：所有 7 個 QC 都用於擬合，沒有保留樣本驗證 overfit。

**為何重要**：
- 7 個 QC 對 LOWESS 已是邊緣，對 RF 更嚴重（如果未來考慮 QC-RFSC）
- 校正後 QC CV% 看起來低，可能只是 LOWESS 把曲線拉到完全貼合 7 個點——典型 overfit 訊號

**文獻支持**：
- Anderson 2025：GCV 是 LOOCV 的計算高效版，本質是「leave-one-out 評估 smoothing 品質」
- QComics 2024：強調 QC-based 校正必須 resist overfitting

**演進選項**：
- **C1（量化）**：對每個 feature，跑一次 leave-one-out QC 預測，記錄 mean prediction error 入 `LOESS_summary`
- **C2（決策化）**：若 prediction error > raw QC variability 50% → `Decision_Status='overfit_risk'`，fallback to original
- **C3（與 B3 結合）**：與 D-ratio 共構雙護欄

---

## 4. 對「換引擎 vs 加護欄」的判斷

### 4.1 換引擎（QC-LOWESS → QC-RSC / QC-RFSC）的 cost-benefit

**理論上的好處**：
- QC-RSC 在 R² 0.3-0.5 範圍可能略好（spline > LOWESS）
- QC-RFSC 對非線性 drift 強（但你資料是否非線性 drift 未知）
- pmp/statTarget 是 R 套件，整合進 Python 流程需 reticulate 或 rpy2

**實際 cost**：
- Step 2 已是工程化完整的工具（5 種 Decision_Status、PCA T²、三重統計）；換引擎要重做這些工程細節
- 你的 R² 分布實際是多少未知；若多數 feature R²>0.5，spline 與 LOWESS 結果幾乎重合
- RF 在 QC=7 時 overfit 風險 > LOWESS

**結論**：**換引擎的工程成本 vs 預期增益不對稱**。除非有強烈證據（例如多數 feature R²<0.3），否則不換。

### 4.2 加護欄（D-ratio + leave-one-out + frac fallback 改 spline）的 cost-benefit

**理論上的好處**：
- D-ratio 是 Broadhurst 2018 的核心指標——不加會讓討論文件被引用時被質疑
- leave-one-out 是 QC=7 的 mandatory overfit 護欄
- frac=1.0 fallback 改 spline 直接解決動態 frac 退化問題

**實際 cost**：
- D-ratio 是 2 行程式：`np.std(qc_corrected) / np.std(samples_corrected)`
- leave-one-out 對 7 個 QC 是 7 次 LOWESS fit，每 feature ~0.1 秒——對 325 features 約 4 分鐘
- frac fallback 改 spline 需引入 `scipy.interpolate.UnivariateSpline`，~50 行程式

**結論**：**加護欄是高 cost-benefit 比的演進路徑**。但仍須先做 §5 驗證實驗確認本 cohort 是否真正受益。

---

## 5. 驗證實驗設計（Step 2 之外，repo 之外）

**目的**：在不污染 production code 的前提下，量化三個 gap 對本 cohort 的實際影響。

### 5.1 三步漸進驗證

**Step A：跑既有 Step 2 取得 baseline**
1. 用 raw matrix（跳過 Step 1）作為 Step 2 輸入
2. 完整跑一次 QC-LOWESS，取得 `LOESS_summary` 完整輸出
3. 統計：
   - LOWESS_R² 分布（直方圖）
   - Decision_Status 各類別計數
   - 校正前後 QC CV% 改善分布
   - PCA T² 異常值數量變化

**Step B：算 D-ratio（不修改 Step 2，純後處理）**
1. 從 Step 2 輸出讀 corrected matrix 與 SampleInfo
2. Per-feature 計算 `D_Ratio_Original` 與 `D_Ratio_Corrected`
3. 統計：
   - D_Ratio_Corrected < 50% 比例
   - D_Ratio 上升的 feature 數（潛在 biological signal erosion）
   - 與 `Decision_Status='success'` 交叉表

**Step C：算 leave-one-QC-out prediction error（不修改 Step 2）**
1. 對每個 feature，跑 7 次 LOWESS（每次留 1 QC 做 prediction）
2. 算 mean absolute prediction error / median QC intensity
3. 統計：
   - prediction error 中位數
   - prediction error > 50% 的 feature 數（overfit 候選）

**Step D（only if A-C 顯示問題）：spline 對照**
1. 用 scipy.interpolate.UnivariateSpline 重做校正
2. 比對 R²、QC CV%、D-ratio 是否系統性優於 LOWESS
3. 若無系統性優勢——確認「不需換引擎」

### 5.2 Stop conditions

任一條件觸發即停止 QC-based 演進探索：
- Step A 顯示 ≥80% feature `Decision_Status='success'` 且 QC CV% 改善中位數 ≥30%——Step 2 已經夠好
- Step B 顯示 D_Ratio_Corrected < 50% 比例 ≥80%——既有實作 biological signal preservation 沒問題
- Step C 顯示 prediction error 中位數 < 25%——既有實作沒有 overfit
- 任一指標顯示「Step 2 反而比 raw 差」的 feature 比例 ≥10%——退一步思考是否要連 Step 2 也跳過

### 5.3 實驗載體

**所有實驗在 `tmp_qc_diagnostic/` 目錄執行**（仿 ISTD discussion 的 `tmp_diagnostic_run/` 模式），事後刪除。**不修改 `src/metabolomics/processors/qc_lowess.py`**。

---

## 6. 開放問題（須在演進前釐清）

1. **Step 2 對本 cohort 的實際 R² 分布是什麼？** 沒做 §5 Step A 之前，所有討論是空中樓閣
2. **跳過 Step 1 後，Step 2 是否能單獨穩住 drift？** 既有 QC-LOWESS 規格寫「輸入應為 ISTD 校正後」——但同時提到「若 Step 1 因 gate skip，則可退回 RawIntensity」。實際從 RawIntensity 接手的效益沒有 benchmark
3. **DNA adductomics 領域是否有 QC-based 校正的特殊考量？** 文獻搜尋顯示**沒有**——所有 metabolomics QC-based 文獻針對 plasma/serum；DNA adductomics 用 QC-based 校正本身是 **off-label use**
4. **Step 3 PQN 對 Step 2 輸出的依賴是什麼？** 演進 Step 2 的下游影響需評估——`Decision_Status` / `Clamped_Factor_Ratio` 是 PQN 的正式契約
5. **若 §5 顯示既有 Step 2 已足夠，本 cohort 的 normalization 路徑就確定為**：「跳過 Step 1 + 維持 Step 2 + Step 3 PQN」——可能是這份 cohort 的最終定論

---

## 7. 與 ISTD 討論的呼應

| 維度 | ISTD（前一份）| QC-based（本份） |
|---|---|---|
| 起點 | 「ISTD CV% 看似還好，gate 卻擋」| 「跳過 Step 1 後，誰負責 drift 校正？」 |
| 文獻 vs 實作 | 文獻有 B-MIS 但本資料模擬下無增量 | 文獻有 QC-RSC/QC-RFSC 但既有 QC-LOWESS 已工程化完整 |
| 失敗模式 | 配錯 ISTD（cross-class） | QC overfit / biological signal erosion |
| 護欄哲學 | Boysen 40% threshold | D-ratio < 50% + leave-one-out |
| 實作決策 | 不引入 B-MIS（成本不對稱）| 不換引擎（成本不對稱），考慮加 D-ratio + leave-one-out 兩道護欄 |
| 系統評價 | `evaluate_istd_gate` 的判斷正確 | Step 2 QC-LOWESS 的工程細節已優於文獻多數 reference implementation |

**共同主題**：本專案的既有 gate 與工程細節（istd gate、qc_lowess 動態 frac、Decision_Status）**比文獻 reference 實作更完整**——演進方向應是**選擇性引入文獻最新的後驗指標**，而非整體更換引擎。

---

## 8. 推薦結論（本次調研）

1. **不換引擎**：QC-LOWESS → QC-RSC / QC-RFSC 的工程成本與預期增益不對稱
2. **選擇性加兩道護欄**（**僅在 §5 驗證實驗顯示確有需要時**）：
   - **D-ratio post-check**（補 Broadhurst 2018 標準）
   - **leave-one-QC-out validation**（補小 QC 數的 overfit 護欄）
3. **下一步只做驗證實驗**（§5 Step A-C），**不修改 production code**
4. **若 §5 顯示既有 Step 2 已足夠**——這個 cohort 的 normalization pipeline 就確定為「Skip Step 1 + 既有 Step 2 + Step 3 PQN」，作為 DNP 對 untargeted DNA adductomics 的 reference workflow

---

## 9. 參考文獻

1. Kirwan, J.A., et al. **Characterising and correcting batch variation in an automated direct infusion mass spectrometry (DIMS) metabolomics workflow.** *Anal Bioanal Chem* (2013). 405:5147-5157
2. Bioconductor pmp package — QCRSC implementation. https://rdrr.io/bioc/pmp/man/QCRSC.html
3. Luan, H., et al. **statTarget: A streamlined tool for signal drift correction.** *Anal Chim Acta* (2018). https://www.sciencedirect.com/science/article/abs/pii/S0003267018309395
4. statTarget bioRxiv — QC-RFSC. https://www.biorxiv.org/content/10.1101/253583v1.full
5. Anderson et al. **Robust metabolomics data normalization across scales and experimental designs.** *bioRxiv* (2025). https://www.biorxiv.org/content/10.1101/2025.09.30.679445v1.full
6. Broadhurst, D., et al. **Guidelines and considerations for the use of system suitability and quality control samples.** *Metabolomics* (2018). https://link.springer.com/article/10.1007/s11306-018-1367-3
7. Lippa, K.A., et al. **Instrumental Drift in Untargeted Metabolomics: Optimizing Data Quality with Intrastudy QC Samples.** *Metabolites* (2023). PMC10222478
8. QComics: Recommendations and Guidelines for QC of Metabolomics Data. *Anal Chem* (2024). PMC10809278
9. Closing the Knowledge Gap of Post-Acquisition Sample Normalization in Untargeted Metabolomics. *ACS Measure Sci Au* (2024). https://pubs.acs.org/doi/10.1021/acsmeasuresciau.4c00047
10. Fan, S., et al. **SERRF for Normalizing Large-Scale Untargeted Lipidomics Data.** *Anal Chem* (2019). https://slfan2013.github.io/SERRF-online/
11. Fan, S., et al. **Denoising Autoencoder Normalization (SERDA).** *Metabolites* MDPI (2023). PMC10456436
12. RALPS: Regularized adversarial learning for normalization. *Bioinformatics* (2023). PMC9978579
13. WaveICA original. *Anal Chim Acta* (2019). https://www.sciencedirect.com/science/article/abs/pii/S0003267019301849
14. hRUV: Hierarchical removal of unwanted variation. *Nat Commun* (2021). PMC8371158
15. Current Practices in LC-MS Untargeted Metabolomics: Scoping Review on Pooled QC Samples. *Anal Chem* (2024). https://pubs.acs.org/doi/10.1021/acs.analchem.3c02924
16. NOREVA web tool. https://idrblab.cn/noreva/
17. Dunn, W.B., et al. **Procedures for large-scale metabolic profiling of serum and plasma using GC-MS and UPLC-MS.** *Nat Protoc* (2011). 6:1060-1083 — original QC-RLSC
