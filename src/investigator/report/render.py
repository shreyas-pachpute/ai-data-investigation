"""Renders an InvestigationTrace to JSON (full trace, for observability and
the grounding/eval machinery) and Markdown (human-readable report).

PROJECT.md Section 18: "a root-cause report without its full evidence trail
is far less useful ... than one with it" — the JSON trace, not just the
final report text, is treated as the primary artifact.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from investigator.agent.loop import InvestigationTrace


def trace_to_dict(trace: InvestigationTrace) -> dict:
    context = trace.context
    return {
        "run_id": trace.run_id,
        "target_date": trace.target_date,
        "metric_name": trace.metric_name,
        "context": {
            "metric_definition": context.metric_definition,
            "metric_owner": context.metric_owner,
            "anomaly": dataclasses.asdict(context.anomaly),
            "recent_values": context.recent_values,
            "pipeline_runs_window": context.pipeline_runs_window,
            "schema_changes_window": context.schema_changes_window,
        },
        "hypotheses": [h.model_dump(mode="json") for h in trace.hypotheses],
        "queries": [dataclasses.asdict(q) for q in trace.queries],
        "verdicts": [dataclasses.asdict(v) for v in trace.verdicts],
        "final_report": trace.final_report.model_dump(mode="json"),
        "grounding_violations": trace.grounding_violations,
        "iterations_used": trace.iterations_used,
        "llm_call_count": trace.llm_call_count,
        "llm_prompt_tokens": trace.llm_prompt_tokens,
        "llm_output_tokens": trace.llm_output_tokens,
    }


def render_markdown(trace: InvestigationTrace) -> str:
    report = trace.final_report
    lines = [
        f"# Root-Cause Investigation Report — {trace.metric_name} on {trace.target_date}",
        "",
        f"**Run ID:** {trace.run_id}",
        f"**Conclusion category:** {report.conclusion_category.value}",
        f"**Confidence:** {report.confidence.value} ({report.confidence_score:.2f})",
        f"**Investigation complete:** {report.investigation_complete}",
        "",
        "## Conclusion",
        report.conclusion_summary,
        "",
        "## Evidence",
    ]
    if not report.evidence:
        lines.append("_No evidence cited._")
    for ev in report.evidence:
        lines.append(f"- (query_id={ev.query_id}) {ev.finding}")

    lines += ["", "## Hypotheses Ruled Out"]
    if not report.ruled_out:
        lines.append("_None._")
    for r in report.ruled_out:
        lines.append(f"- **{r.hypothesis_id}**: {r.description} — _{r.reason}_")

    lines += ["", "## Full Investigation Trail"]
    for h in trace.hypotheses:
        lines.append(f"### [{h.hypothesis_id}] {h.description}")
        lines.append(f"- category: {h.category.value}, prior: {h.prior_likelihood.value}, final status: {h.status.value}")
        for q in [q for q in trace.queries if q.hypothesis_id == h.hypothesis_id]:
            v = next((v for v in trace.verdicts if v.query_id == q.query_id), None)
            lines.append(f"  - **query_id={q.query_id}** ({q.purpose})")
            lines.append(f"    ```sql\n    {q.executed_sql}\n    ```")
            if v:
                lines.append(f"    verdict: {v.verdict} — {v.reasoning}")

    lines += [
        "",
        "## Observability",
        f"- Iterations used: {trace.iterations_used}",
        f"- LLM calls: {trace.llm_call_count}",
        f"- Prompt tokens: {trace.llm_prompt_tokens}, Output tokens: {trace.llm_output_tokens}",
        f"- Grounding violations: {trace.grounding_violations or 'none'}",
    ]
    return "\n".join(lines)


def save_run(trace: InvestigationTrace, runs_dir: Path) -> Path:
    run_dir = runs_dir / trace.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trace.json").write_text(json.dumps(trace_to_dict(trace), indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_markdown(trace), encoding="utf-8")
    return run_dir
