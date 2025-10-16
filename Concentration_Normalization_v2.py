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

def normalization_pqn_with_reference(data_matrix, reference_values):
    """
    混合標準化方法：PQN + Sample-specific
    
    Steps:
    1. 先使用 Sample-specific normalization (肌酐校正)
    2. 再使用 PQN 進一步標準化
    
    Parameters:
    -----------
    data_matrix : np.ndarray
        數據矩陣 (特徵 x 樣本)
    reference_values : np.ndarray
        參考值陣列 (樣本數量)，例如肌酐濃度
    """
    print("\n執行混合標準化方法：")
    print("  步驟1: Sample-specific Normalization (肌酐校正)")
    
    # Step 1: Sample-specific normalization
    median_ref = np.median(reference_values)
    step1_normalized = data_matrix / reference_values
    step1_normalized = step1_normalized * median_ref
    
    print(f"    - 參考值中位數: {median_ref:.2f}")
    print(f"    - 參考值範圍: {np.min(reference_values):.2f} - {np.max(reference_values):.2f}")
    
    print("  步驟2: Probabilistic Quotient Normalization (PQN)")
    
    # Step 2: PQN
    # 使用所有樣本的中位數作為參考樣本
    reference_sample = np.median(step1_normalized, axis=1)
    
    # 計算每個樣本與參考樣本的比值
    quotients = step1_normalized / reference_sample[:, np.newaxis]
    
    # 計算每個樣本的中位數比值
    quotients = np.where(np.isfinite(quotients), quotients, np.nan)
    normalization_factors = np.nanmedian(quotients, axis=0)
    
    # 最終標準化
    final_normalized = step1_normalized / normalization_factors
    
    print(f"    - PQN標準化因子範圍: {np.min(normalization_factors):.4f} - {np.max(normalization_factors):.4f}")
    print("  ✓ 混合標準化完成")
    
    return final_normalized

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

def create_normalization_summary_report(quality_metrics, method_name, n_features, n_samples):
    """建立標準化摘要報告"""
    report = []
    report.append("=" * 80)
    report.append(f"標準化效果摘要報告 - {method_name}")
    report.append(f"報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)
    
    # 基本資訊
    report.append("")
    report.append("【基本資訊】")
    report.append(f"標準化方法: {method_name}")
    report.append(f"特徵數量: {n_features}")
    report.append(f"樣本數量: {n_samples}")
    
    # CV% 評估
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
    
    # 樣本總強度變異
    report.append("")
    report.append("【樣本總強度變異】")
    report.append(f"標準化前總強度CV%: {quality_metrics['total_cv_before']:.2f}%")
    report.append(f"標準化後總強度CV%: {quality_metrics['total_cv_after']:.2f}%")
    report.append(f"總強度CV%改善: {quality_metrics['total_cv_improvement']:.2f}%")
    
    # 樣本間相關性
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
    
    # 評估結論
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
    
    # 整體評分
    report.append("")
    report.append("【整體評分】")
    score = 0
    if quality_metrics['cv_improvement'] > 0:
        score += 25
    if quality_metrics['total_cv_improvement'] > 0:
        score += 25
    if not np.isnan(quality_metrics['sample_corr_std_before']) and quality_metrics['sample_corr_std_after'] < quality_metrics['sample_corr_std_before']:
        score += 25
    if quality_metrics['cv_improved_ratio'] > 50:
        score += 25
    
    report.append(f"標準化質量評分: {score}/100")
    if score >= 75:
        report.append("評級: 優秀 ★★★★★")
    elif score >= 50:
        report.append("評級: 良好 ★★★★")
    elif score >= 25:
        report.append("評級: 尚可 ★★★")
    else:
        report.append("評級: 需改進 ★★")
    
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
    執行 PQN + Sample-specific 混合標準化處理
    """
    print(f"\n" + "="*70)
    print("開始執行標準化處理...")
    print("="*70)
    
    method_name = "PQN_SampleSpecific"
    
    # 獲取純樣本欄位（排除統計欄位）
    sample_columns = get_sample_columns_only(data_df, sample_info_df)
    print(f"✓ 樣本數量: {len(sample_columns)}")
    
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
    valid_sample_mask = []
    
    for sample in sample_columns:
        sample_row = sample_info_df[sample_info_df.iloc[:, 0] == sample]
        if not sample_row.empty and pd.notna(sample_row.iloc[0][correction_col]):
            try:
                ref_val = float(sample_row.iloc[0][correction_col])
                if ref_val > 0:
                    reference_values.append(ref_val)
                    valid_sample_mask.append(True)
                else:
                    reference_values.append(np.nan)
                    valid_sample_mask.append(False)
            except:
                reference_values.append(np.nan)
                valid_sample_mask.append(False)
        else:
            reference_values.append(np.nan)
            valid_sample_mask.append(False)
    
    reference_values = np.array(reference_values)
    valid_sample_mask = np.array(valid_sample_mask)
    
    valid_count = np.sum(valid_sample_mask)
    print(f"✓ 有效參考值數量: {valid_count}/{len(sample_columns)}")
    
    if valid_count < len(sample_columns) * 0.5:
        print("警告：有效參考值不足50%")
        return None
    
    # 執行混合標準化（只對有效樣本）
    normalized_data_valid = normalization_pqn_with_reference(
        data_matrix[:, valid_sample_mask], 
        reference_values[valid_sample_mask]
    )
    
    # 創建完整的標準化數據矩陣
    normalized_data = np.full_like(data_matrix, np.nan)
    normalized_data[:, valid_sample_mask] = normalized_data_valid
    
    print(f"✓ 標準化完成")
    
    # 創建輸出資料夾
    output_dir = Path(file_path).parent / f"Normalization_Results_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir.mkdir(exist_ok=True)
    print(f"✓ 創建輸出資料夾: {output_dir.name}")
    
    # 只使用有效樣本進行評估和繪圖
    original_data_valid = original_data[:, valid_sample_mask]
    sample_columns_valid = [sample_columns[i] for i in range(len(sample_columns)) if valid_sample_mask[i]]
    
    # 評估標準化質量
    print("\n評估標準化質量...")
    quality_metrics = evaluate_normalization_quality(original_data_valid, normalized_data_valid)
    
    # 生成視覺化圖表
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
    
    # 生成摘要報告
    summary_report = create_normalization_summary_report(
        quality_metrics, method_name, len(feature_ids), len(sample_columns_valid)
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

