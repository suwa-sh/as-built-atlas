"""PostgreSQL への接続と問い合わせ (psycopg の薄いラッパー)。"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg

from jobs import settings


@contextmanager
def connect():
    conn = psycopg.connect(settings.DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def execute_many(sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(sql, rows)
        return cur.rowcount
