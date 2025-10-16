import pandas as pd
import numpy as np
import os
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import statsmodels.api as sm
from scipy.stats import f as f_dist
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from scipy.stats import chi2
import scipy.stats as stats
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
import warnings
import tkinter as tk
from tkinter import filedialog
import copy

warnings.filterwarnings('ignore')

# ========== 🔧 優化：動態 frac 選擇 ==========
def optimize_lowess_frac_dynamic(qc_count):
    """
    根據 QC 樣本數量動態選擇 frac
    
    參考文獻：
    - Dunn et al. (2011) Nature Protocols
    - Cleveland (1979) JASA: LOWESS 原始論文
    """
    if qc_count < 6:
        return 1.0  # 樣本太少，使用全局平滑
    elif qc_count < 10:
        return 0.8
    elif qc_count < 15:
        return 0.75
    elif qc_count < 25:
        return 0.6
    else:
        return 0.5  # 樣本足夠多，可以使用更局部的平滑


# ========== 🔧 穩健的 LOWESS 校正 ==========
def robust_lowess_correction_v5(qc_orders, qc_intensities, all_orders, all_intensities, feature_id):
    """
    強制捕捉趨勢的 LOWESS 校正（齊頭式校正）
    
    參數:
        feature_id: 如果為 None，則不輸出調試信息；否則輸出詳細調試信息
    """
    qc_orders = np.array(qc_orders)
    qc_intensities = np.array(qc_intensities)
    all_orders = np.array(all_orders)
    all_intensities = np.array(all_intensities)
    
    # ✅ 判斷是否需要輸出調試信息
    debug_mode = feature_id is not None
    
    if len(qc_orders) < 5:
        return all_intensities, {
            'status': 'insufficient_qc',
            'qc_count': len(qc_orders)
        }
    
    # 🔧 步驟 1：檢測離群值（使用更寬鬆的標準）
    Q1 = np.percentile(qc_intensities, 25)
    Q3 = np.percentile(qc_intensities, 75)
    IQR = Q3 - Q1
    
    # ✅ 使用 1.5×IQR
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    
    outlier_mask = (qc_intensities < lower_bound) | (qc_intensities > upper_bound)
    outliers_removed = np.sum(outlier_mask)
    
    qc_orders_clean = qc_orders[~outlier_mask]
    qc_intensities_clean = qc_intensities[~outlier_mask]
    
    # 如果移除太多離群值（>30%），使用原始數據
    if len(qc_orders_clean) < max(5, len(qc_orders) * 0.7):
        qc_orders_clean = qc_orders
        qc_intensities_clean = qc_intensities
        outliers_removed = 0
    
    # 🔧 步驟 2：動態選擇 frac（使用更大的值）
    n_qc = len(qc_orders_clean)

    # ✅ 關鍵改進：使用更大的 frac 值以確保平滑
    if n_qc < 8:
        best_frac = 1.0  # 小樣本：使用全局平滑
    elif n_qc < 12:
        best_frac = 0.8  # 中小樣本
    elif n_qc < 20:
        best_frac = 0.6  # 中等樣本
    else:
        best_frac = 0.4  # 大樣本
    
    try:
        # 🔧 步驟 3：LOWESS 擬合
        lowess_result = sm.nonparametric.lowess(
            qc_intensities_clean,
            qc_orders_clean,
            frac=best_frac,
            it=3,
            delta=0.0,
            return_sorted=True
        )

        # ✅ 驗證 LOWESS 是否進行了平滑
        fitted_values = lowess_result[:, 1]
        input_values = qc_intensities_clean

        # 計算擬合值與輸入值的差異
        diff = np.abs(fitted_values - input_values)
        max_diff = np.max(diff)
        mean_diff = np.mean(diff)

        if debug_mode:
            print(f"\n   🔍 LOWESS 擬合驗證:")
            print(f"     最大差異: {max_diff:.2e}")
            print(f"     平均差異: {mean_diff:.2e}")
            print(f"     差異範圍: {np.min(diff):.2e} - {np.max(diff):.2e}")
            
            if max_diff < 1e-6:
                print(f"     ⚠️  警告：LOWESS 擬合幾乎沒有平滑效果！")
                print(f"     ⚠️  擬合值與輸入值幾乎完全相同")

        
        # 🔧 調試輸出（只在 debug_mode 時輸出）
        if debug_mode:
            print(f"\n🔍 調試特徵: {feature_id}")
            print(f"   QC 樣本數: {n_qc}")
            print(f"   移除離群值: {outliers_removed} 個")
            print(f"   QC 強度範圍: {np.min(qc_intensities_clean):.2e} - {np.max(qc_intensities_clean):.2e}")
            print(f"   QC 均值: {np.mean(qc_intensities_clean):.2e}")
            print(f"   QC 中位數: {np.median(qc_intensities_clean):.2e}")
            print(f"   QC 標準差: {np.std(qc_intensities_clean):.2e}")
            print(f"   原始 CV%: {np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100:.2f}%")
            print(f"   使用 frac: {best_frac}")
            print(f"   LOWESS 擬合點數: {len(lowess_result)}")
            
            print(f"\n   LOWESS 擬合詳細:")
            print(f"     輸入 x (orders): {qc_orders_clean}")
            print(f"     輸入 y (intensities): {qc_intensities_clean}")
            print(f"     輸出 x (orders): {lowess_result[:, 0]}")
            print(f"     輸出 y (fitted): {lowess_result[:, 1]}")
            
            print(f"\n   LOWESS 趨勢範圍: {np.min(lowess_result[:, 1]):.2e} - {np.max(lowess_result[:, 1]):.2e}")
            
            trend_range = np.max(lowess_result[:, 1]) - np.min(lowess_result[:, 1])
            trend_mean = np.mean(lowess_result[:, 1])
            trend_cv = (np.std(lowess_result[:, 1]) / trend_mean) * 100 if trend_mean != 0 else 0
            print(f"   趨勢變異範圍: {trend_range:.2e}")
            print(f"   趨勢 CV%: {trend_cv:.2f}%")
            print(f"   趨勢標準差: {np.std(lowess_result[:, 1]):.2e}")
        
        # 🔧 步驟 4：檢查趨勢是否過於平坦
        trend_std = np.std(lowess_result[:, 1])
        trend_mean = np.mean(lowess_result[:, 1])
        
        if trend_std < trend_mean * 0.001:
            if debug_mode:
                print(f"   ⚠️  警告：趨勢過於平坦 (std={trend_std:.2e}, mean={trend_mean:.2e})")
                print(f"   ⚠️  這可能是數值精度問題或數據本身非常穩定")
            
            from scipy.stats import linregress
            slope, intercept, r_value, p_value, std_err = linregress(qc_orders_clean, qc_intensities_clean)
            
            if debug_mode:
                print(f"\n   📊 嘗試線性擬合:")
                print(f"     斜率: {slope:.2e}")
                print(f"     截距: {intercept:.2e}")
                print(f"     R²: {r_value**2:.4f}")
                print(f"     p-value: {p_value:.4f}")
            
            if abs(slope) > 0 and p_value < 0.1:
                if debug_mode:
                    print(f"   ✅ 使用線性擬合（顯著趨勢）")
                lowess_result[:, 1] = slope * qc_orders_clean + intercept
            else:
                if debug_mode:
                    print(f"   ⚠️  無顯著趨勢，使用原始數據")
                
                return all_intensities, {
                    'status': 'no_trend',
                    'original_cv': np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100,
                    'corrected_cv': np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100,
                    'median_correction_factor': 1.0,
                    'trend_std': trend_std,
                    'linear_slope': slope,
                    'linear_pvalue': p_value
                }
        
        # 🔧 步驟 5：計算參考水平
        qc_reference = np.median(qc_intensities_clean)
        
        # 🔧 步驟 6：插值
        predicted_trends = np.interp(
            all_orders, 
            lowess_result[:, 0],
            lowess_result[:, 1]
        )

        # ✅ 驗證插值結果
        if debug_mode:
            qc_indices = [i for i, order in enumerate(all_orders) if order in qc_orders_clean]
            qc_predicted = predicted_trends[qc_indices]
            
            print(f"\n   🔍 插值驗證:")
            print(f"     QC 樣本的預測趨勢:")
            for i, (order, pred) in enumerate(zip(qc_orders_clean, qc_predicted)):
                print(f"       QC{i+1:02d} (order={order}): {pred:.2e}")
            
            print(f"     預測趨勢範圍: {np.min(qc_predicted):.2e} - {np.max(qc_predicted):.2e}")
            print(f"     預測趨勢標準差: {np.std(qc_predicted):.2e}")

        
        # 🔧 步驟 7：計算校正因子
        predicted_trends = np.where(predicted_trends == 0, qc_reference, predicted_trends)
        correction_factors = qc_reference / predicted_trends
        
        # ✅ 限制校正因子範圍（防止過度校正）
        correction_factors = np.clip(correction_factors, 0.5, 2.0)
        
        # 🔧 調試輸出（只在 debug_mode 時輸出）
        if debug_mode:
            print(f"\n   參考水平 (中位數): {qc_reference:.2e}")
            print(f"   預測趨勢範圍: {np.min(predicted_trends):.2e} - {np.max(predicted_trends):.2e}")
            print(f"   校正因子範圍: {np.min(correction_factors):.2f} - {np.max(correction_factors):.2f}")
            print(f"   校正因子中位數: {np.median(correction_factors):.2f}")
            print(f"   校正因子標準差: {np.std(correction_factors):.2f}")
        
        # 🔧 步驟 8：應用校正
        corrected_intensities = all_intensities * correction_factors
        
        # 🔧 步驟 9：計算校正效果
        qc_indices = [i for i, order in enumerate(all_orders) if order in qc_orders]
        
        if len(qc_indices) >= 2:
            qc_corrected = corrected_intensities[qc_indices]
            original_cv = np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100
            corrected_cv = np.std(qc_corrected, ddof=1) / np.mean(qc_corrected) * 100
            
            if debug_mode:
                print(f"\n   CV% 變化:")
                print(f"     原始: {original_cv:.2f}%")
                print(f"     校正後: {corrected_cv:.2f}%")
                print(f"     改善: {original_cv - corrected_cv:.2f}%")
                
                print(f"\n   前 5 個 QC 樣本的校正:")
                for i in range(min(5, len(qc_indices))):
                    qc_idx = qc_indices[i]
                    original = all_intensities[qc_idx]
                    corrected = corrected_intensities[qc_idx]
                    print(f"     QC{i+1:02d}: {original:.2e} → {corrected:.2e} (因子: {correction_factors[qc_idx]:.2f})")
        else:
            original_cv = np.nan
            corrected_cv = np.nan
        
        correction_info = {
            'status': 'success',
            'frac': best_frac,
            'qc_count': len(qc_orders_clean),
            'outliers_removed': outliers_removed,
            'original_cv': original_cv,
            'corrected_cv': corrected_cv,
            'median_correction_factor': np.median(correction_factors),
            'qc_reference': qc_reference,
            'correction_factor_range': (np.min(correction_factors), np.max(correction_factors)),
            'correction_factor_std': np.std(correction_factors)
        }
        
        return corrected_intensities, correction_info
        
    except Exception as e:
        if debug_mode:
            print(f"   ❌ 校正失敗: {e}")
            import traceback
            traceback.print_exc()
        return all_intensities, {
            'status': 'failed',
            'error': str(e)
        }



# ========== 數據載入 ==========
def get_valid_values(row, columns):
    """
    從 DataFrame 的一行中提取有效值（>0 且非 NaN）
    
    """
    values = []
    for col in columns:
        if col in row.index:  # ✅ 修正：使用 row.index
            try:
                val = float(row[col])
                if not pd.isna(val) and val > 0:
                    values.append(val)
            except (ValueError, TypeError):
                pass
    return values


def load_and_process_data(file_path):
    """載入並驗證數據"""
    try:
        excel_file = pd.ExcelFile(file_path)
        required_sheets = ['ISTD_Correction', 'SampleInfo']
        
        if not all(sheet in excel_file.sheet_names for sheet in required_sheets):
            print(f"❌ 錯誤：缺少必要工作表")
            return None, None, None
        
        sample_info_df = pd.read_excel(excel_file, sheet_name='SampleInfo')
        istd_df = pd.read_excel(excel_file, sheet_name='ISTD_Correction')
        raw_df = pd.read_excel(excel_file, sheet_name='RawIntensity') if 'RawIntensity' in excel_file.sheet_names else None
        
        print(f"✓ 成功載入數據")
        print(f"  - 特徵數: {len(istd_df)}")
        print(f"  - 樣本數: {len(sample_info_df)}")
        
        return raw_df, istd_df, sample_info_df
        
    except Exception as e:
        print(f"❌ 載入數據失敗: {e}")
        return None, None, None


# ========== 🔧 簡化：LOWESS 正規化（移除批次處理）==========
def perform_lowess_normalization(istd_df, sample_info_df):
    """
    簡化的 LOWESS 正規化（所有樣本視為單一批次）
    """
    try:
        # 識別樣本欄位
        exclude_cols = ['FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference', 
                       'ISTD_Median', 'QC_CV%']
        sample_columns = [col for col in istd_df.columns if col not in exclude_cols]
        
         # 識別 QC 樣本
        if 'Sample_Type' in sample_info_df.columns:
            qc_samples = sample_info_df[
                sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)
            ]['Sample_Name'].tolist()
        else:
            qc_samples = [col for col in sample_columns if 'QC' in col.upper()]
        
        qc_samples = [s for s in qc_samples if s in sample_columns]
        
        if len(qc_samples) < 5:
            print(f"❌ QC 樣本不足 ({len(qc_samples)} < 5)，無法進行校正")
            return None, None
        
        print(f"\n📊 數據概覽:")
        print(f"  - 總樣本數: {len(sample_columns)}")
        print(f"  - QC 樣本數: {len(qc_samples)}")
        print(f"  - 特徵數: {len(istd_df)}")
        
        # 建立樣本元數據
        sample_meta = sample_info_df.set_index('Sample_Name')
        
        # 🔧 所有樣本視為單一批次
        all_samples = sample_columns
        all_qc = qc_samples
        
        print(f"\n📦 處理所有樣本")
        print(f"  - 樣本數: {len(all_samples)} (QC: {len(all_qc)})")
        
        # 獲取進樣順序
        injection_orders = {}
        for col in all_samples:
            if col in sample_meta.index:
                injection_orders[col] = sample_meta.loc[col, 'Injection_Order']
        
        # 🔧 計算所有特徵的 CV%，並按高中低選擇調試特徵
        print(f"\n🔍 計算特徵 CV% 以選擇調試樣本...")
        
        feature_cvs = []
        for idx, row in istd_df.iterrows():
            feature_id = row['FeatureID']
            
            # 提取 QC 數據
            qc_values = []
            for qc_sample in all_qc:
                if qc_sample in row.index:
                    intensity = row[qc_sample]
                    if not pd.isna(intensity) and intensity > 0:
                        qc_values.append(intensity)
            
            if len(qc_values) >= 2:
                cv = np.std(qc_values, ddof=1) / np.mean(qc_values) * 100
                feature_cvs.append((feature_id, cv))
        
        if len(feature_cvs) < 3:
            print(f"   ⚠️  特徵數不足，隨機選擇調試特徵")
            import random
            debug_features = [f[0] for f in random.sample(feature_cvs, min(len(feature_cvs), 3))]
        else:
            # 按 CV% 排序
            feature_cvs_sorted = sorted(feature_cvs, key=lambda x: x[1])
            
            # 選擇低、中、高 CV% 的特徵
            low_cv_feature = feature_cvs_sorted[0]
            mid_cv_feature = feature_cvs_sorted[len(feature_cvs_sorted) // 2]
            high_cv_feature = feature_cvs_sorted[-1]
            
            debug_features = [low_cv_feature[0], mid_cv_feature[0], high_cv_feature[0]]
            
            print(f"\n🔍 選擇以下特徵進行詳細調試（按 CV% 低→中→高）:")
            print(f"   1. 低 CV%: {low_cv_feature[0]} (CV% = {low_cv_feature[1]:.2f}%)")
            print(f"   2. 中 CV%: {mid_cv_feature[0]} (CV% = {mid_cv_feature[1]:.2f}%)")
            print(f"   3. 高 CV%: {high_cv_feature[0]} (CV% = {high_cv_feature[1]:.2f}%)")
        
        # 準備結果容器
        all_results = []
        correction_stats = []
        
        # ✅ 新增：記錄每個特徵的 QC 校正後強度
        qc_corrected_values = {}  # {feature_id: {qc_sample: corrected_intensity}}
        
        # 逐特徵校正
        corrected_count = 0
        failed_count = 0
        
        for idx, row in istd_df.iterrows():
            feature_id = row['FeatureID']
            
            # 提取 QC 數據
            qc_data = []
            for qc_sample in qc_samples:  # ✅ 使用 qc_samples
                if qc_sample in injection_orders:
                    order = injection_orders[qc_sample]
                    intensity = row[qc_sample]
                    if not pd.isna(intensity) and intensity > 0:
                        qc_data.append((order, intensity))
            
            if len(qc_data) < 5:
                failed_count += 1
                result_row = {'FeatureID': feature_id}
                for sample in all_samples:
                    result_row[sample] = row[sample]
                all_results.append(result_row)
                
                # ✅ 記錄未校正的 QC 值
                qc_corrected_dict = {}
                for qc in qc_samples:  # ✅ 使用 qc_samples
                    if qc in row.index:
                        qc_corrected_dict[qc] = row[qc]
                qc_corrected_values[feature_id] = qc_corrected_dict
                continue
            
            qc_orders, qc_intensities = zip(*sorted(qc_data))
            
            # 提取所有樣本數據
            all_data = []
            for sample in all_samples:
                if sample in injection_orders:
                    order = injection_orders[sample]
                    intensity = row[sample]
                    all_data.append((sample, order, intensity if not pd.isna(intensity) else 0))
            
            all_sample_names, all_orders, all_intensities = zip(*all_data)
            
            # 執行 LOWESS 校正
            corrected_intensities, info = robust_lowess_correction_v5(  
                qc_orders, qc_intensities, all_orders, all_intensities, 
                feature_id if feature_id in debug_features else None
            )
            
            if info['status'] == 'success':
                corrected_count += 1
                correction_stats.append(info)
            else:
                failed_count += 1
            
            # 保存結果
            result_row = {'FeatureID': feature_id}
            for sample, corrected_val in zip(all_sample_names, corrected_intensities):
                result_row[sample] = corrected_val
            all_results.append(result_row)
            
            # ✅ 記錄 QC 樣本的校正後強度
            qc_corrected_dict = {}
            for sample, corrected_val in zip(all_sample_names, corrected_intensities):
                if sample in qc_samples:  # ✅ 使用 qc_samples
                    qc_corrected_dict[sample] = corrected_val
            qc_corrected_values[feature_id] = qc_corrected_dict
            
            # 進度顯示
            if (idx + 1) % 500 == 0:
                print(f"  進度: {idx + 1}/{len(istd_df)} features")
        
        print(f"  ✓ 完成: {corrected_count} 成功, {failed_count} 失敗")
        
        # 合併結果
        lowess_df = pd.DataFrame(all_results)
        
        # ✅ 返回 QC 校正後強度
        return lowess_df, sample_columns, qc_corrected_values
        
    except Exception as e:
        print(f"❌ LOWESS 校正失敗: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None



# ========== 配對 F 檢定 ==========
def paired_f_test_variance(original_values, corrected_values):
    """
    配對數據的 F 檢定（方差比較）
    """
    if len(original_values) < 2 or len(corrected_values) < 2:
        return np.nan, np.nan, np.nan
    
    var_original = np.var(original_values, ddof=1)
    var_corrected = np.var(corrected_values, ddof=1)
    
    min_variance_threshold = 1e-10
    
    if var_corrected < min_variance_threshold:
        if var_original < min_variance_threshold:
            return np.nan, 1.0, 1.0
        else:
            return np.nan, 0.0, np.inf
    
    if var_original < min_variance_threshold:
        return np.nan, np.nan, 0.0
    
    try:
        # 計算 F 統計量（方差比）
        f_statistic = var_original / var_corrected
        
        # 自由度
        df1 = len(original_values) - 1
        df2 = len(corrected_values) - 1
        
        # 雙尾 p 值
        if f_statistic >= 1:
            p_value = 2 * (1 - f_dist.cdf(f_statistic, df1, df2))
        else:
            p_value = 2 * f_dist.cdf(f_statistic, df1, df2)
        
        p_value = np.clip(p_value, 0, 1)
        variance_ratio = f_statistic
        
    except Exception as e:
        return np.nan, np.nan, np.nan
    
    return f_statistic, p_value, variance_ratio

def calculate_robust_cv(values, method='median'):
    """
    更穩健且精確的 CV% 計算
    """
    if len(values) < 2:
        return np.nan
    
    # 檢查所有值是否幾乎相等
    if np.allclose(values, values[0], rtol=1e-5, atol=1e-8):
        return 0.0
    
    # 使用魯棒統計方法
    if method == 'median':
        center = np.median(values)
        deviation = np.abs(values - center)
        robust_std = 1.4826 * np.median(deviation)  # MAD 估計標準差
    else:
        center = np.mean(values)
        robust_std = np.std(values, ddof=1)
    
    # 避免除零
    if center == 0:
        return np.nan
    
    cv = (robust_std / center) * 100
    
    return cv


def calculate_qc_cv_with_f_test(istd_df, lowess_df, sample_columns, sample_info_df, qc_corrected_values):
    """
    計算 QC CV% 並進行配對 F 檢定
    
    ✅ 確保只計算 QC 樣本的 CV%
    """
    # 🔧 確保 DataFrame 索引重置
    istd_df = istd_df.reset_index(drop=True)
    lowess_df = lowess_df.reset_index(drop=True)
    
    # 🔧 確保兩個 DataFrame 長度一致
    min_length = min(len(istd_df), len(lowess_df))
    istd_df = istd_df.iloc[:min_length]
    lowess_df = lowess_df.iloc[:min_length]
    
    # 🔍 識別 QC 樣本（添加詳細調試）
    print(f"\n{'='*70}")
    print(f"🔬 識別 QC 樣本")
    print(f"{'='*70}")
    
    if 'Sample_Type' in sample_info_df.columns:
        print(f"  ✓ 使用 Sample_Type 欄位識別 QC 樣本")
        qc_samples = sample_info_df[
            sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)
        ]['Sample_Name'].tolist()
        print(f"  - 從 Sample_Type 識別到的 QC 樣本: {qc_samples}")
    else:
        print(f"  ⚠️ 未找到 Sample_Type 欄位，使用欄位名稱識別 QC 樣本")
        qc_samples = [col for col in sample_columns if 'QC' in col.upper()]
        print(f"  - 從欄位名稱識別到的 QC 樣本: {qc_samples}")
    
    # 🔍 驗證 QC 樣本是否在 sample_columns 中
    qc_columns = [col for col in qc_samples if col in sample_columns]
    print(f"  - 最終使用的 QC 樣本數: {len(qc_columns)}")
    print(f"  - QC 樣本列表: {qc_columns}")
    
    if len(qc_columns) == 0:
        print(f"  ❌ 錯誤：未找到任何 QC 樣本！")
        print(f"  - sample_columns: {sample_columns}")
        return pd.DataFrame()
    
    cv_results = []
    
    print(f"\n🔬 開始統計檢定（配對 F 檢定）...")
    print(f"  - 特徵總數: {len(istd_df)}")
    
    # 🔍 調試前 3 個特徵
    debug_count = 0
    
    for idx in range(len(istd_df)):
        try:
            istd_row = istd_df.iloc[idx]
            lowess_row = lowess_df.iloc[idx]
            feature_id = istd_row['FeatureID']
            
            # 🔍 調試輸出
            if debug_count < 3:
                print(f"\n{'='*70}")
                print(f"🔬 調試特徵 {idx + 1}: {feature_id}")
                print(f"{'='*70}")
            
            # ✅ 計算原始數據的 CV%（只使用 QC 樣本）
            qc_values_istd = get_valid_values(istd_row, qc_columns)
            
            # 🔍 調試輸出
            if debug_count < 3:
                print(f"原始數據 (ISTD):")
                print(f"  - QC 樣本欄位: {qc_columns}")
                print(f"  - 提取的有效值數量: {len(qc_values_istd)}")
                if len(qc_values_istd) > 0:
                    print(f"  - 有效值: {qc_values_istd[:5]}..." if len(qc_values_istd) > 5 else f"  - 有效值: {qc_values_istd}")
                    print(f"  - 均值: {np.mean(qc_values_istd):.2e}")
                    print(f"  - 標準差: {np.std(qc_values_istd, ddof=1):.2e}")
            
            mean_istd = np.mean(qc_values_istd) if qc_values_istd else np.nan
            std_istd = np.std(qc_values_istd, ddof=1) if len(qc_values_istd) >= 2 else np.nan
            cv_istd = (std_istd / mean_istd) * 100 if mean_istd != 0 else np.nan
            
            # 🔍 調試輸出
            if debug_count < 3:
                print(f"  - CV%: {cv_istd:.2f}%")
            
            # ✅ 計算校正後數據的 CV%（從 qc_corrected_values）
            if feature_id in qc_corrected_values:
                qc_corrected_dict = qc_corrected_values[feature_id]
                
                # 提取有效的校正後 QC 值
                qc_values_lowess = []
                for qc in qc_columns:
                    if qc in qc_corrected_dict:
                        val = qc_corrected_dict[qc]
                        if not pd.isna(val) and val > 0:
                            qc_values_lowess.append(val)
                
                # 🔍 調試輸出
                if debug_count < 3:
                    print(f"\n校正後數據 (LOWESS):")
                    print(f"  - QC 樣本欄位: {qc_columns}")
                    print(f"  - qc_corrected_dict 中的樣本數: {len(qc_corrected_dict)}")
                    print(f"  - 提取的有效值數量: {len(qc_values_lowess)}")
                    if len(qc_values_lowess) > 0:
                        print(f"  - 有效值: {qc_values_lowess[:5]}..." if len(qc_values_lowess) > 5 else f"  - 有效值: {qc_values_lowess}")
                        print(f"  - 均值: {np.mean(qc_values_lowess):.2e}")
                        print(f"  - 標準差: {np.std(qc_values_lowess, ddof=1):.2e}")
                
                if len(qc_values_lowess) >= 2:
                    mean_lowess = np.mean(qc_values_lowess)
                    std_lowess = np.std(qc_values_lowess, ddof=1)
                    cv_lowess = (std_lowess / mean_lowess) * 100 if mean_lowess != 0 else np.nan
                else:
                    mean_lowess = np.nan
                    std_lowess = np.nan
                    cv_lowess = np.nan
            else:
                # ⚠️ 如果沒有記錄，使用 lowess_df 的值（備用方案）
                if debug_count < 3:
                    print(f"\n⚠️ 警告：feature_id {feature_id} 不在 qc_corrected_values 中")
                    print(f"  - 使用 lowess_df 的值作為備用方案")
                
                qc_values_lowess = get_valid_values(lowess_row, qc_columns)
                mean_lowess = np.mean(qc_values_lowess) if qc_values_lowess else np.nan
                std_lowess = np.std(qc_values_lowess, ddof=1) if len(qc_values_lowess) >= 2 else np.nan
                cv_lowess = (std_lowess / mean_lowess) * 100 if mean_lowess != 0 else np.nan
            
            # 🔍 調試輸出
            if debug_count < 3:
                print(f"  - CV%: {cv_lowess:.2f}%")
                debug_count += 1
            
            # 使用配對 F 檢定
            if len(qc_values_istd) >= 2 and len(qc_values_lowess) >= 2:
                try:
                    f_stat, p_value, var_ratio = paired_f_test_variance(
                        qc_values_istd, qc_values_lowess
                    )
                except Exception:
                    f_stat, p_value, var_ratio = np.nan, np.nan, np.nan
            else:
                f_stat, p_value, var_ratio = np.nan, np.nan, np.nan
            
            # 計算改善程度
            improvement = cv_istd - cv_lowess if not np.isnan(cv_istd) and not np.isnan(cv_lowess) else np.nan
            
            # 判定顯著性
            if not np.isnan(p_value):
                significant = 'Yes' if p_value < 0.05 else 'No'
            else:
                significant = 'N/A'
            
            cv_results.append({
                'FeatureID': feature_id,
                'Original_QC_CV%': cv_istd,
                'Corrected_QC_CV%': cv_lowess,
                'Improvement_QC_CV%': improvement,
                'Variance_Ratio': var_ratio,
                'F_statistic': f_stat,
                'F_test_pvalue': p_value,
                'Significant': significant
            })
            
            # 進度顯示
            if (idx + 1) % 100 == 0:
                print(f"  處理進度: {idx + 1}/{len(istd_df)} features")
        
        except Exception as e:
            print(f"  ⚠️ 處理特徵 {idx} 時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"  ✓ 統計檢定完成！")
    
    return pd.DataFrame(cv_results)



# ========== 完整複製工作表格式 ==========
def copy_sheet_with_full_format(source_sheet, target_sheet):
    """完整複製工作表（包含所有格式、合併儲存格、列寬行高）"""
    try:
        # 複製儲存格值和格式
        for row in source_sheet.iter_rows():
            for cell in row:
                target_cell = target_sheet.cell(row=cell.row, column=cell.column, value=cell.value)
                
                # 複製所有格式
                if cell.has_style:
                    target_cell.font = copy.copy(cell.font)
                    target_cell.border = copy.copy(cell.border)
                    target_cell.fill = copy.copy(cell.fill)
                    target_cell.number_format = copy.copy(cell.number_format)
                    target_cell.protection = copy.copy(cell.protection)
                    target_cell.alignment = copy.copy(cell.alignment)
        
        # 複製列寬
        for col_letter, col_dim in source_sheet.column_dimensions.items():
            target_sheet.column_dimensions[col_letter].width = col_dim.width
        
        # 複製行高
        for row_num, row_dim in source_sheet.row_dimensions.items():
            target_sheet.row_dimensions[row_num].height = row_dim.height
        
        # 複製合併儲存格
        for merged_cell_range in source_sheet.merged_cells.ranges:
            target_sheet.merge_cells(str(merged_cell_range))
        
        return True
        
    except Exception as e:
        print(f"  ⚠ 複製格式時發生錯誤: {e}")
        return False


# ========== 保存結果到 Excel ==========
def save_results_to_excel(raw_df, istd_df, lowess_df, sample_info_df, sample_columns, output_file, input_file, qc_corrected_values):
    try:
        # 使用配對 F 檢定計算 CV%
        cv_results_df = calculate_qc_cv_with_f_test(
            istd_df, 
            lowess_df, 
            sample_columns, 
            sample_info_df, 
            qc_corrected_values  # 添加 qc_corrected_values 參數
        )
        
        lowess_with_cv = lowess_df.merge(cv_results_df, on='FeatureID', how='left')
        
        # 調整欄位順序
        cols_order = ['Original_QC_CV%', 'Corrected_QC_CV%', 'Improvement_QC_CV%',
                      'Variance_Ratio', 'F_statistic', 'F_test_pvalue', 'Significant']
        other_cols = [col for col in lowess_with_cv.columns if col not in cols_order]
        lowess_with_cv = lowess_with_cv[other_cols + cols_order]
        
        # 載入原始檔案，保留 ISTD_Correction 的格式
        print(f"\n📋 開始處理 Excel 檔案...")
        print(f"  - 載入原始檔案: {os.path.basename(input_file)}")
        
        input_workbook = load_workbook(input_file)
        workbook = input_workbook
        
        # 刪除要重新生成的工作表
        sheets_to_update = ['QC LOWESS result', 'SampleInfo']
        
        for sheet_name in sheets_to_update:
            if sheet_name in workbook.sheetnames:
                del workbook[sheet_name]
                print(f"  - 刪除舊工作表: {sheet_name}")
        
        # 保存 ISTD_Correction 的原始格式
        istd_sheet_original = workbook['ISTD_Correction']
        
        # 儲存原始格式資訊
        istd_formats = {}
        for row in istd_sheet_original.iter_rows():
            for cell in row:
                cell_coord = f"{cell.column_letter}{cell.row}"
                if cell.has_style:
                    istd_formats[cell_coord] = {
                        'font': copy.copy(cell.font),
                        'border': copy.copy(cell.border),
                        'fill': copy.copy(cell.fill),
                        'number_format': copy.copy(cell.number_format),
                        'protection': copy.copy(cell.protection),
                        'alignment': copy.copy(cell.alignment)
                    }
        
        # 儲存列寬和行高
        istd_col_widths = {col: dim.width for col, dim in istd_sheet_original.column_dimensions.items()}
        istd_row_heights = {row: dim.height for row, dim in istd_sheet_original.row_dimensions.items()}
        istd_merged_cells = [str(merged) for merged in istd_sheet_original.merged_cells.ranges]
        
        # 使用 pandas 寫入新數據到臨時檔案
        temp_file = output_file.replace('.xlsx', '_temp.xlsx')
        with pd.ExcelWriter(temp_file, engine='openpyxl') as writer:
            istd_df.to_excel(writer, sheet_name='ISTD_Correction', index=False)
            lowess_with_cv.to_excel(writer, sheet_name='QC LOWESS result', index=False)
            sample_info_df.to_excel(writer, sheet_name='SampleInfo', index=False)
        
        # 載入臨時檔案
        temp_workbook = load_workbook(temp_file)
        
        # 將 ISTD_Correction 的數據複製到原始 workbook，並恢復格式
        print(f"  - 更新 ISTD_Correction 工作表（保留原始格式）...")
        
        # 刪除舊的 ISTD_Correction
        if 'ISTD_Correction' in workbook.sheetnames:
            del workbook['ISTD_Correction']
        
        # 創建新的 ISTD_Correction
        istd_sheet_new = workbook.create_sheet('ISTD_Correction', 0)
        
        # 複製數據
        temp_istd_sheet = temp_workbook['ISTD_Correction']
        for row in temp_istd_sheet.iter_rows():
            for cell in row:
                istd_sheet_new.cell(row=cell.row, column=cell.column, value=cell.value)
        
        # 恢復原始格式
        for cell_coord, formats in istd_formats.items():
            try:
                cell = istd_sheet_new[cell_coord]
                cell.font = formats['font']
                cell.border = formats['border']
                cell.fill = formats['fill']
                cell.number_format = formats['number_format']
                cell.protection = formats['protection']
                cell.alignment = formats['alignment']
            except:
                pass
        
        # 恢復列寬和行高
        for col, width in istd_col_widths.items():
            istd_sheet_new.column_dimensions[col].width = width
        
        for row, height in istd_row_heights.items():
            istd_sheet_new.row_dimensions[row].height = height
        
                # 恢復合併儲存格
        for merged in istd_merged_cells:
            try:
                istd_sheet_new.merge_cells(merged)
            except:
                pass
        
        print(f"  ✓ ISTD_Correction 格式已完整保留")
        
        # 複製其他新工作表
        for sheet_name in ['QC LOWESS result', 'SampleInfo']:
            if sheet_name in temp_workbook.sheetnames:
                source_sheet = temp_workbook[sheet_name]
                target_sheet = workbook.create_sheet(sheet_name)
                copy_sheet_with_full_format(source_sheet, target_sheet)
                print(f"  ✓ 已複製工作表: {sheet_name}")
        
        temp_workbook.close()
        
        # 刪除臨時檔案
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        # 格式化數值欄位（科學記號）
        scientific_format = '0.00E+00'
        
        for sheet_name in ['ISTD_Correction', 'QC LOWESS result', 'SampleInfo']:
            if sheet_name in workbook.sheetnames:
                worksheet = workbook[sheet_name]
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=1, max_col=worksheet.max_column):
                    for cell in row:
                        if isinstance(cell.value, (int, float)) and not pd.isna(cell.value):
                            if cell.number_format == 'General' or cell.number_format == '0':
                                cell.number_format = scientific_format

        # 顏色標記（僅針對 QC LOWESS result）
        orange_fill = PatternFill(start_color='FFA500', end_color='FFA500', fill_type='solid')
        green_fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
        yellow_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
        light_blue_fill = PatternFill(start_color='ADD8E6', end_color='ADD8E6', fill_type='solid')

        if 'QC LOWESS result' in workbook.sheetnames:
            worksheet = workbook['QC LOWESS result']
            header = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            
            # CV% 欄位 - 橙色
            for col_name in ['Original_QC_CV%', 'Corrected_QC_CV%', 'Improvement_QC_CV%']:
                if col_name in header:
                    col_idx = header.index(col_name) + 1
                    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                        for cell in row:
                            cell.fill = orange_fill
            
            # F 檢定相關欄位 - 淺藍色
            for col_name in ['Variance_Ratio', 'F_statistic', 'F_test_pvalue']:
                if col_name in header:
                    col_idx = header.index(col_name) + 1
                    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                        for cell in row:
                            cell.fill = light_blue_fill
            
            # Significant 欄位 - 綠色/黃色
            if 'Significant' in header:
                col_idx = header.index('Significant') + 1
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                    for cell in row:
                        if cell.value == 'Yes':
                            cell.fill = green_fill
                        elif cell.value == 'No':
                            cell.fill = yellow_fill

        # 保存最終檔案
        workbook.save(output_file)
        workbook.close()
        
        # 統計報告
        print(f"\n{'='*70}")
        print(f"✓ QC LOWESS 結果已保存:")
        print(f"  {output_file}")
        print(f"{'='*70}")
        
        # 統計顯著性結果（F 檢定）
        sig_count = (cv_results_df['Significant'] == 'Yes').sum()
        total_count = len(cv_results_df)
        print(f"\n📊 配對 F 檢定統計摘要:")
        print(f"  - 總特徵數: {total_count}")
        print(f"  - 顯著改善 (p < 0.05): {sig_count} ({sig_count/total_count*100:.1f}%)")
        print(f"  - 無顯著差異: {total_count - sig_count} ({(total_count-sig_count)/total_count*100:.1f}%)")
        
        # F 檢定統計
        f_valid = cv_results_df['F_test_pvalue'].notna().sum()
        f_sig = ((cv_results_df['F_test_pvalue'] < 0.05) & (cv_results_df['F_test_pvalue'].notna())).sum()
        print(f"\n🔬 配對 F 檢定詳細統計:")
        print(f"  - 成功執行: {f_valid}/{total_count} ({f_valid/total_count*100:.1f}%)")
        if f_valid > 0:
            print(f"  - 顯著改善 (p < 0.05): {f_sig}/{f_valid} ({f_sig/f_valid*100:.1f}%)")
            print(f"  - 無顯著差異: {f_valid - f_sig}/{f_valid} ({(f_valid-f_sig)/f_valid*100:.1f}%)")
        
        # 方差比統計
        var_ratio_valid = cv_results_df['Variance_Ratio'].notna()
        if var_ratio_valid.sum() > 0:
            var_ratios = cv_results_df.loc[var_ratio_valid, 'Variance_Ratio']
            var_ratios_finite = var_ratios[np.isfinite(var_ratios)]
            
            if len(var_ratios_finite) > 0:
                median_ratio = np.median(var_ratios_finite)
                mean_ratio = np.mean(var_ratios_finite)
                print(f"\n📉 方差比統計 (Original/Corrected):")
                print(f"  - 中位數: {median_ratio:.2f}")
                print(f"  - 平均值: {mean_ratio:.2f}")
                print(f"  - 範圍: {var_ratios_finite.min():.2f} - {var_ratios_finite.max():.2f}")
                
                improved_count = (var_ratios_finite > 1.2).sum()
                similar_count = ((var_ratios_finite >= 0.8) & (var_ratios_finite <= 1.2)).sum()
                worse_count = (var_ratios_finite < 0.8).sum()
                
                print(f"\n  改善程度分類:")
                print(f"  - 顯著改善 (>1.2x): {improved_count} ({improved_count/len(var_ratios_finite)*100:.1f}%)")
                print(f"  - 無明顯變化 (0.8-1.2x): {similar_count} ({similar_count/len(var_ratios_finite)*100:.1f}%)")
                print(f"  - 變差 (<0.8x): {worse_count} ({worse_count/len(var_ratios_finite)*100:.1f}%)")
        
        # CV% 改善統計
        cv_improvement_valid = cv_results_df['Improvement_QC_CV%'].notna()
        if cv_improvement_valid.sum() > 0:
            improvements = cv_results_df.loc[cv_improvement_valid, 'Improvement_QC_CV%']
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
        
        return True

    except Exception as e:
        print(f"❌ 儲存 Excel 時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False



# ========== ✅ 修正：基於 QC 群組內部的 Hotelling T² 異常值檢測 ==========
def calculate_hotelling_t2_outliers(qc_scores, all_scores=None, alpha=0.05):
    """
    使用 Hotelling T² 檢測 QC 樣本中的異常值
    
    ✅ 正確邏輯：計算每個 QC 樣本與 QC 群組中心的偏離
    
    Parameters:
    -----------
    qc_scores : ndarray
        QC 樣本的 PCA 分數 (n_qc, n_components)
    all_scores : ndarray, optional
        所有樣本的 PCA 分數（此參數保留以兼容舊代碼，但不使用）
    alpha : float
        顯著水平（預設 0.05）
    
    Returns:
    --------
    t2_values : ndarray
        每個 QC 樣本的 Hotelling T² 值
    threshold : float
        T² 閾值
    outliers : ndarray (bool)
        異常值標記
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
    # 參考：Montgomery (2009), "Introduction to Statistical Quality Control"
    if n_qc - p - 1 > 0:
        f_critical = stats.f.ppf(1 - alpha, p, n_qc - p - 1)
        threshold = (p * (n_qc + 1) * (n_qc - 1)) / (n_qc * (n_qc - p - 1)) * f_critical
    else:
        # 樣本數太少，使用卡方分布
        threshold = chi2.ppf(1 - alpha, p)
    
    # 識別異常值
    outliers = t2_values > threshold
    
    return t2_values, threshold, outliers





# ========== Hotelling T² 橢圓繪製 ==========
# ========== ✅ 保持不變：繪製 Hotelling T² 橢圓 ==========
def draw_hotelling_t2_ellipse(ax, scores, alpha=0.05, label=None, edgecolor='black', linestyle='-', linewidth=2.5):
    """
    在 2D PCA 圖上繪製 Hotelling T² 橢圓
    
    ✅ 關鍵：橢圓中心使用樣本群組的實際均值
    
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
        print(f"   ⚠️ 樣本數不足 ({n} < 3)，無法繪製 Hotelling T² 橢圓")
        return None
    
    # ✅ 使用該群組的實際均值
    mean = np.mean(scores, axis=0)
    
    # 計算協方差矩陣
    cov = np.cov(scores, rowvar=False)
    
    # 計算特徵值和特徵向量
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
    
    # 旋轉角度
    angle = np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
    
    # ✅ 繪製橢圓（中心為該群組的實際均值）
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




# ========== ✅ 完整：PCA 分析（參考 Batch_effect 腳本）==========
def perform_pca_analysis(istd_df, lowess_df, sample_columns, sample_info_df):
    """
    完整的 PCA 分析
    
    ✅ 參考 Batch_effect 腳本的邏輯：
    1. QC 異常值檢測基於 QC 群組內部統計量
    2. 繪製兩個橢圓：所有樣本（灰色虛線）+ QC（紫色實線）
    3. 異常值標記：紅色邊框 + 加大尺寸
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, "QC_LOWESS_plots")
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        sample_meta = sample_info_df.set_index('Sample_Name')

        # ===== 數據準備 =====
        
        # 提取樣本列
        sample_columns_clean = [col for col in sample_columns if col in istd_df.columns and col in lowess_df.columns]
        
        if len(sample_columns_clean) < 3:
            print("   ⚠️ 樣本數量不足，無法進行 PCA 分析")
            return
        
        # 分類樣本
        qc_columns = []
        control_columns = []
        exposed_columns = []
        
        for col in sample_columns_clean:
            if col in sample_meta.index:
                sample_type = sample_meta.loc[col].get('Sample_Type', 'Unknown')
                sample_type_upper = str(sample_type).upper()
                
                if 'QC' in sample_type_upper:
                    qc_columns.append(col)
                elif 'CONTROL' in sample_type_upper or 'CTL' in sample_type_upper:
                    control_columns.append(col)
                elif 'EXPOSED' in sample_type_upper or 'EXP' in sample_type_upper:
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
                control_columns.append(col)
        
        print(f"\n📊 樣本分類:")
        print(f"   - Control: {len(control_columns)} 個")
        print(f"   - Exposed: {len(exposed_columns)} 個")
        print(f"   - QC: {len(qc_columns)} 個")
        
        # 提取數據矩陣
        istd_data = istd_df[sample_columns_clean].values.T  # (樣本 x 特徵)
        lowess_data = lowess_df[sample_columns_clean].values.T
        
        # 數據預處理
        def preprocess_data(data):
            data_processed = data.astype(float)
            min_nonzero = np.min(data_processed[data_processed > 0]) if np.any(data_processed > 0) else 1
            data_processed[data_processed == 0] = min_nonzero / 2
            data_processed = np.nan_to_num(data_processed, nan=min_nonzero / 2)
            data_log = np.log2(data_processed + 1)
            scaler = StandardScaler()
            return scaler.fit_transform(data_log)
        
        istd_scaled = preprocess_data(istd_data)
        lowess_scaled = preprocess_data(lowess_data)
        
        # PCA
        pca_istd = PCA(n_components=2)
        pca_lowess = PCA(n_components=2)
        
        scores_istd = pca_istd.fit_transform(istd_scaled)
        scores_lowess = pca_lowess.fit_transform(lowess_scaled)
        
        var_istd = pca_istd.explained_variance_ratio_
        var_lowess = pca_lowess.explained_variance_ratio_
        
        print(f"\n🔬 PCA 解釋變異量:")
        print(f"   ISTD Correction:")
        print(f"   - PC1: {var_istd[0]:.1%}")
        print(f"   - PC2: {var_istd[1]:.1%}")
        print(f"   QC-LOWESS Normalized:")
        print(f"   - PC1: {var_lowess[0]:.1%}")
        print(f"   - PC2: {var_lowess[1]:.1%}")
        
        # ===== ✅ 關鍵修正：基於 QC 群組內部的異常值檢測 =====
        
        qc_indices = [i for i, col in enumerate(sample_columns_clean) if col in qc_columns]
        
        if len(qc_indices) >= 3:
            qc_scores_istd = scores_istd[qc_indices]
            qc_scores_lowess = scores_lowess[qc_indices]
            
            # ✅ 修正：不傳入 all_scores，只使用 qc_scores
            t2_istd, t2_threshold_istd, outliers_istd = calculate_hotelling_t2_outliers(
                qc_scores_istd, alpha=0.05
            )
            t2_lowess, t2_threshold_lowess, outliers_lowess = calculate_hotelling_t2_outliers(
                qc_scores_lowess, alpha=0.05
            )
            
            print(f"\n🔍 Hotelling T² 異常值檢測（基於 QC 群組內部）:")
            print(f"   ISTD Correction:")
            print(f"   - T² 閾值: {t2_threshold_istd:.2f}")
            print(f"   - 異常值數量: {np.sum(outliers_istd)}/{len(qc_columns)}")
            if np.sum(outliers_istd) > 0:
                outlier_samples = [qc_columns[i] for i in range(len(outliers_istd)) if outliers_istd[i]]
                outlier_t2_values = [t2_istd[i] for i in range(len(outliers_istd)) if outliers_istd[i]]
                print(f"   - 異常樣本:")
                for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                    print(f"     • {sample}: T² = {t2_val:.2f}")
            
            print(f"\n   QC-LOWESS Normalized:")
            print(f"   - T² 閾值: {t2_threshold_lowess:.2f}")
            print(f"   - 異常值數量: {np.sum(outliers_lowess)}/{len(qc_columns)}")
            if np.sum(outliers_lowess) > 0:
                outlier_samples = [qc_columns[i] for i in range(len(outliers_lowess)) if outliers_lowess[i]]
                outlier_t2_values = [t2_lowess[i] for i in range(len(outliers_lowess)) if outliers_lowess[i]]
                print(f"   - 異常樣本:")
                for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                    print(f"     • {sample}: T² = {t2_val:.2f}")
        else:
            outliers_istd = np.zeros(len(qc_indices), dtype=bool)
            outliers_lowess = np.zeros(len(qc_indices), dtype=bool)
            print(f"\n   ⚠️ QC 樣本數不足 ({len(qc_indices)} < 3)，無法進行異常值檢測")
        
        # ===== 繪製 PCA 圖（參考 Batch_effect 腳本）=====
        
        fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(18, 7.5))
        fig.suptitle('2D PCA Comparison: ISTD Corrected vs QC-LOWESS Normalized',
                     fontsize=18, y=0.98, fontweight='bold')
        
        # 顏色和標記
        color_map = {
            'QC': '#9370DB',
            'Control': '#4169E1',
            'Exposed': '#DC143C'
        }
        
        markers = {'QC': 'o', 'Control': 's', 'Exposed': '^'}
        
        # ===== 左圖：ISTD Correction =====
        for i, col in enumerate(sample_columns_clean):
            if col in qc_columns:
                sample_type = 'QC'
                qc_idx = qc_columns.index(col)
                is_outlier = outliers_istd[qc_idx] if qc_idx < len(outliers_istd) else False
            elif col in exposed_columns:
                sample_type = 'Exposed'
                is_outlier = False
            else:
                sample_type = 'Control'
                is_outlier = False
            
            color = color_map[sample_type]
            marker = markers[sample_type]
            
            # ✅ 異常值標記（參考 Batch_effect 腳本）
            if is_outlier:
                edgecolor = 'red'
                linewidth = 3
                size = 150
                alpha = 0.9
            else:
                edgecolor = 'black'
                linewidth = 1
                size = 100
                alpha = 0.7
            
            ax_left.scatter(scores_istd[i, 0], scores_istd[i, 1],
                          c=[color], marker=marker, s=size, alpha=alpha,
                          edgecolors=edgecolor, linewidths=linewidth)
        
        # ✅ 繪製兩個橢圓（參考 Batch_effect 腳本）
        all_bounds_left = []
        
        # 1. 所有樣本的橢圓（灰色虛線）
        try:
            bounds_all_left = draw_hotelling_t2_ellipse(
                ax_left, scores_istd,
                label='95% CI (All Samples)',
                edgecolor='gray', linestyle='--', linewidth=3
            )
            if bounds_all_left is not None:
                all_bounds_left.append(bounds_all_left)
        except Exception as e:
            print(f"   ⚠️ 所有樣本橢圓繪製失敗: {e}")
        
        # 2. QC 樣本的橢圓（紫色實線）
        if len(qc_indices) >= 3:
            try:
                bounds_qc_left = draw_hotelling_t2_ellipse(
                    ax_left, qc_scores_istd,
                    label='95% CI (QC Only)',
                    edgecolor='#9370DB', linestyle='-', linewidth=3
                )
                if bounds_qc_left is not None:
                    all_bounds_left.append(bounds_qc_left)
            except Exception as e:
                print(f"   ⚠️ QC 橢圓繪製失敗: {e}")
        
        # ✅ 調整軸範圍（參考 Batch_effect 腳本）
        if all_bounds_left:
            x_min = min([b[0] for b in all_bounds_left])
            x_max = max([b[1] for b in all_bounds_left])
            y_min = min([b[2] for b in all_bounds_left])
            y_max = max([b[3] for b in all_bounds_left])
        else:
            x_min, x_max = np.min(scores_istd[:, 0]), np.max(scores_istd[:, 0])
            y_min, y_max = np.min(scores_istd[:, 1]), np.max(scores_istd[:, 1])
        
        # 同時考慮數據點範圍
        data_x_min, data_x_max = np.min(scores_istd[:, 0]), np.max(scores_istd[:, 0])
        data_y_min, data_y_max = np.min(scores_istd[:, 1]), np.max(scores_istd[:, 1])
        
        x_min = min(x_min, data_x_min)
        x_max = max(x_max, data_x_max)
        y_min = min(y_min, data_y_min)
        y_max = max(y_max, data_y_max)
        
        x_margin = (x_max - x_min) * 0.2
        y_margin = (y_max - y_min) * 0.2
        
        ax_left.set_xlim(x_min - x_margin, x_max + x_margin)
        ax_left.set_ylim(y_min - y_margin, y_max + y_margin)
        
        ax_left.set_title(
            f'ISTD Correction\n'
            f'PC1: {var_istd[0]:.1%}, PC2: {var_istd[1]:.1%}',
            fontsize=13, fontweight='bold', pad=10
        )
        ax_left.set_xlabel(f't[1] ({var_istd[0]:.1%})', fontsize=12, fontweight='bold')
        ax_left.set_ylabel(f't[2] ({var_istd[1]:.1%})', fontsize=12, fontweight='bold')
        ax_left.grid(True, alpha=0.3, linestyle='--')
        ax_left.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        ax_left.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        
        # ===== 右圖：QC-LOWESS Normalized（相同邏輯）=====
        for i, col in enumerate(sample_columns_clean):
            if col in qc_columns:
                sample_type = 'QC'
                qc_idx = qc_columns.index(col)
                is_outlier = outliers_lowess[qc_idx] if qc_idx < len(outliers_lowess) else False
            elif col in exposed_columns:
                sample_type = 'Exposed'
                is_outlier = False
            else:
                sample_type = 'Control'
                is_outlier = False
            
            color = color_map[sample_type]
            marker = markers[sample_type]
            
            if is_outlier:
                edgecolor = 'red'
                linewidth = 3
                size = 150
                alpha = 0.9
            else:
                edgecolor = 'black'
                linewidth = 1
                size = 100
                alpha = 0.7
            
            ax_right.scatter(scores_lowess[i, 0], scores_lowess[i, 1],
                           c=[color], marker=marker, s=size, alpha=alpha,
                           edgecolors=edgecolor, linewidths=linewidth)
        
        all_bounds_right = []
        
        try:
            bounds_all_right = draw_hotelling_t2_ellipse(
                ax_right, scores_lowess,
                label='95% CI (All Samples)',
                edgecolor='gray', linestyle='--', linewidth=3
            )
            if bounds_all_right is not None:
                all_bounds_right.append(bounds_all_right)
        except Exception as e:
            print(f"   ⚠️ 所有樣本橢圓繪製失敗: {e}")
        
        if len(qc_indices) >= 3:
            try:
                bounds_qc_right = draw_hotelling_t2_ellipse(
                    ax_right, qc_scores_lowess,
                    label='95% CI (QC Only)',
                    edgecolor='#9370DB', linestyle='-', linewidth=3
                )
                if bounds_qc_right is not None:
                    all_bounds_right.append(bounds_qc_right)
            except Exception as e:
                print(f"   ⚠️ QC 橢圓繪製失敗: {e}")
        
        if all_bounds_right:
            x_min = min([b[0] for b in all_bounds_right])
            x_max = max([b[1] for b in all_bounds_right])
            y_min = min([b[2] for b in all_bounds_right])
            y_max = max([b[3] for b in all_bounds_right])
        else:
            x_min, x_max = np.min(scores_lowess[:, 0]), np.max(scores_lowess[:, 0])
            y_min, y_max = np.min(scores_lowess[:, 1]), np.max(scores_lowess[:, 1])
        
        data_x_min, data_x_max = np.min(scores_lowess[:, 0]), np.max(scores_lowess[:, 0])
        data_y_min, data_y_max = np.min(scores_lowess[:, 1]), np.max(scores_lowess[:, 1])
        
        x_min = min(x_min, data_x_min)
        x_max = max(x_max, data_x_max)
        y_min = min(y_min, data_y_min)
        y_max = max(y_max, data_y_max)
        
        x_margin = (x_max - x_min) * 0.2
        y_margin = (y_max - y_min) * 0.2
        
        ax_right.set_xlim(x_min - x_margin, x_max + x_margin)
        ax_right.set_ylim(y_min - y_margin, y_max + y_margin)
        
        ax_right.set_title(
            f'QC-LOWESS Normalized\n'
            f'PC1: {var_lowess[0]:.1%}, PC2: {var_lowess[1]:.1%}',
            fontsize=13, fontweight='bold', pad=10
        )
        ax_right.set_xlabel(f't[1] ({var_lowess[0]:.1%})', fontsize=12, fontweight='bold')
        ax_right.set_ylabel(f't[2] ({var_lowess[1]:.1%})', fontsize=12, fontweight='bold')
        ax_right.grid(True, alpha=0.3, linestyle='--')
        ax_right.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        ax_right.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
        
        # ===== 添加圖例（參考 Batch_effect 腳本）=====
        sample_legend_elements = [
            plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='#4169E1',
                      markersize=10, label='Control', markeredgecolor='black', markeredgewidth=1),
            plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='#DC143C',
                      markersize=10, label='Exposed', markeredgecolor='black', markeredgewidth=1),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#9370DB',
                      markersize=10, label='QC', markeredgecolor='black', markeredgewidth=1),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='gray',
                      markersize=10, label='QC Outlier (T² > threshold)', 
                      markeredgecolor='red', markeredgewidth=3)
        ]
        
        ellipse_legend_elements = [
            plt.Line2D([0], [0], linestyle='-', color='#9370DB',
                      linewidth=3, label='95% CI (QC Only)'),
            plt.Line2D([0], [0], linestyle='--', color='gray',
                      linewidth=3, label='95% CI (All Samples)')
        ]
        
        # 左圖圖例
        legend1_left = ax_left.legend(handles=sample_legend_elements, 
                                      loc='upper left', 
                                      fontsize=9,
                                      title='Sample Type', 
                                      title_fontsize=10,
                                      frameon=True, 
                                      fancybox=True, 
                                      shadow=True)
        
        ax_left.add_artist(legend1_left)
        
        legend2_left = ax_left.legend(handles=ellipse_legend_elements, 
                                      loc='upper right', 
                                      fontsize=9,
                                      title='Confidence Ellipse', 
                                      title_fontsize=10,
                                      frameon=True, 
                                      fancybox=True, 
                                      shadow=True)
        
        # 右圖圖例
        legend1_right = ax_right.legend(handles=sample_legend_elements, 
                                        loc='upper left', 
                                        fontsize=9,
                                        title='Sample Type', 
                                        title_fontsize=10,
                                        frameon=True, 
                                        fancybox=True, 
                                        shadow=True)
        
        ax_right.add_artist(legend1_right)
        
        legend2_right = ax_right.legend(handles=ellipse_legend_elements, 
                                        loc='upper right', 
                                        fontsize=9,
                                        title='Confidence Ellipse', 
                                        title_fontsize=10,
                                        frameon=True, 
                                        fancybox=True, 
                                        shadow=True)
        
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        
        # 保存圖表
        pca_plot_path = os.path.join(output_dir, f'2D_PCA_ISTD_vs_LOWESS_{timestamp}.png')
        plt.savefig(pca_plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"\n✓ 2D PCA 圖已儲存: {pca_plot_path}")
        
        # ===== 輸出異常值摘要 =====
        print(f"\n{'='*70}")
        print(f"📊 ISTD Correction - Hotelling T² 異常值檢測結果（基於 QC 群組內部）")
        print(f"{'='*70}")
        print(f"QC 異常值數量: {np.sum(outliers_istd)}/{len(outliers_istd)}")
        if np.sum(outliers_istd) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_istd)) if outliers_istd[i]]
            outlier_t2_values = [t2_istd[i] for i in range(len(outliers_istd)) if outliers_istd[i]]
            print(f"異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"  - {sample}: T² = {t2_val:.2f} (閾值 = {t2_threshold_istd:.2f})")
        else:
            print("  ✓ 無異常樣本")
        
        print(f"\n📊 QC-LOWESS Normalized - Hotelling T² 異常值檢測結果（基於 QC 群組內部）")
        print(f"{'='*70}")
        print(f"QC 異常值數量: {np.sum(outliers_lowess)}/{len(outliers_lowess)}")
        if np.sum(outliers_lowess) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_lowess)) if outliers_lowess[i]]
            outlier_t2_values = [t2_lowess[i] for i in range(len(outliers_lowess)) if outliers_lowess[i]]
            print(f"異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"  - {sample}: T² = {t2_val:.2f} (閾值 = {t2_threshold_lowess:.2f})")
        else:
            print("  ✓ 無異常樣本")
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"❌ PCA 分析失敗: {e}")
        import traceback
        traceback.print_exc()




# ========== 主程式 ==========
def main():
    """
    主程式：QC-LOWESS 正規化（簡化版，無批次處理）
    
    
    """
    print("="*70)
    print("🔬 QC-LOWESS 正規化分析")
    print("📚 參考文獻：Dunn et al. (2011) Nature Protocols")
    print("="*70)
    
    # 選擇輸入檔案
    root = tk.Tk()
    root.withdraw()
    
    print("\n📂 請選擇輸入檔案...")
    input_file = filedialog.askopenfilename(
        title="選擇 ISTD 校正後的 Excel 檔案",
        filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
    )
    
    if not input_file:
        print("❌ 未選擇檔案，程式結束")
        return
    
    print(f"✓ 已選擇檔案: {os.path.basename(input_file)}")
    
    # 載入數據
    print(f"\n{'='*70}")
    print("📥 載入數據...")
    print(f"{'='*70}")
    
    raw_df, istd_df, sample_info_df = load_and_process_data(input_file)
    
    if istd_df is None or sample_info_df is None:
        print("❌ 數據載入失敗")
        return
    
     # 執行 LOWESS 正規化
    print(f"\n{'='*70}")
    print("🔬 執行 LOWESS 正規化")
    print(f"{'='*70}")
    print("✓ 使用標準模式 (frac=0.75)")
    print("✓ 所有樣本視為單一批次")
    
    # ✅ 接收 qc_corrected_values
    lowess_df, sample_columns, qc_corrected_values = perform_lowess_normalization(
        istd_df, 
        sample_info_df
    )
    
    if lowess_df is None:
        print("❌ LOWESS 正規化失敗")
        return
    
    # 生成輸出檔名
    input_dir = os.path.dirname(input_file)
    input_basename = os.path.splitext(os.path.basename(input_file))[0]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    output_file = os.path.join(input_dir, f"QC_LOWESS_{timestamp}.xlsx")
    
     # 保存結果
    print(f"\n{'='*70}")
    print("💾 保存結果...")
    print(f"{'='*70}")
    
    # ✅ 傳遞 qc_corrected_values
    success = save_results_to_excel(
        raw_df, 
        istd_df, 
        lowess_df, 
        sample_info_df, 
        sample_columns, 
        output_file,
        input_file,
        qc_corrected_values  # ✅ 新增參數
    )
    
    
    if not success:
        print("❌ 結果保存失敗")
        return
    
    # 執行 PCA 分析
    print(f"\n{'='*70}")
    print("📊 執行 PCA 分析...")
    print(f"{'='*70}")
    
    perform_pca_analysis(istd_df, lowess_df, sample_columns, sample_info_df)
    
    # 最終摘要
    print(f"\n{'='*70}")
    print("✅ QC-LOWESS 正規化完成！")
    print(f"{'='*70}")
    print(f"\n📋 輸出檔案:")
    print(f"   - Excel: {output_file}")
    print(f"   - PCA 圖表: QC_LOWESS_plots/2D_PCA_ISTD_vs_LOWESS_{timestamp}.png")
    
    
    print(f"\n{'='*70}\n")


# ========== 程式入口 ==========
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  程式被使用者中斷")
    except Exception as e:
        print(f"\n\n❌ 程式執行時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\n按 Enter 鍵退出...")


