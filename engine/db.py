"""Database engine/session management. sqlite for dev/tests, Postgres in deploy."""
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from . import config

engine = create_engine(
    config.DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _sqlite_fk(dbapi_conn, _):  # pragma: no cover - sqlite only
    if config.DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Session, "after_begin")
def _apply_scope(session, transaction, connection):
    if connection.dialect.name != "postgresql":
        return
    for setting, field in (
        ("app.organization_id", "organization_id"),
        ("app.user_id", "user_id"),
        ("app.api_key_hash", "api_key_hash"),
    ):
        value = session.info.get(field)
        if value:
            connection.execute(
                text("SELECT set_config(:setting, :value, true)"),
                {"setting": setting, "value": value},
            )


def scope_session(session: Session, organization_id: str, user_id: str = "") -> None:
    # Bind context before the first tenant query; after_begin reapplies it
    # after every commit (Postgres SET LOCAL lasts only one transaction).
    session.info["organization_id"] = organization_id
    session.info["user_id"] = user_id


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
