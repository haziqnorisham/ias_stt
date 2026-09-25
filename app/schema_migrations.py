"""Small idempotent schema upgrades for databases created by older releases."""
from sqlalchemy import inspect, text


def upgrade_schema(engine):
    """Apply schema changes that ``db.create_all()`` cannot apply in place."""
    inspector = inspect(engine)
    if "traps" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("traps")}
    if "asset_number" in columns:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE traps ADD COLUMN asset_number VARCHAR(100)")
        )
