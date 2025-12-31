"""
共用工具模組

包含：
- data_helpers: 資料處理輔助函數
- statistics: 統計分析函數 (Hotelling T² 等)
- plotting: matplotlib 繪圖設定
"""

from .data_helpers import get_valid_values
from .statistics import calculate_hotelling_t2_outliers, draw_hotelling_t2_ellipse
from .plotting import setup_matplotlib, FONT_SIZES, COLORBLIND_COLORS
