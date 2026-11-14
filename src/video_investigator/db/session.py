"""Engine and session helpers. SQLite in WAL mode with foreign keys and a busy timeout; bounded retry on 'database is locked'."""
from __future__ import annotations
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypeVar
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from ..paths import db_path
from .models import Base

T = TypeVar("T")
BUSY_TIMEOUT_MS = 5000


def make_engine(path: Path | str | None = None) -> Engine:
    eng = create_engine(f"sqlite:///{path or db_path()}", connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000}, future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL"); cur.execute("PRAGMA foreign_keys=ON"); cur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA synchronous=NORMAL"); cur.close()

    # SQLAlchemy's pysqlite default delays BEGIN; take explicit control so BEGIN IMMEDIATE can be used for claims.
    @event.listens_for(eng, "connect")
    def _isolation(dbapi_conn, _):
        dbapi_conn.isolation_level = None

    @event.listens_for(eng, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")
    return eng


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory) -> "Session":
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback(); raise
    finally:
        s.close()


def with_lock_retry(fn: Callable[[], T], attempts: int = 5, delay_s: float = 0.2) -> T:
    """Bounded retry for transient SQLite lock contention. Anything else propagates immediately."""
    for i in range(attempts):
        try:
            return fn()
        except OperationalError as e:
            if "locked" not in str(e).lower() or i == attempts - 1:
                raise
            time.sleep(delay_s * (i + 1))
    raise RuntimeError("unreachable")


# ---- migrations: a minimal versioned runner (no Alembic dependency for a single-user prototype) ----
def _m1(conn):
    Base.metadata.create_all(conn)


def _m2(conn):
    """Explanations table (optional video-language descriptions)."""
    from .models import Explanation
    Explanation.__table__.create(conn, checkfirst=True)


MIGRATIONS: list[tuple[int, Callable]] = [(1, _m1), (2, _m2)]


def migrate(engine: Engine) -> int:
    """Apply pending migrations in order, each in its own transaction. Returns the resulting schema version."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"))
    with engine.connect() as c:
        done = {r[0] for r in c.execute(text("SELECT version FROM schema_migrations"))}
    for version, fn in MIGRATIONS:
        if version in done:
            continue
        with engine.begin() as conn:
            fn(conn)
            conn.execute(text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, datetime('now'))"), {"v": version})
    with engine.connect() as c:
        return int(c.execute(text("SELECT max(version) FROM schema_migrations")).scalar() or 0)
