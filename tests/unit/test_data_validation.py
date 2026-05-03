import pandas as pd
import pytest

from metabolomics.utils import data_validation
from metabolomics.utils.data_validation import DataValidator, ValidationResult


def test_validate_required_sheets_reports_missing_and_available_context():
    validator = DataValidator()

    result = validator.validate_required_sheets(
        ["SampleInfo"],
        required_sheets=["RawIntensity", "SampleInfo"],
        context="Step 1 input workbook",
    )

    assert result.is_valid is False
    assert "Step 1 input workbook" in result.errors[0]
    assert "RawIntensity" in result.errors[0]
    assert "SampleInfo" in result.errors[0]


def test_validate_file_path_accepts_pathlike_values(tmp_path):
    input_file = tmp_path / "input.xlsx"
    input_file.write_bytes(b"x" * 2048)
    validator = DataValidator()

    result = validator.validate_file_path(input_file)

    assert result.is_valid is True
    assert result.info["file_size"] == 2048


def test_validate_sample_info_can_require_qc_samples():
    validator = DataValidator()
    sample_info_df = pd.DataFrame(
        {
            "Sample_Name": ["Sample_A", "Sample_B"],
            "Sample_Type": ["Control", "Exposure"],
        }
    )

    result = validator.validate_sample_info(sample_info_df, require_qc=True)

    assert result.is_valid is False
    assert result.errors == ["未找到 QC 樣本 (Sample_Type 中無 'QC')"]


def test_validate_raw_intensity_can_fail_when_no_expected_samples_match():
    validator = DataValidator()
    raw_df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "Unmapped_A": [10.0],
            "Unmapped_B": [20.0],
        }
    )

    result = validator.validate_raw_intensity(
        raw_df,
        sample_names=["Sample_A", "Sample_B"],
        require_sample_match=True,
    )

    assert result.is_valid is False
    assert "RawIntensity 中找不到任何可與 SampleInfo 對齊的樣本欄位" in result.errors[0]


def test_validate_raw_intensity_matches_normalized_sample_names():
    validator = DataValidator()
    raw_df = pd.DataFrame(
        {
            "Mz/RT": ["100.1/1.0"],
            "TumorBC2257_DNA": [10.0],
        }
    )

    result = validator.validate_raw_intensity(
        raw_df,
        sample_names=["Tumor tissue BC2257_DNA"],
        require_sample_match=True,
    )

    assert result.is_valid is True
    assert result.info["matched_sample_count"] == 1


def test_require_valid_raises_value_error_with_context_and_errors():
    result = ValidationResult()
    result.add_error("缺少必要欄位: Sample_Type")

    with pytest.raises(ValueError, match="Step 3 SampleInfo validation failed"):
        data_validation.require_valid(result, context="Step 3 SampleInfo")


def test_validator_keeps_existing_specialized_methods_on_class():
    validator = DataValidator()

    assert callable(validator.validate_istd_signals)
    assert callable(validator.validate_batch_info)
