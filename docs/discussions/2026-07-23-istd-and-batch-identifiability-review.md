# ISTD 與 batch 可識別性重審

**日期**：2026-07-23
**狀態**：ISTD 與 batch/QC identifiability review 已完成
**適用情境**：LC-MS untargeted DNA adductomics；大量未知 feature；只有少量 spiked ISTD，沒有每個 feature 的 authentic analyte standard 或 matched SIL-IS

## 決策摘要

**近期研究沒有證明：少量 non-matched ISTD 可以無條件、安全地校正大量 untargeted unknown features。**

目前可支持的分層決策是：

1. **Matched stable-isotope-labelled internal standard（SIL-IS）**仍是特定 analyte 校正 ionization、matrix effect、sample preparation loss 與 injection variation 的首選；若再配合 authentic analyte calibration curve，才可主張經驗證的 concentration。
2. **Class-matched／RT-near surrogate IS**只能做條件式的 relative／semi-quantitative correction。結構或 RT 接近只是合理先驗，不是效能證明；必須用 matrix-matched QC、technical replicates、spike recovery 或已知 analyte 做 feature-level 驗證。
3. **Single/global IS**適合作 system suitability、injection/process monitoring，或在已驗證的小範圍內提供 relative scaling；不應預設代理所有 unknown features。直接 head-to-head 證據顯示，錯配常降低 precision。
4. **Post-acquisition data-driven matching**（例如 B-MIS、Metchalizer）是可研究的 fallback，不是普遍安全的 substitution。其有效性依賴足夠的 QC/reference data、randomized batches、out-of-sample validation，以及 abstention；不能只看 fit 後 QC CV。
5. **對目前這批 adductomics data，Step 1 預設 SKIP 仍合理。** 少數高可信 matched pair 可留給 targeted/XIC assay；不應把少量 DNA-adduct ISTD 擴張成整張 unknown-feature matrix 的 universal denominator。

## 先釐清：內標、外標與 calibration curve 不是同一件事

| 元件 | 主要回答的問題 | 能證明 | 不能單獨證明 |
|---|---|---|---|
| Spiked internal standard（IS） | 同一樣本在前處理、注射、離子化時受到多少技術擾動？ | IS 自身及與其行為相近 analyte 的相對校正能力；run/process monitoring | Unknown analyte 的真實濃度、response factor、recovery、linearity |
| Authentic analyte calibration standards（常被口語稱為「外標」） | 已知濃度的 analyte 產生多少 response？ | analyte-specific response curve、range、LLOQ/ULOQ | 未必能獨自抵消每個 study sample 的 matrix effect/process loss |
| Analyte/IS response-ratio calibration curve | 已知 analyte concentration 與 analyte/IS ratio 的關係？ | 經 validation 後的定量 concentration | 不能自然外推到沒有 authentic standard、未知身份或 response factor 未知的 feature |
| QC / reference samples | 方法在固定矩陣與重複量測中的表現？ | precision、drift、batch behaviour；可評估 correction 是否改善 | 沒有 spike/recovery 或 reference value 時，不能證明 accuracy |

**Observed evidence**：ICH M10 要求 suitable IS 加入 calibration standards、QCs 與 study samples，並建議 MS 優先使用 stable-isotope-labelled analyte；同時要求每個 analyte 有自己的 calibration curve。Calibration standards 是在相同 biological matrix 中加入已知量 analyte。即使使用 labelled surrogate analyte，仍須證明 response factor 在 calibration range 內穩定、matrix effect 與 recovery 與 authentic analyte 相似。
來源：[ICH M10 Bioanalytical Method Validation and Study Sample Analysis, 2022](https://www.fda.gov/media/128343/download)（§3.1、§3.2.4、§7.1）。

**Inference for this repo**：沒有 authentic analyte standard／calibration curve，不代表 IS 完全無用；它仍可用於 technical monitoring 或 validated relative correction。但輸出只能稱為 relative response／semi-quantitative abundance，不能稱 absolute concentration 或 analyte recovery。

## 各種 ISTD 策略的證據邊界

### 1. Matched SIL-IS：用途最清楚，但只覆蓋它的 analyte

**Observed evidence**

- Ulvik et al. 對 70 多個 biomarkers、4 個 MS platforms、60 個 96-well runs，回溯比較 1,442 組 analyte/IS pairing。Matched A/SIL-IS 的 median between-run CV 為 2.7–5.9%；nonmatching pairs 的 median CV 額外增加 2.9–10.7 percentage points。Nonmatching pair 的 CV 隨 RT 差距增加，Spearman ρ 為 0.17–0.93；結構相近有時改善，但並不保證。
  來源：[Ulvik et al., *Analytical Chemistry* 2021, DOI 10.1021/acs.analchem.1c00119](https://doi.org/10.1021/acs.analchem.1c00119)。
- ICH M10 仍把 stable-isotope-labelled analyte 定位為 MS 中「whenever possible」的推薦 IS；即使 isotopically labelled surrogate，也要求驗證 response factor、matrix effect 與 recovery。
  來源：[ICH M10, 2022](https://www.fda.gov/media/128343/download)。

**Can support**

- 同一 analyte 跨樣本的 relative response。
- 若 IS 在 sample preparation 前加入，可共同追蹤該 analyte 的 extraction/process loss、injection 與 ionization variation。
- 與 matrix-matched authentic analyte calibration curve、QC、accuracy/precision validation 合用時，可支持 concentration。

**Cannot support**

- 不會自動把校正能力傳遞給不同結構、不同 RT 的 unknown feature。
- 單有 matched IS、沒有 analyte calibration／reference response，仍不能完整證明 absolute amount、linearity、LLOQ 或 recovery。

### 2. Class-matched／RT-near surrogate：合理候選，不是保證

**Observed evidence**

- 2021 head-to-head study 顯示 RT 越不匹配，nonmatching ratio 的 precision 通常越差；close structural analogue 常較好，但不是一致規律。作者明確要求 nonmatching IS 要以 assay acceptance criteria 驗證。
  來源：[Ulvik et al. 2021](https://doi.org/10.1021/acs.analchem.1c00119)。
- LipidMatch Normalizer 以 class、adduct、RT 排名替 analyte 配 surrogate IS；作者指出 lipid class 對 ionization efficiency 影響最大，RP-LC 中即使同 class 也可能因 RT 分散而無法校正 region-specific ion suppression。該方法把結果定位為 relative／semi-quantitation；RP 下不應把這類 normalization 視為 quantitative。
  來源：[Koelmel et al., *BMC Bioinformatics* 2019, DOI 10.1186/s12859-019-2803-8](https://doi.org/10.1186/s12859-019-2803-8)。
- Drotleff & Lämmerhofer 以不同 lipid classes 的 SIL standards 系統比較多種 post-acquisition normalization，並用 pooled QCs 的 CV、MAD、variance 評估；其結論不是指定一個 universal strategy，而是要求逐 dataset 驗證 data integrity。
  來源：[Drotleff & Lämmerhofer, *Analytical Chemistry* 2019, DOI 10.1021/acs.analchem.9b01505](https://doi.org/10.1021/acs.analchem.9b01505)。

**Can support**

- 已知 class/adduct 且 chromatographic behaviour 接近時，作 feature-specific candidate correction。
- 在 independent technical replicates、QC 或 spike-recovery 證明改善時，提供 relative／semi-quantitative values。

**Cannot support**

- 只靠「最近 RT」或「同 nucleobase class」就主張 recovery、matrix effect 或 absolute concentration 被正確校正。
- Feature 尚未 annotation、class 不明時，不能把 class matching 當成 observed fact。

### 3. Single/global IS：可監測系統，不能預設代理整張表

**Observed evidence**

- 2023 大型 GC-MS plasma study使用 25 個 isotope-labelled standards、4,104 study samples、413 cohort-pooled QCs 與 413 independent commercial plasma QCs。23 個 matched endogenous/ISTD ratios 的 median RSD 為 19%；以 sorbitol-d8 作 20 個 sugars/sugar alcohols/disaccharides 的 single class surrogate，沒有改善 technical error。作者總結 internal standards 應限於 specific metabolites 的 absolute concentration estimation，不應用於 broad-scale normalization。
  來源：[Zhang et al., *Metabolites* 2023, DOI 10.3390/metabo13080944](https://doi.org/10.3390/metabo13080944)。
- 同研究中，把 all ISTDs 加總成 iTIC，對長期大型資料也未達可接受 precision；這表示「多個 IS 加總」本身不會自動變成 universal correction factor。這是 GC-MS/derivatization plasma 的直接證據，不能無條件外推到所有 LC-MS assay，但足以否定 universal safety claim。
  來源同上。
- DNA adductomics 的直接先例確實存在：Carrà et al. 因不可能為所有 adduct 準備 IS，將 36 個 adduct 的 AUC 除以單一 [^15N5]-N²-ethyl-dG 與 DNA amount，並明確稱為 **relative quantitation**；其 validation 是三次 instrument technical replicates，沒有證明每個 cross-adduct ratio 的 accuracy/recovery。
  來源：[Carrà et al., *Frontiers in Chemistry* 2019, DOI 10.3389/fchem.2019.00658](https://doi.org/10.3389/fchem.2019.00658)。

**Inference**

- Single/global IS 有實際用途：system suitability、injection/process alarm、粗略 relative denominator，或特定 assay 已用 independent evidence 驗證的 limited scope。
- 「領域有人這樣做」只能證明它是一種 relative reporting convention，不能證明跨化學類別 correction 無偏。

### 4. Post-acquisition data-driven matching：有方法，但不是免驗證捷徑

#### B-MIS（2018，作為近期方法的直接前導證據）

Boysen et al. 讓每個 metabolite/feature 選擇在該 batch 中最能降低 obscuring variation 的 isotope-labelled IS，並在 marine samples 展示可救回原本會因 variation 被排除的 untargeted features。這證明「unknown feature 可由 empirical matching 找 surrogate」是可行研究方向。
來源：[Boysen et al., *Analytical Chemistry* 2018, DOI 10.1021/acs.analchem.7b04400](https://doi.org/10.1021/acs.analchem.7b04400)。

但它不能證明：

- 被選 IS 與 feature 有化學等價性；
- 最低 training-QC CV 等於 study samples 的 unbiased correction；
- 在 QC 稀疏、QC 與 study matrix 不一致時仍可靠。

#### Metchalizer（2020/2021）

**Observed evidence**

- 以 10 個 stable-isotope-labelled IS 的 latent variables 加 mixed-effects model 校正 9 batches。對跨 batch 保留的 features，Log-Metchalizer 在 batch prediction、QC variance、與 targeted quantitative measurements 的 correlation，以及 49 個 IEM patients、195 個 biomarkers 的 detection 上表現良好，out-of-batch controls 的 biomarker detection 可接近 15 個 within-batch controls。
  來源：[Bongaerts et al., *Metabolites* 2021, DOI 10.3390/metabo11010008](https://doi.org/10.3390/metabo11010008)。
- 它不是「10 個 IS 各自直接除全部 feature」；模型假設能被 IS latent variables 解釋的 covariance 是 technical variation，再用 batch effects 處理 residual。
- 原始約每 mode 20,000 features；要求九批都能 matched 後，只保留 positive 446、negative 328 features。作者明列這會丟失 clinically relevant biomarkers，必要時仍需 within-batch references。
- 作者明列 overcorrection 風險：若 batches 因 biology 而不同，模型會把 biological differences 當成 unexplained batch/technical variation；因此要求 samples across batches randomized。
- 增加 IS 數目未單調改善所有 metabolites；某些 IS combinations 使特定 metabolites 改善或惡化。

**Inference**

- Metchalizer 是「在高度結構化 clinical reference workflow 中經驗證的 multivariate model」，不是少量 non-matched ISTD 的 universal license。
- 對 biology 與 batch/order 混雜、features 稀疏、跨批不 consistently detected 的 adductomics，它的核心假設可能不成立。

### 5. 2025 IROA：真正的進展，但不是少量 surrogate 的突破

**Observed evidence**

- IROA TruQuant 使用 fully ^13C-labelled yeast metabolite library、chemically identical isotopolog pairs、long-term reference standard 與 companion software。研究跨 IC、HILIC、RPLC、正負離子、clean/unclean source、plasma/urine，展示 ion-suppression correction；完整資料辨識/量測 539 metabolites。
  來源：[Mahmud et al., *Nature Communications* 2025, DOI 10.1038/s41467-025-56646-8](https://doi.org/10.1038/s41467-025-56646-8)。
- Correctability 依賴 natural-abundance metabolite 與其 chemically equivalent ^13C partner 都被偵測。作者把只在一個 channel 出現或不在 yeast library 的 metabolites 列為主要限制。
- 方法本質上擴大 matched SIL-IS coverage，而不是證明 non-matched IS 可代理 unknowns。其廣泛 coverage 主要是 yeast 能產生、且 library 中已有 labelled match 的 metabolites；報告中 lipids 僅 14 個。
- ClusterFinder 與 workflow 為 IROA Technologies 產品；三名作者受雇於 IROA Technologies。這不否定結果，但獨立 external replication 仍重要。

**Inference for DNA adductomics**

- 若未來能建立涵蓋 DNA adduct chemical space 的 labelled biological/reference library，這類方法可能改變能力邊界。
- 目前 yeast-derived IROA library 不能被假定覆蓋未知 endogenous/exposure-derived DNA adducts，因此不是現有 Step 1 的 drop-in replacement。

## Annotation 前後，能做的事情不同

### Feature 尚未 annotation

可做：

- 監測 spiked IS 自身 stability、extraction/injection alarms。
- 以 RT、correlation 或 model 建立 **candidate** surrogate mapping。
- 在有充分 QC/technical replicates 時做 blinded/out-of-sample performance test。
- 沒有可靠改善時 abstain，保留 raw/Step 2/Step 3 values。

不可做：

- 聲稱 unknown feature 與某 ISTD 同 class、同 recovery 或同 matrix response。
- 把 analyte/IS ratio 稱 concentration。
- 用 training QC fit 後 CV 當唯一 acceptance evidence。

### Feature 已高可信 annotation

可以升級：

- 優先找 analyte-specific SIL-IS。
- 次選同 class、同 adduct、RT-near surrogate，並用 authentic standard／matrix-matched spike／technical replicate 驗證。
- 對重要 finding 建立 targeted PRM/MRM/XIC assay與 calibration curve。
- 重要 feature 若無 matched standard，仍可以 relative abundance 報告，但需保留 method qualifier 與 raw-vs-corrected sensitivity analysis。

Carrà et al. 的 adductomics workflow也是先用 DDA-CNL/MS³ 發現／鑑別，再用 PRM-MS² 做 relative quantitation；putative identifications 盡可能以 SIL-IS 或 synthetic standard 的 RT、MS²、MS³ 確認。
來源：[Carrà et al. 2019](https://doi.org/10.3389/fchem.2019.00658)。

## 對目前 Step 1 的建議 contract

### 建議保留的角色

1. `ISTD_QC_MONITORING`
   - 報告每個 ISTD 的 missingness、QC CV、drift、saturation、RT stability。
   - 這是 diagnostics；不改 feature matrix。

2. `MATCHED_ISTD_CORRECTION`
   - 只有 explicit analyte ↔ SIL-IS mapping 且 validation 通過的 features。
   - 輸出標記 `corrected_matched_istd`。

3. `VALIDATED_SURROGATE_CORRECTION`（未來可選）
   - 必須有可稽核 mapping rule、independent evaluation、minimum improvement、severe-tail guardrail 與 abstention。
   - 輸出標記 `corrected_surrogate_istd`；不可與 matched correction 混稱同一證據等級。

4. 其餘 feature：
   - `uncorrected_no_valid_istd`。
   - 進 Step 2/Step 3，不把 skip 當 failure。

### 不建議實作的角色

- 只因「有加 ISTD」就將全部 features 除以單一／最近 RT ISTD。
- 在沒有 independent QC/reference evidence 時，自動挑使 training QC CV 最小的 ISTD。
- 將 unmatched ratio 輸出稱為 absolute concentration 或 corrected recovery。

## 是否存在近期「突破」？

**回答：有擴大 matched coverage 與 multivariate modeling 的進展，但沒有少量 non-matched ISTD universal correction 的突破。**

| 進展 | 真正新增的能力 | 仍未解決 |
|---|---|---|
| Metchalizer | 用多個 IS covariance + mixed-effects model整合跨 batch reference populations | biology/batch confounding、稀疏跨批 features、overcorrection |
| SERDA 等 QC models | 大量、頻密、matrix-matched QC 下可超越 classic IS ratios | QC 稀疏時不可用；不是 ISTD breakthrough |
| IROA TruQuant | 用數百個 chemically matched labelled metabolites擴大 suppression correction coverage | library 外 unknowns、特殊 chemical space、成本/軟體依賴、獨立 replication |
| B-MIS/class/RT mapping | empirical surrogate 選配 | 需要 validation；不能證明 chemical equivalence 或 accuracy |

因此，對「6 個 DNA ISTD 能不能校正數百個 unknown adduct features」的答案仍是：**不能預設可以；目前 evidence 支持 monitoring、少數 matched correction、其餘 abstain。**

## 2026-07-23 real-data sensitivity evidence

這一輪另以實際組織資料的七個 XIC ISTD 做一次性診斷。診斷程式與圖表留在 local `build/`，不作為 production asset；以下只保留可重現的判斷與門檻定義。

### Quantitative source contract

- XIC 是使用者調校過、結合 MS1/MS2 證據的原生 integration，作為主要 area evidence。
- FH+MZmine 最終矩陣以 FH 負責 qualitative feature identity、MZmine 負責 quantitative area。
- 六個共同 ISTD 的 workbook area 可追溯到 pre-merge MZmine peak area 乘以 60；這是預期單位 contract，不是來源異常。
- 因此 cross-pipeline area comparison 實際比較 XIC 與 MZmine-derived quantitation，不能拿來驗證 FH 的定性正確性。

### XIC versus MZmine-derived areas

在每個 sample type 內各自中心化後，六個共同 ISTD 的 XIC/MZmine area Spearman \(\rho\) 為 0.921–0.999。多個 late-QC collapse 在兩種 integration 中方向一致，降低了「單一 integration pipeline artifact」的可能性；仍有六個 sample-feature integration disagreement 需要 raw-peak review。

這項一致性只表示兩種 integration 對同一批 raw data 的主要 area trajectory 接近，不是獨立生物學驗證。

### Generic ISTD correction stress test

將七個 XIC ISTD 逐一當成 generic donor，使用

\[
y'_{recipient,i}
= y_{recipient,i}
\times
\frac{\operatorname{median}(IS_{donor,QC})}{IS_{donor,i}}
\]

校正其餘六個 ISTD，得到：

- 沒有任何 donor 降低其餘 recipient 的 median QC CV。
- 各 donor 的 median QC CV change 為 +2.1 至 +29.5 percentage points。
- 最穩定的 `d3-5-hmdC` 仍只有 1/6 recipient 改善；三個 recipient 惡化超過 2 percentage points。
- `d4-N6-2HE-dA` 對 5/6 recipient 引入嚴重 late-QC failure。
- 其他不穩定 donor 也可引入 1–4 個 severe late-QC failures。

本次 severe late-QC diagnostic flag 定義為：最後兩個共同 QC 相對前段 QC median 的 corrected absolute log2 error > 1，且相較 raw 額外增加 > 0.5。這是本次 stress-test flag，不是跨 assay 的文獻硬標準。

### Injection order versus sample type

實際 workbook 中 sample type 對 injection order 的解釋度約為 \(R^2=0.895\)，表示 sample type 與 order 高度相關。ISTD RT 與 area trajectory 證明 run-order-associated technical behavior 確實存在，但各 ISTD 的 area behavior 並不共享一個 global multiplicative factor。

因此 ISTD 能推翻「組別分離必然是純 biology」的安全假設，卻不能把 observed group effect 唯一拆成 biology 與 order drift。這是 study-design identifiability 限制，不是再換一個 correction algorithm 就能補回的資訊。

### Resulting decision

- Broad adductomics Step 1 預設 `SKIP`。
- ISTD 保留作 monitoring；只有 explicit matched mapping 或另行驗證的 surrogate 可做 selective correction。
- 不使用 single/global/nearest-RT ISTD 作整張 unknown-feature matrix 的 denominator。
- XIC 作 primary area evidence；MZmine-derived area 作 sensitivity comparison。
- Group/order confounding 必須在 downstream sensitivity analysis 與結果敘述中保留，不能宣稱已由 ISTD correction 解決。

Implementation follow-up：

- [DNP issue #33](https://github.com/Chao-hu-Lab/Data_Normalization_project_v2/issues/33)：以 monitoring／matched correction／validated surrogate／abstention 取代 legacy universal auto-match contract。
- [DNP issue #34](https://github.com/Chao-hu-Lab/Data_Normalization_project_v2/issues/34)：建立 sample type／injection order／batch／QC pool 的 design-identifiability preflight 與 evidence receipt。

## Batch/QC identifiability：QCA 與 QCB composition 不同時，哪些仍可做？

### 問題設定

- Batch A 的 pooled QC（QCA）由 `exp + nor` 組成。
- Batch B 的 pooled QC（QCB）由 `exp + nor + con` 組成。
- QCA 與 QCB 不是同一 biological material，也不是同一 composition 的 aliquots。

此設計必須拆成兩個不同問題：

1. **批內 drift**：同一 batch 內，instrument response 是否隨 injection order 漂移？
2. **跨批 level alignment**：Batch A 與 B 的 feature level 差多少是 technical batch，而不是 QC pool composition？

第一個問題仍可能可識別；第二個問題不能由 QCA/QCB ratio 單獨識別。

### 1. 為什麼不可用 QCA/QCB median ratio 做跨批 scaling？

設某 feature 的 pooled-QC observation 為：

\[
\log Y_{QC,b} =
\text{technical batch effect}_b +
\text{pool composition effect}_b +
\epsilon
\]

QCA 與 QCB 的 ratio 同時包含：

- instrument、column、source、sample preparation 等 technical batch difference；
- `exp + nor` 與 `exp + nor + con` 的 biological pool composition difference；
- 各 subtype 在 pool 中的比例與 feature abundance difference。

沒有 shared material、bridge sample 或同一樣本跨批重測時，只有一個 observed ratio，卻至少有 technical 與 composition 兩個未知來源，因此不可分解。

**Observed evidence**：Broadhurst et al. 將 pooled study QC 定位為代表該 study sample matrix 的重複材料，可用於 conditioning、precision、drift correction；跨 study／跨 laboratory comparability 則需要 long-term reference QC 或 standard reference material。這個角色分工不支持把 composition 不同的兩個 study-specific pools 視為同一 absolute anchor。
來源：[Broadhurst et al., *Metabolomics* 2018, DOI 10.1007/s11306-018-1367-3](https://doi.org/10.1007/s11306-018-1367-3)。

**Additional observed evidence**：Ramos et al. 比較不同 QC preparation type 時，發現 QC 類型會顯著影響 downstream feature selection、VIP 與 biomarkers，最高可有 54% biomarkers 為特定 QC preparation 所獨有。其設計不等同本案的 `exp+nor` vs `exp+nor+con`，所以不能直接量化本案 bias；但它直接支持「QC composition/preparation 不是可忽略的 technical detail」。
來源：[Ramos et al., *Analytical and Bioanalytical Chemistry* 2025, DOI 10.1007/s00216-024-05646-6](https://doi.org/10.1007/s00216-024-05646-6)。

**Decision**

- 禁止用 `median(QCA) / median(QCB)`、feature-wise QCA/QCB ratio 或 QC batch scaling 將 A/B 拉到共同 absolute level。
- 這不是 scaling formula 選錯，而是 denominator 不具共同 biological meaning。

### 2. 批內 QC drift 仍可各自估計

若 QCA 在 Batch A 從 run 開頭到結尾都使用同一固定 composition pool，QCB 在 Batch B 也同樣如此，則：

\[
\log Y_{QC,b}(t) =
\alpha_b + f_b(t) + \epsilon
\]

在每一 batch 內，pool composition effect 被固定在 intercept \(\alpha_b\)；隨 injection order 變化的 \(f_b(t)\) 仍可被估計。這只能移除 **within-batch drift**，不能使 \(\alpha_A\) 與 \(\alpha_B\) 具有共同尺度。

**Observed evidence**：QC-SVRC 以每批序列中的 repeated QC observations 建立 feature-wise signal correction，依賴的是 QC 在 injection sequence 中提供穩定、重複的 drift anchor。
來源：[Kuligowski et al., *Analytica Chimica Acta* 2018, DOI 10.1016/j.aca.2018.04.055](https://doi.org/10.1016/j.aca.2018.04.055)。

**Inference for this repo**

- Batch A 與 B 可以各自執行現有 feature-wise QC drift gate。
- 每個 feature 仍須滿足該 batch 的有效 QC 數、端點覆蓋、trend evidence、cross-validation 與 severe-tail guardrail。
- 若某 feature 在 QCA 或 QCB 中因 pool dilution/composition 而少量或未檢出，該 batch 對該 feature abstain；不能 impute QC 再造 drift anchor。
- 批內 correction 完成後，矩陣仍是「各批已去除可識別 drift」，不是「已完成跨批 calibration」。

### 3. ComBat 的可用性看 study-sample design，不看 QCA/QCB 是否相同

對 study samples 考慮：

\[
\log Y =
\beta_0 +
\beta_{\text{subtype}}\text{Subtype} +
\beta_{\text{batch}}\text{Batch} +
\beta_{\text{cov}}\text{Covariates} +
\epsilon
\]

是否能同時估 subtype 與 batch，首先取決於 `batch × subtype` design matrix 是否 full rank，以及各 biological contrasts 是否有 overlap。

**Observed evidence**

- reComBat 明確把 biological covariates 與 batch effects 放入設計矩陣；regularization 可改善 high-dimensional 或較不穩定的 estimation，但不能從完全混雜的資料創造缺少的 biological overlap。
  來源：[Borgwardt Lab et al., *Bioinformatics Advances* 2022, DOI 10.1093/bioadv/vbac071](https://doi.org/10.1093/bioadv/vbac071)。
- Nygaard et al. 顯示，當 biological group 與 batch confounded 或 highly unbalanced 時，batch correction 可能造成 exaggerated confidence 與 false-positive signal；即使模型可執行，也不代表 corrected data 的 group inference 可信。
  來源：[Nygaard et al., *Biostatistics* 2016, DOI 10.1093/biostatistics/kxv027](https://doi.org/10.1093/biostatistics/kxv027)。
- Quartet multi-omics benchmark 顯示，batch correction performance 與保留 biological signal 需要 reference materials、ground truth 與多維指標共同評估；單看 PCA batch mixing 或一個 dispersion metric 不足以證明成功。
  來源：[Yu et al., *Genome Biology* 2023, DOI 10.1186/s13059-023-03047-z](https://doi.org/10.1186/s13059-023-03047-z)。

**本案的識別判斷**

- 若 `exp` 與 `nor` 都出現在 A、B 兩批，則 `exp vs nor` 與 batch 有 overlap，通常可在 raw log model 中同時估 subtype 與 batch；仍須檢查 counts、rank、leverage 與 `batch × subtype` interaction。
- 若 `con` 只出現在 Batch B：
  - `con vs exp/nor` 的 **Batch B 內 contrast** 可估。
  - `con` 在跨批資料中的 stability、batch interaction 或「假如 con 在 A 會是多少」不可由現有資料驗證。
  - 即使 additive design matrix 數值上未必 singular，global `con` coefficient 仍完全依賴 Batch B 內比較及「沒有 batch × subtype interaction」的不可驗證假設；因此不可把它解讀為已跨批校正的 universal con effect。
- 若某 subtype 只存在一批，且該批沒有其他可形成 overlap 的 subtype，group 與 batch 完全 collinear，ComBat／linear model 都不能分離兩者。

**Decision**

- ComBat 不作 primary matrix correction。
- 在 design full rank、exp/nor 有跨批 overlap 時，ComBat 可作 sensitivity-only。
- 如果顯著結果只在 ComBat 後出現，raw+batch model 與 batch-stratified analysis 都不支持，停止宣稱已成功合併。

### 4. 最可靠的 rescue 不是更靈活的 algorithm，而是共同測量 anchor

**Observed evidence**

- Systematic benchmarking 顯示，cross-batch harmonization 最可靠的資訊來自可持續、共享 reference samples；reference-based methods 能否工作取決於 reference 與 study samples 的代表性及跨批重複。
  來源：[Nature Computational Science 2023, DOI 10.1038/s43588-023-00500-8](https://doi.org/10.1038/s43588-023-00500-8)。
- 同一 biological samples 的 cross-platform／cross-batch replicate measurements可直接估計 mapping，比只依賴不同 composition pooled QCs 提供更強的 bridge。
  來源：[Nature Communications 2021, DOI 10.1038/s41467-021-25210-5](https://doi.org/10.1038/s41467-021-25210-5)。

**Decision hierarchy**

1. 最佳：保留 aliquots，將同一批 shared reference／bridge samples 在 A、B 重測。
2. 次佳：挑一組代表 `exp`、`nor`、`con` chemical space 的 study samples 做 same-sample remeasurement。
3. 若不可重測：不做 absolute batch alignment，改採 model-based與 stratified evidence triangulation。

### 5. 建議 primary analysis arms

#### Arm A：per-batch QC drift correction

- Batch A 只用 QCA sequence。
- Batch B 只用 QCB sequence。
- Feature-wise gate 決定 linear/LOWESS/uncorrected。
- 結果只宣稱 within-batch drift addressed。

#### Arm B：raw log-scale covariate model

在不做 QCA/QCB inter-batch scaling 的矩陣上建模：

\[
\log_2(Y) =
\beta_0 +
\beta_{\text{subtype}}\text{Subtype} +
\beta_{\text{batch}}\text{Batch} +
\beta_{\text{cov}}\text{Covariates} +
\epsilon
\]

- 先檢查 `batch × subtype` counts 與 model-matrix rank。
- 視 sample size 評估 `Subtype × Batch` interaction；interaction 不穩定時至少比較方向。
- Missingness/imputation 必須沿用 Step 4 tag contract，不能為 batch model 另造一套全域 imputation。

#### Arm C：batch-stratified contrasts

- 在 A、B 各自估 `exp vs nor`。
- 比較 effect direction、magnitude、uncertainty與 heterogeneity；條件允許才做 fixed/random-effects meta-analysis。
- `con` 若只在 B，所有涉及 con 的 primary comparison 限定 Batch B。

#### Arm D：ComBat sensitivity

- 僅在 full-rank、overlap 可接受時執行。
- 與 Arm B/C 對照 effect direction、rank、significance stability。
- 不以 PCA batch mixing 當成功唯一證據。

### 6. 最小 evidence loop

1. **盤點設計**
   - 產出 `batch × subtype` count table。
   - 檢查 model matrix rank、condition number、empty cells、pairing/covariate balance。

2. **確認批內 QC 能做什麼**
   - 每批、每 feature 計算有效 QC 數、首尾覆蓋、trend、LOOCV improvement、tail error。
   - 標記 corrected / no drift / insufficient QC / endpoint failure。

3. **跑三個不依賴相同 QC composition 的 primary/sensitivity views**
   - raw log model：`subtype + batch + covariates`。
   - A/B stratified `exp vs nor`，再比較/合併 effect。
   - ComBat sensitivity。

4. **比較證據，不比較漂亮程度**
   - effect direction 是否一致；
   - effect magnitude 是否在合理範圍；
   - `Subtype × Batch` interaction；
   - missingness、outlier 與 imputation sensitivity；
   - paired samples 是否維持成對。

5. **停止條件**
   - result 只有 ComBat 後顯著；
   - A/B effect directions 相反且 interaction/heterogeneity 明顯；
   - design matrix rank deficient；
   - con conclusion 需要假設其在 Batch A 的未觀測 behaviour；
   - correction 嚴重改變 tail、missingness 或主要 biological ordering。

遇到任一停止條件，不輸出「merged corrected matrix」作 primary evidence；回報 batch-specific results，或安排 shared-reference/same-sample remeasurement。

### Batch 部分的 observed facts、inference、decision、unknowns

#### Observed facts

1. QCA 與 QCB 的 biological composition 不同。
2. Study-specific pooled QC 適合代表其批內 matrix 與 drift；不同 pool 不構成共同 absolute reference。
3. QC preparation/composition 可實質改變 downstream feature/VIP/biomarker selection。
4. ComBat 類方法需要 study-sample design 提供 biology/batch overlap；regularization 不會補出未觀測 cell。
5. Shared reference 或 same-sample cross-batch measurement提供最直接的 bridging evidence。

#### Inference

1. QCA/QCB ratio 不能拆成純 technical batch factor。
2. 每批 QC composition 固定時，批內 drift 仍可獨立估計。
3. `exp vs nor` 若兩批都有觀測，可用 raw+batch model與 stratified analysis triangulate。
4. `con` 只在 B 時，con-related primary inference 應限 B 內。

#### Decision

- 不做 QC median inter-batch scaling。
- Primary：per-batch QC drift + raw log model + batch-stratified/meta evidence。
- ComBat：sensitivity-only。
- 若結論依賴 ComBat 才成立，停止合併。

#### Remaining unknowns

1. 實際 `batch × subtype` counts、pairs與 covariates 是否平衡。
2. `exp/nor` 是否確實在 A/B 都有足夠樣本，不只是名義上存在。
3. QCA/QCB 每批的 injection count、端點、feature detection coverage。
4. 是否仍有原始 aliquots可做 shared-reference 或 selected same-sample remeasurement。
5. 是否存在強烈 `Subtype × Batch` interaction；若有，跨批共同 effect 可能不具意義。

## Observed facts、inference、decision、remaining unknowns

### Observed facts

1. Matched SIL-IS 在大規模直接比較中 precision 明顯優於 nonmatching pairs。
2. RT/structure similarity 可降低錯配風險，但不是穩定保證。
3. Single class surrogate 在至少一個大型 GC-MS plasma head-to-head study 失敗。
4. DNA adductomics 文獻確實用單一 dG IS 做 broad relative normalization，但只主張 relative quantitation，且沒有逐 adduct accuracy/recovery validation。
5. Metchalizer 與 IROA 顯示近期進展，但分別依賴 multivariate assumptions 或大量 chemically matched labelled library。

### Inference

1. 目前 repo 的 universal RT-weighted ISTD correction 對 broad unknown adductomics 缺乏充分證據。
2. 只要 Step 1 明確區分 monitoring、matched correction、validated surrogate 與 abstention，skip 是完整決策，不是流程缺口。
3. 少數 matched features 與大量 uncorrected features可共存於 relative feature matrix，但必須帶 feature-level provenance；若下游無法保留 provenance，主矩陣全體 skip 會更誠實。

### Decision

- 現行 broad adductomics 主流程：Step 1 預設 `SKIP`。
- 已知、重要 analytes：移交 targeted/XIC pipeline，以 matched SIL-IS + calibration/validation 處理。
- 不因近期 IROA/Metchalizer 論文重新啟用 universal ISTD correction。

### Remaining unknowns

1. **本 assay 是否有足夠多的 high-confidence adduct annotations，可建立 analyte/class-specific mapping？**
   影響：若答案是有，可能支援少量 selective correction；不影響 universal correction 的否決。
2. **既有 6 個 ISTD 是在 extraction 前、digestion 前、還是 reconstitution 前加入？**
   影響：決定它們能監測的 error sources；晚加入的 IS 不能證明前段 recovery。
3. **是否有 independent technical replicates 或 matrix-matched spike series，而非只有同一批 pooled QC？**
   影響：決定 surrogate correction 能否做 out-of-sample validation。
4. **未來是否願意引入 broad labelled library（例如 custom DNA-adduct SIL library）？**
   影響：可能改變 coverage，但屬新 assay design，不是 post hoc software fix。

## Primary sources checked

1. ICH. [M10 Bioanalytical Method Validation and Study Sample Analysis](https://www.fda.gov/media/128343/download). Final guideline, 2022.
2. Ulvik A, et al. [Quantifying Precision Loss in Targeted Metabolomics Based on Mass Spectrometry and Nonmatching Internal Standards](https://doi.org/10.1021/acs.analchem.1c00119). *Anal Chem*. 2021.
3. Drotleff B, Lämmerhofer M. [Guidelines for Selection of Internal Standard-Based Normalization Strategies in Untargeted Lipidomic Profiling by LC-HR-MS/MS](https://doi.org/10.1021/acs.analchem.9b01505). *Anal Chem*. 2019.
4. Koelmel JP, et al. [Software tool for internal standard based normalization of lipids, and effect of data-processing strategies on resulting values](https://doi.org/10.1186/s12859-019-2803-8). *BMC Bioinformatics*. 2019.
5. Carrà A, et al. [Targeted High Resolution LC/MS³ Adductomics Method for the Characterization of Endogenous DNA Damage](https://doi.org/10.3389/fchem.2019.00658). *Front Chem*. 2019.
6. Bongaerts M, et al. [Using Out-of-Batch Reference Populations to Improve Untargeted Metabolomics for Screening Inborn Errors of Metabolism](https://doi.org/10.3390/metabo11010008). *Metabolites*. 2021.
7. Zhang Y, et al. [Denoising Autoencoder Normalization for Large-Scale Untargeted Metabolomics by GC-MS](https://doi.org/10.3390/metabo13080944). *Metabolites*. 2023.
8. Mahmud I, et al. [Ion suppression correction and normalization for non-targeted metabolomics](https://doi.org/10.1038/s41467-025-56646-8). *Nat Commun*. 2025.
9. Boysen AK, et al. [Best-Matched Internal Standard Normalization in LC-MS Metabolomics Applied to Environmental Samples](https://doi.org/10.1021/acs.analchem.7b04400). *Anal Chem*. 2018.（早於主要檢索窗，但為後續 B-MIS 使用的直接方法來源。）
10. Broadhurst D, et al. [Guidelines and considerations for the use of system suitability and quality control samples in mass spectrometry assays applied in untargeted clinical metabolomic studies](https://doi.org/10.1007/s11306-018-1367-3). *Metabolomics*. 2018.
11. Kuligowski J, et al. [QC-SVRC: signal correction using quality control samples and support vector regression](https://doi.org/10.1016/j.aca.2018.04.055). *Anal Chim Acta*. 2018.
12. Ramos et al. [Study of QC sample preparation effects on metabolomics biomarker selection](https://doi.org/10.1007/s00216-024-05646-6). *Anal Bioanal Chem*. 2025.
13. [reComBat: regularised Combat for improved batch effect correction in high-dimensional omics datasets](https://doi.org/10.1093/bioadv/vbac071). *Bioinformatics Advances*. 2022.
14. Nygaard V, et al. [Methods that remove batch effects while retaining group differences may lead to exaggerated confidence in downstream analyses](https://doi.org/10.1093/biostatistics/kxv027). *Biostatistics*. 2016.
15. Yu et al. [Quartet multi-omics reference materials and inter-laboratory performance assessment](https://doi.org/10.1186/s13059-023-03047-z). *Genome Biology*. 2023.
16. [Reference-based systematic benchmarking of batch-effect correction](https://doi.org/10.1038/s43588-023-00500-8). *Nature Computational Science*. 2023.
17. [Cross-batch/platform harmonization using shared biological measurements](https://doi.org/10.1038/s41467-021-25210-5). *Nature Communications*. 2021.
