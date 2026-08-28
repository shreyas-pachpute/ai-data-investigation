-- Synthetic data warehouse for the AI Data Investigation & Root-Cause Agent.
-- One flat orders table (already denormalized to keep MVP query surface simple)
-- plus pipeline run history and schema-change history, mirroring the three
-- evidence sources named in PROJECT.md Section 10.

CREATE TABLE IF NOT EXISTS orders (
    order_id     INTEGER PRIMARY KEY,
    order_date   TEXT NOT NULL,   -- YYYY-MM-DD
    region       TEXT NOT NULL,   -- NA, EMEA, APAC
    segment      TEXT NOT NULL,   -- Enterprise, SMB, Consumer
    channel      TEXT NOT NULL,   -- Web, Mobile, Partner
    quantity     INTEGER NOT NULL,
    unit_price   REAL NOT NULL,
    revenue      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_region ON orders(region);
CREATE INDEX IF NOT EXISTS idx_orders_segment ON orders(segment);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          INTEGER PRIMARY KEY,
    pipeline_name   TEXT NOT NULL,
    run_date        TEXT NOT NULL,   -- YYYY-MM-DD, the date of data this run ingested
    status          TEXT NOT NULL,   -- success, failed, partial
    rows_processed  INTEGER NOT NULL,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date ON pipeline_runs(run_date);

CREATE TABLE IF NOT EXISTS schema_changes (
    change_id    INTEGER PRIMARY KEY,
    table_name   TEXT NOT NULL,
    change_date  TEXT NOT NULL,   -- YYYY-MM-DD
    description  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schema_changes_date ON schema_changes(change_date);

-- Not part of the agent's iterative SQL tool: loaded once, deterministically,
-- as context before an investigation starts (a "Resource", not a "Tool").
CREATE TABLE IF NOT EXISTS metrics_catalog (
    metric_name  TEXT PRIMARY KEY,
    definition   TEXT NOT NULL,
    owner        TEXT NOT NULL
);
