import pandas as pd

from metabolomics.processors.batch_effect import prepare_data_for_combat
from metabolomics.utils.sample_classification import identify_sample_columns, normalize_sample_name


def test_normalize_sample_name_handles_spacing_camelcase_and_tissue_suffix():
    assert normalize_sample_name("Tumor tissue BC2257_DNA") == normalize_sample_name("TumorBC2257_DNA")
    assert normalize_sample_name("Normal tissue BC2257_DNA") == normalize_sample_name("NormalBC2257_DNA")
    assert normalize_sample_name("Breast Cancer Tissue_ pooled_QC_1") == normalize_sample_name(
        "Breast_Cancer_Tissue_pooled_QC_1"
    )


def test_identify_sample_columns_matches_mismatched_names_and_ignores_ratio_columns():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": [
                "Tumor tissue BC2257_DNA",
                "Normal tissue BC2257_DNA",
                "Breast Cancer Tissue_ pooled_QC_1",
            ],
            "Sample_Type": ["Exposure", "Normal", "QC"],
            "Batch": ["A", "B", "A"],
        }
    )
    df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "TumorBC2257_DNA": [10.0],
            "NormalBC2257_DNA": [20.0],
            "Breast_Cancer_Tissue_pooled_QC_1": [30.0],
            "exposure_ratio": [0.5],
            "QC_ratio": [1.0],
        }
    )

    sample_columns, dropped_columns = identify_sample_columns(df, sample_info_df)

    assert sample_columns == [
        "TumorBC2257_DNA",
        "NormalBC2257_DNA",
        "Breast_Cancer_Tissue_pooled_QC_1",
    ]
    assert "exposure_ratio" not in sample_columns
    assert "QC_ratio" not in sample_columns
    assert dropped_columns == []


def test_prepare_data_for_combat_matches_normalized_sample_names():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": [
                "Tumor tissue BC2257_DNA",
                "Normal tissue BC2257_DNA",
                "Breast Cancer Tissue_ pooled_QC_1",
            ],
            "Sample_Type": ["Exposure", "Normal", "QC"],
            "Batch": ["A", "B", "A"],
        }
    )
    data = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0", "200.2/2.0"],
            "TumorBC2257_DNA": [10.0, 11.0],
            "NormalBC2257_DNA": [20.0, 21.0],
            "Breast_Cancer_Tissue_pooled_QC_1": [30.0, 31.0],
            "exposure_ratio": [0.5, 0.6],
        }
    )

    data_matrix, batch_info, sample_columns, feature_ids = prepare_data_for_combat(data, sample_info_df)

    assert sample_columns == [
        "TumorBC2257_DNA",
        "NormalBC2257_DNA",
        "Breast_Cancer_Tissue_pooled_QC_1",
    ]
    assert batch_info == ["A", "B", "A"]
    assert data_matrix.shape == (2, 3)
    assert list(feature_ids) == ["100.1/1.0", "200.2/2.0"]
