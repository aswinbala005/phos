import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# --- PHOS SPECIFIC: Add backend to path for imports ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.config import settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- PHOS CONFIG: Use SYNC URL for Alembic migrations ---
target_metadata = Base.metadata

# Alembic runs synchronously, so we need a sync driver (psycopg2)
# Use DATABASE_URL_SYNC if defined, otherwise convert async URL to sync
if hasattr(settings, 'DATABASE_URL_SYNC') and settings.DATABASE_URL_SYNC:
    sync_url = settings.DATABASE_URL_SYNC
else:
    # Fallback: replace asyncpg with psycopg2 in the URL
    sync_url = settings.DATABASE_URL.replace('+asyncpg', '+psycopg2')

config.set_main_option("sqlalchemy.url", sync_url)

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Alembic needs a SYNC engine, not async
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()