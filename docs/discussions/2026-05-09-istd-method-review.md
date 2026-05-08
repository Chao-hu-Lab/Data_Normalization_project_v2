# ISTD 校正方法評估與決策紀錄

**日期**：2026-05-08 ~ 2026-05-09
**研究方向**：DNA Adductomics（鍵結體學）
**Cohort**：Breast Cancer Tissue, n=85（30 Exposure + 28 Normal + 20 Control + 7 QC），單批次
**Pipeline**：mzMine 出 feature → metabCombiner 對齊 → DNP（本 repo）Step 1–3
**MS 方法**：CID-only，無 HCD

---

## TL;DR

對這份 cohort，**決定不執行 Step 1 ISTD 校正**，下游 Step 2/Step 3 直接從 RawIntensity 接手。

理由（按證據強度遞增）：

1. **資料客觀條件**：6 個 DNA-ISTD 中，4 個（d4-N6-2HE-dA、15N5-8-oxodG、d3-N6-medA、d3-dG-C8-MeIQx）對應的 endogenous analyte 在這批樣本中**根本不存在或低於偵測**。它們在現有 RT-優先演算法下被「借用」去校正不同類別的 adduct。
2. **方法學限制**：untargeted + CID-only 無法可靠對 feature 做 nucleobase class assignment（HCD 才能穩定產生 diagnostic neutral loss），因此「class-matched ISTD」這條文獻黃金路徑不適用於本資料。
3. **In-house gold-standard 對照數據**：除了同類配對 ISTD，其他所有 ISTD 套上 endogenous 5-medC / 5-hmdC 都讓 CV% **比不校正還糟**（5-medC 從 22% 升到 23–54%；5-hmdC 從 4.7% 升到 9–45%）。
4. **系統設計與資料趨勢一致**：`evaluate_istd_gate` 原本就要求 ≥5 個 ISTD 在 QC 上 CV<20% 才執行 Step 1。這份資料 0 個達標，gate 預設行為 = skip Step 1。**這次討論證實 gate 的判斷正確**，不應引入 bypass 強行繞過。

---

## 1. 動機

初始觀察：6 個 DNA-ISTD 在 7 個 QC 樣本上的 CV% 為 25.4–31.2%（除 d3-dG-C8-MeIQx 為 46.7%）。直覺上「沒那麼糟」，但 `evaluate_istd_gate` 卻把整個 Step 1 跳過。質疑：

- 是不是 gate 的閾值（CV<20% × 5 個）對 adductomics 太嚴格？
- ISTD 校正方法本身是不是有方法學問題？
- 還是純粹 ISTD 數量不夠？

---

## 2. 文獻調查

### 2.1 ISTD 配對的 gold-standard 階層

文獻（FDA / EMA / WuXi industry guide / Tretyakova 2012 / 多篇 LC-MS bioanalysis review）一致指出：

1. **最佳**：SIL-IS = 同分子的同位素版本（13C, 15N, 2H, 18O），ionization 與 matrix effect 完全相同
2. **次佳**：結構類似 analog（functional groups 相同、極性相近）
3. **最差**：不同化學類別的 ISTD（藥物舉例：cimetidine 用於 creatinine 校正失敗）

> "Although structural analogues have been used in LC–MS and were demonstrated to be capable of increasing the linearity of the method, both accuracy and precision were not improved as compared to the SIL-IS method."
> — Multiple LC-MS bioanalysis reviews

### 2.2 DNA Adductomics 領域的實作慣例

所有有名的 DNA adductomics 方法（Villalta、Balbo、Tretyakova labs）**全部採 class-matched ISTD**：

| ISTD | 服務的 analyte 類別 |
|---|---|
| [15N5]-N6-methyl-dA | dA-adducts |
| [15N5]-N2-ethyl-dG | dG-adducts |
| [15N5]-pro-dG | dG-adducts |
| [D4]-O2-POB-dT | dT-adducts |
| [D4]-O6-POB-dG | dG-adducts |

來源：Villalta-style targeted MS3 adductomics, *Frontiers in Chemistry* 2019。

文獻明確承認：
> "It is not practical, or even currently possible, to include all internal standards necessary for screening of all DNA adducts."

### 2.3 跨 class 應用 ISTD 的直接實驗證據

Helm lab（RNA SILIS, *PMC6356711*）做了 m3C 用 m5U 作 ISTD（cross-class）的對照：

> "Using a chemically similar compound is sometimes sufficient for reliable quantification. **However, such an internal standard is unable to normalize the matrix effects and pH effects and thus the quantification results are perturbed as in the case for m3C.**"

這是 RNA 領域，但化學原理（不同 nucleobase 有不同 ionization efficiency 與 matrix response）同樣適用於 DNA adductomics。

### 2.4 替代方案：B-MIS 與 D-ratio

- **B-MIS（Boysen 2018, *Anal Chem*）**：data-driven ISTD 選擇——對每個 analyte 試所有 ISTD，挑校正後 QC RSD 最低的那個。內建 safeguard：**40% RSD 改善硬門檻** + raw RSD<10% 不校正 + 無合格 ISTD 時 fallback 到 raw。
- **D-ratio（Broadhurst 2018, *Metabolomics*）**：`std(QC) / std(samples)` per feature。後驗指標，確認 normalization 沒把生物變異也壓掉。

### 2.5 untargeted CID-only 的關鍵限制

- mzMine + metabCombiner 出來的 feature 只有 (m/z, RT)，**沒有結構標籤**
- 自動歸 nucleobase class 需要 MS2 的 diagnostic neutral loss（dR loss=−116.05、guanine=−151、adenine=−135、cytosine=−111、thymine=−126）
- **CID 通常不會穩定產生這些 loss**；HCD 才是 nucleoside 結構分類的標準方法
- 因此「class-matched ISTD」這條路徑在本資料無法自動實作

---

## 3. 診斷實驗（Step 1 全資料跑一次）

繞過 gate（暫時引入 `DNP_BYPASS_ISTD_GATE` 環境變數）後，讓 Step 1 對全部 325 個 analyte 套用現有 RT-優先加權演算法（RT 60% + ISTD CV 25% + intensity 10% + m/z 5%）。

### 3.1 整體結果

| 指標 | Raw QC CV% | Corrected QC CV% |
|---|---|---|
| 中位數 | 50.3% | 52.3% |
| 平均 | 55.4% | 58.7% |
| 25–75% IQR | 32.7–74.0% | 29.4–77.8% |

**逐 analyte delta CV 分布**（n=190 有有效 CV 的 analyte）：
- 改善（>5pp）：33.2%
- 無變化（±5pp）：29.5%
- **惡化（<−5pp）：37.4%**
- 中位 delta = −0.56pp（**整體幾乎打平、略傾向變差**）

### 3.2 逐 ISTD 的指派表現

| ISTD ID | 化學身份 | 接收的 analyte 數 | 改善% | 惡化% | 中位 delta CV |
|---|---|---|---|---|---|
| 269.1445/25.51 | d3-N6-medA（adenosine）| 36 | 17% | **58%** | −8.8 |
| 289.0852/16.59 | 15N5-8-oxodG（guanosine）| 53 | 32% | **51%** | −5.5 |
| 245.1332/12.28 | d3-5-medC（cytidine）| 48 | 48% | 25% | +3.1 |
| 261.1283/8.97 | d3-5-hmdC（cytidine）| 49 | 31% | 22% | +0.9 |
| 300.1615/23.35 | d4-N6-2HE-dA（adenosine）| 4 | 50% | 0% | +7.8 |
| 482.2102/40.57 | d3-dG-C8-MeIQx | 0 | n/a | n/a | 完全沒被選中（CV=47% 被 25% CV 權重排除）|

兩個「壞」ISTD（269、289）合計處理 89/190 = 47% 的 analyte，是拉低整體表現的主因。

### 3.3 化學解讀

- 269（d3-N6-medA, RT 25.5）位於色譜中段，演算法把它指派給很多 mid-eluting analyte，但其中許多其實是 cytidine 或 guanosine 類 → ionization 不匹配 → 校正引入雜訊
- 289（15N5-8-oxodG, RT 16.6）同樣寬 RT 範圍內什麼都收
- 245、261（cytidine 類，早期 RT）表現尚可，因為 RT 鄰近 + 結構鄰近碰巧重合
- 482（d3-dG-C8-MeIQx）因 CV>20% 被 CV 權重排除，**從未被選為任何 analyte 的 best ISTD**——但這正是它本該服務的 bulky guanosine adduct 類

---

## 4. In-house Gold-Standard 對照（XIC matched-pair）

從 XIC_Extractor pipeline 取得 7 個 analyte-ISTD 配對的偵測表，發現：

| Analyte | ISTD | Detection |
|---|---|---|
| **5-hmdC** | **d3-5-hmdC** | **71/85（84%），CV(ratio) = 6.6% n=7** ⭐ |
| **5-medC** | **d3-5-medC** | **81/85（95%），CV(ratio) = 7.7% n=6** ⭐ |
| N6-HE-dA | d4-N6-2HE-dA | 0/85（樣本未暴露 ethylene oxide）|
| 8-oxodG | 15N5-8-oxodG | 0/85（NL FAIL 67/85）|
| 8-oxo-Guo | [13C,15N2]-8-oxo-Guo | 2/85（RNA-only，本就不在 DNA 矩陣）|
| N6-medA | d3-N6-medA | 1/85（內生量過低）|
| dG-C8-MeIQx | d3-dG-C8-MeIQx | 0/85（未暴露）|

**只有兩個 cytidine 對可作 gold-standard 驗證**——這也意味著：4 個 ISTD 在這批樣本上**沒有真正的「主人」analyte**。

### 4.1 四種 CV% 對照（含 bootstrap 95% CI）

| 對照 | 5-medC | 5-hmdC |
|---|---|---|
| A. XIC gold-standard ratio（XIC tool 預算）| **7.7%** (n=6) | **6.6%** (n=7) |
| B. mzMine 現有演算法（自動選 ISTD）| **2.59%** [0.60–3.25] (n=6) | **3.48%** [0.94–4.10] (n=5) |
| C. 強制完美配對（mzMine raw / d3-X）| **2.59%** [0.60–3.25] (n=6) | **3.48%** [0.94–4.10] (n=5) |
| D. B-MIS 模擬（試所有 ISTD，挑最低 CV）| **245.1332/12.28**（正確）| **261.1283/8.97**（正確）|
| Raw（不校正）| 22.22% (n=7) | **4.72%** (n=7) |

**B = C 是預期結果**——演算法已選對 ISTD（恰好 RT 鄰近就是 class 配對的情況），所以等於強制完美配對。

### 4.2 D：B-MIS 模擬中所有 ISTD 的 CV% 排名

**5-medC 用各 ISTD 校正後 CV%**（raw=22.22%）：

| ISTD | CV% | 改善 | 通過 Boysen 40% |
|---|---|---|---|
| 245.1332/12.28（d3-5-medC）⭐ | 2.59% | +88.3% | ✓ |
| 482.2102/40.57 | 23.60% | −6.2% | ✗ |
| 261.1283/8.97 | 28.32% | −27.4% | ✗ |
| 289.0852/16.59 | 35.95% | −61.8% | ✗ |
| 269.1445/25.51 | 45.01% | −102.6% | ✗ |
| 300.1615/23.35 | 54.21% | −144.0% | ✗ |

**從最佳（2.6%）到最差（54%）相差 21 倍**。

**5-hmdC 用各 ISTD 校正後 CV%**（raw=4.72%）：

| ISTD | CV% | 改善 | 通過 Boysen 40% |
|---|---|---|---|
| 261.1283/8.97（d3-5-hmdC）⭐ | 3.48% | +26.3% | **✗（沒過 40%）** |
| 482.2102/40.57 | 9.42% | −99.8% | ✗ |
| 269.1445/25.51 | 32.04% | −579% | ✗ |
| 289.0852/16.59 | 38.95% | −726% | ✗ |
| 300.1615/23.35 | 41.77% | −785% | ✗ |
| 245.1332/12.28 | 45.26% | −859% | ✗ |

**5-hmdC 連最佳 ISTD 都沒過 Boysen 40% 門檻**，因為 raw CV% 已 4.72%，符合 Boysen safeguard B（raw<10% 不校正）。

### 4.3 對照的限制

- **僅 cytidine 類有 ground truth**：dG/dA/dT 類 adduct 沒有可用的 endogenous-ISTD 對，結論**只能外推 cytidine**
- **小樣本 (n=5–7)**：bootstrap CI 寬，CV% 點估計不確定性大
- **跨 pipeline missing 不一致**：mzMine 與 XIC 的 QC 偵測模式略有差異（如 5-hmdC 在 mzMine 強制配對只有 5/7 有效 QC），bootstrap CI 已反映這個不確定性
- **mzMine 比 XIC CV% 還低（2.59% vs 7.7%；3.48% vs 6.6%）**：可能來自整合演算法差異與 n 不同；**不能據此聲稱 mzMine 整合品質優於 XIC**，只能說「在這 2 個高豐度 cytidine 上 mzMine 整合接近 ceiling」

---

## 5. 結論與決策

### 5.1 對「ISTD 是不是從根本上做錯了」這個問題

**不是**。方法骨架（ratio × ISTD median）是業界標準。問題在三個層面：

1. **ISTD 配對策略**（單一最佳 ISTD by RT）對 untargeted DNA adductomics 是 suboptimal——文獻上 B-MIS（含 40% threshold）才是 untargeted 場景的正確答案
2. **ISTD 數量在現況下放大方法缺陷**——6 個 ISTD 中只有 2 個有對應 endogenous analyte，其他 4 個被「迫使」服務不該服務的 analyte
3. **資料設計層面**：CID-only 阻斷了「自動 class assignment」這條路，class-matched 路徑不可實作

### 5.2 ISTD 的真正能力邊界（這次討論最重要的科學發現）

**ISTD 只能管好自己的配對 analyte。** Cross-class 應用普遍引入更多誤差，**錯的 ISTD 套上去比不校正還糟**——這在 in-house gold-standard 對照上得到直接證實（5-medC 從 22% 推到 54%；5-hmdC 從 4.7% 推到 45%）。

### 5.3 決策

**這份 cohort 的 adductomics 分析將跳過 Step 1 ISTD 校正**：

- 維持 `evaluate_istd_gate` 原本邏輯（≥5 個 ISTD 在 QC 上 CV<20%），不引入 bypass
- 本資料 0 個 ISTD 達標 → gate 自動 skip Step 1
- 下游 Step 2/Step 3 直接從 RawIntensity 接手
- 所有 adduct 在 DNP pipeline 內視為 **semi-quantitative**
- 5-medC 和 5-hmdC 的絕對量值若需要，從 XIC pipeline（外部）取得 gold-standard quantitation

### 5.4 為什麼不選 B-MIS

雖然 B-MIS 是 untargeted 場景的文獻黃金做法，但對這份資料：

- B-MIS 在 easy case（5-medC、5-hmdC 兩個 cytidine 對）的選擇與現有 RT 演算法**完全相同**——沒有額外好處
- B-MIS 在 hard case（其他 4 個 ISTD 沒對應 analyte）會嘗試把它們套到不該套的 analyte 上；雖然 Boysen 40% 門檻會擋掉大部分，但**這等於對 47% 的 analyte 全部 fallback 到 raw**——結果與「整個跳過 Step 1」一致
- 引入 B-MIS 的工程成本與維護負擔，**換不到對這份資料有意義的差異**
- 若未來有 cocktail of class-matched ISTDs，再考慮 B-MIS 重新引入

### 5.5 關於 5-medC / 5-hmdC 的 cytidine 配對好處

跳過 Step 1 表示這 2 個本來能達 gold-standard CV%（2.6% / 3.5%）的 analyte 也不會在 DNP pipeline 內被校正。trade-off 接受：

- 這 2 個 analyte 的精確定量改在外部 XIC pipeline 進行
- DNP pipeline 內所有 adduct 一視同仁為 semi-quantitative，避免「2 個準、其他不準」的混合報告造成誤解
- 實作 cytidine 白名單會增加維護成本（白名單需要更新、測試），不值得為 2 個 feature 付出

---

## 6. 系統與資料的收斂

值得獨立記錄的觀察：

> **`evaluate_istd_gate` 的閾值（5 個 ISTD CV<20%）一開始被視為「擋路」，最終證實是正確的科學護欄。**

- Gate 設計理念：ISTD pool 不夠穩定就跳過 Step 1，讓 raw 進入下游
- 本資料 0 個 ISTD 達標
- 我們暫時繞過 gate，跑出 33% 改善 / 37% 惡化的結果
- 結合 XIC gold-standard 對照，確認 gate 的判斷是對的

這次討論驗證 gate 不需要為 adductomics 鬆閾值。Gate 保留現狀。

---

## 7. 文獻引用

1. Boysen, A.K., et al. **Best-Matched Internal Standard Normalization in Liquid Chromatography–Mass Spectrometry Metabolomics Applied to Environmental Samples.** *Analytical Chemistry* (2018). 全文 PDF：https://kheal.github.io/files/Boysen%20Heal2018.pdf
2. Ingalls Lab. **B-MIS-normalization (reference implementation).** GitHub: https://github.com/IngallsLabUW/B-MIS-normalization
3. Broadhurst, D., et al. **Guidelines and considerations for the use of system suitability and quality control samples in mass spectrometry assays applied in untargeted clinical metabolomic studies.** *Metabolomics* (2018). https://link.springer.com/article/10.1007/s11306-018-1367-3
4. Tretyakova, N., et al. **Quantitation of DNA adducts by stable isotope dilution mass spectrometry.** *Chemical Research in Toxicology* (2012). PMC3495176
5. Mass spectrometry for the assessment of the occurrence and biological consequences of DNA adducts. PMC4787602
6. Villalta, P.W., Balbo, S., et al. **Targeted High Resolution LC/MS3 Adductomics Method for the Characterization of Endogenous DNA Damage.** *Frontiers in Chemistry* (2019). https://www.frontiersin.org/journals/chemistry/articles/10.3389/fchem.2019.00658/full
7. Helm lab. **Production and Application of Stable Isotope-Labeled Internal Standards for RNA Modification Analysis.** PMC6356711
8. Nucleic Acid Adductomics Review (2025). PMC11932045
9. NOREVA: normalization and evaluation of MS-based metabolomics data. *NAR* (2017). https://academic.oup.com/nar/article/45/W1/W162/3835313
10. QComics: Recommendations for QC of Metabolomics Data. *Analytical Chemistry* (2024). PMC10809278

---

## 8. 後續可能（**非當前 scope**）

僅作備忘，不在此次決策範圍內：

- 若未來實驗導入 **cocktail of class-matched ISTDs**（dG-class、dC-class、dA-class 至少各一個 + 樣本中真實存在的 endogenous 對應分子），重新評估啟用 Step 1
- 若導入 **HCD scan**，feature 可獲得 diagnostic neutral loss → class assignment 可自動化 → class-aware ISTD 配對成為可實作路徑
- 若未來需要 selective correction（如僅對少數 high-confidence pair 校正），建議引入 **B-MIS + Boysen 40% threshold + D-ratio 三層保護**，而非單純 minRSD 演算法

---

## 9. 工作區清理紀錄（本 commit 同時完成）

本次討論期間曾在 `src/metabolomics/processors/istd.py` 中加入 `DNP_BYPASS_ISTD_GATE` 環境變數作為診斷用 bypass。基於上述決策，該 bypass 已從 codebase **移除**（連同 PostToolUse formatter 引入的 1300 行雜訊一併還原），理由：

1. 診斷已完成，不需要再次執行
2. Gate 的判斷與資料趨勢一致，沒有「過度保守」的問題，不應保留 bypass
3. 保留 bypass 會增加維護負擔
4. 若未來需要重新評估，建議用獨立 diagnostic script（不修改 production code）

`tmp_diagnostic_run/`（含 Step 1 對照腳本與輸出）與 `uv.lock`（uv 為診斷自動產生）也一併移除——所有改動本來就是為了強制 Step 1 跑起來而存在，現在 Step 1 不跑了，自然不需要。

本 branch 最終只保留：
- `0c03ead` — fix: correct DNA reference column unit from mg to ug（5 個檔案的 9+/9− 單位修正）
- 本 commit — docs: add ISTD method review discussion record
