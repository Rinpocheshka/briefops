"""Storage boundary: local SQLite or TLS Postgres on Neon."""
import re
import sqlite3
import certifi
from contextlib import contextmanager


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in (cursor.description or [])]
    return lambda values: Row(zip(names, values))


class PostgresConnection:
    """Translate the small, fixed SQL dialect used by Store; values stay bound."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, args=()):
        if query.strip().upper() == "BEGIN IMMEDIATE":
            # Serialize short write transactions across overlapping deploy processes.
            return self.connection.execute("SELECT pg_advisory_xact_lock(708184053)")
        ignore = "INSERT OR IGNORE INTO" in query
        query = query.replace("INSERT OR IGNORE INTO", "INSERT INTO").replace("?", "%s")
        if ignore:
            query = query.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return self.connection.execute(query, args)

    def executescript(self, script):
        for statement in script.split(";"):
            if not statement.strip() or statement.strip().startswith("PRAGMA"):
                continue
            statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            statement = re.sub(r"\bREAL\b", "DOUBLE PRECISION", statement)
            self.connection.execute(statement)


class Database:
    def __init__(self, path, database_url=None):
        self.path, self.pool = path, None
        self.kind = "postgres" if database_url else "sqlite"
        if database_url:
            from psycopg_pool import ConnectionPool
            # Neon PgBouncer handles server pooling; keep the client pool small.
            self.pool = ConnectionPool(database_url, min_size=0, max_size=4, timeout=20,
                                       kwargs={"row_factory": row_factory, "prepare_threshold": None,
                                               "connect_timeout": 15, "sslmode": "verify-full", "sslrootcert": certifi.where()})

    @contextmanager
    def connect(self):
        if self.pool:
            with self.pool.connection() as connection:
                yield PostgresConnection(connection)
            return
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self, script, direct_url=None):
        if not self.pool:
            with self.connect() as connection:
                connection.executescript(script)
            return
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        # Run migrations on the direct URL. Refuse a pooled migration endpoint.
        direct_url = direct_url or self.pool.conninfo
        if "-pooler" in conninfo_to_dict(direct_url).get("host", ""):
            raise ValueError("DATABASE_URL_UNPOOLED is required for migrations")
        with psycopg.connect(direct_url, connect_timeout=20, sslmode="verify-full", sslrootcert=certifi.where()) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(708184053)")
            PostgresConnection(connection).executescript(script)

    @contextmanager
    def read(self):
        with self.connect() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" if self.pool else "BEGIN")
            yield connection

    def close(self):
        if self.pool:
            self.pool.close()
