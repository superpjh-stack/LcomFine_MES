# tests/test_dev1_sys.py — SYS 사용자 · 역할·권한 · 공통코드 · 로그 — 실제 DB · 시드 뒤 · 만든 행은 지운다
# 시드 계정은 바꾸지 않는다(다른 개발자 테스트가 쓴다). 사용자 변경은 테스트 계정(난수 비밀번호)으로만 한다.
import pytest
from fastapi.testclient import TestClient

from lcomfine.app import rbac
from lcomfine.app.main import app
from lcomfine.db import conn
from test_dev1_common import cleanup, client, login, make_user, uniq


@pytest.fixture
def p():
    prefix = uniq("sys")
    yield prefix
    cleanup(prefix)


# ── SYS-010 사용자 ──
@pytest.mark.fn("F-SYS-011")
def test_user_create(p):
    c = client("admin")
    r = c.post("/sys/users", data={"login_id": p + "N", "user_name": "신규 (예시)", "role_code": "SH", "password": p})
    assert r.status_code == 200, r.text
    row = conn.q1("select role_code, status, password_hash from sys_user where login_id = %s", (p + "N",))
    assert row["role_code"] == "SH" and row["status"] == "정상" and p not in row["password_hash"]
    assert login(p + "N", p).get("/home/notifications").status_code == 200
    assert c.post("/sys/users", data={"login_id": p + "N", "user_name": "x", "role_code": "SH", "password": "x"}).status_code == 422
    assert c.post("/sys/users", data={"login_id": p + "M", "user_name": "x", "role_code": "ZZ", "password": "x"}).status_code == 422
    assert c.post("/sys/users", data={"login_id": p + "M", "user_name": "x", "role_code": "SH"}).status_code == 422
    assert client("pr").post("/sys/users", data={"login_id": p + "M", "user_name": "x", "role_code": "SH",
                                                 "password": "x"}).status_code == 403


@pytest.mark.fn("F-SYS-012")
def test_user_update_role_applies_next_request(p):
    lid, pw, uid = make_user(p, "SL")
    u = login(lid, pw)
    assert u.get("/bas/warehouses").status_code == 403           # 영업부는 BAS-030 칸 없음
    c = client("admin")
    r = c.post(f"/sys/users/{uid}", data={"user_name": "바꾼 이름", "role_code": "PR", "status": "정상"})
    assert r.status_code == 200, r.text
    assert u.get("/bas/warehouses").status_code == 200           # 다음 요청부터 생산부 권한 (세션 그대로)
    r = c.post(f"/sys/users/{uid}", data={"user_name": "x", "role_code": "PR", "status": "잠금"})
    assert r.status_code == 200
    assert u.get("/bas/warehouses", headers={"accept": "application/json"}).status_code == 401
    assert c.post(f"/sys/users/{uid}", data={"login_id": "다른", "user_name": "x", "role_code": "PR",
                                             "status": "정상"}).status_code == 422
    admin_id = rbac.load_user("admin").id
    assert c.post(f"/sys/users/{admin_id}", data={"user_name": "x", "role_code": "ADM",
                                                  "status": "중지"}).status_code == 422   # 자기 계정
    assert c.post("/sys/users/99999999999", data={"user_name": "x", "role_code": "PR", "status": "정상"}).status_code == 404


@pytest.mark.fn("F-SYS-013")
def test_user_deactivate_next_request_401(p):
    lid, pw, uid = make_user(p, "PR")
    u = login(lid, pw)
    assert u.get("/").status_code == 200
    r = client("admin").post(f"/sys/users/{uid}/delete")
    assert r.status_code == 200 and r.json()["status"] == "중지"
    assert conn.q1("select status from sys_user where user_id = %s", (uid,))["status"] == "중지"   # 지우지 않는다
    assert u.get("/", headers={"accept": "application/json"}).status_code == 401
    assert TestClient(app).post("/login", data={"login_id": lid, "password": pw}).status_code == 401
    assert client("admin").post(f"/sys/users/{rbac.load_user('admin').id}/delete").status_code == 422
    assert client("admin").post("/sys/users/99999999999/delete").status_code == 404


@pytest.mark.fn("F-SYS-014")
def test_user_list(p):
    make_user(p, "AC")
    r = client("admin").get("/sys/users", params={"q": p})
    assert r.status_code == 200 and p + "U" in r.text and "pbkdf2" not in r.text.lower()
    assert client("pr").get("/sys/users").status_code == 403


# ── SYS-020 역할·권한 ──
@pytest.mark.fn("F-SYS-021")
def test_roles_save_cell_and_restore(p):
    lid, pw, _ = make_user(p, "ST")
    u = login(lid, pw)
    before = rbac.level("ST", "SYS-030")
    assert before is None
    c = client("admin")
    try:
        r = c.post("/sys/roles", data={"cell:ST:SYS-030": "R"})
        assert r.status_code == 200 and r.json()["changed"] == 1
        assert conn.q1("select level, updated_by from sys_permission where role_code = 'ST' and screen_id = 'SYS-030'") == \
            {"level": "R", "updated_by": "admin"}
        assert u.get("/sys/codes").status_code == 200              # 다음 요청부터 (invalidate)
        assert c.post("/sys/roles", data={"cell:ST:SYS-030": "R"}).json()["changed"] == 0
    finally:
        c.post("/sys/roles", data={"cell:ST:SYS-030": ""})
    assert u.get("/sys/codes").status_code == 403
    # 검증 — 값 · 없는 칸 · 누락 · 전산 관리자 보호
    assert c.post("/sys/roles", data={"cell:ST:SYS-030": "X"}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ZZ:SYS-030": "R"}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ST:NOPE-1": "R"}).status_code == 422
    assert c.post("/sys/roles", data={}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ADM:BAS-010": ""}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ADM:SYS-020": "R"}).status_code == 422
    assert rbac.level("ADM", "SYS-020") == "W"
    assert client("ex").post("/sys/roles", data={"cell:ST:SYS-030": "R"}).status_code == 403


@pytest.mark.fn("F-SYS-022")
def test_roles_view(p):
    r = client("admin").get("/sys/roles")
    assert r.status_code == 200 and "시드를 다시 돌리면 매트릭스" in r.text and 'name="cell:SL:WO-010"' in r.text


# ── SYS-030 공통코드 ──
@pytest.mark.fn("F-SYS-031")
def test_code_save_update_delete(p):
    c = client("admin")
    r = c.post("/sys/codes", data={"group_code": "불량유형", "code": p + "D", "code_name": "불량 (예시)", "sort_no": "9"})
    assert r.status_code == 200 and r.json()["result"] == "등록"
    cid = r.json()["id"]
    assert c.post("/sys/codes", data={"group_code": "불량유형", "code": p + "D", "code_name": "x"}).status_code == 422
    assert c.post("/sys/codes", data={"group_code": "색상", "code": p + "E", "code_name": "x"}).status_code == 422
    assert c.post("/sys/codes", data={"group_code": "설비", "code": p + "E"}).status_code == 422
    r = c.post("/sys/codes", data={"id": str(cid), "code_name": "바꾼 이름", "use_yn": "N"})
    assert r.status_code == 200 and r.json()["result"] == "수정"
    assert conn.q1("select code_name, use_yn from sys_common_code where id = %s", (cid,)) == {"code_name": "바꾼 이름", "use_yn": "N"}
    assert c.post("/sys/codes", data={"id": str(cid), "code": "다른", "code_name": "x"}).status_code == 422
    assert c.post("/sys/codes", data={"id": "99999999999", "code_name": "x"}).status_code == 404
    assert c.post("/sys/codes", data={"id": str(cid), "action": "delete"}).json()["result"] == "삭제"
    # 참조가 있으면 사용 중지 — 설비 코드를 지시가 쓴다
    from test_dev1_common import make_customer, make_item, make_order, make_request
    eq = c.post("/sys/codes", data={"group_code": "설비", "code": p + "EQ", "code_name": "설비 (예시)"}).json()["id"]
    it, cu = make_item(p), make_customer(p)
    rq = make_request(p, customer_id=cu["id"], item_id=it["id"])
    make_order(p, request_id=rq["id"], item_id=it["id"], equipment_code=p + "EQ")
    assert c.post("/sys/codes", data={"id": str(eq), "action": "delete"}).json()["result"] == "사용 중지"
    assert c.post("/sys/codes", data={"action": "delete"}).status_code == 422
    assert client("pr").post("/sys/codes", data={"group_code": "설비", "code": p + "Z", "code_name": "x"}).status_code == 403


@pytest.mark.fn("F-SYS-032")
def test_code_list(p):
    r = client("admin").get("/sys/codes", params={"group": "설비"})
    assert r.status_code == 200 and "설비" in r.text
    assert client("admin").get("/sys/codes", params={"group": "없는그룹"}).status_code == 422


# ── SYS-040 로그 ──
@pytest.mark.fn("F-SYS-041")
def test_logs_three_tabs(p):
    c = client("admin")
    c.post("/sys/codes", data={"group_code": "수금수단", "code": p + "M", "code_name": "x (예시)"})
    r = c.get("/sys/logs", params={"tab": "change", "log_type": "F-SYS-031"})
    assert r.status_code == 200 and f"sys_common_code:수금수단/{p}M" in r.text
    r = c.get("/sys/logs", params={"tab": "access", "login": "admin", "log_type": "조회"})
    assert r.status_code == 200 and "SYS-040" in r.text
    r = c.get("/sys/logs", params={"tab": "ai"})
    assert r.status_code == 200
    if not conn.q1("select count(*) as n from sys_ai_call_log")["n"]:
        assert "미수집" in r.text
    assert c.get("/sys/logs", params={"tab": "x"}).status_code == 422
    assert client("pr").get("/sys/logs").status_code == 403
