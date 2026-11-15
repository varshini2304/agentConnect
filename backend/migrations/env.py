"""Application and operator runners supply the already-open transaction."""
from alembic import context


def run(connection):
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python scripts/migrate.py for verified backup and copy-first upgrades.")
run(connection)
