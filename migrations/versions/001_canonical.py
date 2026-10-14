"""Initial canonical evidence, workflow ledger and publication schema."""
from alembic import op
from app.store import SCHEMA

revision = "001"
down_revision = None


def upgrade():
    connection = op.get_bind()
    for statement in SCHEMA.split(";"):
        if statement.strip():
            connection.exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Destructive canonical downgrade is unsupported; restore a validated backup")
