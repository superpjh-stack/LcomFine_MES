# tests/test_arch_rbac.py — 화면 단위 권한 · 시드 (D-511 · D-514 · 데이터 질의 제거 D-529) — 실제 DB `lcomfine_db` · 시드 뒤
# 로그인은 `auth.authenticate` 를 거치지 않는다(접근 로그를 남기지 않으려고). 세션은 `auth.login_session` 이 연다.
import secrets
from collections import Counter

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from lcomfine.app import auth, contracts, nav, rbac
from lcomfine.db import conn, seed


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(16))   # 테스트마다 난수 — 값을 적지 않는다

    @app.get("/_login/{login_id}")
    def _login(request: Request, login_id: str):
        user = rbac.load_user(login_id)
        assert user is not None, f"시드 계정 없음: {login_id}"
        auth.login_session(request, user)
        return {"ok": True}

    @app.post("/_revoke")
    def _revoke(request: Request):   # auth.logout_session 과 같은 무효화 — 접근 로그는 남기지 않는다
        user = rbac.require_login(request)
        auth.revoke_session(user.login_id, str(request.session[rbac.SESSION_ID_KEY]))
        return {"ok": True}

    @app.get("/bas-010")
    def _bas(user=rbac.require_screen("BAS-010")):
        return {"login_id": user.login_id}

    @app.post("/bas-items")
    def _bas_write(user=rbac.require_fn("F-BAS-011")):
        return {"login_id": user.login_id}

    @app.post("/home-handle")
    def _handle(user=rbac.require_fn("F-HOME-022")):   # 권한 예외 — 화면 R 이상이면 통과
        return {"login_id": user.login_id}


    return app


def _client(login_id: str | None) -> TestClient:
    c = TestClient(_app())
    if login_id:
        assert c.get(f"/_login/{login_id}").status_code == 200
    return c


def _cell(screen_id: str, role_code: str) -> str | None:
    return dict(((s, r), lv) for s, r, lv in contracts.permission_cells()).get((screen_id, role_code))


def test_permission_cells_seeded_257():
    rows = conn.q("select role_code, screen_id, level from sys_permission")
    assert len(rows) == 257
    assert Counter(r["level"] for r in rows) == {"W": 64, "R": 193}
    assert not [r for r in rows if r["screen_id"] == "RPT-130"]   # D-529
    assert {(r["screen_id"], r["role_code"], r["level"]) for r in rows} == set(contracts.permission_cells())
    assert [r["role_code"] for r in conn.q("select role_code from sys_role order by sort_no")] == list(contracts.ROLE_CODES.values())
    assert {r["role_name"] for r in conn.q("select role_name from sys_role")} == set(contracts.ROLE_CODES)
    assert conn.q1("select count(*) as n from sys_user where created_by = 'seed'")["n"] == 8
    rbac.invalidate()
    assert rbac.counts() == {"W": 64, "R": 193, "전체": 257}


def test_seed_number_rules_and_codes():
    rules = {r["seq_kind"]: r for r in conn.q("select * from sys_number_rule")}
    assert set(rules) == {"REQ", "WO", "MLOT", "PLOT", "SHP", "ERP"}   # 질의 로그 DQ 는 D-529 로 없앴다
    for kind, r in rules.items():   # D-509 — `KIND-YYMM-nnnn`
        assert (r["prefix"], r["date_format"], r["seq_digits"]) == (f"{kind}-", "YYMM-", 4)
        assert "(예시)" in r["note"] and "D-509" in r["note"]
    groups = Counter(r["group_code"] for r in conn.q("select group_code, code_name from sys_common_code"))
    assert groups == {"설비": 2, "불량유형": 3, "수금수단": 3}
    assert all("(예시)" in r["code_name"] for r in conn.q("select code_name from sys_common_code"))


def test_require_login_401():
    assert _client(None).get("/bas-010").status_code == 401


def test_require_screen_403_without_cell():
    assert _cell("BAS-010", "DS") is None   # 정본 칸 `·` — 디자인·개발실은 품목 관리가 없다
    r = _client("ds").get("/bas-010")
    assert r.status_code == 403
    assert r.json()["detail"]["message"] == "이 화면을 볼 권한이 없습니다"
    assert _cell("BAS-010", "SH") == "R"
    assert _client("sh").get("/bas-010").status_code == 200


@pytest.mark.fn("F-BAS-011")
def test_require_fn_w_only():
    assert _cell("BAS-010", "SL") == "R" and _cell("BAS-010", "PR") == "W"
    r = _client("sl").post("/bas-items")
    assert r.status_code == 403
    assert r.json()["detail"]["message"] == "이 기능을 실행할 권한이 없습니다"
    assert _client("pr").post("/bas-items").status_code == 200
    assert _cell("BAS-010", "DS") is None
    assert _client("ds").post("/bas-items").status_code == 403   # 칸 없음


@pytest.mark.fn("F-HOME-022")
def test_require_fn_permission_exception_reads_r():
    assert contracts.function("F-HOME-022").read_ok and _cell("HOME-020", "SL") == "R"
    assert _client("sl").post("/home-handle").status_code == 200
    # 권한 예외라도 그 화면 칸이 없으면 403 (api-contract §4) — SL 의 HOME-020 칸을 잠깐 지우고 되돌린다
    try:
        conn.x("delete from sys_permission where role_code = 'SL' and screen_id = 'HOME-020'")
        rbac.invalidate()
        assert _client("sl").post("/home-handle").status_code == 403
    finally:
        conn.x("""insert into sys_permission (role_code, screen_id, level, updated_at, updated_by) values ('SL', 'HOME-020', 'R', now(), 'seed')
                  on conflict (role_code, screen_id) do nothing""")
        rbac.invalidate()
    assert _client("sl").post("/home-handle").status_code == 200


def test_can_and_visible_menu():
    sl, ds = rbac.load_user("sl"), rbac.load_user("ds")
    assert rbac.can(sl, "BAS-010", "R") and not rbac.can(sl, "BAS-010", "W")
    assert rbac.can(rbac.load_user("pr"), "BAS-010", "W")
    assert not rbac.can(ds, "BAS-010", "R")
    shown = {sc.screen_id for node in rbac.visible_menu(ds) for m in node["menus"] for sc in m.screens}
    assert shown == {s for s, r, _ in contracts.permission_cells() if r == "DS"}
    for node in rbac.visible_menu(ds):
        assert node["menus"] and all(m.screens for m in node["menus"])
    flow = rbac.can_flow(ds)
    assert [s for s, _ in flow] == list(nav.FLOW)
    assert all(ok == rbac.can(ds, s, "R") for s, ok in flow)
    assert rbac.visible_menu(None) == []


def test_seed_idempotent():
    seed.main(["--common-only"])
    before = seed.table_counts()
    seed.main(["--common-only"])
    after = seed.table_counts()
    assert before == after
    assert after["sys_permission"] == 257 and after["sys_role"] == 8 and after["sys_number_rule"] == 6


class _Rollback(Exception):
    pass


def test_numbering_six_kinds():
    import re

    from lcomfine.app import numbering

    assert numbering.KINDS == ("REQ", "WO", "MLOT", "PLOT", "SHP", "ERP")
    with pytest.raises(ValueError):
        numbering.next("JOB")
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            for kind in numbering.KINDS:   # D-509 `KIND-YYMM-nnnn` (예시) — 롤백으로 카운터를 남기지 않는다
                a, b = numbering.next(kind, cur), numbering.next(kind, cur=cur)
                assert re.fullmatch(rf"{kind}-\d{{4}}-\d{{4}}", a) and int(b[-4:]) == int(a[-4:]) + 1
            raise _Rollback


# ── 세션 규칙 (D-26) — 요청마다 DB 로 판정한다. 바꾼 값은 finally 에서 되돌린다 ──
def test_suspended_user_gets_401_on_next_request():
    c = _client("sh")
    assert c.get("/bas-010").status_code == 200
    try:
        conn.x("update sys_user set status = '중지' where login_id = 'sh'")
        assert c.get("/bas-010").status_code == 401
    finally:
        conn.x("update sys_user set status = %s where login_id = 'sh'", (rbac.STATUS_ACTIVE,))
    assert c.get("/bas-010").status_code == 401   # 정상으로 되돌려도 옛 세션은 살아나지 않는다
    assert _client("sh").get("/bas-010").status_code == 200


def test_role_change_applies_next_request():
    assert _cell("BAS-010", "SH") == "R" and _cell("BAS-010", "DS") is None
    c = _client("sh")
    assert c.get("/bas-010").status_code == 200
    try:
        conn.x("update sys_user set role_code = 'DS' where login_id = 'sh'")
        assert c.get("/bas-010").status_code == 403   # 끊기지 않고 새 부서의 칸이 적용된다
    finally:
        conn.x("update sys_user set role_code = 'SH' where login_id = 'sh'")
    assert c.get("/bas-010").status_code == 200


def test_logout_or_epoch_bump_invalidates_session():
    c = _client("sl")
    assert c.get("/bas-010").status_code == 200
    conn.x("update sys_user set session_epoch = session_epoch + 1 where login_id = 'sl'")   # 상태·비밀번호 변경 트리거와 같은 효과
    assert c.get("/bas-010").status_code == 401
    # 로그아웃 — 그 세션 ID 를 서버에서 무효로 만든다. 로그아웃 전의 쿠키를 다시 보내도 401
    c2 = _client("sl")
    before = dict(c2.cookies)
    assert c2.get("/bas-010").status_code == 200
    assert c2.post("/_revoke").status_code == 200
    c2.cookies.clear()
    c2.cookies.update(before)
    assert c2.get("/bas-010").status_code == 401
    conn.x("update sys_user set revoked_sessions = '{}'::jsonb where login_id = 'sl'")
