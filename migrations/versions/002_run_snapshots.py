"""Pin governed catalog/rule versions with a research run."""
from alembic import op
revision = "002"
down_revision = "001"


def upgrade():
    connection = op.get_bind()
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    if "rule_pack_ids" not in columns:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN rule_pack_ids TEXT NOT NULL DEFAULT '[]'")
    if "ontology_version" not in columns:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN ontology_version TEXT NOT NULL DEFAULT ''")


def downgrade():
    raise RuntimeError("Restore a validated canonical backup instead of deleting run evidence")
