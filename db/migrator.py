import logging
from dataclasses import dataclass
from typing import Callable, List, Set

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    upgrade: Callable[[Connection], None]


def _ensure_migrations_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _migration_0001_add_channel_subscription_fields(connection: Connection) -> None:
    inspector = inspect(connection)
    columns: Set[str] = {col["name"] for col in inspector.get_columns("users")}
    statements: List[str] = []

    if "channel_subscription_verified" not in columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN channel_subscription_verified BOOLEAN"
        )
    if "channel_subscription_checked_at" not in columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN channel_subscription_checked_at TIMESTAMPTZ"
        )
    if "channel_subscription_verified_for" not in columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN channel_subscription_verified_for BIGINT"
        )

    for stmt in statements:
        connection.execute(text(stmt))


def _migration_0002_add_referral_code(connection: Connection) -> None:
    inspector = inspect(connection)
    columns: Set[str] = {col["name"] for col in inspector.get_columns("users")}

    if "referral_code" not in columns:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN referral_code VARCHAR(16)")
        )

    connection.execute(
        text(
            """
            WITH generated_codes AS (
                SELECT
                    user_id,
                    UPPER(
                        SUBSTRING(
                            md5(
                                user_id::text
                                || clock_timestamp()::text
                                || random()::text
                            )
                            FROM 1 FOR 9
                        )
                    ) AS referral_code
                FROM users
                WHERE referral_code IS NULL OR referral_code = ''
            )
            UPDATE users AS u
            SET referral_code = g.referral_code
            FROM generated_codes AS g
            WHERE u.user_id = g.user_id
            """
        )
    )

    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_users_referral_code
            ON users (referral_code)
            WHERE referral_code IS NOT NULL
            """
        )
    )


def _migration_0003_normalize_referral_codes(connection: Connection) -> None:
    inspector = inspect(connection)
    columns: Set[str] = {col["name"] for col in inspector.get_columns("users")}
    if "referral_code" not in columns:
        return

    connection.execute(
        text(
            """
            UPDATE users
            SET referral_code = UPPER(referral_code)
            WHERE referral_code IS NOT NULL
              AND referral_code <> UPPER(referral_code)
            """
        )
    )


def _migration_0004_add_lifetime_used_traffic(connection: Connection) -> None:
    inspector = inspect(connection)
    columns: Set[str] = {col["name"] for col in inspector.get_columns("users")}
    if "lifetime_used_traffic_bytes" in columns:
        return

    connection.execute(
        text(
            "ALTER TABLE users ADD COLUMN lifetime_used_traffic_bytes BIGINT"
        )
    )


def _has_unique_constraint_or_index(
    connection: Connection, table_name: str, columns: List[str]
) -> bool:
    inspector = inspect(connection)
    normalized = tuple(columns)

    for constraint in inspector.get_unique_constraints(table_name):
        if tuple(constraint.get("column_names") or []) == normalized:
            return True

    for index in inspector.get_indexes(table_name):
        if index.get("unique") and tuple(index.get("column_names") or []) == normalized:
            return True

    return False


def _migration_0005_add_web_auth_columns(connection: Connection) -> None:
    inspector = inspect(connection)
    columns: Set[str] = {col["name"] for col in inspector.get_columns("users")}
    statements: List[str] = []

    if "email" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN email VARCHAR")
    if "email_verified_at" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ")
    if "telegram_user_id" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN telegram_user_id BIGINT")
    if "telegram_link_code_hash" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN telegram_link_code_hash VARCHAR")
    if "telegram_link_code_purpose" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN telegram_link_code_purpose VARCHAR")
    if "telegram_link_code_expires_at" not in columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN telegram_link_code_expires_at TIMESTAMPTZ"
        )
    if "telegram_linked_at" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN telegram_linked_at TIMESTAMPTZ")

    for stmt in statements:
        connection.execute(text(stmt))

    # Backfill existing Telegram-linked users. Email-only rows will keep NULL.
    connection.execute(
        text(
            """
            UPDATE users
            SET telegram_user_id = user_id
            WHERE telegram_user_id IS NULL
              AND user_id IS NOT NULL
            """
        )
    )

    unique_specs = [
        ("users", ["email"]),
        ("users", ["telegram_user_id"]),
        ("users", ["telegram_link_code_hash"]),
    ]
    for table_name, cols in unique_specs:
        if not _has_unique_constraint_or_index(connection, table_name, cols):
            constraint_name = f"uq_{table_name}_{'_'.join(cols)}"
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} UNIQUE ({', '.join(cols)})"
                )
            )


def _migration_0006_create_web_user_id_sequence(connection: Connection) -> None:
    connection.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind = 'S'
                      AND c.relname = 'web_user_id_seq'
                      AND n.nspname = current_schema()
                ) THEN
                    CREATE SEQUENCE web_user_id_seq
                        START WITH -1
                        INCREMENT BY -1
                        MINVALUE -9223372036854775808
                        MAXVALUE -1
                        CACHE 1;
                END IF;
            END
            $$;
            """
        )
    )


def _migration_0007_create_web_auth_tables(connection: Connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if "web_auth_challenges" not in existing_tables:
        connection.execute(
            text(
                """
                CREATE TABLE web_auth_challenges (
                    challenge_id SERIAL PRIMARY KEY,
                    email VARCHAR NOT NULL,
                    purpose VARCHAR NOT NULL,
                    code_hash VARCHAR NOT NULL,
                    user_id BIGINT NULL,
                    request_ip VARCHAR NULL,
                    user_agent TEXT NULL,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    consumed_at TIMESTAMPTZ NULL,
                    CONSTRAINT fk_web_auth_challenges_user_id
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_auth_challenges_email ON web_auth_challenges (email)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_auth_challenges_purpose ON web_auth_challenges (purpose)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_auth_challenges_code_hash ON web_auth_challenges (code_hash)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_auth_challenges_expires_at ON web_auth_challenges (expires_at)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_web_auth_challenges_code_hash ON web_auth_challenges (code_hash)"))

    if "web_sessions" not in existing_tables:
        connection.execute(
            text(
                """
                CREATE TABLE web_sessions (
                    session_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    token_hash VARCHAR NOT NULL,
                    auth_method VARCHAR NOT NULL DEFAULT 'email',
                    request_ip VARCHAR NULL,
                    user_agent TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ NULL,
                    CONSTRAINT fk_web_sessions_user_id
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
                """
            )
        )
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_web_sessions_token_hash ON web_sessions (token_hash)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_sessions_user_id ON web_sessions (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_sessions_expires_at ON web_sessions (expires_at)"))

MIGRATIONS: List[Migration] = [
    Migration(
        id="0001_add_channel_subscription_fields",
        description="Add columns to track required channel subscription verification",
        upgrade=_migration_0001_add_channel_subscription_fields,
    ),
    Migration(
        id="0002_add_referral_code",
        description="Store short referral codes for users and backfill existing rows",
        upgrade=_migration_0002_add_referral_code,
    ),
    Migration(
        id="0003_normalize_referral_codes",
        description="Normalize referral codes to uppercase for consistent lookups",
        upgrade=_migration_0003_normalize_referral_codes,
    ),
    Migration(
        id="0004_add_lifetime_used_traffic",
        description="Store lifetime traffic usage for users",
        upgrade=_migration_0004_add_lifetime_used_traffic,
    ),
    Migration(
        id="0005_add_web_auth_columns",
        description="Add email and Telegram linking columns for web auth",
        upgrade=_migration_0005_add_web_auth_columns,
    ),
    Migration(
        id="0006_create_web_user_id_sequence",
        description="Create a negative sequence for email-first web accounts",
        upgrade=_migration_0006_create_web_user_id_sequence,
    ),
    Migration(
        id="0007_create_web_auth_tables",
        description="Create tables for web auth challenges and sessions",
        upgrade=_migration_0007_create_web_auth_tables,
    ),
]


def run_database_migrations(connection: Connection) -> None:
    """
    Apply pending migrations sequentially. Already applied revisions are skipped.
    """
    _ensure_migrations_table(connection)

    applied_revisions: Set[str] = {
        row[0]
        for row in connection.execute(
            text("SELECT id FROM schema_migrations")
        )
    }

    for migration in MIGRATIONS:
        if migration.id in applied_revisions:
            continue

        logging.info(
            "Migrator: applying %s – %s", migration.id, migration.description
        )
        try:
            with connection.begin_nested():
                migration.upgrade(connection)
                connection.execute(
                    text(
                        "INSERT INTO schema_migrations (id) VALUES (:revision)"
                    ),
                    {"revision": migration.id},
                )
        except Exception as exc:
            logging.error(
                "Migrator: failed to apply %s (%s)",
                migration.id,
                migration.description,
                exc_info=True,
            )
            raise exc
        else:
            logging.info("Migrator: migration %s applied successfully", migration.id)
