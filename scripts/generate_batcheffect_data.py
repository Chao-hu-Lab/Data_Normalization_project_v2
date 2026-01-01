import numpy as np
import pandas as pd

# 設定隨機種子以確保可重現性
np.random.seed(51)

# 參數設定
n_features = 50
batches = ['A', 'B', 'C']

# 批次效應倍率
batch_effects = {'A': 1.0, 'B': 0.1, 'C': 0.3}

# 隨機選擇5-8個特徵作為內標
n_internal_standards = np.random.randint(5, 9)
is_indices = np.random.choice(n_features, n_internal_standards, replace=False)
is_indices = sorted(is_indices)

print(f"選定的內標特徵索引: {is_indices}")
print(f"內標數量: {n_internal_standards}")

# 生成樣本序列（固定 51 針）
# 規則：首針 QC，之後 Exposure -> Control 交替不停止；每 3 個樣本插入 1 個 QC。
# Exposure/Control 的交替邏輯遇到 QC 不重置，會「順延」到下一個樣本。
TOTAL_INJECTIONS = 51
BATCH_SIZE = 17
QC_EVERY_N_SAMPLES = 3

if len(batches) * BATCH_SIZE != TOTAL_INJECTIONS:
    raise ValueError(
        f"batches({len(batches)}) * BATCH_SIZE({BATCH_SIZE}) 必須等於 TOTAL_INJECTIONS({TOTAL_INJECTIONS})"
    )

sample_list: list[str] = []
batch_list: list[str] = []
sample_type_list: list[str] = []
group_list: list[str] = []

qc_counter = 1
exposure_counter = 1
control_counter = 1
exposure_next = True

# QC 的位置：第 1 針是 QC，之後每 3 個樣本插 1 個 QC（等價於每 4 針出現 1 個 QC）
qc_positions = set(range(1, TOTAL_INJECTIONS + 1, QC_EVERY_N_SAMPLES + 1))

for injection_order in range(1, TOTAL_INJECTIONS + 1):
    batch = batches[(injection_order - 1) // BATCH_SIZE]
    batch_list.append(batch)

    if injection_order in qc_positions:
        sample_list.append(f'QC{qc_counter}')
        sample_type_list.append('QC')
        group_list.append('QC')
        qc_counter += 1
        continue

    if exposure_next:
        sample_list.append(f'Exposure_{exposure_counter}')
        sample_type_list.append('Sample')
        group_list.append('Exposure')
        exposure_counter += 1
    else:
        sample_list.append(f'Control_{control_counter}')
        sample_type_list.append('Sample')
        group_list.append('Control')
        control_counter += 1

    exposure_next = not exposure_next

if len(sample_list) != TOTAL_INJECTIONS:
    raise AssertionError(f"總針數錯誤：預期 {TOTAL_INJECTIONS}，實際 {len(sample_list)}")
if not (len(batch_list) == len(sample_type_list) == len(group_list) == len(sample_list)):
    raise AssertionError("sample_list / batch_list / sample_type_list / group_list 長度不一致")

n_samples = len(sample_list)

# 生成基礎矩陣 (樣本 × 特徵)
base_intensity = 1000000
data_matrix = np.random.uniform(500000, 1500000, (n_samples, n_features))

# 為QC樣本設定相似的基礎值
qc_base_values = np.random.uniform(800000, 1200000, n_features)
for i, sample_type in enumerate(sample_type_list):
    if sample_type == 'QC':
        data_matrix[i, :] = qc_base_values * np.random.uniform(0.95, 1.05, n_features)

# === 為內標設定特殊的穩定基礎值 ===
is_base_values = np.random.uniform(900000, 1100000, n_internal_standards)
for idx, is_idx in enumerate(is_indices):
    # 內標在所有樣本中使用非常相似的基礎值
    stable_value = is_base_values[idx]
    # 內標的變異度非常小 (±3%)
    data_matrix[:, is_idx] = stable_value * np.random.uniform(0.97, 1.03, n_samples)

# 1. 添加批次效應
for i, batch in enumerate(batch_list):
    batch_factor = batch_effects[batch]
    feature_variation = np.random.uniform(0.98, 1.02, n_features)
    
    # 內標對批次效應的響應較小
    for is_idx in is_indices:
        feature_variation[is_idx] = np.random.uniform(0.99, 1.01)
    
    data_matrix[i, :] *= (batch_factor * feature_variation)

# 2. 添加時間相關的儀器飄移 (2-3.5%)
for i in range(n_samples):
    drift_rate = np.random.uniform(0.02, 0.035)
    time_factor = 1 + (drift_rate * i / n_samples)
    feature_drift = time_factor * np.random.uniform(0.99, 1.01, n_features)
    
    # 內標對儀器飄移的響應更小 (±0.5%)
    for is_idx in is_indices:
        feature_drift[is_idx] = time_factor * np.random.uniform(0.995, 1.005)
    
    data_matrix[i, :] *= feature_drift

# 3. 添加異常值 (只在非QC、非內標的樣本和特徵中)
sample_indices = [i for i, st in enumerate(sample_type_list) if st == 'Sample']
non_is_features = [j for j in range(n_features) if j not in is_indices]
n_outliers = np.random.randint(8, 15)

for _ in range(n_outliers):
    sample_idx = np.random.choice(sample_indices)
    feature_idx = np.random.choice(non_is_features)
    
    if np.random.random() > 0.5:
        # 高強度異常 (1.5個order = 10^1.5 ≈ 31.6倍)
        data_matrix[sample_idx, feature_idx] *= 31.6
    else:
        # 低強度異常 (但不低於25000)
        current_value = data_matrix[sample_idx, feature_idx]
        data_matrix[sample_idx, feature_idx] = max(1000, current_value * 0.3)

# 4. 添加缺失值
for j in range(n_features):
    if j in is_indices:
        # 內標的缺失率非常低 (0-5%)
        missing_rate = np.random.uniform(0, 0.05)
    else:
        # 一般特徵的缺失率 (0-29%)
        missing_rate = np.random.uniform(0, 0.29)
    
    n_missing = int(n_samples * missing_rate)
    if n_missing > 0:
        # 優先在樣本中添加缺失值
        available_indices = sample_indices.copy()
        if n_missing <= len(available_indices):
            missing_indices = np.random.choice(available_indices, n_missing, replace=False)
        else:
            missing_indices = np.random.choice(n_samples, n_missing, replace=False)
        data_matrix[missing_indices, j] = np.nan

# 確保所有值不低於25000（除了NaN）
data_matrix = np.where((~np.isnan(data_matrix)) & (data_matrix < 1000), 1000, data_matrix)

# 創建 DataFrame (轉置：特徵為行，樣本為列)
feature_names = []
feature_types = []
for j in range(n_features):
    if j in is_indices:
        feature_names.append(f'IS_{j+1}')
        feature_types.append('Internal_Standard')
    else:
        feature_names.append(f'Feature_{j+1}')
        feature_types.append('Analyte')

df = pd.DataFrame(data_matrix.T, index=feature_names, columns=sample_list)

# 創建特徵資訊 DataFrame
feature_info = pd.DataFrame({
    'Feature': feature_names,
    'Type': feature_types,
    'Index': range(n_features)
})

# 創建樣本資訊 DataFrame
sample_info = pd.DataFrame({
    'Sample': sample_list,
    'Batch': batch_list,
    'Group': group_list,
    'Type': sample_type_list,
    'Injection_Order': range(1, n_samples + 1)
})

# 顯示結果摘要
print("\n" + "=" * 70)
print("矩陣生成完成！")
print("=" * 70)
print(f"\n矩陣維度: {df.shape} (特徵 × 樣本)")
print(f"總樣本數: {n_samples}")
print(f"總特徵數: {n_features}")
print(f"內標數量: {n_internal_standards}")

print(f"\n特徵類型統計:")
print(feature_info['Type'].value_counts())

print(f"\n內標列表:")
is_features = feature_info[feature_info['Type'] == 'Internal_Standard']
print(is_features)

print(f"\n樣本類型統計:")
print(sample_info['Type'].value_counts())

print(f"\n批次分布:")
batch_summary = sample_info.groupby(['Batch', 'Type']).size().unstack(fill_value=0)
print(batch_summary)

print(f"\n批次效應倍率:")
for batch, effect in batch_effects.items():
    print(f"  Batch {batch}: {effect}")

# 計算每個特徵的缺失率和CV (使用正確的索引)
missing_rates = pd.Series(
    [df.loc[fname].isna().sum() / n_samples * 100 for fname in feature_names],
    index=feature_names
)
cv_values = pd.Series(
    [df.loc[fname].std() / df.loc[fname].mean() * 100 for fname in feature_names],
    index=feature_names
)

print(f"\n缺失值統計:")
print(f"總缺失值數量: {df.isna().sum().sum()}")

# 使用特徵名稱來篩選
analyte_features = feature_info[feature_info['Type'] == 'Analyte']['Feature'].tolist()
is_feature_names = feature_info[feature_info['Type'] == 'Internal_Standard']['Feature'].tolist()

print(f"一般特徵平均缺失率: {missing_rates[analyte_features].mean():.2f}%")
print(f"內標平均缺失率: {missing_rates[is_feature_names].mean():.2f}%")

print(f"\n變異係數(CV)統計:")
print(f"一般特徵平均CV: {cv_values[analyte_features].mean():.2f}%")
print(f"內標平均CV: {cv_values[is_feature_names].mean():.2f}%")

print(f"\n強度範圍:")
print(f"最小值: {np.nanmin(data_matrix):.2f}")
print(f"最大值: {np.nanmax(data_matrix):.2f}")
print(f"中位數: {np.nanmedian(data_matrix):.2f}")

print("\n各批次強度中位數比較 (以第一個內標為例):")
is_feature_name = is_features.iloc[0]['Feature']
for batch in batches:
    batch_samples = sample_info[sample_info['Batch'] == batch]['Sample'].tolist()
    batch_values = df.loc[is_feature_name, batch_samples].dropna()
    if len(batch_values) > 0:
        print(f"  Batch {batch}: {batch_values.median():.2f} (CV: {(batch_values.std()/batch_values.mean()*100):.2f}%)")

print("\n內標穩定性分析:")
for _, row in is_features.iterrows():
    feature_name = row['Feature']
    values = df.loc[feature_name].dropna()
    cv = values.std() / values.mean() * 100
    missing_rate = df.loc[feature_name].isna().sum() / n_samples * 100
    print(f"  {feature_name}: CV={cv:.2f}%, 缺失率={missing_rate:.2f}%")

print("\n前5個特徵 × 前10個樣本的數據預覽:")
print(df.iloc[:5, :10].round(2))

print("\n樣本資訊 (前20個):")
print(sample_info.head(20))

# 保存到檔案
df.to_csv('feature_matrix_with_qc_is.csv')
sample_info.to_csv('sample_info.csv', index=False)
feature_info.to_csv('feature_info.csv', index=False)

# 保存統計摘要
stats_summary = pd.DataFrame({
    'Feature': feature_names,
    'Type': feature_types,
    'Mean': [df.loc[fname].mean() for fname in feature_names],
    'Median': [df.loc[fname].median() for fname in feature_names],
    'SD': [df.loc[fname].std() for fname in feature_names],
    'CV(%)': cv_values.values,
    'Missing_Rate(%)': missing_rates.values,
    'Min': [df.loc[fname].min() for fname in feature_names],
    'Max': [df.loc[fname].max() for fname in feature_names]
})
stats_summary.to_csv('feature_statistics.csv', index=False)

print("\n" + "=" * 70)
print("已保存檔案:")
print("- feature_matrix_with_qc_is.csv (特徵矩陣)")
print("- sample_info.csv (樣本資訊)")
print("- feature_info.csv (特徵資訊，標註內標)")
print("- feature_statistics.csv (特徵統計摘要)")
print("=" * 70)
