"""Install fail-closed PostgreSQL tenant policies.

Revision ID: 92bb5b3f7ec1
Revises: fe81fefff753
"""
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "92bb5b3f7ec1"
down_revision = "fe81fefff753"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        source = Path(__file__).resolve().parents[1] / "0002_rls.sql"
        # SQLAlchemy text() escapes PostgreSQL format()'s %I placeholders
        # before psycopg sees the SQL (exec_driver_sql does not).
        op.execute(text(source.read_text(encoding="utf-8")))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("agents", "skills", "tasks", "task_runs", "approvals",
                      "usage_costs", "schedules", "event_triggers", "audit_log",
                      "api_keys", "agent_versions", "skill_versions"):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        for table in ("conversations", "messages"):
            op.execute(f"DROP POLICY IF EXISTS owner_memory ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
