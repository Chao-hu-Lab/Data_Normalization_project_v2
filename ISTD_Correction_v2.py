import pandas as pd
import numpy as np
import os
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.patches import Ellipse
import scipy.stats as stats
from scipy.stats import chi2, f as f_dist  # 🔧 改用 F 分布
import warnings
import tkinter as tk
from tkinter import filedialog
import copy

warnings.filterwarnings('ignore')

def get_valid_values(row, columns):
    """Helper: 從 row 中提取有效浮點值"""
    values = []
    for col in columns:
        if col in row:
            try:
                val = float(row[col])
                if not pd.isna(val) and val > 0:
                    values.append(val)
            except ValueError:
                pass
    return values

def load_and_process_data(file_path):
    try:
        if not (file_path.endswith('.xlsx') or file_path.endswith('.xls')):
            print(f"錯誤：輸入檔案必須是Excel格式 (.xlsx 或 .xls)，但提供了 {file_path}")
            return None, None, None
        
        excel_file = pd.ExcelFile(file_path)
        
        # 讀取所有工作表，儲存為字典 {sheet_name: df}
        all_sheets = {sheet: pd.read_excel(excel_file, sheet_name=sheet) for sheet in excel_file.sheet_names}
        print(f"讀取輸入檔案的所有工作表: {list(all_sheets.keys())}")
        
        required_sheets = ['RawIntensity', 'SampleInfo']
        missing_sheets = [sheet for sheet in required_sheets if sheet not in all_sheets]
        if missing_sheets:
            print(f"錯誤：輸入檔案缺少必要的工作表: {', '.join(missing_sheets)}")
            return None, None, None
        
        sample_info_df = all_sheets['SampleInfo']
        print(f"成功讀取 'SampleInfo' 工作表，包含 {len(sample_info_df)} 筆樣本資訊")
        
        workbook = load_workbook(file_path)
        worksheet = workbook['RawIntensity']
        istd_feature_ids = []  # 收集紅色 FeatureID 的值
        red_colors = ['FFFF0000', 'FF0000']  # 只檢查紅色變體，全大寫
        for row in worksheet.iter_rows(min_row=2):  # 從第 2 行開始
            cell = row[0]  # 第一欄 (FeatureID)
            if cell.font and cell.font.color and cell.font.color.rgb is not None:
                rgb_str = str(cell.font.color.rgb).upper()  # 強制轉 str 並 upper
                if rgb_str in red_colors:
                    if cell.value:  # 確保有值
                        istd_feature_ids.append(str(cell.value).strip())  # 轉 str 以匹配
        workbook.close()
        
        raw_df = all_sheets['RawIntensity']
        
        # 修改：不要自動跳過 'sample_type'，改為檢查並保留
        if not raw_df.empty and str(raw_df.iloc[0]['FeatureID']).strip().lower() == 'sample_type':
            print("偵測到 'Sample_Type' 資訊行，已保留作為元數據。")
        
        # 防呆：強制轉換 RawIntensity 的樣本欄位為數值
        sample_columns = [col for col in raw_df.columns if col != 'FeatureID']
        for col in sample_columns:
            raw_df[col] = pd.to_numeric(raw_df[col], errors='coerce')
        raw_df = raw_df.fillna(0)  # 填充 NaN 為 0
        print(f"RawIntensity 數據類型檢查：{raw_df.dtypes}")
        
        if 'FeatureID' in raw_df.columns:
            def parse_feature_id(fid):
                if isinstance(fid, str) and '/' in fid:
                    parts = fid.split('/')
                    if len(parts) >= 2:
                        return parts[0], parts[1]
                return np.nan, np.nan
            
            parsed = raw_df['FeatureID'].apply(parse_feature_id)
            raw_df['mz'] = pd.to_numeric([p[0] for p in parsed], errors='coerce')
            raw_df['rt'] = pd.to_numeric([p[1] for p in parsed], errors='coerce')
            
            invalid_count = raw_df['mz'].isna().sum()
            if invalid_count > 0:
                print(f"警告：{invalid_count} 筆 'FeatureID' 無法解析為 m/z 和 RT（已設為 NaN）。")
        
        # 基於 FeatureID 值設定 is_ISTD（避免索引偏移）
        raw_df['is_ISTD'] = raw_df['FeatureID'].astype(str).str.strip().isin(istd_feature_ids)
        
        print(f"識別到 {len(istd_feature_ids)} 個ISTD: {istd_feature_ids}")
        return raw_df, sample_info_df, all_sheets
    except Exception as e:
        print(f"載入數據時發生錯誤: {e}")
        return None, None, None

def identify_istd_signals(df):
    return df[df['is_ISTD']], df[~df['is_ISTD']]

def calculate_istd_cv(istd_signals, sample_columns):
    istd_cv = {}
    for _, row in istd_signals.iterrows():
        values = get_valid_values(row, sample_columns)
        if len(values) >= 2:
            mean_val = np.mean(values)
            std_val = np.std(values, ddof=1)
            cv_percent = (std_val / mean_val) * 100 if mean_val != 0 else np.nan
        else:
            cv_percent = np.nan
        istd_cv[row['FeatureID']] = cv_percent
    return istd_cv

def find_best_istd_for_analyte(analyte_row, istd_signals, istd_cv, 
                                sample_columns,  # ✅ 新增參數
                                rt_weight=0.6, cv_weight=0.25, 
                                intensity_weight=0.1, mz_weight=0.05):
    """
    多因素加權評分的 ISTD 選擇函數
    
    評分公式（越低越好）：
    score = 0.6 × RT差異(標準化) + 0.25 × CV%(標準化) + 
            0.1 × 強度倒數(標準化) + 0.05 × m/z差異(標準化)
    
    Parameters:
    -----------
    analyte_row : pd.Series
        待校正的代謝物資料
    istd_signals : pd.DataFrame
        所有 ISTD 訊號
    istd_cv : dict
        ISTD 的 CV% 字典
    sample_columns : list
        樣本欄位名稱列表
    rt_weight : float
        RT 差異權重（預設 0.6）
    cv_weight : float
        CV% 權重（預設 0.25）
    intensity_weight : float
        強度權重（預設 0.1）
    mz_weight : float
        m/z 差異權重（預設 0.05）
    
    Returns:
    --------
    best_istd : pd.Series or None
        最佳 ISTD
    rt_diff : float
        RT 差異
    """
    # ✅ 權重總和檢查
    total_weight = rt_weight + cv_weight + intensity_weight + mz_weight
    if not np.isclose(total_weight, 1.0, atol=1e-6):
        raise ValueError(
            f"❌ 錯誤：權重總和 = {total_weight:.6f}，必須等於 1.0\n"
            f"   rt_weight={rt_weight}, cv_weight={cv_weight}, "
            f"intensity_weight={intensity_weight}, mz_weight={mz_weight}"
        )
    
    analyte_rt = analyte_row.get('rt', np.nan)
    analyte_mz = analyte_row.get('mz', np.nan)
    
    # 檢查 analyte 資訊完整性
    if np.isnan(analyte_rt) or np.isnan(analyte_mz):
        return None, float('inf')
    
    # ========== 步驟 1: 收集所有 ISTD 的指標 ==========
    candidates = []
    
    for _, istd_row in istd_signals.iterrows():
        istd_id = istd_row['FeatureID']
        istd_rt = istd_row.get('rt', np.nan)
        istd_mz = istd_row.get('mz', np.nan)
        
        # 跳過缺少資訊的 ISTD
        if np.isnan(istd_rt) or np.isnan(istd_mz):
            continue
        
        # 計算 RT 差異
        rt_diff = abs(analyte_rt - istd_rt)
        
        # 獲取 CV%
        cv = istd_cv.get(istd_id, np.nan)
        if np.isnan(cv):
            cv = 100.0  # 如果沒有 CV%，設為高值
        
        # 計算 m/z 差異（ppm）
        mz_diff_ppm = abs(analyte_mz - istd_mz) / analyte_mz * 1e6
        
        # 🔧 修正：使用明確的樣本欄位計算強度
        values = []
        for col in sample_columns:
            if col in istd_row.index:
                try:
                    val = float(istd_row[col])
                    if not pd.isna(val) and val > 0:
                        values.append(val)
                except (ValueError, TypeError):
                    pass
        
        median_intensity = np.median(values) if values else 0.0
        
        # 儲存候選資訊
        candidates.append({
            'istd_row': istd_row,
            'istd_id': istd_id,
            'rt_diff': rt_diff,
            'cv': cv,
            'intensity': median_intensity,
            'mz_diff_ppm': mz_diff_ppm
        })
    
    # ========== 步驟 2: 如果沒有候選，返回 None ==========
    if len(candidates) == 0:
        return None, float('inf')
    
    # ========== 步驟 3: 標準化各指標（Min-Max Normalization）==========
    # 提取所有候選的指標
    rt_diffs = np.array([c['rt_diff'] for c in candidates])
    cvs = np.array([c['cv'] for c in candidates])
    intensities = np.array([c['intensity'] for c in candidates])
    mz_diffs = np.array([c['mz_diff_ppm'] for c in candidates])
    
    # 🔧 修正：標準化函數（處理所有值相同的情況）
    def normalize(values):
        """
        Min-Max 標準化到 [0, 1] 範圍
        如果所有值相同，返回 0（表示無差異）
        """
        min_val = np.min(values)
        max_val = np.max(values)
        if np.isclose(max_val, min_val, atol=1e-10):
            # 如果所有值相同，表示無差異，返回 0（不影響評分）
            return np.zeros(len(values))
        return (values - min_val) / (max_val - min_val)
    
    # 標準化各指標
    normalized_rt = normalize(rt_diffs)
    normalized_cv = normalize(cvs)
    
    # 🔧 修正：強度標準化（強度越高 → 分數越低）
    normalized_intensity = normalize(intensities)
    normalized_intensity_inv = 1.0 - normalized_intensity  # 反轉（強度高得分低）
    
    normalized_mz = normalize(mz_diffs)
    
    # ========== 步驟 4: 計算加權評分 ==========
    for i, candidate in enumerate(candidates):
        # 加權評分（越低越好）
        score = (
            rt_weight * normalized_rt[i] +
            cv_weight * normalized_cv[i] +
            intensity_weight * normalized_intensity_inv[i] +
            mz_weight * normalized_mz[i]
        )
        candidate['score'] = score
        
        # 🔧 新增：記錄各項評分（用於調試）
        candidate['score_breakdown'] = {
            'rt_score': rt_weight * normalized_rt[i],
            'cv_score': cv_weight * normalized_cv[i],
            'intensity_score': intensity_weight * normalized_intensity_inv[i],
            'mz_score': mz_weight * normalized_mz[i]
        }
    
    # ========== 步驟 5: 選擇評分最低的 ISTD ==========
    best_candidate = min(candidates, key=lambda x: x['score'])
    
    return best_candidate['istd_row'], best_candidate['rt_diff']

def calculate_istd_medians(istd_signals, sample_columns):
    istd_medians = {}
    for _, row in istd_signals.iterrows():
        values = get_valid_values(row, sample_columns)
        istd_medians[row['FeatureID']] = np.median(values) if values else np.nan
    return istd_medians

def calculate_corrected_ratios(df, sample_info_df):
    istd_signals, analyte_signals = identify_istd_signals(df)
    if len(istd_signals) == 0: 
        return None, None
    
    if 'Sample_Name' not in sample_info_df.columns:
        print("錯誤：'SampleInfo' 缺少 'Sample_Name' 欄位")
        return None, None
    
    sample_names = sample_info_df['Sample_Name'].tolist()
    
    all_columns = df.columns.tolist()
    sample_columns = all_columns[2:] if len(all_columns) >= 2 and all_columns[1].lower() == 'sample_type' else all_columns[1:]
    
    # 修改：標準化名稱（轉小寫、去除空格）以避免不匹配
    normalized_sample_names = [name.strip().lower() for name in sample_names]
    normalized_columns = {col: col.strip().lower() for col in sample_columns}
    
    sample_columns = []
    name_mapping = {}  # 記錄映射
    for col, norm_col in normalized_columns.items():
        if norm_col in normalized_sample_names:
            sample_columns.append(col)  # 保留原始欄位名
            name_mapping[col] = sample_names[normalized_sample_names.index(norm_col)]
    
    missing_columns = [name for name in sample_names if name.strip().lower() not in normalized_columns.values()]
    if missing_columns:
        print(f"警告：以下樣本名稱在 'RawIntensity' 中缺少 (即使大小寫不同): {', '.join(missing_columns)}")
    
    istd_cv = calculate_istd_cv(istd_signals, sample_columns)
    istd_medians = calculate_istd_medians(istd_signals, sample_columns)
    
    # ✅ 新增：印出權重設定資訊
    print(f"\n{'='*70}")
    print(f"🎯 ISTD 選擇權重設定:")
    print(f"{'='*70}")
    print(f"  - RT 差異權重:    60%")
    print(f"  - CV% 權重:       25%")
    print(f"  - 強度權重:       10%")
    print(f"  - m/z 差異權重:    5%")
    print(f"  - 總和:          100%")
    print(f"{'='*70}\n")
    
    results = []
    for _, analyte_row in analyte_signals.iterrows():
        # ✅ 傳入 sample_columns
        best_istd, min_rt_diff = find_best_istd_for_analyte(
            analyte_row, istd_signals, istd_cv, 
            sample_columns  # ✅ 新增參數
        )
        
        if best_istd is None: 
            continue
        
        istd_id = best_istd['FeatureID']
        istd_median = istd_medians[istd_id]
        rt_diff = analyte_row['rt'] - best_istd['rt']
        
        result_row = {
            'FeatureID': analyte_row['FeatureID'], 
            'RT': analyte_row['rt'], 
            'ISTD': istd_id, 
            'ISTD_RT': best_istd['rt'], 
            'RT_Difference': rt_diff, 
            'ISTD_Median': istd_median
        }
        
        for col in sample_columns:
            if col not in df.columns: 
                continue
            try:
                analyte_intensity = float(analyte_row[col])
                istd_intensity = float(best_istd[col])
            except (ValueError, KeyError):
                analyte_intensity = np.nan
                istd_intensity = np.nan
            
            corrected = (
                (analyte_intensity / istd_intensity) * istd_median 
                if istd_intensity > 0 and not np.isnan(istd_median) and not np.isnan(analyte_intensity) 
                else np.nan
            )
            result_row[col] = corrected
        
        results.append(result_row)
    
    results_df = pd.DataFrame(results)
    
    # 防呆：強制轉換 results_df 的樣本欄位為數值
    for col in sample_columns:
        if col in results_df.columns:
            results_df[col] = pd.to_numeric(results_df[col], errors='coerce')
    results_df = results_df.fillna(0)
    print(f"ISTD Correction 數據類型檢查：{results_df.dtypes}")
    
    return results_df, sample_columns



from scipy.stats import wilcoxon, levene

def calculate_qc_cv_with_statistical_test(results_df, sample_columns, sample_info_df, original_df):
    """
    計算 QC 樣本的 CV%，並進行正確的統計檢定
    
    統計方法：
    1. Wilcoxon 配對符號等級檢定（檢驗中位數偏移，適用於非常態分佈）
    2. Levene's test（檢驗方差齊性）
    """
    qc_samples = sample_info_df[sample_info_df['Sample_Type'].str.upper().str.contains('QC')]['Sample_Name'].tolist()
    qc_columns = [col for col in sample_columns if col in qc_samples]
    
    print(f"\n{'='*70}")
    print(f"🔬 開始統計檢定（Wilcoxon 配對符號等級檢定 + Levene's test）")
    print(f"{'='*70}")
    print(f"  - QC 樣本數: {len(qc_columns)}")
    print(f"  - Feature 總數: {len(results_df)}")
    
    cv_results = []
    
    for idx, row in results_df.iterrows():
        feature_id = row['FeatureID']
        
        # 校正後的 QC 值
        qc_values_corrected = get_valid_values(row, qc_columns)
        
        # 原始的 QC 值
        original_row = original_df[original_df['FeatureID'] == feature_id]
        if not original_row.empty:
            qc_values_original = get_valid_values(original_row.iloc[0], qc_columns)
        else:
            qc_values_original = []
        
        # 確保配對樣本數一致
        min_len = min(len(qc_values_original), len(qc_values_corrected))
        
        if min_len < 3:
            cv_results.append({
                'FeatureID': feature_id,
                'Original_QC_CV%': np.nan,
                'Corrected_QC_CV%': np.nan,
                'CV_Improvement%': np.nan,
                'Wilcoxon_pvalue': np.nan,
                'Variance_Test_pvalue': np.nan,
                'Significant_Improvement': 'N/A'
            })
            continue
        
        qc_values_original = np.array(qc_values_original[:min_len])
        qc_values_corrected = np.array(qc_values_corrected[:min_len])
        
        # 計算 CV%
        original_cv = (np.std(qc_values_original, ddof=1) / np.mean(qc_values_original)) * 100
        corrected_cv = (np.std(qc_values_corrected, ddof=1) / np.mean(qc_values_corrected)) * 100
        cv_improvement = original_cv - corrected_cv
        
        # ✅ 1. Wilcoxon 配對符號等級檢定（檢驗中位數是否改變）
        try:
            # 計算差異
            differences = qc_values_original - qc_values_corrected
            
            # 只有當存在非零差異時才進行檢定
            if np.any(differences != 0):
                wilcoxon_stat, wilcoxon_pvalue = wilcoxon(
                    qc_values_original, 
                    qc_values_corrected,
                    alternative='two-sided',
                    zero_method='wilcox'  # 處理零差異的方法
                )
            else:
                # 所有值都相同，p-value = 1.0
                wilcoxon_pvalue = 1.0
        except Exception as e:
            wilcoxon_pvalue = np.nan
        
        # ✅ 2. Levene's test（檢驗方差齊性）
        try:
            levene_stat, variance_test_pvalue = levene(qc_values_original, qc_values_corrected)
        except Exception:
            variance_test_pvalue = np.nan
        
        # ✅ 判斷顯著性
        if not np.isnan(variance_test_pvalue) and cv_improvement > 5:
            if variance_test_pvalue < 0.05:
                significant = 'Yes'
            else:
                significant = 'Marginal'
        elif cv_improvement > 10:
            significant = 'Yes (CV% only)'
        else:
            significant = 'No'
        
        cv_results.append({
            'FeatureID': feature_id,
            'Original_QC_CV%': original_cv,
            'Corrected_QC_CV%': corrected_cv,
            'CV_Improvement%': cv_improvement,
            'Wilcoxon_pvalue': wilcoxon_pvalue,
            'Variance_Test_pvalue': variance_test_pvalue,
            'Significant_Improvement': significant
        })
        
        if (idx + 1) % 100 == 0:
            print(f"  處理進度: {idx + 1}/{len(results_df)} features")
    
    print(f"  ✓ 統計檢定完成！")
    
    cv_results_df = pd.DataFrame(cv_results)
    
    # 統計摘要
    sig_yes = (cv_results_df['Significant_Improvement'] == 'Yes').sum()
    sig_marginal = (cv_results_df['Significant_Improvement'] == 'Marginal').sum()
    sig_cv_only = (cv_results_df['Significant_Improvement'] == 'Yes (CV% only)').sum()
    sig_no = (cv_results_df['Significant_Improvement'] == 'No').sum()
    total_count = len(cv_results_df)
    
    print(f"\n📊 統計檢定摘要:")
    print(f"  - 總特徵數: {total_count}")
    print(f"  - 顯著改善 (Yes): {sig_yes} ({sig_yes/total_count*100:.1f}%)")
    print(f"  - 邊緣顯著 (Marginal): {sig_marginal} ({sig_marginal/total_count*100:.1f}%)")
    print(f"  - 僅 CV% 改善: {sig_cv_only} ({sig_cv_only/total_count*100:.1f}%)")
    print(f"  - 無顯著改善 (No): {sig_no} ({sig_no/total_count*100:.1f}%)")
    
    # Wilcoxon 檢定統計
    wilcoxon_valid = cv_results_df['Wilcoxon_pvalue'].notna().sum()
    wilcoxon_sig = ((cv_results_df['Wilcoxon_pvalue'] < 0.05) & 
                    (cv_results_df['Wilcoxon_pvalue'].notna())).sum()
    
    print(f"\n🔬 Wilcoxon 配對符號等級檢定（中位數變化）:")
    print(f"  - 成功執行: {wilcoxon_valid}/{total_count} ({wilcoxon_valid/total_count*100:.1f}%)")
    if wilcoxon_valid > 0:
        print(f"  - 中位數顯著改變 (p < 0.05): {wilcoxon_sig}/{wilcoxon_valid} ({wilcoxon_sig/wilcoxon_valid*100:.1f}%)")
        print(f"  - 中位數無顯著改變: {wilcoxon_valid - wilcoxon_sig}/{wilcoxon_valid} ({(wilcoxon_valid-wilcoxon_sig)/wilcoxon_valid*100:.1f}%)")
    
    # Levene's test 統計
    variance_valid = cv_results_df['Variance_Test_pvalue'].notna().sum()
    variance_sig = ((cv_results_df['Variance_Test_pvalue'] < 0.05) & 
                    (cv_results_df['Variance_Test_pvalue'].notna())).sum()
    
    print(f"\n🔬 Levene's Test（方差齊性）:")
    print(f"  - 成功執行: {variance_valid}/{total_count} ({variance_valid/total_count*100:.1f}%)")
    if variance_valid > 0:
        print(f"  - 方差顯著改變 (p < 0.05): {variance_sig}/{variance_valid} ({variance_sig/variance_valid*100:.1f}%)")
        print(f"  - 方差無顯著改變: {variance_valid - variance_sig}/{variance_valid} ({(variance_valid-variance_sig)/variance_valid*100:.1f}%)")
    
    # CV% 改善統計
    cv_improvement_valid = cv_results_df['CV_Improvement%'].notna()
    if cv_improvement_valid.sum() > 0:
        improvements = cv_results_df.loc[cv_improvement_valid, 'CV_Improvement%']
        improvements_finite = improvements[np.isfinite(improvements)]
        
        if len(improvements_finite) > 0:
            median_improvement = np.median(improvements_finite)
            mean_improvement = np.mean(improvements_finite)
            
            print(f"\n📊 CV% 改善統計:")
            print(f"  - 中位數改善: {median_improvement:.2f}%")
            print(f"  - 平均改善: {mean_improvement:.2f}%")
            print(f"  - 範圍: {improvements_finite.min():.2f}% - {improvements_finite.max():.2f}%")
            
            improved_cv = (improvements_finite > 5).sum()
            similar_cv = ((improvements_finite >= -5) & (improvements_finite <= 5)).sum()
            worse_cv = (improvements_finite < -5).sum()
            
            print(f"\n  改善程度分類:")
            print(f"  - 顯著改善 (>5%): {improved_cv} ({improved_cv/len(improvements_finite)*100:.1f}%)")
            print(f"  - 無明顯變化 (±5%): {similar_cv} ({similar_cv/len(improvements_finite)*100:.1f}%)")
            print(f"  - 變差 (<-5%): {worse_cv} ({worse_cv/len(improvements_finite)*100:.1f}%)")
    
    print(f"\n{'='*70}\n")
    
    return cv_results_df

# ========== ✅ 修正：基於 QC 群組內部的 Hotelling T² 異常值檢測 ==========
def calculate_hotelling_t2_outliers(qc_scores, all_scores=None, alpha=0.05):
    """
    使用 Hotelling T² 檢測 QC 樣本中的異常值
    
    ✅ 正確邏輯：計算每個 QC 樣本與 QC 群組中心的偏離
    
    
    """
    n_qc, p = qc_scores.shape
    
    if n_qc < 3:
        print(f"   ⚠️ QC 樣本數不足 ({n_qc} < 3)，無法進行異常值檢測")
        return np.zeros(n_qc), 0, np.zeros(n_qc, dtype=bool)
    
    # ✅ 關鍵：使用 QC 群組的統計量
    qc_mean = np.mean(qc_scores, axis=0)
    qc_cov = np.cov(qc_scores, rowvar=False)
    
    # 正則化協方差矩陣（防止奇異矩陣）
    qc_cov_reg = qc_cov + np.eye(p) * 1e-6
    
    try:
        qc_cov_inv = np.linalg.inv(qc_cov_reg)
    except np.linalg.LinAlgError:
        print("   ⚠️ 警告：QC 協方差矩陣奇異，使用偽逆矩陣")
        qc_cov_inv = np.linalg.pinv(qc_cov_reg)
    
    # ✅ 計算每個 QC 樣本與 QC 中心的 Hotelling T² 值
    t2_values = np.zeros(n_qc)
    for i in range(n_qc):
        diff = qc_scores[i] - qc_mean  # ✅ 與 QC 中心比較
        t2_values[i] = np.dot(np.dot(diff, qc_cov_inv), diff.T)
    
    # ✅ 使用 F 分佈計算閾值（考慮樣本數）
    if n_qc - p - 1 > 0:
        f_critical = stats.f.ppf(1 - alpha, p, n_qc - p - 1)
        threshold = (p * (n_qc + 1) * (n_qc - 1)) / (n_qc * (n_qc - p - 1)) * f_critical
    else:
        # 樣本數太少，使用卡方分布
        threshold = chi2.ppf(1 - alpha, p)
    
    # 識別異常值
    outliers = t2_values > threshold
    
    return t2_values, threshold, outliers

def plot_pvalue_distribution(cv_results_df, output_dir, timestamp):
    """繪製 p 值分佈圖（註解移到下方空白區域）"""
    try:
        variance_pvalues = cv_results_df['Variance_Test_pvalue'].dropna()
        
        if len(variance_pvalues) < 10:
            print("  ⚠️ 有效 p 值數量不足，跳過 p 值分佈圖")
            return
        
        # ✅ 只繪製直方圖（移除 Q-Q Plot）
        fig, ax = plt.subplots(1, 1, figsize=(10, 6))
        
        # 直方圖
        ax.hist(variance_pvalues, bins=20, color='steelblue', edgecolor='black', alpha=0.7)
        ax.axhline(y=len(variance_pvalues)/20, color='red', linestyle='--', linewidth=2,
                   label='Uniform Distribution Expected')
        ax.set_xlabel('P-value (Levene\'s Test)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Frequency', fontsize=12, fontweight='bold')
        ax.set_title('P-value Distribution (Variance Homogeneity Test)', 
                     fontsize=14, fontweight='bold')
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # Kolmogorov-Smirnov 檢定
        from scipy.stats import kstest
        ks_stat, ks_pvalue = kstest(variance_pvalues, 'uniform')
        
        # 統計摘要
        p_below_005 = (variance_pvalues < 0.05).sum()
        p_below_001 = (variance_pvalues < 0.01).sum()
        total = len(variance_pvalues)
        
        textstr = f'📊 Statistical Summary:\n'
        textstr += f'Total features: {total}\n'
        textstr += f'p < 0.05: {p_below_005} ({p_below_005/total*100:.1f}%)\n'
        textstr += f'p < 0.01: {p_below_001} ({p_below_001/total*100:.1f}%)\n\n'
        textstr += f'Kolmogorov-Smirnov Test:\n'
        textstr += f'KS statistic = {ks_stat:.4f}\n'
        textstr += f'P-value = {ks_pvalue:.4f}\n\n'
        
        if ks_pvalue < 0.05:
            textstr += '✅ Result: Non-uniform\n'
            textstr += '→ ISTD correction significantly\n'
            textstr += '   reduced QC variance'
            bgcolor = 'lightgreen'
        else:
            textstr += '⚠️ Result: Uniform\n'
            textstr += '→ Limited effect of\n'
            textstr += '   ISTD correction'
            bgcolor = 'lightyellow'
        
        ax.text(0.98, 0.97, textstr, transform=ax.transAxes,
                fontsize=10, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor=bgcolor, alpha=0.8))
        
        plt.tight_layout()
        
        pvalue_plot_path = os.path.join(output_dir, f'Pvalue_Distribution_{timestamp}.png')
        plt.savefig(pvalue_plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n✓ P 值分佈圖已儲存: {pvalue_plot_path}")
        print(f"  - Kolmogorov-Smirnov 檢定: KS={ks_stat:.4f}, p={ks_pvalue:.4f}")
        if ks_pvalue < 0.05:
            print(f"  - ✅ 結論: ISTD 校正顯著改善 QC 方差穩定性")
        else:
            print(f"  - ⚠️ 結論: ISTD 校正效果有限")
        
    except Exception as e:
        print(f"  ⚠️ 繪製 p 值分佈圖時發生錯誤: {e}")
        import traceback
        traceback.print_exc()

# ========== Hotelling T² 橢圓繪製函數（固定原點）==========
def draw_hotelling_t2_ellipse(ax, scores, alpha=0.05, label=None, edgecolor='black', linestyle='-', linewidth=2.5):
    """
    在 2D PCA 圖上繪製 Hotelling T² 橢圓
    
    🔧 修正：橢圓中心使用樣本實際均值（而非強制為原點）
    
    Parameters:
    -----------
    ax : matplotlib.axes.Axes
        繪圖軸
    scores : ndarray
        PCA 分數矩陣 (n_samples, 2)
    alpha : float
        顯著水平（預設 0.05）
    label : str
        圖例標籤
    edgecolor : str
        橢圓邊框顏色
    linestyle : str
        線條樣式
    linewidth : float
        線條寬度
    
    Returns:
    --------
    bounds : tuple
        橢圓邊界 (x_min, x_max, y_min, y_max)
    """
    n, p = scores.shape
    
    if n < 3:
        print(f"   ⚠ 樣本數不足 ({n})，無法繪製 Hotelling T² 橢圓")
        return None
    
    # 🔧 關鍵修正：使用樣本實際均值（而非強制為原點）
    mean = np.mean(scores, axis=0)
    
    # 計算協方差矩陣
    cov = np.cov(scores, rowvar=False)
    
    # 計算特徵值和特徵向量，並按特徵值降序排列
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    
    # 按特徵值降序排序
    idx = eigenvalues.argsort()[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    
    # 防止負值或零值
    eigenvalues = np.maximum(eigenvalues, 1e-10)
    
    # 計算 F 臨界值
    f_critical = stats.f.ppf(1 - alpha, p, n - p)
    
    # 計算橢圓的縮放因子
    scale_factor = np.sqrt((p * (n - 1) * (n + 1)) / (n * (n - p)) * f_critical)
    
    # width 對應最大特徵值（主軸），height 對應次要軸
    width = 2 * scale_factor * np.sqrt(eigenvalues[0])
    height = 2 * scale_factor * np.sqrt(eigenvalues[1])
    
    # 旋轉角度使用第一個特徵向量
    angle = np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
    
    # 🔧 繪製橢圓（中心為實際均值）
    ellipse = Ellipse(mean, width, height, angle=angle,
                     facecolor='none', edgecolor=edgecolor,
                     linewidth=linewidth, linestyle=linestyle, label=label)
    ax.add_patch(ellipse)
    
    # 計算橢圓邊界
    t = np.linspace(0, 2*np.pi, 100)
    ellipse_x = (width/2) * np.cos(t)
    ellipse_y = (height/2) * np.sin(t)
    
    # 旋轉橢圓
    cos_angle = np.cos(np.radians(angle))
    sin_angle = np.sin(np.radians(angle))
    x_rot = ellipse_x * cos_angle - ellipse_y * sin_angle + mean[0]
    y_rot = ellipse_x * sin_angle + ellipse_y * cos_angle + mean[1]
    
    bounds = (np.min(x_rot), np.max(x_rot), np.min(y_rot), np.max(y_rot))
    
    return bounds


# ========== 修改：2D PCA 分析（Hotelling T² 異常值檢測 + 橢圓）==========
def perform_pca_analysis_2d(raw_df, corrected_df, lowess_df, sample_columns, sample_info_df):
    """
    執行 2D PCA 分析（美化版）
    - 使用 Hotelling T² 檢測異常值
    - 繪製橢圓（中心為實際均值）
    - 顏色：控制組=亮藍色、暴露組=亮紅色、QC=亮紫色
    - 標題顯示實際變化數值（而非百分比）
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "ISTD_Correction_plots")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"已建立 'ISTD_Correction_plots' 資料夾: {output_dir}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    sample_meta = sample_info_df.set_index('Sample_Name')

    # 識別 QC 樣本和樣本類型
    qc_columns = []
    control_columns = []
    exposed_columns = []
    sample_type_map = {}
    
    for col in sample_columns:
        if col in sample_meta.index:
            sample_type = sample_meta.loc[col].get('Sample_Type', 'Unknown')
            sample_type_map[col] = sample_type
            
            sample_type_upper = str(sample_type).upper()
            
            if 'QC' in sample_type_upper:
                qc_columns.append(col)
            elif 'CONTROL' in sample_type_upper or 'CTL' in sample_type_upper or 'CON' in sample_type_upper:
                control_columns.append(col)
            elif 'EXPOSED' in sample_type_upper or 'EXP' in sample_type_upper or 'TREAT' in sample_type_upper:
                exposed_columns.append(col)
            else:
                col_upper = col.upper()
                if 'QC' in col_upper:
                    qc_columns.append(col)
                elif any(x in col_upper for x in ['CONTROL', 'CTL', 'CON']):
                    control_columns.append(col)
                elif any(x in col_upper for x in ['EXPOSED', 'EXP', 'TREAT']):
                    exposed_columns.append(col)
                else:
                    control_columns.append(col)
        else:
            sample_type_map[col] = 'Unknown'
            control_columns.append(col)

    if len(qc_columns) < 3:
        print("警告：QC 樣本不足 (<3)，跳過 PCA 分析")
        return

    print(f"識別到樣本分組:")
    print(f"  - QC: {len(qc_columns)} 個")
    print(f"  - 控制組: {len(control_columns)} 個")
    print(f"  - 暴露組: {len(exposed_columns)} 個")
    print(f"  - 總計: {len(sample_columns)} 個")

    # 更鮮明的顏色映射
    color_map = {}
    marker_map = {}
    
    for col in sample_columns:
        if col in qc_columns:
            color_map[col] = '#9C27B0'  # 亮紫色
        elif col in exposed_columns:
            color_map[col] = '#E53935'  # 亮紅色
        else:
            color_map[col] = '#1E88E5'  # 亮藍色

    def prepare_matrix(df, cols, feature_col='FeatureID'):
        try:
            matrix = df.set_index(feature_col)[cols].T
            matrix = matrix.apply(pd.to_numeric, errors='coerce').fillna(0)
            if matrix.shape[1] < 2:
                raise ValueError("特徵數不足 2，無法進行 PCA")
            matrix = np.log2(matrix + 1)
            scaler = StandardScaler()
            matrix = scaler.fit_transform(matrix)
            return matrix
        except Exception as e:
            print(f"警告：準備 PCA 矩陣失敗 ({e})")
            return None

    datasets = {
        'Raw Data': raw_df,
        'ISTD Corrected': corrected_df,
        'LOWESS Normalized': lowess_df
    }

    comparisons = [('Raw Data', 'ISTD Corrected')]
    if lowess_df is not None:
        comparisons.append(('ISTD Corrected', 'LOWESS Normalized'))

    for left_name, right_name in comparisons:
        left_df = datasets.get(left_name)
        right_df = datasets.get(right_name)
        
        if left_df is None or right_df is None:
            continue

        # 準備所有樣本的矩陣
        left_matrix = prepare_matrix(left_df, sample_columns)
        right_matrix = prepare_matrix(right_df, sample_columns)

        if left_matrix is None or right_matrix is None:
            continue

        # 執行 PCA（2 個主成分）
        pca_left = PCA(n_components=2)
        scores_left = pca_left.fit_transform(left_matrix)
        var_left = pca_left.explained_variance_ratio_

        pca_right = PCA(n_components=2)
        scores_right = pca_right.fit_transform(right_matrix)
        var_right = pca_right.explained_variance_ratio_

        # 使用 Hotelling T² 檢測 QC 異常值
        qc_indices = [i for i, col in enumerate(sample_columns) if col in qc_columns]
        qc_scores_left = scores_left[qc_indices]
        qc_scores_right = scores_right[qc_indices]

        t2_left, t2_threshold_left, outliers_left = calculate_hotelling_t2_outliers(
            qc_scores_left, scores_left, alpha=0.05
        )
        t2_right, t2_threshold_right, outliers_right = calculate_hotelling_t2_outliers(
            qc_scores_right, scores_right, alpha=0.05
        )

        # ✅ 計算實際變化（絕對值，單位：百分點）
        pc1_change = (var_left[0] - var_right[0]) * 100  # 轉為百分點
        pc2_change = (var_right[1] - var_left[1]) * 100  # 轉為百分點
        outlier_reduction = np.sum(outliers_left) - np.sum(outliers_right)

        print(f"\n🔍 Hotelling T² 異常值檢測:")
        print(f"   {left_name}:")
        print(f"   - T² 閾值: {t2_threshold_left:.2f}")
        print(f"   - 異常值數量: {np.sum(outliers_left)}/{len(qc_columns)}")
        print(f"   {right_name}:")
        print(f"   - T² 閾值: {t2_threshold_right:.2f}")
        print(f"   - 異常值數量: {np.sum(outliers_right)}/{len(qc_columns)}")
        print(f"   - 異常值減少: {outlier_reduction} 個")

        # 繪製 2D PCA 圖
        fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(16, 10))
        fig.suptitle(f'2D PCA Comparison: {left_name} vs {right_name}',
                     fontsize=18, y=0.98, fontweight='bold')

        # ===== 繪圖函數 =====
        def plot_pca_subplot(ax, scores, qc_scores, var, t2_threshold, outliers, 
                            title, is_right=False, pc1_change=0, pc2_change=0, outlier_info=""):
            # 繪製樣本點
            for i, col in enumerate(sample_columns):
                color = color_map[col]
                
                is_outlier = False
                if col in qc_columns:
                    qc_idx = qc_columns.index(col)
                    is_outlier = outliers[qc_idx]
                
                if is_outlier:
                    edgecolor = '#D32F2F'
                    linewidth = 4
                    size = 180
                    alpha = 0.95
                else:
                    edgecolor = 'black'
                    linewidth = 1.5
                    size = 120
                    alpha = 0.75
                
                ax.scatter(scores[i, 0], scores[i, 1],
                          c=[color], marker='o', s=size, alpha=alpha,
                          edgecolors=edgecolor, linewidths=linewidth)

            # 繪製橢圓
            all_bounds = []
            
            bounds_all = draw_hotelling_t2_ellipse(ax, scores,
                                                    label='95% CI (All Samples)',
                                                    edgecolor='gray', linestyle='--', linewidth=2)
            if bounds_all:
                all_bounds.append(bounds_all)

            bounds_qc = draw_hotelling_t2_ellipse(ax, qc_scores,
                                                   label='95% CI (QC Only)',
                                                   edgecolor='#9C27B0', linestyle='-', linewidth=3)
            if bounds_qc:
                all_bounds.append(bounds_qc)
            
            # 調整軸範圍
            if all_bounds:
                x_min = min([b[0] for b in all_bounds])
                x_max = max([b[1] for b in all_bounds])
                y_min = min([b[2] for b in all_bounds])
                y_max = max([b[3] for b in all_bounds])
            else:
                x_min, x_max = np.min(scores[:, 0]), np.max(scores[:, 0])
                y_min, y_max = np.min(scores[:, 1]), np.max(scores[:, 1])
            
            data_x_min, data_x_max = np.min(scores[:, 0]), np.max(scores[:, 0])
            data_y_min, data_y_max = np.min(scores[:, 1]), np.max(scores[:, 1])
            
            x_min = min(x_min, data_x_min)
            x_max = max(x_max, data_x_max)
            y_min = min(y_min, data_y_min)
            y_max = max(y_max, data_y_max)
            
            x_abs_max = max(abs(x_min), abs(x_max))
            y_abs_max = max(abs(y_min), abs(y_max))
            
            x_margin = x_abs_max * 0.2
            y_margin = y_abs_max * 0.2
            
            ax.set_xlim(-x_abs_max - x_margin, x_abs_max + x_margin)
            ax.set_ylim(-y_abs_max - y_margin, y_abs_max + y_margin)
            
            # ✅ 修改標題：顯示實際變化數值（百分點）
            if is_right and pc1_change != 0:
                title_text = (f'{title}\n'
                             f'PC1: {var[0]:.1%} (↓{pc1_change:.1f}%), '
                             f'PC2: {var[1]:.1%} (↑{pc2_change:.1f}%)\n'
                             f'{outlier_info}\n'
                             f'Hotelling T² Threshold: {t2_threshold:.2f}')
            else:
                title_text = (f'{title}\n'
                             f'PC1: {var[0]:.1%}, PC2: {var[1]:.1%}\n'
                             f'Hotelling T² Threshold: {t2_threshold:.2f}')
            
            ax.set_title(title_text, fontsize=12, fontweight='bold', pad=10)
            ax.set_xlabel(f't[1] ({var[0]:.1%})', fontsize=12, fontweight='bold')
            ax.set_ylabel(f't[2] ({var[1]:.1%})', fontsize=12, fontweight='bold')
            
            ax.grid(True, alpha=0.2, linestyle=':', linewidth=0.5)
            ax.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
            ax.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
            
            # 添加子圖編號
            label = '(A)' if not is_right else '(B)'
            ax.text(0.02, 0.98, label, transform=ax.transAxes,
                   fontsize=16, fontweight='bold', va='top',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        plot_pca_subplot(ax_left, scores_left, qc_scores_left, var_left, t2_threshold_left, 
                        outliers_left, left_name)
        
        plot_pca_subplot(ax_right, scores_right, qc_scores_right, var_right, t2_threshold_right, 
                        outliers_right, right_name, is_right=True, 
                        pc1_change=pc1_change, pc2_change=pc2_change,
                        outlier_info=f'QC Outliers: {np.sum(outliers_left)} → {np.sum(outliers_right)}')

        # ===== 添加圖例 =====
        sample_legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#1E88E5',
                      markersize=11, label='Control', markeredgecolor='black', markeredgewidth=1.5),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#E53935',
                      markersize=11, label='Exposed', markeredgecolor='black', markeredgewidth=1.5),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#9C27B0',
                      markersize=11, label='QC', markeredgecolor='black', markeredgewidth=1.5),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='gray',
                      markersize=11, label='QC Outlier (T² > threshold)', 
                      markeredgecolor='#D32F2F', markeredgewidth=4)
        ]
        
        ellipse_legend_elements = [
            plt.Line2D([0], [0], linestyle='--', color='gray',
                      linewidth=2.5, label='95% CI (All Samples)'),
            plt.Line2D([0], [0], linestyle='-', color='#9C27B0',
                      linewidth=3.5, label='95% CI (QC Only)')
        ]
        
        legend1 = fig.legend(handles=sample_legend_elements, 
                            loc='center left', 
                            bbox_to_anchor=(1.01, 0.7),
                            fontsize=11,
                            title='Sample Type', 
                            title_fontsize=13,
                            frameon=True, 
                            fancybox=True, 
                            shadow=True,
                            edgecolor='black')
        
        legend2 = fig.legend(handles=ellipse_legend_elements, 
                            loc='center left', 
                            bbox_to_anchor=(1.01, 0.3),
                            fontsize=11,
                            title='Confidence Ellipse', 
                            title_fontsize=13,
                            frameon=True, 
                            fancybox=True, 
                            shadow=True,
                            edgecolor='black')

        plt.tight_layout(rect=[0, 0.2, 1, 0.96])

        output_path = os.path.join(output_dir, f"2D_PCA_{left_name.replace(' ', '_')}_vs_{right_name.replace(' ', '_')}_{timestamp}.png")
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"✓ 2D PCA 圖已儲存: {output_path}")

        # ===== 輸出異常值摘要 =====
        print(f"\n{'='*70}")
        print(f"📊 {left_name} - Hotelling T² 異常值檢測結果")
        print(f"{'='*70}")
        print(f"QC 異常值數量: {np.sum(outliers_left)}/{len(outliers_left)} ({np.sum(outliers_left)/len(outliers_left)*100:.1f}%)")
        if np.sum(outliers_left) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_left)) if outliers_left[i]]
            outlier_t2_values = [t2_left[i] for i in range(len(outliers_left)) if outliers_left[i]]
            print(f"異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"  - {sample}: T² = {t2_val:.2f} (閾值 = {t2_threshold_left:.2f})")
        else:
            print("  ✓ 無異常樣本")
        
        print(f"\n📊 {right_name} - Hotelling T² 異常值檢測結果")
        print(f"{'='*70}")
        print(f"QC 異常值數量: {np.sum(outliers_right)}/{len(outliers_right)} ({np.sum(outliers_right)/len(outliers_right)*100:.1f}%)")
        if np.sum(outliers_right) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_right)) if outliers_right[i]]
            outlier_t2_values = [t2_right[i] for i in range(len(outliers_right)) if outliers_right[i]]
            print(f"異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"  - {sample}: T² = {t2_val:.2f} (閾值 = {t2_threshold_right:.2f})")
        else:
            print("  ✓ 無異常樣本")
        
        print(f"\n📈 校正效果摘要:")
        print(f"  - PC1 變異量: {var_left[0]:.1%} → {var_right[0]:.1%} (↓{pc1_change:.1f} 百分點)")
        print(f"  - PC2 變異量: {var_left[1]:.1%} → {var_right[1]:.1%} (↑{pc2_change:.1f} 百分點)")
        print(f"  - QC 異常值: {np.sum(outliers_left)} → {np.sum(outliers_right)} (↓{outlier_reduction} 個)")
        print(f"{'='*70}\n")

# ========== 🔧 修改：save_results_to_excel==========
def save_results_to_excel(original_df, results_df, sample_info_df, output_file, all_sheets, sample_columns, original_workbook):
    """
    儲存結果到 Excel，使用 Wilcoxon 配對符號等級檢定 + Levene's test
    """
    # 設定輸出目錄
    output_dir = os.path.join(os.path.dirname(output_file), "ISTD_Correction_plots")
    os.makedirs(output_dir, exist_ok=True)
    
    # ✅ 使用新的統計檢定函數
    cv_results_df = calculate_qc_cv_with_statistical_test(
        results_df, sample_columns, sample_info_df, original_df
    )
    
    # 合併結果
    results_with_cv = results_df.merge(cv_results_df, on='FeatureID', how='left')
    
    # ✅ 調整欄位順序
    cols_order = [
        'Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%',
        'Wilcoxon_pvalue', 'Variance_Test_pvalue',  # 移除 Normality_pvalue
        'Significant_Improvement'
    ]
    other_cols = [col for col in results_with_cv.columns if col not in cols_order]
    results_with_cv = results_with_cv[other_cols + cols_order]
    
    # 寫入 Excel
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        for sheet_name, df in all_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        results_with_cv.to_excel(writer, sheet_name='ISTD_Correction', index=False)
    
    # 格式設定
    workbook = load_workbook(original_workbook)
    new_workbook = load_workbook(output_file)
    
    # 複製 RawIntensity 格式
    if 'RawIntensity' in workbook.sheetnames and 'RawIntensity' in new_workbook.sheetnames:
        original_sheet = workbook['RawIntensity']
        new_sheet = new_workbook['RawIntensity']
        
        for row in range(1, original_sheet.max_row + 1):
            for col in range(1, original_sheet.max_column + 1):
                original_cell = original_sheet.cell(row=row, column=col)
                new_cell = new_sheet.cell(row=row, column=col)
                if original_cell.font:
                    new_cell.font = copy.copy(original_cell.font)
                if original_cell.fill:
                    new_cell.fill = copy.copy(original_cell.fill)
    
    # ISTD_Correction 格式
    scientific_format = '0.00E+00'
    orange_fill = PatternFill(start_color='FFA500', end_color='FFA500', fill_type='solid')
    green_fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
    yellow_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
    light_blue_fill = PatternFill(start_color='ADD8E6', end_color='ADD8E6', fill_type='solid')
    light_pink_fill = PatternFill(start_color='FFB6C1', end_color='FFB6C1', fill_type='solid')
    
    if 'ISTD_Correction' in new_workbook.sheetnames:
        worksheet = new_workbook['ISTD_Correction']
        header = [cell.value for cell in worksheet[1]]
        
        # CV% 欄位塗橙色
        for col_name in ['Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%']:
            if col_name in header:
                col_idx = header.index(col_name) + 1
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                    for cell in row:
                        cell.fill = orange_fill
        
        # ✅ 統計檢定欄位塗淡藍色（更新為 Wilcoxon_pvalue）
        for col_name in ['Wilcoxon_pvalue', 'Variance_Test_pvalue']:
            if col_name in header:
                col_idx = header.index(col_name) + 1
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                    for cell in row:
                        cell.fill = light_blue_fill
        
        # ✅ 顯著性標記
        if 'Significant_Improvement' in header:
            col_idx = header.index('Significant_Improvement') + 1
            for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                for cell in row:
                    if cell.value == 'Yes' or cell.value == 'Yes (CV% only)':
                        cell.fill = green_fill
                    elif cell.value == 'Marginal':
                        cell.fill = yellow_fill
                    elif cell.value == 'No':
                        cell.fill = light_pink_fill
        
        # 數字格式
        for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=1, max_col=worksheet.max_column):
            for cell in row:
                if isinstance(cell.value, (int, float)) and cell.value is not None:
                    cell.number_format = scientific_format
    
    new_workbook.save(output_file)
    
    print(f"\n{'='*70}")
    print(f"✓ ISTD Correction 結果已保存:")
    print(f"  {output_file}")
    print(f"{'='*70}\n")
    
    # ✅ 繪製 P 值分佈圖
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    plot_pvalue_distribution(cv_results_df, output_dir, timestamp)

# ========== main 函數 ==========
def main(input_file=None):
    """
    主函數 - 修改為與 GUI 配合
    
    Parameters:
    -----------
    input_file : str, optional
        輸入檔案路徑（由 GUI 傳入）
        如果為 None，則顯示檔案選擇對話框
    
    Returns:
    --------
    dict or None
        - None: 用戶取消檔案選擇
        - dict: 執行成功，包含統計資訊
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 🔧 關鍵修正：如果沒有提供 input_file，則顯示對話框
    if input_file is None:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        
        input_file = filedialog.askopenfilename(
            title="選擇原始 Excel 檔案", 
            filetypes=[("Excel files", "*.xlsx *.xls")]
        )
        
        root.destroy()
        
        # 如果用戶取消選擇，返回 None
        if not input_file:
            print("⚠️ 用戶取消了檔案選擇")
            return None
    
    # 驗證檔案是否存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"找不到檔案: {input_file}")
    
    print("\n" + "="*70)
    print("🔬 開始 ISTD Correction 分析")
    print(f"📁 輸入檔案: {os.path.basename(input_file)}")
    print("="*70 + "\n")
    
    # 載入數據
    original_df, sample_info_df, all_sheets = load_and_process_data(input_file)
    if original_df is None or sample_info_df is None:
        print("❌ 錯誤：數據載入失敗")
        raise Exception("數據載入失敗")
    
    # 計算校正結果
    results_df, sample_columns = calculate_corrected_ratios(original_df, sample_info_df)
    if results_df is None:
        print("❌ 錯誤：校正計算失敗")
        raise Exception("校正計算失敗")
    
    # 儲存結果
    output_file = os.path.join(
        script_dir, 
        f"ISTD_Results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    save_results_to_excel(
        original_df, results_df, sample_info_df, 
        output_file, all_sheets, sample_columns, input_file
    )
    
        # 執行 2D PCA 分析
    print("\n" + "="*70)
    print("📊 開始 2D PCA 分析（Hotelling T² 異常值檢測 + 橢圓 + 固定原點）")
    print("="*70 + "\n")
    perform_pca_analysis_2d(
        original_df, results_df, None, 
        sample_columns, sample_info_df
    )
    
    print("\n" + "="*70)
    print("✅ ISTD Correction 完成！")
    print("="*70)
    print("\n📁 輸出檔案:")
    print(f"  1. Excel 結果: {os.path.basename(output_file)}")
    print(f"  2. PCA 圖表: ISTD_Correction_plots/ 資料夾")
    print("\n💡 請使用輸出的檔案進行後續 QC LOWESS 處理。\n")
    
    # 🎯 返回統計資訊給 GUI
    return {
        'file_path': input_file,
        'metabolites': len(original_df),
        'samples': len(sample_columns),
        'output_path': output_file
    }


if __name__ == "__main__":
    # 🔧 獨立運行時不傳入 input_file，會顯示對話框
    main()