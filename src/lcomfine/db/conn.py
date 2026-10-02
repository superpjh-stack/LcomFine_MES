"""DB 접속 — `contracts/interfaces.md` §1.

    q(sql, params) -> list[dict]   SELECT. 항상 dict 리스트
    q1(sql, params) -> dict|None   첫 행
    x(sql, params) -> int          INSERT/UPDATE/DELETE. rowcount
    tx()                           컨텍스트 매니저 (with tx() as cur:) — 여러 문장을 한 트랜잭션으로

DSN 은 `LCOMFINE_PG_DSN` (기본 `postgresql:///lcomfine_db`).
**DB 연결 실패를 삼키지 않는다.** `DbUnavailable` 로 올려 보내고 main.py 가 503 `서비스 일시 중단` 으로 렌더링한다.
조용한 폴백(빈 리스트 반환 등)은 하지 않는다. 제약 위반(`psycopg.errors.IntegrityError`)도 그대로 올라가
main.py 가 422 로 바꾼다(`contracts/api-contract.md` §3).
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from ..app import settings as _settings  # noqa: F401 — 로컬 `.env` 를 먼저 읽는다

DEFAULT_DSN = "postgresql:///lcomfine_db"


class DbUnavailable(RuntimeError):
    """DB 연결 자체가 되지 않는 상태. 503 `서비스 일시 중단` 으로 매핑된다."""


def dsn() -> str:
    return os.environ.get("LCOMFINE_PG_DSN") or DEFAULT_DSN


def connect() -> psycopg.Connection:
    """새 커넥션(autocommit). 연결 실패는 DbUnavailable 로 올린다(쿼리 오류는 그대로 통과시킨다)."""
    try:
        return psycopg.connect(dsn(), row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError as exc:  # 연결 불가만 잡는다
        raise DbUnavailable(str(exc)) from exc


def q(sql: str, params: Sequence | Mapping | None = None) -> list[dict]:
    """SELECT. 항상 dict 리스트를 돌려준다. 결과가 없으면 빈 리스트."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        return [dict(r) for r in cur.fetchall()]


def q1(sql: str, params: Sequence | Mapping | None = None) -> dict | None:
    """첫 행만. 없으면 None."""
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: Sequence | Mapping | None = None) -> int:
    """INSERT/UPDATE/DELETE. rowcount 를 돌려준다."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


@contextmanager
def tx() -> Iterator[psycopg.Cursor]:
    """트랜잭션 커서. 예외가 나면 롤백하고 그대로 올린다.

        with tx() as cur:
            cur.execute(...)
            row = cur.fetchone()
    """
    try:
        conn = psycopg.connect(dsn(), row_factory=dict_row)
    except psycopg.OperationalError as exc:
        raise DbUnavailable(str(exc)) from exc
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except psycopg.OperationalError as exc:
        conn.rollback()
        raise DbUnavailable(str(exc)) from exc
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping() -> bool:
    """`/health` 용. 실패는 DbUnavailable 로 올라간다 — True/False 로 뭉개지 않는다."""
    return q("select 1 as ok")[0]["ok"] == 1
