"""Track the active semantic extraction while retaining predecessor units."""
from alembic import op
revision = "003"
down_revision = "002"


def upgrade():
    connection = op.get_bind()
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(documents)")}
    if "active_semantic_revision" not in columns:
        connection.exec_driver_sql("ALTER TABLE documents ADD COLUMN active_semantic_revision TEXT")
    connection.exec_driver_sql("UPDATE documents SET active_semantic_revision=(SELECT semantic_revision FROM units WHERE document_id=documents.id ORDER BY rowid DESC LIMIT 1) WHERE active_semantic_revision IS NULL")


def downgrade():
    raise RuntimeError("Evidence history cannot be destructively downgraded")
