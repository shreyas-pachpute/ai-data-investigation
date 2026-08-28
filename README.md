# AI Data Investigation & Root-Cause Agent

## Implementation Status (MVP)

The design below is implemented under `src/investigator/`. What exists:

- A synthetic SQLite warehouse (`orders`, `pipeline_runs`, `schema_changes`, `metrics_catalog`) with 15 months of daily e-commerce data and four ground-truth-labeled incidents injected (a pipeline failure, a genuine targeted business spike, a broad-based seasonal event, and a metric-definition change).
- Deterministic anomaly detection (same-weekday z-score — not an LLM step, fully unit-tested).
- A real cyclic investigation agent (hand-rolled bounded loop, not a fixed pipeline) using Gemini (`gemini-2.5-flash-lite`): hypothesize → propose a SQL query → execute it through a guardrailed read-only tool → evaluate the verdict → refine → repeat, until confident or budget-exhausted.
- A guardrailed SQL tool: single-`SELECT`-only, keyword-blocklisted, table-whitelisted, row-capped, wall-clock query timeout.
- An automated evidence-grounding validator (every citation in the final report must reference a query that actually ran).
- A 4-incident regression/eval suite measuring root-cause accuracy, confidence calibration, query efficiency, and cost.

### Setup

```bash
python -m venv .venv
./.venv/Scripts/activate         # or source .venv/bin/activate on macOS/Linux
pip install -e .
# add GEMINI_API_KEY=... to a local .env (gitignored)
```

### Usage

```bash
python -m investigator.cli seed                          # build the synthetic warehouse
python -m investigator.cli detect                        # deterministic anomaly detection, no LLM calls
python -m investigator.cli investigate --date 2025-04-15  # run one investigation
python -m investigator.cli eval                          # full 4-incident regression suite
python -m investigator.cli eval --only genuine_spike      # run a subset (useful under a tight API quota)
pytest tests/                                             # guardrail/detection/grounding tests, zero API cost
```

### Verified so far

Running on a free-tier Gemini key (20 requests/day for `gemini-2.5-flash-lite`), so the full eval suite is being run incrementally across days rather than in one shot:

- All 22 deterministic tests pass.
- `pipeline_failure` incident (2025-04-15): agent correctly concluded `data_quality_issue` at high confidence, citing the NA-region revenue collapse and the failed ingestion run, in 4 LLM calls; evidence grounding passed.
- Remaining incidents (`genuine_spike`, `seasonal_black_friday`, `definitional_change`) pending next quota reset.

## 1. One-Sentence Explanation

This is an AI system that investigates "why did this number change" questions the way a good data analyst would — forming a hypothesis, checking it against real data, and either confirming or ruling it out — instead of guessing an answer.

## 2. The Business Problem

Every data-driven organization gets some version of the same question, constantly: "why did revenue drop 12% this month," "why does this dashboard suddenly look wrong," "which pipeline caused this metric to break." Answering these well requires a genuinely investigative process — checking whether it's a real business change or a data-quality issue, checking which segment or dimension the change is concentrated in, checking recent pipeline runs and schema changes, and comparing against historical patterns — and a skilled data analyst or analytics engineer can do this, but it consumes hours of specialized time per incident, and the same kind of investigation gets repeated across the organization by whoever happens to notice a metric looks off.

Companies address this today with dashboards and alerting (which tell you *that* something changed, rarely *why*), data-quality monitoring tools (which catch some classes of pipeline failure but not business-driven anomalies), and, dominantly, ad hoc analyst investigation triggered whenever someone with enough concern and access asks. The pain concentrates around the gap between "the number moved" (usually detected quickly) and "here's the confirmed reason" (usually slow, because it requires a skilled person to manually run a sequence of exploratory queries whose next step depends on what the last one revealed).

The cost is analyst/analytics-engineering time spent on investigation that's often structurally similar across incidents even though the specific cause differs each time, and — more consequentially — slow root-cause time on business-critical anomalies, where a delay in understanding "why" directly delays the decision or fix that depends on it. If nothing changes, this scales with the number of tracked metrics and the size of the data organization's stakeholder base — more metrics and more people who can ask "why" means more investigation demand than a data team can keep up with by hand.

## 3. Who Would Use This?

- **Data Analyst / Analytics Engineer:** Wants investigation grunt work (running the first several exploratory queries, checking obvious candidate explanations) done automatically, so their time goes to the genuinely hard, ambiguous cases.
- **Business stakeholder (product manager, finance, marketing):** Wants a fast, evidence-backed answer to "why did this change" without needing to file a ticket and wait for analyst bandwidth.
- **Data Platform / Data Engineering Lead:** Wants pipeline-related root causes (a broken job, a schema change, a late-arriving data source) surfaced quickly and distinguished clearly from genuine business-driven changes.
- **Executive (indirect, connects to Project 12):** Wants confidence that a reported metric change has a real, evidence-backed explanation before making a decision based on it.

## 4. Current Process Without AI

```
Someone notices a metric looks wrong or has changed unexpectedly
 → Files a request to the data team, or a data team member notices independently
 → Analyst manually forms an initial hypothesis (seasonality? a specific segment? a broken pipeline?)
 → Analyst runs exploratory SQL queries to test the hypothesis
 → If wrong, analyst forms a new hypothesis and repeats — this loop continues until a real cause is found
 → Analyst manually checks recent pipeline run logs and schema-change history if a data-quality cause is suspected
 → Analyst writes up findings, often informally (a Slack message or a one-off doc), rarely captured systematically
 → Investigation knowledge (what caused past anomalies) rarely gets reused for the next similar incident
```

The core loop — hypothesize, query, evaluate, repeat — is exactly the kind of iterative, discovery-dependent process that's slow because each step depends on what the last one revealed, and it's repeated from scratch for nearly every incident, even structurally similar ones.

## 5. Proposed AI-Powered Process

```
Anomaly detected (deterministic monitoring/alerting) or a stakeholder asks a "why did X change" question
 ↓
Deterministic context gathering: pull the metric's definition, recent values, relevant dimensions,
   and recent pipeline run history — known, structured facts, not reasoning
 ↓
Agent investigation loop:
   generate candidate hypotheses (data-quality issue vs. genuine business change vs. definitional/pipeline change)
   → test each hypothesis against warehouse data via SQL queries
   → rule out or confirm, refine hypotheses based on what's found
   → repeat until a well-evidenced explanation emerges or investigation budget is exhausted
 ↓
Agent produces a root-cause report: the most likely explanation, the evidence supporting it,
   hypotheses that were tested and ruled out, and confidence level
 ↓
Analyst/stakeholder reviews the report and evidence (not just the conclusion)
 ↓
For anything suggesting a genuine data-pipeline problem, routed to data engineering; for a business-driven
   change, routed to the relevant business stakeholder — either way, no automated corrective action is taken
```

## 6. What the AI Actually Does

**Reasoning:** Generates plausible candidate hypotheses for why a metric changed, and decides which to test first based on prior likelihood and ease of checking — genuine investigative judgment.

**Retrieval:** Queries the data warehouse, pipeline run logs, and schema-change history needed to test each hypothesis.

**Analysis:** Evaluates query results against each hypothesis, determining whether the evidence supports, contradicts, or is inconclusive for it.

**Decision support:** Presents the most likely explanation with its supporting evidence and confidence level, and explicitly lists what was ruled out — it does not present a single answer without showing its work.

**Tool usage:** Runs SQL queries against the warehouse, checks pipeline orchestration logs and schema-change history.

**Communication:** Produces a structured investigation report — it does not take any corrective action on data or pipelines itself.

**Validation:** Every claim in the final report traces to a specific query result — the agent doesn't assert a conclusion its own queries didn't actually support.

**What the AI does NOT do:** It does not modify data, rerun or fix pipelines, or change dashboard/metric definitions. It does not present a hypothesis as confirmed without evidence, and it does not hide the hypotheses it tried and ruled out — the negative results are part of the value of the report, not discarded scratch work.

## 7. Where AI Is Used

AI is good at exactly the hypothesis-generation-and-testing loop this problem requires: proposing plausible candidate explanations based on the shape of the anomaly (concentrated in one segment vs. broad-based, sudden vs. gradual), deciding which SQL query would most efficiently test a given hypothesis, and adapting the investigation path based on what each query reveals — genuinely open-ended reasoning that cannot be scripted as a fixed sequence because the right next query depends entirely on the last one's result. This is one of the clearest, least-debatable justifications for an agent loop (as opposed to a workflow) anywhere in this portfolio.

Deterministic software should handle initial anomaly detection (statistical threshold/change-point detection on monitored metrics — a well-understood, testable computation, not something that benefits from LLM reasoning) and the actual SQL query execution and result-parsing (the agent decides *what* to query; the query execution itself is normal, reliable database interaction, not something the model does probabilistically).

## 8. Agent vs Workflow vs Normal Software

- **Normal software:** The data warehouse itself, the anomaly-detection/alerting system, pipeline orchestration and logging, the analyst-facing report UI.
- **Deterministic workflow:** Anomaly detection (is this metric outside its normal statistical range) is a fixed computation, not agentic — this triggers the investigation but isn't part of it.
- **AI agent:** The investigation itself — hypothesize, query, evaluate, refine — is the textbook case for an agent loop in this entire portfolio: the number and order of queries cannot be predetermined, because each query's result determines what's investigated next. Research Notes Section 4 uses almost exactly this example ("find out why revenue dropped has no fixed script") as the canonical justification for agentic architecture, and this project is the direct implementation of that principle.
- **Multi-agent system:** Justified in a specific, bounded way: running multiple **hypothesis-testing threads in parallel** (each investigating one candidate explanation independently, e.g., one thread checking for a pipeline issue while another checks for a genuine segment-level business change) can meaningfully reduce time-to-answer for time-sensitive incidents — a parallelism justification, not a role-decomposition one. A single sequential investigation agent is a perfectly valid and simpler MVP choice; parallel hypothesis threads are a scale/latency optimization to consider once the sequential version proves the reasoning quality is sound.

## 9. Agent Roles

**Root-Cause Investigation Agent:** "Given an anomaly (a metric, its context, and how it deviated from expectation), generate and test hypotheses against the warehouse and pipeline data until a well-evidenced explanation is found or the investigation budget is exhausted, and report the full trail — not just the conclusion." At scale, this can spawn parallel **Hypothesis Threads**, each investigating one candidate explanation, with a coordinating layer that decides when enough evidence exists to converge on a conclusion — a legitimate multi-agent pattern here specifically because the hypotheses are genuinely independent lines of investigation.

## 10. Tools the AI Needs

In business terms: the data warehouse (query access), metric/metadata definitions (so the agent knows what a given metric actually measures and how it's computed), pipeline orchestration logs and run history, and schema-change history.

Technically: a read-only SQL query tool against the warehouse (with query cost/row-limit guardrails to prevent runaway expensive queries), a metrics-catalog/semantic-layer connector if one exists (so the agent works from an authoritative metric definition rather than reverse-engineering one from raw tables), a pipeline-orchestrator log connector (Airflow/dbt-style run history), and a schema-change/version-history connector.

## 11. MCP Opportunities

The warehouse query tool, metrics catalog, and pipeline-log connector are strong MCP candidates, and this project shares the warehouse-query connector directly with Project 07's transaction-level investigation needs — a clear reuse case. Warehouse query execution is naturally a MCP **Tool** (the agent decides what to query, iteratively, based on findings), while the metric catalog/semantic-layer definition for the specific metric under investigation is better modeled as a **Resource** loaded deterministically at the start of an investigation, so the agent starts from an authoritative definition rather than guessing at one. What should be scoped carefully rather than excluded outright: query cost and row-limit guardrails on the SQL tool itself, since an agent iterating through many exploratory queries against a large warehouse could otherwise generate meaningful, unplanned compute cost — this is a resource-management safety concern specific to this project, distinct from the write-access safety concerns dominant elsewhere in this portfolio.

## 12. Human-in-the-Loop

**Low-risk (automatic):** Anomaly detection, running read-only exploratory queries, generating and testing hypotheses, producing the investigation report.

**Medium-risk (requires review before broad distribution):** A root-cause report that will be shared widely (e.g., surfaced to executives or a business unit) is reviewed by an analyst before wide distribution, even though generating it was fully automatic — this is a lighter-weight gate than most other projects in this portfolio, appropriate given the read-only, non-action nature of the work, but still present because a wrong root-cause conclusion presented with false confidence to a decision-maker is a real cost.

**High-risk (must never happen automatically):** Any corrective action — rerunning or modifying a pipeline, changing a metric definition, altering data. This system investigates and reports; it never acts on what it finds. Even where the root cause is clearly a specific, fixable pipeline bug, remediation is a data-engineering action taken by a human, not something this agent does.

## 13. Business Value

The clearest measurable driver is time-to-root-cause for flagged anomalies, measurable directly by comparing agent-assisted investigation time against the historical analyst-only baseline for comparable incident types. A second driver is analyst time reclaimed from routine investigation, freeing capacity for higher-value analysis work — measurable via time tracking. A less immediately quantifiable but real driver is faster business decision-making on issues that were previously stuck waiting on root-cause clarity; this should be tracked qualitatively via stakeholder feedback initially, with a defined KPI (Section 14) once enough incident volume accumulates to measure it rigorously.

## 14. Success Metrics

- **Time-to-root-cause**, compared to the manual analyst baseline, segmented by anomaly type (data-quality vs. business-driven).
- **Root-cause accuracy** — on a curated set of historical incidents with known confirmed causes, does the agent identify the correct one?
- **Evidence quality** — human (analyst) rating of whether the cited evidence actually supports the stated conclusion, sampled regularly.
- **Investigation efficiency** (trajectory evaluation) — number of queries run to reach a conclusion, compared against an efficient-analyst benchmark, catching redundant or irrelevant query patterns.
- **Confidence calibration** — when the agent reports high confidence, is it actually right more often than when it reports low confidence? (A poorly calibrated confidence score is arguably worse than no confidence score at all.)
- **Query cost per investigation**, tracked against warehouse compute budget.

## 15. Failure Scenarios

- **Wrong root cause confidently asserted:** the single most damaging failure mode for this project — mitigated by mandatory evidence citation for every claim, by confidence calibration evaluation (Section 14), and by explicitly reporting ruled-out hypotheses so a reviewer can see the reasoning, not just trust the conclusion.
- **Incomplete investigation (budget exhausted without a clear answer):** the agent should report this honestly ("investigated X, Y, Z; no conclusive cause found; here's what would need checking next") rather than forcing a confident-sounding but weakly-supported conclusion.
- **Runaway query cost:** an iterative investigation generates unexpectedly expensive warehouse queries — mitigated by hard query-cost/row-limit guardrails enforced at the tool layer, not left to the model's own restraint.
- **Stale metric definition:** investigating against an outdated understanding of what a metric measures — mitigated by pulling the metric definition from an authoritative catalog at investigation start, not from the model's general knowledge or a cached assumption.
- **Data-quality issue masquerading as a business signal (or vice versa):** exactly the kind of ambiguous case the hypothesis-testing loop exists to resolve — the system's value is precisely in distinguishing these, and evaluation should specifically test this distinction, not just overall accuracy.
- **Tool failure:** warehouse or log system unavailable mid-investigation — the agent should report a partial, clearly-flagged-incomplete investigation rather than proceeding on stale or assumed data.

## 16. Safety and Security

The warehouse query tool is strictly read-only — this agent has no write, no data-modification, and no pipeline-execution capability of any kind, which substantially bounds the security risk profile of this project compared to several others in this portfolio. Query access is scoped to what the requesting analyst/stakeholder's role would already permit (no broader access than a human analyst would have), preserving existing data-governance boundaries (e.g., row-level security on sensitive tables applies identically whether a human or the agent is querying). Query cost/rate limits protect against both runaway expense and a form of resource-exhaustion risk if the investigation loop misbehaves. All queries run and their results are logged as part of the investigation trace, both for the evidence-citation requirement (Section 6) and for security audit (what data was accessed, by which investigation, for what purpose). Because this project deals with internal data rather than external/untrusted input in the same way several other projects do, prompt-injection risk is lower but not zero — data itself (e.g., a freeform text field containing adversarial content) should still be treated cautiously if the agent's investigation ever touches unstructured internal data sources.

## 17. Evaluation

- **Root-cause accuracy** against a curated historical incident set with confirmed causes — the central evaluation metric.
- **Trajectory evaluation:** does the agent investigate efficiently, testing genuinely distinguishing hypotheses rather than redundant or low-information queries (Research Notes Section 25)?
- **Evidence-grounding check:** does every claim in the final report trace to an actual query result, automatically verifiable?
- **Confidence calibration:** statistical comparison of stated confidence against actual correctness rate across many investigations.
- **Human evaluation:** analyst rating of report usefulness and evidence quality, sampled regularly.
- **Regression suite:** a fixed set of historical incident scenarios (replayable against a snapshot or synthetic warehouse) re-run on every prompt/tool change.
- **Cost and latency** per investigation, including query compute cost specifically.

## 18. Observability

Track, per investigation: every hypothesis generated, every query run and its result, which hypotheses were confirmed/ruled out and why, the final conclusion and its confidence, query cost and latency, and the human reviewer's eventual assessment. This is the core value-delivery mechanism of this specific project, not just an operational nicety — a root-cause report without its full evidence trail is far less useful and far less trustworthy than one with it, since the entire point is "don't just tell me the answer, show me it's actually supported." Track root-cause-accuracy and confidence-calibration trends over time as the primary quality dashboard, and track query-cost trends to catch any investigation pattern becoming unexpectedly expensive before it becomes a real infrastructure cost problem.

## 19. Technology Options

**LangGraph:** *Why:* this project is close to a canonical use case for LangGraph's design center — a cyclic, stateful investigation loop (hypothesize → query → evaluate → refine → repeat) with persisted state across potentially many iterations, exactly the graph-with-cycles pattern LangGraph is built for (Research Notes Section 7). *Why not:* unnecessary if the investigation loop is kept intentionally shallow (a fixed small number of hypothesis-test iterations) in the MVP. *Alternative:* a simpler bounded agent loop for the MVP, adopting LangGraph as investigation depth and the parallel-hypothesis-thread pattern (Section 8) are added.

**A SQL-execution tool with strict guardrails (not a specific framework, but a critical design element):** *Why:* the entire investigation depends on safe, bounded, read-only query execution — this needs careful engineering (query cost estimation before execution, row limits, timeout enforcement) regardless of which agent framework sits on top of it. *Why not skip guardrails:* an unconstrained SQL tool given to an iterating agent is a real cost and stability risk. *Alternative:* n/a — this is a required design element, not an optional technology choice.

**MCP:** *Why:* the warehouse-query and metrics-catalog connectors are directly reusable by Project 07's financial investigation needs (Section 11) — a genuine cross-project reuse case. *Why not:* unnecessary for a single-consumer, standalone prototype. *Alternative:* direct database driver integration if reuse isn't imminent.

**Semantic layer / metrics catalog tooling (e.g., a dbt-style metrics layer):** *Why:* gives the agent an authoritative metric definition to investigate against, rather than reverse-engineering meaning from raw table structure — significantly improves reliability. *Why not:* not every organization has one built; without it, metric-definition context has to be supplied more manually (e.g., structured documentation). *Alternative:* a curated internal metrics-documentation source as a lighter-weight substitute.

**DSPy:** *Why:* once a labeled historical-incident evaluation set exists, optimizing the hypothesis-generation step against real accuracy data could improve investigation quality meaningfully. *Why not initially:* no evaluation dataset exists at MVP stage. *Alternative:* manual prompt iteration early.

## 20. Proposed Architecture

```
Anomaly Detection (deterministic, statistical) or Stakeholder "Why" Question
        |
  Context Gathering (deterministic): metric definition, recent values, pipeline run history
        |
  Root-Cause Investigation Agent (LangGraph, cyclic hypothesize-query-evaluate loop)
        |
   +------------------------------+
   |        Tool Layer (MCP)      |
   +------------------------------+
   |         |            |       |
 Warehouse   Metrics     Pipeline  Schema-Change
 Query       Catalog     Logs      History
 (read-only, (MCP)       (MCP)     (MCP)
  cost-guarded)
        |
  Investigation Report (conclusion + full evidence trail + ruled-out hypotheses)
        |
  Analyst/Stakeholder Review -> Routed to Data Eng (if pipeline issue) or Business Owner (if genuine change)
        |
  Evaluation & Observability Layer
```

## 21. MVP

The smallest version that proves value: for a single, well-understood, high-visibility metric (e.g., daily revenue), a bounded investigation agent (a fixed small number of hypothesis-test iterations, sequential, no parallel threads yet) that, given a detected anomaly, checks the most common candidate explanations (data-pipeline issue, specific-segment concentration, known seasonality) against warehouse data and produces an evidence-backed report for analyst review. This validates hypothesis quality and evidence-grounding before expanding metric coverage or adding investigation depth/parallelism.

## 22. Future Version

MVP → expand metric coverage across the organization's key tracked metrics → add parallel hypothesis-thread investigation for faster time-to-answer on urgent incidents → add DSPy-style hypothesis-generation optimization once labeled incident volume justifies it → add a self-service interface so any stakeholder can ask a "why did X change" question directly, not just respond to detected anomalies → build a historical-incident knowledge base so the agent can reference "this looks similar to an incident three months ago caused by Y" as an additional hypothesis-generation signal → connect toward Project 12's executive drill-down capability as a component that answers "why" questions surfaced at the executive level.

## 23. What Makes This Project Difficult?

Getting genuinely efficient hypothesis testing right is hard — a naive agent can burn many queries on low-information tests before finding the actually distinguishing one, and trajectory efficiency (Research Notes Section 25) matters as much as final-answer correctness here, both for cost and for time-to-answer. Confidence calibration is a subtle, important problem specific to this project: a system that's sometimes right and sometimes wrong is only genuinely useful if its confidence signal reliably tracks which is which, and that requires real calibration work, not just accuracy optimization. Building a rigorous evaluation set requires real historical incidents with confirmed causes, which are often not well-documented in most organizations today (the current process, per Section 4, produces mostly informal Slack write-ups) — part of implementing this well is establishing better incident-documentation discipline alongside the AI system itself. Query cost/performance engineering against a real production warehouse, under an iterating agent's unpredictable query patterns, is a genuine infrastructure engineering challenge distinct from the AI reasoning problem.

## 24. What I Would Demonstrate When Implementing It

A genuinely cyclic, stateful agent loop (not a disguised fixed pipeline) with real hypothesis generation and testing against a live data warehouse; strict, tested SQL-execution guardrails (cost/row/timeout limits); mandatory evidence citation with automated grounding checks; confidence calibration evaluation, not just raw accuracy; a parallel-hypothesis-thread pattern justified specifically by latency, not decorative multi-agent architecture; and an observability design that makes the full investigation trail — not just the conclusion — the primary deliverable.

## 25. Portfolio Story

"'Why did this metric change' is one of the purest examples of a task that genuinely needs an agent rather than a workflow — the right next query depends entirely on what the last one revealed, and no fixed script can capture that. I built the investigation as a real hypothesize-query-evaluate loop, and made the evidence trail itself the primary deliverable, not just the final conclusion — the report shows what was ruled out, not just what was confirmed, because that's what makes the conclusion actually trustworthy rather than just plausible-sounding. The metric I cared most about wasn't raw accuracy, it was confidence calibration: a system that's sometimes wrong is fine if it also reliably tells you when to trust it less, and that's a genuinely different (and harder) thing to get right than accuracy alone."

## 26. Questions a CTO Might Ask Me

1. How do you keep the agent from running excessively expensive queries against the warehouse?
2. Why is this an agent loop instead of a fixed diagnostic checklist for common anomaly types?
3. How do you evaluate root-cause accuracy without a large set of confirmed historical incidents?
4. What does confidence calibration actually mean here, and how would you measure it rigorously?
5. How do you prevent the agent from confidently asserting a wrong conclusion?
6. Why show ruled-out hypotheses in the report instead of just the final answer?
7. What's the latency profile for a time-sensitive incident, and how does parallel hypothesis-testing help?
8. How do you distinguish a genuine business signal from a data-quality artifact reliably?
9. What access-control model applies when the agent queries data a human analyst might not normally see?
10. How would this system behave differently investigating a slow, gradual drift versus a sudden spike?
11. What's your fallback when the investigation genuinely can't find a conclusive cause?
12. Why not let the agent also trigger the pipeline fix once it identifies a clear pipeline bug?
13. How do you avoid the agent re-deriving the same investigation for structurally similar recurring incidents?
14. What's the cost per investigation, and how does that compare to analyst time saved?
15. How do you validate the agent's query-writing correctness against your specific warehouse schema?

## 27. Research Sources

- [LangGraph vs LangChain 2026 — Spheron Blog](https://www.spheron.network/blog/langgraph-vs-langchain/)
- [LLM Agent Evaluation Metrics in 2026 — Confident AI](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide)
- [AI Agent Evaluation (2026): Metrics, Frameworks, and Production Failures — MorphLLM](https://www.morphllm.com/ai-agent-evaluation)
- [The 2026-07-28 Specification — Model Context Protocol Blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- See also [../RESEARCH_NOTES.md](../RESEARCH_NOTES.md) for full ecosystem sourcing.
