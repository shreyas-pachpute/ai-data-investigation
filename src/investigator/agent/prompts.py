"""Prompt templates for each LLM call in the investigation loop.

Kept as plain functions returning strings (not a template engine) since
there are only four call sites and each has a distinct, small shape.
"""

from __future__ import annotations

from investigator.context.gather import InvestigationContext

WAREHOUSE_SCHEMA_DESCRIPTION = """\
orders(order_id INTEGER, order_date TEXT 'YYYY-MM-DD', region TEXT ['NA','EMEA','APAC'],
       segment TEXT ['Enterprise','SMB','Consumer'], channel TEXT ['Web','Mobile','Partner'],
       quantity INTEGER, unit_price REAL, revenue REAL)
pipeline_runs(run_id INTEGER, pipeline_name TEXT, run_date TEXT 'YYYY-MM-DD',
              status TEXT ['success','failed','partial'], rows_processed INTEGER, error_message TEXT)
schema_changes(change_id INTEGER, table_name TEXT, change_date TEXT 'YYYY-MM-DD', description TEXT)
"""

SYSTEM_INSTRUCTION = """\
You are a rigorous data analyst investigating why a business metric changed.
You form specific, testable hypotheses and check each one against real
warehouse data before drawing any conclusion. You never assert a claim your
own query results don't actually support. You explicitly distinguish a
genuine data-pipeline problem from a genuine business change from expected
seasonal variation from a metric-definition change — these are different
root causes with different owners. When evidence is weak or contradictory,
you say so honestly rather than forcing a confident-sounding answer."""


def _context_block(context: InvestigationContext) -> str:
    recent = "\n".join(f"  {d}: {v:,.2f}" for d, v in context.recent_values)
    pipeline = "\n".join(
        f"  run_id={r[0]} pipeline={r[1]} date={r[2]} status={r[3]} rows={r[4]} error={r[5]}"
        for r in context.pipeline_runs_window
    ) or "  (none in window)"
    schema = "\n".join(
        f"  change_id={c[0]} table={c[1]} date={c[2]} desc={c[3]}"
        for c in context.schema_changes_window
    ) or "  (none in window)"

    return f"""\
Metric under investigation: {context.metric_name}
Definition (authoritative, from the metrics catalog): {context.metric_definition}

Anomaly detected on {context.anomaly.metric_date}:
  observed value: {context.anomaly.value:,.2f}
  expected (same-weekday baseline mean): {context.anomaly.baseline_mean:,.2f}
  z-score: {context.anomaly.zscore:.2f}  direction: {context.anomaly.direction}

Recent daily values (last 14 days, deterministically pulled, not queried by you):
{recent}

Pipeline run history near this date (deterministically pulled):
{pipeline}

Schema-change history near this date (deterministically pulled):
{schema}

Warehouse schema available to you via the run_sql_query tool:
{WAREHOUSE_SCHEMA_DESCRIPTION}"""


def hypothesis_generation_prompt(context: InvestigationContext) -> str:
    return f"""\
{_context_block(context)}

Generate 3 to 5 specific, testable candidate hypotheses for why this metric
deviated from its expected baseline. Cover distinct root-cause categories
where plausible (data_quality_issue, genuine_business_change,
seasonal_expected_variation, definitional_change) — do not propose multiple
near-duplicate hypotheses in the same category. Each hypothesis must be
concrete enough that a single SQL query against the warehouse schema above
could meaningfully support or contradict it. Assign each a prior_likelihood
based on how well it fits the shape of this specific anomaly (magnitude,
direction, and what the pipeline/schema context above already suggests)."""


def query_proposal_prompt(
    context: InvestigationContext, hypothesis_description: str, hypothesis_category: str
) -> str:
    return f"""\
{_context_block(context)}

You are testing this specific hypothesis:
  category: {hypothesis_category}
  hypothesis: {hypothesis_description}

Propose exactly one read-only SQL SELECT query against the warehouse schema
above that would most efficiently support or contradict this hypothesis.
Prefer aggregation (GROUP BY / SUM / COUNT) over raw row dumps. Filter to
relevant dates and dimensions rather than scanning everything. Do not
propose a query you've already run for this investigation with the same
intent."""


def verdict_prompt(
    context: InvestigationContext,
    hypothesis_description: str,
    hypothesis_category: str,
    sql: str,
    query_purpose: str,
    result_text: str,
) -> str:
    return f"""\
{_context_block(context)}

Hypothesis being tested:
  category: {hypothesis_category}
  hypothesis: {hypothesis_description}

Query run to test it (purpose: {query_purpose}):
{sql}

Query result:
{result_text}

Based ONLY on this result (plus the context above), decide whether the
evidence supports, contradicts, or is inconclusive for this hypothesis.
Set new_status to 'confirmed' only if the evidence is genuinely strong and
specific — not merely consistent. Set it to 'ruled_out' if the evidence
clearly contradicts the hypothesis. Otherwise 'testing' or 'inconclusive'.
If this result reveals a more specific or different hypothesis worth
testing next, set refined_hypothesis; otherwise leave it unset."""


def final_report_prompt(context: InvestigationContext, trace_summary: str) -> str:
    return f"""\
{_context_block(context)}

Full investigation trace (every hypothesis tested, every query run, every
verdict reached):
{trace_summary}

Write the final investigation report. Requirements:
- conclusion_category and conclusion_summary must be the single best-supported
  explanation, or 'inconclusive' if nothing was well-supported.
- Every item in `evidence` MUST cite a query_id that actually appears in the
  trace above — never invent or reference a query that wasn't run.
- List every hypothesis that was tested and ruled out in `ruled_out`, with
  the specific reason — this is not optional scratch work, it is part of
  the report's value.
- confidence_score must genuinely reflect evidence strength: a single
  suggestive query result is not the same as multiple corroborating ones.
  Do not default to high confidence.
- If the investigation did not reach a clear, well-evidenced answer, set
  investigation_complete to false and say so plainly in conclusion_summary
  rather than forcing a confident-sounding conclusion."""
