import pandas as pd
import pytest

from metabolomics.utils import workbook_input
from metabolomics.utils.workbook_input import (
    MissingSampleInfoSheetError,
    MissingSourceSheetError,
    ProcessorWorkbookInput,
    WorkbookPurpose,
)


def _write_workbook(path, sheets):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, dataframe in sheets.items():
            dataframe.to_excel(writer, sheet_name=sheet_name, index=False)


def _record_sheet_reads(monkeypatch):
    original_read_excel = pd.read_excel
    calls = []

    def recording_read_excel(*args, **kwargs):
        calls.append((kwargs.get("sheet_name"), kwargs.get("nrows")))
        return original_read_excel(*args, **kwargs)

    monkeypatch.setattr(workbook_input.pd, "read_excel", recording_read_excel)
    return calls


def _load_workbook(path, purpose):
    with ProcessorWorkbookInput(path, purpose) as workbook:
        return workbook.load()


def test_qc_lowess_prefers_istd_and_reads_only_selected_sheets(tmp_path, monkeypatch):
    workbook_path = tmp_path / "qc_lowess_input.xlsx"
    raw_df = pd.DataFrame({"Mz/RT": ["100/1"], "S1": [1.5]})
    istd_df = pd.DataFrame({"Mz/RT": ["100/1"], "S1": [2.5]})
    sample_info_df = pd.DataFrame(
        {"Sample_Name": ["S1"], "Sample_Type": ["QC"]}
    )
    _write_workbook(
        workbook_path,
        {
            "RawIntensity": raw_df,
            "ISTD_Correction": istd_df,
            "SampleInfo": sample_info_df,
            "Large_Audit": pd.DataFrame({"unused": range(100)}),
        },
    )
    calls = _record_sheet_reads(monkeypatch)

    loaded = _load_workbook(workbook_path, WorkbookPurpose.QC_LOWESS)

    assert loaded.source_sheet == "ISTD_Correction"
    pd.testing.assert_frame_equal(loaded.source_df, istd_df)
    assert {sheet_name for sheet_name, _ in calls} == {
        "ISTD_Correction",
        "SampleInfo",
    }


def test_qc_lowess_falls_back_to_raw_intensity(tmp_path):
    workbook_path = tmp_path / "qc_lowess_raw_fallback.xlsx"
    raw_df = pd.DataFrame({"Mz/RT": ["100/1"], "S1": [1.5]})
    _write_workbook(
        workbook_path,
        {
            "RawIntensity": raw_df,
            "SampleInfo": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["QC"]}
            ),
        },
    )

    loaded = _load_workbook(workbook_path, WorkbookPurpose.QC_LOWESS)

    assert loaded.source_sheet == "RawIntensity"
    pd.testing.assert_frame_equal(loaded.source_df, raw_df)


def test_qc_lowess_defers_missing_source_until_after_sample_info(tmp_path):
    workbook_path = tmp_path / "qc_lowess_missing_source.xlsx"
    _write_workbook(
        workbook_path,
        {
            "SampleInfo": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["QC"]}
            ),
        },
    )

    with ProcessorWorkbookInput(workbook_path, WorkbookPurpose.QC_LOWESS) as workbook:
        assert workbook.sample_info_df["Sample_Name"].tolist() == ["S1"]
        with pytest.raises(MissingSourceSheetError):
            workbook.load()


def test_normalization_loads_only_selected_and_optional_sheets(tmp_path, monkeypatch):
    workbook_path = tmp_path / "normalization_input.xlsx"
    raw_df = pd.DataFrame({"Mz/RT": ["100/1"], "S1": [1.0]})
    selected_df = pd.DataFrame({"Mz/RT": ["100/1"], "S1": [2.5]})
    sample_info_df = pd.DataFrame(
        {"Sample_Name": ["S1"], "Sample_Type": ["Sample"]}
    )
    advanced_df = pd.DataFrame({"metric": ["median_cv"]})
    _write_workbook(
        workbook_path,
        {
            "RawIntensity": raw_df,
            "Large_Audit": pd.DataFrame({"unused": range(100)}),
            "Sample_Info": sample_info_df,
            "QC LOWESS result": selected_df,
            "QC_LOESS_Advanced Statistics": advanced_df,
        },
    )
    calls = _record_sheet_reads(monkeypatch)

    loaded = _load_workbook(workbook_path, WorkbookPurpose.NORMALIZATION)

    assert loaded.source_sheet == "QC LOWESS result"
    assert loaded.sample_info_sheet == "Sample_Info"
    pd.testing.assert_frame_equal(loaded.source_df, selected_df)
    pd.testing.assert_frame_equal(loaded.sample_info_df, sample_info_df)
    pd.testing.assert_frame_equal(
        loaded.optional_sheets["QC_LOESS_Advanced Statistics"],
        advanced_df,
    )
    assert {sheet_name for sheet_name, _ in calls} == {
        "QC LOWESS result",
        "Sample_Info",
        "QC_LOESS_Advanced Statistics",
    }


def test_normalization_sample_info_heuristic_reads_headers_only(tmp_path, monkeypatch):
    workbook_path = tmp_path / "heuristic_sample_info.xlsx"
    _write_workbook(
        workbook_path,
        {
            "RawIntensity": pd.DataFrame({"Mz/RT": ["100/1"], "S1": [1.0]}),
            "Unrelated": pd.DataFrame({"unused": range(20)}),
            "Metadata": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["Sample"]}
            ),
        },
    )
    calls = _record_sheet_reads(monkeypatch)

    loaded = _load_workbook(workbook_path, WorkbookPurpose.NORMALIZATION)

    assert loaded.sample_info_sheet == "Metadata"
    assert ("Unrelated", 0) in calls
    assert ("Unrelated", None) not in calls
    assert ("Metadata", 0) in calls
    assert ("Metadata", None) in calls


def test_batch_diagnostics_prefers_specnorm_and_ignores_unrelated_sheets(
    tmp_path,
    monkeypatch,
):
    workbook_path = tmp_path / "batch_input.xlsx"
    specnorm_df = pd.DataFrame({"Mz/RT": ["100/1"], "S1": [3.5]})
    _write_workbook(
        workbook_path,
        {
            "PQN_Result": pd.DataFrame({"Mz/RT": ["100/1"], "S1": [2.5]}),
            "SpecNorm_PQN_Result": specnorm_df,
            "SampleInfo": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["Sample"]}
            ),
            "Large_Audit": pd.DataFrame({"unused": range(100)}),
        },
    )
    calls = _record_sheet_reads(monkeypatch)

    loaded = _load_workbook(
        workbook_path,
        WorkbookPurpose.BATCH_DIAGNOSTICS,
    )

    assert loaded.source_sheet == "SpecNorm_PQN_Result"
    pd.testing.assert_frame_equal(loaded.source_df, specnorm_df)
    assert {sheet_name for sheet_name, _ in calls} == {
        "SpecNorm_PQN_Result",
        "SampleInfo",
    }


def test_batch_diagnostics_requires_canonical_sample_info_sheet(tmp_path):
    workbook_path = tmp_path / "missing_sample_info.xlsx"
    _write_workbook(
        workbook_path,
        {
            "PQN_Result": pd.DataFrame({"Mz/RT": ["100/1"], "S1": [2.0]}),
            "Sample_Info": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["Sample"]}
            ),
        },
    )

    with pytest.raises(MissingSampleInfoSheetError):
        _load_workbook(
            workbook_path,
            WorkbookPurpose.BATCH_DIAGNOSTICS,
        )


def test_normalization_main_preserves_missing_source_error(tmp_path):
    from metabolomics.processors import normalization

    workbook_path = tmp_path / "missing_source.xlsx"
    _write_workbook(
        workbook_path,
        {
            "SampleInfo": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["QC"], "Batch": ["A"]}
            ),
        },
    )

    with pytest.raises(Exception, match="找不到資料工作表"):
        normalization.main(workbook_path, normalization_method="PQN")


def test_normalization_main_fails_when_batch_metadata_is_missing(tmp_path):
    from metabolomics.processors import normalization

    workbook_path = tmp_path / "normalization_missing_batch.xlsx"
    _write_workbook(
        workbook_path,
        {
            "SampleInfo": pd.DataFrame(
                {"Sample_Name": ["QC1"], "Sample_Type": ["QC"]}
            ),
        },
    )

    with pytest.raises(ValueError, match="請先補齊 Batch"):
        normalization.main(workbook_path, normalization_method="PQN")


def test_normalization_main_fails_when_sample_info_has_no_qc(tmp_path):
    from metabolomics.processors import normalization

    workbook_path = tmp_path / "normalization_no_qc.xlsx"
    _write_workbook(
        workbook_path,
        {
            "SampleInfo": pd.DataFrame(
                {
                    "Sample_Name": ["Sample1"],
                    "Sample_Type": ["Exposure"],
                    "Batch": ["A"],
                }
            ),
        },
    )

    with pytest.raises(ValueError, match="未找到 QC 樣本"):
        normalization.main(workbook_path, normalization_method="PQN")


def test_batch_loader_preserves_missing_sample_info_error(tmp_path):
    from metabolomics.processors import qc_batch_scaling

    workbook_path = tmp_path / "missing_canonical_sample_info.xlsx"
    _write_workbook(
        workbook_path,
        {
            "PQN_Result": pd.DataFrame({"Mz/RT": ["100/1"], "S1": [2.0]}),
        },
    )

    with pytest.raises(ValueError, match="Missing required sheet: SampleInfo"):
        qc_batch_scaling.load_and_process_data(workbook_path)


def test_normalization_validates_sample_info_before_missing_source(tmp_path):
    from metabolomics.processors import normalization

    workbook_path = tmp_path / "invalid_sample_info_and_missing_source.xlsx"
    _write_workbook(
        workbook_path,
        {
            "SampleInfo": pd.DataFrame({"Unrelated": ["value"]}),
        },
    )

    with pytest.raises(ValueError, match="Step 3 SampleInfo validation failed"):
        normalization.main(workbook_path, normalization_method="PQN")


def test_normalization_validates_specnorm_reference_before_missing_source(tmp_path):
    from metabolomics.processors import normalization

    workbook_path = tmp_path / "missing_reference_and_source.xlsx"
    _write_workbook(
        workbook_path,
        {
            "SampleInfo": pd.DataFrame(
                {"Sample_Name": ["S1"], "Sample_Type": ["QC"], "Batch": ["A"]}
            ),
        },
    )

    with pytest.raises(ValueError, match=r"SpecNorm\+PQN"):
        normalization.main(workbook_path, normalization_method="SpecNorm_PQN")
