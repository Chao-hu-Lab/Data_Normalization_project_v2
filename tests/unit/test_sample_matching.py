import pandas as pd

from metabolomics.processors.qc_batch_scaling import build_batch_membership
from metabolomics.utils.sample_classification import (
    build_sample_info_mapping,
    identify_candidate_sample_columns,
    identify_sample_columns,
    normalize_sample_name,
)


def test_normalize_sample_name_handles_spacing_camelcase_and_tissue_suffix():
    assert normalize_sample_name("Tumor tissue BC2257_DNA") == normalize_sample_name("TumorBC2257_DNA")
    assert normalize_sample_name("Normal tissue BC2257_DNA") == normalize_sample_name("NormalBC2257_DNA")
    assert normalize_sample_name("Breast Cancer Tissue_ pooled_QC_1") == normalize_sample_name(
        "Breast_Cancer_Tissue_pooled_QC_1"
    )


def test_normalize_sample_name_treats_special_chars_and_dna_rna_variants_as_equivalent():
    assert normalize_sample_name("Breast Cancer Tissue *pooled_QC_2") == normalize_sample_name(
        "Breast_Cancer_Tissue_pooled_QC_2"
    )
    assert normalize_sample_name("Tumor tissue BC2286* DNA +RNA") == normalize_sample_name(
        "TumorBC2286_DNAandRNA"
    )
    assert normalize_sample_name("Tumor tissue BC2304_ DNA +RNA") == normalize_sample_name(
        "TumorBC2304_DNAandRNA"
    )


def test_normalize_sample_name_treats_old_pooled_qc_pool_and_pool_dna_variants_as_equivalent():
    assert normalize_sample_name("Old Breast Cancer Tissue_ pooled_QC_1") == normalize_sample_name(
        "Old Breast_Cancer_Tissue_pool_DNA_QC_1"
    )
    assert normalize_sample_name("Old Breast Cancer Tissue _pooled_QC_2") == normalize_sample_name(
        "Old Breast_Cancer_Tissue_pool_DNA_QC_2"
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


def test_identify_sample_columns_matches_qc_and_rna_names_with_special_chars():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": [
                "Breast Cancer Tissue *pooled_QC_2",
                "Tumor tissue BC2286* DNA +RNA",
                "Tumor tissue BC2304_ DNA +RNA",
            ],
            "Sample_Type": ["QC", "Exposure", "Exposure"],
            "Batch": ["A", "A", "A"],
        }
    )
    df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "Breast_Cancer_Tissue_pooled_QC_2": [30.0],
            "TumorBC2286_DNAandRNA": [40.0],
            "TumorBC2304_DNAandRNA": [50.0],
        }
    )

    sample_columns, dropped_columns = identify_sample_columns(df, sample_info_df)

    assert sample_columns == [
        "Breast_Cancer_Tissue_pooled_QC_2",
        "TumorBC2286_DNAandRNA",
        "TumorBC2304_DNAandRNA",
    ]
    assert dropped_columns == []


def test_identify_sample_columns_keeps_old_pooled_qc_columns_with_pool_dna_spelling():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": [
                "Old Breast Cancer Tissue_ pooled_QC_1",
                "Old Breast Cancer Tissue _pooled_QC_2",
                "Breast Cancer Tissue_pooled_QC_3",
            ],
            "Sample_Type": ["QC", "QC", "QC"],
            "Batch": ["A", "A", "B"],
        }
    )
    df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "Old Breast_Cancer_Tissue_pool_DNA_QC_1": [10.0],
            "Old Breast_Cancer_Tissue_pool_DNA_QC_2": [20.0],
            "Breast_Cancer_Tissue_pooled_QC_3": [30.0],
        }
    )

    sample_columns, dropped_columns = identify_sample_columns(df, sample_info_df)

    assert sample_columns == [
        "Old Breast_Cancer_Tissue_pool_DNA_QC_1",
        "Old Breast_Cancer_Tissue_pool_DNA_QC_2",
        "Breast_Cancer_Tissue_pooled_QC_3",
    ]
    assert dropped_columns == []


def test_identify_sample_columns_excludes_ratio_and_cv_stat_columns():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": ["Exposure_A", "Normal_A", "Benign_A", "QC_1"],
            "Sample_Type": ["Exposure", "Normal", "Benign", "QC"],
            "Batch": ["A", "A", "A", "A"],
        }
    )
    df = pd.DataFrame(
        {
            "FeatureID": ["100.1/1.0"],
            "Exposure_A": [10.0],
            "Normal_A": [20.0],
            "Benign_A": [30.0],
            "QC_1": [40.0],
            "exposure_ratio": [0.5],
            "normal_ratio": [0.6],
            "control_ratio": [0.7],
            "QC_ratio": [0.8],
            "Original_CV%": [12.0],
            "Normalized_CV%": [8.0],
        }
    )

    sample_columns, dropped_columns = identify_sample_columns(df, sample_info_df)

    assert sample_columns == ["Exposure_A", "Normal_A", "Benign_A", "QC_1"]
    assert "exposure_ratio" not in sample_columns
    assert "normal_ratio" not in sample_columns
    assert "control_ratio" not in sample_columns
    assert "QC_ratio" not in sample_columns
    assert "Original_CV%" not in sample_columns
    assert "Normalized_CV%" not in sample_columns


def test_identify_sample_columns_returns_empty_when_no_sampleinfo_match_exists():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": ["Case_001", "Case_002"],
            "Sample_Type": ["Exposure", "Control"],
        }
    )
    df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "TotallyDifferent_1": [10.0],
            "TotallyDifferent_2": [20.0],
            "custom_ratio_metric": [0.5],
            "mystery_score": [99.0],
        }
    )

    sample_columns, dropped_columns = identify_sample_columns(df, sample_info_df)

    assert sample_columns == []
    assert dropped_columns == []


def test_identify_candidate_sample_columns_keeps_unmatched_data_columns_for_fail_closed_checks():
    df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "Real_A": [10.0],
            "Wrong_Y": [20.0],
            "is_ISTD": [False],
            "custom_ratio_metric": [0.5],
            "robust_cv_summary": [8.0],
        }
    )

    candidate_columns, dropped_columns = identify_candidate_sample_columns(
        df,
        extra_non_sample_columns={"is_ISTD"},
    )

    assert candidate_columns == ["Real_A", "Wrong_Y", "custom_ratio_metric"]
    assert dropped_columns == ["robust_cv_summary"]


def test_build_sample_info_mapping_matches_program_prefixed_columns_via_fuzzy_tokens():
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": ["Normal tissue BC2257_DNA", "Tumor tissue BC2257_DNA"],
            "Sample_Type": ["Normal", "Exposure"],
            "Batch": ["A", "A"],
        }
    )

    mapping = build_sample_info_mapping(
        ["DNA_program1_Normal_BC2257", "DNA_program1_Tumor_BC2257"],
        sample_info_df,
    )

    assert mapping["DNA_program1_Normal_BC2257"]["Sample_Type"] == "Normal"
    assert mapping["DNA_program1_Tumor_BC2257"]["Sample_Type"] == "Exposure"


def test_build_batch_membership_matches_normalized_sample_names():
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

    sample_columns, dropped_columns = identify_sample_columns(data, sample_info_df)
    batch_to_qc, batch_to_samples = build_batch_membership(sample_info_df, sample_columns)

    assert sample_columns == [
        "TumorBC2257_DNA",
        "NormalBC2257_DNA",
        "Breast_Cancer_Tissue_pooled_QC_1",
    ]
    assert dropped_columns == []
    assert batch_to_qc == {"A": ["Breast_Cancer_Tissue_pooled_QC_1"]}
    assert batch_to_samples == {
        "A": ["TumorBC2257_DNA", "Breast_Cancer_Tissue_pooled_QC_1"],
        "B": ["NormalBC2257_DNA"],
    }
