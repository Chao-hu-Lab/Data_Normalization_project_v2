import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score, silhouette_samples
from pycombat import pycombat
import warnings
import tkinter as tk
from tkinter import filedialog
import os
import datetime
import sys
from openpyxl import load_workbook, Workbook
from copy import copy
from scipy import stats
from matplotlib.patches import Ellipse
from openpyxl.styles import PatternFill
from scipy.spatial.distance import mahalanobis
from scipy.stats import chi2, f as f_dist
warnings.filterwarnings('ignore')

# 設定色盲友善的顏色
COLORBLIND_COLORS = ['#0173B2', '#DE8F05', '#029E73', '#CC78BC', '#CA9161', '#949494', '#ECE133', '#56B4E9']

def select_file():
    """
    開啟檔案選擇對話框，讓使用者選擇要處理的Excel檔案
    """
    root = tk.Tk()
    root.withdraw()
    
    file_path = filedialog.askopenfilename(
        title="選擇要進行批次效應校正的Excel檔案",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    
    if not file_path:
        print("未選擇檔案，程式結束")
        return None
    
    return file_path

def read_excel_data(file_path):
    """
    讀取Excel檔案，根據優先順序選擇工作表
    優先順序: QC LOWESS result > ISTD_Correction > RawIntensity
    """
    xl_file = pd.ExcelFile(file_path)
    sheet_names = xl_file.sheet_names
    
    if 'SampleInfo' not in sheet_names:
        raise ValueError("找不到'SampleInfo'工作表")
    
    sample_info = pd.read_excel(file_path, sheet_name='SampleInfo')
    
    data_sheet = None
    sheet_priority = ['QC LOWESS result', 'ISTD_Correction', 'RawIntensity']
    
    for sheet in sheet_priority:
        if sheet in sheet_names:
            data_sheet = sheet
            break
    
    if data_sheet is None:
        for sheet in sheet_names:
            if sheet != 'SampleInfo':
                data_sheet = sheet
                break
    
    if data_sheet is None:
        raise ValueError("找不到數據工作表")
    
    data = pd.read_excel(file_path, sheet_name=data_sheet)
    
    return data, sample_info, data_sheet

def prepare_data_for_combat(data, sample_info):
    """
    準備Combat所需的數據格式
    """
    data_columns = data.columns.tolist()
    feature_col = data_columns[0]
    sample_columns = data_columns[1:]
    
    if 'Sample_Name' not in sample_info.columns or 'Batch' not in sample_info.columns:
        print("警告: SampleInfo工作表缺少必要的列 'Sample_Name' 或 'Batch'")
        print(f"可用列: {sample_info.columns.tolist()}")
        
        sample_name_col = None
        batch_col = None
        
        for col in sample_info.columns:
            if 'sample' in str(col).lower() or 'name' in str(col).lower():
                sample_name_col = col
            elif 'batch' in str(col).lower():
                batch_col = col
        
        if sample_name_col and batch_col:
            print(f"使用猜測的列名: Sample_Name='{sample_name_col}', Batch='{batch_col}'")
            sample_info = sample_info.rename(columns={sample_name_col: 'Sample_Name', batch_col: 'Batch'})
        else:
            if sample_info.shape[1] >= 2:
                print("使用第一列作為樣本名稱，第二列作為批次")
                sample_info = sample_info.copy()
                sample_info.columns = ['Sample_Name', 'Batch'] + list(sample_info.columns[2:])
            else:
                raise ValueError("無法識別SampleInfo中的樣本名稱和批次列")
    
    print(f"SampleInfo中的樣本數: {len(sample_info)}")
    print(f"數據表中的樣本列數: {len(sample_columns)}")
    
    sample_to_batch = {}
    for _, row in sample_info.iterrows():
        sample_name = str(row['Sample_Name']).strip()
        if pd.notna(row['Batch']):
            sample_to_batch[sample_name] = row['Batch']
    
    valid_samples = []
    valid_batches = []
    
    for col in sample_columns:
        col_str = str(col).strip()
        if col_str in sample_to_batch:
            valid_samples.append(col)
            valid_batches.append(sample_to_batch[col_str])
    
    if len(valid_samples) < 2:
        print("精確匹配找不到足夠的樣本，嘗試部分匹配...")
        valid_samples = []
        valid_batches = []
        
        for col in sample_columns:
            col_str = str(col).strip()
            for sample_name in sample_to_batch:
                if (sample_name.lower() in col_str.lower() or 
                    col_str.lower() in sample_name.lower()):
                    valid_samples.append(col)
                    valid_batches.append(sample_to_batch[sample_name])
                    print(f"匹配: 數據列 '{col}' -> 樣本 '{sample_name}', 批次 {sample_to_batch[sample_name]}")
                    break
    
    if len(valid_samples) < 2:
        print("警告: 找不到足夠的有效樣本，嘗試直接使用數據列名...")
        
        if len(sample_info) >= 2:
            valid_samples = sample_columns[:len(sample_info)]
            valid_batches = sample_info['Batch'].tolist()[:len(valid_samples)]
            valid_batches = valid_batches[:len(valid_samples)]
        else:
            raise ValueError(f"找不到足夠的有效樣本（只有{len(valid_samples)}個）。請檢查樣本名稱是否匹配。")
    
    print(f"找到 {len(valid_samples)} 個有效樣本，對應 {len(set(valid_batches))} 個不同的批次")
    for batch in set(valid_batches):
        count = valid_batches.count(batch)
        print(f"  批次 {batch}: {count} 個樣本")
    
    data_matrix = data[valid_samples].values
    
    print(f"數據矩陣形狀: {data_matrix.shape}")
    print(f"批次信息長度: {len(valid_batches)}")
    
    if data_matrix.shape[1] != len(valid_batches):
        print(f"警告: 數據矩陣樣本數 ({data_matrix.shape[1]}) 與批次信息數量 ({len(valid_batches)}) 不匹配")
        print("嘗試調整批次信息以匹配數據矩陣...")
        
        if len(valid_batches) > data_matrix.shape[1]:
            valid_batches = valid_batches[:data_matrix.shape[1]]
    
    print(f"調整後數據矩陣形狀: {data_matrix.shape}")
    print(f"調整後批次信息長度: {len(valid_batches)}")
    
    if data_matrix.shape[1] != len(valid_batches):
        raise ValueError(f"無法調整數據矩陣維度以匹配批次信息數量，請檢查數據格式")
    
    return data_matrix, valid_batches, valid_samples, data[feature_col].values

def perform_combat_correction(data_matrix, batch_info):
    """
    執行Combat批次效應校正
    """
    print(f"原始數據矩陣形狀: {data_matrix.shape}")
    print(f"批次信息長度: {len(batch_info)}")
    
    if data_matrix.shape[1] != len(batch_info):
        print(f"警告: 數據矩陣樣本數 ({data_matrix.shape[1]}) 與批次信息數量 ({len(batch_info)}) 不匹配")
        
        if data_matrix.shape[0] == len(batch_info):
            print(f"轉置數據矩陣: 從 {data_matrix.shape} 到 {data_matrix.T.shape}")
            data_matrix = data_matrix.T
        else:
            print("嘗試調整批次信息以匹配數據矩陣...")
            
            if data_matrix.shape[0] > data_matrix.shape[1]:
                correct_sample_count = data_matrix.shape[1]
                print(f"假設數據矩陣格式為 (特徵 x 樣本)，樣本數為 {correct_sample_count}")
            else:
                correct_sample_count = data_matrix.shape[0]
                print(f"假設數據矩陣需要轉置，樣本數為 {correct_sample_count}")
                data_matrix = data_matrix.T
            
            if len(batch_info) > correct_sample_count:
                print(f"截取批次信息從 {len(batch_info)} 到 {correct_sample_count}")
                batch_info = batch_info[:correct_sample_count]
            else:
                raise ValueError(f"批次信息數量 ({len(batch_info)}) 少於數據矩陣樣本數 ({correct_sample_count})，無法進行校正")
    
    print(f"調整後數據矩陣形狀: {data_matrix.shape}")
    print(f"調整後批次信息長度: {len(batch_info)}")
    
    if data_matrix.shape[1] != len(batch_info):
        raise ValueError(f"無法調整數據矩陣維度以匹配批次信息數量，請檢查數據格式")
    
    batch_counts = {}
    for batch in batch_info:
        if batch not in batch_counts:
            batch_counts[batch] = 0
        batch_counts[batch] += 1
    
    for batch, count in batch_counts.items():
        if count < 2:
            print(f"警告: 批次 {batch} 只有 {count} 個樣本，可能影響校正效果")
    
    data_matrix = data_matrix.astype(float)
    
    min_nonzero = np.min(data_matrix[data_matrix > 0]) if np.any(data_matrix > 0) else 1
    
    data_matrix[data_matrix == 0] = min_nonzero / 2
    data_matrix = np.nan_to_num(data_matrix, nan=min_nonzero / 2)
    
    data_log = np.log2(data_matrix + 1)
    
    print(f"準備進行Combat校正: 數據矩陣維度 {data_log.shape}, 批次信息數量 {len(batch_info)}")
    
    combat_obj = pycombat.Combat()
    corrected_data = combat_obj.fit_transform(data_log.T, batch_info)
    corrected_data = corrected_data.T
    
    corrected_data = np.power(2, corrected_data) - 1
    
    corrected_data[corrected_data < 0] = 0
    
    return corrected_data
def plot_permutation_distribution(null_distribution, observed_improvement, p_value):
    """
    繪製 Permutation Test 的 Null Distribution 圖

    Parameters:
    -----------
    

    """
    if len(null_distribution) == 0:
        print("   ⚠ Null distribution 為空，無法繪製分佈圖")
        return None

    # 可以調整 figsize 來增加圖表整體大小，為文字提供更多空間
    fig, ax = plt.subplots(figsize=(12, 7)) # 調整為更大的尺寸，例如 (12, 7)

    # 繪製 Null Distribution 直方圖
    ax.hist(null_distribution, bins=50, color='lightblue', edgecolor='black', alpha=0.7, label='Null Distribution')

    # 繪製觀察值
    ax.axvline(observed_improvement, color='red', linestyle='--', linewidth=3,
               label=f'Observed Improvement = {observed_improvement:.4f}')

    # 移除原有的 p-value 標註，改為整合到統計摘要中
    # y_max = ax.get_ylim()[1]
    # ax.text(observed_improvement, y_max * 0.9, f'p-value = {p_value:.4f}',
    #         fontsize=12, color='red', fontweight='bold',
    #         bbox=dict(boxstyle='round', facecolor='white', edgecolor='red', linewidth=2))

    # 設定標題和標籤
    ax.set_xlabel('Silhouette Improvement (Original - Corrected)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax.set_title('Permutation Test: Null Distribution of Silhouette Improvement',
                 fontsize=14, fontweight='bold', pad=15)

    # 添加圖例
    ax.legend(fontsize=10, loc='upper left', frameon=True, fancybox=True, shadow=True)

    # 添加網格
    ax.grid(True, alpha=0.3, linestyle='--')

    # 添加統計摘要文字，並將 p-value 整合進去
    stats_text = f"Null Distribution Statistics:\n"
    stats_text += f"  Mean: {np.mean(null_distribution):.4f}\n"
    stats_text += f"  Std: {np.std(null_distribution):.4f}\n"
    stats_text += f"  Min: {np.min(null_distribution):.4f}\n"
    stats_text += f"  Max: {np.max(null_distribution):.4f}\n"
    stats_text += f"  p-value: {p_value:.4f}\n" # 將 p-value 加入統計摘要中
    stats_text += f"\nPermutations: {len(null_distribution)}"

    ax.text(0.98, 0.97, stats_text, transform=ax.transAxes,
            fontsize=9, verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()

    return fig

# ========== 🔧 新增：Cohen's d 效果量計算 ==========
def calculate_cohens_d_batch_effect(data, batch_labels):
    """
    計算批次效應的 Cohen's d 效果量
    
    使用所有批次對的平均 Cohen's d 來量化批次間差異

    """
    from itertools import combinations
    
    print("\n📏 計算 Cohen's d 效果量...")
    
    unique_batches = sorted(list(set(batch_labels)))
    batch_labels = np.array(batch_labels)
    
    if len(unique_batches) < 2:
        print("   ⚠ 只有一個批次，無法計算 Cohen's d")
        return {
            'overall_cohens_d': 0.0,
            'feature_cohens_d': np.zeros(data.shape[1]),
            'pairwise_cohens_d': {}
        }
    
    n_features = data.shape[1]
    feature_cohens_d_list = []
    pairwise_results = {}
    
    # 計算所有批次對的 Cohen's d
    batch_pairs = list(combinations(unique_batches, 2))
    
    for batch1, batch2 in batch_pairs:
        batch1_data = data[batch_labels == batch1]
        batch2_data = data[batch_labels == batch2]
        
        n1 = len(batch1_data)
        n2 = len(batch2_data)
        
        if n1 < 2 or n2 < 2:
            continue
        
        # 計算每個特徵的 Cohen's d
        mean1 = np.mean(batch1_data, axis=0)
        mean2 = np.mean(batch2_data, axis=0)
        std1 = np.std(batch1_data, axis=0, ddof=1)
        std2 = np.std(batch2_data, axis=0, ddof=1)
        
        # Pooled standard deviation
        pooled_std = np.sqrt(((n1 - 1) * std1**2 + (n2 - 1) * std2**2) / (n1 + n2 - 2))
        
        # 避免除以零
        pooled_std = np.where(pooled_std == 0, 1e-10, pooled_std)
        
        # Cohen's d = (mean1 - mean2) / pooled_std
        cohens_d = np.abs(mean1 - mean2) / pooled_std
        
        feature_cohens_d_list.append(cohens_d)
        pairwise_results[f'Batch{batch1}_vs_Batch{batch2}'] = np.mean(cohens_d)
    
    if len(feature_cohens_d_list) == 0:
        return {
            'overall_cohens_d': 0.0,
            'feature_cohens_d': np.zeros(n_features),
            'pairwise_cohens_d': {}
        }
    
    # 平均所有批次對的 Cohen's d
    feature_cohens_d = np.mean(feature_cohens_d_list, axis=0)
    overall_cohens_d = np.mean(feature_cohens_d)
    
    # 輸出統計摘要
    print(f"   - 整體平均 Cohen's d: {overall_cohens_d:.4f}")
    print(f"   - Cohen's d 解釋:")
    if overall_cohens_d < 0.2:
        print(f"     • 小效果 (d < 0.2) - 批次效應微弱")
    elif overall_cohens_d < 0.5:
        print(f"     • 小至中等效果 (0.2 ≤ d < 0.5) - 批次效應輕微")
    elif overall_cohens_d < 0.8:
        print(f"     • 中等效果 (0.5 ≤ d < 0.8) - 批次效應中等")
    else:
        print(f"     • 大效果 (d ≥ 0.8) - 批次效應強烈")
    
    print(f"\n   批次對之間的 Cohen's d:")
    for pair, d_value in pairwise_results.items():
        print(f"     • {pair}: {d_value:.4f}")
    
    return {
        'overall_cohens_d': overall_cohens_d,
        'feature_cohens_d': feature_cohens_d,
        'pairwise_cohens_d': pairwise_results
    }

# ========= 🔧 新增：QC 樣本變異係數 (CV%) 計算 ==========
def calculate_qc_cv(data, sample_info, sample_columns):
    """
    計算 QC 樣本的變異係數 (CV%)
    
    CV% = (標準差 / 平均值) × 100
    CV% < 20% 表示技術重現性良好
    
    Parameters:
    -----------
    data : np.ndarray
        數據矩陣 (特徵 x 樣本)
    sample_info : pd.DataFrame
        樣本資訊表
    sample_columns : list
        樣本列名稱
    
    Returns:
    --------
    dict:
        'qc_cv': np.ndarray - 每個特徵的 QC CV%
        'median_cv': float - QC CV% 中位數
        'mean_cv': float - QC CV% 平均值
        'cv_below_20': float - CV% < 20% 的特徵比例
        'cv_below_30': float - CV% < 30% 的特徵比例
    """
    print("\n📊 計算 QC 樣本 CV%...")
    
    # 識別 QC 樣本
    sample_meta = sample_info.set_index('Sample_Name')
    qc_columns = []
    
    for col in sample_columns:
        if col in sample_meta.index:
            sample_type = sample_meta.loc[col].get('Sample_Type', 'Unknown')
            sample_type_upper = str(sample_type).upper()
            
            if 'QC' in sample_type_upper:
                qc_columns.append(col)
        else:
            col_upper = col.upper()
            if 'QC' in col_upper:
                qc_columns.append(col)
    
    if len(qc_columns) < 3:
        print(f"   ⚠ QC 樣本數不足 ({len(qc_columns)})，無法計算可靠的 CV%")
        return {
            'qc_cv': np.array([]),
            'median_cv': np.nan,
            'mean_cv': np.nan,
            'cv_below_20': 0.0,
            'cv_below_30': 0.0
        }
    
    print(f"   - 找到 {len(qc_columns)} 個 QC 樣本")
    
    # 提取 QC 數據
    qc_indices = [sample_columns.index(col) for col in qc_columns]
    qc_data = data[:, qc_indices]  # (特徵 x QC樣本)
    
    # 計算 CV%
    qc_mean = np.mean(qc_data, axis=1)
    qc_std = np.std(qc_data, axis=1, ddof=1)
    
    # 避免除以零
    qc_mean = np.where(qc_mean == 0, 1e-10, qc_mean)
    
    qc_cv = (qc_std / qc_mean) * 100
    
    # 統計摘要
    median_cv = np.median(qc_cv)
    mean_cv = np.mean(qc_cv)
    cv_below_20 = np.sum(qc_cv < 20) / len(qc_cv) * 100
    cv_below_30 = np.sum(qc_cv < 30) / len(qc_cv) * 100
    
    print(f"   - QC CV% 中位數: {median_cv:.2f}%")
    print(f"   - QC CV% 平均值: {mean_cv:.2f}%")
    print(f"   - CV% < 20% 的特徵: {cv_below_20:.1f}%")
    print(f"   - CV% < 30% 的特徵: {cv_below_30:.1f}%")
    
    if median_cv < 20:
        print(f"   ✅ 技術重現性優良 (中位數 CV% < 20%)")
    elif median_cv < 30:
        print(f"   ⚠ 技術重現性可接受 (20% ≤ 中位數 CV% < 30%)")
    else:
        print(f"   ❌ 技術重現性較差 (中位數 CV% ≥ 30%)")
    
    return {
        'qc_cv': qc_cv,
        'median_cv': median_cv,
        'mean_cv': mean_cv,
        'cv_below_20': cv_below_20,
        'cv_below_30': cv_below_30
    }

# ========== 🔧 新增：PCA 主成分 ANOVA 檢驗 ==========
def calculate_pca_anova(data, batch_labels):
    """
    對 PCA 主成分進行 ANOVA 檢驗，評估批次對主成分的影響
    
    Parameters:
    -----------
    data : np.ndarray
        標準化後的數據 (樣本 x 特徵)
    batch_labels : list or np.ndarray
        批次標籤
    
    Returns:
    --------
    dict:
        'pc1_pvalue': float - PC1 的 ANOVA p-value
        'pc2_pvalue': float - PC2 的 ANOVA p-value
        'pc1_eta_squared': float - PC1 的效果量 (η²)
        'pc2_eta_squared': float - PC2 的效果量 (η²)
    """
    from scipy.stats import f_oneway
    
    print("\n🔬 對 PCA 主成分進行 ANOVA 檢驗...")
    
    # PCA
    pca = PCA(n_components=2)
    scores = pca.fit_transform(data)
    
    unique_batches = sorted(list(set(batch_labels)))
    batch_labels = np.array(batch_labels)
    
    # 為每個主成分進行 ANOVA
    results = {}
    
    for pc_idx, pc_name in enumerate(['PC1', 'PC2']):
        # 按批次分組
        batch_groups = [scores[batch_labels == b, pc_idx] for b in unique_batches]
        
        # ANOVA
        f_stat, p_value = f_oneway(*batch_groups)
        
        # 計算 eta-squared (η²)
        # η² = SSB / SST
        grand_mean = np.mean(scores[:, pc_idx])
        
        # SST (Total Sum of Squares)
        sst = np.sum((scores[:, pc_idx] - grand_mean)**2)
        
        # SSB (Between-group Sum of Squares)
        ssb = 0
        for batch in unique_batches:
            batch_data = scores[batch_labels == batch, pc_idx]
            batch_mean = np.mean(batch_data)
            ssb += len(batch_data) * (batch_mean - grand_mean)**2
        
        eta_squared = ssb / sst if sst > 0 else 0
        
        results[f'{pc_name.lower()}_pvalue'] = p_value
        results[f'{pc_name.lower()}_eta_squared'] = eta_squared
        
        print(f"   - {pc_name}:")
        print(f"     • F-statistic: {f_stat:.4f}")
        print(f"     • p-value: {p_value:.4f}", end="")
        
        if p_value < 0.001:
            print(f" *** (批次對 {pc_name} 有極顯著影響)")
        elif p_value < 0.01:
            print(f" ** (批次對 {pc_name} 有非常顯著影響)")
        elif p_value < 0.05:
            print(f" * (批次對 {pc_name} 有顯著影響)")
        else:
            print(f" n.s. (批次對 {pc_name} 無顯著影響)")
        
        print(f"     • η² = {eta_squared:.4f}", end="")
        if eta_squared < 0.01:
            print(f" (微弱效果)")
        elif eta_squared < 0.06:
            print(f" (小效果)")
        elif eta_squared < 0.14:
            print(f" (中等效果)")
        else:
            print(f" (大效果)")
    
    return results

# ========== 🔧 新增：FDR 多重檢定校正 ==========
def apply_fdr_correction(feature_pvalues, alpha=0.05):
    """
    對特徵層級的 p-values 進行 FDR (False Discovery Rate) 校正
    
    使用 Benjamini-Hochberg 方法
    
    """
    from statsmodels.stats.multitest import multipletests
    
    print("\n🔧 進行 FDR 多重檢定校正 (Benjamini-Hochberg)...")
    
    # 移除 NaN 值
    valid_mask = ~np.isnan(feature_pvalues)
    valid_pvalues = feature_pvalues[valid_mask]
    
    if len(valid_pvalues) == 0:
        print("   ⚠ 沒有有效的 p-values，跳過 FDR 校正")
        return {
            'fdr_corrected_pvalues': feature_pvalues,
            'significant_features': np.zeros(len(feature_pvalues), dtype=bool),
            'n_significant': 0
        }
    
    # FDR 校正
    reject, pvals_corrected, _, _ = multipletests(
        valid_pvalues, alpha=alpha, method='fdr_bh'
    )
    
    # 將校正後的 p-values 放回原位置
    fdr_corrected = np.full(len(feature_pvalues), np.nan)
    fdr_corrected[valid_mask] = pvals_corrected
    
    significant = np.zeros(len(feature_pvalues), dtype=bool)
    significant[valid_mask] = reject
    
    n_significant = np.sum(significant)
    
    print(f"   - 原始 p-values 數量: {len(valid_pvalues)}")
    print(f"   - FDR 校正後顯著特徵數: {n_significant} ({n_significant/len(valid_pvalues)*100:.1f}%)")
    
    return {
        'fdr_corrected_pvalues': fdr_corrected,
        'significant_features': significant,
        'n_significant': n_significant
    }

# ========== 🔧 新增：Permutation Test for Silhouette Coefficient ==========
def permutation_test_silhouette(data_scaled, batch_labels, observed_improvement, n_permutations=1000):
    """
    使用 Permutation Test 評估 Silhouette Coefficient 改善的顯著性
    
    Parameters:
    -----------
    data_scaled : np.ndarray
        標準化後的數據 (樣本 x 特徵)
    batch_labels : np.ndarray
        批次標籤
    observed_improvement : float
        觀察到的 Silhouette 改善值（校正前 - 校正後）
    n_permutations : int
        Permutation 次數（預設 1000）
    
    Returns:
    --------
    p_value : float
        Permutation test 的 p-value
    null_distribution : np.ndarray
        Null distribution（隨機排列下的改善值分佈）
    """
    print(f"\n   執行 Permutation Test ({n_permutations} 次隨機排列)...")
    
    n_samples = len(batch_labels)
    null_improvements = []
    
    # 計算原始 Silhouette Score
    try:
        original_silhouette = silhouette_score(data_scaled, batch_labels)
    except:
        return np.nan, np.array([])
    
    # 進行 Permutation Test
    for i in range(n_permutations):
        # 隨機打亂批次標籤
        permuted_labels = np.random.permutation(batch_labels)
        
        try:
            # 計算隨機排列後的 Silhouette Score
            permuted_silhouette = silhouette_score(data_scaled, permuted_labels)
            
            # 計算「改善值」（原始 - 隨機排列）
            null_improvement = original_silhouette - permuted_silhouette
            null_improvements.append(null_improvement)
        except:
            continue
        
        # 進度顯示
        if (i + 1) % 200 == 0:
            print(f"      Permutation 進度: {i + 1}/{n_permutations}")
    
    null_improvements = np.array(null_improvements)
    
    # 計算 p-value（雙尾檢定）
    # p-value = (隨機排列中改善值 >= 觀察值的次數) / 總次數
    if len(null_improvements) > 0:
        p_value = np.sum(null_improvements >= observed_improvement) / len(null_improvements)
    else:
        p_value = np.nan
    
    return p_value, null_improvements

def calculate_silhouette_improvement(original_data, corrected_data, batch_info, n_permutations=1000):
    """
    計算 Silhouette Coefficient 改善情況，並使用 Permutation Test 評估顯著性
    
    ⚠️ 注意：Silhouette Score 越低 = 批次分離越差 = 批次效應越弱（好）
    
    Parameters:
    -----------
    n_permutations : int
        Permutation Test 的隨機排列次數（預設 1000）
    """
    print("\n🔬 計算 Silhouette Coefficient...")
    print("   ⚠️ 注意：Silhouette Score 越低表示批次效應越弱（這是好的）")
    
    # 數據預處理
    original_data_log = np.log2(original_data + 1)
    corrected_data_log = np.log2(corrected_data + 1)
    
    scaler = StandardScaler()
    original_scaled = scaler.fit_transform(original_data_log)
    corrected_scaled = scaler.fit_transform(corrected_data_log)
    
    # 轉換 batch_info 為數值標籤
    unique_batches = sorted(list(set(batch_info)))
    batch_labels = np.array([unique_batches.index(b) for b in batch_info])
    
    # ========== 整體 Silhouette Score ==========
    try:
        original_silhouette = silhouette_score(original_scaled, batch_labels)
        corrected_silhouette = silhouette_score(corrected_scaled, batch_labels)
        overall_improvement = original_silhouette - corrected_silhouette
        
        print(f"   - 校正前整體 Silhouette Score: {original_silhouette:.4f}")
        print(f"   - 校正後整體 Silhouette Score: {corrected_silhouette:.4f}")
        print(f"   - 整體改善: {overall_improvement:.4f}", end="")
        
        if overall_improvement > 0:
            print(f" (正向改善 ✓ - 批次分離減弱)")
        else:
            print(f" (負向改善 ✗ - 批次分離增強)")
        
    except Exception as e:
        print(f"   ⚠ 整體 Silhouette Score 計算失敗: {e}")
        original_silhouette = np.nan
        corrected_silhouette = np.nan
        overall_improvement = np.nan
    
    # ========== Permutation Test（整體層級）==========
    overall_pvalue = np.nan
    null_distribution = np.array([])
    
    if not np.isnan(overall_improvement):
        print(f"\n🎲 執行整體 Permutation Test...")
        overall_pvalue, null_distribution = permutation_test_silhouette(
            corrected_scaled, batch_labels, overall_improvement, n_permutations
        )
        
        if not np.isnan(overall_pvalue):
            print(f"   ✓ Permutation Test p-value: {overall_pvalue:.4f}")
            if overall_pvalue < 0.05:
                print(f"   ✅ 批次效應校正顯著有效 (p < 0.05)")
            else:
                print(f"   ⚠ 批次效應校正效果不顯著 (p >= 0.05)")
    
    # ========== 特徵層級 Silhouette Coefficient ==========
    n_features = original_data.shape[1]
    original_feature_silhouettes = []
    corrected_feature_silhouettes = []
    feature_pvalues = []
    
    print(f"\n   計算 {n_features} 個特徵的 Silhouette Coefficient...")
    
    # 🔧 決定是否對每個特徵執行 Permutation Test
    run_feature_permutation = (n_features <= 500)
    
    if not run_feature_permutation:
        print(f"   ⚠ 特徵數量過多 ({n_features})，跳過特徵層級 Permutation Test")
    else:
        print(f"   執行特徵層級 Permutation Test (每個特徵 1000 次)")
    
    for i in range(n_features):
        original_feature = original_scaled[:, i].reshape(-1, 1)
        corrected_feature = corrected_scaled[:, i].reshape(-1, 1)
        
        try:
            original_sil = silhouette_score(original_feature, batch_labels)
            corrected_sil = silhouette_score(corrected_feature, batch_labels)
            
            original_feature_silhouettes.append(original_sil)
            corrected_feature_silhouettes.append(corrected_sil)
            
            # 🔧 特徵層級 Permutation Test（提高到 1000 次）
            if run_feature_permutation:
                feature_improvement = original_sil - corrected_sil
                feature_pvalue, _ = permutation_test_silhouette(
                    corrected_feature, batch_labels, feature_improvement, n_permutations=1000
                )
                feature_pvalues.append(feature_pvalue)
            else:
                feature_pvalues.append(np.nan)
                
        except Exception as e:
            original_feature_silhouettes.append(np.nan)
            corrected_feature_silhouettes.append(np.nan)
            feature_pvalues.append(np.nan)
        
        if (i + 1) % 100 == 0:
            print(f"      處理進度: {i + 1}/{n_features} features")
    
    original_feature_silhouettes = np.array(original_feature_silhouettes)
    corrected_feature_silhouettes = np.array(corrected_feature_silhouettes)
    feature_pvalues = np.array(feature_pvalues)
    
    silhouette_improvement = original_feature_silhouettes - corrected_feature_silhouettes
    
    # 統計摘要
    valid_improvements = silhouette_improvement[~np.isnan(silhouette_improvement)]
    if len(valid_improvements) > 0:
        print(f"\n📊 Silhouette Coefficient 統計摘要:")
        print(f"   - 平均改善: {np.mean(valid_improvements):.4f}")
        print(f"   - 中位數改善: {np.median(valid_improvements):.4f}")
        print(f"   - 改善特徵數: {np.sum(valid_improvements > 0)}/{len(valid_improvements)} ({np.sum(valid_improvements > 0)/len(valid_improvements)*100:.1f}%)")
        
        if run_feature_permutation:
            valid_pvalues = feature_pvalues[~np.isnan(feature_pvalues)]
            if len(valid_pvalues) > 0:
                print(f"   - 顯著改善 (p<0.05): {np.sum(valid_pvalues < 0.05)}/{len(valid_pvalues)} ({np.sum(valid_pvalues < 0.05)/len(valid_pvalues)*100:.1f}%)")
    
    return {
        'overall_original': original_silhouette,
        'overall_corrected': corrected_silhouette,
        'overall_improvement': overall_improvement,
        'overall_pvalue': overall_pvalue,
        'null_distribution': null_distribution,
        'feature_original': original_feature_silhouettes,
        'feature_corrected': corrected_feature_silhouettes,
        'feature_improvement': silhouette_improvement,
        'feature_pvalues': feature_pvalues
    }

# ========== 🔧 修正：使用 Hotelling T² 取代馬氏距離檢測異常值 ==========
def calculate_hotelling_t2_outliers(qc_scores, all_scores, alpha=0.05):
    """
    使用 Hotelling T² 檢測 QC 樣本是否偏離整體中心
    
    🔧 修正：使用「所有樣本」的協方差矩陣，但只檢測 QC 樣本
    
    Parameters:
    -----------
    qc_scores : ndarray
        QC 樣本的 PCA 分數 (n_qc, n_components)
    all_scores : ndarray
        所有樣本的 PCA 分數 (n_all, n_components)
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
    n_all = all_scores.shape[0]
    
    if n_qc < 1 or n_all < 3:
        return np.zeros(n_qc), 0, np.zeros(n_qc, dtype=bool)
    
    # 🔧 關鍵修正：使用「所有樣本」的統計量
    mean_all = np.mean(all_scores, axis=0)  # 所有樣本的均值（≈原點）
    cov_all = np.cov(all_scores, rowvar=False)  # 所有樣本的協方差矩陣
    
    # 正則化協方差矩陣
    cov_reg = cov_all + np.eye(p) * 1e-6
    
    try:
        cov_inv = np.linalg.inv(cov_reg)
    except np.linalg.LinAlgError:
        print("   警告：協方差矩陣奇異，使用偽逆矩陣")
        cov_inv = np.linalg.pinv(cov_reg)
    
    # 計算每個 QC 樣本的 Hotelling T² 值
    t2_values = np.zeros(n_qc)
    for i in range(n_qc):
        diff = qc_scores[i] - mean_all  # 相對於所有樣本的均值
        t2_values[i] = np.dot(np.dot(diff, cov_inv), diff.T)
    
    # 🔧 使用卡方分布計算閾值（單樣本 T²）
    threshold = chi2.ppf(1 - alpha, p)
    
    # 識別異常值
    outliers = t2_values > threshold
    
    return t2_values, threshold, outliers



def calculate_hotelling_t2_outliers_internal(scores, alpha=0.05):
    """
    使用 Hotelling T² 檢測樣本內部的異常值（相對於群體均值）
    
    適用場景：檢測 QC 樣本中的離群值
    
    """
    n, p = scores.shape
    
    if n < 3:
        return np.zeros(n), 0, np.zeros(n, dtype=bool)
    
    # 🔧 使用「內部統計量」
    mean = np.mean(scores, axis=0)  # QC 樣本的均值
    cov = np.cov(scores, rowvar=False)  # QC 樣本的協方差矩陣
    
    # 正則化協方差矩陣
    cov_reg = cov + np.eye(p) * 1e-6
    
    try:
        cov_inv = np.linalg.inv(cov_reg)
    except np.linalg.LinAlgError:
        print("   警告：協方差矩陣奇異，使用偽逆矩陣")
        cov_inv = np.linalg.pinv(cov_reg)
    
    # 計算 Hotelling T² 值
    t2_values = np.zeros(n)
    for i in range(n):
        diff = scores[i] - mean  # 相對於 QC 均值
        t2_values[i] = np.dot(np.dot(diff, cov_inv), diff.T)
    
    # 🔧 使用正確的閾值公式（考慮樣本數）
    # 參考：Montgomery (2009), "Introduction to Statistical Quality Control"
    if n - p - 1 > 0:
        f_critical = f_dist.ppf(1 - alpha, p, n - p - 1)
        threshold = (p * (n + 1) * (n - 1)) / (n * (n - p - 1)) * f_critical
    else:
        # 樣本數太少，使用卡方分布
        threshold = chi2.ppf(1 - alpha, p)
    
    # 識別異常值
    outliers = t2_values > threshold
    
    return t2_values, threshold, outliers



def draw_hotelling_t2_ellipse(ax, scores, alpha=0.05, label=None, edgecolor='red', linestyle='-', linewidth=2.5):
    """
    在 2D PCA 圖上繪製 95% Hotelling T² 橢圓，並返回橢圓邊界
    """
    n, p = scores.shape
    
    if n < 3:
        print(f"   ⚠ 樣本數不足 ({n})，無法繪製 Hotelling T² 橢圓")
        return None
    
    mean = np.mean(scores, axis=0)
    cov = np.cov(scores, rowvar=False)
    
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    
    idx = eigenvalues.argsort()[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    
    eigenvalues = np.maximum(eigenvalues, 1e-10)
    
    f_critical = f_dist.ppf(1 - alpha, p, n - p)
    
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

def create_comparison_pca_plot(original_data, corrected_data, sample_info, sample_columns, batch_info, title_suffix="", grouping="batch"):
    """
    創建前後對比的 PCA 圖（左圖：校正前，右圖：校正後）
    
    Parameters:
    -----------
    grouping : str
        'batch' 或 'sample_type'，決定橢圓繪製方式
    """
    sample_meta = sample_info.set_index('Sample_Name')
    
    qc_columns = []
    control_columns = []
    exposed_columns = []
    sample_batches = {}
    
    for col in sample_columns:
        if col in sample_meta.index:
            sample_type = sample_meta.loc[col].get('Sample_Type', 'Unknown')
            sample_type_upper = str(sample_type).upper()
            batch = sample_meta.loc[col].get('Batch', 'Unknown')
            
            sample_batches[col] = batch
            
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
            control_columns.append(col)
            sample_batches[col] = 'Unknown'
    
    if len(sample_columns) < 3:
        print("   ⚠ 樣本數量不足，無法進行 PCA 分析")
        return None
    
    # 數據預處理
    def preprocess_data(data):
        data_processed = data.astype(float)
        min_nonzero = np.min(data_processed[data_processed > 0]) if np.any(data_processed > 0) else 1
        data_processed[data_processed == 0] = min_nonzero / 2
        data_processed = np.nan_to_num(data_processed, nan=min_nonzero / 2)
        data_log = np.log2(data_processed + 1)
        scaler = StandardScaler()
        return scaler.fit_transform(data_log)
    
    original_scaled = preprocess_data(original_data)
    corrected_scaled = preprocess_data(corrected_data)
    
    # PCA
    pca_original = PCA(n_components=2)
    pca_corrected = PCA(n_components=2)
    
    scores_original = pca_original.fit_transform(original_scaled)
    scores_corrected = pca_corrected.fit_transform(corrected_scaled)
    
    var_original = pca_original.explained_variance_ratio_
    var_corrected = pca_corrected.explained_variance_ratio_
    
    # 🔧 使用 Hotelling T² 檢測 QC 異常值
    qc_indices = [i for i, col in enumerate(sample_columns) if col in qc_columns]

    if len(qc_indices) >= 3:
        qc_scores_original = scores_original[qc_indices]
        qc_scores_corrected = scores_corrected[qc_indices]
        
        # 🔧 根據 grouping 模式選擇不同的異常值檢測方法
        if grouping == "batch":
            # 按 Batch 分組：使用「所有樣本」的統計量
            t2_orig, t2_threshold_orig, outliers_orig = calculate_hotelling_t2_outliers(
                qc_scores_original, scores_original, alpha=0.05
            )
            t2_corr, t2_threshold_corr, outliers_corr = calculate_hotelling_t2_outliers(
                qc_scores_corrected, scores_corrected, alpha=0.05
            )
        else:  # grouping == "sample_type"
            # 按樣本類型分組：使用「QC 內部」的統計量
            t2_orig, t2_threshold_orig, outliers_orig = calculate_hotelling_t2_outliers_internal(
                qc_scores_original, alpha=0.05
            )
            t2_corr, t2_threshold_corr, outliers_corr = calculate_hotelling_t2_outliers_internal(
                qc_scores_corrected, alpha=0.05
            )
        
        # 🔧 輸出異常值檢測結果
        print(f"\n🔍 Hotelling T² 異常值檢測 (模式: {grouping}):")
        print(f"   校正前:")
        print(f"   - T² 閾值: {t2_threshold_orig:.2f}")
        print(f"   - 異常值數量: {np.sum(outliers_orig)}/{len(qc_columns)}")
        if np.sum(outliers_orig) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_orig)) if outliers_orig[i]]
            outlier_t2_values = [t2_orig[i] for i in range(len(outliers_orig)) if outliers_orig[i]]
            print(f"   - 異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"     • {sample}: T² = {t2_val:.2f}")
        
        print(f"\n   校正後:")
        print(f"   - T² 閾值: {t2_threshold_corr:.2f}")
        print(f"   - 異常值數量: {np.sum(outliers_corr)}/{len(qc_columns)}")
        if np.sum(outliers_corr) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_corr)) if outliers_corr[i]]
            outlier_t2_values = [t2_corr[i] for i in range(len(outliers_corr)) if outliers_corr[i]]
            print(f"   - 異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"     • {sample}: T² = {t2_val:.2f}")
    else:
        outliers_orig = np.zeros(len(qc_indices), dtype=bool)
        outliers_corr = np.zeros(len(qc_indices), dtype=bool)
    
    # 創建畫布（左右並排）
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(20, 8))
    
    if grouping == "batch":
        fig.suptitle(f'2D PCA Comparison: Before vs After Correction (Grouped by Batch){title_suffix}',
                     fontsize=16, y=0.98, fontweight='bold')
    else:
        fig.suptitle(f'2D PCA Comparison: Before vs After Correction (Grouped by Sample Type){title_suffix}',
                     fontsize=16, y=0.98, fontweight='bold')
    
    color_map = {
        'QC': '#9370DB',
        'Control': '#4169E1',
        'Exposure': '#DC143C'
    }
    
    markers = {'QC': 'o', 'Control': 's', 'Exposure': '^'}
    
    unique_batches = sorted(list(set(sample_batches.values())))
    batch_colors = COLORBLIND_COLORS[:len(unique_batches)]
    batch_color_map = {batch: batch_colors[i] for i, batch in enumerate(unique_batches)}
    
    # ========== 左圖：校正前 ==========
    for i, col in enumerate(sample_columns):
        if col in qc_columns:
            sample_type = 'QC'
            qc_idx = qc_columns.index(col)
            is_outlier = outliers_orig[qc_idx] if qc_idx < len(outliers_orig) else False
        elif col in exposed_columns:
            sample_type = 'Exposure'
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
        
        ax_left.scatter(scores_original[i, 0], scores_original[i, 1],
                       c=[color], marker=marker, s=size, alpha=alpha,
                       edgecolors=edgecolor, linewidths=linewidth)
    
    # 繪製橢圓（左圖）
    all_bounds_left = []
    
    if grouping == "batch":
        # 按 Batch 繪製橢圓
        for batch in unique_batches:
            batch_sample_cols = [col for col in sample_columns if sample_batches.get(col) == batch]
            batch_indices = [i for i, col in enumerate(sample_columns) if col in batch_sample_cols]
            
            if len(batch_indices) >= 3:
                batch_scores = scores_original[batch_indices]
                try:
                    bounds = draw_hotelling_t2_ellipse(ax_left, batch_scores, 
                                                       label=f'95% CI (Batch {batch})', 
                                                       edgecolor=batch_color_map[batch], 
                                                       linestyle='-', 
                                                       linewidth=2.5)
                    if bounds is not None:
                        all_bounds_left.append(bounds)
                except Exception as e:
                    print(f"   ⚠ Batch {batch} 橢圓繪製失敗: {e}")
    else:
        # 按樣本類型繪製橢圓（所有樣本 + QC）
        try:
            bounds_all = draw_hotelling_t2_ellipse(ax_left, scores_original, 
                                                   label='95% CI (All Samples)', 
                                                   edgecolor='gray', 
                                                   linestyle='--', 
                                                   linewidth=3)
            if bounds_all is not None:
                all_bounds_left.append(bounds_all)
        except Exception as e:
            print(f"   ⚠ 所有樣本橢圓繪製失敗: {e}")
        
        if len(qc_indices) >= 3:
            try:
                bounds_qc = draw_hotelling_t2_ellipse(ax_left, qc_scores_original, 
                                                      label='95% CI (QC Only)', 
                                                      edgecolor='#9370DB', 
                                                      linestyle='-', 
                                                      linewidth=3)
                if bounds_qc is not None:
                    all_bounds_left.append(bounds_qc)
            except Exception as e:
                print(f"   ⚠ QC 橢圓繪製失敗: {e}")
    
    # 調整左圖軸範圍
    if all_bounds_left:
        x_min = min([b[0] for b in all_bounds_left])
        x_max = max([b[1] for b in all_bounds_left])
        y_min = min([b[2] for b in all_bounds_left])
        y_max = max([b[3] for b in all_bounds_left])
    else:
        x_min, x_max = np.min(scores_original[:, 0]), np.max(scores_original[:, 0])
        y_min, y_max = np.min(scores_original[:, 1]), np.max(scores_original[:, 1])
    
    data_x_min, data_x_max = np.min(scores_original[:, 0]), np.max(scores_original[:, 0])
    data_y_min, data_y_max = np.min(scores_original[:, 1]), np.max(scores_original[:, 1])
    
    x_min = min(x_min, data_x_min)
    x_max = max(x_max, data_x_max)
    y_min = min(y_min, data_y_min)
    y_max = max(y_max, data_y_max)
    
    x_margin = (x_max - x_min) * 0.2
    y_margin = (y_max - y_min) * 0.2
    
    ax_left.set_xlim(x_min - x_margin, x_max + x_margin)
    ax_left.set_ylim(y_min - y_margin, y_max + y_margin)
    
    ax_left.set_xlabel(f'PC1 ({var_original[0]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax_left.set_ylabel(f'PC2 ({var_original[1]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax_left.set_title('Before Correction', fontsize=14, fontweight='bold', pad=15)
    ax_left.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
    ax_left.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
    ax_left.grid(True, alpha=0.3, linestyle='--')
    
    # ========== 右圖：校正後 ==========
    for i, col in enumerate(sample_columns):
        if col in qc_columns:
            sample_type = 'QC'
            qc_idx = qc_columns.index(col)
            is_outlier = outliers_corr[qc_idx] if qc_idx < len(outliers_corr) else False
        elif col in exposed_columns:
            sample_type = 'Exposure'
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
        
        ax_right.scatter(scores_corrected[i, 0], scores_corrected[i, 1],
                        c=[color], marker=marker, s=size, alpha=alpha,
                        edgecolors=edgecolor, linewidths=linewidth)
    
    # 繪製橢圓（右圖）
    all_bounds_right = []
    
    if grouping == "batch":
        # 按 Batch 繪製橢圓
        for batch in unique_batches:
            batch_sample_cols = [col for col in sample_columns if sample_batches.get(col) == batch]
            batch_indices = [i for i, col in enumerate(sample_columns) if col in batch_sample_cols]
            
            if len(batch_indices) >= 3:
                batch_scores = scores_corrected[batch_indices]
                try:
                    bounds = draw_hotelling_t2_ellipse(ax_right, batch_scores, 
                                                       label=f'95% CI (Batch {batch})', 
                                                       edgecolor=batch_color_map[batch], 
                                                       linestyle='-', 
                                                       linewidth=2.5)
                    if bounds is not None:
                        all_bounds_right.append(bounds)
                except Exception as e:
                    print(f"   ⚠ Batch {batch} 橢圓繪製失敗: {e}")
    else:
        # 按樣本類型繪製橢圓（所有樣本 + QC）
        try:
            bounds_all = draw_hotelling_t2_ellipse(ax_right, scores_corrected, 
                                                   label='95% CI (All Samples)', 
                                                   edgecolor='gray', 
                                                   linestyle='--', 
                                                   linewidth=3)
            if bounds_all is not None:
                all_bounds_right.append(bounds_all)
        except Exception as e:
            print(f"   ⚠ 所有樣本橢圓繪製失敗: {e}")
        
        if len(qc_indices) >= 3:
            try:
                bounds_qc = draw_hotelling_t2_ellipse(ax_right, qc_scores_corrected, 
                                                      label='95% CI (QC Only)', 
                                                      edgecolor='#9370DB', 
                                                      linestyle='-', 
                                                      linewidth=3)
                if bounds_qc is not None:
                    all_bounds_right.append(bounds_qc)
            except Exception as e:
                print(f"   ⚠ QC 橢圓繪製失敗: {e}")
    
    # 調整右圖軸範圍
    if all_bounds_right:
        x_min = min([b[0] for b in all_bounds_right])
        x_max = max([b[1] for b in all_bounds_right])
        y_min = min([b[2] for b in all_bounds_right])
        y_max = max([b[3] for b in all_bounds_right])
    else:
        x_min, x_max = np.min(scores_corrected[:, 0]), np.max(scores_corrected[:, 0])
        y_min, y_max = np.min(scores_corrected[:, 1]), np.max(scores_corrected[:, 1])
    
    data_x_min, data_x_max = np.min(scores_corrected[:, 0]), np.max(scores_corrected[:, 0])
    data_y_min, data_y_max = np.min(scores_corrected[:, 1]), np.max(scores_corrected[:, 1])
    
    x_min = min(x_min, data_x_min)
    x_max = max(x_max, data_x_max)
    y_min = min(y_min, data_y_min)
    y_max = max(y_max, data_y_max)
    
    x_margin = (x_max - x_min) * 0.2
    y_margin = (y_max - y_min) * 0.2
    
    ax_right.set_xlim(x_min - x_margin, x_max + x_margin)
    ax_right.set_ylim(y_min - y_margin, y_max + y_margin)
    
    ax_right.set_xlabel(f'PC1 ({var_corrected[0]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax_right.set_ylabel(f'PC2 ({var_corrected[1]*100:.1f}%)', fontsize=12, fontweight='bold')
    ax_right.set_title('After Correction', fontsize=14, fontweight='bold', pad=15)
    ax_right.axhline(y=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
    ax_right.axvline(x=0, color='k', linestyle='-', linewidth=1.5, alpha=0.5)
    ax_right.grid(True, alpha=0.3, linestyle='--')
    
    # 添加圖例
    sample_legend_elements = [
        plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='#4169E1',
                  markersize=10, label='Control', markeredgecolor='black', markeredgewidth=1),
        plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='#DC143C',
                  markersize=10, label='Exposure', markeredgecolor='black', markeredgewidth=1),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#9370DB',
                  markersize=10, label='QC', markeredgecolor='black', markeredgewidth=1),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='gray',
                  markersize=10, label='QC Outlier', markeredgecolor='red', markeredgewidth=3)
    ]
    
    if grouping == "batch":
        ellipse_legend_elements = [
            plt.Line2D([0], [0], linestyle='-', color=batch_color_map[batch],
                      linewidth=2.5, label=f'95% CI (Batch {batch})')
            for batch in unique_batches
        ]
    else:
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
    
    return fig

def copy_sheet_with_style(src_ws, tgt_ws):
    """
    複製一個工作表的所有儲存格值與格式
    """
    for row in src_ws.iter_rows():
        for cell in row:
            new_cell = tgt_ws[cell.coordinate]
            new_cell.value = cell.value
            if cell.has_style:
                new_cell.font = copy(cell.font)
                new_cell.border = copy(cell.border)
                new_cell.fill = copy(cell.fill)
                new_cell.number_format = cell.number_format
                new_cell.protection = copy(cell.protection)
                new_cell.alignment = copy(cell.alignment)

def color_silhouette_cells(ws):
    """
    根據欄位名稱對特定欄位上色
    
    上色規則：
    - Silhouette 相關欄位：深橘色
    - Cohen's d 相關欄位：淺粉色
    - QC CV% 相關欄位：淺藍色
    - Permutation p-value：根據顯著性上色（綠色=顯著，淺黃=不顯著）
    - FDR p-value：根據顯著性上色（綠色=顯著，淺黃=不顯著）
    - FDR significant：根據 True/False 上色（綠色=TRUE，淺黃=FALSE）
    """
    # 定義顏色
    orange_fill = PatternFill(start_color='FF8C00', end_color='FF8C00', fill_type='solid')  # 深橘色
    light_blue_fill = PatternFill(start_color='ADD8E6', end_color='ADD8E6', fill_type='solid')  # 淺藍色
    green_fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')  # 淺綠色（顯著）
    light_yellow_fill = PatternFill(start_color='FFFF99', end_color='FFFF99', fill_type='solid')  # 淺黃色（不顯著）
    purple_fill = PatternFill(start_color='DDA0DD', end_color='DDA0DD', fill_type='solid')  # 淺紫色
    pink_fill = PatternFill(start_color='FFB6C1', end_color='FFB6C1', fill_type='solid')  # 淺粉色
    
    # 取得欄位標題
    header = [cell.value for cell in ws[1]]
    col_map = {name: idx+1 for idx, name in enumerate(header) if name is not None}
    
    # 定義欄位分組
    silhouette_cols = ['Original_Silhouette', 'Corrected_Silhouette', 'Improvement_Silhouette']
    cohens_d_cols = ['Original_Cohens_d', 'Corrected_Cohens_d', 'Improvement_Cohens_d']
    qc_cv_cols = ['Original_QC_CV%', 'Corrected_QC_CV%', 'Improvement_QC_CV%']
    
    # 🔧 關鍵修正：對每個儲存格進行分類，避免重複上色
    for row in range(2, ws.max_row + 1):
        for col_name, col_idx in col_map.items():
            cell = ws.cell(row=row, column=col_idx)
            
            # 1️⃣ Silhouette 相關欄位 - 深橘色
            if col_name in silhouette_cols:
                cell.fill = orange_fill
            
            # 2️⃣ Cohen's d 相關欄位 - 淺粉色
            elif col_name in cohens_d_cols:
                cell.fill = pink_fill
            
            # 3️⃣ QC CV% 相關欄位 - 淺藍色
            elif col_name in qc_cv_cols:
                cell.fill = light_blue_fill
            
            # 4️⃣ Permutation p-value - 根據顯著性上色
            elif col_name == 'Permutation_pvalue':
                try:
                    p_val = float(cell.value)
                    if p_val < 0.05:
                        cell.fill = green_fill  # 顯著
                    else:
                        cell.fill = light_yellow_fill  # 不顯著
                except (ValueError, TypeError):
                    cell.fill = light_blue_fill  # 無法解析的值
            
            # 5️⃣ FDR corrected p-value - 根據顯著性上色
            elif col_name == 'FDR_corrected_pvalue':
                try:
                    p_val = float(cell.value)
                    if p_val < 0.05:
                        cell.fill = green_fill  # 顯著
                    else:
                        cell.fill = light_yellow_fill  # 不顯著
                except (ValueError, TypeError):
                    cell.fill = purple_fill  # 無法解析的值
            
            # 6️⃣ FDR significant - 根據 True/False 上色
            elif col_name == 'FDR_significant':
                try:
                    # 處理多種可能的布林值格式
                    cell_value = str(cell.value).strip().upper()
                    if cell_value in ['TRUE', '1', '1.0', 'YES']:
                        cell.fill = green_fill  # 顯著
                    elif cell_value in ['FALSE', '0', '0.0', 'NO']:
                        cell.fill = light_yellow_fill  # 不顯著
                    else:
                        cell.fill = purple_fill  # 其他值
                except (ValueError, TypeError):
                    cell.fill = purple_fill  # 無法解析的值
    
    print(f"   ✓ 已對 Excel 工作表進行條件格式化上色")

def copy_all_sheets(input_file, output_file, data_sheet_name, data, sample_info, corrected_df):
    """
    複製輸入Excel的所有工作表到輸出Excel，並覆蓋或新增修改的部分
    並保留「QC LOWESS result」工作表的格式
    """
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        data.to_excel(writer, sheet_name=data_sheet_name, index=False)
        sample_info.to_excel(writer, sheet_name='SampleInfo', index=False)
        corrected_df.to_excel(writer, sheet_name='Batch_effect_result', index=False)
    
    input_wb = load_workbook(input_file, data_only=True)
    output_wb = load_workbook(output_file)
    
    output_sheet_names = output_wb.sheetnames
    
    for sheet_name in input_wb.sheetnames:
        if sheet_name == 'QC LOWESS result':
            if sheet_name in output_sheet_names:
                std = output_wb[sheet_name]
                output_wb.remove(std)
            new_sheet = output_wb.create_sheet(sheet_name)
            copy_sheet_with_style(input_wb[sheet_name], new_sheet)
        else:
            if sheet_name not in output_sheet_names:
                new_sheet = output_wb.create_sheet(sheet_name)
                copy_sheet_with_style(input_wb[sheet_name], new_sheet)
    
    if 'Batch_effect_result' in output_wb.sheetnames:
        ws = output_wb['Batch_effect_result']
        color_silhouette_cells(ws)
    
    output_wb.save(output_file)
    print(f"✓ 已複製所有輸入工作表到輸出檔案，並更新修改的部分（包含保留『QC LOWESS result』格式）")

# ========== 🔧 完整 main() 函數 ==========
def main(input_file=None):
    """
    主函數 - 支援 GUI 和獨立運行
    """
    print("="*70)
    print("  批次效應校正程式 v4.0 (使用 pycombat)")
    print("  - Silhouette Coefficient 評估批次效應")
    print("  - Permutation Test 顯著性檢定")
    print("  - Cohen's d 效果量")
    print("  - QC CV% 技術重現性")
    print("  - PCA-ANOVA 批次影響檢驗")
    print("  - FDR 多重檢定校正")
    print("="*70)
    
    if input_file is None:
        print("\n請選擇要處理的Excel檔案...")
        input_file = select_file()
        
        if not input_file:
            print("❌ 未選擇檔案，程式結束。")
            return None
    
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"找不到檔案: {input_file}")
    
    print(f"\n✓ 選擇的檔案: {os.path.basename(input_file)}")
    
    output_dir = os.path.dirname(input_file)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.normpath(os.path.join(output_dir, f'Combat_corrected_{timestamp}.xlsx'))
    
    plots_dir = os.path.join(output_dir, 'Batch_Effect_plots')
    if not os.path.exists(plots_dir):
        os.makedirs(plots_dir)
        print(f"✓ 已創建資料夾: {plots_dir}")
    
    try:
        print("\n正在讀取數據...")
        data, sample_info, sheet_name = read_excel_data(input_file)
        print(f"✓ 已讀取工作表: {sheet_name}")
        
        print("\n二次檢查 Batch 分組資料...")
        if sample_info.shape[1] >= 4:
            column_d = sample_info.columns[3]
            print(f"檢查 column D ('{column_d}') 中的 Batch 資訊...")
            if 'batch' in str(column_d).lower():
                print(f"✓ column D 確認為 Batch 列，使用它來二次驗證批次資訊")
                sample_info['Batch'] = sample_info[column_d]
        
        print("\n準備數據格式...")
        data_matrix, batch_info, sample_columns, feature_ids = prepare_data_for_combat(data, sample_info)
        print(f"✓ 找到 {len(sample_columns)} 個樣本，{len(feature_ids)} 個特徵")
        unique_batches = list(set(batch_info))
        print(f"✓ 批次信息: {unique_batches}")
        print(f"  批次數量: {len(unique_batches)}")
        
        if len(unique_batches) < 2:
            print("\n警告：只有一個批次，無需進行批次效應校正")
            raise Exception("只有一個批次")
        
        # ========== 🆕 校正前評估 ==========
        print("\n" + "="*70)
        print("📊 校正前批次效應評估")
        print("="*70)
        
        original_data_for_eval = data_matrix.T
        
        # 1. QC CV%
        qc_cv_before = calculate_qc_cv(data_matrix, sample_info, sample_columns)
        
        # 2. Cohen's d
        original_data_log = np.log2(original_data_for_eval + 1)
        scaler_before = StandardScaler()
        original_scaled = scaler_before.fit_transform(original_data_log)
        cohens_d_before = calculate_cohens_d_batch_effect(original_scaled, batch_info)
        
        # 3. PCA-ANOVA
        pca_anova_before = calculate_pca_anova(original_scaled, batch_info)
        
        # ========== Combat 校正 ==========
        print("\n" + "="*70)
        print("⚙️ 執行 Combat 批次效應校正")
        print("="*70)
        corrected_data = perform_combat_correction(data_matrix, batch_info)
        print("✓ 批次效應校正完成")
        
        if corrected_data.shape[1] != len(sample_columns):
            corrected_data = corrected_data.T
        
        # ========== 🆕 校正後評估 ==========
        print("\n" + "="*70)
        print("📊 校正後批次效應評估")
        print("="*70)
        
        corrected_data_for_eval = corrected_data.T
        
        # 1. QC CV%
        qc_cv_after = calculate_qc_cv(corrected_data, sample_info, sample_columns)
        
        # 2. Cohen's d
        corrected_data_log = np.log2(corrected_data_for_eval + 1)
        scaler_after = StandardScaler()
        corrected_scaled = scaler_after.fit_transform(corrected_data_log)
        cohens_d_after = calculate_cohens_d_batch_effect(corrected_scaled, batch_info)
        
        # 3. PCA-ANOVA
        pca_anova_after = calculate_pca_anova(corrected_scaled, batch_info)
        
        # 4. Silhouette Coefficient + Permutation Test
        n_permutations = 1000
        silhouette_results = calculate_silhouette_improvement(
            original_data_for_eval, corrected_data_for_eval, batch_info, 
            n_permutations=n_permutations
        )
        
        # 5. FDR 校正
        fdr_results = apply_fdr_correction(silhouette_results['feature_pvalues'], alpha=0.05)
        
        # ========== 🆕 計算 QC CV% Improvement ==========
        # 確保兩個 CV 陣列長度相同
        if len(qc_cv_before['qc_cv']) > 0 and len(qc_cv_after['qc_cv']) > 0:
            if len(qc_cv_before['qc_cv']) == len(qc_cv_after['qc_cv']):
                qc_cv_improvement = qc_cv_before['qc_cv'] - qc_cv_after['qc_cv']
            else:
                print(f"   ⚠ QC CV% 陣列長度不一致，無法計算 Improvement")
                qc_cv_improvement = np.array([])
        else:
            qc_cv_improvement = np.array([])
        
        # ========== 🆕 前後對比統計摘要 ==========
        print("\n" + "="*70)
        print("📈 批次效應校正前後對比統計摘要")
        print("="*70)
        
        print("\n1️⃣ QC CV% (技術重現性):")
        print(f"   校正前 (Original): 中位數 = {qc_cv_before['median_cv']:.2f}%, CV<20% = {qc_cv_before['cv_below_20']:.1f}%")
        print(f"   校正後 (Corrected): 中位數 = {qc_cv_after['median_cv']:.2f}%, CV<20% = {qc_cv_after['cv_below_20']:.1f}%")
        
        cv_change = qc_cv_after['median_cv'] - qc_cv_before['median_cv']
        print(f"   改善 (Improvement): {-cv_change:+.2f}%", end="")  # 注意：負號表示改善
        
        if abs(cv_change) < 2:
            print(f" (基本不變 ✓)")
        elif cv_change < 0:
            print(f" (改善 ✓)")
        else:
            print(f" (惡化 ⚠)")
        
        # 🆕 CV% Improvement 統計
        if len(qc_cv_improvement) > 0:
            improvement_median = np.median(qc_cv_improvement)
            improvement_positive_ratio = np.sum(qc_cv_improvement > 0) / len(qc_cv_improvement) * 100
            print(f"   - CV% 改善中位數: {improvement_median:+.2f}%")
            print(f"   - CV% 改善特徵比例: {improvement_positive_ratio:.1f}%")
        
        print("\n2️⃣ Cohen's d (批次效應大小):")
        print(f"   校正前: {cohens_d_before['overall_cohens_d']:.4f}")
        print(f"   校正後: {cohens_d_after['overall_cohens_d']:.4f}")
        
        if cohens_d_before['overall_cohens_d'] > 0:
            d_reduction = (cohens_d_before['overall_cohens_d'] - cohens_d_after['overall_cohens_d']) / cohens_d_before['overall_cohens_d'] * 100
            print(f"   減少: {d_reduction:.1f}%", end="")
            if d_reduction > 50:
                print(f" (大幅改善 ✓✓)")
            elif d_reduction > 20:
                print(f" (顯著改善 ✓)")
            elif d_reduction > 0:
                print(f" (輕微改善)")
            else:
                print(f" (未改善 ⚠)")
        
        print("\n3️⃣ PCA-ANOVA (批次對主成分的影響):")
        print(f"   PC1:")
        print(f"     校正前: p = {pca_anova_before['pc1_pvalue']:.4f}, η² = {pca_anova_before['pc1_eta_squared']:.4f}")
        print(f"     校正後: p = {pca_anova_after['pc1_pvalue']:.4f}, η² = {pca_anova_after['pc1_eta_squared']:.4f}")
        
        print(f"   PC2:")
        print(f"     校正前: p = {pca_anova_before['pc2_pvalue']:.4f}, η² = {pca_anova_before['pc2_eta_squared']:.4f}")
        print(f"     校正後: p = {pca_anova_after['pc2_pvalue']:.4f}, η² = {pca_anova_after['pc2_eta_squared']:.4f}")
        
        print("\n4️⃣ Silhouette Coefficient (批次分離程度):")
        print(f"   校正前: {silhouette_results['overall_original']:.4f}")
        print(f"   校正後: {silhouette_results['overall_corrected']:.4f}")
        print(f"   改善值: {silhouette_results['overall_improvement']:.4f}")
        
        if not np.isnan(silhouette_results['overall_pvalue']):
            print(f"   Permutation Test p-value: {silhouette_results['overall_pvalue']:.4f}", end="")
            if silhouette_results['overall_pvalue'] < 0.001:
                print(f" *** (極顯著)")
            elif silhouette_results['overall_pvalue'] < 0.01:
                print(f" ** (非常顯著)")
            elif silhouette_results['overall_pvalue'] < 0.05:
                print(f" * (顯著)")
            else:
                print(f" n.s. (不顯著)")
        
        print(f"\n5️⃣ FDR 多重檢定校正:")
        print(f"   顯著改善特徵數 (FDR < 0.05): {fdr_results['n_significant']}/{len(fdr_results['significant_features'])}")
        
        
        # ========== 生成圖表 ==========
        print("\n" + "="*70)
        print("🎨 生成視覺化圖表")
        print("="*70)
        
        # 1. 按 Batch 分組
        print("\n生成 PCA 前後對比圖（按 Batch 分組）...")
        fig_batch = create_comparison_pca_plot(
            original_data_for_eval, corrected_data_for_eval, 
            sample_info, sample_columns, batch_info, 
            title_suffix="", grouping="batch"
        )
        
        if fig_batch:
            pca_batch_file = os.path.join(plots_dir, f'PCA_comparison_by_batch_{timestamp}.png')
            fig_batch.savefig(pca_batch_file, dpi=300, bbox_inches='tight')
            plt.close(fig_batch)
            print(f"✓ 已儲存: {os.path.basename(pca_batch_file)}")
        
        # 2. 按樣本類型分組
        print("\n生成 PCA 前後對比圖（按樣本類型分組）...")
        fig_type = create_comparison_pca_plot(
            original_data_for_eval, corrected_data_for_eval, 
            sample_info, sample_columns, batch_info, 
            title_suffix="", grouping="sample_type"
        )
        
        if fig_type:
            pca_type_file = os.path.join(plots_dir, f'PCA_comparison_by_sample_type_{timestamp}.png')
            fig_type.savefig(pca_type_file, dpi=300, bbox_inches='tight')
            plt.close(fig_type)
            print(f"✓ 已儲存: {os.path.basename(pca_type_file)}")
        
        # 3. Permutation Test 分佈圖
        if len(silhouette_results['null_distribution']) > 0:
            print("\n生成 Permutation Test 分佈圖...")
            fig_perm = plot_permutation_distribution(
                silhouette_results['null_distribution'],
                silhouette_results['overall_improvement'],
                silhouette_results['overall_pvalue']
            )
            
            if fig_perm:
                perm_file = os.path.join(plots_dir, f'Permutation_Test_Distribution_{timestamp}.png')
                fig_perm.savefig(perm_file, dpi=300, bbox_inches='tight')
                plt.close(fig_perm)
                print(f"✓ 已儲存: {os.path.basename(perm_file)}")
        
        # ========== 準備輸出 Excel ==========
        print("\n準備輸出結果...")
        corrected_df = pd.DataFrame(corrected_data, columns=sample_columns)
        corrected_df.insert(0, data.columns[0], feature_ids)
        
        # 🆕 修改：使用新的命名方式
        corrected_df['Original_Silhouette'] = silhouette_results['feature_original']
        corrected_df['Corrected_Silhouette'] = silhouette_results['feature_corrected']
        corrected_df['Improvement_Silhouette'] = silhouette_results['feature_improvement']
        corrected_df['Permutation_pvalue'] = silhouette_results['feature_pvalues']
        corrected_df['FDR_corrected_pvalue'] = fdr_results['fdr_corrected_pvalues']
        corrected_df['FDR_significant'] = fdr_results['significant_features']
        
        # 🆕 添加 Cohen's d
        corrected_df['Original_Cohens_d'] = cohens_d_before['feature_cohens_d']
        corrected_df['Corrected_Cohens_d'] = cohens_d_after['feature_cohens_d']
        corrected_df['Improvement_Cohens_d'] = cohens_d_before['feature_cohens_d'] - cohens_d_after['feature_cohens_d']
        
        # 🆕 修改：使用新的 CV% 命名方式
        if len(qc_cv_before['qc_cv']) > 0:
            corrected_df['Original_QC_CV%'] = qc_cv_before['qc_cv']
            corrected_df['Corrected_QC_CV%'] = qc_cv_after['qc_cv']
            
            # 🆕 添加 CV% Improvement
            if len(qc_cv_improvement) > 0:
                corrected_df['Improvement_QC_CV%'] = qc_cv_improvement
        
        print(f"\n保存結果到: {os.path.basename(output_file)}")
        copy_all_sheets(input_file, output_file, sheet_name, data, sample_info, corrected_df)

        # ========== 最終輸出摘要 ==========
        print("\n" + "="*70)
        print("✅ 批次效應校正完成！")
        print("="*70)
        print(f"\n輸出檔案: {os.path.basename(output_file)}")
        print(f"\nPCA 圖表已儲存到資料夾: {os.path.basename(plots_dir)}")
        if fig_batch:
            print(f"  1. PCA 前後對比（按 Batch）: PCA_comparison_by_batch_{timestamp}.png")
        if fig_type:
            print(f"  2. PCA 前後對比（按樣本類型）: PCA_comparison_by_sample_type_{timestamp}.png")
        if len(silhouette_results['null_distribution']) > 0:
            print(f"  3. Permutation Test 分佈圖: Permutation_Test_Distribution_{timestamp}.png")
        
        print("\n" + "="*70 + "\n")
        
        # 🎯 返回統計資訊給 GUI
        return {
            'file_path': input_file,
            'metabolites': len(feature_ids),
            'samples': len(sample_columns),
            'output_path': output_file,
            'qc_cv_before': qc_cv_before['median_cv'],
            'qc_cv_after': qc_cv_after['median_cv'],
            'qc_cv_improvement': qc_cv_before['median_cv'] - qc_cv_after['median_cv'],  # 🆕
            'cohens_d_before': cohens_d_before['overall_cohens_d'],
            'cohens_d_after': cohens_d_after['overall_cohens_d'],
            'silhouette_improvement': silhouette_results['overall_improvement'],
            'permutation_pvalue': silhouette_results['overall_pvalue']
        }
        
    except Exception as e:
        print(f"\n錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        print("\n請檢查輸入檔案格式是否正確")
        raise


if __name__ == "__main__":
    main()