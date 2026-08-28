"""CLI entry point: seed, detect, investigate, eval.

Run as `python -m investigator.cli <command>` from the project's src/ dir
(or `python -m investigator <command>` — see __main__.py).
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from investigator.config import load_config
from investigator.detection.anomaly import detect_all_anomalies
from investigator.eval.harness import run_eval
from investigator.report.render import render_markdown, save_run
from investigator.warehouse.seed import build_warehouse

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
console = Console()


@app.command()
def seed() -> None:
    """Build the synthetic warehouse (orders, pipeline_runs, schema_changes)."""
    config = load_config()
    summary = build_warehouse(config)
    console.print(f"[bold green]Warehouse built:[/] {config.warehouse_path}")
    console.print(f"  orders: {summary.orders_rows:,} rows")
    console.print(f"  pipeline_runs: {summary.pipeline_runs_rows:,} rows")
    console.print(f"  schema_changes: {summary.schema_changes_rows:,} rows")
    console.print(f"  date range: {summary.date_range[0]} to {summary.date_range[1]}")


@app.command()
def detect() -> None:
    """Run deterministic anomaly detection over daily_revenue; list flagged dates."""
    config = load_config()
    anomalies = detect_all_anomalies(config)
    if not anomalies:
        console.print("[yellow]No anomalies detected.[/]")
        raise typer.Exit()

    table = Table(title="Detected Anomalies (daily_revenue)")
    table.add_column("Date")
    table.add_column("Value", justify="right")
    table.add_column("Baseline Mean", justify="right")
    table.add_column("Z-score", justify="right")
    table.add_column("Direction")
    for a in anomalies:
        table.add_row(
            a.metric_date, f"{a.value:,.0f}", f"{a.baseline_mean:,.0f}",
            f"{a.zscore:.2f}", a.direction or "-",
        )
    console.print(table)


@app.command()
def investigate(
    date: str = typer.Option(..., "--date", help="YYYY-MM-DD anomaly date to investigate."),
    metric: str = typer.Option("daily_revenue", "--metric", help="Metric name in metrics_catalog."),
) -> None:
    """Run one full investigation for a given anomaly date."""
    from investigator.agent.llm import DailyQuotaExhausted
    from investigator.agent.loop import run_investigation

    config = load_config()
    console.print(f"[bold]Investigating {metric} on {date}...[/]")
    try:
        trace = run_investigation(config, date, metric)
    except DailyQuotaExhausted as exc:
        console.print(f"[bold red]Stopped: {exc}[/]")
        raise typer.Exit(code=1)
    run_dir = save_run(trace, config.runs_dir)

    report = trace.final_report
    console.print()
    console.print(f"[bold]Conclusion:[/] {report.conclusion_category.value}")
    console.print(f"[bold]Confidence:[/] {report.confidence.value} ({report.confidence_score:.2f})")
    console.print(f"[bold]Summary:[/] {report.conclusion_summary}")
    console.print(f"[bold]Queries run:[/] {len(trace.queries)}   [bold]LLM calls:[/] {trace.llm_call_count}")
    if trace.grounding_violations:
        console.print(f"[bold red]Grounding violations:[/] {trace.grounding_violations}")
    else:
        console.print("[bold green]Evidence grounding: passed[/]")
    console.print(f"\nSaved to: {run_dir}")


@app.command(name="eval")
def eval_cmd(
    only: str = typer.Option(
        None,
        "--only",
        help="Comma-separated incident_ids to run (default: all 4). "
        "Useful for spreading a run across a tight daily API quota.",
    ),
) -> None:
    """Run the curated incident regression suite and print metrics."""
    from investigator.eval.incidents import CURATED_INCIDENTS

    config = load_config()
    incidents = CURATED_INCIDENTS
    if only:
        wanted = {i.strip() for i in only.split(",")}
        incidents = [i for i in CURATED_INCIDENTS if i.incident_id in wanted]
        unknown = wanted - {i.incident_id for i in incidents}
        if unknown:
            console.print(f"[bold red]Unknown incident_id(s): {unknown}[/]")
            raise typer.Exit(code=1)

    console.print(f"[bold]Running regression suite against {len(incidents)} incident(s)...[/]\n")
    summary = run_eval(config, incidents=incidents)

    if summary.incomplete_reason:
        console.print(f"[bold red]Stopped early: {summary.incomplete_reason}[/]\n")
    if not summary.results:
        raise typer.Exit(code=1 if summary.incomplete_reason else 0)

    table = Table(title="Eval Results")
    table.add_column("Incident")
    table.add_column("Date")
    table.add_column("Expected")
    table.add_column("Predicted")
    table.add_column("Correct")
    table.add_column("Confidence", justify="right")
    table.add_column("Queries", justify="right")
    table.add_column("Grounded")
    for r in summary.results:
        table.add_row(
            r.incident.incident_id,
            r.incident.target_date,
            r.incident.expected_category.value,
            r.trace.final_report.conclusion_category.value,
            "[green]yes[/]" if r.correct else "[red]no[/]",
            f"{r.trace.final_report.confidence_score:.2f}",
            str(len(r.trace.queries)),
            "[green]yes[/]" if not r.trace.grounding_violations else "[red]no[/]",
        )
    console.print(table)

    console.print(f"\n[bold]Accuracy:[/] {summary.accuracy:.0%}")
    console.print(f"[bold]Grounding pass rate:[/] {summary.grounding_pass_rate:.0%}")
    console.print(f"[bold]Avg queries/investigation:[/] {summary.avg_queries_per_investigation:.1f}")
    console.print(
        f"[bold]Total cost:[/] {summary.total_llm_calls} LLM calls, "
        f"{summary.total_prompt_tokens:,} prompt tokens, {summary.total_output_tokens:,} output tokens"
    )
    console.print(
        "\n[dim]Note: 4 curated incidents demonstrates the calibration/accuracy "
        "measurement methodology, not a statistically powered result — see "
        "PROJECT.md Section 23.[/]"
    )
    console.print("\n[bold]Confidence calibration (bucket -> correct/total):[/]")
    for bucket, (correct, total) in summary.calibration_breakdown().items():
        console.print(f"  {bucket}: {correct}/{total}")


if __name__ == "__main__":
    app()
