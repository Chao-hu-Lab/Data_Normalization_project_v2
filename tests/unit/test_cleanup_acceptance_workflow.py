from scripts.run_cleanup_acceptance_workflow import _result_to_dict

from metabolomics.utils.results import ProcessingResult, WorkflowOutcome


def test_result_manifest_preserves_workflow_outcome():
    result = ProcessingResult(
        file_path="C:/input.xlsx",
        output_path="C:/input.xlsx",
        metabolites=10,
        samples=5,
        status=WorkflowOutcome.SKIPPED,
        reason="insufficient_good_istd",
    )

    manifest = _result_to_dict(result)

    assert manifest["status"] == "skipped"
    assert manifest["reason"] == "insufficient_good_istd"
