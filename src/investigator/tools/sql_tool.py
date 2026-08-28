"""The agent's only tool: a guardrailed, read-only SQL query executor.

This is the safety-critical component named in PROJECT.md Section 16 ("the
warehouse query tool is strictly read-only"). Every guardrail here is
enforced in code, never left to the model's own restraint:

  1. single-statement SELECT (or WITH ... SELECT) only, keyword-blocklisted
  2. table whitelist
  3. connection opened in SQLite read-only mode (defense in depth beyond #1)
  4. row-count cap, auto-clamped LIMIT
  5. wall-clock query timeout via a watchdog thread
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from investigator.config import Config

_FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "ATTACH",
    "DETACH", "PRAGMA", "REPLACE", "TRUNCATE", "VACUUM", "REINDEX",
    "GRANT", "REVOKE",
)
_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_LIMIT_CLAUSE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_CTE_NAME = re.compile(r"\bWITH\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(|,\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.IGNORECASE)


class GuardrailViolation(Exception):
    """Raised when a proposed query fails a safety guardrail before execution."""


@dataclass
class QueryResult:
    original_sql: str
    executed_sql: str
    columns: list[str]
    rows: list[tuple]
    row_count: int
    limit_clamped: bool
    duration_ms: float
    error: str | None = None
    timed_out: bool = False

    def to_prompt_text(self, max_rows: int, max_cell_chars: int) -> str:
        """Compact text table for LLM consumption, truncated for token cost."""
        if self.error:
            return f"ERROR: {self.error}"
        if not self.columns:
            return "(query executed, 0 columns returned)"

        def _cell(v) -> str:
            s = "" if v is None else str(v)
            return s if len(s) <= max_cell_chars else s[: max_cell_chars - 3] + "..."

        lines = [" | ".join(self.columns)]
        shown = self.rows[:max_rows]
        for row in shown:
            lines.append(" | ".join(_cell(v) for v in row))
        text = "\n".join(lines)
        if self.row_count > len(shown):
            text += f"\n... ({self.row_count - len(shown)} more row(s) truncated)"
        return text


def _strip_comments(sql: str) -> str:
    sql = _COMMENT_BLOCK.sub(" ", sql)
    sql = _COMMENT_LINE.sub(" ", sql)
    return sql.strip()


def _validate_single_select(sql: str) -> None:
    body = sql.strip().rstrip(";")
    if ";" in body:
        raise GuardrailViolation("Multiple statements are not allowed (found ';' mid-query).")

    first_token_match = re.match(r"\s*([A-Za-z_]+)", body)
    first_token = first_token_match.group(1).upper() if first_token_match else ""
    if first_token not in ("SELECT", "WITH"):
        raise GuardrailViolation(
            f"Only SELECT (or WITH ... SELECT) statements are allowed; got '{first_token}'."
        )

    for kw in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", body, re.IGNORECASE):
            raise GuardrailViolation(f"Forbidden keyword '{kw}' found in query.")


def _validate_tables(sql: str, allowed_tables: tuple[str, ...]) -> None:
    cte_names = {m.group(1) or m.group(2) for m in _CTE_NAME.finditer(sql)}
    cte_names = {n.lower() for n in cte_names if n}
    referenced = {m.group(1).lower() for m in _TABLE_REF.finditer(sql)}
    allowed = {t.lower() for t in allowed_tables} | cte_names
    disallowed = referenced - allowed
    if disallowed:
        raise GuardrailViolation(
            f"Query references table(s) not in the allowed list: {sorted(disallowed)}."
        )


def _clamp_limit(sql: str, max_rows: int) -> tuple[str, bool]:
    body = sql.strip().rstrip(";")
    match = _LIMIT_CLAUSE.search(body)
    if match:
        requested = int(match.group(1))
        if requested > max_rows:
            body = _LIMIT_CLAUSE.sub(f"LIMIT {max_rows}", body)
            return body, True
        return body, False
    return f"{body} LIMIT {max_rows}", False


def execute_guardrailed_query(config: Config, raw_sql: str) -> QueryResult:
    cleaned = _strip_comments(raw_sql)

    try:
        _validate_single_select(cleaned)
        _validate_tables(cleaned, config.allowed_tables)
    except GuardrailViolation as exc:
        return QueryResult(
            original_sql=raw_sql,
            executed_sql=cleaned,
            columns=[],
            rows=[],
            row_count=0,
            limit_clamped=False,
            duration_ms=0.0,
            error=f"Guardrail rejected query: {exc}",
        )

    executed_sql, clamped = _clamp_limit(cleaned, config.max_rows_returned)

    uri = f"file:{config.warehouse_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    timed_out_flag = {"hit": False}

    def _watchdog():
        timed_out_flag["hit"] = True
        conn.interrupt()

    timer = threading.Timer(config.query_timeout_seconds, _watchdog)
    started = time.perf_counter()
    try:
        timer.start()
        cursor = conn.execute(executed_sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        duration_ms = (time.perf_counter() - started) * 1000
        return QueryResult(
            original_sql=raw_sql,
            executed_sql=executed_sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            limit_clamped=clamped,
            duration_ms=duration_ms,
        )
    except sqlite3.OperationalError as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        if timed_out_flag["hit"]:
            return QueryResult(
                original_sql=raw_sql,
                executed_sql=executed_sql,
                columns=[],
                rows=[],
                row_count=0,
                limit_clamped=clamped,
                duration_ms=duration_ms,
                error=f"Query exceeded timeout of {config.query_timeout_seconds}s and was aborted.",
                timed_out=True,
            )
        return QueryResult(
            original_sql=raw_sql,
            executed_sql=executed_sql,
            columns=[],
            rows=[],
            row_count=0,
            limit_clamped=clamped,
            duration_ms=duration_ms,
            error=f"SQL execution error: {exc}",
        )
    finally:
        timer.cancel()
        conn.close()
