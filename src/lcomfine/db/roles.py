"""앱 DB 역할 — superuser 도 테이블 소유자도 아닌 최소 권한 역할 (decisions.md D-524 · QA3 DEF-QA3-003).

    from lcomfine.db import roles
    roles.apply(cur, "lcomfine_app", password)     # 소유자(스키마를 만든) 연결의 트랜잭션 안에서 부른다

- 업무 테이블: SELECT · INSERT · UPDATE · DELETE. 시퀀스: USAGE · SELECT. 뷰: SELECT.
- **불변 이력 · 감사 로그는 SELECT · INSERT 만** — `APPEND_ONLY` (UPDATE · DELETE · TRUNCATE 권한 없음).
  `stock_adjust` · `shipment_adjust` 는 트리거도 막지만, superuser 가 아니면 `session_replication_role` 로 트리거를 끌 수 없다.
  `sys_change_log` · `sys_access_log` 는 트리거가 없어 이 권한이 유일한 방어선이다.
- 역할 속성: NOSUPERUSER · NOCREATEDB · NOCREATEROLE · NOBYPASSRLS · NOREPLICATION. 스키마 public 에 CREATE 없음(DDL 불가).
- 다시 불러도 같다(멱등) — 역할이 있으면 비밀번호와 속성만 다시 맞추고 권한을 다시 준다.
- 스키마 적용 · 시드 · 백업 복구 검사는 소유자 역할로 돈다(docker-compose 의 `seed` 서비스). 로컬 개발 · 테스트 정리도 소유자 역할이다.
"""

from __future__ import annotations

import re

from psycopg import sql

#: UPDATE · DELETE 를 주지 않는 표 — 이력은 새 행으로만 쌓인다 (db-schema §2 규칙 5 · G-22)
APPEND_ONLY: tuple[str, ...] = (
    "stock_adjust", "shipment_adjust",
    "sys_change_log", "sys_access_log",
)

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def apply(cur, role: str, password: str) -> dict:
    """최소 권한 앱 역할을 만들거나 맞춘다. 반환 = {"role", "created", "tables", "append_only"}.
    비밀번호가 비면 ValueError — 빈 비밀번호로 로그인 역할을 만들지 않는다(조용히 넘어가지 않는다)."""
    if not _ROLE_RE.match(role or ""):
        raise ValueError(f"역할 이름 형식이 아니다: {role!r}")
    if not password:
        raise ValueError("앱 DB 역할 비밀번호가 비었다 — LCOMFINE_APP_DB_PASSWORD 를 .env 에 넣는다")
    r = sql.Identifier(role)
    cur.execute("select 1 from pg_roles where rolname = %s", (role,))
    created = cur.fetchone() is None
    attrs = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION NOINHERIT PASSWORD {}").format(sql.Literal(password))
    cur.execute(sql.SQL("CREATE ROLE {} " if created else "ALTER ROLE {} ").format(r) + attrs)
    cur.execute("select current_database() as db")
    db = cur.fetchone()
    db = db["db"] if isinstance(db, dict) else db[0]
    cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), r))
    cur.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(r))
    cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r))
    cur.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(r))
    cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(r))
    cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(r))
    cur.execute("select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE'")
    tables = {(row["table_name"] if isinstance(row, dict) else row[0]) for row in cur.fetchall()}
    missing = [t for t in APPEND_ONLY if t not in tables]
    if missing:
        raise LookupError(f"불변 이력 표가 스키마에 없다: {missing} — schema.sql 과 roles.APPEND_ONLY 를 맞춘다")
    for t in APPEND_ONLY:
        cur.execute(sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {} FROM {}").format(sql.Identifier(t), r))
    return {"role": role, "created": created, "tables": len(tables), "append_only": list(APPEND_ONLY)}
