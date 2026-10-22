"""D-524 · DEF-QA3-003 — 앱 DB 역할은 superuser 가 아니고 불변 이력 · 감사 로그를 고치거나 지울 수 없다.

역할은 한 트랜잭션 안에서 만들고 끝에 되돌린다(CREATE ROLE 도 트랜잭션에 묶인다) — 클러스터에 역할이 남지 않는다.
"""

import secrets

import psycopg
import pytest

from lcomfine.db import conn, roles

KEY = {"sys_access_log": "logged_at"}   # 갱신 시도에 쓸 열 (log_id 는 GENERATED ALWAYS)
ROLE = "lcomfine_app_t" + secrets.token_hex(3)


class _Rollback(Exception):
    pass


def _expect_denied(cur, stmt, params=()):
    cur.execute("savepoint s")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute(stmt, params)
    cur.execute("rollback to savepoint s")


def test_app_role_is_least_privilege():
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            out = roles.apply(cur, ROLE, secrets.token_urlsafe(16))
            assert out["created"] and out["tables"] >= 48
            cur.execute("select rolsuper, rolcreatedb, rolcreaterole, rolbypassrls from pg_roles where rolname = %s", (ROLE,))
            assert cur.fetchone() == {"rolsuper": False, "rolcreatedb": False, "rolcreaterole": False, "rolbypassrls": False}
            # 다시 불러도 같다(멱등)
            assert roles.apply(cur, ROLE, secrets.token_urlsafe(16))["created"] is False

            cur.execute(f'set local role "{ROLE}"')
            # 읽기 · 업무 쓰기는 된다
            cur.execute("select count(*) as n from sys_role")
            assert cur.fetchone()["n"] >= 8
            cur.execute("select count(*) as n from v_dq_orders")
            cur.execute("insert into sys_access_log (log_type, login_id, result) values ('조회', 'roles-test', '성공') returning log_id")
            log_id = cur.fetchone()["log_id"]
            # 불변 이력 · 감사 로그는 고치거나 지울 수 없다
            for t in roles.APPEND_ONLY:
                _expect_denied(cur, f"update {t} set {KEY.get(t, 'id')} = {KEY.get(t, 'id')} where false")
                _expect_denied(cur, f"delete from {t} where false")
            _expect_denied(cur, "delete from sys_access_log where log_id = %s", (log_id,))
            # 트리거를 끌 수 없다(superuser 아님) · DDL 불가
            _expect_denied(cur, "set local session_replication_role = replica")
            _expect_denied(cur, "create table roles_test_x (id int)")
            _expect_denied(cur, "alter table stock_adjust disable trigger all")
            raise _Rollback

    with conn.tx() as cur:
        cur.execute("select count(*) as n from pg_roles where rolname = %s", (ROLE,))
        assert cur.fetchone()["n"] == 0


def test_apply_refuses_empty_password_and_bad_name():
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            with pytest.raises(ValueError):
                roles.apply(cur, ROLE, "")
            with pytest.raises(ValueError):
                roles.apply(cur, "bad-name; drop", "x")
            raise _Rollback
