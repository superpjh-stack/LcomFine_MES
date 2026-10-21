# tests/test_dev1_wo.py — WO 작업지시 (의뢰 · 지시 · 순서 · 공정상태) — 실제 DB · 시드 뒤 · 만든 행은 지운다
# 번호는 진짜 numbering.next 로 나온다(카운터가 오른다 — 되돌리지 않는다). 알림은 그 번호의 dedupe_key 로 지운다.
import pytest

from lcomfine.app import nav
from lcomfine.db import conn
from test_dev1_common import cleanup, client, make_customer, make_item, make_order, make_request, uniq


@pytest.fixture
def p():
    prefix = uniq("wo")
    keys: list[str] = []
    yield prefix, keys
    if keys:
        conn.x("delete from notification where dedupe_key = any(%s)", (keys,))
    cleanup(prefix)


def _base(prefix):
    return make_item(prefix), make_customer(prefix)


# ── WO-010 생산의뢰서 ──
@pytest.mark.fn("F-WO-011")
def test_request_create_numbers_and_notifies(p):
    prefix, keys = p
    it, cu = _base(prefix)
    r = client("sl").post("/wo/requests", data={"customer_id": str(cu["id"]), "item_id": str(it["id"]), "qty": "100",
                                                "due_date": "2026-11-30", "note": "발주 요약 (예시)"})
    assert r.status_code == 200, r.text
    no = r.json()["request_no"]
    keys.append(f"request_created:{no}")
    row = conn.q1("select status, qty, created_by from production_request where request_no = %s", (no,))
    assert row["status"] == "확인대기" and row["created_by"] == "sl"
    n = conn.q("select to_role, link from notification where dedupe_key = %s order by to_role", (f"request_created:{no}",))
    assert [x["to_role"] for x in n] == ["DS", "PR"]
    assert n[0]["link"] == nav.path_of("WO-010") + f"?q={no}"
    # 누락 · 사용 중지 품목 · 형식
    c = client("pr")
    assert c.post("/wo/requests", data={"customer_id": str(cu["id"]), "qty": "1", "due_date": "2026-11-30"}).status_code == 422
    off = make_item(prefix + "X", use_yn="N")
    r = c.post("/wo/requests", data={"customer_id": str(cu["id"]), "item_id": str(off["id"]), "qty": "1",
                                     "due_date": "2026-11-30"})
    assert r.status_code == 422 and "사용 중지" in r.json()["fields"][0]["reason"]
    assert c.post("/wo/requests", data={"customer_id": str(cu["id"]), "item_id": str(it["id"]), "qty": "-1",
                                        "due_date": "2026-11-30"}).status_code == 422
    assert c.post("/wo/requests", data={"customer_id": str(cu["id"]), "item_id": str(it["id"]), "qty": "1",
                                        "due_date": "30/11"}).status_code == 422
    assert client("ds").post("/wo/requests", data={"customer_id": str(cu["id"]), "item_id": str(it["id"]), "qty": "1",
                                                   "due_date": "2026-11-30"}).status_code == 403


@pytest.mark.fn("F-WO-012")
def test_request_update_status_rules(p):
    prefix, _ = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    c = client("sl")
    data = {"customer_id": str(cu["id"]), "item_id": str(it["id"]), "qty": "20", "due_date": "2026-12-01"}
    r = c.post(f"/wo/requests/{rq['id']}", data={**data, "status": "확정"})
    assert r.status_code == 200, r.text
    assert conn.q1("select status, qty from production_request where id = %s", (rq["id"],)) == {"status": "확정", "qty": 20}
    assert c.post(f"/wo/requests/{rq['id']}", data={**data, "status": "지시완료"}).status_code == 422
    assert c.post(f"/wo/requests/{rq['id']}", data={**data, "status": "확정", "request_no": "BAD"}).status_code == 422
    make_order(prefix, request_id=rq["id"], item_id=it["id"])
    conn.x("update production_request set status = '지시완료' where id = %s", (rq["id"],))
    r = c.post(f"/wo/requests/{rq['id']}", data={**data, "status": "취소"})
    assert r.status_code == 422 and "지시" in r.json()["message"]
    assert c.post(f"/wo/requests/{rq['id']}", data={**data, "status": "지시완료"}).status_code == 200
    assert c.post("/wo/requests/99999999999", data={**data, "status": "확정"}).status_code == 404


@pytest.mark.fn("F-WO-013")
def test_request_list_search(p):
    prefix, _ = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    r = client("ds").get("/wo/requests", params={"q": rq["request_no"]})
    assert r.status_code == 200 and rq["request_no"] in r.text
    r = client("ex").get("/wo/requests", params={"customer": str(cu["id"]), "due_from": "2000-01-01", "status": "확인대기"})
    assert r.status_code == 200 and rq["request_no"] in r.text
    assert client("ex").get("/wo/requests", params={"due_from": "abc"}).status_code == 422
    assert client("sh").get("/wo/requests").status_code == 403


# ── WO-020 생산지시서 ──
@pytest.mark.fn("F-WO-021")
def test_order_create_from_request(p):
    prefix, keys = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"], status="확정")
    spec = conn.q1("insert into spec_sheet (item_id, title) values (%s, 'x') returning id", (it["id"],))["id"]
    other = make_item(prefix + "O")
    other_spec = conn.q1("insert into spec_sheet (item_id, title) values (%s, 'x') returning id", (other["id"],))["id"]
    # 알림을 눌러 연 화면에서 처리하면 닫힌다 — 의뢰 알림을 미리 만든다
    from lcomfine.app import notify
    from lcomfine.app.routers.wo import request_link
    with conn.tx() as cur:
        notify.emit(cur, "request_created", link=request_link(rq["request_no"]),
                    dedupe_key=f"request_created:{rq['request_no']}", text=f"{prefix} 의뢰")
    c = client("pr")
    r = c.post("/wo/orders", data={"request_id": str(rq["id"]), "spec_sheet_id": str(spec), "qty": "10"})
    assert r.status_code == 200, r.text
    no = r.json()["work_order_no"]
    keys.append(f"order_issued:{no}")
    w = conn.q1("select status, item_id, spec_sheet_id from work_order where work_order_no = %s", (no,))
    assert w == {"status": "발행", "item_id": it["id"], "spec_sheet_id": spec}
    assert conn.q1("select status from production_request where id = %s", (rq["id"],))["status"] == "지시완료"
    n = conn.q("select to_role, link from notification where dedupe_key = %s", (f"order_issued:{no}",))
    assert n == [{"to_role": "PR", "link": nav.path_of("MAT-020") + f"?wo={no}"}]
    handled = conn.q("select to_role, handled_by from notification where dedupe_key = %s order by to_role",
                     (f"request_created:{rq['request_no']}",))
    assert handled == [{"to_role": "DS", "handled_by": None}, {"to_role": "PR", "handled_by": "pr"}]
    # 다른 제품의 사양 422 · 없는 의뢰 404 · 취소 의뢰 422 · 누락 422 · 권한
    assert c.post("/wo/orders", data={"request_id": str(rq["id"]), "spec_sheet_id": str(other_spec),
                                      "qty": "1"}).status_code == 422
    assert c.post("/wo/orders", data={"request_no": "없는의뢰", "qty": "1"}).status_code == 404
    cancel = make_request(prefix + "C", customer_id=cu["id"], item_id=it["id"], status="취소")
    assert c.post("/wo/orders", data={"request_id": str(cancel["id"]), "qty": "1"}).status_code == 422
    assert c.post("/wo/orders", data={"qty": "1"}).status_code == 422
    assert c.post("/wo/orders", data={"request_id": str(rq["id"]), "qty": "1", "equipment_code": "없는설비"}).status_code == 422
    assert client("sl").post("/wo/orders", data={"request_id": str(rq["id"]), "qty": "1"}).status_code == 403


@pytest.mark.fn("F-WO-022")
def test_order_update(p):
    prefix, _ = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    wo = make_order(prefix, request_id=rq["id"], item_id=it["id"])
    c = client("admin")
    r = c.post(f"/wo/orders/{wo['id']}", data={"qty": "7", "status": "진행", "planned_on": "2026-11-01"})
    assert r.status_code == 200, r.text
    assert conn.q1("select qty, status from work_order where id = %s", (wo["id"],)) == {"qty": 7, "status": "진행"}
    assert c.post(f"/wo/orders/{wo['id']}", data={"qty": "7", "status": "진행", "work_order_no": "X"}).status_code == 422
    assert c.post(f"/wo/orders/{wo['id']}", data={"qty": "7", "status": "보류"}).status_code == 422
    assert c.post("/wo/orders/99999999999", data={"qty": "7", "status": "진행"}).status_code == 404


@pytest.mark.fn("F-WO-023")
def test_order_list_and_pick_request(p):
    prefix, _ = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    wo = make_order(prefix, request_id=rq["id"], item_id=it["id"])
    c = client("pr")
    r = c.get("/wo/orders", params={"q": prefix})
    assert r.status_code == 200 and wo["work_order_no"] in r.text
    r = c.get("/wo/orders", params={"request_no": rq["request_no"]})
    assert r.status_code == 200 and "지시서 작성 — 의뢰 " + rq["request_no"] in r.text
    assert c.get("/wo/orders", params={"request_no": "없는번호"}).status_code == 422
    assert client("sl").get("/wo/orders").status_code == 403


@pytest.mark.fn("F-WO-024")
def test_order_print(p):
    prefix, _ = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    wo = make_order(prefix, request_id=rq["id"], item_id=it["id"])
    r = client("pr").get(f"/wo/orders/{wo['id']}/print")
    assert r.status_code == 200 and wo["work_order_no"] in r.text and rq["request_no"] in r.text
    assert client("pr").get("/wo/orders/99999999/print").status_code == 404


# ── WO-030 생산순서관리 ──
@pytest.mark.fn("F-WO-031")
def test_sequence_move(p):
    prefix, _ = p
    it, cu = _base(prefix)
    eq = prefix + "EQ"
    conn.x("insert into sys_common_code (group_code, code, code_name) values ('설비', %s, '설비 (예시)')", (eq,))
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    a = make_order(prefix + "A", request_id=rq["id"], item_id=it["id"], equipment_code=eq)
    b = make_order(prefix + "B", request_id=rq["id"], item_id=it["id"], equipment_code=eq)
    c = client("pr")
    r = c.post(f"/wo/sequence/{b['id']}/move", data={"direction": "up"})
    assert r.status_code == 200, r.text
    assert r.json()["order"] == [b["id"], a["id"]]
    seq = conn.q("select work_order_id, seq_no from work_sequence where equipment_code = %s order by seq_no", (eq,))
    assert [x["work_order_id"] for x in seq] == [b["id"], a["id"]]
    r = c.post(f"/wo/sequence/{b['id']}/move", data={"direction": "up"})
    assert r.status_code == 422 and "맨 앞" in r.json()["message"]
    assert c.post(f"/wo/sequence/{b['id']}/move", data={}).status_code == 422
    none_eq = make_order(prefix + "N", request_id=rq["id"], item_id=it["id"])
    assert c.post(f"/wo/sequence/{none_eq['id']}/move", data={"direction": "up"}).status_code == 422
    assert c.post("/wo/sequence/99999999999/move", data={"direction": "up"}).status_code == 404
    assert client("sl").post(f"/wo/sequence/{a['id']}/move", data={"direction": "up"}).status_code == 403


@pytest.mark.fn("F-WO-032")
def test_sequence_view(p):
    prefix, _ = p
    it, cu = _base(prefix)
    eq = prefix + "EQ"
    conn.x("insert into sys_common_code (group_code, code, code_name) values ('설비', %s, '설비 (예시)')", (eq,))
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    a = make_order(prefix + "A", request_id=rq["id"], item_id=it["id"], equipment_code=eq)
    r = client("pr").get("/wo/sequence")
    assert r.status_code == 200 and eq in r.text and a["work_order_no"] in r.text


# ── WO-040 공정상태 ──
@pytest.mark.fn("F-WO-041")
def test_status_view(p):
    prefix, _ = p
    it, cu = _base(prefix)
    rq = make_request(prefix, customer_id=cu["id"], item_id=it["id"])
    wo = make_order(prefix, request_id=rq["id"], item_id=it["id"], qty=12)
    r = client("sl").get("/wo/status", params={"q": wo["work_order_no"]})
    assert r.status_code == 200 and wo["work_order_no"] in r.text and "12.000" in r.text
    assert client("sh").get("/wo/status").status_code == 403
