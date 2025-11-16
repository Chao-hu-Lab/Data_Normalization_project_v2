#!/usr/bin/env python3
"""
ISTD_Correction_v2 防呆措施测试脚本

测试各种错误输入情况，验证防呆机制是否正常工作
"""

import os
import sys
import tempfile
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font

def test_file_not_found():
    """测试1: 文件不存在"""
    print("\n" + "="*70)
    print("测试1: 文件不存在")
    print("="*70)

    from ISTD_Correction_v2 import load_and_process_data

    result = load_and_process_data("non_existent_file.xlsx")
    assert result == (None, None, None), "应该返回 None"
    print("✓ 通过: 正确处理文件不存在的情况")


def test_invalid_file_format():
    """测试2: 无效的文件格式"""
    print("\n" + "="*70)
    print("测试2: 无效的文件格式")
    print("="*70)

    from ISTD_Correction_v2 import load_and_process_data

    # 创建一个非 Excel 文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        temp_file = f.name
        f.write("test")

    try:
        result = load_and_process_data(temp_file)
        assert result == (None, None, None), "应该返回 None"
        print("✓ 通过: 正确拒绝非 Excel 格式文件")
    finally:
        os.unlink(temp_file)


def test_empty_file():
    """测试3: 空文件"""
    print("\n" + "="*70)
    print("测试3: 空文件")
    print("="*70)

    from ISTD_Correction_v2 import load_and_process_data

    # 创建一个空文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xlsx', delete=False) as f:
        temp_file = f.name

    try:
        result = load_and_process_data(temp_file)
        assert result == (None, None, None), "应该返回 None"
        print("✓ 通过: 正确检测空文件")
    finally:
        os.unlink(temp_file)


def test_missing_sheets():
    """测试4: 缺少必要的工作表"""
    print("\n" + "="*70)
    print("测试4: 缺少必要的工作表")
    print("="*70)

    from ISTD_Correction_v2 import load_and_process_data

    # 创建一个只有部分工作表的 Excel 文件
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.xlsx', delete=False) as f:
        temp_file = f.name

    wb = Workbook()
    ws = wb.active
    ws.title = "SomeSheet"
    wb.save(temp_file)
    wb.close()

    try:
        result = load_and_process_data(temp_file)
        assert result == (None, None, None), "应该返回 None"
        print("✓ 通过: 正确检测缺少必要工作表")
    finally:
        os.unlink(temp_file)


def test_weight_validation():
    """测试5: 权重参数验证"""
    print("\n" + "="*70)
    print("测试5: 权重参数验证")
    print("="*70)

    from ISTD_Correction_v2 import find_best_istd_for_analyte
    import numpy as np

    # 创建模拟数据
    analyte_row = pd.Series({'rt': 5.0, 'mz': 200.0})
    istd_signals = pd.DataFrame({
        'FeatureID': ['ISTD1'],
        'rt': [5.1],
        'mz': [201.0]
    })
    istd_cv = {'ISTD1': 10.0}
    sample_columns = ['Sample1', 'Sample2']

    # 测试负权重
    try:
        result = find_best_istd_for_analyte(
            analyte_row, istd_signals, istd_cv, sample_columns,
            rt_weight=-0.1, cv_weight=0.5, intensity_weight=0.3, mz_weight=0.3
        )
        print("✗ 失败: 应该拒绝负权重")
    except ValueError as e:
        if "權重不能為負值" in str(e):
            print("✓ 通过: 正确拒绝负权重")
        else:
            print(f"✗ 失败: 错误消息不正确 - {e}")

    # 测试权重总和不为 1
    try:
        result = find_best_istd_for_analyte(
            analyte_row, istd_signals, istd_cv, sample_columns,
            rt_weight=0.5, cv_weight=0.3, intensity_weight=0.1, mz_weight=0.05
        )
        print("✗ 失败: 应该拒绝权重总和不为 1")
    except ValueError as e:
        if "權重總和" in str(e):
            print("✓ 通过: 正确拒绝权重总和不为 1")
        else:
            print(f"✗ 失败: 错误消息不正确 - {e}")


def test_alpha_validation():
    """测试6: alpha 参数验证"""
    print("\n" + "="*70)
    print("测试6: alpha 参数验证")
    print("="*70)

    from ISTD_Correction_v2 import calculate_hotelling_t2_outliers
    import numpy as np

    # 创建模拟 QC scores
    qc_scores = np.random.randn(5, 2)

    # 测试 alpha = 0
    try:
        result = calculate_hotelling_t2_outliers(qc_scores, alpha=0)
        print("✗ 失败: 应该拒绝 alpha = 0")
    except ValueError as e:
        if "alpha 必須在 (0, 1) 範圍內" in str(e):
            print("✓ 通过: 正确拒绝 alpha = 0")
        else:
            print(f"✗ 失败: 错误消息不正确 - {e}")

    # 测试 alpha = 1
    try:
        result = calculate_hotelling_t2_outliers(qc_scores, alpha=1)
        print("✗ 失败: 应该拒绝 alpha = 1")
    except ValueError as e:
        if "alpha 必須在 (0, 1) 範圍內" in str(e):
            print("✓ 通过: 正确拒绝 alpha = 1")
        else:
            print(f"✗ 失败: 错误消息不正确 - {e}")

    # 测试 alpha = -0.05
    try:
        result = calculate_hotelling_t2_outliers(qc_scores, alpha=-0.05)
        print("✗ 失败: 应该拒绝负的 alpha")
    except ValueError as e:
        if "alpha 必須在 (0, 1) 範圍內" in str(e):
            print("✓ 通过: 正确拒绝负的 alpha")
        else:
            print(f"✗ 失败: 错误消息不正确 - {e}")


def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("ISTD_Correction_v2 防呆措施测试")
    print("="*70)

    tests = [
        test_file_not_found,
        test_invalid_file_format,
        test_empty_file,
        test_missing_sheets,
        test_weight_validation,
        test_alpha_validation
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n✗ 测试失败: {test_func.__name__}")
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*70)
    print(f"测试总结:")
    print(f"  通过: {passed}/{len(tests)}")
    print(f"  失败: {failed}/{len(tests)}")
    print("="*70 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
