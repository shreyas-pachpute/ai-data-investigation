from investigator.agent.grounding import validate_grounding
from investigator.agent.schemas import (
    EvidenceCitation,
    FinalReport,
    PriorLikelihood,
    RootCauseCategory,
)


def _report(evidence_query_ids, category=RootCauseCategory.DATA_QUALITY_ISSUE):
    return FinalReport(
        conclusion_category=category,
        conclusion_summary="test",
        confidence=PriorLikelihood.HIGH,
        confidence_score=0.9,
        evidence=[EvidenceCitation(query_id=qid, finding="f") for qid in evidence_query_ids],
        ruled_out=[],
        investigation_complete=True,
    )


def test_grounded_report_passes():
    report = _report([1, 2])
    violations = validate_grounding(report, executed_query_ids={1, 2, 3})
    assert violations == []


def test_ungrounded_citation_flagged():
    report = _report([1, 99])
    violations = validate_grounding(report, executed_query_ids={1, 2, 3})
    assert len(violations) == 1
    assert "99" in violations[0]


def test_conclusive_report_with_no_evidence_flagged():
    report = _report([])
    violations = validate_grounding(report, executed_query_ids={1, 2})
    assert any("cites zero evidence" in v for v in violations)


def test_inconclusive_report_with_no_evidence_is_allowed():
    report = _report([], category=RootCauseCategory.INCONCLUSIVE)
    violations = validate_grounding(report, executed_query_ids={1, 2})
    assert violations == []
