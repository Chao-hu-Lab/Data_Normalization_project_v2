"""
資料處理輔助函數

包含各模組共用的資料處理函數。
"""
import pandas as pd


def get_valid_values(row, columns):
    """
    從 DataFrame 的一行中提取有效值（>0 且非 NaN）

    Parameters:
    -----------
    row : pd.Series
        DataFrame 的一行資料
    columns : list
        要提取的欄位名稱列表

    Returns:
    --------
    list : 有效的浮點數值列表（>0 且非 NaN）

    Examples:
    ---------
    >>> row = pd.Series({'A': 100, 'B': 200, 'C': 0, 'D': -5})
    >>> get_valid_values(row, ['A', 'B', 'C', 'D'])
    [100.0, 200.0]
    """
    values = []
    for col in columns:
        # 支援兩種檢查方式: dict-like 和 Series
        if hasattr(row, 'index'):
            if col not in row.index:
                continue
        elif col not in row:
            continue

        try:
            val = float(row[col])
            if not pd.isna(val) and val > 0:
                values.append(val)
        except (ValueError, TypeError):
            pass
    return values
