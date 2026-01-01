import pandas as pd
import numpy as np
import os
import sys
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
from scipy.spatial.distance import mahalanobis
from scipy.stats import chi2, f as f_dist
import warnings
import tkinter as tk
from tkinter import filedialog
import copy

warnings.filterwarnings('ignore')

# ========== 匯入共用模組 ==========
from metabolomics.utils.data_helpers import get_valid_values
from metabolomics.utils.statistics import calculate_hotelling_t2_outliers, draw_hotelling_t2_ellipse
from metabolomics.utils.plotting import setup_matplotlib, plot_pca_comparison_qc_style
from metabolomics.utils.constants import FONT_SIZES, COLORBLIND_COLORS, SHEET_NAMES
from metabolomics.utils.sample_classification import SampleClassifier, identify_sample_columns

# 設定 matplotlib
setup_matplotlib()

def load_and_process_data(file_path):
    try:
        # ===== 防呆1: 文件存在性检查 =====
        if not os.path.exists(file_path):
            print(f"錯誤：找不到檔案 '{file_path}'")
            return None, None, None

        # ===== 防呆2: 文件格式检查 =====
        if not (file_path.endswith('.xlsx') or file_path.endswith('.xls')):
            print(f"錯誤：輸入檔案必須是Excel格式 (.xlsx 或 .xls)，但提供了 {file_path}")
            return None, None, None

        # ===== 防呆3: 文件大小检查 =====
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            print(f"錯誤：檔案大小為 0 bytes，可能是空檔案")
            return None, None, None
        elif file_size < 1024:  # 小于 1KB
            print(f"警告：檔案大小僅 {file_size} bytes，可能不是有效的 Excel 檔案")

        print(f"檔案大小: {file_size / 1024:.2f} KB")

        # ===== 防呆4: Excel 文件有效性检查 =====
        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as e:
            print(f"錯誤：無法讀取 Excel 檔案，可能已損壞或格式不正確")
            print(f"詳細錯誤: {e}")
            return None, None, None
        
        # 讀取所有工作表，儲存為字典 {sheet_name: df}
        all_sheets = {sheet: pd.read_excel(excel_file, sheet_name=sheet) for sheet in excel_file.sheet_names}
        print(f"讀取輸入檔案的所有工作表: {list(all_sheets.keys())}")
        
        # ===== 防呆5: 必要工作表检查 =====
        required_sheets = ['RawIntensity', 'SampleInfo']
        missing_sheets = [sheet for sheet in required_sheets if sheet not in all_sheets]
        if missing_sheets:
            print(f"錯誤：輸入檔案缺少必要的工作表: {', '.join(missing_sheets)}")
            print(f"找到的工作表: {', '.join(all_sheets.keys())}")
            return None, None, None

        # ===== 防呆6: SampleInfo 完整性检查 =====
        sample_info_df = all_sheets['SampleInfo']
        print(f"成功讀取 'SampleInfo' 工作表，包含 {len(sample_info_df)} 筆樣本資訊")

        if sample_info_df.empty:
            print(f"錯誤：'SampleInfo' 工作表為空")
            return None, None, None

        required_columns = ['Sample_Name', 'Sample_Type']
        missing_cols = [col for col in required_columns if col not in sample_info_df.columns]
        if missing_cols:
            print(f"錯誤：'SampleInfo' 缺少必要欄位: {', '.join(missing_cols)}")
            print(f"找到的欄位: {', '.join(sample_info_df.columns.tolist())}")
            return None, None, None

        # ===== 防呆7: 样本名称重复检查 =====
        duplicate_samples = sample_info_df[sample_info_df['Sample_Name'].duplicated()]
        if not duplicate_samples.empty:
            print(f"警告：'SampleInfo' 中發現重複的樣本名稱:")
            for idx, row in duplicate_samples.iterrows():
                print(f"  - {row['Sample_Name']}")
            print(f"  建議：請檢查樣本名稱是否正確")

        # ===== 防呆8: 样本类型检查 =====
        sample_types = sample_info_df['Sample_Type'].unique()
        print(f"樣本類型: {', '.join([str(t) for t in sample_types])}")

        qc_count = sample_info_df[sample_info_df['Sample_Type'].str.upper().str.contains('QC', na=False)].shape[0]
        if qc_count == 0:
            print(f"警告：未找到 QC 樣本（Sample_Type 中無 'QC' 字樣）")
            print(f"  部分統計分析可能無法執行")
        else:
            print(f"找到 {qc_count} 個 QC 樣本")
        
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

        # ===== 防呆9: RawIntensity 基本检查 =====
        if raw_df.empty:
            print(f"錯誤：'RawIntensity' 工作表為空")
            return None, None, None

        if 'FeatureID' not in raw_df.columns:
            print(f"錯誤：'RawIntensity' 缺少 'FeatureID' 欄位")
            print(f"找到的欄位: {', '.join(raw_df.columns.tolist())}")
            return None, None, None

        # ===== 防呆10: FeatureID 重复检查 =====
        duplicate_features = raw_df[raw_df['FeatureID'].duplicated(keep=False)]
        if not duplicate_features.empty:
            print(f"警告：'RawIntensity' 中發現重複的 FeatureID:")
            dup_ids = duplicate_features['FeatureID'].unique()
            for fid in dup_ids[:5]:  # 只显示前5个
                print(f"  - {fid}")
            if len(dup_ids) > 5:
                print(f"  ... 還有 {len(dup_ids) - 5} 個重複的 FeatureID")
            print(f"  建議：請檢查數據是否正確，腳本將保留第一次出現的記錄")

        # ===== 防呆11: 样本列检查 =====
        sample_columns = [col for col in raw_df.columns if col != 'FeatureID']
        if len(sample_columns) == 0:
            print(f"錯誤：'RawIntensity' 中沒有樣本欄位")
            return None, None, None

        print(f"找到 {len(sample_columns)} 個樣本欄位")

        # 修改：不要自動跳過 'sample_type'，改為檢查並保留
        if not raw_df.empty and str(raw_df.iloc[0]['FeatureID']).strip().lower() == 'sample_type':
            print("偵測到 'Sample_Type' 資訊行，已保留作為元數據。")

        # ===== 防呆12: 样本名称匹配检查 =====
        sample_names_in_info = set(sample_info_df['Sample_Name'].str.strip().str.lower())
        sample_names_in_raw = set([col.strip().lower() for col in sample_columns])

        missing_in_raw = sample_names_in_info - sample_names_in_raw
        missing_in_info = sample_names_in_raw - sample_names_in_info

        if missing_in_raw:
            print(f"警告：以下樣本在 SampleInfo 中有記錄，但在 RawIntensity 中找不到:")
            for name in list(missing_in_raw)[:5]:
                print(f"  - {name}")
            if len(missing_in_raw) > 5:
                print(f"  ... 還有 {len(missing_in_raw) - 5} 個樣本")

        if missing_in_info:
            print(f"警告：以下樣本在 RawIntensity 中有數據，但在 SampleInfo 中找不到:")
            for name in list(missing_in_info)[:5]:
                print(f"  - {name}")
            if len(missing_in_info) > 5:
                print(f"  ... 還有 {len(missing_in_info) - 5} 個樣本")

        # 防呆：強制轉換 RawIntensity 的樣本欄位為數值
        for col in sample_columns:
            raw_df[col] = pd.to_numeric(raw_df[col], errors='coerce')

        # ===== 防呆13: 全为 NaN 或 0 的列检查 =====
        for col in sample_columns:
            non_zero_count = (raw_df[col] > 0).sum()
            if non_zero_count == 0:
                print(f"警告：樣本 '{col}' 的所有數值都是 0 或 NaN")

        raw_df = raw_df.fillna(0)  # 填充 NaN 為 0
        print(f"RawIntensity 數據類型檢查：樣本欄位已轉換為數值型")

        # ===== 防呆16: 数值范围检查 =====
        negative_count = 0
        extreme_high_count = 0
        for col in sample_columns:
            negative_values = (raw_df[col] < 0).sum()
            if negative_values > 0:
                negative_count += negative_values
                print(f"⚠️ 警告：樣本 '{col}' 有 {negative_values} 個負值，已設為 0")
                raw_df[col] = raw_df[col].clip(lower=0)

            # 检查极端高值（可能是数据错误）
            max_val = raw_df[col].max()
            if max_val > 1e15:
                extreme_high_count += 1
                print(f"⚠️ 警告：樣本 '{col}' 有極端高值 ({max_val:.2e})，請檢查數據是否正確")

        if negative_count > 0:
            print(f"總計修正了 {negative_count} 個負值")

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

        # ===== 防呆14: ISTD 识别验证 =====
        print(f"\n{'='*70}")
        print(f"ISTD 識別結果:")
        print(f"{'='*70}")
        print(f"識別到 {len(istd_feature_ids)} 個ISTD（紅色標記的 FeatureID）")

        if len(istd_feature_ids) == 0:
            print(f"❌ 錯誤：未找到任何 ISTD（請在 RawIntensity 工作表的 FeatureID 欄位中，")
            print(f"   將內標物質的 FeatureID 標記為紅色字體）")
            return None, None, None
        elif len(istd_feature_ids) < 3:
            print(f"⚠️ 警告：ISTD 數量較少（{len(istd_feature_ids)} 個），建議至少使用 3 個以上的 ISTD")
            print(f"   以確保校正效果的穩定性")

        # 验证 ISTD 是否存在于 raw_df 中
        istd_in_df = raw_df[raw_df['is_ISTD']]
        if len(istd_in_df) != len(istd_feature_ids):
            print(f"⚠️ 警告：部分 ISTD 在 RawIntensity 中找不到對應的 FeatureID")
            print(f"   標記的 ISTD: {len(istd_feature_ids)} 個")
            print(f"   實際找到: {len(istd_in_df)} 個")

        # ===== 防呆15: ISTD 强度验证 =====
        print(f"\nISTD 強度驗證:")
        for idx, row in istd_in_df.iterrows():
            fid = row['FeatureID']
            values = get_valid_values(row, sample_columns)

            if len(values) == 0:
                print(f"❌ 錯誤：ISTD '{fid}' 的所有樣本強度都是 0 或 NaN")
                print(f"   無法進行校正，請檢查數據")
                return None, None, None
            elif len(values) < len(sample_columns) * 0.5:
                print(f"⚠️ 警告：ISTD '{fid}' 有效值比例較低 ({len(values)}/{len(sample_columns)})")

            # 计算 CV%
            if len(values) >= 2:
                mean_val = np.mean(values)
                std_val = np.std(values, ddof=1)
                cv_percent = (std_val / mean_val) * 100 if mean_val != 0 else np.nan

                if cv_percent > 30:
                    print(f"⚠️ 警告：ISTD '{fid}' 的 CV% 較高 ({cv_percent:.1f}%)，可能影響校正品質")

        print(f"ISTD 列表: {', '.join(istd_feature_ids[:5])}")
        if len(istd_feature_ids) > 5:
            print(f"           ... 還有 {len(istd_feature_ids) - 5} 個")
        print(f"{'='*70}\n")

        return raw_df, sample_info_df, all_sheets
    except Exception as e:
        print(f"載入數據時發生錯誤: {e}")
        return None, None, None

def identify_istd_signals(df):
    return df[df['is_ISTD']], df[~df['is_ISTD']]

def calculate_istd_cv(istd_signals, sample_columns):
    """
    Calculate CV% for each ISTD signal.

    Vectorized implementation - much faster than iterrows().
    """
    from metabolomics.utils.safe_math import safe_cv_percent_vectorized, extract_numeric_matrix

    # Extract numeric matrix for sample columns
    valid_cols = [c for c in sample_columns if c in istd_signals.columns]
    if not valid_cols:
        return {}

    # Get numeric data matrix
    numeric_data = istd_signals[valid_cols].apply(pd.to_numeric, errors='coerce').values

    # Calculate CV% for each row (vectorized)
    cv_values = safe_cv_percent_vectorized(numeric_data, axis=1, min_samples=2)

    # Build result dictionary
    return dict(zip(istd_signals['FeatureID'], cv_values))

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
    # ===== 防呆21: 权重参数验证 =====
    # 检查权重是否为负
    if rt_weight < 0 or cv_weight < 0 or intensity_weight < 0 or mz_weight < 0:
        raise ValueError(
            f"❌ 錯誤：權重不能為負值\n"
            f"   rt_weight={rt_weight}, cv_weight={cv_weight}, "
            f"intensity_weight={intensity_weight}, mz_weight={mz_weight}"
        )

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
    """
    Calculate median intensity for each ISTD signal.

    Vectorized implementation - much faster than iterrows().
    """
    # Extract numeric matrix for sample columns
    valid_cols = [c for c in sample_columns if c in istd_signals.columns]
    if not valid_cols:
        return {}

    # Get numeric data and calculate median per row
    numeric_data = istd_signals[valid_cols].apply(pd.to_numeric, errors='coerce').values

    # Replace non-positive values with NaN for proper median calculation
    numeric_data = np.where(numeric_data > 0, numeric_data, np.nan)

    # Calculate median for each row (ignoring NaN)
    medians = np.nanmedian(numeric_data, axis=1)

    # Build result dictionary
    return dict(zip(istd_signals['FeatureID'], medians))

def calculate_corrected_ratios(df, sample_info_df):
    """
    计算 ISTD 校正后的比值

    增强了多层防呆检查
    """
    # ===== 防呆19: 基本输入验证 =====
    if df is None or df.empty:
        print("❌ 錯誤：輸入數據為空")
        return None, None

    if sample_info_df is None or sample_info_df.empty:
        print("❌ 錯誤：樣本資訊為空")
        return None, None

    istd_signals, analyte_signals = identify_istd_signals(df)

    # ===== 防呆20: ISTD 信号检查 =====
    if len(istd_signals) == 0:
        print("❌ 錯誤：未找到 ISTD 信號")
        return None, None

    if len(analyte_signals) == 0:
        print("❌ 錯誤：未找到代謝物信號（所有 FeatureID 都被標記為 ISTD）")
        return None, None

    print(f"\n校正統計:")
    print(f"  - ISTD 數量: {len(istd_signals)}")
    print(f"  - 代謝物數量: {len(analyte_signals)}")

    if 'Sample_Name' not in sample_info_df.columns:
        print("❌ 錯誤：'SampleInfo' 缺少 'Sample_Name' 欄位")
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

    Performance optimized:
    - Uses indexed lookup instead of O(N) search per row (was O(N^2), now O(N))
    - Pre-extracts numeric matrices for QC columns
    """
    from metabolomics.utils.safe_math import safe_divide

    qc_samples = sample_info_df[sample_info_df['Sample_Type'].str.upper().str.contains('QC')]['Sample_Name'].tolist()
    qc_columns = [col for col in sample_columns if col in qc_samples]

    print(f"\n{'='*70}")
    print(f"🔬 開始統計檢定（Wilcoxon 配對符號等級檢定 + Levene's test）")
    print(f"{'='*70}")
    print(f"  - QC 樣本數: {len(qc_columns)}")
    print(f"  - Feature 總數: {len(results_df)}")

    # ===== PERFORMANCE OPTIMIZATION: Create indexed lookup for O(1) access =====
    # This replaces O(N) lookup per iteration with O(1) lookup
    original_indexed = original_df.set_index('FeatureID')

    # Pre-extract QC columns data for faster access
    valid_qc_cols = [c for c in qc_columns if c in results_df.columns and c in original_df.columns]

    cv_results = []
    total_features = len(results_df)

    for idx, row in results_df.iterrows():
        feature_id = row['FeatureID']

        # 校正後的 QC 值
        qc_values_corrected = get_valid_values(row, qc_columns)

        # 原始的 QC 值 - O(1) lookup instead of O(N)
        try:
            if feature_id in original_indexed.index:
                original_row = original_indexed.loc[feature_id]
                qc_values_original = get_valid_values(original_row, qc_columns)
            else:
                qc_values_original = []
        except KeyError:
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

        # 計算 CV% with safe division
        orig_mean = np.mean(qc_values_original)
        corr_mean = np.mean(qc_values_corrected)
        original_cv = safe_divide(np.std(qc_values_original, ddof=1), orig_mean, np.nan) * 100
        corrected_cv = safe_divide(np.std(qc_values_corrected, ddof=1), corr_mean, np.nan) * 100
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
        except Exception:
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

        if (idx + 1) % 500 == 0:
            print(f"  處理進度: {idx + 1}/{total_features} features")
    
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
    # ===== 防呆23: alpha 参数验证 =====
    if not (0 < alpha < 1):
        raise ValueError(f"❌ 錯誤：alpha 必須在 (0, 1) 範圍內，當前值: {alpha}")

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

def plot_pvalue_distribution(cv_results_df, plots_dir, timestamp):
    """繪製 p 值分佈圖（驗證統計檢定有效性）"""
    try:
        # ✅ 圖表儲存在指定目錄，必要時建立預設路徑
        if plots_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.join(script_dir, 'output', 'ISTD_Correction_plots')
            os.makedirs(base_dir, exist_ok=True)
            plots_dir = os.path.join(base_dir, f"ISTD_Correction_{timestamp}")

        os.makedirs(plots_dir, exist_ok=True)
        
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
        
        # ✅ 儲存到 output/ISTD_Correction_plots/
        pvalue_plot_path = os.path.join(plots_dir, f'Pvalue_Distribution_{timestamp}.png')
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

# ========== Hotelling T² 橢圓繪製函數 ==========
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
def perform_pca_analysis_2d(raw_df, corrected_df, lowess_df, sample_columns, sample_info_df, plots_dir):
    """
    執行 2D PCA 分析
    - 🔧 使用 Hotelling T² 檢測異常值
    - 使用 Hotelling T² 繪製橢圓（中心固定為原點）
    - 🎨 不同組別使用不同形狀：控制組=方形（無邊框）、暴露組=三角形（無邊框）、QC=圓形（黑邊框）
    """
    # ✅ 修正：圖表儲存在 output/ISTD_Correction_plots/ 下的指定子資料夾
    if plots_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.join(script_dir, "output", "ISTD_Correction_plots")
        os.makedirs(base_dir, exist_ok=True)
        plots_dir = os.path.join(base_dir, f"ISTD_Correction_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    if not os.path.exists(plots_dir):
        os.makedirs(plots_dir, exist_ok=True)
        print(f"已建立 'ISTD_Correction_plots' 資料夾: {plots_dir}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M')

    # 🔧 修正：樣本名稱用 strip+lower 做穩健匹配，避免因空白/大小寫差異導致 QC 誤判不足
    sample_info_norm = sample_info_df.copy()
    sample_info_norm['Sample_Name_norm'] = (
        sample_info_norm['Sample_Name'].astype(str).str.strip().str.lower()
    )
    sample_meta = sample_info_norm.set_index('Sample_Name_norm')

    # 識別 QC 樣本和樣本類型
    qc_columns = []
    control_columns = []
    exposed_columns = []
    sample_type_map = {}
    
    for col in sample_columns:
        col_norm = str(col).strip().lower()
        if col_norm in sample_meta.index:
            sample_type = sample_meta.loc[col_norm].get('Sample_Type', 'Unknown')
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

    # 🎨 顏色和形狀映射
    color_map = {}
    marker_map = {}
    
    for col in sample_columns:
        if col in qc_columns:
            color_map[col] = '#9370DB'  # 紫色
            marker_map[col] = 'o'        # 圓形
        elif col in exposed_columns:
            color_map[col] = '#DC143C'  # 紅色
            marker_map[col] = '^'        # 三角形
        else:  # control
            color_map[col] = '#4169E1'  # 藍色
            marker_map[col] = 's'        # 方形

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

        # 🔧 使用 Hotelling T² 檢測 QC 異常值
        qc_indices = [i for i, col in enumerate(sample_columns) if col in qc_columns]
        qc_scores_left = scores_left[qc_indices]
        qc_scores_right = scores_right[qc_indices]

        t2_left, t2_threshold_left, outliers_left = calculate_hotelling_t2_outliers(
            qc_scores_left, scores_left, alpha=0.05
        )
        t2_right, t2_threshold_right, outliers_right = calculate_hotelling_t2_outliers(
            qc_scores_right, scores_right, alpha=0.05
        )

        print(f"\n🔍 Hotelling T² 異常值檢測:")
        print(f"   {left_name}:")
        print(f"   - T² 閾值: {t2_threshold_left:.2f}")
        print(f"   - 異常值數量: {np.sum(outliers_left)}/{len(qc_columns)}")
        print(f"   {right_name}:")
        print(f"   - T² 閾值: {t2_threshold_right:.2f}")
        print(f"   - 異常值數量: {np.sum(outliers_right)}/{len(qc_columns)}")

        # 統一 PCA 圖樣式（以 QC 子程式風格為主）
        sample_types = []
        for col in sample_columns:
            if col in qc_columns:
                sample_types.append('QC')
            elif col in exposed_columns:
                sample_types.append('Exposure')
            else:
                sample_types.append('Control')

        qc_outliers_left = {qc_columns[i] for i in range(len(qc_columns)) if outliers_left[i]}
        qc_outliers_right = {qc_columns[i] for i in range(len(qc_columns)) if outliers_right[i]}

        output_path = os.path.join(plots_dir, f"2D_PCA_{left_name.replace(' ', '_')}_vs_{right_name.replace(' ', '_')}_{timestamp}.png")
        plot_pca_comparison_qc_style(
            scores_left,
            scores_right,
            var_left,
            var_right,
            sample_columns,
            sample_types,
            batch_labels=None,
            grouping='sample_type',
            suptitle=f'2D PCA Comparison: {left_name} vs {right_name}',
            left_title=left_name,
            right_title=right_name,
            left_threshold_text=f'Hotelling T² Threshold: {t2_threshold_left:.2f}',
            right_threshold_text=f'Hotelling T² Threshold: {t2_threshold_right:.2f}',
            qc_outlier_names_left=qc_outliers_left,
            qc_outlier_names_right=qc_outliers_right,
            output_path=output_path,
            dpi=300,
        )

        plt.close('all')
        print(f"✓ 2D PCA 圖已儲存: {output_path}")

        # ===== 輸出異常值摘要 =====
        print(f"\n{'='*70}")
        print(f"📊 {left_name} - Hotelling T² 異常值檢測結果")
        print(f"{'='*70}")
        print(f"QC 異常值數量: {np.sum(outliers_left)}/{len(outliers_left)}")
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
        print(f"QC 異常值數量: {np.sum(outliers_right)}/{len(outliers_right)}")
        if np.sum(outliers_right) > 0:
            outlier_samples = [qc_columns[i] for i in range(len(outliers_right)) if outliers_right[i]]
            outlier_t2_values = [t2_right[i] for i in range(len(outliers_right)) if outliers_right[i]]
            print(f"異常樣本:")
            for sample, t2_val in zip(outlier_samples, outlier_t2_values):
                print(f"  - {sample}: T² = {t2_val:.2f} (閾值 = {t2_threshold_right:.2f})")
        else:
            print("  ✓ 無異常樣本")
        print(f"{'='*70}\n")

def apply_fdr_correction(pvalues):
    """
    使用 Benjamini-Hochberg 方法進行 FDR 校正

    Args:
        pvalues: p 值的 array 或 Series

    Returns:
        qvalues: 校正後的 q 值（FDR-adjusted p-values）
    """
    # 移除 NaN 值
    pvalues_array = np.array(pvalues)
    valid_mask = ~np.isnan(pvalues_array)

    # 初始化 q-values 為 NaN
    qvalues = np.full_like(pvalues_array, np.nan, dtype=float)

    if np.sum(valid_mask) == 0:
        return qvalues

    # 提取有效的 p-values
    valid_pvalues = pvalues_array[valid_mask]
    n = len(valid_pvalues)

    # Benjamini-Hochberg 方法
    # 1. 對 p 值排序，記錄原始索引
    sorted_indices = np.argsort(valid_pvalues)
    sorted_pvalues = valid_pvalues[sorted_indices]

    # 2. 計算 q 值：q_i = p_i * n / rank_i
    ranks = np.arange(1, n + 1)
    sorted_qvalues = sorted_pvalues * n / ranks

    # 3. 確保單調性（從後往前取最小值）
    for i in range(n - 2, -1, -1):
        sorted_qvalues[i] = min(sorted_qvalues[i], sorted_qvalues[i + 1])

    # 4. q 值不能超過 1
    sorted_qvalues = np.minimum(sorted_qvalues, 1.0)

    # 5. 恢復原始順序
    unsorted_qvalues = np.empty_like(sorted_qvalues)
    unsorted_qvalues[sorted_indices] = sorted_qvalues

    # 6. 將結果填回包含 NaN 的陣列
    qvalues[valid_mask] = unsorted_qvalues

    return qvalues


# ========== 🔧 修改：save_results_to_excel==========
def save_results_to_excel(original_df, results_df, sample_info_df, output_file,
                          all_sheets, sample_columns, original_workbook, plots_dir=None):
    """
    儲存結果到 Excel，使用 Wilcoxon 配對符號等級檢定 + Levene's test
    """
    # ===== 防呆22: 结果数据验证 =====
    if results_df is None or results_df.empty:
        print("❌ 錯誤：校正結果為空，無法儲存")
        raise ValueError("校正結果為空")

    if len(results_df) == 0:
        print("❌ 錯誤：沒有成功校正的代謝物")
        raise ValueError("沒有成功校正的代謝物")

    print(f"\n準備儲存結果:")
    print(f"  - 校正成功的代謝物數量: {len(results_df)}")
    print(f"  - 樣本數量: {len(sample_columns)}")

    # 检查必要欄位
    required_columns = ['FeatureID', 'ISTD']
    missing_cols = [col for col in required_columns if col not in results_df.columns]
    if missing_cols:
        print(f"❌ 錯誤：結果缺少必要欄位: {', '.join(missing_cols)}")
        raise ValueError(f"結果缺少必要欄位: {missing_cols}")

    # ✅ 圖表輸出基底（可覆蓋為特定目錄）
    plot_output_dir = plots_dir or os.path.dirname(output_file)
    
    # ✅ 使用新的統計檢定函數
    cv_results_df = calculate_qc_cv_with_statistical_test(
        results_df, sample_columns, sample_info_df, original_df
    )
    
    # 合併結果
    results_with_cv = results_df.merge(cv_results_df, on='FeatureID', how='left')

    # 🆕 應用 FDR 校正（Benjamini-Hochberg 方法）
    print("\n📊 應用 FDR 校正（Benjamini-Hochberg 方法）...")

    # 對 Wilcoxon p-value 進行 FDR 校正
    if 'Wilcoxon_pvalue' in results_with_cv.columns:
        results_with_cv['Wilcoxon_qvalue'] = apply_fdr_correction(results_with_cv['Wilcoxon_pvalue'])
        wilcoxon_valid = results_with_cv['Wilcoxon_pvalue'].notna().sum()
        wilcoxon_sig_p = ((results_with_cv['Wilcoxon_pvalue'] < 0.05) &
                          (results_with_cv['Wilcoxon_pvalue'].notna())).sum()
        wilcoxon_sig_q = ((results_with_cv['Wilcoxon_qvalue'] < 0.05) &
                          (results_with_cv['Wilcoxon_qvalue'].notna())).sum()
        print(f"  Wilcoxon test:")
        print(f"    - 有效檢定數: {wilcoxon_valid}")
        print(f"    - p < 0.05: {wilcoxon_sig_p} ({wilcoxon_sig_p/wilcoxon_valid*100:.1f}%)")
        print(f"    - q < 0.05 (FDR 校正後): {wilcoxon_sig_q} ({wilcoxon_sig_q/wilcoxon_valid*100:.1f}%)")

    # 對 Variance Test p-value 進行 FDR 校正
    if 'Variance_Test_pvalue' in results_with_cv.columns:
        results_with_cv['Variance_Test_qvalue'] = apply_fdr_correction(results_with_cv['Variance_Test_pvalue'])
        variance_valid = results_with_cv['Variance_Test_pvalue'].notna().sum()
        variance_sig_p = ((results_with_cv['Variance_Test_pvalue'] < 0.05) &
                          (results_with_cv['Variance_Test_pvalue'].notna())).sum()
        variance_sig_q = ((results_with_cv['Variance_Test_qvalue'] < 0.05) &
                          (results_with_cv['Variance_Test_qvalue'].notna())).sum()
        print(f"  Levene's test:")
        print(f"    - 有效檢定數: {variance_valid}")
        print(f"    - p < 0.05: {variance_sig_p} ({variance_sig_p/variance_valid*100:.1f}%)")
        print(f"    - q < 0.05 (FDR 校正後): {variance_sig_q} ({variance_sig_q/variance_valid*100:.1f}%)")

    print("  ✓ FDR 校正完成\n")

    # ✅ 調整欄位順序（加入 q-value 欄位）
    cols_order = [
        'Original_QC_CV%', 'Corrected_QC_CV%', 'CV_Improvement%',
        'Wilcoxon_pvalue', 'Wilcoxon_qvalue',
        'Variance_Test_pvalue', 'Variance_Test_qvalue',
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
        
        # ✅ 統計檢定欄位塗淡藍色（包含 p-value 和 q-value）
        for col_name in ['Wilcoxon_pvalue', 'Wilcoxon_qvalue', 'Variance_Test_pvalue', 'Variance_Test_qvalue']:
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
    
    # P 值分佈圖 (disabled: provides limited diagnostic value)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    # plot_pvalue_distribution(cv_results_df, plot_output_dir, timestamp)

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
    
    # 🔧 建立 output 資料夾
    output_dir = os.path.join(script_dir, "output")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"已建立 'output' 資料夾: {output_dir}")
    
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
    
    # 🔧 修改：儲存結果到 output 資料夾
    run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = os.path.join(
        output_dir,
        f"ISTD_Results_{run_timestamp}.xlsx"
    )
    plots_root = os.path.join(output_dir, "ISTD_Correction_plots")
    os.makedirs(plots_root, exist_ok=True)
    plots_session_dir = os.path.join(plots_root, f"ISTD_Correction_{run_timestamp}")
    os.makedirs(plots_session_dir, exist_ok=True)

    # ===== 防呆17: 输出目录权限检查 =====
    try:
        # 测试写入权限
        test_file = os.path.join(output_dir, '.write_test')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
    except Exception as e:
        print(f"❌ 錯誤：無法寫入 output 目錄")
        print(f"   請檢查目錄權限: {output_dir}")
        print(f"   詳細錯誤: {e}")
        raise Exception(f"輸出目錄無寫入權限: {output_dir}")

    # ===== 防呆18: 输出文件检查 =====
    if os.path.exists(output_file):
        print(f"⚠️ 警告：輸出檔案已存在，將被覆蓋")
        print(f"   {output_file}")

    save_results_to_excel(
        original_df, results_df, sample_info_df,
        output_file, all_sheets, sample_columns, input_file,
        plots_dir=plots_session_dir
    )
    
    # ✅ 執行 2D PCA 分析（傳入 output_dir）
    print("\n" + "="*70)
    print("📊 開始 2D PCA 分析（Hotelling T² 異常值檢測 + 橢圓 + 固定原點）")
    print("="*70 + "\n")
    perform_pca_analysis_2d(
        original_df, results_df, None,
        sample_columns, sample_info_df, plots_session_dir
    )
    
    print("\n" + "="*70)
    print("✅ ISTD Correction 完成！")
    print("="*70)
    print("\n📁 輸出檔案:")
    print(f"  1. Excel 結果: output/{os.path.basename(output_file)}")
    print(f"  2. PCA 圖表: {plots_session_dir}")
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