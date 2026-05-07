"""
PostgreSQL connection pool — single shared pool for the whole app.

Usage:
    from app.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
    # connection is returned to pool automatically
"""

import os
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _dsn() -> str:
    return os.environ.get(
        "POSTGRES_DSN",
        "postgresql://society:society@localhost:5432/society",
    )


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    dsn=_dsn(),
                )
    return _pool


@contextmanager
def get_conn():
    """Yield a psycopg2 connection; auto-commit on success, rollback on error."""
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)
