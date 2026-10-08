"""영업관리 — 설계도 밖 확장 (D-418). 수주 등록·수정·취소·조회 · 수주 현황 · 거래처 이력 · 수주 → 작업지시 연결.

확장은 설계도 수(대메뉴 12 · 기능 94 · 권한 48칸 · 테이블 30)에 들어가지 않는다 — 그 수가 그대로인지도 여기서 본다.
권한은 작업지시 관리 칸을 따른다: 관리자·생산 입력, 품질·현장 조회. 공통 시드가 들어 있어야 한다(`make db-reset`).
"""
import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from lcomfine.app import contracts, nav, numbering, rbac
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn

ORDERS, STATUS, CUSTOMERS, JOBS = nav.path_of("SAL-01"), nav.path_of("SAL-02"), nav.path_of("SAL-03"), nav.path_of("JOB-01")
TAG = "TEST-SAL"


def client(login_id: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    if login_id:
        r = c.post("/login", data={"login_id": login_id, "password": get_settings().seed_password}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 실패 {r.status_code}"
    return c


@pytest.fixture(scope="module")
def ids():
    fg = conn.q1("select item_id from item where item_type = '제품' and use_yn = 'Y' order by item_code limit 1")
    raw = conn.q1("select item_id from item where item_type = '원재료' and use_yn = 'Y' order by item_code limit 1")
    cu = conn.q1("select customer_id, customer_name from customer where use_yn = 'Y' order by customer_code limit 1")
    fg2 = conn.q1("select item_id from item where item_type = '제품' and use_yn = 'Y' order by item_code offset 1 limit 1")
    assert fg and raw and cu, "공통·개발1 시드가 필요하다 (make db-reset)"
    yield {"item": fg["item_id"], "raw": raw["item_id"], "customer": cu["customer_id"], "customer_name": cu["customer_name"],
           "item2": fg2["item_id"] if fg2 else None}
    conn.x("delete from job where sales_order_id in (select sales_order_id from sales_order where note like %s)", (TAG + "%",))
    conn.x("delete from sales_order where note like %s", (TAG + "%",))


def form(ids, **over):
    base = {"customer_id": ids["customer"], "item_id": ids["item"], "order_qty": "1500.5", "qty_unit": "m",
            "due_date": str(date.today() + timedelta(days=21)), "customer_po": "PO-(예시)-1", "note": TAG}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def change_logs(function_id: str, target: str) -> int:
    return conn.q1("select count(*) as n from sys_access_log where log_type = '변경' and function_id = %s and target = %s",
                   (function_id, target))["n"]


def create(c: TestClient, ids, **over) -> str:
    r = c.post(ORDERS, data=form(ids, **over))
    assert r.status_code == 200, r.text
    return r.json()["order_no"]


# ── 확장은 설계도 수 밖이다 ─────────────────────────────────────────────
def test_extension_sits_outside_the_design_counts():
    assert [m.code for m in nav.EXT_MENUS] == ["SAL"] and [s.screen_id for s in nav.EXT_SCREENS] == ["SAL-01", "SAL-02", "SAL-03"]
    assert (len(nav.MENUS), len(nav.SCREENS)) == (12, 32)                       # 설계도 수 그대로
    fns = contracts.functions()
    assert sum(1 for f in fns if not f.is_batch) == 94 and sum(1 for f in fns if f.is_batch) == 6
    ext = contracts.ext_functions()
    assert [f.id for f in ext] == [f"X-SAL-0{i}" for i in range(1, 7)] and all(f.process == "확장" for f in ext)
    assert sum(1 for f in ext if f.is_write) == 3 and all(f.menu_code == "SAL" for f in ext)
    def walk(routes):                                                             # include_router 덩어리(original_router)를 편다 — tools/check_trace.py 의 all_routes 와 같다
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from walk(inner.routes)
            elif getattr(r, "methods", None):
                yield r

    routes = {(m, r.path) for r in walk(app.routes) for m in (getattr(r, "methods", None) or ())}
    for f in ext:                                                                 # 계약의 API 가 전부 등록돼 있다
        assert (f.method, f.path) in routes, (f.id, sorted(p for _, p in routes if p.startswith("/sal")))
    rbac.invalidate()
    assert rbac.counts()["전체"] == 48                                            # 권한 칸을 늘리지 않았다
    for role in ("ADMIN", "PROD", "QC", "FIELD"):
        assert rbac.cell(role, "SAL") == rbac.cell(role, "JOB")                   # 영업관리 = 작업지시 관리 칸
    assert numbering.rule("SALES_ORDER") is not None
    assert conn.q1("select count(*) as n from information_schema.columns where table_name = 'job' and column_name = 'sales_order_id'")["n"] == 1


# ── 수주 등록 ───────────────────────────────────────────────────────────
@pytest.mark.fn("X-SAL-01")
def test_create_order_numbers_from_numbering_and_logs(ids):
    c = client("admin")
    rule = numbering.rule("SALES_ORDER")
    r = c.post(ORDERS, data=form(ids))
    assert r.status_code == 200, r.text
    body = r.json()
    no = body["order_no"]
    assert body["status"] == "등록" and no.startswith(rule["prefix"]) and re.fullmatch(r"[A-Z0-9-]+", no)
    row = conn.q1("select * from sales_order where order_no = %s", (no,))
    assert (row["customer_id"], row["item_id"], str(row["order_qty"]), row["qty_unit"]) == (ids["customer"], ids["item"], "1500.500", "m")
    assert row["order_date"] == date.today() and row["due_date"] == date.today() + timedelta(days=21)
    assert row["customer_po"] == "PO-(예시)-1" and row["created_by"] == "admin" and row["status"] == "등록"
    assert change_logs("X-SAL-01", f"sales_order:{no}") == 1
    second = create(c, ids, qty_unit=None)                                        # 단위를 비우면 품목의 단위
    assert second != no
    assert conn.q1("select qty_unit from sales_order where order_no = %s", (second,))["qty_unit"] == \
        conn.q1("select unit from item where item_id = %s", (ids["item"],))["unit"]
    assert create(client("prod"), ids) != second                                  # 생산도 입력 (작업지시 관리 칸)


@pytest.mark.fn("X-SAL-01")
def test_create_order_validation_and_permissions(ids):
    c = client("admin")
    before = conn.q1("select count(*) as n from sales_order")["n"]
    bad = [
        {"customer_id": None}, {"item_id": None}, {"order_qty": None}, {"due_date": None},
        {"customer_id": 999999999}, {"item_id": 999999999}, {"item_id": ids["raw"]},
        {"order_qty": "0"}, {"order_qty": "-1"}, {"order_qty": "많이"},
        {"due_date": "2026-13-40"}, {"due_date": str(date.today() - timedelta(days=1))},   # 납기가 수주일(오늘)보다 앞
    ]
    for override in bad:
        r = c.post(ORDERS, data=form(ids, **override))
        assert r.status_code == 422 and r.json()["code"] == "validation_error", (override, r.text)
    assert conn.q1("select count(*) as n from sales_order")["n"] == before
    for login_id in ("qc", "field"):                                              # 조회 역할의 쓰기는 403
        assert client(login_id).post(ORDERS, data=form(ids)).status_code == 403
        assert client(login_id).get(ORDERS).status_code == 200
    assert client().post(ORDERS, data=form(ids)).status_code == 401


# ── 조회 · 현황 · 거래처 이력 ───────────────────────────────────────────
@pytest.mark.fn("X-SAL-04", "X-SAL-05", "X-SAL-06")
def test_screens_show_the_order_and_handle_unknown_numbers(ids):
    c = client("admin")
    no = create(c, ids)
    page = c.get(ORDERS, headers={"accept": "text/html"})
    assert page.status_code == 200 and no in page.text and 'data-scan' not in page.text
    one = c.get(ORDERS, params={"no": no}, headers={"accept": "text/html"}).text
    assert "미지시" in one and "이 수주로 작업지시 등록" in one and f"sales_order_no={no}" in one
    assert c.get(ORDERS, params={"no": "SO-없는-번호"}).status_code == 422          # D-201
    assert c.get(ORDERS, params={"q": "PO-(예시)", "customer_id": str(ids["customer"]), "status": "등록"}).status_code == 200
    status = c.get(STATUS, headers={"accept": "text/html"}).text
    assert no in status and "미지시" in status
    assert c.get(STATUS, params={"late": "1"}).status_code == 200
    assert c.get(STATUS, params={"progress": "지시"}).status_code == 200
    cust = c.get(CUSTOMERS, headers={"accept": "text/html"}).text
    assert ids["customer_name"] in cust
    assert c.get(CUSTOMERS, params={"date_from": "2026-12-31", "date_to": "2026-01-01"}).status_code == 422
    assert c.get(CUSTOMERS, params={"q": ids["customer_name"][:2]}).status_code == 200
    # 품질·현장은 조회만 — 화면은 열린다
    for login_id in ("qc", "field"):
        for path in (ORDERS, STATUS, CUSTOMERS):
            assert client(login_id).get(path).status_code == 200, (login_id, path)


# ── 수주 → 작업지시 ─────────────────────────────────────────────────────
@pytest.mark.fn("X-SAL-04", "X-SAL-05", "X-SAL-03")
def test_job_from_order_links_and_blocks_cancel(ids):
    c = client("admin")
    no = create(c, ids)
    so = conn.q1("select * from sales_order where order_no = %s", (no,))
    page = c.get(JOBS, params={"sales_order_no": no}, headers={"accept": "text/html"})
    assert page.status_code == 200 and f"의 값을 채웠다" in page.text
    assert re.search(rf'name="sales_order_id"[^>]*>.*?<option value="{so["sales_order_id"]}" selected', page.text, re.S)
    assert re.search(rf'name="order_qty" value="1500.500"', page.text)
    assert c.get(JOBS, params={"sales_order_no": "SO-없는-번호"}).status_code == 422
    # 수주와 다른 품목·고객으로는 422
    job_form = {"item_id": ids["item"], "customer_id": ids["customer"], "order_qty": "1500.5", "qty_unit": "m",
                "due_date": str(so["due_date"]), "sales_order_id": so["sales_order_id"], "note": TAG}
    if ids["item2"]:
        assert c.post(JOBS, data={**job_form, "item_id": ids["item2"]}).status_code == 422
    assert c.post(JOBS, data={**job_form, "sales_order_id": 999999999}).status_code == 422
    r = c.post(JOBS, data=job_form)
    assert r.status_code == 200, r.text
    job_no = r.json()["job_no"]
    assert conn.q1("select sales_order_id from job where job_no = %s", (job_no,))["sales_order_id"] == so["sales_order_id"]
    one = c.get(ORDERS, params={"no": no}, headers={"accept": "text/html"}).text
    assert job_no in one and "진행 <b>지시</b>" in one
    assert c.get(STATUS, params={"progress": "지시"}, headers={"accept": "text/html"}).text.count(no) >= 1
    # 작업지시가 걸린 수주는 취소도, 고객·품목·수량 수정도 안 된다
    assert c.post(f"{ORDERS}/{no}/cancel").status_code == 422
    assert c.post(f"{ORDERS}/{no}", data={"order_qty": "10"}).status_code == 422
    assert c.post(f"{ORDERS}/{no}", data={"customer_po": "PO-(예시)-2"}).status_code == 200      # 발주 번호는 바꿀 수 있다
    # 취소된 수주에는 작업지시를 낼 수 없다 — 작업지시를 먼저 취소하면 수주도 취소된다
    assert c.post(f"{JOBS}/{job_no}/cancel").status_code == 200
    assert c.post(f"{ORDERS}/{no}/cancel").status_code == 200
    assert conn.q1("select status from sales_order where order_no = %s", (no,))["status"] == "취소"
    assert change_logs("X-SAL-03", f"sales_order:{no}") == 1
    assert c.post(JOBS, data=job_form).status_code == 422
    assert c.post(f"{ORDERS}/{no}/cancel").status_code == 422                     # 이미 취소
    assert c.post(f"{ORDERS}/{no}", data={"note": TAG + " x"}).status_code == 422  # 취소된 수주는 수정 불가
    cust = c.get(CUSTOMERS, headers={"accept": "text/html"}).text
    assert ids["customer_name"] in cust


# ── 수정 ────────────────────────────────────────────────────────────────
@pytest.mark.fn("X-SAL-02")
def test_update_order(ids):
    c = client("admin")
    no = create(c, ids)
    new_due = str(date.today() + timedelta(days=30))
    r = c.post(f"{ORDERS}/{no}", data={"due_date": new_due, "note": TAG + " 수정", "customer_po": "PO-(예시)-9"})
    assert r.status_code == 200 and sorted(r.json()["changed"]) == ["customer_po", "due_date", "note"]
    row = conn.q1("select * from sales_order where order_no = %s", (no,))
    assert str(row["due_date"]) == new_due and row["updated_by"] == "admin" and row["customer_po"] == "PO-(예시)-9"
    assert change_logs("X-SAL-02", f"sales_order:{no}") == 1
    assert c.post(f"{ORDERS}/{no}", data={"note": TAG + " 수정"}).status_code == 422          # 바꿀 값 없음
    assert c.post(f"{ORDERS}/{no}", data={"due_date": "2000-01-01"}).status_code == 422      # 수주일보다 앞
    assert c.post(f"{ORDERS}/{no}", data={"status": "취소"}).status_code == 422               # 상태는 취소 기능으로
    assert c.post(f"{ORDERS}/{no}", data={"item_id": ids["raw"]}).status_code == 422
    assert c.post(f"{ORDERS}/없는-번호", data={"note": "x"}).status_code == 404
    assert client("qc").post(f"{ORDERS}/{no}", data={"note": "x"}).status_code == 403
    assert c.post(f"{ORDERS}/{no}", data={"order_qty": "2000"}).status_code == 200          # 지시 전이라 수량은 바꿀 수 있다
    assert str(conn.q1("select order_qty from sales_order where order_no = %s", (no,))["order_qty"]) == "2000.000"


# ── 메인 · 권한 화면 · 계약 패널 ────────────────────────────────────────
def test_main_and_permission_screen_show_the_extension():
    c = client("admin")
    main = c.get("/", headers={"accept": "text/html"}).text
    assert 'data-ext-menu="SAL"' in main and "영업관리" in main and 'class="card card-ext"' in main
    assert 'data-group="' not in main and main.index('data-menu="STA"') < main.index('data-menu="SAL"') < main.index('data-menu="JOB"')  # 묶음 없이 그 자리에
    assert main.count('class="card"') == sum(1 for m in nav.MENUS if rbac.cell("ADMIN", m.code).can_read)   # 설계도 카드 수는 그대로
    assert 'data-ext-menu="SAL"' in client("field").get("/", headers={"accept": "text/html"}).text        # 현장은 조회 — 카드가 보인다
    perm = c.get(nav.path_of("SYS-02"), headers={"accept": "text/html"}).text
    assert "영업관리" in perm and "작업지시 관리</b> 칸을 그대로 따른다" in perm
    assert perm.count('class="perm-cell') == 48                                          # 칸은 48 그대로
    one = c.get(ORDERS, headers={"accept": "text/html"}).text
    assert "X-SAL-01" in one and "X-SAL-04" in one                                        # 우측 계약 패널에 확장 기능이 나온다
