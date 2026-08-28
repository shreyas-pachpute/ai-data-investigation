"""Regression/eval harness (PROJECT.md Sections 14 & 17).

Runs the full investigation loop against every curated incident and reports
root-cause accuracy, confidence calibration, query efficiency, grounding
pass rate, and total LLM cost. With only four curated incidents this is a
demonstration of the calibration *methodology*, not a statistically
powered calibration study — that caveat is surfaced in the printed output
rather than hidden, since an overstated metric here would be exactly the
kind of "confidently wrong" failure this project is designed to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from investigator.agent.loop import InvestigationTrace, run_investigation
from investigator.config import Config
from investigator.eval.incidents import CURATED_INCIDENTS, GroundTruthIncident
from investigator.report.render import save_run


@dataclass
class IncidentEvalResult:
    incident: GroundTruthIncident
    trace: InvestigationTrace
    correct: bool


@dataclass
class EvalSummary:
    results: list[IncidentEvalResult]
    incomplete_reason: str | None = None

    @property
    def accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.correct) / len(self.results)

    @property
    def grounding_pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if not r.trace.grounding_violations) / len(self.results)

    @property
    def avg_queries_per_investigation(self) -> float:
        if not self.results:
            return 0.0
        return sum(len(r.trace.queries) for r in self.results) / len(self.results)

    @property
    def total_llm_calls(self) -> int:
        return sum(r.trace.llm_call_count for r in self.results)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(r.trace.llm_prompt_tokens for r in self.results)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.trace.llm_output_tokens for r in self.results)

    def calibration_breakdown(self) -> dict[str, tuple[int, int]]:
        """confidence bucket -> (correct_count, total_count)."""
        buckets: dict[str, tuple[int, int]] = {}
        for r in self.results:
            bucket = r.trace.final_report.confidence.value
            correct, total = buckets.get(bucket, (0, 0))
            buckets[bucket] = (correct + (1 if r.correct else 0), total + 1)
        return buckets


def run_eval(
    config: Config, save_runs: bool = True, incidents: list[GroundTruthIncident] | None = None
) -> EvalSummary:
    from investigator.agent.llm import DailyQuotaExhausted

    results: list[IncidentEvalResult] = []
    for incident in incidents or CURATED_INCIDENTS:
        try:
            trace = run_investigation(config, incident.target_date)
        except DailyQuotaExhausted as exc:
            return EvalSummary(results=results, incomplete_reason=str(exc))
        correct = trace.final_report.conclusion_category == incident.expected_category
        results.append(IncidentEvalResult(incident=incident, trace=trace, correct=correct))
        if save_runs:
            save_run(trace, config.runs_dir)
    return EvalSummary(results=results)
