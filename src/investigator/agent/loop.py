"""The investigation agent: a genuinely cyclic hypothesize-query-evaluate-
refine loop. This is the core of the whole project (PROJECT.md Section 8) —
the number and order of queries is decided at runtime based on what each
query reveals, not fixed in advance.

Hypothesis *selection* (which untested hypothesis to test next) is done by
deterministic prior-likelihood ranking rather than an extra LLM call — this
is a genuine agentic-loop cost optimization (fewer calls, same behavior a
"test the most likely thing first" agent would produce) that matters given
the free-tier budget constraint, not a shortcut that changes what the loop
demonstrates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from investigator.agent.grounding import validate_grounding
from investigator.agent.llm import GeminiClient
from investigator.agent.prompts import (
    SYSTEM_INSTRUCTION,
    final_report_prompt,
    hypothesis_generation_prompt,
    query_proposal_prompt,
    verdict_prompt,
)
from investigator.agent.schemas import (
    FinalReport,
    Hypothesis,
    HypothesisGenerationOutput,
    HypothesisStatus,
    QueryProposal,
    VerdictOutput,
)
from investigator.config import Config
from investigator.context.gather import InvestigationContext, gather_context
from investigator.tools.sql_tool import QueryResult, execute_guardrailed_query

_LIKELIHOOD_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class QueryLogEntry:
    query_id: int
    hypothesis_id: str
    sql: str
    executed_sql: str
    purpose: str
    row_count: int
    limit_clamped: bool
    duration_ms: float
    error: str | None
    result_preview: str


@dataclass
class VerdictLogEntry:
    query_id: int
    hypothesis_id: str
    verdict: str
    reasoning: str
    new_status: str


@dataclass
class InvestigationTrace:
    run_id: str
    target_date: str
    metric_name: str
    context: InvestigationContext
    hypotheses: list[Hypothesis]
    queries: list[QueryLogEntry]
    verdicts: list[VerdictLogEntry]
    final_report: FinalReport
    grounding_violations: list[str]
    iterations_used: int
    llm_call_count: int
    llm_prompt_tokens: int
    llm_output_tokens: int


def _render_trace_summary(
    hypotheses: dict[str, Hypothesis],
    queries: list[QueryLogEntry],
    verdicts: list[VerdictLogEntry],
) -> str:
    lines: list[str] = []
    for h in hypotheses.values():
        lines.append(f"[{h.hypothesis_id}] ({h.category.value}, status={h.status.value}) {h.description}")
        related_queries = [q for q in queries if q.hypothesis_id == h.hypothesis_id]
        for q in related_queries:
            v = next((v for v in verdicts if v.query_id == q.query_id), None)
            lines.append(f"    query_id={q.query_id}: {q.sql}")
            lines.append(f"    purpose: {q.purpose}")
            lines.append(f"    result: {q.result_preview}")
            if v:
                lines.append(f"    verdict: {v.verdict} — {v.reasoning}")
    return "\n".join(lines)


def run_investigation(
    config: Config, target_date: str, metric_name: str = "daily_revenue"
) -> InvestigationTrace:
    context = gather_context(config, target_date, metric_name)
    client = GeminiClient(config)

    hyp_output: HypothesisGenerationOutput = client.generate_structured(
        SYSTEM_INSTRUCTION, hypothesis_generation_prompt(context), HypothesisGenerationOutput
    )
    hypotheses: dict[str, Hypothesis] = {
        h.hypothesis_id: h for h in hyp_output.hypotheses[: config.max_hypotheses]
    }

    queries: list[QueryLogEntry] = []
    verdicts: list[VerdictLogEntry] = []
    next_query_id = 1
    iterations_used = 0

    for _ in range(config.max_iterations):
        candidates = [
            h
            for h in hypotheses.values()
            if h.status in (HypothesisStatus.UNTESTED, HypothesisStatus.TESTING)
        ]
        if not candidates:
            break
        candidates.sort(key=lambda h: _LIKELIHOOD_RANK.get(h.prior_likelihood.value, 1))
        current = candidates[0]
        current.status = HypothesisStatus.TESTING
        iterations_used += 1

        proposal: QueryProposal = client.generate_structured(
            SYSTEM_INSTRUCTION,
            query_proposal_prompt(context, current.description, current.category.value),
            QueryProposal,
        )
        result: QueryResult = execute_guardrailed_query(config, proposal.sql)
        result_text = result.to_prompt_text(config.max_rows_in_prompt, config.max_cell_chars)

        query_id = next_query_id
        next_query_id += 1
        queries.append(
            QueryLogEntry(
                query_id=query_id,
                hypothesis_id=current.hypothesis_id,
                sql=proposal.sql,
                executed_sql=result.executed_sql,
                purpose=proposal.purpose,
                row_count=result.row_count,
                limit_clamped=result.limit_clamped,
                duration_ms=result.duration_ms,
                error=result.error,
                result_preview=result_text,
            )
        )

        verdict: VerdictOutput = client.generate_structured(
            SYSTEM_INSTRUCTION,
            verdict_prompt(
                context,
                current.description,
                current.category.value,
                proposal.sql,
                proposal.purpose,
                result_text,
            ),
            VerdictOutput,
        )
        verdicts.append(
            VerdictLogEntry(
                query_id=query_id,
                hypothesis_id=current.hypothesis_id,
                verdict=verdict.verdict,
                reasoning=verdict.reasoning,
                new_status=verdict.new_status.value,
            )
        )
        current.status = verdict.new_status

        if (
            verdict.refined_hypothesis is not None
            and len(hypotheses) < config.max_hypotheses
            and verdict.refined_hypothesis.hypothesis_id not in hypotheses
        ):
            hypotheses[verdict.refined_hypothesis.hypothesis_id] = verdict.refined_hypothesis

        if current.status == HypothesisStatus.CONFIRMED:
            break

    trace_summary = _render_trace_summary(hypotheses, queries, verdicts)
    final_report: FinalReport = client.generate_structured(
        SYSTEM_INSTRUCTION, final_report_prompt(context, trace_summary), FinalReport
    )

    executed_ids = {q.query_id for q in queries}
    grounding_violations = validate_grounding(final_report, executed_ids)

    return InvestigationTrace(
        run_id=uuid.uuid4().hex[:12],
        target_date=target_date,
        metric_name=metric_name,
        context=context,
        hypotheses=list(hypotheses.values()),
        queries=queries,
        verdicts=verdicts,
        final_report=final_report,
        grounding_violations=grounding_violations,
        iterations_used=iterations_used,
        llm_call_count=client.stats.call_count,
        llm_prompt_tokens=client.stats.total_prompt_tokens,
        llm_output_tokens=client.stats.total_output_tokens,
    )
