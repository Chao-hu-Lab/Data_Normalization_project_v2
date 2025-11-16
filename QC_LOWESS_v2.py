import pandas as pd
import numpy as np
import os
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import statsmodels.api as sm
from scipy.stats import levene, kendalltau, wilcoxon
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
    """根據 QC 樣本數量動態選擇 frac"""
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


# ========== ✅ 趨勢顯著性檢驗 ==========
def validate_lowess_trend(qc_orders, qc_intensities, fitted_values):
    """驗證 LOWESS 擬合品質（僅用於記錄）"""
    try:
        tau, mk_pvalue = kendalltau(qc_orders, qc_intensities)
        
        ss_res = np.sum((qc_intensities - fitted_values) ** 2)
        ss_tot = np.sum((qc_intensities - np.mean(qc_intensities)) ** 2)
        
        if ss_tot == 0:
            r_squared = 0.0
        else:
            r_squared = 1 - (ss_res / ss_tot)
            r_squared = max(0, r_squared)
        
        rmse = np.sqrt(np.mean((qc_intensities - fitted_values) ** 2))
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


# ========== ✅ 簡化版 LOWESS 校正 ==========
def robust_lowess_correction_v7(qc_orders, qc_intensities, all_orders, all_intensities, feature_id):
    """
    簡化版 LOWESS 校正
    
    決策邏輯：
    1. QC 樣本數 < 5 → 跳過
    2. 離群值檢測與移除
    3. LOWESS 擬合
    4. CV% 改善 ≥ 2% → 執行校正
    5. 穩定性檢查（校正因子 CV < 30%）
    6. 過度校正檢查（校正後 CV 不能增加）
    """
    qc_orders = np.array(qc_orders)
    qc_intensities = np.array(qc_intensities)
    all_orders = np.array(all_orders)
    all_intensities = np.array(all_intensities)
    
    debug_mode = feature_id is not None
    
    # ========== 步驟 1：檢查 QC 樣本數 ==========
    if len(qc_orders) < 5:
        return all_intensities, {
            'status': 'insufficient_qc',
            'qc_count': len(qc_orders),
            'trend_validation': {
                'trend_pvalue': np.nan,
                'trend_tau': np.nan,
                'r_squared': np.nan,
                'rmse': np.nan,
                'has_significant_trend': False
            }
        }
    
    # ========== 步驟 2：離群值檢測 ==========
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
    
    # ========== 步驟 3：動態選擇 frac ==========
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
        # ========== 步驟 4：LOWESS 擬合 ==========
        lowess_result = sm.nonparametric.lowess(
            qc_intensities_clean,
            qc_orders_clean,
            frac=best_frac,
            it=3,
            delta=0.0,
            return_sorted=True
        )
        
        fitted_values = lowess_result[:, 1]
        
        # ========== 步驟 5：趨勢驗證（僅用於記錄）==========
        trend_validation = validate_lowess_trend(
            qc_orders_clean, 
            qc_intensities_clean, 
            fitted_values
        )
        
        if debug_mode:
            print(f"\n🔍 調試特徵: {feature_id}")
            print(f"   QC 樣本數: {n_qc}")
            print(f"   使用 frac: {best_frac}")
            print(f"\n   📊 趨勢驗證（參考）:")
            print(f"     Mann-Kendall p: {trend_validation['trend_pvalue']:.4f}")
            print(f"     Kendall's tau: {trend_validation['trend_tau']:.4f}")
            print(f"     R²: {trend_validation['r_squared']:.4f}")
            print(f"     RMSE: {trend_validation['rmse']:.2e}")
        
        # ========== 步驟 6：計算 CV% 改善 ==========
        original_cv = np.std(qc_intensities_clean, ddof=1) / np.mean(qc_intensities_clean) * 100
        
        # 預測 QC 樣本校正後的值
        qc_predicted_trends = np.interp(
            qc_orders_clean,
            lowess_result[:, 0],
            lowess_result[:, 1]
        )
        
        qc_reference = np.median(qc_intensities_clean)
        qc_predicted_trends = np.where(qc_predicted_trends == 0, qc_reference, qc_predicted_trends)
        qc_correction_factors = qc_reference / qc_predicted_trends
        qc_correction_factors = np.clip(qc_correction_factors, 0.5, 2.0)
        
        qc_corrected = qc_intensities_clean * qc_correction_factors
        corrected_cv = np.std(qc_corrected, ddof=1) / np.mean(qc_corrected) * 100
        
        cv_improvement = original_cv - corrected_cv
        
        if debug_mode:
            print(f"\n   📊 CV% 評估:")
            print(f"     原始 CV: {original_cv:.2f}%")
            print(f"     預測校正 CV: {corrected_cv:.2f}%")
            print(f"     改善: {cv_improvement:.2f}%")
        
        # ========== 步驟 7：CV% 改善判斷 ==========
        MIN_IMPROVEMENT = 2.0
        
        if cv_improvement < MIN_IMPROVEMENT:
            if debug_mode:
                print(f"\n   ⚠️  CV% 改善不足 ({cv_improvement:.2f}% < {MIN_IMPROVEMENT}%)，跳過校正")
            return all_intensities, {
                'status': 'insufficient_improvement',
                'original_cv': original_cv,
                'corrected_cv': corrected_cv,
                'cv_improvement': cv_improvement,
                'trend_validation': trend_validation
            }
        
        # ========== 步驟 8：校正因子穩定性檢查 ==========
        cf_cv = np.std(qc_correction_factors) / np.mean(qc_correction_factors) * 100
        MAX_CF_CV = 30.0
        
        if cf_cv > MAX_CF_CV:
            if debug_mode:
                print(f"\n   ⚠️  校正因子不穩定 (CV={cf_cv:.1f}% > {MAX_CF_CV}%)，跳過校正")
            return all_intensities, {
                'status': 'unstable_correction_factors',
                'correction_factor_cv': cf_cv,
                'original_cv': original_cv,
                'corrected_cv': corrected_cv,
                'cv_improvement': cv_improvement,
                'trend_validation': trend_validation
            }
        
        # ========== 步驟 9：過度校正檢查 ==========
        if corrected_cv > original_cv * 1.05:
            if debug_mode:
                print(f"\n   ⚠️  校正反而增加變異，跳過校正")
            return all_intensities, {
                'status': 'overcorrection_detected',
                'original_cv': original_cv,
                'corrected_cv': corrected_cv,
                'cv_improvement': cv_improvement,
                'trend_validation': trend_validation
            }
        
        # ========== 步驟 10：通過所有檢查，執行校正 ==========
        if debug_mode:
            print(f"\n   ✅ 通過所有檢查，執行校正")
            print(f"      CV% 改善: {cv_improvement:.2f}%")
            print(f"      校正因子穩定性: CV={cf_cv:.1f}%")
        
        # 計算所有樣本的校正因子
        predicted_trends = np.interp(
            all_orders, 
            lowess_result[:, 0],
            lowess_result[:, 1]
        )
        
        predicted_trends = np.where(predicted_trends == 0, qc_reference, predicted_trends)
        correction_factors = qc_reference / predicted_trends
        correction_factors = np.clip(correction_factors, 0.5, 2.0)
        
        # 應用校正
        corrected_intensities = all_intensities * correction_factors
        
        # 計算最終效果
        qc_indices = [i for i, order in enumerate(all_orders) if order in qc_orders]
        
        if len(qc_indices) >= 2:
            qc_corrected_final = corrected_intensities[qc_indices]
            final_corrected_cv = np.std(qc_corrected_final, ddof=1) / np.mean(qc_corrected_final) * 100
        else:
            final_corrected_cv = corrected_cv
        
        correction_info = {
            'status': 'success',
            'frac': best_frac,
            'qc_count': len(qc_orders_clean),
            'outliers_removed': outliers_removed,
            'original_cv': original_cv,
            'corrected_cv': final_corrected_cv,
            'cv_improvement': original_cv - final_corrected_cv,
            'median_correction_factor': np.median(correction_factors),
            'correction_factor_cv': cf_cv,
            'qc_reference': qc_reference,
            'correction_factor_range': (np.min(correction_factors), np.max(correction_factors)),
            'correction_factor_std': np.std(correction_factors),
            'trend_validation': trend_validation
        }
        
        return corrected_intensities, correction_info
        
    except Exception as e:
        if debug_mode:
            print(f"\n   ❌ 校正失敗: {e}")
            import traceback
            traceback.print_exc()
        return all_intensities, {
            'status': 'failed',
            'error': str(e),
            'trend_validation': {
                'trend_pvalue': np.nan,
                'trend_tau': np.nan,
                'r_squared': np.nan,
                'rmse': np.nan,
                'has_significant_trend': False
            }
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
    """載入並驗證數據（含完整防呆檢查）"""
    try:
        # ===== 防呆1: 文件存在性檢查 =====
        if not os.path.exists(file_path):
            print(f"❌ 錯誤：找不到檔案 '{file_path}'")
            return None, None, None

        # ===== 防呆2: 文件格式檢查 =====
        if not (file_path.endswith('.xlsx') or file_path.endswith('.xls')):
            print(f"❌ 錯誤：輸入檔案必須是 Excel 格式 (.xlsx 或 .xls)，但提供了 {file_path}")
            return None, None, None

        # ===== 防呆3: 文件大小檢查 =====
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            print(f"❌ 錯誤：檔案大小為 0 bytes，可能是空檔案")
            return None, None, None
        elif file_size < 1024:  # 小於 1KB
            print(f"⚠️  警告：檔案大小僅 {file_size} bytes，可能不是有效的 Excel 檔案")

        print(f"📄 檔案大小: {file_size / 1024:.2f} KB")

        # ===== 防呆4: Excel 文件有效性檢查 =====
        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as e:
            print(f"❌ 錯誤：無法讀取 Excel 檔案，可能已損壞或格式不正確")
            print(f"   詳細錯誤: {e}")
            return None, None, None

        # ===== 防呆5: 必要工作表檢查 =====
        print(f"📋 找到的工作表: {', '.join(excel_file.sheet_names)}")

        required_sheets = ['ISTD_Correction', 'SampleInfo']
        missing_sheets = [sheet for sheet in required_sheets if sheet not in excel_file.sheet_names]

        if missing_sheets:
            print(f"❌ 錯誤：輸入檔案缺少必要的工作表: {', '.join(missing_sheets)}")
            print(f"   找到的工作表: {', '.join(excel_file.sheet_names)}")
            print(f"   提示：QC-LOWESS 校正需要先執行 ISTD_Correction")
            return None, None, None

        # ===== 防呆6: SampleInfo 完整性檢查 =====
        sample_info_df = pd.read_excel(excel_file, sheet_name='SampleInfo')
        print(f"✓ 成功讀取 'SampleInfo' 工作表，包含 {len(sample_info_df)} 筆樣本資訊")

        if sample_info_df.empty:
            print(f"❌ 錯誤：'SampleInfo' 工作表為空")
            return None, None, None

        required_columns = ['Sample_Name', 'Sample_Type', 'Injection_Order']
        missing_cols = [col for col in required_columns if col not in sample_info_df.columns]

        if missing_cols:
            print(f"❌ 錯誤：'SampleInfo' 缺少必要欄位: {', '.join(missing_cols)}")
            print(f"   找到的欄位: {', '.join(sample_info_df.columns.tolist())}")
            return None, None, None

        # ===== 防呆7: 樣本名稱重複檢查 =====
        duplicate_samples = sample_info_df[sample_info_df['Sample_Name'].duplicated()]
        if not duplicate_samples.empty:
            print(f"⚠️  警告：'SampleInfo' 中發現重複的樣本名稱:")
            for idx, row in duplicate_samples.iterrows():
                print(f"     - {row['Sample_Name']}")
            print(f"   建議：請檢查樣本名稱是否正確")

        # ===== 防呆8: 樣本類型檢查 =====
        sample_types = sample_info_df['Sample_Type'].unique()
        print(f"📊 樣本類型: {', '.join([str(t) for t in sample_types])}")

        qc_count = sample_info_df[sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)].shape[0]
        if qc_count == 0:
            print(f"❌ 錯誤：未找到 QC 樣本（Sample_Type 中無 'QC' 字樣）")
            print(f"   提示：QC-LOWESS 校正需要至少 5 個 QC 樣本")
            return None, None, None
        elif qc_count < 5:
            print(f"⚠️  警告：QC 樣本數量不足 ({qc_count} < 5)")
            print(f"   提示：建議至少有 5 個 QC 樣本以確保校正準確性")
        else:
            print(f"✓ 找到 {qc_count} 個 QC 樣本")

        # ===== 防呆9: Injection_Order 有效性檢查 =====
        if 'Injection_Order' in sample_info_df.columns:
            invalid_orders = sample_info_df[pd.isna(sample_info_df['Injection_Order'])]
            if not invalid_orders.empty:
                print(f"⚠️  警告：發現 {len(invalid_orders)} 個樣本缺少 Injection_Order:")
                for idx, row in invalid_orders.head(5).iterrows():
                    print(f"     - {row['Sample_Name']}")
                if len(invalid_orders) > 5:
                    print(f"     ... 還有 {len(invalid_orders) - 5} 個樣本")

            # 檢查 Injection_Order 是否為數值
            try:
                sample_info_df['Injection_Order'] = pd.to_numeric(sample_info_df['Injection_Order'], errors='coerce')
                invalid_count = sample_info_df['Injection_Order'].isna().sum()
                if invalid_count > 0:
                    print(f"⚠️  警告：{invalid_count} 個樣本的 Injection_Order 無法轉換為數值")
            except Exception as e:
                print(f"⚠️  警告：Injection_Order 數據類型檢查失敗: {e}")

        # ===== 防呆10: ISTD_Correction 基本檢查 =====
        istd_df = pd.read_excel(excel_file, sheet_name='ISTD_Correction')
        print(f"✓ 成功讀取 'ISTD_Correction' 工作表，包含 {len(istd_df)} 個特徵")

        if istd_df.empty:
            print(f"❌ 錯誤：'ISTD_Correction' 工作表為空")
            return None, None, None

        if 'FeatureID' not in istd_df.columns:
            print(f"❌ 錯誤：'ISTD_Correction' 缺少 'FeatureID' 欄位")
            print(f"   找到的欄位: {', '.join(istd_df.columns.tolist())}")
            return None, None, None

        # ===== 防呆11: FeatureID 重複檢查 =====
        duplicate_features = istd_df[istd_df['FeatureID'].duplicated(keep=False)]
        if not duplicate_features.empty:
            print(f"⚠️  警告：'ISTD_Correction' 中發現重複的 FeatureID:")
            dup_ids = duplicate_features['FeatureID'].unique()
            for fid in dup_ids[:5]:
                print(f"     - {fid}")
            if len(dup_ids) > 5:
                print(f"     ... 還有 {len(dup_ids) - 5} 個重複的 FeatureID")
            print(f"   建議：請檢查數據是否正確，腳本將保留第一次出現的記錄")

        # ===== 防呆12: 樣本欄位檢查 =====
        exclude_cols = ['FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference',
                       'ISTD_Median', 'QC_CV%']
        sample_columns = [col for col in istd_df.columns if col not in exclude_cols]

        if len(sample_columns) == 0:
            print(f"❌ 錯誤：'ISTD_Correction' 中沒有樣本欄位")
            return None, None, None

        print(f"✓ 找到 {len(sample_columns)} 個樣本欄位")

        # ===== 防呆13: 樣本名稱匹配檢查 =====
        sample_names_in_info = set(sample_info_df['Sample_Name'].astype(str).str.strip().str.lower())
        sample_names_in_istd = set([str(col).strip().lower() for col in sample_columns])

        missing_in_istd = sample_names_in_info - sample_names_in_istd
        missing_in_info = sample_names_in_istd - sample_names_in_info

        if missing_in_istd:
            print(f"⚠️  警告：以下樣本在 SampleInfo 中有記錄，但在 ISTD_Correction 中找不到:")
            for name in list(missing_in_istd)[:5]:
                print(f"     - {name}")
            if len(missing_in_istd) > 5:
                print(f"     ... 還有 {len(missing_in_istd) - 5} 個樣本")

        if missing_in_info:
            print(f"⚠️  警告：以下樣本在 ISTD_Correction 中有數據，但在 SampleInfo 中找不到:")
            for name in list(missing_in_info)[:5]:
                print(f"     - {name}")
            if len(missing_in_info) > 5:
                print(f"     ... 還有 {len(missing_in_info) - 5} 個樣本")

        # ===== 防呆14: 強制轉換樣本欄位為數值 =====
        for col in sample_columns:
            istd_df[col] = pd.to_numeric(istd_df[col], errors='coerce')

        # ===== 防呆15: 全為 NaN 或 0 的列檢查 =====
        empty_columns = []
        for col in sample_columns:
            non_zero_count = (istd_df[col] > 0).sum()
            if non_zero_count == 0:
                empty_columns.append(col)

        if empty_columns:
            print(f"⚠️  警告：以下樣本的所有數值都是 0 或 NaN:")
            for col in empty_columns[:5]:
                print(f"     - {col}")
            if len(empty_columns) > 5:
                print(f"     ... 還有 {len(empty_columns) - 5} 個樣本")

        # 填充 NaN 為 0
        istd_df = istd_df.fillna(0)
        print(f"✓ ISTD_Correction 數據類型檢查：樣本欄位已轉換為數值型")

        # ===== 防呆16: 數值範圍檢查 =====
        negative_count = 0
        extreme_high_count = 0

        for col in sample_columns:
            negative_values = (istd_df[col] < 0).sum()
            if negative_values > 0:
                negative_count += 1
                print(f"⚠️  警告：樣本 '{col}' 包含 {negative_values} 個負值")

            # 檢查極端高值（> 1e12）
            extreme_values = (istd_df[col] > 1e12).sum()
            if extreme_values > 0:
                extreme_high_count += 1
                print(f"⚠️  警告：樣本 '{col}' 包含 {extreme_values} 個極端高值 (> 1e12)")

        if negative_count > 0:
            print(f"   提示：已將負值設為 0")
            for col in sample_columns:
                istd_df[col] = istd_df[col].clip(lower=0)

        # 載入 RawIntensity（可選）
        raw_df = None
        if 'RawIntensity' in excel_file.sheet_names:
            try:
                raw_df = pd.read_excel(excel_file, sheet_name='RawIntensity')
                print(f"✓ 已載入 'RawIntensity' 工作表（可選）")
            except Exception as e:
                print(f"⚠️  警告：無法載入 'RawIntensity' 工作表: {e}")

        print(f"\n{'='*70}")
        print(f"✓ 數據載入完成")
        print(f"  - 特徵數: {len(istd_df)}")
        print(f"  - 樣本數: {len(sample_info_df)}")
        print(f"  - QC 樣本數: {qc_count}")
        print(f"{'='*70}\n")

        return raw_df, istd_df, sample_info_df

    except Exception as e:
        print(f"❌ 載入數據失敗（未預期的錯誤）: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None


# ========== LOWESS 正規化 ==========
def perform_lowess_normalization(istd_df, sample_info_df):
    """簡化的 LOWESS 正規化（所有樣本視為單一批次）（含防呆檢查）"""
    try:
        # ===== 防呆1: 輸入數據有效性檢查 =====
        if istd_df is None or istd_df.empty:
            print(f"❌ 錯誤：ISTD_Correction 數據為空")
            return None, None, None, None, None

        if sample_info_df is None or sample_info_df.empty:
            print(f"❌ 錯誤：SampleInfo 數據為空")
            return None, None, None, None, None

        # ===== 防呆2: 必要欄位檢查 =====
        if 'FeatureID' not in istd_df.columns:
            print(f"❌ 錯誤：ISTD_Correction 缺少 'FeatureID' 欄位")
            return None, None, None, None, None

        if 'Sample_Name' not in sample_info_df.columns or 'Sample_Type' not in sample_info_df.columns:
            print(f"❌ 錯誤：SampleInfo 缺少必要欄位")
            return None, None, None, None, None

        exclude_cols = ['FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference',
                       'ISTD_Median', 'QC_CV%']
        sample_columns = [col for col in istd_df.columns if col not in exclude_cols]

        # ===== 防呆3: 樣本欄位檢查 =====
        if len(sample_columns) == 0:
            print(f"❌ 錯誤：找不到任何樣本欄位")
            return None, None, None, None, None

        print(f"✓ 找到 {len(sample_columns)} 個樣本欄位")

        # ===== 防呆4: QC 樣本識別 =====
        if 'Sample_Type' in sample_info_df.columns:
            qc_samples = sample_info_df[
                sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)
            ]['Sample_Name'].tolist()
        else:
            qc_samples = [col for col in sample_columns if 'QC' in col.upper()]

        qc_samples = [s for s in qc_samples if s in sample_columns]

        # ===== 防呆5: QC 樣本數量檢查 =====
        if len(qc_samples) < 5:
            print(f"❌ 錯誤：QC 樣本不足 ({len(qc_samples)} < 5)，無法進行校正")
            print(f"   提示：LOWESS 校正需要至少 5 個 QC 樣本以確保擬合準確性")
            return None, None, None, None, None
        
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
        trend_stats = []
        
        # ✅ 收集決策統計
        decision_stats = {
            'success': 0,
            'insufficient_qc': 0,
            'insufficient_improvement': 0,
            'unstable_correction_factors': 0,
            'overcorrection_detected': 0,
            'failed': 0
        }
        
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
                decision_stats['insufficient_qc'] += 1
                
                result_row = {'FeatureID': feature_id}
                for sample in all_samples:
                    result_row[sample] = row[sample]
                all_results.append(result_row)
                
                qc_corrected_dict = {}
                for qc in qc_samples:
                    if qc in row.index:
                        qc_corrected_dict[qc] = row[qc]
                qc_corrected_values[feature_id] = qc_corrected_dict
                
                trend_stats.append({
                    'FeatureID': feature_id,
                    'MK_Trend_pvalue': np.nan,
                    'Kendall_Tau': np.nan,
                    'LOWESS_R2': np.nan,
                    'LOWESS_RMSE': np.nan
                })
                continue
            
            qc_orders, qc_intensities = zip(*sorted(qc_data))
            
            all_data = []
            for sample in all_samples:
                if sample in injection_orders:
                    order = injection_orders[sample]
                    intensity = row[sample]
                    all_data.append((sample, order, intensity if not pd.isna(intensity) else 0))
            
            all_sample_names, all_orders, all_intensities = zip(*all_data)
            
            # ✅ 使用 v7 版本
            corrected_intensities, info = robust_lowess_correction_v7(
                qc_orders, qc_intensities, all_orders, all_intensities, 
                feature_id if feature_id in debug_features else None
            )
            
            # ✅ 收集決策統計
            status = info.get('status', 'unknown')
            if status in decision_stats:
                decision_stats[status] += 1
            
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
            
            # 收集趨勢驗證統計
            trend_val = info.get('trend_validation', {})
            trend_stats.append({
                'FeatureID': feature_id,
                'MK_Trend_pvalue': trend_val.get('trend_pvalue', np.nan),
                'Kendall_Tau': trend_val.get('trend_tau', np.nan),
                'LOWESS_R2': trend_val.get('r_squared', np.nan),
                'LOWESS_RMSE': trend_val.get('rmse', np.nan)
            })
            
            if (idx + 1) % 500 == 0:
                print(f"  進度: {idx + 1}/{len(istd_df)} features")
        
        print(f"  ✓ 完成: {corrected_count} 成功, {failed_count} 跳過")
        
        # ✅ 顯示詳細決策統計
        print(f"\n  📊 詳細決策統計:")
        print(f"     ✅ 成功校正: {decision_stats['success']} ({decision_stats['success']/len(istd_df)*100:.1f}%)")
        print(f"     • QC 樣本不足: {decision_stats['insufficient_qc']} ({decision_stats['insufficient_qc']/len(istd_df)*100:.1f}%)")
        print(f"     • CV% 改善不足: {decision_stats['insufficient_improvement']} ({decision_stats['insufficient_improvement']/len(istd_df)*100:.1f}%)")
        print(f"     • 校正因子不穩定: {decision_stats['unstable_correction_factors']} ({decision_stats['unstable_correction_factors']/len(istd_df)*100:.1f}%)")
        print(f"     • 檢測到過度校正: {decision_stats['overcorrection_detected']} ({decision_stats['overcorrection_detected']/len(istd_df)*100:.1f}%)")
        print(f"     • 其他失敗: {decision_stats['failed']} ({decision_stats['failed']/len(istd_df)*100:.1f}%)")
        
        lowess_df = pd.DataFrame(all_results)
        trend_stats_df = pd.DataFrame(trend_stats)
        
        return lowess_df, sample_columns, qc_corrected_values, trend_stats_df, decision_stats
        
    except Exception as e:
        print(f"❌ LOWESS 校正失敗: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None, None, None


# ========== ✅ 修正：統計檢定（Levene's test + 整體 Wilcoxon test）==========
def calculate_qc_cv_with_statistical_test(istd_df, lowess_df, sample_columns, sample_info_df, qc_corrected_values):
    """計算 QC CV% 並進行正確的統計檢定"""
    
    istd_df = istd_df.reset_index(drop=True)
    lowess_df = lowess_df.reset_index(drop=True)
    
    min_length = min(len(istd_df), len(lowess_df))
    istd_df = istd_df.iloc[:min_length]
    lowess_df = lowess_df.iloc[:min_length]
    
    print(f"\n{'='*70}")
    print(f"🔬 統計檢定")
    print(f"{'='*70}")
    
    # 識別 QC 樣本
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
    all_cv_improvements = []  # ✅ 收集所有 CV% 改善值（用於整體評估）
    
    print(f"\n  💡 統計方法:")
    print(f"     • Levene's test: 檢測方差是否顯著改變（單一特徵）")
    print(f"     • Wilcoxon test: 檢測 CV% 是否整體顯著降低（所有特徵）")
    
    for idx in range(len(istd_df)):
        try:
            istd_row = istd_df.iloc[idx]
            lowess_row = lowess_df.iloc[idx]
            feature_id = istd_row['FeatureID']
            
            qc_values_istd = get_valid_values(istd_row, qc_columns)
            
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
            
            min_len = min(len(qc_values_istd), len(qc_values_lowess))
            if min_len < 3:
                cv_results.append({
                    'FeatureID': feature_id,
                    'Original_QC_CV%': np.nan,
                    'Corrected_QC_CV%': np.nan,
                    'CV_Improvement%': np.nan,
                    'Variance_Test_pvalue': np.nan
                })
                continue
            
            qc_values_istd = np.array(qc_values_istd[:min_len])
            qc_values_lowess = np.array(qc_values_lowess[:min_len])
            
            # ========== 計算 CV% ==========
            original_cv = (np.std(qc_values_istd, ddof=1) / np.mean(qc_values_istd)) * 100
            corrected_cv = (np.std(qc_values_lowess, ddof=1) / np.mean(qc_values_lowess)) * 100
            cv_improvement = original_cv - corrected_cv
            
            # ✅ 收集 CV% 改善值（用於整體評估）
            if not np.isnan(cv_improvement):
                all_cv_improvements.append(cv_improvement)
            
            # ========== ✅ Levene's test（單一特徵）==========
            try:
                levene_stat, levene_pvalue = levene(qc_values_istd, qc_values_lowess)
            except Exception:
                levene_pvalue = np.nan
            
            cv_results.append({
                'FeatureID': feature_id,
                'Original_QC_CV%': original_cv,
                'Corrected_QC_CV%': corrected_cv,
                'CV_Improvement%': cv_improvement,
                'Variance_Test_pvalue': levene_pvalue
            })
            
            if (idx + 1) % 100 == 0:
                print(f"  處理進度: {idx + 1}/{len(istd_df)} features")
        
        except Exception as e:
            print(f"  ⚠️ 處理特徵 {idx} 時發生錯誤: {e}")
            continue
    
    cv_results_df = pd.DataFrame(cv_results)
    
    # ========== ✅ 整體評估：Wilcoxon test ==========
    print(f"\n{'='*70}")
    print(f"📊 整體校正效果評估")
    print(f"{'='*70}")
    
    if len(all_cv_improvements) >= 10:
        try:
            # 檢測 CV% 改善是否整體 > 0
            w_stat, w_pvalue = wilcoxon(all_cv_improvements, alternative='greater')
            
            print(f"\n  ✅ Wilcoxon Signed-Rank Test (整體評估):")
            print(f"     H₀: CV% 改善的中位數 = 0")
            print(f"     H₁: CV% 改善的中位數 > 0")
            print(f"     統計量: {w_stat:.2f}")
            print(f"     P-value: {w_pvalue:.4e}")
            
            if w_pvalue < 0.001:
                print(f"     結論: LOWESS 校正顯著降低了 QC CV% (p < 0.001) ✅✅✅")
            elif w_pvalue < 0.01:
                print(f"     結論: LOWESS 校正顯著降低了 QC CV% (p < 0.01) ✅✅")
            elif w_pvalue < 0.05:
                print(f"     結論: LOWESS 校正顯著降低了 QC CV% (p < 0.05) ✅")
            else:
                print(f"     結論: LOWESS 校正未顯著降低 QC CV% (p ≥ 0.05) ❌")
            
            # 描述性統計
            median_improvement = np.median(all_cv_improvements)
            mean_improvement = np.mean(all_cv_improvements)
            positive_improvements = np.sum(np.array(all_cv_improvements) > 0)
            
            print(f"\n  📊 CV% 改善的描述性統計:")
            print(f"     中位數改善: {median_improvement:.2f}%")
            print(f"     平均改善: {mean_improvement:.2f}%")
            print(f"     改善特徵比例: {positive_improvements}/{len(all_cv_improvements)} ({positive_improvements/len(all_cv_improvements)*100:.1f}%)")
            
        except Exception as e:
            print(f"  ⚠️ 整體評估失敗: {e}")
    else:
        print(f"  ⚠️ 有效特徵數不足 ({len(all_cv_improvements)} < 10)，跳過整體評估")
    
    print(f"{'='*70}\n")
    
    return cv_results_df


# ========== ✅ 修正：P 值分佈圖（只繪製 Levene's test）==========
def plot_pvalue_distribution(cv_results_df, output_base_dir, timestamp):
    """繪製 Levene's test p 值分佈圖（含防呆檢查）"""
    try:
        # ===== 防呆1: 輸入數據檢查 =====
        if cv_results_df is None or cv_results_df.empty:
            print("  ⚠️  警告：CV 結果數據為空，無法繪製 p 值分佈圖")
            return

        if 'Variance_Test_pvalue' not in cv_results_df.columns:
            print("  ⚠️  警告：找不到 Variance_Test_pvalue 欄位，無法繪製 p 值分佈圖")
            return

        # ===== 防呆2: 輸出目錄檢查 =====
        plots_dir = os.path.join(output_base_dir, 'QC_LOWESS_plots')

        try:
            os.makedirs(plots_dir, exist_ok=True)
        except Exception as e:
            print(f"  ⚠️  警告：無法創建輸出目錄: {e}")
            return

        if not os.access(plots_dir, os.W_OK):
            print(f"  ⚠️  警告：沒有寫入權限到目錄: {plots_dir}")
            return
        
        levene_pvalues = cv_results_df['Variance_Test_pvalue'].dropna()
        
        if len(levene_pvalues) < 10:
            print("  ⚠️ 有效 p 值數量不足，跳過 p 值分佈圖")
            return
        
        # 只繪製 Levene's test 的 p 值分佈
        fig, ax = plt.subplots(1, 1, figsize=(10, 7))
        
        ax.hist(levene_pvalues, bins=20, color='steelblue', edgecolor='black', alpha=0.7)
        ax.axhline(y=len(levene_pvalues)/20, color='red', linestyle='--', linewidth=2,
                   label='Uniform Distribution Expected')
        ax.set_xlabel('P-value (Levene\'s Test)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Frequency', fontsize=12, fontweight='bold')
        ax.set_title('P-value Distribution\n(Variance Homogeneity Test)', 
                     fontsize=14, fontweight='bold')
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # Kolmogorov-Smirnov 檢定
        from scipy.stats import kstest
        ks_stat, ks_pvalue = kstest(levene_pvalues, 'uniform')
        
        textstr = f'Kolmogorov-Smirnov Test:\n'
        textstr += f'Statistic = {ks_stat:.4f}\n'
        textstr += f'P-value = {ks_pvalue:.4f}\n'
        if ks_pvalue > 0.05:
            textstr += 'Result: Uniform ✓'
        else:
            textstr += 'Result: Non-uniform ✗'
        
        ax.text(0.98, 0.97, textstr, transform=ax.transAxes,
                fontsize=10, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        plt.tight_layout()
        
        pvalue_plot_path = os.path.join(plots_dir, f'Pvalue_Distribution_Levene_{timestamp}.png')

        # ===== 防呆: 圖表保存檢查 =====
        try:
            plt.savefig(pvalue_plot_path, dpi=300, bbox_inches='tight')
            plt.close()

            # 驗證文件是否成功保存
            if not os.path.exists(pvalue_plot_path):
                print(f"\n⚠️  警告：P 值分佈圖保存失敗，找不到輸出檔案")
                return
            else:
                plot_size = os.path.getsize(pvalue_plot_path)
                if plot_size == 0:
                    print(f"\n⚠️  警告：P 值分佈圖大小為 0 bytes")
                    return

            print(f"\n✓ P 值分佈圖已儲存: {pvalue_plot_path}")
            print(f"  - 圖表大小: {plot_size / 1024:.2f} KB")
        except Exception as e:
            plt.close()
            print(f"\n⚠️  警告：保存 P 值分佈圖時發生錯誤: {e}")
            return
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
        for row in source_sheet.iter_rows():
            for cell in row:
                target_cell = target_sheet.cell(row=cell.row, column=cell.column, value=cell.value)
                
                if cell.has_style:
                    target_cell.font = copy.copy(cell.font)
                    target_cell.border = copy.copy(cell.border)
                    target_cell.fill = copy.copy(cell.fill)
                    target_cell.number_format = copy.copy(cell.number_format)
                    target_cell.protection = copy.copy(cell.protection)
                    target_cell.alignment = copy.copy(cell.alignment)
        
        for col_letter, col_dim in source_sheet.column_dimensions.items():
            target_sheet.column_dimensions[col_letter].width = col_dim.width
        
        for row_num, row_dim in source_sheet.row_dimensions.items():
            target_sheet.row_dimensions[row_num].height = row_dim.height
        
        for merged_cell_range in source_sheet.merged_cells.ranges:
            target_sheet.merge_cells(str(merged_cell_range))
        
        return True
        
    except Exception as e:
        print(f"  ⚠ 複製格式時發生錯誤: {e}")
        return False


# ========== ✅ 修正：保存結果到 Excel（移除 Wilcoxon_pvalue）==========
def save_results_to_excel(raw_df, istd_df, lowess_df, sample_info_df, sample_columns,
                          output_file, input_file, qc_corrected_values, trend_stats_df, decision_stats):
    """保存結果到 Excel（含完整防呆檢查）"""
    try:
        # ===== 防呆1: 輸入數據有效性檢查 =====
        if istd_df is None or istd_df.empty:
            print(f"❌ 錯誤：ISTD_Correction 數據為空，無法保存")
            return False

        if lowess_df is None or lowess_df.empty:
            print(f"❌ 錯誤：LOWESS 校正結果為空，無法保存")
            return False

        if sample_info_df is None or sample_info_df.empty:
            print(f"❌ 錯誤：SampleInfo 數據為空，無法保存")
            return False

        # ===== 防呆2: 輸出路徑有效性檢查 =====
        output_dir = os.path.dirname(output_file)
        if not os.path.exists(output_dir):
            print(f"⚠️  警告：輸出目錄不存在，嘗試創建: {output_dir}")
            try:
                os.makedirs(output_dir, exist_ok=True)
                print(f"✓ 成功創建輸出目錄")
            except Exception as e:
                print(f"❌ 錯誤：無法創建輸出目錄: {e}")
                return False

        # ===== 防呆3: 輸出目錄可寫性檢查 =====
        if not os.access(output_dir, os.W_OK):
            print(f"❌ 錯誤：沒有寫入權限到目錄: {output_dir}")
            return False

        # ===== 防呆4: 輸入文件有效性檢查 =====
        if not os.path.exists(input_file):
            print(f"❌ 錯誤：找不到輸入檔案: {input_file}")
            return False
        cv_results_df = calculate_qc_cv_with_statistical_test(
            istd_df, 
            lowess_df, 
            sample_columns, 
            sample_info_df, 
            qc_corrected_values
        )
        
        # ✅ 主表：只保留 Levene's test 和 CV%
        lowess_with_cv = lowess_df.merge(cv_results_df, on='FeatureID', how='left')
        
        # ✅ 主表欄位順序（移除 Wilcoxon_pvalue 和 Significant_Improvement）
        cols_order = [
            'Original_QC_CV%', 
            'Corrected_QC_CV%', 
            'CV_Improvement%',
            'Variance_Test_pvalue'  # 只保留 Levene's test
        ]
        other_cols = [col for col in lowess_with_cv.columns if col not in cols_order]
        lowess_with_cv = lowess_with_cv[other_cols + cols_order]
        
        # ✅ 副表：進階統計指標
        advanced_stats_df = lowess_df[['FeatureID']].merge(
            trend_stats_df, on='FeatureID', how='left'
        )
        
        print(f"\n📋 開始處理 Excel 檔案...")
        print(f"  - 載入原始檔案: {os.path.basename(input_file)}")
        
        input_workbook = load_workbook(input_file)
        workbook = input_workbook
        
        # 刪除舊工作表
        sheets_to_update = ['QC LOWESS result', 'Advanced Statistics', 'SampleInfo']
        
        for sheet_name in sheets_to_update:
            if sheet_name in workbook.sheetnames:
                del workbook[sheet_name]
                print(f"  - 刪除舊工作表: {sheet_name}")
        
        istd_sheet_original = workbook['ISTD_Correction']
        
        # 保存格式資訊
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
        
        istd_col_widths = {col: dim.width for col, dim in istd_sheet_original.column_dimensions.items()}
        istd_row_heights = {row: dim.height for row, dim in istd_sheet_original.row_dimensions.items()}
        istd_merged_cells = [str(merged) for merged in istd_sheet_original.merged_cells.ranges]
        
        # 寫入臨時檔案
        temp_file = output_file.replace('.xlsx', '_temp.xlsx')
        with pd.ExcelWriter(temp_file, engine='openpyxl') as writer:
            istd_df.to_excel(writer, sheet_name='ISTD_Correction', index=False)
            lowess_with_cv.to_excel(writer, sheet_name='QC LOWESS result', index=False)
            advanced_stats_df.to_excel(writer, sheet_name='Advanced Statistics', index=False)
            sample_info_df.to_excel(writer, sheet_name='SampleInfo', index=False)
        
        temp_workbook = load_workbook(temp_file)
        
        print(f"  - 更新 ISTD_Correction 工作表（保留原始格式）...")
        
        if 'ISTD_Correction' in workbook.sheetnames:
            del workbook['ISTD_Correction']
        
        istd_sheet_new = workbook.create_sheet('ISTD_Correction', 0)
        
        temp_istd_sheet = temp_workbook['ISTD_Correction']
        for row in temp_istd_sheet.iter_rows():
            for cell in row:
                istd_sheet_new.cell(row=cell.row, column=cell.column, value=cell.value)
        
        # 恢復格式
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
        
        for col, width in istd_col_widths.items():
            istd_sheet_new.column_dimensions[col].width = width
        
        for row, height in istd_row_heights.items():
            istd_sheet_new.row_dimensions[row].height = height
        
        for merged in istd_merged_cells:
            try:
                istd_sheet_new.merge_cells(merged)
            except:
                pass
        
        print(f"  ✓ ISTD_Correction 格式已完整保留")
        
        # 複製其他工作表
        for sheet_name in ['QC LOWESS result', 'Advanced Statistics', 'SampleInfo']:
            if sheet_name in temp_workbook.sheetnames:
                source_sheet = temp_workbook[sheet_name]
                target_sheet = workbook.create_sheet(sheet_name)
                copy_sheet_with_full_format(source_sheet, target_sheet)
                print(f"  ✓ 已複製工作表: {sheet_name}")
        
        temp_workbook.close()
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        # 科學記號格式
        scientific_format = '0.00E+00'
        
        for sheet_name in ['ISTD_Correction', 'QC LOWESS result', 'Advanced Statistics', 'SampleInfo']:
            if sheet_name in workbook.sheetnames:
                worksheet = workbook[sheet_name]
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=1, max_col=worksheet.max_column):
                    for cell in row:
                        if isinstance(cell.value, (int, float)) and not pd.isna(cell.value):
                            if cell.number_format == 'General' or cell.number_format == '0':
                                cell.number_format = scientific_format

        # ✅ 顏色標記（簡化版）
        orange_fill = PatternFill(start_color='FFA500', end_color='FFA500', fill_type='solid')
        light_blue_fill = PatternFill(start_color='ADD8E6', end_color='ADD8E6', fill_type='solid')
        light_green_fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')

        # 主表顏色標記
        if 'QC LOWESS result' in workbook.sheetnames:
            worksheet = workbook['QC LOWESS result']
            header = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            
            # CV% 相關欄位 - 橘色
            for col_name in ['Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%']:
                if col_name in header:
                    col_idx = header.index(col_name) + 1
                    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                        for cell in row:
                            cell.fill = orange_fill
            
            # Levene's test - 淺藍色
            if 'Variance_Test_pvalue' in header:
                col_idx = header.index('Variance_Test_pvalue') + 1
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                    for cell in row:
                        cell.fill = light_blue_fill
        
        # 副表顏色標記
        if 'Advanced Statistics' in workbook.sheetnames:
            worksheet = workbook['Advanced Statistics']
            header = [cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1))]
            
            # 所有進階指標 - 淺綠色
            for col_name in ['MK_Trend_pvalue', 'Kendall_Tau', 'LOWESS_R2', 'LOWESS_RMSE']:
                if col_name in header:
                    col_idx = header.index(col_name) + 1
                    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=col_idx, max_col=col_idx):
                        for cell in row:
                            cell.fill = light_green_fill

        # ===== 防呆5: 文件保存檢查 =====
        try:
            workbook.save(output_file)
            print(f"✓ 成功保存 Excel 檔案")
        except PermissionError:
            print(f"❌ 錯誤：無法保存檔案，可能檔案已被其他程式開啟")
            print(f"   請關閉檔案後重試: {output_file}")
            workbook.close()
            return False
        except Exception as e:
            print(f"❌ 錯誤：保存檔案時發生錯誤: {e}")
            workbook.close()
            return False

        workbook.close()

        # ===== 防呆6: 文件保存驗證 =====
        if not os.path.exists(output_file):
            print(f"❌ 錯誤：檔案保存失敗，找不到輸出檔案: {output_file}")
            return False

        # 檢查文件大小
        output_size = os.path.getsize(output_file)
        if output_size == 0:
            print(f"❌ 錯誤：輸出檔案大小為 0 bytes")
            return False
        elif output_size < 1024:
            print(f"⚠️  警告：輸出檔案大小異常小 ({output_size} bytes)")

        print(f"✓ 輸出檔案大小: {output_size / 1024:.2f} KB")

        # ✅ 統計報告
        print(f"\n{'='*70}")
        print(f"✓ QC LOWESS 結果已保存:")
        print(f"  {output_file}")
        print(f"{'='*70}")
        
        total_count = len(cv_results_df)
        
        print(f"\n📊 核心統計摘要（主表）:")
        print(f"  - 總特徵數: {total_count}")
        
        # CV% 改善統計
        cv_improvements = cv_results_df['CV_Improvement%'].dropna()
        if len(cv_improvements) > 0:
            print(f"\n  📈 CV% 改善:")
            print(f"     平均: {cv_improvements.mean():.2f}%")
            print(f"     中位數: {cv_improvements.median():.2f}%")
            print(f"     範圍: {cv_improvements.min():.2f}% ~ {cv_improvements.max():.2f}%")
            
            improved = (cv_improvements > 5).sum()
            similar = ((cv_improvements >= -5) & (cv_improvements <= 5)).sum()
            worse = (cv_improvements < -5).sum()
            
            print(f"\n  分類:")
            print(f"     顯著改善 (>5%): {improved} ({improved/len(cv_improvements)*100:.1f}%)")
            print(f"     持平 (±5%): {similar} ({similar/len(cv_improvements)*100:.1f}%)")
            print(f"     變差 (<-5%): {worse} ({worse/len(cv_improvements)*100:.1f}%)")
        
        # Levene's test 統計
        levene_valid = cv_results_df['Variance_Test_pvalue'].notna().sum()
        levene_sig = ((cv_results_df['Variance_Test_pvalue'] < 0.05) & 
                      (cv_results_df['Variance_Test_pvalue'].notna())).sum()
        
        print(f"\n  🔬 Levene's Test（方差齊性）:")
        print(f"     成功執行: {levene_valid}/{total_count} ({levene_valid/total_count*100:.1f}%)")
        if levene_valid > 0:
            print(f"     方差顯著改變 (p < 0.05): {levene_sig}/{levene_valid} ({levene_sig/levene_valid*100:.1f}%)")
        
        # 校正決策統計
        print(f"\n📊 校正決策統計:")
        print(f"  ✅ 成功校正: {decision_stats['success']} ({decision_stats['success']/total_count*100:.1f}%)")
        print(f"  ❌ 跳過校正: {total_count - decision_stats['success']} ({(total_count - decision_stats['success'])/total_count*100:.1f}%)")
        print(f"\n  跳過原因:")
        print(f"    • QC 樣本不足: {decision_stats['insufficient_qc']}")
        print(f"    • CV% 改善不足 (<2%): {decision_stats['insufficient_improvement']}")
        print(f"    • 校正因子不穩定: {decision_stats['unstable_correction_factors']}")
        print(f"    • 檢測到過度校正: {decision_stats['overcorrection_detected']}")
        print(f"    • 其他錯誤: {decision_stats['failed']}")
        
        # Mann-Kendall 趨勢統計（副表）
        mk_valid = trend_stats_df['MK_Trend_pvalue'].notna().sum()
        mk_sig = ((trend_stats_df['MK_Trend_pvalue'] < 0.05) & 
                  (trend_stats_df['MK_Trend_pvalue'].notna())).sum()
        
        print(f"\n📊 進階統計（副表）:")
        print(f"  Mann-Kendall 趨勢檢驗:")
        print(f"    成功執行: {mk_valid}/{total_count} ({mk_valid/total_count*100:.1f}%)")
        if mk_valid > 0:
            print(f"    檢測到顯著趨勢 (p < 0.05): {mk_sig}/{mk_valid} ({mk_sig/mk_valid*100:.1f}%)")
        
        # R² 統計
        r2_valid = trend_stats_df['LOWESS_R2'].notna().sum()
        if r2_valid > 0:
            r2_values = trend_stats_df['LOWESS_R2'].dropna()
            print(f"\n  LOWESS 擬合優度 R²:")
            print(f"    中位數: {np.median(r2_values):.4f}")
            print(f"    平均值: {np.mean(r2_values):.4f}")
        
        print(f"\n💡 提示:")
        print(f"  - 主表 (QC LOWESS result): Levene's test + CV%（單一特徵）")
        print(f"  - 副表 (Advanced Statistics): Mann-Kendall + R²/RMSE（進階評估）")
        print(f"  - 整體評估: Wilcoxon test 已在終端機顯示")
        print(f"\n{'='*70}\n")
        
        # P 值分佈圖
        output_base_dir = os.path.dirname(output_file)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        plot_pvalue_distribution(cv_results_df, output_base_dir, timestamp)
        
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
    
    # ✅ 只使用 QC 群組的統計量
    qc_mean = np.mean(qc_scores, axis=0)
    qc_cov = np.cov(qc_scores, rowvar=False)
    
    # 正則化協方差矩陣
    qc_cov_reg = qc_cov + np.eye(p) * 1e-6
    
    try:
        qc_cov_inv = np.linalg.inv(qc_cov_reg)
    except np.linalg.LinAlgError:
        print("   ⚠️ 警告：QC 協方差矩陣奇異，使用偽逆矩陣")
        qc_cov_inv = np.linalg.pinv(qc_cov_reg)
    
    # ✅ 計算每個 QC 樣本與 QC 中心的 Hotelling T² 值
    t2_values = np.zeros(n_qc)
    for i in range(n_qc):
        diff = qc_scores[i] - qc_mean
        t2_values[i] = np.dot(np.dot(diff, qc_cov_inv), diff.T)
    
    # 計算閾值
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
        print(f"   ⚠️ 樣本數不足 ({n})，無法繪製 Hotelling T² 橢圓")
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


# ========== PCA 分析 ==========
def perform_pca_analysis(istd_df, lowess_df, sample_columns, sample_info_df, output_base_dir=None):
    """完整的 PCA 分析（含防呆檢查）"""
    try:
        # ===== 防呆1: 輸入數據有效性檢查 =====
        if istd_df is None or istd_df.empty:
            print(f"❌ 錯誤：ISTD_Correction 數據為空，無法進行 PCA 分析")
            return

        if lowess_df is None or lowess_df.empty:
            print(f"❌ 錯誤：LOWESS 校正結果為空，無法進行 PCA 分析")
            return

        if sample_info_df is None or sample_info_df.empty:
            print(f"❌ 錯誤：SampleInfo 數據為空，無法進行 PCA 分析")
            return

        if not sample_columns or len(sample_columns) == 0:
            print(f"❌ 錯誤：樣本欄位為空，無法進行 PCA 分析")
            return
        # ===== 防呆2: 輸出目錄設置和檢查 =====
        if output_base_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_base_dir = os.path.join(script_dir, "output")

        output_dir = os.path.join(output_base_dir, "QC_LOWESS_plots")

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            print(f"❌ 錯誤：無法創建輸出目錄: {e}")
            return

        # 檢查目錄可寫性
        if not os.access(output_dir, os.W_OK):
            print(f"❌ 錯誤：沒有寫入權限到目錄: {output_dir}")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        sample_meta = sample_info_df.set_index('Sample_Name')

        # 排除統計欄位
        exclude_cols = [
            'FeatureID', 'RT', 'ISTD', 'ISTD_RT', 'RT_Difference', 
            'ISTD_Median', 'QC_CV%',
            'Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%',
            'Variance_Test_pvalue', 'MK_Trend_pvalue', 'Kendall_Tau',
            'LOWESS_R2', 'LOWESS_RMSE'
        ]
        
        sample_columns_clean = [col for col in sample_columns 
                                if col not in exclude_cols 
                                and col in istd_df.columns
                                and col in lowess_df.columns]
        
        print(f"\n📊 PCA 數據準備:")
        print(f"   - 用於 PCA 的樣本數: {len(sample_columns_clean)}")
        
        if len(sample_columns_clean) < 3:
            print("❌ 錯誤：可用樣本數不足 (<3)，無法進行 PCA 分析")
            return

        # 識別樣本類型
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
                    control_columns.append(col)
            else:
                control_columns.append(col)
        
        print(f"\n📋 樣本分類:")
        print(f"   - QC: {len(qc_columns)}")
        print(f"   - Control: {len(control_columns)}")
        print(f"   - Exposed: {len(exposed_columns)}")

        if len(qc_columns) < 3:
            print("⚠️ 警告：QC 樣本不足 (<3)，跳過 PCA 分析")
            return

        # 準備數據矩陣
        def prepare_data_matrix(df, columns):
            data_matrix = df[columns].T.values
            data_matrix = np.where(np.isnan(data_matrix), 0, data_matrix)
            data_matrix = np.where(np.isinf(data_matrix), 0, data_matrix)
            data_matrix = np.where(data_matrix < 0, 0, data_matrix)
            non_zero_features = np.any(data_matrix != 0, axis=0)
            data_matrix = data_matrix[:, non_zero_features]
            data_matrix = np.log2(data_matrix + 1)
            return data_matrix, non_zero_features

        istd_matrix, _ = prepare_data_matrix(istd_df, sample_columns_clean)
        lowess_matrix, _ = prepare_data_matrix(lowess_df, sample_columns_clean)
        
        if istd_matrix.shape[1] < 2 or lowess_matrix.shape[1] < 2:
            print("❌ 錯誤：有效特徵數不足 (<2)，無法進行 PCA 分析")
            return

        # PCA
        scaler_istd = StandardScaler()
        scaler_lowess = StandardScaler()
        
        istd_scaled = scaler_istd.fit_transform(istd_matrix)
        lowess_scaled = scaler_lowess.fit_transform(lowess_matrix)

        pca_istd = PCA(n_components=2)
        pca_lowess = PCA(n_components=2)
        
        scores_istd = pca_istd.fit_transform(istd_scaled)
        scores_lowess = pca_lowess.fit_transform(lowess_scaled)

        var_istd = pca_istd.explained_variance_ratio_
        var_lowess = pca_lowess.explained_variance_ratio_

        # Hotelling T² 異常值檢測
        qc_indices = [i for i, col in enumerate(sample_columns_clean) if col in qc_columns]
        qc_scores_istd = scores_istd[qc_indices]
        qc_scores_lowess = scores_lowess[qc_indices]

        t2_istd, t2_threshold_istd, outliers_istd = calculate_hotelling_t2_outliers(
            qc_scores_istd, scores_istd, alpha=0.05
        )
        t2_lowess, t2_threshold_lowess, outliers_lowess = calculate_hotelling_t2_outliers(
            qc_scores_lowess, scores_lowess, alpha=0.05
        )

        # 建立 QC 異常值映射表
        qc_outlier_map_istd = {}
        qc_outlier_map_lowess = {}
        for i, qc_sample in enumerate(qc_columns):
            qc_outlier_map_istd[qc_sample] = outliers_istd[i]
            qc_outlier_map_lowess[qc_sample] = outliers_lowess[i]

        # 繪製 2D PCA 圖
        print(f"\n🎨 繪製 2D PCA Score Plot...")
        
        fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(16, 9))
        fig.suptitle('2D PCA Comparison: ISTD Corrected vs QC-LOWESS Normalized',
                     fontsize=18, y=0.98, fontweight='bold')

        def plot_pca_subplot(ax, scores, qc_scores, var, t2_threshold, qc_outlier_map, title):
            for i, col in enumerate(sample_columns_clean):
                is_outlier = False
                if col in qc_columns:
                    is_outlier = qc_outlier_map[col]
                    color = '#9370DB'
                    marker = 'o'
                elif col in exposed_columns:
                    color = '#DC143C'
                    marker = '^'
                else:
                    color = '#4169E1'
                    marker = 's'
                
                if is_outlier:
                    edgecolor = 'red'
                    linewidth = 3
                    size = 150
                    alpha = 0.9
                else:
                    edgecolor = 'none'
                    linewidth = 0
                    size = 100
                    alpha = 0.7
                
                ax.scatter(scores[i, 0], scores[i, 1],
                          c=[color], marker=marker, s=size, alpha=alpha,
                          edgecolors=edgecolor, linewidths=linewidth)
            
            # 繪製橢圓
            draw_hotelling_t2_ellipse(ax, scores, label='95% CI (All Samples)',
                                     edgecolor='gray', linestyle='--', linewidth=2)
            draw_hotelling_t2_ellipse(ax, qc_scores, label='95% CI (QC Only)',
                                     edgecolor='#9370DB', linestyle='-', linewidth=3)
            
            ax.set_title(f'{title}\nPC1: {var[0]:.1%}, PC2: {var[1]:.1%}\nHotelling T² Threshold: {t2_threshold:.2f}',
                         fontsize=13, fontweight='bold', pad=10)
            ax.set_xlabel(f't[1] ({var[0]:.1%})', fontsize=12, fontweight='bold')
            ax.set_ylabel(f't[2] ({var[1]:.1%})', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
            ax.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)

        plot_pca_subplot(ax_left, scores_istd, qc_scores_istd, var_istd, 
                        t2_threshold_istd, qc_outlier_map_istd, 'ISTD Corrected')
        
        plot_pca_subplot(ax_right, scores_lowess, qc_scores_lowess, var_lowess,
                        t2_threshold_lowess, qc_outlier_map_lowess, 'QC-LOWESS Normalized')

        # 圖例
        sample_legend_elements = [
            plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='#4169E1',
                      markersize=10, label='Control', markeredgecolor='none'),
            plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='#DC143C',
                      markersize=10, label='Exposed', markeredgecolor='none'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#9370DB',
                      markersize=10, label='QC', markeredgecolor='none'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#9370DB',
                      markersize=10, label='QC Outlier', markeredgecolor='red', markeredgewidth=3)
        ]
        
        ellipse_legend_elements = [
            plt.Line2D([0], [0], linestyle='--', color='gray',
                      linewidth=2, label='95% CI (All Samples)'),
            plt.Line2D([0], [0], linestyle='-', color='#9370DB',
                      linewidth=3, label='95% CI (QC Only)')
        ]
        
        fig.legend(handles=sample_legend_elements, loc='center left', 
                  bbox_to_anchor=(1.01, 0.7), fontsize=11,
                  title='Sample Type', title_fontsize=12,
                  frameon=True, fancybox=True, shadow=True)
        
        fig.legend(handles=ellipse_legend_elements, loc='center left', 
                  bbox_to_anchor=(1.01, 0.3), fontsize=11,
                  title='Confidence Ellipse', title_fontsize=12,
                  frameon=True, fancybox=True, shadow=True)

        plt.tight_layout(rect=[0, 0, 0.88, 0.96])

        pca_plot_path = os.path.join(output_dir, f'2D_PCA_ISTD_vs_LOWESS_{timestamp}.png')

        # ===== 防呆3: 圖表保存檢查 =====
        try:
            plt.savefig(pca_plot_path, dpi=300, bbox_inches='tight')
            print(f"   ✓ 2D PCA 圖表已保存: {pca_plot_path}")

            # 驗證文件是否成功保存
            if not os.path.exists(pca_plot_path):
                print(f"   ⚠️  警告：PCA 圖表保存失敗，找不到輸出檔案")
            else:
                plot_size = os.path.getsize(pca_plot_path)
                if plot_size == 0:
                    print(f"   ⚠️  警告：PCA 圖表大小為 0 bytes")
                else:
                    print(f"   ✓ PCA 圖表大小: {plot_size / 1024:.2f} KB")

        except Exception as e:
            print(f"   ⚠️  警告：保存 PCA 圖表時發生錯誤: {e}")

        plt.close()

        # 統計摘要
        print(f"\n{'='*70}")
        print(f"📊 PCA 分析完成")
        print(f"{'='*70}")
        print(f"  解釋變異量:")
        print(f"    ISTD: PC1={var_istd[0]*100:.2f}%, PC2={var_istd[1]*100:.2f}%")
        print(f"    LOWESS: PC1={var_lowess[0]*100:.2f}%, PC2={var_lowess[1]*100:.2f}%")
        print(f"  異常值: ISTD={np.sum(outliers_istd)}, LOWESS={np.sum(outliers_lowess)}")

    except Exception as e:
        print(f"❌ PCA 分析失敗: {e}")
        import traceback
        traceback.print_exc()


# ========== 主程式 ==========
def main(input_file=None):
    """主程式入口"""
    print("="*70)
    print("🔬 QC-LOWESS 批次效應校正工具 v3")
    print("   ✅ 簡化校正邏輯：CV% 改善 ≥ 2%")
    print("   ✅ 統計方法：Levene's test（單一特徵）+ Wilcoxon test（整體評估）")
    print("   ✅ 進階統計：Mann-Kendall + R²/RMSE（副表）")
    print("="*70)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"\n✓ 已建立 'output' 資料夾: {output_dir}")
    
    if input_file:
        file_path = input_file
        print(f"\n📂 使用傳入的檔案: {os.path.basename(file_path)}")
    else:
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
    
    print(f"\n{'='*70}")
    print(f"📥 載入數據...")
    print(f"{'='*70}")
    
    raw_df, istd_df, sample_info_df = load_and_process_data(file_path)
    
    if istd_df is None or sample_info_df is None:
        print("❌ 數據載入失敗，程式結束")
        return
    
    print(f"\n{'='*70}")
    print(f"🔧 執行 QC-LOWESS 校正...")
    print(f"{'='*70}")
    
    result = perform_lowess_normalization(istd_df, sample_info_df)
    
    if result[0] is None:
        print("❌ LOWESS 校正失敗,程式結束")
        return
    
    lowess_df, sample_columns, qc_corrected_values, trend_stats_df, decision_stats = result
    
    print(f"\n{'='*70}")
    print(f"💾 保存結果...")
    print(f"{'='*70}")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = os.path.join(output_dir, f'QC_LOWESS_{timestamp}.xlsx')
    
    success = save_results_to_excel(
        raw_df, istd_df, lowess_df, sample_info_df, 
        sample_columns, output_file, file_path, qc_corrected_values, trend_stats_df, decision_stats
    )
    
    if not success:
        print("❌ 結果保存失敗")
        return
    
    print(f"\n{'='*70}")
    print(f"📊 執行 PCA 分析...")
    print(f"{'='*70}")
    
    perform_pca_analysis(istd_df, lowess_df, sample_columns, sample_info_df, output_dir)
    
    print(f"\n{'='*70}")
    print(f"✅ 所有分析完成！")
    print(f"{'='*70}")
    print(f"\n📁 輸出內容:")
    print(f"  - Excel 結果: output/{os.path.basename(output_file)}")
    print(f"    ├── ISTD_Correction（保留原格式）")
    print(f"    ├── QC LOWESS result（主表：Levene's test + CV%）")
    print(f"    ├── Advanced Statistics（副表：Mann-Kendall + R²/RMSE）")
    print(f"    └── SampleInfo")
    print(f"\n  - 圖表輸出: output/QC_LOWESS_plots/")
    print(f"    ├── 2D_PCA_ISTD_vs_LOWESS_*.png")
    print(f"    └── Pvalue_Distribution_Levene_*.png")
    print(f"\n  💡 統計方法:")
    print(f"    - Levene's test: 檢測單一特徵方差變化")
    print(f"    - Wilcoxon test: 檢測整體 CV% 是否顯著降低（終端機顯示）")
    print(f"\n{'='*70}\n")
    
    output_file_abs = os.path.abspath(output_file)
    metabolites_count = len(lowess_df)
    samples_count = len(sample_columns)
    
    return {
        'metabolites': metabolites_count,
        'samples': samples_count,
        'output_path': output_file_abs
    }


if __name__ == "__main__":
    main()
