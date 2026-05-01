import pandas as pd
import pytest

from metabolomics.utils.data_helpers import apply_feature_metadata_passthrough


def test_apply_feature_metadata_passthrough_preserves_step4_metadata_by_feature_id():
    source_df = pd.DataFrame(
        {
            "Mz/RT": ["F1", "F2"],
            "Sample_A": [10.0, 20.0],
            "tumor_ratio": [0.25, 0.75],
            "is_Presence_Absence_Marker": [False, True],
            "Feature_Filter_Keep_Reasons": ["stable", "mnar|ratio_rescue"],
            "Imputation_Tag_Reasons": ["", "low_overall_detection"],
            "Detection_Profile": ["legacy_1", "legacy_2"],
        }
    )
    target_df = pd.DataFrame(
        {
            "Mz/RT": ["F2", "F1"],
            "Sample_A": [200.0, 100.0],
        }
    )

    result = apply_feature_metadata_passthrough(target_df.copy(), source_df)

    assert result["tumor_ratio"].tolist() == [0.75, 0.25]
    assert result["is_Presence_Absence_Marker"].tolist() == [True, False]
    assert result["Feature_Filter_Keep_Reasons"].tolist() == ["mnar|ratio_rescue", "stable"]
    assert result["Imputation_Tag_Reasons"].tolist() == ["low_overall_detection", ""]
    assert result["Detection_Profile"].tolist() == ["legacy_2", "legacy_1"]


def test_apply_feature_metadata_passthrough_fails_when_feature_identity_is_missing():
    source_df = pd.DataFrame(
        {
            "Mz/RT": ["F1"],
            "Feature_Filter_Keep_Reasons": ["stable"],
        }
    )
    target_df = pd.DataFrame({"Mz/RT": ["F2"], "Sample_A": [1.0]})

    with pytest.raises(ValueError, match="metadata pass-through"):
        apply_feature_metadata_passthrough(target_df, source_df)
