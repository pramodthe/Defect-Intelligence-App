"""Reviewed finding equivalence across immutable Word/PDF renditions."""
from alembic import op
revision='004'
down_revision='003'


def upgrade():
    op.get_bind().exec_driver_sql("CREATE TABLE IF NOT EXISTS finding_equivalences(id TEXT PRIMARY KEY,canonical_finding_id TEXT NOT NULL REFERENCES findings(id),alias_finding_id TEXT UNIQUE NOT NULL REFERENCES findings(id),anchor_ids TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL)")


def downgrade():
    raise RuntimeError('Identity audit history requires a validated backup restore')
