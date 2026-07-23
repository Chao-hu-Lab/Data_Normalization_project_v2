import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook
from openpyxl.styles import Font

from metabolomics.utils.constants import is_non_sample_column
from metabolomics.utils.istd_mapping import (
    ISTD_PROVENANCE_COLUMNS,
    build_istd_monitoring_table,
    calculate_selective_istd_correction,
    validate_istd_mapping,
)


SAMPLES = ["QC1", "QC2", "QC3", "QC4", "QC5", "S1", "S2"]


def test_istd_provenance_columns_are_never_treated_as_samples():
    assert all(is_non_sample_column(column) for column in ISTD_PROVENANCE_COLUMNS)


def _sample_info():
    return pd.DataFrame(
        {
            "Sample_Name": SAMPLES,
            "Sample_Type": ["QC"] * 5 + ["Exposure", "Control"],
            "Batch": ["A"] * len(SAMPLES),
            "Injection_Order": range(1, len(SAMPLES) + 1),
        }
    )


def _intensity_frame(*, incomplete_stable_donor=False):
    stable = [100.0, 101.0, 99.0, 100.0, 100.0, 110.0, 90.0]
    if incomplete_stable_donor:
        stable[-1] = np.nan
    rows = [
        {
            "FeatureID": "D1/1.0",
            "mz": 100.0,
            "rt": 1.0,
            "is_ISTD": True,
            **dict(zip(SAMPLES, stable)),
        },
        {
            "FeatureID": "D2/2.0",
            "mz": 200.0,
            "rt": 2.0,
            "is_ISTD": True,
            **dict(zip(SAMPLES, [100.0, 200.0, 50.0, 150.0, 80.0, 100.0, 100.0])),
        },
        {
            "FeatureID": "A1/1.1",
            "mz": 110.0,
            "rt": 1.1,
            "is_ISTD": False,
            **dict(zip(SAMPLES, [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])),
        },
        {
            "FeatureID": "A2/2.1",
            "mz": 210.0,
            "rt": 2.1,
            "is_ISTD": False,
            **dict(zip(SAMPLES, [5.0, np.nan, 15.0, 20.0, 25.0, 30.0, 35.0])),
        },
    ]
    return pd.DataFrame(rows)


def _mapping(
    analyte="A1/1.1",
    donor="D1/1.0",
    mapping_type="matched",
    reference="SOP-1",
):
    return pd.DataFrame(
        {
            "Analyte_Feature_ID": [analyte],
            "ISTD_Feature_ID": [donor],
            "Mapping_Type": [mapping_type],
            "Validation_Reference": [reference],
        }
    )


def test_monitoring_only_preserves_every_analyte_value_and_missing_mask():
    source = _intensity_frame()

    result, sample_columns, summary = calculate_selective_istd_correction(
        source,
        _sample_info(),
        mapping_df=None,
    )

    analytes = source.loc[
        ~source["is_ISTD"]
        & source["FeatureID"].astype(str).str.lower().ne("sample_type")
    ].set_index("FeatureID")
    output = result.set_index("FeatureID")
    pd.testing.assert_frame_equal(
        output.loc[analytes.index, sample_columns],
        analytes[sample_columns],
        check_dtype=False,
    )
    assert set(output["ISTD_Correction_Status"]) == {"uncorrected_no_mapping"}
    assert summary["corrected_features"] == 0
    assert summary["istd_mode"] == "monitoring_only"


def test_explicit_matched_mapping_applies_ratio_and_keeps_unmapped_feature_raw():
    source = _intensity_frame()

    result, sample_columns, summary = calculate_selective_istd_correction(
        source,
        _sample_info(),
        mapping_df=_mapping(),
    )

    output = result.set_index("FeatureID")
    donor_median = np.median([100.0, 101.0, 99.0, 100.0, 100.0, 110.0, 90.0])
    assert output.loc["A1/1.1", "QC2"] == pytest.approx(20.0 / 101.0 * donor_median)
    assert output.loc["A1/1.1", "ISTD_Correction_Status"] == "corrected_matched_istd"
    assert output.loc["A1/1.1", "Validation_Reference"] == "SOP-1"
    assert output.loc["A2/2.1", "ISTD_Correction_Status"] == "uncorrected_no_mapping"
    assert np.isnan(output.loc["A2/2.1", "QC2"])
    assert summary["corrected_features"] == 1
    assert summary["istd_mode"] == "selective_correction"
    assert sample_columns == SAMPLES


def test_surrogate_without_validation_reference_is_rejected_and_preserves_raw():
    source = _intensity_frame()

    result, _, summary = calculate_selective_istd_correction(
        source,
        _sample_info(),
        mapping_df=_mapping(
            mapping_type="validated_surrogate",
            reference="",
        ),
    )

    output = result.set_index("FeatureID")
    assert (
        output.loc["A1/1.1", "ISTD_Correction_Status"]
        == "uncorrected_rejected_surrogate"
    )
    assert output.loc["A1/1.1", "QC2"] == 20.0
    assert summary["corrected_features"] == 0


def test_unstable_donor_is_rejected_per_feature_not_as_matrix_wide_factor():
    source = _intensity_frame()
    mappings = pd.concat(
        [
            _mapping(analyte="A1/1.1", donor="D1/1.0"),
            _mapping(analyte="A2/2.1", donor="D2/2.0"),
        ],
        ignore_index=True,
    )

    result, _, summary = calculate_selective_istd_correction(
        source,
        _sample_info(),
        mapping_df=mappings,
    )

    output = result.set_index("FeatureID")
    assert output.loc["A1/1.1", "ISTD_Correction_Status"] == "corrected_matched_istd"
    assert output.loc["A2/2.1", "ISTD_Correction_Status"] == "uncorrected_unstable_istd"
    assert output.loc["A2/2.1", "S1"] == 30.0
    assert summary["corrected_features"] == 1


def test_incomplete_donor_rejects_whole_feature_without_creating_new_nan():
    source = _intensity_frame(incomplete_stable_donor=True)

    result, _, summary = calculate_selective_istd_correction(
        source,
        _sample_info(),
        mapping_df=_mapping(),
    )

    output = result.set_index("FeatureID")
    assert output.loc["A1/1.1", "ISTD_Correction_Status"] == "uncorrected_incomplete_istd"
    assert output.loc["A1/1.1", "S2"] == 70.0
    assert summary["corrected_features"] == 0


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (_mapping(analyte="missing"), "unknown analyte"),
        (_mapping(donor="missing"), "unknown ISTD"),
        (_mapping(donor="A2/2.1"), "not marked as ISTD"),
        (_mapping(mapping_type="automatic"), "Mapping_Type"),
        (
            pd.concat([_mapping(), _mapping()], ignore_index=True),
            "duplicate analyte",
        ),
    ],
)
def test_mapping_schema_fails_closed_for_identity_errors(mapping, message):
    with pytest.raises(ValueError, match=message):
        validate_istd_mapping(mapping, _intensity_frame())


def test_explicit_mapping_rejects_duplicate_raw_feature_identity():
    source = pd.concat(
        [_intensity_frame(), _intensity_frame().iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="unique RawIntensity FeatureID"):
        validate_istd_mapping(_mapping(), source)


def test_monitoring_table_reports_area_qc_missingness_and_rt_unavailability():
    monitoring = build_istd_monitoring_table(
        _intensity_frame(incomplete_stable_donor=True),
        _sample_info(),
    ).set_index("FeatureID")

    assert monitoring.loc["D1/1.0", "Missing_Count"] == 1
    assert monitoring.loc["D1/1.0", "QC_Missing_Count"] == 0
    assert monitoring.loc["D1/1.0", "QC_CV%"] < 20
    assert monitoring.loc["D1/1.0", "RT_Status"] == "not_available_from_current_matrix"
    assert np.isfinite(monitoring.loc["D1/1.0", "Area_Order_Spearman"])


@pytest.mark.parametrize(
    ("orders", "expected_status"),
    [
        (None, "not_available"),
        ([1, 2, 3, 4, 5, 6, np.nan], "incomplete"),
    ],
)
def test_monitoring_does_not_invent_missing_injection_order(
    orders,
    expected_status,
):
    sample_info = _sample_info()
    if orders is None:
        sample_info = sample_info.drop(columns=["Injection_Order"])
    else:
        sample_info["Injection_Order"] = orders

    monitoring = build_istd_monitoring_table(
        _intensity_frame(),
        sample_info,
    )

    assert set(monitoring["Order_Status"]) == {expected_status}
    assert monitoring["Area_Order_Spearman"].isna().all()
    assert monitoring["Alarm_Codes"].str.contains(
        f"order_{expected_status}"
    ).all()


@pytest.mark.slow
def test_step1_default_is_monitoring_only_and_does_not_call_legacy_matcher(
    istd_module,
    sample_input_file,
    monkeypatch,
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("legacy automatic ISTD matcher was called")

    monkeypatch.setattr(
        istd_module,
        "calculate_corrected_ratios",
        fail_if_called,
    )

    source, sample_info, _, _ = istd_module.load_and_process_data(
        sample_input_file
    )
    result = istd_module.main(input_file=sample_input_file)

    assert result.status.value == "succeeded"
    assert result.extra["istd_mode"] == "monitoring_only"
    assert result.extra["corrected_features"] == 0

    output = pd.read_excel(result.output_path, sheet_name="ISTD_Correction")
    output = output.loc[
        output["Mz/RT"].astype(str).str.lower().ne("sample_type")
    ].set_index("Mz/RT")
    analytes = source.loc[
        ~source["is_ISTD"]
        & source["FeatureID"].astype(str).str.lower().ne("sample_type")
    ].set_index("FeatureID")
    sample_columns = [
        name
        for name in sample_info["Sample_Name"]
        if name in analytes.columns and name in output.columns
    ]
    pd.testing.assert_frame_equal(
        output.loc[analytes.index, sample_columns],
        analytes[sample_columns],
        check_dtype=False,
    )


@pytest.mark.slow
def test_step1_workbook_applies_explicit_mapping_end_to_end(
    istd_module,
    tmp_path,
):
    source = _intensity_frame().drop(columns=["mz", "rt", "is_ISTD"]).rename(
        columns={"FeatureID": "Mz/RT"}
    )
    workbook_path = tmp_path / "explicit_mapping.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        source.to_excel(writer, sheet_name="RawIntensity", index=False)
        _sample_info().to_excel(writer, sheet_name="SampleInfo", index=False)
        _mapping().to_excel(writer, sheet_name="ISTD_Mapping", index=False)

    workbook = load_workbook(workbook_path)
    try:
        red_font = Font(color="FFFF0000")
        workbook["RawIntensity"]["A2"].font = red_font
        workbook["RawIntensity"]["A3"].font = red_font
        workbook.save(workbook_path)
    finally:
        workbook.close()

    result = istd_module.main(input_file=workbook_path)

    assert result.extra["istd_mode"] == "selective_correction"
    assert result.extra["corrected_features"] == 1
    output = pd.read_excel(
        result.output_path,
        sheet_name="ISTD_Correction",
    ).set_index("Mz/RT")
    donor_median = np.median(
        [100.0, 101.0, 99.0, 100.0, 100.0, 110.0, 90.0]
    )
    assert output.loc["A1/1.1", "QC2"] == pytest.approx(
        20.0 / 101.0 * donor_median
    )
    assert (
        output.loc["A1/1.1", "ISTD_Correction_Status"]
        == "corrected_matched_istd"
    )
    assert output.loc["A2/2.1", "S1"] == 30.0
    assert output.loc["A2/2.1", "ISTD_Correction_Status"] == (
        "uncorrected_no_mapping"
    )
    assert "ISTD_Mapping" in pd.ExcelFile(result.output_path).sheet_names
