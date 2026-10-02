"""DB 접속 — `contracts/interfaces.md` §1.

    q(sql, params) -> list[dict]   SELECT. 항상 dict 리스트
    q1(sql, params) -> dict|None   첫 행
    x(sql, params) -> int          INSERT/UPDATE/DELETE. rowcount
    tx()                           컨텍스트 매니저 (with tx() as cur:) — 여러 문장을 한 트랜잭션으로

DSN 은 `LCOMFINE_PG_DSN` (기본 `postgresql:///lcomfine_db`).
**DB 연결 실패를 삼키지 않는다.** `DbUnavailable` 로 올려 보내고 main.py 가 503 `서비스 일시 중단` 으로 렌더링한다.
조용한 폴백(빈 리스트 반환 등)은 하지 않는다. 제약 위반(`psycopg.errors.IntegrityError`)도 그대로 올라가
main.py 가 422 로 바꾼다(`contracts/api-contract.md` §3).

접속 문자열은 **어디에도 내보내지 않는다**(D-32) — 응답에는 싣지 않고(`/health` 포함), 서버 로그에 남는 `DbUnavailable` 의
사유 문구에서는 비밀번호를 가린다. 접속 문자열 자체가 틀려 드라이버가 그 조각을 되읊는 경우(`invalid percent-encoded token: "…"`)는
원문을 버리고 예외 종류만 남긴다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from urllib.parse import quote

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from ..app import settings as _settings  # noqa: F401 — 로컬 `.env` 를 먼저 읽는다

DEFAULT_DSN = "postgresql:///lcomfine_db"


class DbUnavailable(RuntimeError):
    """DB 연결 자체가 되지 않는 상태. 503 `서비스 일시 중단` 으로 매핑된다."""


def dsn() -> str:
    return os.environ.get("LCOMFINE_PG_DSN") or DEFAULT_DSN


#: 접속 문자열을 드라이버가 해석하지 못했을 때의 사유 — 드라이버의 원문은 접속 문자열 조각(비밀번호일 수 있다)을 되읊으므로 남기지 않는다
BAD_DSN = "접속 문자열(LCOMFINE_PG_DSN)을 해석하지 못했다 — 형식을 확인한다 (원문은 접속 문자열 조각을 담을 수 있어 남기지 않는다)"


def _passwords() -> list[str]:
    """지금 접속 설정의 비밀번호(접속 문자열 · `PGPASSWORD`)와 그 URL 인코딩 꼴 — 사유 문구에서 가릴 글자들."""
    try:
        found = [str(conninfo_to_dict(dsn()).get("password") or ""), os.environ.get("PGPASSWORD") or ""]
    except psycopg.Error as exc:            # 해석이 안 되면 무엇이 비밀번호인지 모른다 — 원문을 통째로 버린다
        raise DbUnavailable(f"{BAD_DSN} [{type(exc).__name__}]") from None
    return [v for pw in found if pw for v in {pw, quote(pw, safe="")}]


def unavailable(exc: psycopg.Error) -> DbUnavailable:
    """연결 실패 → `DbUnavailable`. 사유 문구는 서버 로그에 남는다 — 호스트·소켓 경로는 운영자가 봐야 하므로 그대로 두고
    **비밀번호만** 가린다(D-32). 원래 예외는 달지 않는다(`from None` — 가리기 전의 문구가 트레이스백으로 새지 않게)."""
    if not isinstance(exc, psycopg.OperationalError):        # 접속 문자열 자체가 틀렸다 (`ProgrammingError` — 조각을 되읊는다)
        return DbUnavailable(f"{BAD_DSN} [{type(exc).__name__}]")
    text = str(exc).strip()
    for secret in _passwords():
        text = text.replace(secret, "***")
    return DbUnavailable(text)


def connect() -> psycopg.Connection:
    """새 커넥션(autocommit). 연결 실패는 DbUnavailable 로 올린다(쿼리 오류는 그대로 통과시킨다)."""
    try:
        return psycopg.connect(dsn(), row_factory=dict_row, autocommit=True)
    except psycopg.Error as exc:  # 이 try 안에는 연결뿐이다 — 연결하지 못한 것만 잡는다
        raise unavailable(exc) from None


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
    except psycopg.Error as exc:            # 이 try 안에는 연결뿐이다
        raise unavailable(exc) from None
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except psycopg.OperationalError as exc:
        conn.rollback()
        raise unavailable(exc) from None
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping() -> bool:
    """`/health` 용. 실패는 DbUnavailable 로 올라간다 — True/False 로 뭉개지 않는다."""
    return q("select 1 as ok")[0]["ok"] == 1
