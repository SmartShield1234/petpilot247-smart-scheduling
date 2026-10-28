
"""PostgreSQL reconciliation coverage receipt schema.

Development-only schema definition.
No database connection, writes, or booking authorization.
"""

CREATE_COVERAGE_RECEIPTS_TABLE = """
CREATE TABLE IF NOT EXISTS petpilot_sync_coverage_receipts (
    receipt_id BIGSERIAL PRIMARY KEY,
    location_id TEXT NOT NULL,
    calendar_ids JSONB NOT NULL,
    range_start TIMESTAMPTZ NOT NULL,
    range_end TIMESTAMPTZ NOT NULL,
    event_count BIGINT NOT NULL,
    event_max_id BIGINT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'unverified',
    CONSTRAINT valid_receipt_status
        CHECK (status IN ('unverified', 'verified', 'invalidated')),
    CONSTRAINT valid_coverage_range
        CHECK (range_end > range_start)
);
"""
