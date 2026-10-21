# tests/test_dev1_bas.py — BAS 기준정보 (품목 · 거래처 · 창고·위치) — 실제 DB · 시드 뒤 · 만든 행은 지운다
import pytest

from lcomfine.db import conn
from test_dev1_common import cleanup, client, make_item, uniq


@pytest.fixture
def p():
    prefix = uniq("bas")
    yield prefix
    cleanup(prefix)


# ── BAS-010 품목 ──
@pytest.mark.fn("F-BAS-011")
def test_item_create_dup_and_missing(p):
    c = client("pr")
    r = c.post("/bas/items", data={"item_code": p + "I1", "item_name": "품목 (예시)", "item_type": "제품"})
    assert r.status_code == 200, r.text
    assert conn.q1("select item_type, created_by from item where item_code = %s", (p + "I1",)) == \
        {"item_type": "제품", "created_by": "pr"}
    r = c.post("/bas/items", data={"item_code": p + "I1", "item_name": "x", "item_type": "제품"})
    assert r.status_code == 422 and "이미 있는 품목 코드" in r.json()["message"]
    r = c.post("/bas/items", data={"item_code": p + "I2", "item_type": "제품"})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "품목명"
    r = c.post("/bas/items", data={"item_code": p + "I3", "item_name": "x", "item_type": "반제품"})
    assert r.status_code == 422
    assert client("sl").post("/bas/items", data={"item_code": p + "I4", "item_name": "x", "item_type": "제품"}).status_code == 403
    log = conn.q1("select function_id, login_id from sys_change_log where target = %s order by id desc limit 1",
                  (f"item:{p}I1",))
    assert log == {"function_id": "F-BAS-011", "login_id": "pr"}


@pytest.mark.fn("F-BAS-012")
def test_item_update_code_fixed(p):
    it = make_item(p)
    c = client("admin")
    r = c.post(f"/bas/items/{it['id']}", data={"item_name": "바꾼 이름 (예시)", "item_type": "제품", "use_yn": "N"})
    assert r.status_code == 200, r.text
    assert conn.q1("select item_name, use_yn from item where id = %s", (it["id"],)) == \
        {"item_name": "바꾼 이름 (예시)", "use_yn": "N"}
    r = c.post(f"/bas/items/{it['id']}", data={"item_code": "OTHER", "item_name": "x", "item_type": "제품"})
    assert r.status_code == 422 and "바꿀 수 없습니다" in r.json()["message"]
    assert c.post("/bas/items/999999999999", data={"item_name": "x", "item_type": "제품"}).status_code == 404
    assert c.post("/bas/items/abc", data={"item_name": "x", "item_type": "제품"}).status_code == 404
    assert c.post(f"/bas/items/{it['id']}", data={"item_type": "제품"}).status_code == 422


@pytest.mark.fn("F-BAS-013")
def test_item_delete_or_disable(p):
    from test_dev1_common import make_customer, make_request
    free = make_item(p + "A")
    used = make_item(p + "B")
    cu = make_customer(p)
    make_request(p, customer_id=cu["id"], item_id=used["id"])
    c = client("pr")
    r = c.post(f"/bas/items/{free['id']}/delete")
    assert r.status_code == 200 and r.json()["result"] == "삭제"
    assert conn.q1("select 1 from item where id = %s", (free["id"],)) is None
    r = c.post(f"/bas/items/{used['id']}/delete")
    assert r.status_code == 200 and r.json()["result"] == "사용 중지"
    assert conn.q1("select use_yn from item where id = %s", (used["id"],))["use_yn"] == "N"
    assert c.post("/bas/items/0/delete").status_code == 404


@pytest.mark.fn("F-BAS-014")
def test_item_list_search(p):
    make_item(p)
    c = client("sl")   # R 이상
    r = c.get("/bas/items", params={"q": p})
    assert r.status_code == 200 and p in r.text and "미구현" not in r.text
    r = c.get("/bas/items", params={"q": p + "없음"})
    assert "미수집" in r.text
    assert client("admin").get("/bas/items", params={"edit": "x"}).status_code == 404


# ── BAS-020 거래처 ──
@pytest.mark.fn("F-BAS-021")
def test_customer_create(p):
    c = client("sl")
    r = c.post("/bas/customers", data={"customer_code": p + "C1", "customer_name": "거래처 (예시)"})
    assert r.status_code == 200
    assert c.post("/bas/customers", data={"customer_code": p + "C1", "customer_name": "x"}).status_code == 422
    assert c.post("/bas/customers", data={"customer_code": p + "C2"}).status_code == 422
    assert client("pr").post("/bas/customers", data={"customer_code": p + "C3", "customer_name": "x"}).status_code == 403


@pytest.mark.fn("F-BAS-022")
def test_customer_update(p):
    cid = conn.q1("insert into customer (customer_code, customer_name) values (%s, 'x') returning id", (p + "C",))["id"]
    c = client("sl")
    r = c.post(f"/bas/customers/{cid}", data={"customer_name": "새 이름 (예시)", "phone": "000", "use_yn": "Y"})
    assert r.status_code == 200
    assert conn.q1("select customer_name, phone from customer where id = %s", (cid,)) == \
        {"customer_name": "새 이름 (예시)", "phone": "000"}
    assert c.post(f"/bas/customers/{cid}", data={"customer_code": "Z", "customer_name": "x"}).status_code == 422
    assert c.post("/bas/customers/123456789012/x").status_code in (404, 405)
    assert c.post("/bas/customers/123456789012", data={"customer_name": "x"}).status_code == 404


@pytest.mark.fn("F-BAS-023")
def test_customer_delete(p):
    cid = conn.q1("insert into customer (customer_code, customer_name) values (%s, 'x') returning id", (p + "C",))["id"]
    r = client("admin").post(f"/bas/customers/{cid}/delete")
    assert r.status_code == 200 and r.json()["result"] == "삭제"
    assert client("admin").post(f"/bas/customers/{cid}/delete").status_code == 404


@pytest.mark.fn("F-BAS-024")
def test_customer_list(p):
    conn.x("insert into customer (customer_code, customer_name) values (%s, 'x (예시)')", (p + "C",))
    r = client("ac").get("/bas/customers", params={"q": p})
    assert r.status_code == 200 and p + "C" in r.text


# ── BAS-030 창고·위치 ──
def _wh(p, code="W"):
    return conn.q1("insert into warehouse (warehouse_code, warehouse_name) values (%s, 'w (예시)') returning id",
                   (p + code,))["id"]


@pytest.mark.fn("F-BAS-031")
def test_warehouse_and_location_create(p):
    c = client("pr")
    r = c.post("/bas/warehouses", data={"warehouse_code": p + "W", "warehouse_name": "창고 (예시)"})
    assert r.status_code == 200
    wid = r.json()["id"]
    r = c.post("/bas/warehouses", data={"target": "location", "warehouse_id": str(wid), "location_code": "L1",
                                        "location_name": "랙 (예시)"})
    assert r.status_code == 200
    assert c.post("/bas/warehouses", data={"target": "location", "warehouse_id": str(wid), "location_code": "L1",
                                           "location_name": "x"}).status_code == 422          # 창고 안 중복
    assert c.post("/bas/warehouses", data={"warehouse_code": p + "W", "warehouse_name": "x"}).status_code == 422
    assert c.post("/bas/warehouses", data={"target": "location", "location_code": "L2",
                                           "location_name": "x"}).status_code == 422          # 창고 누락
    assert c.post("/bas/warehouses", data={"target": "location", "warehouse_id": "99999999999",
                                           "location_code": "L2", "location_name": "x"}).status_code == 422


@pytest.mark.fn("F-BAS-032")
def test_warehouse_update(p):
    wid = _wh(p)
    lid = conn.q1("insert into location (warehouse_id, location_code, location_name) values (%s, 'L', 'x') returning id",
                  (wid,))["id"]
    c = client("admin")
    assert c.post(f"/bas/warehouses/{wid}", data={"warehouse_name": "새 창고 (예시)"}).status_code == 200
    assert c.post(f"/bas/warehouses/{lid}", data={"target": "location", "location_name": "새 위치 (예시)",
                                                  "use_yn": "N"}).status_code == 200
    assert conn.q1("select location_name, use_yn from location where id = %s", (lid,)) == \
        {"location_name": "새 위치 (예시)", "use_yn": "N"}
    assert c.post(f"/bas/warehouses/{wid}", data={"warehouse_code": "X", "warehouse_name": "x"}).status_code == 422
    assert c.post("/bas/warehouses/99999999999", data={"warehouse_name": "x"}).status_code == 404


@pytest.mark.fn("F-BAS-033")
def test_location_with_stock_cannot_delete(p):
    wid = _wh(p)
    lid = conn.q1("insert into location (warehouse_id, location_code, location_name) values (%s, 'L', 'x') returning id",
                  (wid,))["id"]
    conn.x("insert into lot_stock (lot_kind, lot_id, location_id, qty, status) values ('원자재', -1, %s, 5, '가용')", (lid,))
    c = client("pr")
    r = c.post(f"/bas/warehouses/{lid}/delete", data={"target": "location"})
    assert r.status_code == 422 and "재고가 남은 위치" in r.json()["message"]
    assert c.post(f"/bas/warehouses/{wid}/delete").status_code == 422
    conn.x("update lot_stock set qty = 0 where location_id = %s", (lid,))
    r = c.post(f"/bas/warehouses/{lid}/delete", data={"target": "location"})      # 재고 0 행이 참조 → 사용 중지
    assert r.status_code == 200 and r.json()["result"] == "사용 중지"
    empty = _wh(p, "E")
    r = c.post(f"/bas/warehouses/{empty}/delete")
    assert r.status_code == 200 and r.json()["result"] == "삭제"


@pytest.mark.fn("F-BAS-034")
def test_warehouse_list(p):
    _wh(p)
    r = client("pr").get("/bas/warehouses")
    assert client("sh").get("/bas/warehouses").status_code == 403
    assert r.status_code == 200 and p + "W" in r.text
