# tests/test_dev2_lot.py — LOT 추적 (LOT-010 정방향 · LOT-020 역방향) · trace 는 읽기만 한다 (G-05 · G-07 · G-08)
import pytest

from lcomfine.app import trace
from lcomfine.db import conn
from tests.test_dev2_world import pr, sh, sl, world  # noqa: F401 — 픽스처

H = {"accept": "text/html"}


def _spine(world, pr):
    """원자재 2 LOT(하나는 분할 뒤 분할 LOT 을 불출) → 지시 → 제품 LOT → 분할 → 분할 LOT 출하."""
    m1, m2, m3 = world.receive(pr, 100, 50, 10)
    for m in (m1, m2, m3):
        world.pass_incoming(pr, m)
    r = pr.post("/inv/moves", data={"lot_kind": "원자재", "lot_no": m1, "from_location_id": str(world.loc1),
                                    "to_location_id": str(world.loc2), "qty": "40", "split": "1"})
    m1c = r.json()["lot_no"]
    assert world.issue(pr, m1c, 30, loc=world.loc2).status_code == 200       # 분할 LOT 을 불출
    assert world.issue(pr, m2, 20).status_code == 200
    assert world.issue(pr, m3, 5, wo_id=world.wo2).status_code == 200        # 다른 지시 — 섞이면 안 된다
    world.daily(pr, 60)
    out = world.product_receive(pr)
    plot = out["lot_no"]
    pr.post("/qc/product", data={"lot_no": plot, "result": "합격"})
    r = pr.post("/inv/moves", data={"lot_kind": "제품", "lot_no": plot, "from_location_id": str(world.loc1),
                                    "to_location_id": str(world.loc2), "qty": "25", "split": "1"})
    pchild = r.json()["lot_no"]
    shp = world.ship(pchild, 25, loc=world.loc2)
    return {"m1": m1, "m1c": m1c, "m2": m2, "m3": m3, "plot": plot, "pchild": pchild, "shp": shp}


def _independent_origin(shipment_no: str) -> list[str]:
    """QA2 가 따로 짜는 것과 같은 꼴의 독립 SQL — 출하 → 제품 LOT 의 지시 → 불출 LOT → 원 입고 LOT."""
    return [r["lot_no"] for r in conn.q("""
        with recursive up as (
            select m.id, m.parent_lot_id from material_issue_line l
              join material_issue h on h.id = l.issue_id and h.canceled_at is null
              join material_lot m on m.id = l.material_lot_id
             where l.work_order_id in (select p.work_order_id from shipment_line sl join product_lot p on p.id = sl.product_lot_id
                                         join shipment_order so on so.id = sl.shipment_order_id where so.shipment_no = %s)
            union all
            select m.id, m.parent_lot_id from up join material_lot m on m.id = up.parent_lot_id)
        select distinct lot_no from up join material_lot using (id) where up.parent_lot_id is null order by lot_no""",
        (shipment_no,))]


def _counts() -> dict:
    tables = [r["table_name"] for r in conn.q("""select table_name from information_schema.tables
                                                  where table_schema = 'public' and table_type = 'BASE TABLE'
                                                    and table_name not in ('sys_access_log')""")]
    return {t: conn.q1(f"select count(*) as n from {t}")["n"] for t in tables}


@pytest.mark.fn("F-LOT-021")
def test_backward_from_shipment_reaches_origin_material_lots(world, pr, sl):
    s = _spine(world, pr)
    back = trace.backward(shipment_no=s["shp"])
    assert back["origin_material_lot_nos"] == sorted([s["m1"], s["m2"]]) == _independent_origin(s["shp"])   # G-07
    assert back["issued_material_lot_nos"] == sorted([s["m1c"], s["m2"]])
    assert s["m3"] not in back["origin_material_lot_nos"]
    pl = back["product_lots"]
    assert [(p["lot_no"], p["root_lot_no"], int(p["shipped_qty"]), p["judgement"]) for p in pl] == \
        [(s["pchild"], s["plot"], 25, "합격")]                        # 분할 LOT 은 원 LOT 의 판정을 따른다
    assert [w["work_order_no"] for w in back["work_orders"]] == [world.wo_no]
    assert [x["start"] for x in [back]] == [{"kind": "출하", "no": s["shp"]}]
    by_plot = trace.backward(product_lot_no=s["plot"])
    assert by_plot["origin_material_lot_nos"] == back["origin_material_lot_nos"]
    assert [x["shipment_no"] for x in by_plot["shipments"]] == [s["shp"]]   # 원 LOT 의 분할 자식이 나간 출하
    # 화면 (영업부 R)
    r = sl.get("/lot/backward", params={"shipment_no": s["shp"]}, headers=H)
    assert r.status_code == 200 and s["m1"] in r.text and s["m2"] in r.text and s["m3"] not in r.text
    r = sl.get("/lot/backward", params={"shipment_no": "SHP-없는번호"}, headers=H)
    assert r.status_code == 422 and "없는 출하 번호" in r.text and 'value="SHP-없는번호"' in r.text
    r = sl.get("/lot/backward", params={"shipment_no": s["shp"], "product_lot_no": s["plot"]}, headers=H)
    assert r.status_code == 422
    assert sl.get("/lot/backward", headers=H).status_code == 200
    with pytest.raises(trace.NotFound):
        trace.backward(product_lot_no="PLOT-없음")
    with pytest.raises(ValueError):
        trace.backward()


@pytest.mark.fn("F-LOT-011")
def test_forward_from_material_lot_reaches_shipments(world, pr, sh, sl):
    s = _spine(world, pr)
    fw = trace.forward(s["m1"])
    assert [m["lot_no"] for m in fw["material_lots"]] == sorted([s["m1"], s["m1c"]])     # 분할 자식까지
    assert [w["work_order_no"] for w in fw["work_orders"]] == [world.wo_no]
    assert fw["product_lot_nos"] == sorted([s["plot"], s["pchild"]])
    assert fw["shipment_nos"] == [s["shp"]]                                             # G-08
    fw3 = trace.forward(s["m3"])
    assert [w["work_order_no"] for w in fw3["work_orders"]] == [world.wo2_no] and fw3["shipment_nos"] == []
    r = sh.get("/lot/forward", params={"lot_no": s["m1"]}, headers=H)
    assert r.status_code == 200 and s["shp"] in r.text and s["pchild"] in r.text
    r = sh.get("/lot/forward", params={"lot_no": "MLOT-없음"}, headers=H)
    assert r.status_code == 422 and "없는 원자재 LOT" in r.text
    assert sl.get("/lot/forward", headers=H).status_code == 403                         # 영업부는 LOT-010 칸 없음


@pytest.mark.fn("F-LOT-011")
@pytest.mark.fn("F-LOT-021")
def test_trace_writes_nothing(world, pr, sh):
    s = _spine(world, pr)
    before = _counts()
    trace.backward(shipment_no=s["shp"])
    trace.forward(s["m1"])
    sh.get("/lot/backward", params={"shipment_no": s["shp"]}, headers=H)
    sh.get("/lot/forward", params={"lot_no": s["m1"]}, headers=H)
    after = _counts()
    changed = {t: (before[t], after.get(t)) for t in before if before[t] != after.get(t)}
    # 같은 DB 를 다른 개발자 테스트가 함께 쓴다 — 개발2 영역(추적 척추) 테이블만 본다
    spine = {"material_receipt", "material_lot", "material_issue", "material_issue_line", "product_lot", "product_receipt",
             "lot_stock", "stock_move", "shipment_order", "shipment_line", "incoming_inspection", "product_inspection"}
    assert not {t for t in changed if t in spine}, changed
    # 정적으로도: trace.py 에 쓰기 문이 없다
    import inspect
    import re
    src = inspect.getsource(trace).lower()
    assert not re.search(r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from|truncate)\b", src)
