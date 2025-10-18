import pandas as pd
import numpy as np
import os
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import statsmodels.api as sm
from scipy.stats import ttest_rel, levene, shapiro, kendalltau
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
        return 1.0
    elif qc_count < 10:
        return 0.8
    elif qc_count < 15:
        return 0.75
    elif qc_count < 25:
        return 0.6
    else:
        return 0.5


# ========== ✅ 新增：趨勢顯著性檢驗 ==========
def validate_lowess_trend(qc_orders, qc_intensities, fitted_values):
    """
    驗證 LOWESS 是否捕捉到顯著趨勢
    
    參考文獻：
    - Mann (1945) Econometrica
    - Kendall (1975) Rank Correlation Methods
    
    Returns:
    --------
    dict with keys:
        - 'trend_pvalue': Mann-Kendall 趨勢檢驗 p 值
        - 'trend_tau': Kendall's tau 係數
        - 'r_squared': 擬合優度 R²
        - 'rmse': 均方根誤差
        - 'has_significant_trend': 是否有顯著趨勢
    """
    try:
        # 1. Mann-Kendall 趨勢檢驗
        tau, mk_pvalue = kendalltau(qc_orders, qc_intensities)
        
        # 2. 計算 R²
        ss_res = np.sum((qc_intensities - fitted_values) ** 2)
        ss_tot = np.sum((qc_intensities - np.mean(qc_intensities)) ** 2)
        
        if ss_tot == 0:
            r_squared = 0.0
        else:
            r_squared = 1 - (ss_res / ss_tot)
            r_squared = max(0, r_squared)  # R² 不應為負
        
        # 3. 計算 RMSE
        rmse = np.sqrt(np.mean((qc_intensities - fitted_values) ** 2))
        
        # 4. 判定是否有顯著趨勢
        has_significant_trend = mk_pvalue < 0.05
        
        return {
            'trend_pvalue': mk_pvalue,
            'trend_tau': tau,
            'r_squared': r_squared,
            'rmse': rmse,
            'has_significant_trend': has_significant_trend
        }
    
    except Exception as e:
        return {
            'trend_pvalue': np.nan,
            'trend_tau': np.nan,
            'r_squared': np.nan,
            'rmse': np.nan,
            'has_significant_trend': False,
            'error': str(e)
        }


# ========== 🔧 改進：LOWESS 校正（添加趨勢驗證）==========
def robust_lowess_correction_v6(qc_orders, qc_intensities, all_orders, all_intensities, feature_id):
    """
    改進的 LOWESS 校正（添加趨勢顯著性檢驗和擬合優度評估）
    
    ✅ 新增功能：
    1. Mann-Kendall 趨勢檢驗
    2. R² 擬合優度
    3. RMSE 計算
    """
    qc_orders = np.array(qc_orders)
    qc_intensities = np.array(qc_intensities)
    all_orders = np.array(all_orders)
    all_intensities = np.array(all_intensities)
    
    debug_mode = feature_id is not None
    
    if len(qc_orders) < 5:
        return all_intensities, {
            'status': 'insufficient_qc',
            'qc_count': len(qc_orders)
        }
    
    # 步驟 1：檢測離群值
    Q1 = np.percentile(qc_intensities, 25)
    Q3 = np.percentile(qc_intensities, 75)
    IQR = Q3 - Q1
    
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    
    outlier_mask = (qc_intensities < lower_bound) | (qc_intensities > upper_bound)
    outliers_removed = np.sum(outlier_mask)
    
    qc_orders_clean = qc_orders[~outlier_mask]
    qc_intensities_clean = qc_intensities[~outlier_mask]
    
    if len(qc_orders_clean) < max(5, len(qc_orders) * 0.7):
        qc_orders_clean = qc_orders
        qc_intensities_clean = qc_intensities
        outliers_removed = 0
    
    # 步驟 2：動態選擇 frac
    n_qc = len(qc_orders_clean)
    
    if n_qc < 8:
        best_frac = 1.0
    elif n_qc < 12:
        best_frac = 0.8
    elif n_qc < 20:
        best_frac = 0.6
    else:
        best_frac = 0.4
    
    try:
        # 步驟 3：LOWESS 擬合
        lowess_result = sm.nonparametric.lowess(
            qc_intensities_clean,
            qc_orders_clean,
            frac=best_frac,
            it=3,
            delta=0.0,
            return_sorted=True
        )
        
        fitted_values = lowess_result[:, 1]
        
        # ✅ 步驟 4：趨勢顯著性檢驗
        trend_validation = validate_lowess_trend(
            qc_orders_clean, 
            qc_intensities_clean, 
            fitted_values
        )
        
        if debug_mode:
            print(f"\n🔍 調試特徵: {feature_id}")
            print(f"   QC 樣本數: {n_qc}")
            print(f"   使用 frac: {best_frac}")
            print(f"\n   📊 趨勢顯著性檢驗:")
            print(f"     Mann-Kendall p-value: {trend_validation['trend_pvalue']:.4f}")
            print(f"     Kendall's tau: {trend_validation['trend_tau']:.4f}")
            print(f"     R²: {trend_validation['r_squared']:.4f}")
            print(f"     RMSE: {trend_validation['rmse']:.2e}")
            print(f"     顯著趨勢: {'是' if trend_validation['has_significant_trend'] else '否'}")
        
        # 步驟 5：檢查趨勢是否過於平坦
        trend_std = np.std(lowess_result[:, 1])
        trend_mean = np.mean(lowess_result[:, 1])
        
        # ✅ 如果沒有顯著趨勢且 R² 很低，考慮不校正
        if not trend_validation['has_significant_trend'] and trend_validation['r_squared'] < 0.1:
            if debug_mode:
                print(f"   ⚠️  無顯著趨勢且擬合優度低，考慮不校正")
            
            return all_intensities, {
                'status': 'no_significant_trend',
                'original_cv': np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100,
                'corrected_cv': np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100,
                'median_correction_factor': 1.0,
                'trend_validation': trend_validation
            }
        
        # 步驟 6：計算參考水平
        qc_reference = np.median(qc_intensities_clean)
        
        # 步驟 7：插值
        predicted_trends = np.interp(
            all_orders, 
            lowess_result[:, 0],
            lowess_result[:, 1]
        )
        
        # 步驟 8：計算校正因子
        predicted_trends = np.where(predicted_trends == 0, qc_reference, predicted_trends)
        correction_factors = qc_reference / predicted_trends
        correction_factors = np.clip(correction_factors, 0.5, 2.0)
        
        # 步驟 9：應用校正
        corrected_intensities = all_intensities * correction_factors
        
        # 步驟 10：計算校正效果
        qc_indices = [i for i, order in enumerate(all_orders) if order in qc_orders]
        
        if len(qc_indices) >= 2:
            qc_corrected = corrected_intensities[qc_indices]
            original_cv = np.std(qc_intensities, ddof=1) / np.mean(qc_intensities) * 100
            corrected_cv = np.std(qc_corrected, ddof=1) / np.mean(qc_corrected) * 100
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
            'correction_factor_std': np.std(correction_factors),
            'trend_validation': trend_validation  # ✅ 添加趨勢驗證結果
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
    """從 DataFrame 的一行中提取有效值（>0 且非 NaN）"""
    values = []
    for col in columns:
        if col in row.index:
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


# ========== LOWESS 正規化 ==========
def perform_lowess_normalization(istd_df, sample_info_df):
    """簡化的 LOWESS 正規化（所有樣本視為單一批次）"""
    try:
        exclude_cols = ['FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference', 
                       'ISTD_Median', 'QC_CV%']
        sample_columns = [col for col in istd_df.columns if col not in exclude_cols]
        
        if 'Sample_Type' in sample_info_df.columns:
            qc_samples = sample_info_df[
                sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)
            ]['Sample_Name'].tolist()
        else:
            qc_samples = [col for col in sample_columns if 'QC' in col.upper()]
        
        qc_samples = [s for s in qc_samples if s in sample_columns]
        
        if len(qc_samples) < 5:
            print(f"❌ QC 樣本不足 ({len(qc_samples)} < 5)，無法進行校正")
            return None, None, None
        
        print(f"\n📊 數據概覽:")
        print(f"  - 總樣本數: {len(sample_columns)}")
        print(f"  - QC 樣本數: {len(qc_samples)}")
        print(f"  - 特徵數: {len(istd_df)}")
        
        sample_meta = sample_info_df.set_index('Sample_Name')
        
        all_samples = sample_columns
        all_qc = qc_samples
        
        print(f"\n📦 處理所有樣本")
        print(f"  - 樣本數: {len(all_samples)} (QC: {len(all_qc)})")
        
        injection_orders = {}
        for col in all_samples:
            if col in sample_meta.index:
                injection_orders[col] = sample_meta.loc[col, 'Injection_Order']
        
        # 計算特徵 CV% 並選擇調試樣本
        print(f"\n🔍 計算特徵 CV% 以選擇調試樣本...")
        
        feature_cvs = []
        for idx, row in istd_df.iterrows():
            feature_id = row['FeatureID']
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
            import random
            debug_features = [f[0] for f in random.sample(feature_cvs, min(len(feature_cvs), 3))]
        else:
            feature_cvs_sorted = sorted(feature_cvs, key=lambda x: x[1])
            low_cv_feature = feature_cvs_sorted[0]
            mid_cv_feature = feature_cvs_sorted[len(feature_cvs_sorted) // 2]
            high_cv_feature = feature_cvs_sorted[-1]
            debug_features = [low_cv_feature[0], mid_cv_feature[0], high_cv_feature[0]]
            
            print(f"\n🔍 選擇以下特徵進行詳細調試（按 CV% 低→中→高）:")
            print(f"   1. 低 CV%: {low_cv_feature[0]} (CV% = {low_cv_feature[1]:.2f}%)")
            print(f"   2. 中 CV%: {mid_cv_feature[0]} (CV% = {mid_cv_feature[1]:.2f}%)")
            print(f"   3. 高 CV%: {high_cv_feature[0]} (CV% = {high_cv_feature[1]:.2f}%)")
        
        all_results = []
        correction_stats = []
        qc_corrected_values = {}
        
        corrected_count = 0
        failed_count = 0
        
        for idx, row in istd_df.iterrows():
            feature_id = row['FeatureID']
            
            qc_data = []
            for qc_sample in qc_samples:
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
                
                qc_corrected_dict = {}
                for qc in qc_samples:
                    if qc in row.index:
                        qc_corrected_dict[qc] = row[qc]
                qc_corrected_values[feature_id] = qc_corrected_dict
                continue
            
            qc_orders, qc_intensities = zip(*sorted(qc_data))
            
            all_data = []
            for sample in all_samples:
                if sample in injection_orders:
                    order = injection_orders[sample]
                    intensity = row[sample]
                    all_data.append((sample, order, intensity if not pd.isna(intensity) else 0))
            
            all_sample_names, all_orders, all_intensities = zip(*all_data)
            
            # ✅ 使用改進的 LOWESS 校正
            corrected_intensities, info = robust_lowess_correction_v6(
                qc_orders, qc_intensities, all_orders, all_intensities, 
                feature_id if feature_id in debug_features else None
            )
            
            if info['status'] == 'success':
                corrected_count += 1
                correction_stats.append(info)
            else:
                failed_count += 1
            
            result_row = {'FeatureID': feature_id}
            for sample, corrected_val in zip(all_sample_names, corrected_intensities):
                result_row[sample] = corrected_val
            all_results.append(result_row)
            
            qc_corrected_dict = {}
            for sample, corrected_val in zip(all_sample_names, corrected_intensities):
                if sample in qc_samples:
                    qc_corrected_dict[sample] = corrected_val
            qc_corrected_values[feature_id] = qc_corrected_dict
            
            if (idx + 1) % 500 == 0:
                print(f"  進度: {idx + 1}/{len(istd_df)} features")
        
        print(f"  ✓ 完成: {corrected_count} 成功, {failed_count} 失敗")
        
        lowess_df = pd.DataFrame(all_results)
        
        return lowess_df, sample_columns, qc_corrected_values
        
    except Exception as e:
        print(f"❌ LOWESS 校正失敗: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None


# ========== ✅ 修正：統計檢定（配對 t 檢定 + Levene's test）==========
def calculate_qc_cv_with_statistical_test(istd_df, lowess_df, sample_columns, sample_info_df, qc_corrected_values):
    """
    計算 QC CV% 並進行正確的統計檢定
    
    ✅ 修正：
    1. 使用配對 t 檢定檢驗均值變化
    2. 使用 Levene's test 檢驗方差變化
    3. CV% 僅作為描述性統計
    
    參考文獻：
    - Dunn et al. (2011) Nature Protocols
    - van den Berg et al. (2006) BMC Genomics
    """
    istd_df = istd_df.reset_index(drop=True)
    lowess_df = lowess_df.reset_index(drop=True)
    
    min_length = min(len(istd_df), len(lowess_df))
    istd_df = istd_df.iloc[:min_length]
    lowess_df = lowess_df.iloc[:min_length]
    
    print(f"\n{'='*70}")
    print(f"🔬 識別 QC 樣本")
    print(f"{'='*70}")
    
    if 'Sample_Type' in sample_info_df.columns:
        qc_samples = sample_info_df[
            sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)
        ]['Sample_Name'].tolist()
    else:
        qc_samples = [col for col in sample_columns if 'QC' in col.upper()]
    
    qc_columns = [col for col in qc_samples if col in sample_columns]
    print(f"  - QC 樣本數: {len(qc_columns)}")
    
    if len(qc_columns) == 0:
        print(f"  ❌ 錯誤：未找到任何 QC 樣本！")
        return pd.DataFrame()
    
    cv_results = []
    
    print(f"\n🔬 開始統計檢定（配對 t 檢定 + Levene's test）...")
    print(f"  - 特徵總數: {len(istd_df)}")
    
    for idx in range(len(istd_df)):
        try:
            istd_row = istd_df.iloc[idx]
            lowess_row = lowess_df.iloc[idx]
            feature_id = istd_row['FeatureID']
            
            # 提取 QC 原始強度值
            qc_values_istd = get_valid_values(istd_row, qc_columns)
            
            # 提取 QC 校正後強度值
            if feature_id in qc_corrected_values:
                qc_corrected_dict = qc_corrected_values[feature_id]
                qc_values_lowess = []
                for qc in qc_columns:
                    if qc in qc_corrected_dict:
                        val = qc_corrected_dict[qc]
                        if not pd.isna(val) and val > 0:
                            qc_values_lowess.append(val)
            else:
                qc_values_lowess = get_valid_values(lowess_row, qc_columns)
            
            # 確保數據長度一致
            min_len = min(len(qc_values_istd), len(qc_values_lowess))
            if min_len < 3:
                cv_results.append({
                    'FeatureID': feature_id,
                    'Original_QC_CV%': np.nan,
                    'Corrected_QC_CV%': np.nan,
                    'CV_Improvement%': np.nan,
                    'Mean_Shift_pvalue': np.nan,
                    'Variance_Test_pvalue': np.nan,
                    'Normality_pvalue': np.nan,
                    'Significant_Improvement': 'N/A'
                })
                continue
            
            qc_values_istd = np.array(qc_values_istd[:min_len])
            qc_values_lowess = np.array(qc_values_lowess[:min_len])
            
            # 1. 計算 CV%（描述性統計）
            original_cv = (np.std(qc_values_istd, ddof=1) / np.mean(qc_values_istd)) * 100
            corrected_cv = (np.std(qc_values_lowess, ddof=1) / np.mean(qc_values_lowess)) * 100
            cv_improvement = original_cv - corrected_cv
            
            # 2. 配對 t 檢定（檢驗均值是否改變）
            try:
                t_stat, mean_shift_pvalue = ttest_rel(qc_values_istd, qc_values_lowess)
            except Exception:
                mean_shift_pvalue = np.nan
            
            # 3. Levene's test（檢驗方差是否改變）
            try:
                levene_stat, variance_test_pvalue = levene(qc_values_istd, qc_values_lowess)
            except Exception:
                variance_test_pvalue = np.nan
            
            # 4. Shapiro-Wilk 正態性檢驗
            try:
                shapiro_stat, normality_pvalue = shapiro(qc_values_istd)
            except Exception:
                normality_pvalue = np.nan
            
            # 5. 判定顯著改善
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
                'Mean_Shift_pvalue': mean_shift_pvalue,
                'Variance_Test_pvalue': variance_test_pvalue,
                'Normality_pvalue': normality_pvalue,
                'Significant_Improvement': significant
            })
            
            if (idx + 1) % 100 == 0:
                print(f"  處理進度: {idx + 1}/{len(istd_df)} features")
        
        except Exception as e:
            print(f"  ⚠️ 處理特徵 {idx} 時發生錯誤: {e}")
            continue
    
    print(f"  ✓ 統計檢定完成！")
    
    return pd.DataFrame(cv_results)


# ========== ✅ 新增：P 值分佈圖 ==========
def plot_pvalue_distribution(cv_results_df, output_dir, timestamp):
    """
    繪製 p 值分佈圖
    
    參考文獻：
    - Broadhurst & Kell (2006) Metabolomics
    - Storey & Tibshirani (2003) PNAS
    """
    try:
        # 提取有效的 p 值
        variance_pvalues = cv_results_df['Variance_Test_pvalue'].dropna()
        
        if len(variance_pvalues) < 10:
            print("  ⚠️ 有效 p 值數量不足，跳過 p 值分佈圖")
            return
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # 直方圖
        ax1.hist(variance_pvalues, bins=20, color='steelblue', edgecolor='black', alpha=0.7)
        ax1.axhline(y=len(variance_pvalues)/20, color='red', linestyle='--', linewidth=2,
                   label='Uniform Distribution Expected')
        ax1.set_xlabel('P-value (Levene\'s Test)', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Frequency', fontsize=12, fontweight='bold')
        ax1.set_title('P-value Distribution\n(Variance Homogeneity Test)', 
                     fontsize=14, fontweight='bold')
        ax1.legend(fontsize=10)
        ax1.grid(True, alpha=0.3, linestyle='--')
        
        # Q-Q plot
        from scipy.stats import probplot
        probplot(variance_pvalues, dist="uniform", plot=ax2)
        ax2.set_title('Q-Q Plot (Uniform Distribution)', fontsize=14, fontweight='bold')
        ax2.set_xlabel('Theoretical Quantiles', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Sample Quantiles', fontsize=12, fontweight='bold')
        ax2.grid(True, alpha=0.3, linestyle='--')
        
        # 添加統計信息
        from scipy.stats import kstest
        ks_stat, ks_pvalue = kstest(variance_pvalues, 'uniform')
        
        textstr = f'Kolmogorov-Smirnov Test:\n'
        textstr += f'Statistic = {ks_stat:.4f}\n'
        textstr += f'P-value = {ks_pvalue:.4f}\n'
        if ks_pvalue > 0.05:
            textstr += 'Result: Uniform ✓'
        else:
            textstr += 'Result: Non-uniform ✗'
        
        ax1.text(0.98, 0.97, textstr, transform=ax1.transAxes,
                fontsize=10, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        plt.tight_layout()
        
        # 保存圖表
        pvalue_plot_path = os.path.join(output_dir, f'Pvalue_Distribution_{timestamp}.png')
        plt.savefig(pvalue_plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n✓ P 值分佈圖已儲存: {pvalue_plot_path}")
        print(f"  - Kolmogorov-Smirnov 檢定: KS={ks_stat:.4f}, p={ks_pvalue:.4f}")
        if ks_pvalue > 0.05:
            print(f"  - 結論: p 值分佈接近均勻分佈 ✓")
        else:
            print(f"  - 結論: p 值分佈偏離均勻分佈 ✗")
        
    except Exception as e:
        print(f"  ⚠️ 繪製 p 值分佈圖時發生錯誤: {e}")
        import traceback
        traceback.print_exc()


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


# ========== ✅ 修正：保存結果到 Excel ==========
def save_results_to_excel(raw_df, istd_df, lowess_df, sample_info_df, sample_columns, output_file, input_file, qc_corrected_values):
    try:
        # ✅ 使用修正後的統計檢定
        cv_results_df = calculate_qc_cv_with_statistical_test(
            istd_df, 
            lowess_df, 
            sample_columns, 
            sample_info_df, 
            qc_corrected_values
        )
        
        lowess_with_cv = lowess_df.merge(cv_results_df, on='FeatureID', how='left')
        
        # ✅ 修正：調整欄位順序（使用新的欄位名稱）
        cols_order = [
            'Original_QC_CV%', 
            'Corrected_QC_CV%', 
            'CV_Improvement%',
            'Mean_Shift_pvalue', 
            'Variance_Test_pvalue', 
            'Normality_pvalue',
            'Significant_Improvement'
        ]
        other_cols = [col for col in lowess_with_cv.columns if col not in cols_order]
        lowess_with_cv = lowess_with_cv[other_cols + cols_order]
        
        # 載入原始檔案
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

        # ✅ 修正：顏色標記（使用新的欄位名稱）
        orange_fill = PatternFill(start_color='FFA500', end_color='FFA500', fill_type='solid')
        green_fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
        yellow_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
        light_blue_fill = PatternFill(start_color='ADD8E6', end_color='ADD8E6', fill_type='solid')
        light_purple_fill = PatternFill(start_color='E6E6FA', end_color='E6E6FA', fill_type='solid')

        if 'QC LOWESS result' in workbook.sheetnames:
            worksheet = workbook['QC LOWESS result']
            header = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            
            # CV% 欄位 - 橙色
            for col_name in ['Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%']:
                if col_name in header:
                    col_idx = header.index(col_name) + 1
                    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                        for cell in row:
                            cell.fill = orange_fill
            
            # 統計檢定欄位 - 淺藍色
            for col_name in ['Mean_Shift_pvalue', 'Variance_Test_pvalue']:
                if col_name in header:
                    col_idx = header.index(col_name) + 1
                    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                        for cell in row:
                            cell.fill = light_blue_fill
            
            # 正態性檢驗 - 淺紫色
            if 'Normality_pvalue' in header:
                col_idx = header.index('Normality_pvalue') + 1
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                    for cell in row:
                        cell.fill = light_purple_fill
            
            # Significant_Improvement 欄位 - 綠色/黃色
            if 'Significant_Improvement' in header:
                col_idx = header.index('Significant_Improvement') + 1
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                    for cell in row:
                        if cell.value == 'Yes' or cell.value == 'Yes (CV% only)':
                            cell.fill = green_fill
                        elif cell.value == 'Marginal':
                            cell.fill = yellow_fill
                        elif cell.value == 'No':
                            cell.fill = PatternFill(start_color='FFB6C1', end_color='FFB6C1', fill_type='solid')

        # 保存最終檔案
        workbook.save(output_file)
        workbook.close()
        
        # ✅ 統計報告（使用新的欄位名稱）
        print(f"\n{'='*70}")
        print(f"✓ QC LOWESS 結果已保存:")
        print(f"  {output_file}")
        print(f"{'='*70}")
        
        # 統計顯著性結果
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
        
        # 配對 t 檢定統計
        mean_shift_valid = cv_results_df['Mean_Shift_pvalue'].notna().sum()
        mean_shift_sig = ((cv_results_df['Mean_Shift_pvalue'] < 0.05) & (cv_results_df['Mean_Shift_pvalue'].notna())).sum()
        
        print(f"\n🔬 配對 t 檢定（均值變化）:")
        print(f"  - 成功執行: {mean_shift_valid}/{total_count} ({mean_shift_valid/total_count*100:.1f}%)")
        if mean_shift_valid > 0:
            print(f"  - 均值顯著改變 (p < 0.05): {mean_shift_sig}/{mean_shift_valid} ({mean_shift_sig/mean_shift_valid*100:.1f}%)")
            print(f"  - 均值無顯著改變: {mean_shift_valid - mean_shift_sig}/{mean_shift_valid} ({(mean_shift_valid-mean_shift_sig)/mean_shift_valid*100:.1f}%)")
        
        # Levene's test 統計
        variance_valid = cv_results_df['Variance_Test_pvalue'].notna().sum()
        variance_sig = ((cv_results_df['Variance_Test_pvalue'] < 0.05) & (cv_results_df['Variance_Test_pvalue'].notna())).sum()
        
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
        
        # ✅ 繪製 p 值分佈圖
        output_dir = os.path.dirname(output_file)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        plot_pvalue_distribution(cv_results_df, output_dir, timestamp)
        
        return True

    except Exception as e:
        print(f"❌ 儲存 Excel 時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False


# ========== Hotelling T² 異常值檢測 ==========
def calculate_hotelling_t2_outliers(qc_scores, all_scores=None, alpha=0.05):
    """
    使用 Hotelling T² 檢測 QC 樣本中的異常值
    
    ✅ 正確邏輯：計算每個 QC 樣本與 QC 群組中心的偏離
    """
    n_qc, p = qc_scores.shape
    
    if n_qc < 3:
        print(f"   ⚠️ QC 樣本數不足 ({n_qc} < 3)，無法進行異常值檢測")
        return np.zeros(n_qc), 0, np.zeros(n_qc, dtype=bool)
    
    qc_mean = np.mean(qc_scores, axis=0)
    qc_cov = np.cov(qc_scores, rowvar=False)
    
    qc_cov_reg = qc_cov + np.eye(p) * 1e-6
    
    try:
        qc_cov_inv = np.linalg.inv(qc_cov_reg)
    except np.linalg.LinAlgError:
        print("   ⚠️ 警告：QC 協方差矩陣奇異，使用偽逆矩陣")
        qc_cov_inv = np.linalg.pinv(qc_cov_reg)
    
    t2_values = np.zeros(n_qc)
    for i in range(n_qc):
        diff = qc_scores[i] - qc_mean
        t2_values[i] = np.dot(np.dot(diff, qc_cov_inv), diff.T)
    
    if n_qc - p - 1 > 0:
        f_critical = stats.f.ppf(1 - alpha, p, n_qc - p - 1)
        threshold = (p * (n_qc + 1) * (n_qc - 1)) / (n_qc * (n_qc - p - 1)) * f_critical
    else:
        threshold = chi2.ppf(1 - alpha, p)
    
    outliers = t2_values > threshold
    
    return t2_values, threshold, outliers


# ========== Hotelling T² 橢圓繪製 ==========
def draw_hotelling_t2_ellipse(ax, scores, alpha=0.05, label=None, edgecolor='black', linestyle='-', linewidth=2.5):
    """在 2D PCA 圖上繪製 Hotelling T² 橢圓"""
    n, p = scores.shape
    
    if n < 3:
        print(f"   ⚠️ 樣本數不足 ({n} < 3)，無法繪製 Hotelling T² 橢圓")
        return None
    
    mean = np.mean(scores, axis=0)
    cov = np.cov(scores, rowvar=False)
    
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    
    idx = eigenvalues.argsort()[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    
    eigenvalues = np.maximum(eigenvalues, 1e-10)
    
    f_critical = stats.f.ppf(1 - alpha, p, n - p)
    scale_factor = np.sqrt((p * (n - 1) * (n + 1)) / (n * (n - p)) * f_critical)
    
    width = 2 * scale_factor * np.sqrt(eigenvalues[0])
    height = 2 * scale_factor * np.sqrt(eigenvalues[1])
    
    angle = np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
    
    ellipse = Ellipse(mean, width, height, angle=angle,
                     facecolor='none', edgecolor=edgecolor,
                     linewidth=linewidth, linestyle=linestyle, label=label)
    ax.add_patch(ellipse)
    
    t = np.linspace(0, 2*np.pi, 100)
    ellipse_x = (width/2) * np.cos(t)
    ellipse_y = (height/2) * np.sin(t)
    
    cos_angle = np.cos(np.radians(angle))
    sin_angle = np.sin(np.radians(angle))
    x_rot = ellipse_x * cos_angle - ellipse_y * sin_angle + mean[0]
    y_rot = ellipse_x * sin_angle + ellipse_y * cos_angle + mean[1]
    
    bounds = (np.min(x_rot), np.max(x_rot), np.min(y_rot), np.max(y_rot))
    
    return bounds


# ========== PCA 分析（續）==========
def perform_pca_analysis(istd_df, lowess_df, sample_columns, sample_info_df):
    """完整的 PCA 分析"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, "QC_LOWESS_plots")
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        sample_meta = sample_info_df.set_index('Sample_Name')

        sample_columns_clean = [col for col in sample_columns if col in istd_df.columns and col in lowess_df.columns]
        
        if len(sample_columns_clean) < 3:
            print("   ⚠️ 樣本數量不足，無法進行 PCA 分析")
            return
        
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
        
        print(f"\n📊 樣本分類:")
        print(f"  - QC 樣本: {len(qc_columns)}")
        print(f"  - Control 樣本: {len(control_columns)}")
        print(f"  - Exposed 樣本: {len(exposed_columns)}")
        
        if len(qc_columns) < 3:
            print("   ⚠️ QC 樣本數不足 (<3)，無法進行 Hotelling T² 分析")
            return
        
        # 準備數據（ISTD 校正後）
        istd_data = istd_df[sample_columns_clean].T
        istd_data = istd_data.fillna(0)
        istd_data = istd_data.replace([np.inf, -np.inf], 0)
        
        # 準備數據（LOWESS 校正後）
        lowess_data = lowess_df[sample_columns_clean].T
        lowess_data = lowess_data.fillna(0)
        lowess_data = lowess_data.replace([np.inf, -np.inf], 0)
        
        # 標準化
        scaler_istd = StandardScaler()
        istd_scaled = scaler_istd.fit_transform(istd_data)
        
        scaler_lowess = StandardScaler()
        lowess_scaled = scaler_lowess.fit_transform(lowess_data)
        
        # PCA
        pca_istd = PCA(n_components=min(10, len(sample_columns_clean), istd_scaled.shape[1]))
        pca_lowess = PCA(n_components=min(10, len(sample_columns_clean), lowess_scaled.shape[1]))
        
        istd_scores = pca_istd.fit_transform(istd_scaled)
        lowess_scores = pca_lowess.fit_transform(lowess_scaled)
        
        # 提取 PC1 和 PC2
        istd_pc1_pc2 = istd_scores[:, :2]
        lowess_pc1_pc2 = lowess_scores[:, :2]
        
        # 計算 Hotelling T² (僅針對 QC 樣本)
        qc_indices = [sample_columns_clean.index(qc) for qc in qc_columns]
        
        istd_qc_scores = istd_pc1_pc2[qc_indices]
        lowess_qc_scores = lowess_pc1_pc2[qc_indices]
        
        print(f"\n🔬 Hotelling T² 異常值檢測 (QC 樣本):")
        
        # ISTD 校正後的 Hotelling T²
        istd_t2, istd_threshold, istd_outliers = calculate_hotelling_t2_outliers(istd_qc_scores)
        istd_outlier_count = np.sum(istd_outliers)
        
        print(f"\n  ISTD 校正後:")
        print(f"    - QC 樣本數: {len(qc_columns)}")
        print(f"    - Hotelling T² 閾值: {istd_threshold:.2f}")
        print(f"    - 異常值數量: {istd_outlier_count}/{len(qc_columns)} ({istd_outlier_count/len(qc_columns)*100:.1f}%)")
        
        if istd_outlier_count > 0:
            outlier_names = [qc_columns[i] for i in range(len(qc_columns)) if istd_outliers[i]]
            print(f"    - 異常樣本: {', '.join(outlier_names)}")
        
        # LOWESS 校正後的 Hotelling T²
        lowess_t2, lowess_threshold, lowess_outliers = calculate_hotelling_t2_outliers(lowess_qc_scores)
        lowess_outlier_count = np.sum(lowess_outliers)
        
        print(f"\n  LOWESS 校正後:")
        print(f"    - QC 樣本數: {len(qc_columns)}")
        print(f"    - Hotelling T² 閾值: {lowess_threshold:.2f}")
        print(f"    - 異常值數量: {lowess_outlier_count}/{len(qc_columns)} ({lowess_outlier_count/len(qc_columns)*100:.1f}%)")
        
        if lowess_outlier_count > 0:
            outlier_names = [qc_columns[i] for i in range(len(qc_columns)) if lowess_outliers[i]]
            print(f"    - 異常樣本: {', '.join(outlier_names)}")
        
        # 計算改善效果
        improvement = istd_outlier_count - lowess_outlier_count
        if improvement > 0:
            print(f"\n  ✓ 異常值減少: {improvement} 個 ({improvement/len(qc_columns)*100:.1f}%)")
        elif improvement < 0:
            print(f"\n  ⚠️ 異常值增加: {abs(improvement)} 個")
        else:
            print(f"\n  - 異常值數量無變化")
        
        # ========== 繪製 PCA 圖 ==========
        fig, axes = plt.subplots(1, 2, figsize=(20, 8))
        
        # 左圖：ISTD 校正後
        ax1 = axes[0]
        
        # 繪製樣本點
        if len(control_columns) > 0:
            control_indices = [sample_columns_clean.index(s) for s in control_columns]
            ax1.scatter(istd_pc1_pc2[control_indices, 0], istd_pc1_pc2[control_indices, 1],
                       c='blue', s=100, alpha=0.6, edgecolors='black', linewidth=1.5, label='Control')
        
        if len(exposed_columns) > 0:
            exposed_indices = [sample_columns_clean.index(s) for s in exposed_columns]
            ax1.scatter(istd_pc1_pc2[exposed_indices, 0], istd_pc1_pc2[exposed_indices, 1],
                       c='red', s=100, alpha=0.6, edgecolors='black', linewidth=1.5, label='Exposed')
        
        # 繪製 QC 樣本（正常 vs 異常）
        qc_normal_indices = [i for i in range(len(qc_columns)) if not istd_outliers[i]]
        qc_outlier_indices = [i for i in range(len(qc_columns)) if istd_outliers[i]]
        
        if len(qc_normal_indices) > 0:
            ax1.scatter(istd_qc_scores[qc_normal_indices, 0], istd_qc_scores[qc_normal_indices, 1],
                       c='green', s=150, alpha=0.8, edgecolors='black', linewidth=2, 
                       marker='D', label=f'QC (Normal, n={len(qc_normal_indices)})')
        
        if len(qc_outlier_indices) > 0:
            ax1.scatter(istd_qc_scores[qc_outlier_indices, 0], istd_qc_scores[qc_outlier_indices, 1],
                       c='orange', s=200, alpha=0.9, edgecolors='red', linewidth=3, 
                       marker='X', label=f'QC (Outlier, n={len(qc_outlier_indices)})')
        
        # 繪製 Hotelling T² 橢圓（僅針對 QC）
        draw_hotelling_t2_ellipse(ax1, istd_qc_scores, alpha=0.05, 
                                 label='Hotelling T² (95% CI)', 
                                 edgecolor='darkgreen', linestyle='--', linewidth=2.5)
        
        ax1.set_xlabel(f'PC1 ({pca_istd.explained_variance_ratio_[0]*100:.1f}%)', 
                      fontsize=14, fontweight='bold')
        ax1.set_ylabel(f'PC2 ({pca_istd.explained_variance_ratio_[1]*100:.1f}%)', 
                      fontsize=14, fontweight='bold')
        ax1.set_title('PCA Score Plot - ISTD Corrected\n(Hotelling T² for QC samples only)', 
                     fontsize=16, fontweight='bold')
        ax1.legend(loc='best', fontsize=11, framealpha=0.9)
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.axhline(0, color='gray', linewidth=0.8, linestyle='-', alpha=0.5)
        ax1.axvline(0, color='gray', linewidth=0.8, linestyle='-', alpha=0.5)
        
        # 右圖：LOWESS 校正後
        ax2 = axes[1]
        
        # 繪製樣本點
        if len(control_columns) > 0:
            ax2.scatter(lowess_pc1_pc2[control_indices, 0], lowess_pc1_pc2[control_indices, 1],
                       c='blue', s=100, alpha=0.6, edgecolors='black', linewidth=1.5, label='Control')
        
        if len(exposed_columns) > 0:
            ax2.scatter(lowess_pc1_pc2[exposed_indices, 0], lowess_pc1_pc2[exposed_indices, 1],
                       c='red', s=100, alpha=0.6, edgecolors='black', linewidth=1.5, label='Exposed')
        
        # 繪製 QC 樣本（正常 vs 異常）
        qc_normal_indices_lowess = [i for i in range(len(qc_columns)) if not lowess_outliers[i]]
        qc_outlier_indices_lowess = [i for i in range(len(qc_columns)) if lowess_outliers[i]]
        
        if len(qc_normal_indices_lowess) > 0:
            ax2.scatter(lowess_qc_scores[qc_normal_indices_lowess, 0], 
                       lowess_qc_scores[qc_normal_indices_lowess, 1],
                       c='green', s=150, alpha=0.8, edgecolors='black', linewidth=2, 
                       marker='D', label=f'QC (Normal, n={len(qc_normal_indices_lowess)})')
        
        if len(qc_outlier_indices_lowess) > 0:
            ax2.scatter(lowess_qc_scores[qc_outlier_indices_lowess, 0], 
                       lowess_qc_scores[qc_outlier_indices_lowess, 1],
                       c='orange', s=200, alpha=0.9, edgecolors='red', linewidth=3, 
                       marker='X', label=f'QC (Outlier, n={len(qc_outlier_indices_lowess)})')
        
        # 繪製 Hotelling T² 橢圓（僅針對 QC）
        draw_hotelling_t2_ellipse(ax2, lowess_qc_scores, alpha=0.05, 
                                 label='Hotelling T² (95% CI)', 
                                 edgecolor='darkgreen', linestyle='--', linewidth=2.5)
        
        ax2.set_xlabel(f'PC1 ({pca_lowess.explained_variance_ratio_[0]*100:.1f}%)', 
                      fontsize=14, fontweight='bold')
        ax2.set_ylabel(f'PC2 ({pca_lowess.explained_variance_ratio_[1]*100:.1f}%)', 
                      fontsize=14, fontweight='bold')
        ax2.set_title('PCA Score Plot - QC LOWESS Corrected\n(Hotelling T² for QC samples only)', 
                     fontsize=16, fontweight='bold')
        ax2.legend(loc='best', fontsize=11, framealpha=0.9)
        ax2.grid(True, alpha=0.3, linestyle='--')
        ax2.axhline(0, color='gray', linewidth=0.8, linestyle='-', alpha=0.5)
        ax2.axvline(0, color='gray', linewidth=0.8, linestyle='-', alpha=0.5)
        
        plt.tight_layout()
        
        # 保存圖表
        pca_plot_path = os.path.join(output_dir, f'PCA_Comparison_{timestamp}.png')
        plt.savefig(pca_plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n✓ PCA 圖已儲存: {pca_plot_path}")
        
        # ========== 繪製 Scree Plot ==========
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        
        # ISTD Scree Plot
        ax1 = axes[0]
        n_components_istd = len(pca_istd.explained_variance_ratio_)
        ax1.bar(range(1, n_components_istd + 1), pca_istd.explained_variance_ratio_ * 100,
               color='steelblue', alpha=0.7, edgecolor='black')
        ax1.plot(range(1, n_components_istd + 1), 
                np.cumsum(pca_istd.explained_variance_ratio_) * 100,
                'ro-', linewidth=2, markersize=8, label='Cumulative')
        ax1.set_xlabel('Principal Component', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Explained Variance (%)', fontsize=12, fontweight='bold')
        ax1.set_title('Scree Plot - ISTD Corrected', fontsize=14, fontweight='bold')
        ax1.legend(fontsize=10)
        ax1.grid(True, alpha=0.3, linestyle='--')
        
        # LOWESS Scree Plot
        ax2 = axes[1]
        n_components_lowess = len(pca_lowess.explained_variance_ratio_)
        ax2.bar(range(1, n_components_lowess + 1), pca_lowess.explained_variance_ratio_ * 100,
               color='coral', alpha=0.7, edgecolor='black')
        ax2.plot(range(1, n_components_lowess + 1), 
                np.cumsum(pca_lowess.explained_variance_ratio_) * 100,
                'ro-', linewidth=2, markersize=8, label='Cumulative')
        ax2.set_xlabel('Principal Component', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Explained Variance (%)', fontsize=12, fontweight='bold')
        ax2.set_title('Scree Plot - QC LOWESS Corrected', fontsize=14, fontweight='bold')
        ax2.legend(fontsize=10)
        ax2.grid(True, alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        
        scree_plot_path = os.path.join(output_dir, f'Scree_Plot_{timestamp}.png')
        plt.savefig(scree_plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Scree Plot 已儲存: {scree_plot_path}")
        
        # ========== 輸出解釋變異量 ==========
        print(f"\n📊 PCA 解釋變異量:")
        print(f"\n  ISTD 校正後:")
        print(f"    - PC1: {pca_istd.explained_variance_ratio_[0]*100:.2f}%")
        print(f"    - PC2: {pca_istd.explained_variance_ratio_[1]*100:.2f}%")
        print(f"    - PC1+PC2: {sum(pca_istd.explained_variance_ratio_[:2])*100:.2f}%")
        
        print(f"\n  LOWESS 校正後:")
        print(f"    - PC1: {pca_lowess.explained_variance_ratio_[0]*100:.2f}%")
        print(f"    - PC2: {pca_lowess.explained_variance_ratio_[1]*100:.2f}%")
        print(f"    - PC1+PC2: {sum(pca_lowess.explained_variance_ratio_[:2])*100:.2f}%")
        
    except Exception as e:
        print(f"❌ PCA 分析失敗: {e}")
        import traceback
        traceback.print_exc()


# ========== 主程式 ==========
def main():
    """主程式入口"""
    print("="*70)
    print("🔬 QC-LOWESS 批次效應校正工具 v6.0")
    print("   ✅ 配對 t 檢定 + Levene's test")
    print("   ✅ Mann-Kendall 趨勢檢驗")
    print("   ✅ R² 和 RMSE 擬合優度評估")
    print("   ✅ P 值分佈圖")
    print("="*70)
    
    # 選擇檔案
    root = tk.Tk()
    root.withdraw()
    
    file_path = filedialog.askopenfilename(
        title="選擇 Excel 檔案",
        filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
    )
    
    if not file_path:
        print("❌ 未選擇檔案，程式結束")
        return
    
    print(f"\n📂 選擇的檔案: {os.path.basename(file_path)}")
    
    # 載入數據
    print(f"\n{'='*70}")
    print(f"📥 載入數據...")
    print(f"{'='*70}")
    
    raw_df, istd_df, sample_info_df = load_and_process_data(file_path)
    
    if istd_df is None or sample_info_df is None:
        print("❌ 數據載入失敗，程式結束")
        return
    
    # 執行 LOWESS 校正
    print(f"\n{'='*70}")
    print(f"🔧 執行 QC-LOWESS 校正...")
    print(f"{'='*70}")
    
    lowess_df, sample_columns, qc_corrected_values = perform_lowess_normalization(istd_df, sample_info_df)
    
    if lowess_df is None:
        print("❌ LOWESS 校正失敗，程式結束")
        return
    
    # 保存結果
    print(f"\n{'='*70}")
    print(f"💾 保存結果...")
    print(f"{'='*70}")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = file_path.replace('.xlsx', f'_QC_LOWESS_{timestamp}.xlsx')
    
    success = save_results_to_excel(
        raw_df, istd_df, lowess_df, sample_info_df, 
        sample_columns, output_file, file_path, qc_corrected_values
    )
    
    if not success:
        print("❌ 結果保存失敗")
        return
    
    # PCA 分析
    print(f"\n{'='*70}")
    print(f"📊 執行 PCA 分析...")
    print(f"{'='*70}")
    
    perform_pca_analysis(istd_df, lowess_df, sample_columns, sample_info_df)
    
    print(f"\n{'='*70}")
    print(f"✅ 所有分析完成！")
    print(f"{'='*70}")
    print(f"\n📁 輸出檔案:")
    print(f"  - Excel 結果: {output_file}")
    print(f"  - 圖表目錄: QC_LOWESS_plots/")
    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
