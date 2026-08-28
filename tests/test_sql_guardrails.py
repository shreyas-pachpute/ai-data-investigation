from investigator.tools.sql_tool import execute_guardrailed_query


def test_valid_select_executes(test_config):
    result = execute_guardrailed_query(
        test_config, "SELECT region, SUM(revenue) FROM orders GROUP BY region"
    )
    assert result.error is None
    assert result.row_count == 3
    assert "region" in result.columns


def test_rejects_insert(test_config):
    result = execute_guardrailed_query(
        test_config, "INSERT INTO orders (order_id) VALUES (999999)"
    )
    assert result.error is not None
    assert "Guardrail rejected" in result.error


def test_rejects_delete(test_config):
    result = execute_guardrailed_query(test_config, "DELETE FROM orders WHERE 1=1")
    assert result.error is not None


def test_rejects_drop_table(test_config):
    result = execute_guardrailed_query(test_config, "DROP TABLE orders")
    assert result.error is not None


def test_rejects_pragma(test_config):
    result = execute_guardrailed_query(test_config, "PRAGMA table_info(orders)")
    assert result.error is not None


def test_rejects_stacked_statements(test_config):
    result = execute_guardrailed_query(
        test_config, "SELECT * FROM orders; DELETE FROM orders"
    )
    assert result.error is not None
    assert "Multiple statements" in result.error


def test_rejects_disallowed_table(test_config):
    result = execute_guardrailed_query(test_config, "SELECT * FROM sqlite_master")
    assert result.error is not None
    assert "not in the allowed list" in result.error


def test_allows_cte_referencing_own_name(test_config):
    result = execute_guardrailed_query(
        test_config,
        "WITH totals AS (SELECT region, SUM(revenue) AS rev FROM orders GROUP BY region) "
        "SELECT * FROM totals",
    )
    assert result.error is None
    assert result.row_count == 3


def test_row_limit_is_clamped(test_config):
    result = execute_guardrailed_query(
        test_config, f"SELECT * FROM orders LIMIT {test_config.max_rows_returned * 10}"
    )
    assert result.error is None
    assert result.limit_clamped is True
    assert result.row_count <= test_config.max_rows_returned


def test_missing_limit_is_auto_appended(test_config):
    result = execute_guardrailed_query(test_config, "SELECT * FROM orders")
    assert result.error is None
    assert result.row_count <= test_config.max_rows_returned


def test_stacked_statement_after_comment_still_rejected(test_config):
    result = execute_guardrailed_query(
        test_config, "SELECT * FROM orders; -- trailing comment\nDELETE FROM orders"
    )
    assert result.error is not None
    assert "Multiple statements" in result.error


def test_query_timeout_is_enforced(test_config):
    # A cartesian self-join over ~12k rows (~150M pairs) reliably takes well
    # over 0.1s, so a 0.1s timeout exercises the watchdog without a race
    # against query startup (an unrealistically tiny timeout could fire
    # before conn.execute() even begins).
    slow_config = test_config.__class__(
        **{**test_config.__dict__, "query_timeout_seconds": 0.1}
    )
    result = execute_guardrailed_query(
        slow_config,
        "SELECT COUNT(*) FROM orders a JOIN orders b ON a.order_id != b.order_id",
    )
    assert result.error is not None
    assert result.timed_out is True
