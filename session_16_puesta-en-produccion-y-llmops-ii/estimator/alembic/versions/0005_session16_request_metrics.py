"""Session 16 — request_metrics: one row per request, with its latency and its cost.

Revision ID: 0005_session16_request_metrics
Revises: 0004_session10_multi_index
Create Date: 2026-09-26 00:00:00

Why a table and not a log file. The dashboard's questions are all of the form
"over the last N hours": mean and p95 latency, cost per request, error rate,
and the same split by route. In SQL that is one `percentile_cont` away; over
stdout it is a log-collection pipeline you have to build and operate before you
can ask anything at all. The service already runs Postgres, so the honest cheap
answer is a narrow table with an index on the column every query filters by.

It holds no PII by construction: no transcript, no body, no headers. The route
travels as its TEMPLATE, which is both the safe form and the only aggregable
one — grouped by concrete id, every row is its own group.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_session16_request_metrics"
down_revision = "0004_session10_multi_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("route", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        # Texto, no entero: las peticiones HTTP traen su codigo y las ejecuciones
        # del grafo en segundo plano no tienen respuesta que devolver, asi que
        # terminan en 'completed' o 'failed'.
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("calls_without_usage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost", sa.Float(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_request_metrics_recorded_at", "request_metrics", ["recorded_at"])
    op.create_index("idx_request_metrics_route", "request_metrics", ["route", "recorded_at"])


def downgrade() -> None:
    op.drop_index("idx_request_metrics_route", table_name="request_metrics")
    op.drop_index("idx_request_metrics_recorded_at", table_name="request_metrics")
    op.drop_table("request_metrics")
