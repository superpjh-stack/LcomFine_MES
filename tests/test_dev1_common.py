# tests/test_dev1_common.py — 개발1 테스트 공용 도구 (실제 DB `lcomfine_db` · 시드 뒤)
# 다른 개발자와 같은 DB 를 함께 쓴다 — 만든 행은 고유 접두(T<시각><난수>-)를 달고 테스트 끝에 지운다. 시드 행에 기대지 않는다.
import time
import uuid

import pytest

from fastapi.testclient import TestClient

from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn

_CLIENTS: dict[str, TestClient] = {}


def client(login_id: str) -> TestClient:
    """시드 계정으로 로그인한 TestClient (모듈 사이에서 재사용). 기본 Accept */* → 쓰기 성공 200 JSON · 422 JSON."""
    if login_id not in _CLIENTS:
        pw = get_settings().seed_password
        assert pw, "LCOMFINE_SEED_PASSWORD 미설정 — `make setup`"
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/login", data={"login_id": login_id, "password": pw}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
        _CLIENTS[login_id] = c
    return _CLIENTS[login_id]


def uniq(tag: str = "") -> str:
    return f"T{int(time.time())}{uuid.uuid4().hex[:6]}-{tag}"


def make_item(prefix: str, item_type: str = "제품", use_yn: str = "Y") -> dict:
    return conn.q1("insert into item (item_code, item_name, item_type, use_yn, created_by) values (%s, %s, %s, %s, 'test') "
                   "returning id, item_code", (f"{prefix}{item_type}", f"{prefix} 품목 (예시)", item_type, use_yn))


def make_customer(prefix: str) -> dict:
    return conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'test') "
                   "returning id, customer_code", (f"{prefix}C", f"{prefix} 거래처 (예시)"))


def make_request(prefix: str, *, customer_id: int, item_id: int, qty=10, due="current_date + 2", status="확인대기") -> dict:
    return conn.q1(f"insert into production_request (request_no, customer_id, item_id, qty, due_date, status, created_by) "
                   f"values (%s, %s, %s, %s, {due}, %s, 'test') returning id, request_no",
                   (f"{prefix}REQ", customer_id, item_id, qty, status))


def make_order(prefix: str, *, request_id: int, item_id: int, qty=10, equipment_code=None, status="발행") -> dict:
    return conn.q1("insert into work_order (work_order_no, request_id, item_id, qty, equipment_code, status, created_by) "
                   "values (%s, %s, %s, %s, %s, %s, 'test') returning id, work_order_no",
                   (f"{prefix}WO", request_id, item_id, qty, equipment_code, status))


def cleanup(prefix: str) -> None:
    """접두가 붙은 행을 FK 역순으로 지운다. 개발1 테이블만 + 테스트가 직접 만든 행."""
    like = f"{prefix}%"
    with conn.tx() as cur:
        cur.execute("delete from notification where dedupe_key like %s or message like %s", (f"%{prefix}%", f"%{prefix}%"))
        cur.execute("delete from work_sequence where work_order_id in (select w.id from work_order w "
                    "join production_request r on r.id = w.request_id join item i on i.id = r.item_id where i.item_code like %s)",
                    (like,))
        cur.execute("delete from plate_usage where plate_id in (select id from plate where plate_code like %s) "
                    "or work_order_id in (select w.id from work_order w join item i on i.id = w.item_id where i.item_code like %s)",
                    (like, like))
        cur.execute("delete from work_order where item_id in (select id from item where item_code like %s)", (like,))
        cur.execute("delete from production_request where item_id in (select id from item where item_code like %s) "
                    "or customer_id in (select id from customer where customer_code like %s)", (like, like))
        cur.execute("delete from plate where plate_code like %s", (like,))
        for t in ("spec_sheet", "artwork", "sample_sheet", "exception_item", "plate"):
            cur.execute(f"delete from {t} where item_id in (select id from item where item_code like %s)", (like,))
        cur.execute("delete from standard where standard_code like %s", (like,))
        cur.execute("delete from lot_stock where location_id in (select l.id from location l join warehouse w "
                    "on w.id = l.warehouse_id where w.warehouse_code like %s)", (like,))
        cur.execute("delete from location where warehouse_id in (select id from warehouse where warehouse_code like %s)", (like,))
        cur.execute("delete from warehouse where warehouse_code like %s", (like,))
        cur.execute("delete from item where item_code like %s", (like,))
        cur.execute("delete from customer where customer_code like %s", (like,))
        cur.execute("delete from sys_common_code where code like %s", (like,))
        cur.execute("delete from notification_setting where user_id in (select user_id from sys_user where login_id like %s)",
                    (like,))
        cur.execute("delete from sys_user where login_id like %s", (like,))


def make_user(prefix: str, role_code: str, tag: str = "U") -> tuple[str, str, int]:
    """테스트 계정 — 비밀번호는 실행할 때마다 난수(어디에도 적지 않는다). 반환 (login_id, password, user_id)."""
    import secrets

    from lcomfine.app import auth
    login_id, pw = f"{prefix}{tag}", secrets.token_urlsafe(12)
    uid = conn.q1("insert into sys_user (login_id, user_name, password_hash, role_code, created_by) "
                  "values (%s, %s, %s, %s, 'test') returning user_id",
                  (login_id, f"{prefix} 사용자 (예시)", auth.hash_password(pw), role_code))["user_id"]
    return login_id, pw, uid


def login(login_id: str, password: str) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"login_id": login_id, "password": password}, follow_redirects=False)
    assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
    return c


def test_helpers_make_and_cleanup():
    p = uniq("h")
    it = make_item(p)
    assert it["item_code"].startswith(p)
    cleanup(p)
    assert conn.q1("select count(*) as n from item where item_code like %s", (p + "%",))["n"] == 0


@pytest.mark.fn("F-BAS-011")
@pytest.mark.fn("F-BAS-021")
@pytest.mark.fn("F-BAS-031")
@pytest.mark.fn("F-STD-021")
@pytest.mark.fn("F-WO-011")
@pytest.mark.fn("F-SYS-011")
@pytest.mark.fn("F-SYS-031")
def test_nul_input_names_the_field_dev1():
    """DEF-QA3-002 · api-contract §3 — 글자 속 NUL(0x00) 은 라우터가 먼저 422 로 막고 어느 항목인지 짚는다
    (핸들러의 `입력` 한 줄은 마지막 방어선). 개발2 와 같은 문장 「<항목>: 글자에 NUL(0x00)을 넣을 수 없습니다」."""
    p = uniq("nul")
    cu, it = make_customer(p), make_item(p)
    try:
        cases = [
            ("admin", "/bas/items", {"item_code": f"{p}a\x00b", "item_name": "x (예시)", "item_type": "제품"}, "품목 코드"),
            ("admin", "/bas/items", {"item_code": f"{p}ok", "item_name": "x (예시)", "item_type": "제품", "spec": "a\x00b"}, "규격"),
            ("admin", "/bas/customers", {"customer_code": f"{p}c", "customer_name": "a\x00b"}, "거래처명"),
            ("admin", "/bas/customers", {"customer_code": f"{p}c", "customer_name": "x (예시)", "phone": "0\x001"}, "연락처"),
            ("admin", "/bas/warehouses", {"target": "warehouse", "warehouse_code": f"{p}w", "warehouse_name": "x (예시)",
                                          "note": "a\x00b"}, "비고"),
            ("admin", "/std/standards", {"standard_code": f"{p}s", "standard_name": "x (예시)", "content": "a=\x00"}, "조건 항목"),
            ("sl", "/wo/requests", {"customer_id": str(cu["id"]), "item_id": str(it["id"]), "qty": "5",
                                    "due_date": "2027-01-31", "note": "a\x00b"}, "비고"),
            ("admin", "/sys/users", {"login_id": f"{p}u\x00", "user_name": "x (예시)", "role_code": "SL", "password": "x"},
             "사번(로그인 ID)"),
            ("admin", "/sys/codes", {"group_code": "설비", "code": "a\x00b", "code_name": "x (예시)", "sort_no": "1"}, "코드 값"),
            ("admin", "/sys/codes", {"group_code": "설비", "code": f"{p}c", "code_name": "x\x00", "sort_no": "1"}, "코드 이름"),
        ]
        for role, path, body, label in cases:
            r = client(role).post(path, data=body)
            assert r.status_code == 422, f"{path} {label} → {r.status_code} {r.text[:200]}"
            j = r.json()
            assert j["fields"] == [{"name": label, "reason": "글자에 NUL(0x00)을 넣을 수 없습니다"}], f"{path} {label} → {j}"
            assert j["message"] == f"{label}: 글자에 NUL(0x00)을 넣을 수 없습니다", j["message"]
        # 조회 인자도 같은 문장으로 422 (500 이 아니다)
        r = client("admin").get("/bas/items", params={"q": "a\x00b"})
        assert r.status_code == 422 and r.json()["fields"][0]["name"] == "검색어", r.text[:200]
    finally:
        cleanup(p)
