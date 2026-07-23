# 混合 corrected／unchanged features 的 QC drift correction：文獻證據與設計建議

日期：2026-07-22

## 結論先行

**可以在同一張輸出矩陣中，同時存在經 QC drift correction 的 feature 與維持原值的 feature。** 這不只是理論上的折衷：Wehrens 等人的三組真實 untargeted MS 資料研究，明確在無法校正某個 metabolite × batch 時保留原值，再以完整混合矩陣評估 PCA 與 biological repeatability。QC-RLSC 類方法本來也是逐 feature 建模；`notame` workflow 更明確提供「品質改善才採用校正值，否則保留原值」的 feature-wise 選擇。

但這不等於兩類 feature 具有相同的分析可信度。它們仍在相同的原始 response／area scale 上，真正混合的是不同的**誤差模型與校正證據強度**：

- corrected feature：數值是估計移除 run-order drift 後的 area；仍有模型誤差。
- unchanged、但 QC 足夠且無可辨識 drift：數值是原始 area；不校正是有證據的 abstention。
- unchanged、因 QC 點不足：數值也是原始 area，但無法判定 drift 是否存在；不確定性最高。

因此，較可信的方案不是「為了矩陣一致而全部強制校正」，而是 **feature × batch routing + 單一數字矩陣 + 不可省略的逐 feature 狀態與下游敏感度分析**。文獻直接支持逐 feature 校正及「改善才採用」；但沒有找到直接以同一套 ground truth 比較「混合 corrected／unchanged matrix」和「全部強制校正 matrix」的研究，所以本專案仍需要自己的模擬與代表性資料驗證。

## 一、文獻中可以直接觀察到的事實

### 1. QC-based drift correction 通常就是逐 feature 建模

QC-RLSC 的原始大型代謝體流程以 QC 注射的訊號，對多批次資料進行 robust LOESS signal correction。[Dunn et al., 2011](https://doi.org/10.1038/nprot.2011.335)

後續實作把這一點寫得更明確：

- `notame` protocol 要求對「每一個 molecular feature」重複 drift modelling 與 correction；模型以該 feature 的 QC abundance 對 injection order 擬合。[Klåvus et al., 2020，步驟 35–42](https://www.mdpi.com/2218-1989/10/4/135)
- MetaboDrift 說明 QC-based 方法可以逐一校正 individual metabolite；而且各 metabolite 的 drift pattern 可能不同。其 curve fitting 是對每個 metabolite、每個 batch 分別套用。[Thonusin et al., 2017](https://doi.org/10.1016/j.chroma.2017.09.023)
- 一個以相鄰 reference QC 做線性校正的原始 protocol，也只對兩個相鄰 QC 都成功定量的 feature 建立 linear corrector，顯示 eligibility 天然是 feature-specific。[Yu et al., 2016](https://doi.org/10.1371/journal.pone.0160555)

所以，「同一批中每個 feature 可能得到不同 drift curve」是 QC-based correction 的正常結構，不是本專案特有的偏離。

### 2. 文獻與正式套件會逐 feature 判定 detection／quality eligibility

`notame` protocol 建議先標記 pooled QC detection rate 太低的 feature，示例門檻是 QC detection rate 70%；再逐 feature 進行 drift correction。該 protocol 沒有主張先補出人造 QC 點再強制擬合。[Klåvus et al., 2020](https://www.mdpi.com/2218-1989/10/4/135)

`notame` 的正式套件介面也將 QC detection rate、RSD、robust RSD、D-ratio 與 robust D-ratio 保存為 feature-level 品質資訊。[notame package manual](https://bioc-release.r-universe.dev/notame/doc/manual.html)

這支持兩項判斷：

1. 「批次安排了 8 支 QC」不等於「每個 feature 都有 8 個可用 QC 點」。
2. 是否能建立 drift model，應由單一 `feature × batch` 的有效 QC 數與覆蓋決定，而不是由整批 QC 的名義支數決定。

### 3. 「校正沒有改善就保留原值」有明確先例

`notame` protocol 的 optional quality gate 明確要求：只有當校正前後的 quality metrics 顯示資料品質改善，才保留 drift-corrected values；其他 features 保留 original values。[Klåvus et al., 2020，步驟 42](https://www.mdpi.com/2218-1989/10/4/135)

套件實作更具體：啟用 `check_quality` 時，預設條件要求 robust RSD 與 robust D-ratio 都下降；否則丟棄該 feature 的 corrected values，保留 original values。[notame `correct_drift` manual](https://bioc-release.r-universe.dev/notame/doc/manual.html)

這是與本專案最接近的文獻／實作證據：**同一份 processed matrix 可以由「通過 gate 的 corrected feature」和「未通過 gate 而保留 original 的 feature」組成。** 不過，`notame` 把這個 gate 設為 optional，不能據此宣稱所有 QC correction 工具都會自動這樣做。

### 4. 有研究直接以 corrected／unchanged 混合矩陣評估 PCA 與 repeatability

Wehrens 等人用三組真實 untargeted LC–MS／GC–MS 資料比較 batch correction 與 non-detect handling。其 correction 是逐 metabolite 的 regression；當某個 metabolite × batch 因資訊不足而無法校正時，作者將 original uncorrected value 保留在 corrected matrix，藉此讓所有方法用相同數量的資料點比較。[Wehrens et al., 2016](https://doi.org/10.1007/s11306-016-1015-8)

這篇研究提供目前找到最直接的 mixed-matrix 實證：

- 在 LC–MS Arabidopsis hapmap dataset，QC-based strategy Q 讓 PCA 中明顯的 batch separation 消失；即使一部分 metabolite 因 QC 資訊不足而留在對角線（原值未變），平均 biological repeatability 仍由 `0.559` 提升到 `0.62`。
- 混合並不保證一定改善。另一個 QC 稀疏 dataset 中，加入 injection-order correction 後，QC-based strategy 有 `58.0%` 的 metabolite × batch cases 無法校正；大量原值使整體結果接近 raw data，而且結果比只校正 batch average 更差。
- 同一個 metabolite 可以在 QC 資訊足夠的 batches 校正，在其他 batches 保留原值。作者認為只評估可校正的子集會得到很好看的 quality criteria，卻因每種方法納入的 metabolite 數不同而難以公平解讀。
- 將 non-detects 人工填成 0 後再校正，通常是所比較策略中較差的做法。

所以文獻不是說「混合必然安全」，而是證明兩件事：**混合矩陣是可運作、可量化評估的設計；其成敗取決於 unchanged coverage、routing 原因及全矩陣層級的 biological-aware validation。**

### 5. 強制或過度靈活的 correction 確實可能讓資料變差

MetaboDrift 的實驗提供一個很直接的反例：

- 在用來擬合的 QC 上，cubic spline correction 可得到 `0.0%` 的 post-correction QC RSD，因為每個 QC 都是 curve-fitting lock point。
- 但在沒有參與擬合的獨立 QC 上，原始資料平均 RSD 是 `13.6%`，cubic spline 校正後反而升到 `19.0%`；同一資料的 LOESS 是 `12.2%`。

也就是說，**訓練 QC 看起來完美，並不代表對未見資料的 correction 正確**。作者也警告 LOESS 的 smoothing parameter 太低會擬合 QC random noise，降低 correction performance。[Thonusin et al., 2017](https://doi.org/10.1016/j.chroma.2017.09.023)

Brunius 等人的 batchCorr 方法採取更嚴格的保護：cluster drift correction 只有在未參與 QC drift model、且生物來源不同的 long-term reference samples 上降低 RMSD 時才採用；校正後仍以 feature-level QC CV 做篩選。[Brunius et al., 2016](https://doi.org/10.1007/s11306-016-1124-4)

這兩篇共同支持：若沒有足夠 evidence，`unchanged` 是合理的保守結果；不能只因為演算法能產生 correction factor 就強制套用。

### 6. 只看校正後 QC RSD 不足以驗證 correction

已有文獻使用或建議下列更接近外部效度的檢查：

- **Held-out QC**：不參與 curve fitting 的 QC，檢查真正的 out-of-sample RSD。MetaboDrift 的 cubic spline 反例就是靠這項檢查才被看見。[Thonusin et al., 2017](https://doi.org/10.1016/j.chroma.2017.09.023)
- **獨立 reference samples**：batchCorr 只在未參與 drift modelling 的 long-term references 改善時採用 correction。[Brunius et al., 2016](https://doi.org/10.1007/s11306-016-1124-4)
- **matched isotope-labelled internal standards**：MetaboDrift 將 matching IS normalization 視為定量比較基準；28 個 metabolite 中有 4 個的 biological fold-change 與 QC correction 顯著不同，其中 palmitic acid 的差異較大（約 2.2-fold 對 1.6-fold）。[Thonusin et al., 2017](https://doi.org/10.1016/j.chroma.2017.09.023)
- **D-ratio**：不只量 QC 自身 spread，也比較 QC technical spread 與 biological sample spread。Broadhurst 等人提出 RSD 與 D-ratio 作為互補的 feature-level quality reporting。[Broadhurst et al., 2018](https://doi.org/10.1007/s11306-018-1367-3)
- **study samples 的 injection-order 殘留**：`notame` 建議分別在 QC、biological samples 與全部樣本中，檢查 feature abundance 與 injection order 的關聯，並以 PCA、t-SNE、clustering 等檢查全域結構。[Klåvus et al., 2020](https://www.mdpi.com/2218-1989/10/4/135)
- **生物結論**：MetaboDrift 比較不同 correction 對 physiological fold-change 與顯著 metabolite 的影響，而非只比較 QC 聚集程度。[Thonusin et al., 2017](https://doi.org/10.1016/j.chroma.2017.09.023)
- **全矩陣 PCA 與 biological repeatability**：Wehrens 等人的兩項 quality criteria 都只使用 study samples，並保留不可校正 cases 進入整體評估，避免只挑可校正的 subset 得出過度樂觀結論。[Wehrens et al., 2016](https://doi.org/10.1007/s11306-016-1015-8)

## 二、從上述證據推導出的設計判斷

以下是本專案的推論，不是文獻逐字規範。

### 1. 混合矩陣沒有「單位衝突」，但有「可信度分層」

若 correction 是在 log scale 估計 drift、最後轉回原始 scale，或以 dimensionless correction factor 乘回 peak area，corrected 與 unchanged values 都仍表示同一 feature 的相對 response／peak area。`unchanged` 等價於 correction factor 為 1。

問題不在單位，而在 residual technical error：

- corrected feature 可能降低 drift，也可能引入 model error。
- `unchanged_no_drift` 可能已經是最佳估計。
- `unchanged_insufficient_qc` 可能仍含未知 run-order drift。

因此不能只輸出一張沒有 provenance 的數字表，讓下游誤以為所有 feature 經過相同證據強度的 correction。

### 2. 強制統一演算法不會讓矩陣更一致，只會讓風險更隱蔽

不同 metabolite 的 ionization、matrix effect、LOD、missingness 與 drift pattern 本來就不同。把 QC 點不足或沒有可辨識 drift 的 feature 強制套入 curve，只是把「可見的未校正不確定性」換成「看似整齊但不可驗證的模型偏差」。MetaboDrift 在 training QC RSD 為 0、held-out QC 卻惡化的結果，就是這種假性整齊的實例。

### 3. 對 multivariate analysis 的主要風險是異質 measurement error

PCA、clustering 或 supervised model 常會在 feature scaling 後讓各 feature 取得相近權重。這時，一個 `unchanged_insufficient_qc` feature 的殘留 drift 可能和高品質 corrected feature 一樣影響結果。這不是混合矩陣必然無效，而是代表分析必須做 route-aware QC 與敏感度比較。

## 三、建議的產品契約

### 1. Routing 單位

以 `feature × batch` 為最小判斷單位，而不是整個 batch 或整張矩陣：

- `corrected_lowess`：有效 QC 足夠且 LOWESS gate 通過。
- `corrected_linear_shrinkage`：稀疏 QC fallback 的所有 gate 通過。
- `unchanged_no_detectable_drift`：QC evidence 足夠，但 correction 沒有勝過原值。
- `unchanged_insufficient_qc`：有效 QC 不足，無法辨識 drift。
- `unchanged_failed_quality_gate`：模型可擬合，但校正後品質或外部驗證沒有改善。

同一 feature 在不同 batch 可以有不同狀態；status 必須伴隨矩陣保存，不能只在 log 中出現。

### 2. 不要把所有 unchanged 合併成同一語義

`unchanged_no_detectable_drift` 是有證據的 abstention；`unchanged_insufficient_qc` 是 evidence gap。兩者數值都未變，但下游解讀完全不同，必須分開。

### 3. 建議輸出兩層資料視圖

1. **完整探索矩陣**：保留所有上游允許的 feature，包含 corrected 與 unchanged；搭配 route/status sidecar。
2. **定量高可信度視圖**：排除或另外標記 `unchanged_insufficient_qc`、post-correction quality 不佳，以及明顯受 LOD/censoring 影響的 features。若某 feature 只在特定 biological group 出現，應考慮 presence/absence 或 censored analysis，而不是把它硬塞入 QC drift model。

這樣既不因 pooled QC 稀釋而過早刪掉可能有生物意義的 feature，也不讓低 QC evidence 的 feature 默默取得與高品質 feature 相同的推論權重。

### 4. 最低驗證組合

每次算法或 gate 變更至少同時報告：

1. 各 routing status 的 feature × batch 數量與比例。
2. 校正前後 RSD／robust RSD 與 D-ratio／robust D-ratio，依 routing 分層。
3. 可能時使用 held-out QC 或獨立 reference，而不是用 fitted QC 自評。
4. biological samples 中 feature 與 injection order 的殘留關聯；若 group 與 order 混雜，另行標記，不能宣稱已辨識 biology 與 drift。
5. 有 matching IS 的 features，比較 raw、corrected 與 IS-normalized 的誤差及 fold-change。
6. raw matrix、mixed routed matrix、以及只含高可信度 features 的主要 biological conclusions 是否同方向。
7. 多變量圖與模型至少做一次排除 `unchanged_insufficient_qc` 的敏感度分析。

## 四、仍未解決的問題

1. Wehrens 等人直接評估過 corrected／unchanged 混合矩陣，但**仍沒有找到完全符合本專案情境的 head-to-head ground-truth 研究**：也就是上游寬鬆保留、部分 feature 的 pooled QC 只檢出 1–2 點，然後比較「混合 corrected／unchanged」和「全部強制校正」對下游 inference 的淨影響。
2. 文獻常用 70% 或 80% QC detection rate 作 feature filter，但在只有 6–8 支 QC 時，百分比會變成很粗的整數門檻；本專案使用有效點數、端點覆蓋與模型 gate，比單一百分比更可解釋，但屬於本專案決策，不能冒充通用文獻標準。
3. `notame` 的 selective retention 證明混合輸出有方法學先例，但其預設 `check_quality` 可關閉，而且使用的 spline 與本專案的 LOWESS／shrunken linear 不同；仍需用本專案的 frozen simulation 與真實代表性資料驗證。
4. pooled QC 中低 detection 可能來自低濃度、pool dilution、peak integration failure 或 feature 真正不穩定；僅靠矩陣無法完全區分。重要 feature 仍需要 raw-data reintegration、matched IS 或 targeted assay。

## 參考文獻

1. Dunn WB, et al. Procedures for large-scale metabolic profiling of serum and plasma using gas chromatography and liquid chromatography coupled to mass spectrometry. *Nature Protocols*. 2011;6:1060–1083. [doi:10.1038/nprot.2011.335](https://doi.org/10.1038/nprot.2011.335)
2. Klåvus A, et al. “Notame”: Workflow for Non-Targeted LC–MS Metabolic Profiling. *Metabolites*. 2020;10:135. [doi:10.3390/metabo10040135](https://doi.org/10.3390/metabo10040135)
3. Thonusin C, et al. Evaluation of intensity drift correction strategies using MetaboDrift, a normalization tool for multi-batch metabolomics data. *Journal of Chromatography A*. 2017;1523:265–274. [doi:10.1016/j.chroma.2017.09.023](https://doi.org/10.1016/j.chroma.2017.09.023)
4. Brunius C, Shi L, Landberg R. Large-scale untargeted LC-MS metabolomics data correction using between-batch feature alignment and cluster-based within-batch signal intensity drift correction. *Metabolomics*. 2016;12:173. [doi:10.1007/s11306-016-1124-4](https://doi.org/10.1007/s11306-016-1124-4)
5. Broadhurst D, et al. Guidelines and considerations for the use of system suitability and quality control samples in mass spectrometry assays applied in untargeted clinical metabolomic studies. *Metabolomics*. 2018;14:72. [doi:10.1007/s11306-018-1367-3](https://doi.org/10.1007/s11306-018-1367-3)
6. Yu T, et al. Establishment of Protocols for Global Metabolomics by LC-MS for Biomarker Discovery. *PLOS ONE*. 2016;11:e0160555. [doi:10.1371/journal.pone.0160555](https://doi.org/10.1371/journal.pone.0160555)
7. Wehrens R, et al. Improved batch correction in untargeted MS-based metabolomics. *Metabolomics*. 2016;12:88. [doi:10.1007/s11306-016-1015-8](https://doi.org/10.1007/s11306-016-1015-8)
8. `notame` package reference manual. [Bioconductor/R-universe manual](https://bioc-release.r-universe.dev/notame/doc/manual.html)
