"""Small idempotent schema upgrades for databases created by older releases."""
from sqlalchemy import inspect, text


def upgrade_schema(engine):
    """Apply schema changes that ``db.create_all()`` cannot apply in place."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "traps" in tables:
        trap_columns = {
            column["name"] for column in inspector.get_columns("traps")
        }
        if "asset_number" not in trap_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE traps ADD COLUMN asset_number VARCHAR(100)")
                )

    if "users" not in tables:
        return

    user_columns = {
        column["name"]: column for column in inspector.get_columns("users")
    }
    additions = {
        "auth_provider": "VARCHAR(10) NOT NULL DEFAULT 'LOCAL'",
        "directory_key": "VARCHAR(100)",
        "directory_subject": "VARCHAR(255)",
        "ldap_dn": "VARCHAR(1024)",
        "ldap_synced_at": (
            "TIMESTAMP WITH TIME ZONE"
            if engine.dialect.name == "postgresql"
            else "DATETIME"
        ),
        "token_version": "INTEGER NOT NULL DEFAULT 0",
    }

    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in user_columns:
                connection.execute(
                    text(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                )

        password_column = user_columns.get("password_hash")
        if password_column and not password_column.get("nullable", True):
            if engine.dialect.name == "sqlite":
                # SQLite cannot directly drop NOT NULL. Renaming the old column,
                # copying its values to a nullable replacement, and dropping the
                # old column preserves existing LOCAL hashes and user rows.
                connection.execute(
                    text(
                        "ALTER TABLE users RENAME COLUMN password_hash "
                        "TO password_hash_legacy"
                    )
                )
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
                )
                connection.execute(
                    text(
                        "UPDATE users SET password_hash = password_hash_legacy"
                    )
                )
                connection.execute(
                    text("ALTER TABLE users DROP COLUMN password_hash_legacy")
                )
            elif engine.dialect.name == "postgresql":
                connection.execute(
                    text("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")
                )
            else:
                raise RuntimeError(
                    "Automatic nullable password_hash upgrade is supported only "
                    "for SQLite and PostgreSQL; apply the equivalent schema change "
                    "for this database backend."
                )

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_directory_identity "
                "ON users (directory_key, directory_subject)"
            )
        )
