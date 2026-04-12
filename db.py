# db.py
from __future__ import annotations

import logging
from contextlib import contextmanager

from psycopg2.pool import ThreadedConnectionPool

from config import DATABASE_URL

log = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None

def init_pool(minconn: int = 2, maxconn: int = 10, dsn: str | None = None) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(minconn=minconn, maxconn=maxconn, dsn=dsn or DATABASE_URL)
    log.info("Connection pool initialized (min=%d, max=%d)", minconn, maxconn)

def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None

@contextmanager
def get_conn():
    """Acquire a connection from the pool, commit on success, rollback on error."""
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
