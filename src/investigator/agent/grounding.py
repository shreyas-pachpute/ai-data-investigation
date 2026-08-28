"""Automated evidence-grounding check — deterministic, not LLM-judged.

PROJECT.md Section 17: "does every claim in the final report trace to an
actual query result, automatically verifiable?" This is the mechanism that
answers that question: it never trusts the model's own claim that a
citation is valid, it checks the citation against the actual trace.
"""

from __future__ import annotations

from investigator.agent.schemas import FinalReport


def validate_grounding(report: FinalReport, executed_query_ids: set[int]) -> list[str]:
    """Returns a list of grounding violations; empty means the report passed."""
    violations: list[str] = []

    if not report.evidence and report.conclusion_category.value != "inconclusive":
        violations.append(
            "Report reaches a non-inconclusive conclusion but cites zero evidence."
        )

    for item in report.evidence:
        if item.query_id not in executed_query_ids:
            violations.append(
                f"Evidence cites query_id={item.query_id}, which was never executed "
                f"in this investigation (executed ids: {sorted(executed_query_ids)})."
            )

    return violations
