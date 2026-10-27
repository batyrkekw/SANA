from sqlalchemy import create_engine, pool

from alembic import context
from app import models  # noqa: F401
from app.config import get_settings
from app.db import Base

target_metadata = Base.metadata
url = get_settings().database_url.get_secret_value()

if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:

    def run(connection):
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        run(supplied)
    else:
        engine = create_engine(url, poolclass=pool.NullPool)
        with engine.connect() as connection:
            run(connection)
