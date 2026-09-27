import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def configure(connection=None) -> None:
    context.configure(
        connection=connection,
        url=(
            None if connection is not None else config.get_main_option("sqlalchemy.url")
        ),
        target_metadata=target_metadata,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table="audience_pulse_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(configure)
    await connectable.dispose()


if context.is_offline_mode():
    configure()
else:
    asyncio.run(run_async_migrations())
