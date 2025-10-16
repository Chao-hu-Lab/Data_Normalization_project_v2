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

# ========== 🔧 改進：Silhouette Coefficient 計算 + Permutation Test ==========
def calculate_silhouette_improvement(original_data, corrected_data, batch_info, n_permutations=1000):
    """
    計算 Silhouette Coefficient 改善情況，並使用 Permutation Test 評估顯著性
    
    Parameters:
    -----------
    n_permutations : int
        Permutation Test 的隨機排列次數（預設 1000）
    """
    print("\n🔬 計算 Silhouette Coefficient...")
    
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
        print(f"   - 整體改善: {overall_improvement:.4f} (越大越好，表示批次效應減弱)")
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
    # 如果特徵數量太多，可以選擇性執行（例如只對前 100 個特徵）
    run_feature_permutation = (n_features <= 500)  # 特徵數 <= 500 才執行
    
    if not run_feature_permutation:
        print(f"   ⚠ 特徵數量過多 ({n_features})，跳過特徵層級 Permutation Test")
    
    for i in range(n_features):
        # 提取單個特徵的所有樣本值
        original_feature = original_scaled[:, i].reshape(-1, 1)
        corrected_feature = corrected_scaled[:, i].reshape(-1, 1)
        
        try:
            # 計算該特徵的 Silhouette Score
            original_sil = silhouette_score(original_feature, batch_labels)
            corrected_sil = silhouette_score(corrected_feature, batch_labels)
            
            original_feature_silhouettes.append(original_sil)
            corrected_feature_silhouettes.append(corrected_sil)
            
            # 🔧 特徵層級 Permutation Test（可選）
            if run_feature_permutation:
                feature_improvement = original_sil - corrected_sil
                feature_pvalue, _ = permutation_test_silhouette(
                    corrected_feature, batch_labels, feature_improvement, n_permutations=100
                )
                feature_pvalues.append(feature_pvalue)
            else:
                feature_pvalues.append(np.nan)
                
        except Exception as e:
            original_feature_silhouettes.append(np.nan)
            corrected_feature_silhouettes.append(np.nan)
            feature_pvalues.append(np.nan)
        
        # 進度顯示
        if (i + 1) % 100 == 0:
            print(f"      處理進度: {i + 1}/{n_features} features")
    
    original_feature_silhouettes = np.array(original_feature_silhouettes)
    corrected_feature_silhouettes = np.array(corrected_feature_silhouettes)
    feature_pvalues = np.array(feature_pvalues)
    
    # 計算改善
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
    
    # 返回結果字典
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
    Silhouette 欄位塗深橘色，Permutation Test 欄位塗淺藍色
    """
    orange_fill = PatternFill(start_color='FF8C00', end_color='FF8C00', fill_type='solid')
    light_blue_fill = PatternFill(start_color='ADD8E6', end_color='ADD8E6', fill_type='solid')
    green_fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
    light_yellow_fill = PatternFill(start_color='FFFF99', end_color='FFFF99', fill_type='solid')
    
    header = [cell.value for cell in ws[1]]
    col_map = {name: idx+1 for idx, name in enumerate(header)}
    
    silhouette_cols = ['Original_Silhouette', 'Corrected_Silhouette', 'Silhouette_Improvement']
    permutation_cols = ['Permutation_pvalue']
    
    for col_name in silhouette_cols:
        if col_name in col_map:
            col_idx = col_map[col_name]
            for row in range(2, ws.max_row + 1):
                cell = ws.cell(row=row, column=col_idx)
                cell.fill = orange_fill
    
    for col_name in permutation_cols:
        if col_name in col_map:
            col_idx = col_map[col_name]
            for row in range(2, ws.max_row + 1):
                cell = ws.cell(row=row, column=col_idx)
                cell.fill = light_blue_fill
    
    # 根據 p-value 上色
    if 'Permutation_pvalue' in col_map:
        col_idx = col_map['Permutation_pvalue']
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=col_idx)
            try:
                p_val = float(cell.value)
                if p_val < 0.05:
                    cell.fill = green_fill  # 顯著
                else:
                    cell.fill = light_yellow_fill  # 不顯著
            except:
                pass

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
    print("="*70)
    print("  批次效應校正程式 v3.0 (使用 pycombat)")
    print("  - Silhouette Coefficient 評估批次效應")
    print("  - Permutation Test 顯著性檢定")
    print("  - 前後對比 PCA 圖（左右並排）")
    print("="*70)
    
    # 🔧 關鍵修正：如果沒有提供 input_file，則顯示對話框
    if input_file is None:
        print("\n請選擇要處理的Excel檔案...")
        input_file = select_file()
        
        # 如果用戶取消選擇，返回 None
        if not input_file:
            print("❌ 未選擇檔案，程式結束。")
            return None
    
    # 驗證檔案是否存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"找不到檔案: {input_file}")
    
    print(f"\n✓ 選擇的檔案: {os.path.basename(input_file)}")
    
    output_dir = os.path.dirname(input_file)
    base_name = os.path.basename(input_file)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.normpath(os.path.join(output_dir,f'Combat_corrected_{timestamp}.xlsx'))
    
    # 🔧 創建 Batch_Effect_plots 資料夾
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
            else:
                print(f"警告: column D ('{column_d}') 不像是 Batch 資訊，未進行更新")
        else:
            print("警告: SampleInfo 列數不足4，無法檢查 column D")
        
        if 'Batch' in sample_info.columns:
            unique_batches_info = sample_info['Batch'].unique()
            print(f"二次檢查後的 Batch 分組: {unique_batches_info}")
            if len(unique_batches_info) < 2:
                print("警告: 二次檢查後 Batch 分組不足2個，無法進行校正")
                raise Exception("Batch 分組不足2個")
        else:
            print("錯誤: 無法找到 Batch 列，無法進行二次檢查")
            raise Exception("無法找到 Batch 列")
        
        print("\n準備數據格式...")
        data_matrix, batch_info, sample_columns, feature_ids = prepare_data_for_combat(data, sample_info)
        print(f"✓ 找到 {len(sample_columns)} 個樣本，{len(feature_ids)} 個特徵")
        unique_batches = list(set(batch_info))
        print(f"✓ 批次信息: {unique_batches}")
        print(f"  批次數量: {len(unique_batches)}")
        
        if len(unique_batches) < 2:
            print("\n警告：只有一個批次，無需進行批次效應校正")
            raise Exception("只有一個批次")
        
        print("\n執行Combat批次效應校正...")
        corrected_data = perform_combat_correction(data_matrix, batch_info)
        print("✓ 批次效應校正完成")
        
        if corrected_data.shape[1] != len(sample_columns):
            print(f"轉置校正後的數據矩陣: 從 {corrected_data.shape} 到 {corrected_data.T.shape}")
            corrected_data = corrected_data.T
        
        # 🔧 計算 Silhouette Coefficient 並執行 Permutation Test
        print("\n計算 Silhouette Coefficient 並執行 Permutation Test...")
        original_data_for_eval = data_matrix.T
        corrected_data_for_eval = corrected_data.T
        
        # 設定 Permutation 次數
        n_permutations = 1000
        print(f"   Permutation Test 次數: {n_permutations}")
        
        silhouette_results = calculate_silhouette_improvement(
            original_data_for_eval, corrected_data_for_eval, batch_info, 
            n_permutations=n_permutations
        )
        
        # 🔧 生成 2 張前後對比 PCA 圖（左右並排）
        
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
        
        # 🔧 生成 Permutation Test 分佈圖
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
        
        print("\n準備輸出結果...")
        corrected_df = pd.DataFrame(corrected_data, columns=sample_columns)
        corrected_df.insert(0, data.columns[0], feature_ids)
        
        # 🔧 添加 Silhouette Coefficient 和 Permutation Test 結果
        corrected_df['Original_Silhouette'] = silhouette_results['feature_original']
        corrected_df['Corrected_Silhouette'] = silhouette_results['feature_corrected']
        corrected_df['Silhouette_Improvement'] = silhouette_results['feature_improvement']
        corrected_df['Permutation_pvalue'] = silhouette_results['feature_pvalues']
        
        print(f"\n保存結果到: {os.path.basename(output_file)}")
        copy_all_sheets(input_file, output_file, sheet_name, data, sample_info, corrected_df)
        
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
        
        # 輸出統計摘要
        print(f"\n📊 Silhouette Coefficient 統計摘要:")
        print(f"  - 整體校正前: {silhouette_results['overall_original']:.4f}")
        print(f"  - 整體校正後: {silhouette_results['overall_corrected']:.4f}")
        print(f"  - 整體改善: {silhouette_results['overall_improvement']:.4f}")
        
        if not np.isnan(silhouette_results['overall_pvalue']):
            print(f"\n🎲 Permutation Test 結果:")
            print(f"  - p-value: {silhouette_results['overall_pvalue']:.4f}")
            if silhouette_results['overall_pvalue'] < 0.001:
                print(f"  - 顯著性: *** (p < 0.001) - 批次效應校正極顯著有效")
            elif silhouette_results['overall_pvalue'] < 0.01:
                print(f"  - 顯著性: ** (p < 0.01) - 批次效應校正非常顯著")
            elif silhouette_results['overall_pvalue'] < 0.05:
                print(f"  - 顯著性: * (p < 0.05) - 批次效應校正顯著有效")
            else:
                print(f"  - 顯著性: n.s. (p >= 0.05) - 批次效應校正效果不顯著")
        
        valid_improvements = silhouette_results['feature_improvement'][~np.isnan(silhouette_results['feature_improvement'])]
        if len(valid_improvements) > 0:
            print(f"\n  特徵層級統計:")
            print(f"  - 平均改善: {np.mean(valid_improvements):.4f}")
            print(f"  - 中位數改善: {np.median(valid_improvements):.4f}")
            print(f"  - 改善特徵數: {np.sum(valid_improvements > 0)}/{len(valid_improvements)} ({np.sum(valid_improvements > 0)/len(valid_improvements)*100:.1f}%)")
            
            valid_pvalues = silhouette_results['feature_pvalues'][~np.isnan(silhouette_results['feature_pvalues'])]
            if len(valid_pvalues) > 0:
                print(f"  - 顯著改善特徵 (p<0.05): {np.sum(valid_pvalues < 0.05)}/{len(valid_pvalues)} ({np.sum(valid_pvalues < 0.05)/len(valid_pvalues)*100:.1f}%)")
        
        print("\n" + "="*70 + "\n")
        
        # 🎯 返回統計資訊給 GUI
        return {
            'file_path': input_file,
            'metabolites': len(feature_ids),
            'samples': len(sample_columns),
            'output_path': output_file
        }
        
    except Exception as e:
        print(f"\n錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        print("\n請檢查輸入檔案格式是否正確")
        raise  # 🔧 重新拋出異常，讓 GUI 可以捕獲


if __name__ == "__main__":
    # 🔧 獨立運行時不傳入 input_file，會顯示對話框
    main()

