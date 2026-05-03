from metabolomics.gui import workflow
from metabolomics.processors import normalization
from metabolomics.utils import normalization_contract


def test_default_normalization_method_is_shared_by_gui_and_processor():
    assert normalization_contract.DEFAULT_NORMALIZATION_METHOD == "SpecNorm+PQN"
    assert workflow.DEFAULT_STEP3_METHOD is normalization_contract.DEFAULT_NORMALIZATION_METHOD
    assert normalization.DEFAULT_NORMALIZATION_METHOD is normalization_contract.DEFAULT_NORMALIZATION_METHOD


def test_step3_method_options_keep_specnorm_pqn_first():
    assert normalization_contract.STEP3_METHOD_OPTIONS == (
        ("SpecNorm+PQN", "SpecNorm+PQN"),
        ("PQN", "PQN"),
    )
    assert workflow.STEP3_METHOD_OPTIONS is normalization_contract.STEP3_METHOD_OPTIONS


def test_normalization_method_aliases_and_summary_sheet_names():
    assert normalization_contract.canonicalize_normalization_method(None) == "SpecNorm_PQN"
    assert normalization_contract.canonicalize_normalization_method("SpecNorm+PQN") == "SpecNorm_PQN"
    assert normalization_contract.canonicalize_normalization_method("SpecNorm PQN") == "SpecNorm_PQN"
    assert normalization_contract.canonicalize_normalization_method("PQN") == "PQN"
    assert normalization_contract.get_summary_sheet_name("SpecNorm+PQN") == "SpecNorm_PQN_summary"
    assert normalization_contract.get_summary_sheet_name("PQN") == "PQN_summary"
    assert normalization_contract.get_summary_sheet_name("CustomMethod") == "CustomMethod_summary"
