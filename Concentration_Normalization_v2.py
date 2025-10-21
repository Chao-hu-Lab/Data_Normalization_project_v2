import pandas as pd
import numpy as np
from tkinter import filedialog
import tkinter as tk
from pathlib import Path
import warnings
import os
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border
from openpyxl.utils.dataframe import dataframe_to_rows
from scipy.stats import spearmanr, pearsonr
from scipy import stats
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
from copy import copy
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

# ==================== 標準化方法 ====================

def enhanced_pqn_normalization(data_matrix, sample_info_df, sample_columns, reference_values):
    """
    改進版 PQN 標準化：優先使用 QC 樣本作為參考
    """
    print("\n執行改進版混合標準化方法：")
    
    # ========== 🔍 除錯輸出 ==========
    print(f"\n【除錯資訊】")
    print(f"  總樣本數: {len(sample_columns)}")
    
     # ========== Step 1: 分離 QC 和真實樣本（改進版）==========
    sample_types = {}
    for sample in sample_columns:
        sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
        if not sample_row.empty:
            sample_type = str(sample_row.iloc[0].get('Sample_Type', '')).strip().upper()  # ← 加入 strip()
            sample_types[sample] = sample_type
        else:
            # 如果找不到，根據名稱判斷
            if 'QC' in sample.upper():  # ← 改為更寬鬆的判斷
                sample_types[sample] = 'QC'
            else:
                sample_types[sample] = 'SAMPLE'
    
    qc_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] == 'QC']
    real_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] != 'QC']
    
    # 🔍 除錯：顯示樣本類型分佈
    print(f"  樣本類型統計:")
    from collections import Counter
    type_counts = Counter(sample_types.values())
    for stype, count in type_counts.items():
        print(f"    - {stype}: {count}")
    
    # 🔍 除錯：顯示 QC 樣本名稱
    qc_samples = [s for s, t in sample_types.items() if t == 'QC']
    print(f"  QC 樣本列表: {qc_samples}")
    
    qc_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] == 'QC']
    real_indices = [i for i, s in enumerate(sample_columns) if sample_types[s] != 'QC']
    
    qc_count = len(qc_indices)
    real_count = len(real_indices)
    
    print(f"  樣本分類:")
    print(f"    - QC 樣本數量: {qc_count}")
    print(f"    - 真實樣本數量: {real_count}")
    # ========== 除錯輸出結束 ==========
    
    # ========== Step 2: 評估 QC 樣本質量 ==========
    qc_cv_median = np.nan
    reference_strategy = 'NONE'
    
    if qc_count > 0:
        qc_data = data_matrix[:, qc_indices]
        qc_cv = calculate_rsd(qc_data)
        qc_cv_median = np.nanmedian(qc_cv)
        
        print(f"  QC 質量評估:")
        print(f"    - QC 中位數 CV%: {qc_cv_median:.2f}%")
        
        if qc_count >= 3 and qc_cv_median < 30:
            reference_strategy = 'QC'
            print(f"    - ✓ QC 樣本質量良好，使用 QC 作為 PQN 參考")
        elif qc_count >= 1:
            reference_strategy = 'QC_LIMITED'
            print(f"    - ⚠ QC 樣本數量有限（{qc_count}），但仍使用 QC 作為參考")
        else:
            reference_strategy = 'ROBUST_MEDIAN'
            print(f"    - ⚠ QC 樣本不足，使用穩健中位數作為參考")
    else:
        reference_strategy = 'ROBUST_MEDIAN'
        print(f"  ⚠ 無 QC 樣本，使用穩健中位數作為參考")
    
    # ========== Step 3: 肌酐校正（僅針對真實樣本）==========
    print("\n  步驟1: Sample-specific Normalization (肌酐校正)")
    
    real_data = data_matrix[:, real_indices]
    real_reference_values = reference_values[real_indices]
    
    # 過濾有效的參考值
    valid_ref_mask = ~np.isnan(real_reference_values) & (real_reference_values > 0)
    
    if np.sum(valid_ref_mask) < len(real_reference_values) * 0.5:
        print(f"    ⚠ 警告：有效肌酐值不足 50% ({np.sum(valid_ref_mask)}/{len(real_reference_values)})")
    
    # 肌酐校正
    median_ref = np.nanmedian(real_reference_values[valid_ref_mask])
    real_data_corrected = real_data.copy()
    real_data_corrected[:, valid_ref_mask] = (real_data[:, valid_ref_mask] / 
                                               real_reference_values[valid_ref_mask]) * median_ref
    
    print(f"    - 肌酐中位數: {median_ref:.2f}")
    print(f"    - 肌酐範圍: {np.nanmin(real_reference_values):.2f} - {np.nanmax(real_reference_values):.2f}")
    print(f"    - 校正樣本數: {np.sum(valid_ref_mask)}/{len(real_reference_values)}")
    
    # ========== Step 4: PQN 標準化 ==========
    print("\n  步驟2: Probabilistic Quotient Normalization (PQN)")
    
    # 決定參考樣本
    if reference_strategy == 'QC' or reference_strategy == 'QC_LIMITED':
        # 使用 QC 樣本中位數
        reference_sample = np.nanmedian(data_matrix[:, qc_indices], axis=1)
        print(f"    - 使用 QC 樣本中位數作為參考")
    else:
        # 使用真實樣本的穩健中位數（排除極端 10%）
        sorted_totals = np.argsort(np.nansum(real_data_corrected, axis=0))
        n_exclude = max(1, int(len(sorted_totals) * 0.1))
        robust_indices = sorted_totals[n_exclude:-n_exclude]
        reference_sample = np.nanmedian(real_data_corrected[:, robust_indices], axis=1)
        print(f"    - 使用穩健中位數作為參考（排除極端 {n_exclude*2} 個樣本）")
    
    # 4a. 真實樣本的 PQN
    quotients_real = real_data_corrected / reference_sample[:, np.newaxis]
    quotients_real = np.where(np.isfinite(quotients_real), quotients_real, np.nan)
    normalization_factors_real = np.nanmedian(quotients_real, axis=0)
    
    real_data_final = real_data_corrected / normalization_factors_real
    
    print(f"    - 真實樣本標準化因子範圍: {np.nanmin(normalization_factors_real):.4f} - {np.nanmax(normalization_factors_real):.4f}")
    
    # 4b. QC 樣本的 PQN（不做肌酐校正）
    normalization_factors_qc = None
    qc_data_final = None
    
    if qc_count > 0:
        qc_data = data_matrix[:, qc_indices]
        quotients_qc = qc_data / reference_sample[:, np.newaxis]
        quotients_qc = np.where(np.isfinite(quotients_qc), quotients_qc, np.nan)
        normalization_factors_qc = np.nanmedian(quotients_qc, axis=0)
        
        qc_data_final = qc_data / normalization_factors_qc
        
        print(f"    - QC 樣本標準化因子範圍: {np.nanmin(normalization_factors_qc):.4f} - {np.nanmax(normalization_factors_qc):.4f}")
    
    # ========== Step 5: 合併結果 ==========
    final_data = np.full_like(data_matrix, np.nan)
    final_data[:, real_indices] = real_data_final
    if qc_count > 0:
        final_data[:, qc_indices] = qc_data_final
    
    print("  ✓ 混合標準化完成")
    
    # 返回資訊
    pqn_info = {
        'reference_strategy': reference_strategy,
        'qc_count': qc_count,
        'qc_cv': qc_cv_median,
        'real_count': real_count,
        'normalization_factors_real': normalization_factors_real,
        'normalization_factors_qc': normalization_factors_qc,
        'creatinine_median': median_ref,
        'creatinine_valid_count': np.sum(valid_ref_mask)
    }
    
    return final_data, pqn_info

def get_all_sample_columns(df, sample_info_df):
    """
    獲取所有樣本欄位（包含 QC，但排除統計欄位）
    """
    # 排除的統計欄位關鍵字
    exclude_keywords = [
        'CV', 'Silhouette', 'Permutation', 'Correlation', 
        'R_squared', 'Improvement', 'Before', 'After', 
        'Original', 'Corrected', 'pvalue', 'p_value'
    ]
    
    sample_columns = []
    
    for col in df.columns:
        if col == df.columns[0]:  # 跳過第一欄（特徵ID）
            continue
        
        # 檢查是否包含排除關鍵字
        is_stat_column = any(keyword.lower() in str(col).lower() for keyword in exclude_keywords)
        
        if not is_stat_column:
            sample_columns.append(col)  # ← 不排除 QC
    
    return sample_columns

def evaluate_normality(original_data, normalized_data, alpha=0.05):
    """
    評估標準化前後的正態性
    
    使用 Shapiro-Wilk 檢驗評估每個特徵的正態性
    
    """
    from scipy.stats import shapiro
    
    n_features = original_data.shape[0]
    
    # 對數轉換（代謝體學標準做法）
    original_log = np.log10(original_data + 1)
    normalized_log = np.log10(normalized_data + 1)
    
    # 初始化結果
    normality_before = []
    normality_after = []
    p_values_before = []
    p_values_after = []
    
    print(f"\n【正態性檢驗】")
    print(f"  檢驗方法: Shapiro-Wilk")
    print(f"  特徵數量: {n_features}")
    print(f"  顯著性水平: α = {alpha}")
    print(f"  檢驗中...", end="")
    
    for i in range(n_features):
        # 標準化前
        feature_before = original_log[i, :]
        feature_before = feature_before[~np.isnan(feature_before)]
        
        if len(feature_before) >= 3:  # Shapiro-Wilk 至少需要 3 個樣本
            try:
                stat_before, p_before = shapiro(feature_before)
                normality_before.append(p_before > alpha)
                p_values_before.append(p_before)
            except:
                normality_before.append(False)
                p_values_before.append(np.nan)
        else:
            normality_before.append(False)
            p_values_before.append(np.nan)
        
        # 標準化後
        feature_after = normalized_log[i, :]
        feature_after = feature_after[~np.isnan(feature_after)]
        
        if len(feature_after) >= 3:
            try:
                stat_after, p_after = shapiro(feature_after)
                normality_after.append(p_after > alpha)
                p_values_after.append(p_after)
            except:
                normality_after.append(False)
                p_values_after.append(np.nan)
        else:
            normality_after.append(False)
            p_values_after.append(np.nan)
        
        # 進度提示
        if (i + 1) % 100 == 0:
            print(f"\r  檢驗中... {i+1}/{n_features}", end="")
    
    print(f"\r  ✓ 檢驗完成 ({n_features}/{n_features})")
    
    # 統計結果
    n_normal_before = np.sum(normality_before)
    n_normal_after = np.sum(normality_after)
    
    pct_before = (n_normal_before / n_features) * 100
    pct_after = (n_normal_after / n_features) * 100
    improvement = pct_after - pct_before
    
    print(f"\n  【結果】")
    print(f"  標準化前通過: {n_normal_before}/{n_features} ({pct_before:.1f}%)")
    print(f"  標準化後通過: {n_normal_after}/{n_features} ({pct_after:.1f}%)")
    print(f"  改善幅度: {improvement:+.1f}%")
    
    # 評估
    if improvement > 10:
        print(f"  結論: ✓✓ 正態性顯著改善")
    elif improvement > 5:
        print(f"  結論: ✓ 正態性有所改善")
    elif improvement > 0:
        print(f"  結論: ○ 正態性輕微改善")
    else:
        print(f"  結論: ⚠ 正態性未改善")
    
    return {
        'n_normal_before': n_normal_before,
        'n_normal_after': n_normal_after,
        'pct_before': pct_before,
        'pct_after': pct_after,
        'improvement': improvement,
        'normality_before': normality_before,
        'normality_after': normality_after,
        'p_values_before': p_values_before,
        'p_values_after': p_values_after
    }

def calculate_cohens_d(group1, group2):
    """
    計算 Cohen's d (effect size)
    
    Parameters:
    -----------
    group1 : np.ndarray
        第一組數據
    group2 : np.ndarray
        第二組數據
    
    Returns:
    --------
    float : Cohen's d 值
    """
    n1 = len(group1)
    n2 = len(group2)
    
    if n1 < 2 or n2 < 2:
        return np.nan
    
    mean1 = np.mean(group1)
    mean2 = np.mean(group2)
    
    var1 = np.var(group1, ddof=1)
    var2 = np.var(group2, ddof=1)
    
    # Pooled standard deviation
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    
    if pooled_std == 0:
        return np.nan
    
    # Cohen's d
    d = (mean1 - mean2) / pooled_std
    
    return d

def evaluate_group_difference_preservation(original_data, normalized_data, 
                                           sample_info_df, sample_columns):
    """
    評估標準化對組間差異的影響
    
    基於 Sample_Type: CONTROL vs EXPOSURE
    
    Parameters:
    -----------
    original_data : np.ndarray
        原始數據矩陣 (特徵 x 樣本)
    normalized_data : np.ndarray
        標準化後數據矩陣 (特徵 x 樣本)
    sample_info_df : pd.DataFrame
        樣本資訊表
    sample_columns : list
        樣本名稱列表
    
    Returns:
    --------
    dict or None : 組間差異評估結果
    """
    
    # 1. 提取組別資訊
    sample_groups = []
    for sample in sample_columns:
        sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
        if not sample_row.empty:
            sample_type = str(sample_row.iloc[0].get('Sample_Type', '')).upper()
            sample_groups.append(sample_type)
        else:
            sample_groups.append('UNKNOWN')
    
    sample_groups = np.array(sample_groups)
    
    # 2. 識別 CONTROL 和 EXPOSURE
    control_indices = np.where(sample_groups == 'CONTROL')[0]
    exposure_indices = np.where(sample_groups == 'EXPOSURE')[0]
    
    if len(control_indices) == 0 or len(exposure_indices) == 0:
        print(f"\n【組間差異評估】")
        print(f"  ⚠ 警告: 未找到 CONTROL 或 EXPOSURE 組別")
        print(f"    找到的組別類型: {np.unique(sample_groups)}")
        print(f"  跳過組間差異評估")
        return None
    
    print(f"\n【組間差異評估】")
    print(f"  Control 組樣本數: {len(control_indices)}")
    print(f"  Exposure 組樣本數: {len(exposure_indices)}")
    
    # 3. 計算 Cohen's d
    n_features = original_data.shape[0]
    cohens_d_before = []
    cohens_d_after = []
    
    print(f"  計算 Effect Size (Cohen's d)...", end="")
    
    for i in range(n_features):
        # 標準化前
        control_before = original_data[i, control_indices]
        exposure_before = original_data[i, exposure_indices]
        
        control_before = control_before[~np.isnan(control_before)]
        exposure_before = exposure_before[~np.isnan(exposure_before)]
        
        d_before = calculate_cohens_d(control_before, exposure_before)
        cohens_d_before.append(d_before)
        
        # 標準化後
        control_after = normalized_data[i, control_indices]
        exposure_after = normalized_data[i, exposure_indices]
        
        control_after = control_after[~np.isnan(control_after)]
        exposure_after = exposure_after[~np.isnan(exposure_after)]
        
        d_after = calculate_cohens_d(control_after, exposure_after)
        cohens_d_after.append(d_after)
        
        if (i + 1) % 100 == 0:
            print(f"\r  計算 Effect Size... {i+1}/{n_features}", end="")
    
    print(f"\r  ✓ 計算完成 ({n_features}/{n_features})")
    
    cohens_d_before = np.array(cohens_d_before)
    cohens_d_after = np.array(cohens_d_after)
    
    # 4. 分析 Effect Size 變化
    valid_mask = ~(np.isnan(cohens_d_before) | np.isnan(cohens_d_after))
    
    d_before_valid = cohens_d_before[valid_mask]
    d_after_valid = cohens_d_after[valid_mask]
    
    # 計算相對變化（百分比）
    d_change = np.abs(d_after_valid) - np.abs(d_before_valid)
    d_change_pct = (d_change / (np.abs(d_before_valid) + 1e-10)) * 100
    
    # 分類
    enhanced = np.sum(d_change > 0)  # Effect size 增強
    stable = np.sum(np.abs(d_change_pct) <= 10)  # 變化 < 10%
    mild_reduction = np.sum((d_change_pct < -10) & (d_change_pct >= -30))
    severe_reduction = np.sum(d_change_pct < -30)
    
    total = len(d_change)
    
    # 平均保留率
    avg_preservation = np.mean(np.abs(d_after_valid) / (np.abs(d_before_valid) + 1e-10)) * 100
    
    print(f"\n  【Effect Size 變化統計】")
    print(f"  分析特徵數: {total}")
    print(f"  - 增強: {enhanced} ({enhanced/total*100:.1f}%)")
    print(f"  - 穩定 (±10%): {stable} ({stable/total*100:.1f}%)")
    print(f"  - 輕度減弱 (-10% ~ -30%): {mild_reduction} ({mild_reduction/total*100:.1f}%)")
    print(f"  - 顯著減弱 (< -30%): {severe_reduction} ({severe_reduction/total*100:.1f}%)")
    print(f"\n  平均 Effect Size 保留率: {avg_preservation:.1f}%")
    
    # 評估
    if severe_reduction / total > 0.1:
        print(f"  結論: ⚠⚠ 超過 10% 的特徵顯著減弱，需要檢查")
    elif severe_reduction / total > 0.05:
        print(f"  結論: ⚠ 約 5-10% 的特徵顯著減弱，建議關注")
    elif avg_preservation > 90:
        print(f"  結論: ✓✓ 組間差異保留優秀")
    elif avg_preservation > 80:
        print(f"  結論: ✓ 組間差異保留良好")
    else:
        print(f"  結論: ○ 組間差異保留尚可")
    
    return {
        'cohens_d_before': cohens_d_before,
        'cohens_d_after': cohens_d_after,
        'enhanced': enhanced,
        'stable': stable,
        'mild_reduction': mild_reduction,
        'severe_reduction': severe_reduction,
        'avg_preservation': avg_preservation,
        'total': total,
        'control_count': len(control_indices),
        'exposure_count': len(exposure_indices)
    }
def plot_qq_comparison(original_data, normalized_data, sample_size=20, output_path=None):
    """
    繪製 Q-Q Plot 對比（隨機選擇代謝物）
    
    Parameters:
    -----------
    original_data : np.ndarray
        原始數據矩陣
    normalized_data : np.ndarray
        標準化後數據矩陣
    sample_size : int
        選擇多少個特徵繪製
    output_path : Path
        輸出路徑
    """
    from scipy import stats
    
    n_features = original_data.shape[0]
    selected_features = np.random.choice(n_features, min(sample_size, n_features), replace=False)
    
    # 對數轉換
    original_log = np.log10(original_data + 1)
    normalized_log = np.log10(normalized_data + 1)
    
    # 計算子圖佈局
    n_cols = 5
    n_rows = (len(selected_features) + n_cols - 1) // n_cols
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(20, 4*n_rows))
    if n_rows == 1:
        axes = axes.reshape(1, -1)
    axes = axes.flatten()
    
    for idx, feature_idx in enumerate(selected_features):
        ax = axes[idx]
        
        # 標準化前（藍色）
        data_before = original_log[feature_idx, :]
        data_before = data_before[~np.isnan(data_before)]
        
        if len(data_before) > 0:
            stats.probplot(data_before, dist="norm", plot=ax)
            
            # 修改顏色
            line = ax.get_lines()[0]
            line.set_markerfacecolor('blue')
            line.set_markeredgecolor('blue')
            line.set_alpha(0.6)
            
            line = ax.get_lines()[1]
            line.set_color('blue')
            line.set_linestyle('--')
            line.set_alpha(0.6)
        
        # 標準化後（紅色）
        data_after = normalized_log[feature_idx, :]
        data_after = data_after[~np.isnan(data_after)]
        
        if len(data_after) > 0:
            stats.probplot(data_after, dist="norm", plot=ax)
            
            line = ax.get_lines()[2]
            line.set_markerfacecolor('red')
            line.set_markeredgecolor('red')
            line.set_alpha(0.6)
            
            line = ax.get_lines()[3]
            line.set_color('red')
            line.set_linestyle('--')
            line.set_alpha(0.6)
        
        ax.set_title(f'Feature {feature_idx}', fontsize=9)
        ax.legend(['Before', '', 'After', ''], fontsize=7, loc='lower right')
        ax.grid(True, alpha=0.3)
    
    # 隱藏多餘的子圖
    for idx in range(len(selected_features), len(axes)):
        axes[idx].axis('off')
    
    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"  ✓ Q-Q Plot 已儲存")
    plt.close()

def plot_effect_size_comparison(cohens_d_before, cohens_d_after, output_path):
    """
    繪製 Effect Size 變化散點圖
    
    Parameters:
    -----------
    cohens_d_before : np.ndarray
        標準化前的 Cohen's d
    cohens_d_after : np.ndarray
        標準化後的 Cohen's d
    output_path : Path
        輸出路徑
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # 移除 NaN
    valid_mask = ~(np.isnan(cohens_d_before) | np.isnan(cohens_d_after))
    d_before = cohens_d_before[valid_mask]
    d_after = cohens_d_after[valid_mask]
    
    # 子圖 1: 散點圖
    ax1.scatter(np.abs(d_before), np.abs(d_after), alpha=0.5, s=30, color='steelblue')
    
    # 添加對角線（完美保留）
    max_val = max(np.max(np.abs(d_before)), np.max(np.abs(d_after)))
    ax1.plot([0, max_val], [0, max_val], 'r--', linewidth=2, label='Perfect preservation')
    
    # 添加 ±20% 參考線
    ax1.plot([0, max_val], [0, max_val*0.8], 'orange', linestyle='--', 
             linewidth=1, alpha=0.5, label='-20%')
    ax1.plot([0, max_val], [0, max_val*1.2], 'orange', linestyle='--', 
             linewidth=1, alpha=0.5, label='+20%')
    
    ax1.set_xlabel('|Cohen\'s d| Before Normalization', fontsize=12, fontweight='bold')
    ax1.set_ylabel('|Cohen\'s d| After Normalization', fontsize=12, fontweight='bold')
    ax1.set_title('Effect Size Preservation', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    
    # 子圖 2: 變化分佈直方圖
    d_change_pct = ((np.abs(d_after) - np.abs(d_before)) / (np.abs(d_before) + 1e-10)) * 100
    
    ax2.hist(d_change_pct, bins=50, color='steelblue', alpha=0.7, edgecolor='black')
    ax2.axvline(x=0, color='red', linestyle='--', linewidth=2, label='No change')
    ax2.axvline(x=np.median(d_change_pct), color='orange', linestyle='--', linewidth=2, 
                label=f'Median: {np.median(d_change_pct):.1f}%')
    
    ax2.set_xlabel('Effect Size Change (%)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax2.set_title('Distribution of Effect Size Change', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')
    
    # 添加統計文字
    improved = np.sum(d_change_pct > 0)
    worsened = np.sum(d_change_pct < 0)
    stats_text = f"Improved: {improved}\nWorsened: {worsened}\nTotal: {len(d_change_pct)}"
    ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes,
            fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ Effect Size 對比圖已儲存")

def plot_qc_quality_assessment(original_qc, normalized_qc, qc_names, output_path):
    """
    專門評估 QC 樣本質量的視覺化
    
    包含：
    1. QC 樣本 CV% 分佈
    2. QC 樣本總強度
    3. QC 樣本間相關性
    4. CV% 改善散點圖
    5. 統計摘要
    
    Parameters:
    -----------
    original_qc : np.ndarray
        原始 QC 數據 (特徵 x QC樣本)
    normalized_qc : np.ndarray
        標準化後 QC 數據
    qc_names : list
        QC 樣本名稱
    output_path : Path
        輸出路徑
    """
    fig = plt.figure(figsize=(18, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
    
    # === 子圖 1: CV% 分佈對比 ===
    ax1 = fig.add_subplot(gs[0, 0])
    
    cv_before = calculate_rsd(original_qc)
    cv_after = calculate_rsd(normalized_qc)
    
    ax1.hist(cv_before, bins=30, alpha=0.6, color='blue', label='Before', edgecolor='black')
    ax1.hist(cv_after, bins=30, alpha=0.6, color='red', label='After', edgecolor='black')
    
    ax1.axvline(x=np.median(cv_before), color='blue', linestyle='--', linewidth=2,
                label=f'Median Before: {np.median(cv_before):.1f}%')
    ax1.axvline(x=np.median(cv_after), color='red', linestyle='--', linewidth=2,
                label=f'Median After: {np.median(cv_after):.1f}%')
    ax1.axvline(x=20, color='orange', linestyle=':', linewidth=2, label='20% threshold')
    
    ax1.set_xlabel('CV%', fontsize=10, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=10, fontweight='bold')
    ax1.set_title('QC Sample CV% Distribution', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=7)
    ax1.grid(True, alpha=0.3)
    
    # === 子圖 2: QC 樣本總強度 ===
    ax2 = fig.add_subplot(gs[0, 1])
    
    total_before = np.sum(original_qc, axis=0)
    total_after = np.sum(normalized_qc, axis=0)
    
    x_pos = np.arange(len(qc_names))
    width = 0.35
    
    ax2.bar(x_pos - width/2, total_before, width, label='Before', alpha=0.7, color='blue')
    ax2.bar(x_pos + width/2, total_after, width, label='After', alpha=0.7, color='red')
    
    ax2.axhline(y=np.median(total_before), color='blue', linestyle='--', linewidth=1, alpha=0.5)
    ax2.axhline(y=np.median(total_after), color='red', linestyle='--', linewidth=1, alpha=0.5)
    
    ax2.set_ylabel('Total Intensity', fontsize=10, fontweight='bold')
    ax2.set_title('QC Sample Total Intensity', fontsize=12, fontweight='bold')
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(qc_names, rotation=45, fontsize=8, ha='right')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3, axis='y')
    
    # === 子圖 3: QC 相關性熱圖（標準化前）===
    ax3 = fig.add_subplot(gs[0, 2])
    
    corr_before = np.corrcoef(original_qc.T)
    im3 = ax3.imshow(corr_before, cmap='coolwarm', vmin=0.9, vmax=1, aspect='auto')
    ax3.set_xticks(range(len(qc_names)))
    ax3.set_yticks(range(len(qc_names)))
    ax3.set_xticklabels(qc_names, rotation=45, fontsize=8, ha='right')
    ax3.set_yticklabels(qc_names, fontsize=8)
    ax3.set_title('QC Correlation (Before)', fontsize=12, fontweight='bold')
    plt.colorbar(im3, ax=ax3, label='Correlation', fraction=0.046)
    
    # 在格子中顯示數值
    for i in range(len(qc_names)):
        for j in range(len(qc_names)):
            text = ax3.text(j, i, f'{corr_before[i, j]:.3f}',
                           ha="center", va="center", color="black", fontsize=7)
    
    # === 子圖 4: QC 相關性熱圖（標準化後）===
    ax4 = fig.add_subplot(gs[1, 2])
    
    corr_after = np.corrcoef(normalized_qc.T)
    im4 = ax4.imshow(corr_after, cmap='coolwarm', vmin=0.9, vmax=1, aspect='auto')
    ax4.set_xticks(range(len(qc_names)))
    ax4.set_yticks(range(len(qc_names)))
    ax4.set_xticklabels(qc_names, rotation=45, fontsize=8, ha='right')
    ax4.set_yticklabels(qc_names, fontsize=8)
    ax4.set_title('QC Correlation (After)', fontsize=12, fontweight='bold')
    plt.colorbar(im4, ax=ax4, label='Correlation', fraction=0.046)
    
    for i in range(len(qc_names)):
        for j in range(len(qc_names)):
            text = ax4.text(j, i, f'{corr_after[i, j]:.3f}',
                           ha="center", va="center", color="black", fontsize=7)
    
    # === 子圖 5: CV% 改善散點圖 ===
    ax5 = fig.add_subplot(gs[1, 0])
    
    ax5.scatter(cv_before, cv_after, alpha=0.5, s=20, color='steelblue')
    
    max_cv = max(np.max(cv_before), np.max(cv_after))
    ax5.plot([0, max_cv], [0, max_cv], 'r--', linewidth=2, label='No change')
    ax5.plot([0, max_cv], [0, max_cv*0.8], 'orange', linestyle='--', 
             linewidth=1, alpha=0.5, label='-20%')
    
    ax5.set_xlabel('CV% Before', fontsize=10, fontweight='bold')
    ax5.set_ylabel('CV% After', fontsize=10, fontweight='bold')
    ax5.set_title('Feature-wise CV% Change', fontsize=12, fontweight='bold')
    ax5.legend(fontsize=8)
    ax5.grid(True, alpha=0.3)
    
    # === 子圖 6: 盒鬚圖對比 ===
    ax6 = fig.add_subplot(gs[1, 1])
    
    box_data = [cv_before, cv_after]
    bp = ax6.boxplot(box_data, labels=['Before', 'After'], patch_artist=True,
                     showfliers=True, widths=0.6)
    
    bp['boxes'][0].set_facecolor('lightblue')
    bp['boxes'][1].set_facecolor('lightcoral')
    
    ax6.set_ylabel('CV%', fontsize=10, fontweight='bold')
    ax6.set_title('QC CV% Distribution Comparison', fontsize=12, fontweight='bold')
    ax6.grid(True, alpha=0.3, axis='y')
    ax6.axhline(y=20, color='orange', linestyle='--', linewidth=1, alpha=0.5, label='20% threshold')
    ax6.legend(fontsize=8)
    
    # === 子圖 7-9: 統計摘要文字 ===
    ax7 = fig.add_subplot(gs[2, :])
    ax7.axis('off')
    
    # 計算統計資訊
    median_cv_before = np.median(cv_before)
    median_cv_after = np.median(cv_after)
    cv_improvement = median_cv_before - median_cv_after
    
    features_below_20_before = np.sum(cv_before < 20) / len(cv_before) * 100
    features_below_20_after = np.sum(cv_after < 20) / len(cv_after) * 100
    
    mean_corr_before = np.mean(corr_before[np.triu_indices_from(corr_before, k=1)])
    mean_corr_after = np.mean(corr_after[np.triu_indices_from(corr_after, k=1)])
    
    # 組織文字
    summary_text = f"""
╔════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                                    QC QUALITY ASSESSMENT SUMMARY                                    ║
╚════════════════════════════════════════════════════════════════════════════════════════════════════╝

【CV% Metrics】
  ├─ Before Normalization:        {median_cv_before:6.2f}%  (Median)    {np.mean(cv_before):6.2f}%  (Mean)
  ├─ After Normalization:         {median_cv_after:6.2f}%  (Median)    {np.mean(cv_after):6.2f}%  (Mean)
  └─ Improvement:                 {cv_improvement:6.2f}%  ({(cv_improvement/median_cv_before)*100:+.1f}%)

【Features with CV% < 20%】
  ├─ Before:    {features_below_20_before:5.1f}%  ({int(features_below_20_before * len(cv_before) / 100)}/{len(cv_before)} features)
  └─ After:     {features_below_20_after:5.1f}%  ({int(features_below_20_after * len(cv_after) / 100)}/{len(cv_after)} features)

【QC Sample Correlation】
  ├─ Before:    {mean_corr_before:.4f}  (Mean inter-QC correlation)
  └─ After:     {mean_corr_after:.4f}  (Mean inter-QC correlation)

【Total Intensity Stability】
  ├─ CV% Before:    {(np.std(total_before)/np.mean(total_before))*100:5.2f}%
  └─ CV% After:     {(np.std(total_after)/np.mean(total_after))*100:5.2f}%

【Overall QC Quality Rating】"""
    
    # 評級
    if median_cv_after < 15 and features_below_20_after > 80:
        summary_text += "\n  ★★★★★  EXCELLENT  -  QC samples show outstanding stability and reproducibility"
        color = 'green'
    elif median_cv_after < 20 and features_below_20_after > 70:
        summary_text += "\n  ★★★★    GOOD      -  QC samples show good stability, suitable for analysis"
        color = 'blue'
    elif median_cv_after < 25:
        summary_text += "\n  ★★★     ACCEPTABLE -  QC samples show acceptable stability"
        color = 'orange'
    else:
        summary_text += "\n  ★★      NEEDS IMPROVEMENT - Consider reviewing experimental procedures"
        color = 'red'
    
    ax7.text(0.5, 0.5, summary_text, transform=ax7.transAxes,
            fontsize=9, verticalalignment='center', horizontalalignment='center',
            family='monospace',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8, edgecolor=color, linewidth=2))
    
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ QC 質量評估圖已儲存")

# ==================== 輔助函數 ====================

def is_numeric_value(value):
    """檢查值是否為有效的數值"""
    if pd.isna(value):
        return False
    try:
        float_val = float(value)
        return float_val > 0
    except (ValueError, TypeError):
        return False

def get_non_qc_columns(df, sample_info_df):
    """獲取非QC樣本的欄位列表"""
    non_qc_columns = []
    
    sample_type_dict = {}
    for idx, row in sample_info_df.iterrows():
        sample_name = row.iloc[0]
        sample_type = str(row.get('Sample_Type', '')).upper()
        sample_type_dict[sample_name] = sample_type
    
    for col in df.columns:
        if col != df.columns[0]:
            if col in sample_type_dict:
                if sample_type_dict[col] != 'QC':
                    non_qc_columns.append(col)
            else:
                if not col.upper().startswith('QC'):
                    non_qc_columns.append(col)
    
    return non_qc_columns

def get_sample_columns_only(df, sample_info_df):
    """
    獲取純樣本欄位（排除QC和統計欄位）
    """
    # 排除的統計欄位關鍵字
    exclude_keywords = [
        'CV', 'Silhouette', 'Permutation', 'Correlation', 
        'R_squared', 'Improvement', 'Before', 'After', 
        'Original', 'Corrected', 'pvalue', 'p_value'
    ]
    
    sample_columns = []
    
    # 建立樣本類型對應字典
    sample_type_dict = {}
    for idx, row in sample_info_df.iterrows():
        sample_name = row.iloc[0]
        sample_type = str(row.get('Sample_Type', '')).upper()
        sample_type_dict[sample_name] = sample_type
    
    for col in df.columns:
        if col == df.columns[0]:  # 跳過第一欄（特徵ID）
            continue
        
        # 檢查是否包含排除關鍵字
        is_stat_column = any(keyword.lower() in str(col).lower() for keyword in exclude_keywords)
        
        if not is_stat_column:
            # 檢查是否為QC樣本
            if col in sample_type_dict:
                if sample_type_dict[col] != 'QC':
                    sample_columns.append(col)
            else:
                if not col.upper().startswith('QC'):
                    sample_columns.append(col)
    
    return sample_columns

def calculate_cv_per_feature(data_matrix):
    """
    計算每個特徵的CV%
    
    Parameters:
    -----------
    data_matrix : np.ndarray
        數據矩陣 (特徵 x 樣本)
    
    Returns:
    --------
    cv_values : np.ndarray
        每個特徵的CV%
    """
    mean = np.nanmean(data_matrix, axis=1)
    std = np.nanstd(data_matrix, axis=1)
    cv = (std / mean) * 100
    return cv

def calculate_rsd(data_matrix):
    """計算相對標準偏差 (RSD%)"""
    mean = np.nanmean(data_matrix, axis=1, keepdims=True)
    std = np.nanstd(data_matrix, axis=1, keepdims=True)
    rsd = (std / mean) * 100
    return rsd.flatten()

def calculate_sample_correlation(data_matrix):
    """計算樣本間的相關性"""
    # 移除含有NaN的特徵
    valid_features = ~np.isnan(data_matrix).any(axis=1)
    clean_data = data_matrix[valid_features, :]
    
    if clean_data.shape[0] < 3:
        return np.nan, np.nan
    
    corr_matrix = np.corrcoef(clean_data.T)
    mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
    correlations = corr_matrix[mask]
    return np.mean(correlations), np.std(correlations)

# ==================== 視覺化函數 ====================

def plot_density_comparison(original_data, normalized_data, sample_names, output_path, method_name):
    """繪製標準化前後的密度圖對比"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # 標準化前
    for i in range(min(original_data.shape[1], 30)):  # 最多顯示30個樣本
        sample_data = original_data[:, i]
        sample_data = sample_data[sample_data > 0]
        if len(sample_data) > 0:
            ax1.hist(np.log10(sample_data), bins=50, alpha=0.3, density=True)
    
    ax1.set_xlabel('Log10(Intensity)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Density', fontsize=12, fontweight='bold')
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    
    # 標準化後
    for i in range(min(normalized_data.shape[1], 30)):
        sample_data = normalized_data[:, i]
        sample_data = sample_data[sample_data > 0]
        if len(sample_data) > 0:
            ax2.hist(np.log10(sample_data), bins=50, alpha=0.3, density=True)
    
    ax2.set_xlabel('Log10(Intensity)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Density', fontsize=12, fontweight='bold')
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ 密度圖已儲存")

def plot_boxplot_comparison(original_data, normalized_data, sample_names, output_path, method_name):
    """繪製標準化前後的盒鬚圖對比"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(max(16, len(sample_names)*0.5), 10))
    
    # 準備數據（取對數）
    original_log = np.log10(original_data + 1)
    normalized_log = np.log10(normalized_data + 1)
    
    # 標準化前
    positions = np.arange(len(sample_names))
    bp1 = ax1.boxplot([original_log[:, i] for i in range(len(sample_names))],
                       positions=positions,
                       widths=0.6,
                       patch_artist=True,
                       showfliers=False)
    
    for patch in bp1['boxes']:
        patch.set_facecolor('lightblue')
        patch.set_alpha(0.7)
    
    ax1.set_ylabel('Log10(Intensity + 1)', fontsize=12, fontweight='bold')
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    ax1.set_xticks(positions)
    ax1.set_xticklabels(sample_names, rotation=90, fontsize=8)
    ax1.grid(True, alpha=0.3, axis='y')
    
    # 標準化後
    bp2 = ax2.boxplot([normalized_log[:, i] for i in range(len(sample_names))],
                       positions=positions,
                       widths=0.6,
                       patch_artist=True,
                       showfliers=False)
    
    for patch in bp2['boxes']:
        patch.set_facecolor('lightcoral')
        patch.set_alpha(0.7)
    
    ax2.set_ylabel('Log10(Intensity + 1)', fontsize=12, fontweight='bold')
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    ax2.set_xticks(positions)
    ax2.set_xticklabels(sample_names, rotation=90, fontsize=8)
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ 盒鬚圖已儲存")

def plot_sample_distribution(original_data, normalized_data, sample_names, output_path, method_name):
    """繪製樣本總強度分佈圖"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(max(16, len(sample_names)*0.5), 6))
    
    # 計算每個樣本的總強度
    original_totals = np.nansum(original_data, axis=0)
    normalized_totals = np.nansum(normalized_data, axis=0)
    
    # 標準化前
    positions = np.arange(len(sample_names))
    ax1.bar(positions, original_totals, color='steelblue', alpha=0.7)
    ax1.axhline(y=np.median(original_totals), color='red', linestyle='--', 
                linewidth=2, label=f'Median: {np.median(original_totals):.2e}')
    ax1.set_ylabel('Total Intensity', fontsize=12, fontweight='bold')
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    ax1.set_xticks(positions)
    ax1.set_xticklabels(sample_names, rotation=90, fontsize=8)
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')
    
    # 標準化後
    ax2.bar(positions, normalized_totals, color='coral', alpha=0.7)
    ax2.axhline(y=np.median(normalized_totals), color='red', linestyle='--', 
                linewidth=2, label=f'Median: {np.median(normalized_totals):.2e}')
    ax2.set_ylabel('Total Intensity', fontsize=12, fontweight='bold')
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    ax2.set_xticks(positions)
    ax2.set_xticklabels(sample_names, rotation=90, fontsize=8)
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ 樣本分佈圖已儲存")

def plot_cv_comparison(original_cv, normalized_cv, output_path, method_name):
    """繪製CV%分佈對比圖"""
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(20, 5))
    
    # 移除 NaN 值
    original_cv_clean = original_cv[~np.isnan(original_cv)]
    normalized_cv_clean = normalized_cv[~np.isnan(normalized_cv)]
    
    # 1. 標準化前CV%分佈
    ax1.hist(original_cv_clean, bins=50, color='steelblue', alpha=0.7, edgecolor='black')
    ax1.axvline(x=np.median(original_cv_clean), color='red', linestyle='--', 
                linewidth=2, label=f'Median: {np.median(original_cv_clean):.2f}%')
    ax1.axvline(x=np.mean(original_cv_clean), color='orange', linestyle='--', 
                linewidth=2, label=f'Mean: {np.mean(original_cv_clean):.2f}%')
    ax1.set_xlabel('CV%', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. 標準化後CV%分佈
    ax2.hist(normalized_cv_clean, bins=50, color='coral', alpha=0.7, edgecolor='black')
    ax2.axvline(x=np.median(normalized_cv_clean), color='red', linestyle='--', 
                linewidth=2, label=f'Median: {np.median(normalized_cv_clean):.2f}%')
    ax2.axvline(x=np.mean(normalized_cv_clean), color='orange', linestyle='--', 
                linewidth=2, label=f'Mean: {np.mean(normalized_cv_clean):.2f}%')
    ax2.set_xlabel('CV%', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. CV%改善分佈
    cv_improvement = original_cv_clean - normalized_cv_clean[:len(original_cv_clean)]
    ax3.hist(cv_improvement, bins=50, color='green', alpha=0.7, edgecolor='black')
    ax3.axvline(x=0, color='black', linestyle='-', linewidth=2)
    ax3.axvline(x=np.median(cv_improvement), color='red', linestyle='--', 
                linewidth=2, label=f'Median: {np.median(cv_improvement):.2f}%')
    ax3.set_xlabel('CV% Improvement', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax3.set_title('CV% Improvement Distribution', fontsize=14, fontweight='bold')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # 添加統計文字
    improved_count = np.sum(cv_improvement > 0)
    total_count = len(cv_improvement)
    improvement_rate = (improved_count / total_count) * 100
    
    stats_text = f"Improved: {improved_count}/{total_count} ({improvement_rate:.1f}%)"
    ax3.text(0.05, 0.95, stats_text, transform=ax3.transAxes,
            fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ CV%分佈圖已儲存")

def plot_pca_comparison(original_data, normalized_data, sample_names, sample_info_df, output_path, method_name):
    """繪製PCA對比圖（標準化前後）"""
    # 數據預處理（轉置：樣本 x 特徵）
    original_transposed = original_data.T
    normalized_transposed = normalized_data.T
    
    # 移除含有NaN的樣本
    valid_samples_orig = ~np.isnan(original_transposed).any(axis=1)
    valid_samples_norm = ~np.isnan(normalized_transposed).any(axis=1)
    valid_samples = valid_samples_orig & valid_samples_norm
    
    if np.sum(valid_samples) < 3:
        print("  ⚠ 有效樣本數不足，無法進行PCA分析")
        return
    
    original_clean = original_transposed[valid_samples]
    normalized_clean = normalized_transposed[valid_samples]
    sample_names_clean = [sample_names[i] for i in range(len(sample_names)) if valid_samples[i]]
    
    # 獲取樣本分組信息
    sample_groups = []
    for sample in sample_names_clean:
        sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
        if not sample_row.empty:
            sample_type = str(sample_row.iloc[0].get('Sample_Type', 'Unknown')).upper()
            sample_groups.append(sample_type)
        else:
            sample_groups.append('Unknown')
    
    # 顏色映射
    unique_groups = list(set(sample_groups))
    colors = plt.cm.Set3(np.linspace(0, 1, len(unique_groups)))
    color_map = {group: colors[i] for i, group in enumerate(unique_groups)}
    sample_colors = [color_map[group] for group in sample_groups]
    
    # 標準化（用於PCA）
    scaler_orig = StandardScaler()
    scaler_norm = StandardScaler()
    
    original_scaled = scaler_orig.fit_transform(original_clean)
    normalized_scaled = scaler_norm.fit_transform(normalized_clean)
    
    # PCA
    pca = PCA(n_components=2)
    pc_original = pca.fit_transform(original_scaled)
    var_original = pca.explained_variance_ratio_
    
    pca = PCA(n_components=2)
    pc_normalized = pca.fit_transform(normalized_scaled)
    var_normalized = pca.explained_variance_ratio_
    
    # 繪圖
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))
    
    # 標準化前
    for group in unique_groups:
        mask = [g == group for g in sample_groups]
        ax1.scatter(pc_original[mask, 0], pc_original[mask, 1], 
                   c=[color_map[group]], label=group, s=100, alpha=0.7, edgecolors='black', linewidth=1.5)
    
    ax1.set_xlabel(f'PC1 ({var_original[0]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax1.set_ylabel(f'PC2 ({var_original[1]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color='k', linestyle='--', linewidth=1, alpha=0.5)
    ax1.axvline(x=0, color='k', linestyle='--', linewidth=1, alpha=0.5)
    
    # 標準化後
    for group in unique_groups:
        mask = [g == group for g in sample_groups]
        ax2.scatter(pc_normalized[mask, 0], pc_normalized[mask, 1], 
                   c=[color_map[group]], label=group, s=100, alpha=0.7, edgecolors='black', linewidth=1.5)
    
    ax2.set_xlabel(f'PC1 ({var_normalized[0]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax2.set_ylabel(f'PC2 ({var_normalized[1]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    ax2.legend(loc='best', fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=0, color='k', linestyle='--', linewidth=1, alpha=0.5)
    ax2.axvline(x=0, color='k', linestyle='--', linewidth=1, alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ PCA對比圖已儲存")

def plot_correlation_heatmap(original_data, normalized_data, sample_names, output_path, method_name):
    """繪製樣本相關性熱圖（標準化前後）"""
    # 計算相關性矩陣
    corr_original = np.corrcoef(original_data.T)
    corr_normalized = np.corrcoef(normalized_data.T)
    
    # 繪圖
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))
    
    # 標準化前
    im1 = ax1.imshow(corr_original, cmap='coolwarm', vmin=-1, vmax=1, aspect='auto')
    ax1.set_xticks(range(len(sample_names)))
    ax1.set_yticks(range(len(sample_names)))
    ax1.set_xticklabels(sample_names, rotation=90, fontsize=8)
    ax1.set_yticklabels(sample_names, fontsize=8)
    ax1.set_title('Before Normalization', fontsize=14, fontweight='bold')
    plt.colorbar(im1, ax=ax1, label='Correlation')
    
    # 標準化後
    im2 = ax2.imshow(corr_normalized, cmap='coolwarm', vmin=-1, vmax=1, aspect='auto')
    ax2.set_xticks(range(len(sample_names)))
    ax2.set_yticks(range(len(sample_names)))
    ax2.set_xticklabels(sample_names, rotation=90, fontsize=8)
    ax2.set_yticklabels(sample_names, fontsize=8)
    ax2.set_title(f'After Normalization ({method_name})', fontsize=14, fontweight='bold')
    plt.colorbar(im2, ax=ax2, label='Correlation')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"  ✓ 相關性熱圖已儲存")

# ==================== 評估函數 ====================

def evaluate_normalization_quality(original_data, normalized_data):
    """綜合評估標準化質量"""
    results = {}
    
    # 1. CV% 評估
    original_cv = calculate_rsd(original_data)
    normalized_cv = calculate_rsd(normalized_data)
    
    results['median_cv_before'] = np.nanmedian(original_cv)
    results['median_cv_after'] = np.nanmedian(normalized_cv)
    results['mean_cv_before'] = np.nanmean(original_cv)
    results['mean_cv_after'] = np.nanmean(normalized_cv)
    results['cv_improvement'] = results['median_cv_before'] - results['median_cv_after']
    results['cv_improvement_pct'] = (results['cv_improvement'] / results['median_cv_before']) * 100 if results['median_cv_before'] > 0 else 0
    
    # CV%改善的特徵比例
    cv_improved = np.sum((original_cv - normalized_cv) > 0)
    cv_total = len(original_cv[~np.isnan(original_cv)])
    results['cv_improved_ratio'] = (cv_improved / cv_total) * 100 if cv_total > 0 else 0
    
    # 2. 樣本總強度變異
    original_totals = np.nansum(original_data, axis=0)
    normalized_totals = np.nansum(normalized_data, axis=0)
    
    results['total_cv_before'] = (np.nanstd(original_totals) / np.nanmean(original_totals)) * 100
    results['total_cv_after'] = (np.nanstd(normalized_totals) / np.nanmean(normalized_totals)) * 100
    results['total_cv_improvement'] = results['total_cv_before'] - results['total_cv_after']
    
    # 3. 樣本間相關性
    corr_mean_before, corr_std_before = calculate_sample_correlation(original_data)
    corr_mean_after, corr_std_after = calculate_sample_correlation(normalized_data)
    
    results['sample_corr_mean_before'] = corr_mean_before
    results['sample_corr_mean_after'] = corr_mean_after
    results['sample_corr_std_before'] = corr_std_before
    results['sample_corr_std_after'] = corr_std_after
    
    # 4. 數據範圍評估
    results['data_range_before'] = np.nanmax(original_data) - np.nanmin(original_data)
    results['data_range_after'] = np.nanmax(normalized_data) - np.nanmin(normalized_data)
    
    return results

def create_normalization_summary_report(quality_metrics, method_name, n_features, n_samples,
                                       pqn_info=None, normality_results=None, group_diff_results=None):
    """
    建立增強版標準化摘要報告
    
    Parameters:
    -----------
    quality_metrics : dict
        標準化質量指標
    method_name : str
        標準化方法名稱
    n_features : int
        特徵數量
    n_samples : int
        樣本數量
    pqn_info : dict, optional
        PQN 相關資訊
    normality_results : dict, optional
        正態性檢驗結果
    group_diff_results : dict, optional
        組間差異評估結果
    
    Returns:
    --------
    str : 格式化的報告文字
    """
    report = []
    report.append("=" * 80)
    report.append(f"標準化效果摘要報告 - {method_name}")
    report.append(f"報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)
    
    # ========== 基本資訊 ==========
    report.append("")
    report.append("【基本資訊】")
    report.append(f"標準化方法: {method_name}")
    report.append(f"特徵數量: {n_features}")
    report.append(f"樣本數量: {n_samples}")
    
    # ========== PQN 參考樣本資訊（新增）==========
    if pqn_info:
        report.append("")
        report.append("【PQN 參考樣本資訊】")
        report.append(f"參考策略: {pqn_info['reference_strategy']}")
        report.append(f"QC 樣本數量: {pqn_info['qc_count']}")
        report.append(f"真實樣本數量: {pqn_info['real_count']}")
        
        if pqn_info['qc_count'] > 0 and not np.isnan(pqn_info['qc_cv']):
            report.append(f"QC 中位數 CV%: {pqn_info['qc_cv']:.2f}%")
            if pqn_info['qc_cv'] < 20:
                report.append("QC 質量評估: ✓✓ 優秀")
            elif pqn_info['qc_cv'] < 30:
                report.append("QC 質量評估: ✓ 良好")
            else:
                report.append("QC 質量評估: ⚠ 需改進")
        
        report.append(f"肌酐校正:")
        report.append(f"  - 肌酐中位數: {pqn_info['creatinine_median']:.2f}")
        report.append(f"  - 有效樣本數: {pqn_info['creatinine_valid_count']}/{pqn_info['real_count']}")
    
    # ========== CV% 評估 ==========
    report.append("")
    report.append("【CV% 評估】")
    report.append(f"標準化前:")
    report.append(f"  - 中位數CV%: {quality_metrics['median_cv_before']:.2f}%")
    report.append(f"  - 平均CV%: {quality_metrics['mean_cv_before']:.2f}%")
    report.append(f"標準化後:")
    report.append(f"  - 中位數CV%: {quality_metrics['median_cv_after']:.2f}%")
    report.append(f"  - 平均CV%: {quality_metrics['mean_cv_after']:.2f}%")
    report.append(f"改善:")
    report.append(f"  - CV%降低: {quality_metrics['cv_improvement']:.2f}%")
    report.append(f"  - 改善百分比: {quality_metrics['cv_improvement_pct']:.2f}%")
    report.append(f"  - CV%改善的特徵比例: {quality_metrics['cv_improved_ratio']:.1f}%")
    
    # ========== 樣本總強度變異 ==========
    report.append("")
    report.append("【樣本總強度變異】")
    report.append(f"標準化前總強度CV%: {quality_metrics['total_cv_before']:.2f}%")
    report.append(f"標準化後總強度CV%: {quality_metrics['total_cv_after']:.2f}%")
    report.append(f"總強度CV%改善: {quality_metrics['total_cv_improvement']:.2f}%")
    
    # ========== 樣本間相關性 ==========
    report.append("")
    report.append("【樣本間相關性】")
    if not np.isnan(quality_metrics['sample_corr_mean_before']):
        report.append(f"標準化前:")
        report.append(f"  - 平均相關性: {quality_metrics['sample_corr_mean_before']:.4f}")
        report.append(f"  - 相關性標準差: {quality_metrics['sample_corr_std_before']:.4f}")
        report.append(f"標準化後:")
        report.append(f"  - 平均相關性: {quality_metrics['sample_corr_mean_after']:.4f}")
        report.append(f"  - 相關性標準差: {quality_metrics['sample_corr_std_after']:.4f}")
    else:
        report.append("  - 數據不足，無法計算樣本間相關性")
    
    # ========== 正態性檢驗結果（新增）==========
    if normality_results:
        report.append("")
        report.append("【正態性檢驗】(Shapiro-Wilk, α=0.05)")
        report.append(f"標準化前通過: {normality_results['n_normal_before']}/{n_features} ({normality_results['pct_before']:.1f}%)")
        report.append(f"標準化後通過: {normality_results['n_normal_after']}/{n_features} ({normality_results['pct_after']:.1f}%)")
        report.append(f"改善幅度: {normality_results['improvement']:+.1f}%")
        
        if normality_results['improvement'] > 10:
            report.append("評估: ✓✓ 正態性顯著改善")
        elif normality_results['improvement'] > 5:
            report.append("評估: ✓ 正態性有所改善")
        elif normality_results['improvement'] > 0:
            report.append("評估: ○ 正態性輕微改善")
        else:
            report.append("評估: ⚠ 正態性未改善")
    
    # ========== 組間差異保留評估（新增）==========
    if group_diff_results:
        report.append("")
        report.append("【組間差異保留評估】(Control vs Exposure)")
        report.append(f"Control 組樣本數: {group_diff_results['control_count']}")
        report.append(f"Exposure 組樣本數: {group_diff_results['exposure_count']}")
        report.append(f"分析特徵數: {group_diff_results['total']}")
        report.append(f"Effect Size 變化統計:")
        report.append(f"  - 增強: {group_diff_results['enhanced']} ({group_diff_results['enhanced']/group_diff_results['total']*100:.1f}%)")
        report.append(f"  - 穩定 (±10%): {group_diff_results['stable']} ({group_diff_results['stable']/group_diff_results['total']*100:.1f}%)")
        report.append(f"  - 輕度減弱: {group_diff_results['mild_reduction']} ({group_diff_results['mild_reduction']/group_diff_results['total']*100:.1f}%)")
        report.append(f"  - 顯著減弱: {group_diff_results['severe_reduction']} ({group_diff_results['severe_reduction']/group_diff_results['total']*100:.1f}%)")
        report.append(f"平均 Effect Size 保留率: {group_diff_results['avg_preservation']:.1f}%")
        
        if group_diff_results['severe_reduction'] / group_diff_results['total'] > 0.1:
            report.append("評估: ⚠⚠ 部分特徵差異顯著減弱，需檢查")
        elif group_diff_results['avg_preservation'] > 90:
            report.append("評估: ✓✓ 組間差異保留優秀")
        elif group_diff_results['avg_preservation'] > 80:
            report.append("評估: ✓ 組間差異保留良好")
        else:
            report.append("評估: ○ 組間差異保留尚可")
    
    # ========== 評估結論 ==========
    report.append("")
    report.append("【評估結論】")
    
    # CV%評估
    if quality_metrics['cv_improvement'] > 0:
        if quality_metrics['cv_improvement_pct'] > 20:
            report.append("✓✓✓ CV%顯著降低，標準化效果極佳")
        elif quality_metrics['cv_improvement_pct'] > 10:
            report.append("✓✓ CV%明顯降低，標準化效果良好")
        else:
            report.append("✓ CV%略有降低，標準化效果尚可")
    else:
        report.append("⚠ CV%未降低，建議檢查數據或嘗試其他標準化方法")
    
    # 總強度變異評估
    if quality_metrics['total_cv_improvement'] > 0:
        if quality_metrics['total_cv_improvement'] > 10:
            report.append("✓✓ 樣本總強度變異顯著降低")
        else:
            report.append("✓ 樣本總強度變異有所降低")
    else:
        report.append("⚠ 樣本總強度變異未改善")
    
    # 樣本間相關性評估
    if not np.isnan(quality_metrics['sample_corr_std_before']):
        if quality_metrics['sample_corr_std_after'] < quality_metrics['sample_corr_std_before']:
            report.append("✓ 樣本間相關性更一致")
        else:
            report.append("⚠ 樣本間相關性一致性未改善")
    
    # 特徵改善比例評估
    if quality_metrics['cv_improved_ratio'] > 70:
        report.append(f"✓✓ 大多數特徵({quality_metrics['cv_improved_ratio']:.1f}%)的CV%得到改善")
    elif quality_metrics['cv_improved_ratio'] > 50:
        report.append(f"✓ 超過半數特徵({quality_metrics['cv_improved_ratio']:.1f}%)的CV%得到改善")
    else:
        report.append(f"⚠ 僅{quality_metrics['cv_improved_ratio']:.1f}%的特徵CV%得到改善")
    
    # ========== 整體評分（更新評分邏輯）==========
    report.append("")
    report.append("【整體評分】")
    score = 0
    max_score = 100
    
    # CV% 改善 (25 分)
    if quality_metrics['cv_improvement'] > 0:
        if quality_metrics['cv_improvement_pct'] > 20:
            score += 25
        elif quality_metrics['cv_improvement_pct'] > 10:
            score += 20
        else:
            score += 15
    
    # 總強度變異改善 (20 分)
    if quality_metrics['total_cv_improvement'] > 0:
        if quality_metrics['total_cv_improvement'] > 10:
            score += 20
        else:
            score += 15
    
    # 樣本間相關性改善 (15 分)
    if not np.isnan(quality_metrics['sample_corr_std_before']):
        if quality_metrics['sample_corr_std_after'] < quality_metrics['sample_corr_std_before']:
            score += 15
    
    # 正態性改善 (20 分) - 新增
    if normality_results:
        if normality_results['improvement'] > 10:
            score += 20
        elif normality_results['improvement'] > 5:
            score += 15
        elif normality_results['improvement'] > 0:
            score += 10
    
    # 組間差異保留 (20 分) - 新增
    if group_diff_results:
        if group_diff_results['avg_preservation'] > 90:
            score += 20
        elif group_diff_results['avg_preservation'] > 80:
            score += 15
        elif group_diff_results['avg_preservation'] > 70:
            score += 10
        
        # 嚴重減弱特徵的懲罰
        if group_diff_results['severe_reduction'] / group_diff_results['total'] > 0.1:
            score -= 10
            report.append("  ⚠ 警告：超過 10% 的特徵 Effect Size 顯著減弱（-10 分）")
    
    report.append(f"標準化質量評分: {score}/{max_score}")
    if score >= 85:
        report.append("評級: 優秀 ★★★★★")
    elif score >= 70:
        report.append("評級: 良好 ★★★★")
    elif score >= 50:
        report.append("評級: 尚可 ★★★")
    else:
        report.append("評級: 需改進 ★★")
    
    # ========== 建議與注意事項（新增）==========
    report.append("")
    report.append("【建議與注意事項】")
    
    # QC 相關建議
    if pqn_info:
        if pqn_info['qc_count'] < 3:
            report.append("⚠ 建議：QC 樣本數量較少，建議至少使用 3 個 QC 樣本以提高標準化穩定性")
        
        if not np.isnan(pqn_info['qc_cv']) and pqn_info['qc_cv'] > 25:
            report.append("⚠ 建議：QC CV% 較高，可能需要檢查實驗技術重現性")
        
        if pqn_info['creatinine_valid_count'] < pqn_info['real_count'] * 0.9:
            report.append(f"⚠ 注意：有 {pqn_info['real_count'] - pqn_info['creatinine_valid_count']} 個樣本缺少有效肌酐值")
    
    # 正態性相關建議
    if normality_results and normality_results['pct_after'] < 50:
        report.append("⚠ 建議：仍有超過一半的特徵不符合正態分佈，進行統計分析時建議使用非參數檢驗")
    
    # 組間差異相關建議
    if group_diff_results:
        if group_diff_results['severe_reduction'] > 0:
            report.append(f"⚠ 注意：有 {group_diff_results['severe_reduction']} 個特徵的組間差異顯著減弱")
            report.append("  建議：檢查這些特徵是否與肌酐代謝相關，可能需要特別處理")
        
        if group_diff_results['avg_preservation'] < 80:
            report.append("⚠ 建議：組間差異保留率較低，建議檢查標準化方法是否適合您的數據")
    
    # CV% 改善相關建議
    if quality_metrics['cv_improved_ratio'] < 50:
        report.append("⚠ 建議：僅不到一半的特徵 CV% 得到改善，可能需要考慮其他標準化方法")
    
    # 如果所有指標都良好
    if (quality_metrics['cv_improvement_pct'] > 20 and 
        quality_metrics['total_cv_improvement'] > 10 and
        (normality_results is None or normality_results['improvement'] > 10) and
        (group_diff_results is None or group_diff_results['avg_preservation'] > 90)):
        report.append("✓✓✓ 恭喜！所有評估指標均表現優異，標準化效果極佳")
    
    report.append("")
    report.append("=" * 80)
    
    return "\n".join(report)

# ==================== 檔案處理函數 ====================

def select_file():
    """讓使用者選擇Excel檔案"""
    root = tk.Tk()
    root.withdraw()
    
    file_path = filedialog.askopenfilename(
        title="請選擇Excel檔案",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    
    if not file_path:
        print("未選擇檔案，程式結束。")
        return None
    
    return file_path

def load_excel_sheets(file_path):
    """載入Excel檔案的所有工作表"""
    try:
        xl_file = pd.ExcelFile(file_path)
        sheet_names = xl_file.sheet_names
        
        sheets = {}
        for sheet_name in sheet_names:
            sheets[sheet_name] = pd.read_excel(file_path, sheet_name=sheet_name)
            
        return sheets, sheet_names
    except Exception as e:
        print(f"讀取Excel檔案時發生錯誤: {e}")
        return None, None

def determine_correction_sheet(sheets):
    """按指定順序確定要標準化的資料工作表"""
    priority_sheets = [
        "Batch_effect_result",
        "QC LOWESS result", 
        "ISTD_Correction", 
        "RawIntensity"
    ]
    
    for sheet_name in priority_sheets:
        if sheet_name in sheets:
            print(f"✓ 依優先順序選擇工作表: {sheet_name}")
            return sheets[sheet_name], sheet_name
    
    print("警告：未找到指定的資料工作表")
    return None, None

def find_sample_info_sheet(sheets):
    """尋找包含樣本資訊的工作表"""
    possible_names = ['SampleInfo', 'Sample_Info', 'sample_info', 'Sample Info']
    
    for name in possible_names:
        if name in sheets:
            return sheets[name], name
    
    for sheet_name, df in sheets.items():
        if any(col for col in df.columns if 'normalization' in str(col).lower() or 'creatinine' in str(col).lower()):
            return df, sheet_name
    
    return None, None

def find_correction_column(df):
    """在樣本資訊工作表中尋找可用於校正的欄位"""
    if df.shape[1] < 6:
        print("警告：樣本資訊工作表欄位不足")
        return None, None
    
    # 預設使用第 F 欄（索引 5）
    correction_col = df.columns[5]
    valid_values = df[correction_col].dropna()
    
    if len(valid_values) > 0:
        # 檢查是否為數值
        numeric_count = valid_values.apply(lambda x: str(x).replace('.','').replace('-','').replace('e','').replace('E','').replace('+','').isnumeric()).sum()
        if numeric_count / len(valid_values) > 0.5:
            if 'creatinine' in str(correction_col).lower():
                correction_type = 'Creatinine'
            else:
                correction_type = 'Normalization_adduct'
            
            print(f"✓ 偵測到校正欄位: {correction_col} (類型: {correction_type})")
            return correction_col, correction_type
    
    # 如果第 F 欄不可用，嘗試找其他可用的數值欄位
    for col in df.columns[6:]:
        valid_values = df[col].dropna()
        if len(valid_values) > 0:
            numeric_count = valid_values.apply(lambda x: str(x).replace('.','').replace('-','').replace('e','').replace('E','').replace('+','').isnumeric()).sum()
            if numeric_count / len(valid_values) > 0.5:
                if 'creatinine' in str(col).lower():
                    correction_type = 'Creatinine'
                else:
                    correction_type = 'Normalization_adduct'
                
                print(f"✓ 偵測到校正欄位: {col} (類型: {correction_type})")
                return col, correction_type
    
    print("錯誤：找不到可用於校正的欄位")
    return None, None

def clean_dataframe_for_excel(df):
    """清理DataFrame以避免Excel格式問題"""
    cleaned_df = df.copy()
    
    for col in cleaned_df.columns:
        str_series = cleaned_df[col].astype(str)
        
        # 移除公式
        mask_formula = str_series.str.startswith('=')
        cleaned_df.loc[mask_formula, col] = ''
        
        # 移除Excel錯誤值
        error_values = ['#REF!', '#VALUE!', '#NAME?', '#DIV/0!', '#N/A', '#NULL!', '#NUM!']
        for error_val in error_values:
            cleaned_df[col] = cleaned_df[col].replace(error_val, '')
        
        # 嘗試轉換數值欄位
        if col != cleaned_df.columns[0]:
            cleaned_df[col] = pd.to_numeric(cleaned_df[col], errors='ignore')
    
    return cleaned_df

def copy_cell_style(src_cell, dest_cell):
    """完整複製儲存格的所有樣式和格式"""
    try:
        if src_cell.font:
            dest_cell.font = Font(
                name=src_cell.font.name,
                size=src_cell.font.size,
                bold=src_cell.font.bold,
                italic=src_cell.font.italic,
                underline=src_cell.font.underline,
                strike=src_cell.font.strike,
                color=src_cell.font.color
            )
        
        if src_cell.fill:
            dest_cell.fill = PatternFill(
                fill_type=src_cell.fill.fill_type,
                start_color=src_cell.fill.start_color,
                end_color=src_cell.fill.end_color
            )
        
        if src_cell.border:
            dest_cell.border = Border(
                left=copy(src_cell.border.left),
                right=copy(src_cell.border.right),
                top=copy(src_cell.border.top),
                bottom=copy(src_cell.border.bottom)
            )
        
        if src_cell.alignment:
            dest_cell.alignment = Alignment(
                horizontal=src_cell.alignment.horizontal,
                vertical=src_cell.alignment.vertical,
                wrap_text=src_cell.alignment.wrap_text
            )
        
        if src_cell.number_format:
            dest_cell.number_format = src_cell.number_format
        
    except Exception as style_error:
        pass

# ==================== 主要處理函數 ====================

def perform_normalization(data_df, sample_info_df, correction_col, file_path):
    """
    執行 PQN + Sample-specific 混合標準化處理（增強版）
    """
    print(f"\n" + "="*70)
    print("開始執行標準化處理...")
    print("="*70)
    
    method_name = "PQN_SampleSpecific"
    
    # 獲取純樣本欄位（排除統計欄位）
    sample_columns = get_all_sample_columns(data_df, sample_info_df)  # ← 改用新函數
    print(f"✓ 樣本數量（含QC）: {len(sample_columns)}")
    
    if len(sample_columns) == 0:
        print("錯誤：未找到有效的樣本欄位")
        return None
    
    # 準備數據矩陣 (特徵 x 樣本)
    data_matrix = []
    feature_ids = []
    
    for idx, row in data_df.iterrows():
        feature_ids.append(row[data_df.columns[0]])
        feature_values = []
        for col in sample_columns:
            if col in data_df.columns and is_numeric_value(row[col]):
                feature_values.append(float(row[col]))
            else:
                feature_values.append(np.nan)
        data_matrix.append(feature_values)
    
    data_matrix = np.array(data_matrix)
    print(f"✓ 數據矩陣形狀: {data_matrix.shape} (特徵 x 樣本)")
    
    # 保存原始數據用於對比
    original_data = data_matrix.copy()
    
    # 獲取參考值（肌酐濃度）
    reference_values = []
    
    for sample in sample_columns:
        sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
        if not sample_row.empty and pd.notna(sample_row.iloc[0][correction_col]):
            try:
                ref_val = float(sample_row.iloc[0][correction_col])
                if ref_val > 0:
                    reference_values.append(ref_val)
                else:
                    reference_values.append(np.nan)
            except:
                reference_values.append(np.nan)
        else:
            reference_values.append(np.nan)
    
    reference_values = np.array(reference_values)
    
    valid_count = np.sum(~np.isnan(reference_values) & (reference_values > 0))
    print(f"✓ 有效參考值數量: {valid_count}/{len(sample_columns)}")
    
    if valid_count < len(sample_columns) * 0.3:
        print("警告：有效參考值不足30%")
        return None
    
    # ========== 🔧 關鍵修正：正確呼叫 enhanced_pqn_normalization ==========
    normalized_data, pqn_info = enhanced_pqn_normalization(
        data_matrix,           # 完整的數據矩陣
        sample_info_df,        # 樣本資訊表
        sample_columns,        # 樣本名稱列表
        reference_values       # 參考值（肌酐濃度）
    )
    
    print(f"✓ 標準化完成")
    
    # 創建輸出資料夾
    output_dir = Path(file_path).parent / f"Normalization_Results_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir.mkdir(exist_ok=True)
    print(f"✓ 創建輸出資料夾: {output_dir.name}")
    
    # 分離有效樣本用於評估
    valid_sample_mask = ~np.isnan(normalized_data[0, :])
    original_data_valid = original_data[:, valid_sample_mask]
    normalized_data_valid = normalized_data[:, valid_sample_mask]
    sample_columns_valid = [sample_columns[i] for i in range(len(sample_columns)) if valid_sample_mask[i]]
    
    # ========== 評估標準化質量 ==========
    print("\n評估標準化質量...")
    quality_metrics = evaluate_normalization_quality(original_data_valid, normalized_data_valid)
    
    # ========== 新增：正態性檢驗 ==========
    try:
        normality_results = evaluate_normality(original_data_valid, normalized_data_valid, alpha=0.05)
    except Exception as e:
        print(f"  ⚠ 正態性檢驗失敗: {e}")
        normality_results = None
    
    # ========== 新增：組間差異保留評估 ==========
    try:
        group_diff_results = evaluate_group_difference_preservation(
            original_data_valid, normalized_data_valid, sample_info_df, sample_columns_valid
        )
    except Exception as e:
        print(f"  ⚠ 組間差異評估失敗: {e}")
        group_diff_results = None
    
    # ========== 生成視覺化圖表 ==========
    print("\n生成視覺化圖表...")
    
    # 1. 密度圖
    plot_density_comparison(
        original_data_valid, normalized_data_valid, sample_columns_valid,
        output_dir / f"Density_Plot_{method_name}.png",
        method_name
    )
    
    # 2. 盒鬚圖
    plot_boxplot_comparison(
        original_data_valid, normalized_data_valid, sample_columns_valid,
        output_dir / f"Boxplot_{method_name}.png",
        method_name
    )
    
    # 3. 樣本分佈圖
    plot_sample_distribution(
        original_data_valid, normalized_data_valid, sample_columns_valid,
        output_dir / f"Sample_Distribution_{method_name}.png",
        method_name
    )
    
    # 4. CV%分佈圖
    original_cv = calculate_cv_per_feature(original_data_valid)
    normalized_cv = calculate_cv_per_feature(normalized_data_valid)
    plot_cv_comparison(
        original_cv, normalized_cv,
        output_dir / f"CV_Distribution_{method_name}.png",
        method_name
    )
    
    # 5. PCA對比圖
    try:
        plot_pca_comparison(
            original_data_valid, normalized_data_valid, sample_columns_valid, sample_info_df,
            output_dir / f"PCA_Comparison_{method_name}.png",
            method_name
        )
    except Exception as e:
        print(f"  ⚠ PCA對比圖生成失敗: {e}")
    
    # 6. 相關性熱圖
    try:
        plot_correlation_heatmap(
            original_data_valid, normalized_data_valid, sample_columns_valid,
            output_dir / f"Correlation_Heatmap_{method_name}.png",
            method_name
        )
    except Exception as e:
        print(f"  ⚠ 相關性熱圖生成失敗: {e}")
    
    # ========== 新增：Q-Q Plot ==========
    if normality_results:
        try:
            plot_qq_comparison(
                original_data_valid, normalized_data_valid,
                sample_size=20,
                output_path=output_dir / f"QQ_Plot_{method_name}.png"
            )
        except Exception as e:
            print(f"  ⚠ Q-Q Plot 生成失敗: {e}")
    
    # ========== 新增：Effect Size 對比圖 ==========
    if group_diff_results:
        try:
            plot_effect_size_comparison(
                group_diff_results['cohens_d_before'],
                group_diff_results['cohens_d_after'],
                output_path=output_dir / f"Effect_Size_Comparison_{method_name}.png"
            )
        except Exception as e:
            print(f"  ⚠ Effect Size 對比圖生成失敗: {e}")
    
    # ========== 新增：QC 質量評估圖 ==========
    if pqn_info['qc_count'] > 0:
        try:
            # 提取 QC 樣本索引
            qc_indices = []
            qc_names = []
            for i, sample in enumerate(sample_columns_valid):
                sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
                if not sample_row.empty:
                    sample_type = str(sample_row.iloc[0].get('Sample_Type', '')).upper()
                    if sample_type == 'QC':
                        qc_indices.append(i)
                        qc_names.append(sample)
            
            if len(qc_indices) > 0:
                original_qc = original_data_valid[:, qc_indices]
                normalized_qc = normalized_data_valid[:, qc_indices]
                
                plot_qc_quality_assessment(
                    original_qc, normalized_qc, qc_names,
                    output_path=output_dir / f"QC_Quality_{method_name}.png"
                )
        except Exception as e:
            print(f"  ⚠ QC 質量評估圖生成失敗: {e}")
    
    # 創建結果DataFrame（只包含樣本數據和CV%）
    normalized_df = pd.DataFrame()
    normalized_df[data_df.columns[0]] = feature_ids
    
    # 添加標準化後的樣本數據
    for i, col in enumerate(sample_columns):
        normalized_df[col] = normalized_data[:, i]
    
    # 只添加CV%欄位
    normalized_df['Original_CV%'] = calculate_cv_per_feature(original_data)
    normalized_df['Normalized_CV%'] = calculate_cv_per_feature(normalized_data)
    normalized_df['CV_Improvement%'] = normalized_df['Original_CV%'] - normalized_df['Normalized_CV%']
    
    # ========== 生成增強版摘要報告 ==========
    summary_report = create_normalization_summary_report(
        quality_metrics, method_name, len(feature_ids), len(sample_columns_valid),
        pqn_info=pqn_info,
        normality_results=normality_results,
        group_diff_results=group_diff_results
    )
    
    print(f"\n{summary_report}")
    
    return normalized_df, summary_report, method_name, output_dir, quality_metrics

def save_normalization_results(normalized_df, summary_report, file_path, method_name, original_sheets, output_dir):
    """儲存標準化結果到Excel檔案"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"Normalized_{method_name}_{timestamp}.xlsx"
        output_path = output_dir / output_filename
        
        # 載入原始工作簿
        wb_original = load_workbook(file_path, data_only=False)
        
        # 創建新工作簿
        wb_new = Workbook()
        wb_new.remove(wb_new.active)
        
        # 1. 儲存標準化後的資料
        ws_normalized = wb_new.create_sheet(title=f'{method_name}_Result')
        
        cleaned_normalized_df = clean_dataframe_for_excel(normalized_df)
        for r_idx, row in enumerate(dataframe_to_rows(cleaned_normalized_df, index=False, header=True), 1):
            for c_idx, value in enumerate(row, 1):
                cell = ws_normalized.cell(row=r_idx, column=c_idx, value=value)
                if r_idx == 1:
                    cell.font = Font(bold=True, size=11)
                    cell.fill = PatternFill(start_color='CCE5FF', end_color='CCE5FF', fill_type='solid')
                    cell.alignment = Alignment(horizontal='center', vertical='center')
        
        # 自動調整列寬
        for column in ws_normalized.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws_normalized.column_dimensions[column_letter].width = adjusted_width
        
        # 2. 儲存摘要報告
        ws_summary = wb_new.create_sheet(title='Summary_Report')
        summary_rows = summary_report.split('\n')
        for r_idx, row_text in enumerate(summary_rows, 1):
            cell = ws_summary.cell(row=r_idx, column=1, value=row_text)
            if '=' in row_text and r_idx <= 3:
                cell.font = Font(bold=True, size=12)
            elif '【' in row_text:
                cell.font = Font(bold=True, size=11, color='0000FF')
            elif '✓' in row_text:
                cell.font = Font(color='008000')
            elif '⚠' in row_text:
                cell.font = Font(color='FF6600')
        
        ws_summary.column_dimensions['A'].width = 80
        
        # 3. 複製原始工作表並保留格式
        for sheet_name in wb_original.sheetnames:
            if sheet_name in [f'{method_name}_Result', 'Summary_Report']:
                continue
            
            ws_original = wb_original[sheet_name]
            ws_new = wb_new.create_sheet(title=sheet_name[:31])
            
            # 設置列寬
            for col in ws_original.column_dimensions:
                ws_new.column_dimensions[col].width = ws_original.column_dimensions[col].width
            
            # 設置行高
            for row_idx, row_dim in ws_original.row_dimensions.items():
                ws_new.row_dimensions[row_idx].height = row_dim.height
            
            # 複製儲存格內容和格式
            for row in ws_original.iter_rows():
                for cell in row:
                    new_cell = ws_new.cell(row=cell.row, column=cell.column, value=cell.value)
                    copy_cell_style(cell, new_cell)
        
        # 儲存新工作簿
        wb_new.save(output_path)
        
        print(f"\n✓ 結果已儲存至: {output_path}")
        print(f"\n包含工作表:")
        print(f"  1. {method_name}_Result (標準化後資料)")
        print(f"  2. Summary_Report (摘要報告)")
        for sheet_name in wb_original.sheetnames:
            if sheet_name not in [f'{method_name}_Result', 'Summary_Report']:
                print(f"  3. {sheet_name} (原始資料)")
        
        return str(output_path)
        
    except Exception as e:
        print(f"儲存檔案時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==================== 主程式 ====================

def main(input_file=None):
    """
    主函數 - 支援 GUI 和獨立運行
    
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
    print("=" * 80)
    print("  代謝體學標準化程式 v3.0")
    print("  標準化方法: PQN + Sample-specific (肌酐校正)")
    print("  - 步驟1: Sample-specific Normalization (肌酐校正)")
    print("  - 步驟2: Probabilistic Quotient Normalization (PQN)")
    print("  - 視覺化評估工具（密度圖、盒鬚圖、PCA、CV%分佈等）")
    print("=" * 80)
    
    # 🔧 關鍵修正：如果沒有提供 input_file，則顯示對話框
    if input_file is None:
        file_path = select_file()
        
        # 如果用戶取消選擇，返回 None
        if not file_path:
            print("❌ 未選擇檔案，程式結束。")
            return None
        
        input_file = file_path
    
    # 驗證檔案是否存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"找不到檔案: {input_file}")
    
    print(f"\n✓ 選擇的檔案: {Path(input_file).name}")
    
    # 載入Excel工作表
    sheets, sheet_names = load_excel_sheets(input_file)
    if not sheets:
        raise Exception("無法載入 Excel 工作表")
    
    print(f"✓ 找到 {len(sheet_names)} 個工作表")
    
    # 尋找樣本資訊工作表
    sample_info_df, sample_info_sheet_name = find_sample_info_sheet(sheets)
    if sample_info_df is None:
        print("❌ 錯誤：找不到包含樣本資訊的工作表")
        raise Exception("找不到樣本資訊工作表")
    
    print(f"✓ 使用樣本資訊工作表: {sample_info_sheet_name}")
    
    # 尋找校正欄位（肌酐濃度）
    correction_col, correction_type = find_correction_column(sample_info_df)
    if not correction_col:
        print("❌ 錯誤：找不到校正用的欄位")
        raise Exception("找不到校正欄位")
    
    # 確定要標準化的資料工作表
    data_df, data_sheet_name = determine_correction_sheet(sheets)
    if data_df is None:
        print("❌ 錯誤：找不到要標準化的資料工作表")
        raise Exception("找不到資料工作表")
    
    print(f"✓ 使用資料工作表: {data_sheet_name}")
    
    # 執行標準化
    result = perform_normalization(data_df, sample_info_df, correction_col, input_file)
    
    if result is None:
        print("\n❌ 標準化失敗")
        raise Exception("標準化失敗")
    
    normalized_df, summary_report, method_name, output_dir, quality_metrics = result
    
    # 儲存結果
    print("\n儲存結果...")
    output_path = save_normalization_results(
        normalized_df, summary_report, input_file, method_name, sheets, output_dir
    )
    
    if not output_path:
        raise Exception("儲存結果失敗")
    
    print("\n" + "=" * 80)
    print("✅ 標準化完成！")
    print("=" * 80)
    print(f"\n📁 輸出資料夾: {output_dir.name}")
    print(f"📄 Excel檔案: {Path(output_path).name}")
    
    print("\n📊 生成的視覺化圖表:")
    print(f"  1. Density_Plot_{method_name}.png - 密度分佈圖")
    print(f"  2. Boxplot_{method_name}.png - 盒鬚圖")
    print(f"  3. Sample_Distribution_{method_name}.png - 樣本總強度分佈")
    print(f"  4. CV_Distribution_{method_name}.png - CV%分佈圖")
    print(f"  5. PCA_Comparison_{method_name}.png - PCA對比圖")
    print(f"  6. Correlation_Heatmap_{method_name}.png - 樣本相關性熱圖")
    
    print("\n" + "=" * 80)
    print("📈 標準化質量評估摘要:")
    print("=" * 80)
    print(f"  中位數CV%改善: {quality_metrics['median_cv_before']:.2f}% → {quality_metrics['median_cv_after']:.2f}%")
    print(f"  CV%降低: {quality_metrics['cv_improvement']:.2f}% ({quality_metrics['cv_improvement_pct']:.1f}%)")
    print(f"  改善特徵比例: {quality_metrics['cv_improved_ratio']:.1f}%")
    print(f"  樣本總強度CV%: {quality_metrics['total_cv_before']:.2f}% → {quality_metrics['total_cv_after']:.2f}%")
    
    if not np.isnan(quality_metrics['sample_corr_mean_before']):
        print(f"  樣本間平均相關性: {quality_metrics['sample_corr_mean_before']:.4f} → {quality_metrics['sample_corr_mean_after']:.4f}")
    
    # 計算整體評分
    score = 0
    if quality_metrics['cv_improvement'] > 0:
        score += 25
    if quality_metrics['total_cv_improvement'] > 0:
        score += 25
    if not np.isnan(quality_metrics['sample_corr_std_before']) and quality_metrics['sample_corr_std_after'] < quality_metrics['sample_corr_std_before']:
        score += 25
    if quality_metrics['cv_improved_ratio'] > 50:
        score += 25
    
    print(f"\n  整體評分: {score}/100", end=" ")
    if score >= 75:
        print("★★★★★ (優秀)")
    elif score >= 50:
        print("★★★★ (良好)")
    elif score >= 25:
        print("★★★ (尚可)")
    else:
        print("★★ (需改進)")
    
    print("=" * 80)
    
    print("\n✅ 所有檔案已成功儲存！")
    print(f"✅ 完整路徑: {output_path}")
    
    # 🎯 返回統計資訊給 GUI
    # 從 normalized_df 中提取樣本數量（排除第一列 FeatureID）
    sample_count = len(normalized_df.columns) - 1
    metabolite_count = len(normalized_df)
    
    return {
        'file_path': input_file,
        'metabolites': metabolite_count,
        'samples': sample_count,
        'output_path': output_path
    }


if __name__ == "__main__":
    # 🔧 獨立運行時不傳入 input_file，會顯示對話框
    main()

