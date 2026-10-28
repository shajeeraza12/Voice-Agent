"""Alembic environment. Uses the same DATABASE_URL as the app."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.core import calls  # noqa: F401  (registers the calls table)
from app.db.base import Base
from app.domains.us_patient import orm  # noqa: F401  (registers the patients table)
from app.settings import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.sqlalchemy_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(settings.sqlalchemy_url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
