import pandas as pd
import numpy as np
import os
from datetime import datetime
from openpyxl import load_workbook
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings('ignore')

# ========== 匯入共用模組 ==========
from metabolomics.utils.data_helpers import apply_feature_metadata_passthrough, get_valid_values
from metabolomics.utils.plotting import setup_matplotlib
from metabolomics.utils.constants import (
    SHEET_NAMES,
    DATETIME_FORMAT_FULL,
    FEATURE_ID_COLUMN,
    NON_SAMPLE_COLUMNS,
    STAT_COLUMN_KEYWORDS,
    CV_QUALITY_THRESHOLDS,
    is_non_sample_column,
)
from metabolomics.utils.sample_classification import (
    build_sample_info_mapping,
    identify_candidate_sample_columns,
    identify_sample_columns,
    normalize_sample_name,
    normalize_sample_type,
)
from metabolomics.utils.file_io import (
    build_output_path,
    build_plots_dir,
    get_output_root,
    resolve_session_dir,
)
from metabolomics.utils.data_validation import DataValidator, require_valid
from metabolomics.utils.excel_colors import cell_has_red_font
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome
from metabolomics.utils.console import safe_print as print
from metabolomics.utils.excel_format import (
    apply_cv_quality_fill,
    apply_header_fill,
    apply_improvement_fill,
    apply_number_format,
    apply_significance_fill,
    apply_status_fill,
)

import re as _re

# 設定 matplotlib
setup_matplotlib()


def simplify_column_name(name):
    """Remove redundant DNA/RNA_programN_ prefix from column names.

    Example: 'DNA_program1_TumorBC2257_DNA' → 'TumorBC2257_DNA'
    """
    return _re.sub(r'^(?:DNA|RNA)_program\d+_', '', str(name))

def load_and_process_data(file_path):
    try:
        validator = DataValidator()
        require_valid(
            validator.validate_file_path(file_path),
            context="Step 1 input file",
        )
        file_path = os.fspath(file_path)

        # ===== 防呆1: 文件存在性检查 =====
        if not os.path.exists(file_path):
            raise ValueError(f"錯誤：找不到檔案 '{file_path}'")

        # ===== 防呆2: 文件格式检查 =====
        if not (file_path.endswith('.xlsx') or file_path.endswith('.xls')):
            raise ValueError(f"錯誤：輸入檔案必須是Excel格式 (.xlsx 或 .xls)，但提供了 {file_path}")

        # ===== 防呆3: 文件大小检查 =====
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError("錯誤：檔案大小為 0 bytes，可能是空檔案")
        elif file_size < 1024:  # 小于 1KB
            print(f"警告：檔案大小僅 {file_size} bytes，可能不是有效的 Excel 檔案")


        # ===== 防呆4: Excel 文件有效性检查 =====
        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as e:
            raise ValueError(f"錯誤：無法讀取 Excel 檔案，可能已損壞或格式不正確。詳細錯誤: {e}") from e

        require_valid(
            validator.validate_required_sheets(
                excel_file.sheet_names,
                required_sheets=[SHEET_NAMES['raw_intensity'], SHEET_NAMES['sample_info']],
                context="Step 1 input workbook",
            ),
            context="Step 1 workbook sheets",
        )

        # 讀取所有工作表，儲存為字典 {sheet_name: df}
        all_sheets = {sheet: pd.read_excel(excel_file, sheet_name=sheet) for sheet in excel_file.sheet_names}

        # ===== 防呆5: 必要工作表检查 =====
        required_sheets = [SHEET_NAMES['raw_intensity'], SHEET_NAMES['sample_info']]
        missing_sheets = [sheet for sheet in required_sheets if sheet not in all_sheets]
        if missing_sheets:
            raise ValueError(f"錯誤：輸入檔案缺少必要的工作表: {', '.join(missing_sheets)}。找到的工作表: {', '.join(all_sheets.keys())}")

        # ===== 防呆6: SampleInfo 完整性检查 =====
        sample_info_df = all_sheets[SHEET_NAMES['sample_info']]
        print(f"成功讀取 '{SHEET_NAMES['sample_info']}' 工作表，包含 {len(sample_info_df)} 筆樣本資訊")

        if sample_info_df.empty:
            raise ValueError(f"錯誤：'{SHEET_NAMES['sample_info']}' 工作表為空")

        require_valid(
            validator.validate_sample_info(
                sample_info_df,
                require_qc=True,
                require_batch=True,
            ),
            context="Step 1 SampleInfo",
        )

        required_columns = ['Sample_Name', 'Sample_Type']
        missing_cols = [col for col in required_columns if col not in sample_info_df.columns]
        if missing_cols:
            raise ValueError(f"錯誤：'{SHEET_NAMES['sample_info']}' 缺少必要欄位: {', '.join(missing_cols)}。找到的欄位: {', '.join(sample_info_df.columns.tolist())}")

        # ===== 防呆7: 样本名称重复检查 =====
        duplicate_samples = sample_info_df[sample_info_df['Sample_Name'].duplicated()]
        if not duplicate_samples.empty:
            print(f"警告：'{SHEET_NAMES['sample_info']}' 中發現重複的樣本名稱:")
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

        workbook = load_workbook(file_path, read_only=True)
        worksheet = workbook[SHEET_NAMES['raw_intensity']]
        istd_feature_ids = []  # 收集紅色標記的特徵 ID
        for row in worksheet.iter_rows(min_row=2, max_col=1):  # 只讀第一欄
            cell = row[0]  # 第一欄特徵 ID（例如 Mz/RT）
            if cell_has_red_font(cell) and cell.value:
                istd_feature_ids.append(str(cell.value).strip())  # 轉 str 以匹配
        workbook.close()

        raw_df = all_sheets[SHEET_NAMES['raw_intensity']]

        # ===== 防呆9: RawIntensity 基本检查 =====
        if raw_df.empty:
            raise ValueError(f"錯誤：'{SHEET_NAMES['raw_intensity']}' 工作表為空")

        require_valid(
            validator.validate_raw_intensity(
                raw_df,
                sample_names=sample_info_df['Sample_Name'].tolist(),
                require_sample_match=True,
            ),
            context="Step 1 RawIntensity",
        )

        # 支援 'Mz/RT' 或 'FeatureID' 作為特徵ID欄位名稱
        if FEATURE_ID_COLUMN in raw_df.columns and FEATURE_ID_COLUMN != 'FeatureID':
            raw_df = raw_df.rename(columns={FEATURE_ID_COLUMN: 'FeatureID'})
        elif 'FeatureID' not in raw_df.columns:
            # 嘗試使用第一欄作為特徵ID
            first_col = raw_df.columns[0]
            print(f"⚠️ 未找到 '{FEATURE_ID_COLUMN}' 或 'FeatureID' 欄位，使用第一欄 '{first_col}' 作為特徵ID")
            raw_df = raw_df.rename(columns={first_col: 'FeatureID'})

        # ===== 防呆10: FeatureID 重复检查 =====
        duplicate_features = raw_df[raw_df['FeatureID'].duplicated(keep=False)]
        if not duplicate_features.empty:
            print(f"警告：'{SHEET_NAMES['raw_intensity']}' 中發現重複的 FeatureID:")
            dup_ids = duplicate_features['FeatureID'].unique()
            for fid in dup_ids[:5]:  # 只显示前5个
                print(f"  - {fid}")
            if len(dup_ids) > 5:
                print(f"  ... 還有 {len(dup_ids) - 5} 個重複的 FeatureID")
            print(f"  建議：請檢查數據是否正確，腳本將保留第一次出現的記錄")

        # ===== 防呆11: 样本列检查 =====
        sample_columns, _ = identify_sample_columns(raw_df, sample_info_df)
        sample_columns = [
            col for col in sample_columns
            if col in raw_df.columns and col not in {'is_ISTD', 'Sample_Type', 'sample_type'}
        ]
        if len(sample_columns) == 0:
            raise ValueError(f"錯誤：'{SHEET_NAMES['raw_intensity']}' 中沒有樣本欄位")

        print(f"找到 {len(sample_columns)} 個樣本欄位")

        # 修改：不要自動跳過 'sample_type'，改為檢查並保留
        if not raw_df.empty and str(raw_df.iloc[0]['FeatureID']).strip().lower() == 'sample_type':
            print("偵測到 'Sample_Type' 資訊行，已保留作為元數據。")

        # ===== 防呆12: 样本名称匹配检查（支援模糊匹配）=====
        import re
        from metabolomics.utils.sample_classification import normalize_sample_name

        def _extract_key_tokens(name):
            """從樣本名稱中提取關鍵字和編號用於模糊匹配。
            例如 'DNA_program1_TumorBC2257_DNA' 和 'Tumor tissue BC2257_DNA'
            都會提取出類似的 token 集合。"""
            s = str(name).strip()
            # 移除常見前綴 (保留原始大小寫做 camelCase 拆分)
            s = re.sub(r'^(?:DNA|RNA|dna|rna)_program\d+_', '', s)
            # camelCase 拆分：'TumorBC2257' → 'Tumor BC 2257'
            s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
            s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
            s = s.lower()
            # 用空白、底線、分隔符拆分
            parts = re.split(r'[\s_\-/]+', s)
            tokens = set()
            for part in parts:
                # 將合併字拆開：'bc2257' → 'bc', '2257'
                sub_tokens = re.findall(r'[a-z]+|[0-9]+', part)
                tokens.update(sub_tokens)
                # 也保留「字母+數字」的組合 token（如 bc2257）
                combo_tokens = re.findall(r'[a-z]+\d+', part)
                tokens.update(combo_tokens)
            # 過濾掉純通用詞
            generic = {'tissue', 'cancer', 'breast', 'pooled', 'fat',
                        'dna', 'rna', 'dnaandrna', 'program1', 'and'}
            return tokens - generic

        info_names_by_norm = {
            normalize_sample_name(name): str(name).strip()
            for name in sample_info_df['Sample_Name'].tolist()
            if normalize_sample_name(name)
        }
        raw_names_by_norm = {
            normalize_sample_name(col): str(col).strip()
            for col in sample_columns
            if normalize_sample_name(col)
        }

        aligned_count = len(set(info_names_by_norm) & set(raw_names_by_norm))
        if aligned_count > 0:
            print(f"✓ 樣本名稱正規化對齊成功：{aligned_count} 個樣本")

        missing_in_raw_norm = set(info_names_by_norm) - set(raw_names_by_norm)
        missing_in_info_norm = set(raw_names_by_norm) - set(info_names_by_norm)

        if missing_in_raw_norm:
            print(f"⚠️ 警告：以下 {len(missing_in_raw_norm)} 個樣本在 SampleInfo 中有記錄，但無法匹配到 RawIntensity:")
            for norm_name in list(missing_in_raw_norm)[:5]:
                print(f"  - {info_names_by_norm[norm_name]}")
            if len(missing_in_raw_norm) > 5:
                print(f"  ... 還有 {len(missing_in_raw_norm) - 5} 個樣本")

        if missing_in_info_norm:
            print(f"⚠️ 警告：以下 {len(missing_in_info_norm)} 個樣本在 RawIntensity 中有數據，但無法匹配到 SampleInfo:")
            for norm_name in list(missing_in_info_norm)[:5]:
                print(f"  - {raw_names_by_norm[norm_name]}")
            if len(missing_in_info_norm) > 5:
                print(f"  ... 還有 {len(missing_in_info_norm) - 5} 個樣本")

        # 防呆：強制轉換 RawIntensity 的樣本欄位為數值 (向量化)
        raw_df[sample_columns] = raw_df[sample_columns].apply(pd.to_numeric, errors='coerce')

        # ===== 防呆13: 全为 NaN 或 0 的列检查 (向量化) =====
        non_zero_counts = (raw_df[sample_columns] > 0).sum()
        zero_cols = non_zero_counts[non_zero_counts == 0].index.tolist()
        for col in zero_cols:
            print(f"警告：樣本 '{col}' 的所有數值都是 0 或 NaN")


        # ===== 防呆16: 数值范围检查 (向量化) =====
        # Check for negative values across all columns at once
        negative_mask = raw_df[sample_columns] < 0
        negative_counts_per_col = negative_mask.sum()
        negative_count = negative_counts_per_col.sum()

        for col in negative_counts_per_col[negative_counts_per_col > 0].index:
            print(f"⚠️ 警告：樣本 '{col}' 有 {negative_counts_per_col[col]} 個負值，已設為 0")

        if negative_count > 0:
            # Clip all columns at once (vectorized)
            raw_df[sample_columns] = raw_df[sample_columns].clip(lower=0)
            print(f"總計修正了 {negative_count} 個負值")

        # 检查极端高值（可能是数据错误）
        max_values = raw_df[sample_columns].max()
        extreme_cols = max_values[max_values > 1e15]
        for col, max_val in extreme_cols.items():
            print(f"⚠️ 警告：樣本 '{col}' 有極端高值 ({max_val:.2e})，請檢查數據是否正確")

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
        print(f"識別到 {len(istd_feature_ids)} 個 ISTD（紅色標記的特徵 ID）")

        if len(istd_feature_ids) == 0:
            print("⚠️ 未找到任何 ISTD；Step 1 將跳過，Step 2 直接使用 RawIntensity")
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
                raise ValueError(f"錯誤：ISTD '{fid}' 的所有樣本強度都是 0 或 NaN，無法進行校正，請檢查數據")
            elif len(values) < len(sample_columns) * 0.5:
                print(f"⚠️ 警告：ISTD '{fid}' 有效值比例較低 ({len(values)}/{len(sample_columns)})")

            # 计算 CV%
            if len(values) >= 2:
                mean_val = np.mean(values)
                std_val = np.std(values, ddof=1)
                cv_percent = (std_val / mean_val) * 100 if mean_val != 0 else np.nan

                if cv_percent > CV_QUALITY_THRESHOLDS['acceptable']:
                    print(f"⚠️ 警告：ISTD '{fid}' 的 CV% 較高 ({cv_percent:.1f}%)，可能影響校正品質")

        print(f"ISTD 列表: {', '.join(istd_feature_ids[:5])}")
        if len(istd_feature_ids) > 5:
            print(f"           ... 還有 {len(istd_feature_ids) - 5} 個")
        print(f"{'='*70}\n")

        # ===== 建立 col_to_info 映射 =====
        # 將 RawIntensity 欄位名 → SampleInfo 資訊行 (Sample_Type, Batch 等)
        col_to_info = {}
        info_rows = []
        for _, row in sample_info_df.iterrows():
            info_rows.append({
                'Sample_Name': str(row['Sample_Name']).strip(),
                'Sample_Type': str(row.get('Sample_Type', '')).strip(),
                'Batch': str(row.get('Batch', '')) if pd.notna(row.get('Batch')) else '',
                '_norm': normalize_sample_name(row['Sample_Name']),
                '_tokens': _extract_key_tokens(str(row['Sample_Name'])),
            })

        # Pass 1: exact normalized match
        unmatched_cols = []
        for col in sample_columns:
            col_norm = normalize_sample_name(col)
            matched = False
            for info in info_rows:
                if col_norm == info['_norm']:
                    col_to_info[col] = {
                        'Sample_Name': info['Sample_Name'],
                        'Sample_Type': info['Sample_Type'],
                        'Batch': info['Batch'],
                    }
                    matched = True
                    break
            if not matched:
                unmatched_cols.append(col)

        # Pass 2: fuzzy token match (overlap >= 2)
        still_unmatched = []
        available_infos = [info for info in info_rows
                           if info['Sample_Name'] not in {v['Sample_Name'] for v in col_to_info.values()}]
        for col in unmatched_cols:
            col_tokens = _extract_key_tokens(col)
            best_match = None
            best_overlap = 0
            for info in available_infos:
                overlap = len(col_tokens & info['_tokens'])
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = info
            if best_overlap >= 2 and best_match is not None:
                col_to_info[col] = {
                    'Sample_Name': best_match['Sample_Name'],
                    'Sample_Type': best_match['Sample_Type'],
                    'Batch': best_match['Batch'],
                }
                available_infos.remove(best_match)
            else:
                still_unmatched.append(col)

        # Pass 3: keyword fallback from column name
        for col in still_unmatched:
            col_upper = col.upper()
            if 'QC' in col_upper or 'POOLED' in col_upper:
                col_to_info[col] = {'Sample_Name': col, 'Sample_Type': 'QC', 'Batch': ''}
            elif any(k in col_upper for k in ('CONTROL', 'CTL', 'CON', 'BENIGN')):
                col_to_info[col] = {'Sample_Name': col, 'Sample_Type': 'Control', 'Batch': ''}
            elif any(k in col_upper for k in ('EXPOSED', 'EXP', 'TREAT', 'TUMOR')):
                col_to_info[col] = {'Sample_Name': col, 'Sample_Type': 'Exposure', 'Batch': ''}
            elif any(k in col_upper for k in ('NORMAL', 'NOR')):
                col_to_info[col] = {'Sample_Name': col, 'Sample_Type': 'Normal', 'Batch': ''}
            else:
                col_to_info[col] = {'Sample_Name': col, 'Sample_Type': 'Unknown', 'Batch': ''}

        matched_count = len(sample_columns) - len(still_unmatched)
        print(f"✓ col_to_info 映射建立完成：{matched_count}/{len(sample_columns)} 個欄位成功匹配到 SampleInfo")

        return raw_df, sample_info_df, all_sheets, col_to_info
    except Exception:
        raise

def identify_istd_signals(df):
    return df[df['is_ISTD']], df[~df['is_ISTD']]

def calculate_istd_cv(istd_signals, sample_columns):
    """
    Calculate CV% for each ISTD signal.

    Vectorized implementation - much faster than iterrows().
    """
    from metabolomics.utils.safe_math import safe_cv_percent_vectorized

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

def get_qc_sample_columns(raw_df, col_to_info, sample_info_df=None):
    """Return sample columns and the QC subset for the Step 1 gate."""
    if sample_info_df is not None:
        sample_columns, _ = identify_sample_columns(raw_df, sample_info_df)
        sample_columns = [
            col for col in sample_columns
            if col in raw_df.columns and col not in {'is_ISTD', 'Sample_Type', 'sample_type'}
        ]
    else:
        non_sample_lower = {normalize_sample_name(col) for col in NON_SAMPLE_COLUMNS}
        sample_columns = []
        for col in raw_df.columns:
            col_norm = normalize_sample_name(col)
            if is_non_sample_column(col) or col_norm in non_sample_lower:
                continue
            if any(keyword in col_norm for keyword in STAT_COLUMN_KEYWORDS):
                continue
            if col in col_to_info:
                sample_columns.append(col)
    qc_columns = []

    for col in sample_columns:
        sample_type = normalize_sample_type(col_to_info.get(col, {}).get('Sample_Type', ''))
        if sample_type == 'QC' or 'QC' in str(col).upper() or 'POOLED' in str(col).upper():
            qc_columns.append(col)

    return sample_columns, qc_columns


def evaluate_istd_gate(raw_df, col_to_info, sample_info_df=None):
    """Evaluate whether there are enough good ISTDs to run Step 1."""
    sample_columns, qc_columns = get_qc_sample_columns(raw_df, col_to_info, sample_info_df=sample_info_df)
    istd_signals, _ = identify_istd_signals(raw_df)
    istd_qc_cv = calculate_istd_cv(istd_signals, qc_columns)
    good_istd_ids = [
        feature_id
        for feature_id, cv in istd_qc_cv.items()
        if pd.notna(cv) and cv < CV_QUALITY_THRESHOLDS['excellent']
    ]

    return {
        'sample_columns': sample_columns,
        'qc_columns': qc_columns,
        'istd_qc_cv': istd_qc_cv,
        'good_istd_ids': good_istd_ids,
        'total_istd': len(istd_qc_cv),
        'good_istd_count': len(good_istd_ids),
        'should_skip': len(good_istd_ids) < 5,
    }


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

    # ========== 步驟 1: 收集所有 ISTD 的指標 (向量化優化) ==========
    # Pre-calculate median intensities for all ISTDs (vectorized)
    valid_sample_cols = [c for c in sample_columns if c in istd_signals.columns]
    if valid_sample_cols:
        # Extract numeric matrix and calculate medians vectorized
        numeric_data = istd_signals[valid_sample_cols].apply(pd.to_numeric, errors='coerce')
        numeric_data = numeric_data.where(numeric_data > 0, np.nan)  # Replace <=0 with NaN
        median_intensities = numeric_data.median(axis=1).values
    else:
        median_intensities = np.zeros(len(istd_signals))

    # Pre-calculate RT and mz differences (vectorized)
    istd_rts = istd_signals['rt'].values
    istd_mzs = istd_signals['mz'].values
    rt_diffs_all = np.abs(analyte_rt - istd_rts)
    mz_diffs_all = np.abs(analyte_mz - istd_mzs) / analyte_mz * 1e6

    candidates = []

    for idx, istd_row in enumerate(istd_signals.itertuples()):
        istd_id = istd_row.FeatureID
        istd_rt = istd_rts[idx]
        istd_mz = istd_mzs[idx]

        # 跳過缺少資訊的 ISTD
        if np.isnan(istd_rt) or np.isnan(istd_mz):
            continue

        # 獲取預先計算的值
        rt_diff = rt_diffs_all[idx]
        mz_diff_ppm = mz_diffs_all[idx]
        median_intensity = median_intensities[idx]

        # 獲取 CV%
        cv = istd_cv.get(istd_id, np.nan)
        if np.isnan(cv):
            cv = 100.0  # 如果沒有 CV%，設為高值

        # 儲存候選資訊 (convert namedtuple row back to Series for compatibility)
        istd_row_series = istd_signals.iloc[idx]
        candidates.append({
            'istd_row': istd_row_series,
            'istd_id': istd_id,
            'rt_diff': rt_diff,
            'cv': cv,
            'intensity': median_intensity if not np.isnan(median_intensity) else 0.0,
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
        raise ValueError("錯誤：輸入數據為空")

    if sample_info_df is None or sample_info_df.empty:
        raise ValueError("錯誤：樣本資訊為空")

    istd_signals, analyte_signals = identify_istd_signals(df)

    # ===== 防呆20: ISTD 信号检查 =====
    if len(istd_signals) == 0:
        raise ValueError("錯誤：未找到 ISTD 信號")

    if len(analyte_signals) == 0:
        raise ValueError("錯誤：未找到代謝物信號（所有 FeatureID 都被標記為 ISTD）")

    print(f"\n校正統計:")
    print(f"  - ISTD 數量: {len(istd_signals)}")
    print(f"  - 代謝物數量: {len(analyte_signals)}")

    if 'Sample_Name' not in sample_info_df.columns:
        raise ValueError(f"錯誤：'{SHEET_NAMES['sample_info']}' 缺少 'Sample_Name' 欄位")

    candidate_columns, dropped_columns = identify_candidate_sample_columns(
        df,
        extra_non_sample_columns={'is_ISTD', 'Sample_Type', 'sample_type'},
    )
    col_to_info_row = build_sample_info_mapping(candidate_columns, sample_info_df)
    sample_columns = [col for col in candidate_columns if col in col_to_info_row]

    if dropped_columns:
        print(f"⚠️ 已排除 {len(dropped_columns)} 個推定統計欄位，不納入 ISTD 校正：")
        for col in dropped_columns[:5]:
            print(f"  - {col}")
        if len(dropped_columns) > 5:
            print(f"  ... 還有 {len(dropped_columns) - 5} 個欄位")

    if not sample_columns:
        raise ValueError(
            "未找到可與 SampleInfo 對齊的有效樣本欄位，"
            "已停止 ISTD 校正以避免將未知資料欄位當成樣本。"
        )

    unmatched_columns = [col for col in candidate_columns if col not in col_to_info_row]
    if unmatched_columns:
        preview = ", ".join(unmatched_columns[:5])
        if len(unmatched_columns) > 5:
            preview += f" ... 還有 {len(unmatched_columns) - 5} 個"
        raise ValueError(
            "以下資料欄位無法可靠對齊到 SampleInfo，已停止 ISTD 校正以避免錯誤樣本語義流入下游: "
            f"{preview}"
        )

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

    # 防呆：強制轉換 results_df 的樣本欄位為數值 (向量化)
    valid_sample_cols = [col for col in sample_columns if col in results_df.columns]
    if valid_sample_cols:
        results_df[valid_sample_cols] = results_df[valid_sample_cols].apply(pd.to_numeric, errors='coerce')

    return results_df, sample_columns



from scipy.stats import wilcoxon, levene

def calculate_qc_cv_with_statistical_test(results_df, sample_columns, sample_info_df, original_df,
                                           col_to_info=None):
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
    from metabolomics.utils.sample_classification import normalize_sample_type

    # Use col_to_info for QC identification (primary), fallback to direct name match
    if col_to_info:
        qc_columns = [col for col in sample_columns
                       if normalize_sample_type(col_to_info.get(col, {}).get('Sample_Type', '')) == 'QC']
    else:
        qc_samples = sample_info_df[sample_info_df['Sample_Type'].str.upper().str.contains('QC')]['Sample_Name'].tolist()
        qc_columns = [col for col in sample_columns if col in qc_samples]
        # Keyword fallback if no match
        if not qc_columns:
            qc_columns = [col for col in sample_columns
                          if 'QC' in col.upper() or 'POOLED' in col.upper()]

    print(f"\n{'='*70}")
    print(f"🔬 開始統計檢定（Wilcoxon 配對符號等級檢定 + Levene's test）")
    print(f"{'='*70}")
    print(f"  - QC 樣本數: {len(qc_columns)}")
    print(f"  - Feature 總數: {len(results_df)}")

    # ===== PERFORMANCE OPTIMIZATION: Pre-extract all QC data vectorized =====
    # This replaces O(N*M) row-by-row extraction with O(N+M) vectorized operations
    original_indexed = original_df.set_index('FeatureID')

    # Pre-extract QC columns data for faster access
    valid_qc_cols = [c for c in qc_columns if c in results_df.columns and c in original_df.columns]

    # ===== VECTORIZED: Extract all QC data at once =====
    # Convert to numeric and replace <=0 with NaN (vectorized)
    qc_corrected_data = results_df[valid_qc_cols].apply(pd.to_numeric, errors='coerce')
    qc_corrected_data = qc_corrected_data.where(qc_corrected_data > 0, np.nan)

    qc_original_data = original_indexed[valid_qc_cols].apply(pd.to_numeric, errors='coerce')
    qc_original_data = qc_original_data.where(qc_original_data > 0, np.nan)

    cv_results = []
    total_features = len(results_df)

    # Use itertuples for faster iteration (2-3x faster than iterrows)
    for row_idx, row_tuple in enumerate(results_df.itertuples()):
        idx = row_tuple.Index
        feature_id = row_tuple.FeatureID

        # Extract QC values from pre-processed data (vectorized access)
        try:
            qc_values_corrected = qc_corrected_data.loc[idx].dropna().values
        except KeyError:
            qc_values_corrected = np.array([])

        try:
            if feature_id in qc_original_data.index:
                qc_values_original = qc_original_data.loc[feature_id].dropna().values
            else:
                qc_values_original = np.array([])
        except KeyError:
            qc_values_original = np.array([])

        # 確保配對樣本數一致
        min_len = min(len(qc_values_original), len(qc_values_corrected))

        if min_len < 3:
            cv_results.append({
                'FeatureID': feature_id,
                'Original_QC_CV%': np.nan,
                'Corrected_QC_CV%': np.nan,
                'CV_Improvement%': np.nan,
                'Original_Robust_CV%': np.nan,
                'Corrected_Robust_CV%': np.nan,
                'Robust_CV_Improvement%': np.nan,
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

        # Robust CV (MAD/median) — 不受極端值影響，適用於非常態質譜數據
        orig_median = np.nanmedian(qc_values_original)
        corr_median = np.nanmedian(qc_values_corrected)
        orig_mad = np.nanmedian(np.abs(qc_values_original - orig_median))
        corr_mad = np.nanmedian(np.abs(qc_values_corrected - corr_median))
        original_robust_cv = safe_divide(orig_mad, orig_median, np.nan) * 100
        corrected_robust_cv = safe_divide(corr_mad, corr_median, np.nan) * 100
        robust_cv_improvement = original_robust_cv - corrected_robust_cv

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
            'Original_Robust_CV%': original_robust_cv,
            'Corrected_Robust_CV%': corrected_robust_cv,
            'Robust_CV_Improvement%': robust_cv_improvement,
            'Wilcoxon_pvalue': wilcoxon_pvalue,
            'Variance_Test_pvalue': variance_test_pvalue,
            'Significant_Improvement': significant
        })

        if (row_idx + 1) % 500 == 0:
            print(f"  處理進度: {row_idx + 1}/{total_features} features")

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
        pvalue_plot_path = os.path.join(plots_dir, f'Step1_Pvalue_Distribution_{timestamp}.png')
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

def build_step1_plot_sample_metadata(sample_columns, sample_info_df, col_to_info=None):
    """Align Step 1 sample columns to sample metadata and injection order."""
    info_df = sample_info_df.copy()
    if 'Sample_Name' in info_df.columns:
        info_df['_norm_name'] = info_df['Sample_Name'].map(normalize_sample_name)
        info_df = info_df[info_df['_norm_name'].astype(bool)]
        info_df = info_df.drop_duplicates('_norm_name').set_index('_norm_name')
    else:
        info_df = pd.DataFrame()

    records = []
    for position, sample_column in enumerate(sample_columns, start=1):
        mapped_name = sample_column
        mapped_type = 'Unknown'
        mapped_batch = ''
        if col_to_info and sample_column in col_to_info:
            mapped_name = col_to_info[sample_column].get('Sample_Name', sample_column)
            mapped_type = col_to_info[sample_column].get('Sample_Type', mapped_type)
            mapped_batch = col_to_info[sample_column].get('Batch', mapped_batch)

        meta_row = None
        for candidate in (mapped_name, sample_column):
            norm = normalize_sample_name(candidate)
            if not norm or info_df.empty or norm not in info_df.index:
                continue
            meta_row = info_df.loc[norm]
            break

        if meta_row is not None:
            mapped_type = meta_row.get('Sample_Type', mapped_type)
            mapped_batch = meta_row.get('Batch', mapped_batch)
            injection_order = pd.to_numeric(meta_row.get('Injection_Order', np.nan), errors='coerce')
        else:
            injection_order = np.nan

        records.append(
            {
                'sample_column': sample_column,
                'sample_name': mapped_name,
                'sample_type': normalize_sample_type(mapped_type),
                'batch': mapped_batch,
                'injection_order': injection_order,
                'fallback_order': position,
            }
        )

    sample_meta = pd.DataFrame(records)
    if sample_meta.empty:
        return sample_meta

    sample_meta['injection_order'] = pd.to_numeric(sample_meta['injection_order'], errors='coerce')
    max_existing = sample_meta['injection_order'].dropna().max()
    if pd.isna(max_existing):
        max_existing = 0

    missing_mask = sample_meta['injection_order'].isna()
    if missing_mask.any():
        filler = np.arange(1, missing_mask.sum() + 1, dtype=float) + float(max_existing)
        sample_meta.loc[missing_mask, 'injection_order'] = filler

    return sample_meta.sort_values(['injection_order', 'fallback_order']).reset_index(drop=True)


def plot_istd_stability_tracking(
    original_df,
    sample_columns,
    sample_info_df,
    plots_dir,
    timestamp,
    col_to_info=None,
    max_istds=6,
):
    """Plot representative ISTD intensity traces against injection order."""
    if 'is_ISTD' not in original_df.columns:
        return None

    sample_meta = build_step1_plot_sample_metadata(sample_columns, sample_info_df, col_to_info=col_to_info)
    if sample_meta.empty:
        return None

    ordered_sample_columns = [col for col in sample_meta['sample_column'] if col in original_df.columns]
    if len(ordered_sample_columns) < 2:
        return None

    istd_df = original_df[original_df['is_ISTD'] == True].copy()
    if istd_df.empty:
        return None

    qc_columns = [
        row.sample_column
        for row in sample_meta.itertuples()
        if row.sample_type == 'QC' and row.sample_column in original_df.columns
    ]
    ranking_columns = qc_columns if len(qc_columns) >= 2 else ordered_sample_columns
    istd_cv = calculate_istd_cv(istd_df, ranking_columns)
    ranked_feature_ids = sorted(
        istd_df['FeatureID'].tolist(),
        key=lambda feature_id: (np.inf if pd.isna(istd_cv.get(feature_id)) else istd_cv.get(feature_id), str(feature_id)),
    )[:max_istds]
    ranked_df = (
        istd_df.set_index('FeatureID')
        .loc[[feature_id for feature_id in ranked_feature_ids if feature_id in set(istd_df['FeatureID'])]]
        .reset_index()
    )
    if ranked_df.empty:
        return None

    n_panels = len(ranked_df)
    ncols = 2 if n_panels > 1 else 1
    nrows = int(np.ceil(n_panels / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, max(4.5, nrows * 3.6)), squeeze=False)

    type_colors = {
        'QC': '#d55e00',
        'Control': '#0072b2',
        'Exposure': '#009e73',
        'Normal': '#cc79a7',
        'Unknown': '#666666',
    }
    orders = sample_meta['injection_order'].to_numpy(dtype=float)
    sample_types = sample_meta['sample_type'].tolist()

    for ax, row in zip(axes.flatten(), ranked_df.itertuples()):
        values = pd.to_numeric(pd.Series([getattr(row, col, np.nan) for col in ordered_sample_columns]), errors='coerce').to_numpy(dtype=float)
        valid_mask = np.isfinite(values) & (values > 0)
        if valid_mask.sum() < 2:
            ax.text(0.5, 0.5, 'Insufficient positive data', ha='center', va='center', transform=ax.transAxes)
            ax.set_axis_off()
            continue

        valid_values = values[valid_mask]
        median_value = np.nanmedian(valid_values)
        normalized_values = valid_values / median_value if np.isfinite(median_value) and median_value > 0 else valid_values
        valid_orders = orders[valid_mask]
        valid_types = [sample_types[i] for i, is_valid in enumerate(valid_mask) if is_valid]

        ax.plot(valid_orders, normalized_values, color='#4c4c4c', linewidth=1.6, alpha=0.8, zorder=1)
        for sample_type in dict.fromkeys(valid_types):
            mask = np.array([current_type == sample_type for current_type in valid_types], dtype=bool)
            ax.scatter(
                valid_orders[mask],
                normalized_values[mask],
                s=32,
                color=type_colors.get(sample_type, '#666666'),
                alpha=0.85,
                label=sample_type,
                zorder=2,
            )

        cv_value = istd_cv.get(row.FeatureID)
        cv_text = f" | QC CV={cv_value:.1f}%" if pd.notna(cv_value) else ""
        ax.axhline(1.0, color='#999999', linestyle='--', linewidth=1)
        ax.set_title(f"{row.FeatureID}{cv_text}", fontsize=11, fontweight='bold')
        ax.set_xlabel('Injection Order', fontsize=10)
        ax.set_ylabel('Relative Intensity', fontsize=10)
        ax.grid(True, alpha=0.25)

    for ax in axes.flatten()[n_panels:]:
        ax.set_axis_off()

    handles = []
    labels = []
    for ax in axes.flatten()[:n_panels]:
        current_handles, current_labels = ax.get_legend_handles_labels()
        for handle, label in zip(current_handles, current_labels):
            if label not in labels:
                handles.append(handle)
                labels.append(label)

    fig.suptitle('ISTD Stability Tracking', fontsize=16, fontweight='bold', y=0.98)
    if handles:
        fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.92), ncol=min(4, len(labels)), frameon=True)
        plt.tight_layout(rect=[0, 0, 1, 0.9])
    else:
        plt.tight_layout(rect=[0, 0, 1, 0.95])

    output_path = os.path.join(plots_dir, f'Step1_ISTD_Tracking_{timestamp}.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    return output_path


def plot_cv_comparison(cv_results_df, plots_dir, timestamp):
    """Compare QC CV% before and after Step 1 correction."""
    original_cv = pd.to_numeric(cv_results_df.get('Original_QC_CV%'), errors='coerce')
    corrected_cv = pd.to_numeric(cv_results_df.get('Corrected_QC_CV%'), errors='coerce')
    valid_mask = np.isfinite(original_cv) & np.isfinite(corrected_cv)
    if valid_mask.sum() < 3:
        return None

    original_values = original_cv[valid_mask].to_numpy(dtype=float)
    corrected_values = corrected_cv[valid_mask].to_numpy(dtype=float)
    improved_mask = corrected_values < original_values

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    ax1.boxplot(
        [original_values, corrected_values],
        patch_artist=True,
        boxprops=dict(facecolor='#c9d6df', alpha=0.85),
        medianprops=dict(color='#222222', linewidth=2),
    )
    ax1.set_xticks([1, 2])
    ax1.set_xticklabels(['Before', 'After'])
    for idx, values in enumerate((original_values, corrected_values), start=1):
        jitter = np.random.uniform(-0.08, 0.08, size=len(values))
        ax1.scatter(np.full(len(values), idx) + jitter, values, color='#4c4c4c', alpha=0.35, s=16)
    ax1.set_ylabel('QC CV%', fontsize=11, fontweight='bold')
    ax1.set_title('Distribution Shift', fontsize=13, fontweight='bold')
    ax1.grid(True, axis='y', alpha=0.25)

    max_value = max(np.nanmax(original_values), np.nanmax(corrected_values))
    ax2.scatter(
        original_values[~improved_mask],
        corrected_values[~improved_mask],
        color='#c44e52',
        alpha=0.6,
        s=28,
        label='Worse / unchanged',
    )
    ax2.scatter(
        original_values[improved_mask],
        corrected_values[improved_mask],
        color='#55a868',
        alpha=0.65,
        s=28,
        label='Improved',
    )
    ax2.plot([0, max_value], [0, max_value], linestyle='--', color='#666666', linewidth=1.5, label='y = x')
    ax2.set_xlabel('Before QC CV%', fontsize=11, fontweight='bold')
    ax2.set_ylabel('After QC CV%', fontsize=11, fontweight='bold')
    ax2.set_title('Feature-wise Comparison', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.25)
    ax2.legend(fontsize=9)

    improved_count = int(improved_mask.sum())
    total_count = int(valid_mask.sum())
    fig.suptitle(
        f'QC CV Comparison ({improved_count}/{total_count} features improved)',
        fontsize=16,
        fontweight='bold',
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    output_path = os.path.join(plots_dir, f'Step1_CV_Comparison_{timestamp}.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    return output_path


def plot_density_overlay(original_df, results_df, sample_columns, plots_dir, timestamp):
    """Overlay intensity density before and after Step 1 correction."""
    original_source = original_df.copy()
    if 'is_ISTD' in original_source.columns:
        original_source = original_source[original_source['is_ISTD'] == False]

    original_columns = [col for col in sample_columns if col in original_source.columns]
    corrected_columns = [col for col in sample_columns if col in results_df.columns]
    if not original_columns or not corrected_columns:
        return None

    original_values = pd.to_numeric(original_source[original_columns].stack(), errors='coerce')
    corrected_values = pd.to_numeric(results_df[corrected_columns].stack(), errors='coerce')
    original_values = original_values[np.isfinite(original_values) & (original_values > 0)].to_numpy(dtype=float)
    corrected_values = corrected_values[np.isfinite(corrected_values) & (corrected_values > 0)].to_numpy(dtype=float)
    if len(original_values) < 10 or len(corrected_values) < 10:
        return None

    log_original = np.log10(original_values)
    log_corrected = np.log10(corrected_values)
    x_grid = np.linspace(
        min(np.min(log_original), np.min(log_corrected)),
        max(np.max(log_original), np.max(log_corrected)),
        256,
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        from scipy.stats import gaussian_kde

        if len(np.unique(log_original)) > 1:
            kde_original = gaussian_kde(log_original)
            ax.plot(x_grid, kde_original(x_grid), color='#4c72b0', linewidth=2.2, label='Before')
            ax.fill_between(x_grid, kde_original(x_grid), color='#4c72b0', alpha=0.18)
        if len(np.unique(log_corrected)) > 1:
            kde_corrected = gaussian_kde(log_corrected)
            ax.plot(x_grid, kde_corrected(x_grid), color='#dd8452', linewidth=2.2, label='After')
            ax.fill_between(x_grid, kde_corrected(x_grid), color='#dd8452', alpha=0.18)
    except Exception:
        ax.hist(log_original, bins=40, density=True, histtype='step', linewidth=2, color='#4c72b0', label='Before')
        ax.hist(log_corrected, bins=40, density=True, histtype='step', linewidth=2, color='#dd8452', label='After')

    ax.axvline(np.median(log_original), color='#4c72b0', linestyle='--', linewidth=1.5)
    ax.axvline(np.median(log_corrected), color='#dd8452', linestyle='--', linewidth=1.5)
    ax.set_xlabel('log10(Intensity)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Density', fontsize=11, fontweight='bold')
    ax.set_title('Intensity Density Overlay', fontsize=15, fontweight='bold')
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=10)
    plt.tight_layout()

    output_path = os.path.join(plots_dir, f'Step1_Density_Overlay_{timestamp}.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    return output_path


def generate_step1_diagnostic_plots(
    original_df,
    results_df,
    sample_columns,
    sample_info_df,
    cv_results_df,
    plots_dir,
    timestamp,
    col_to_info=None,
):
    """Generate the Step 1 diagnostic figure set."""
    os.makedirs(plots_dir, exist_ok=True)
    plot_pvalue_distribution(cv_results_df, plots_dir, timestamp)
    plot_istd_stability_tracking(
        original_df,
        sample_columns,
        sample_info_df,
        plots_dir,
        timestamp,
        col_to_info=col_to_info,
    )
    plot_cv_comparison(cv_results_df, plots_dir, timestamp)
    plot_density_overlay(original_df, results_df, sample_columns, plots_dir, timestamp)
    return str(plots_dir)


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
                          all_sheets, sample_columns, original_workbook, plots_dir=None,
                          col_to_info=None, cv_results_df=None):
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

    # ✅ 使用新的統計檢定函數
    if cv_results_df is None:
        cv_results_df = calculate_qc_cv_with_statistical_test(
            results_df, sample_columns, sample_info_df, original_df,
            col_to_info=col_to_info
        )

    # 合併結果
    results_with_cv = results_df.merge(cv_results_df, on='FeatureID', how='left')
    results_with_cv = apply_feature_metadata_passthrough(results_with_cv, original_df)

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

    # 寫入 Excel（將內部欄名 'FeatureID' 還原為 FEATURE_ID_COLUMN）
    def _rename_feature_col(df):
        if 'FeatureID' in df.columns and FEATURE_ID_COLUMN != 'FeatureID':
            return df.rename(columns={'FeatureID': FEATURE_ID_COLUMN})
        return df

    # ===== Fix 3: 簡化欄位名稱 (移除 DNA/RNA_programN_ prefix) =====
    rename_map = {}
    for col in sample_columns:
        simplified = simplify_column_name(col)
        if simplified != col:
            rename_map[col] = simplified

    retained_sheets = {
        SHEET_NAMES['raw_intensity']: all_sheets[SHEET_NAMES['raw_intensity']],
        SHEET_NAMES['sample_info']: all_sheets[SHEET_NAMES['sample_info']],
    }

    if rename_map:
        print(f"✓ 簡化 {len(rename_map)} 個欄位名稱（移除 DNA/RNA_programN_ 前綴）")
        # Rename in results
        results_with_cv = results_with_cv.rename(columns=rename_map)
        # Rename in retained upstream sheets only
        for sheet_name in retained_sheets:
            retained_sheets[sheet_name] = retained_sheets[sheet_name].rename(columns=rename_map)

        # Update SampleInfo Sample_Name to match simplified column names
        # so downstream processors can match columns to SampleInfo directly
        if SHEET_NAMES['sample_info'] in retained_sheets and col_to_info:
            si = retained_sheets[SHEET_NAMES['sample_info']]
            if 'Sample_Name' in si.columns:
                # Build reverse mapping: original SampleInfo name → simplified column name
                info_name_to_col = {}
                for orig_col, info in col_to_info.items():
                    simplified = rename_map.get(orig_col, orig_col)
                    info_name_to_col[info['Sample_Name'].strip()] = simplified

                def _update_sample_name(name):
                    name_stripped = str(name).strip()
                    return info_name_to_col.get(name_stripped, name_stripped)

                si['Sample_Name'] = si['Sample_Name'].apply(_update_sample_name)
                retained_sheets[SHEET_NAMES['sample_info']] = si

    # ===== 在 ISTD_Correction 中插入 Sample_Type 資訊行 =====
    # 讓下游步驟可直接從資料 sheet 讀取分組資訊，無需另查 SampleInfo
    if col_to_info:
        from metabolomics.utils.sample_classification import normalize_sample_type
        sample_type_row = {'FeatureID': 'Sample_Type'}
        for col in results_with_cv.columns:
            if col in sample_type_row:
                continue
            # 先查原始欄名（rename 前），再查 rename 後的名稱
            orig_col = col
            if rename_map:
                # rename_map: original -> simplified，需要反查
                reverse_map = {v: k for k, v in rename_map.items()}
                orig_col = reverse_map.get(col, col)
            info = col_to_info.get(orig_col, col_to_info.get(col))
            if info is not None and 'Sample_Type' in info:
                sample_type_row[col] = normalize_sample_type(info['Sample_Type'])
            else:
                sample_type_row[col] = ''
        type_row_df = pd.DataFrame([sample_type_row], columns=results_with_cv.columns)
        results_with_cv = pd.concat([type_row_df, results_with_cv], ignore_index=True)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        for sheet_name, df in retained_sheets.items():
            _rename_feature_col(df).to_excel(writer, sheet_name=sheet_name, index=False)
        _rename_feature_col(results_with_cv).to_excel(writer, sheet_name=SHEET_NAMES['istd_correction'], index=False)

    # 統計區格式設定（直接配色，不複製原始檔格式）
    new_workbook = load_workbook(output_file)

    # ISTD_Correction 格式
    scientific_format = '0.00E+00'

    if SHEET_NAMES['istd_correction'] in new_workbook.sheetnames:
        worksheet = new_workbook[SHEET_NAMES['istd_correction']]
        header = [cell.value for cell in worksheet[1]]
        header_map = {name: idx + 1 for idx, name in enumerate(header) if name}

        apply_header_fill(worksheet)

        for col_name in ['Original_QC_CV%', 'Corrected_QC_CV%', 'Original_Robust_CV%', 'Corrected_Robust_CV%']:
            if col_name in header_map:
                apply_cv_quality_fill(worksheet, header_map[col_name])
                apply_number_format(worksheet, header_map[col_name], '0.00')

        for col_name in ['CV_Improvement%', 'Robust_CV_Improvement%']:
            if col_name in header_map:
                apply_improvement_fill(worksheet, header_map[col_name])
                apply_number_format(worksheet, header_map[col_name], '+0.00;-0.00')

        for q_col_name in ['Wilcoxon_qvalue', 'Variance_Test_qvalue']:
            if q_col_name in header_map:
                apply_significance_fill(worksheet, header_map[q_col_name])
                apply_number_format(worksheet, header_map[q_col_name], '0.0000')

        for p_col_name in ['Wilcoxon_pvalue', 'Variance_Test_pvalue']:
            if p_col_name in header_map:
                apply_number_format(worksheet, header_map[p_col_name], '0.0000')

        if 'Significant_Improvement' in header_map:
            apply_status_fill(
                worksheet,
                header_map['Significant_Improvement'],
                {
                    'Yes': 'pass',
                    'Yes (CV% only)': 'warn',
                    'Marginal': 'warn',
                    'No': 'fail',
                },
            )

        for col_name in header:
            if not col_name or is_non_sample_column(col_name):
                continue
            apply_number_format(worksheet, header_map[col_name], scientific_format)

    new_workbook.save(output_file)

    print(f"\n{'='*70}")
    print(f"✓ ISTD Correction 結果已保存:")
    print(f"  {output_file}")
    print(f"{'='*70}\n")


def main(input_file=None, session_dir=None):
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
    if input_file is None:
        raise ValueError("input_file is required; GUI must provide the file path.")

    session_dir = resolve_session_dir(input_file=input_file, session_dir=session_dir)


    # 🔧 建立 output 資料夾
    output_dir = get_output_root(input_file=input_file)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"已建立 'output' 資料夾: {output_dir}")

    if input_file is None:
        raise ValueError("input_file is required; GUI must provide the file path.")

    # 驗證檔案是否存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"找不到檔案: {input_file}")

    print("\n" + "="*70)
    print("🔬 開始 ISTD Correction 分析")
    print(f"📁 輸入檔案: {os.path.basename(input_file)}")
    print("="*70 + "\n")

    # 載入數據 (raises ValueError on failure)
    original_df, sample_info_df, all_sheets, col_to_info = load_and_process_data(input_file)

    # 計算校正結果 (raises ValueError on failure)
    sample_columns = None

    # 🔧 修改：儲存結果到 output 資料夾
    run_timestamp = datetime.now().strftime(DATETIME_FORMAT_FULL)
    if session_dir is not None:
        from metabolomics.utils.file_io import session_output_path, session_plots_dir
        output_file = session_output_path(session_dir, step=1, prefix="ISTD_Results")
        _plots_dir = session_plots_dir(session_dir)
    else:
        output_file = build_output_path("ISTD_Results", input_file=input_file, timestamp=run_timestamp)
        _plots_dir = build_plots_dir(
            "ISTD_Correction_plots",
            input_file=input_file,
            timestamp=run_timestamp,
            session_prefix="ISTD_Correction"
        )

    def _plot_path(filename_without_ext):
        """Build plot file path, adding step prefix when in session mode."""
        if session_dir is not None:
            return os.path.join(str(_plots_dir), f"Step1_{filename_without_ext}.png")
        return os.path.join(str(_plots_dir), f"{filename_without_ext}_{run_timestamp}.png")

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

    gate_eval = evaluate_istd_gate(original_df, col_to_info, sample_info_df=sample_info_df)
    print("\n" + "="*70)
    print("🔎 ISTD 前置品質檢查")
    print("="*70)
    print(f"  - QC 樣本數: {len(gate_eval['qc_columns'])}")
    print(f"  - ISTD 總數: {gate_eval['total_istd']}")
    print(f"  - QC_CV% < {CV_QUALITY_THRESHOLDS['excellent']:.0f}% 的 ISTD: {gate_eval['good_istd_count']}")
    if gate_eval['should_skip']:
        print("  - 決策: 跳過 Step 1 ISTD Correction")
        print("  - 原因: 合格 ISTD 數量不足，後續 Step 2 應直接使用 RawIntensity")
    print("="*70 + "\n")

    if gate_eval['should_skip']:
        # Skip: no output workbook is produced. Downstream steps should continue
        # from the original input and apply their own fallback filtering.
        skip_reason = (
            'no_istd_detected'
            if gate_eval['total_istd'] == 0
            else 'insufficient_good_istd'
        )
        return ProcessingResult(
            file_path=input_file,
            output_path=input_file,
            metabolites=len(original_df),
            samples=len(gate_eval['sample_columns']),
            status=WorkflowOutcome.SKIPPED,
            reason=skip_reason,
            extra={
                'total_istd': gate_eval['total_istd'],
                'good_istd': gate_eval['good_istd_count'],
            }
        )

    results_df, sample_columns = calculate_corrected_ratios(original_df, sample_info_df)

    cv_results_df = calculate_qc_cv_with_statistical_test(
        results_df,
        sample_columns,
        sample_info_df,
        original_df,
        col_to_info=col_to_info,
    )

    save_results_to_excel(
        original_df, results_df, sample_info_df,
        output_file, all_sheets, sample_columns, input_file,
        plots_dir=_plots_dir, col_to_info=col_to_info, cv_results_df=cv_results_df
    )
    generate_step1_diagnostic_plots(
        original_df,
        results_df,
        sample_columns,
        sample_info_df,
        cv_results_df,
        plots_dir=str(_plots_dir),
        timestamp=run_timestamp,
        col_to_info=col_to_info,
    )

    print(f"\n  ✓ ISTD Correction 完成 → {os.path.basename(output_file)}")

    # 🎯 返回統計資訊給 GUI
    return ProcessingResult(
        file_path=input_file,
        output_path=str(output_file),
        plots_dir=str(_plots_dir),
        metabolites=len(original_df),
        samples=len(sample_columns),
        status=WorkflowOutcome.SUCCEEDED,
    )


if __name__ == "__main__":
    # 🔧 獨立運行時不傳入 input_file，會顯示對話框
    main()
