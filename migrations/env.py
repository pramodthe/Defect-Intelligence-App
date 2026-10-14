from alembic import context
from sqlalchemy import create_engine
from app.settings import settings

settings.workspace_root.mkdir(parents=True, exist_ok=True)
engine = create_engine("sqlite:///" + str(settings.db_path))
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
