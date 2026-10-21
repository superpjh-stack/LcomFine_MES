# tests/test_dev2_inv.py — INV 재고 (INV-010 · 020 · 030) — 가용 = 현재고 − 할당 · 분할 -01 · 조정 사유 필수 · 불변 이력
import psycopg
import pytest

from lcomfine.db import conn
from tests.test_dev2_world import pr, sh, sl, world  # noqa: F401 — 픽스처


@pytest.mark.fn("F-INV-011")
def test_stock_available_is_qty_minus_allocated_and_chips(world, pr, sl):
    out = world.product_receive(pr, 50)
    pr.post("/qc/product", data={"lot_no": out["lot_no"], "result": "합격"})
    world.ship(out["lot_no"], 20, confirm=False)                    # 출하 지시 할당 20 (SHP — SQL)
    (m,) = world.receive(pr, 9)
    r = sl.get("/inv/stock", params={"warehouse": world.p + "WH"}, headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text
    row = html[html.index(f'data-lot="{out["lot_no"]}"'):]
    row = row[:row.index("</tr>")]
    assert "data-available>30<" in row and "할당" in row and "가용" in row
    assert m in html and "검사대기" in html
    db = conn.q1("""select sum(qty - allocated_qty) as a from v_dq_stock where lot_no = %s""", (out["lot_no"],))
    assert int(db["a"]) == 30                                       # 화면 값 = 독립 재계산 (G-10)
    r = sl.get("/inv/stock", params={"warehouse": world.p + "WH", "status": "할당"}, headers={"accept": "text/html"})
    assert out["lot_no"] in r.text and m not in r.text
    assert sl.get("/inv/stock", params={"status": "없는상태"}).status_code == 422


@pytest.mark.fn("F-INV-021")
def test_move_and_split_lot(world, pr, sh):
    (m,) = world.receive(pr, 100)
    world.pass_incoming(pr, m)
    base = {"lot_kind": "원자재", "lot_no": m, "from_location_id": str(world.loc1), "to_location_id": str(world.loc2)}
    r = pr.post("/inv/moves", data={**base, "qty": "30"})
    assert r.status_code == 200, r.text
    assert [(s["location_id"], int(s["qty"]), s["status"]) for s in world.stock("원자재", m)] == \
        [(world.loc1, 70, "가용"), (world.loc2, 30, "가용")]
    r = pr.post("/inv/moves", data={**base, "qty": "20", "split": "1"})
    assert r.status_code == 200, r.text
    child = r.json()["lot_no"]
    assert child == f"{m}-01"
    row = conn.q1("select parent_lot_id, qty, receipt_id from material_lot where lot_no = %s", (child,))
    parent = conn.q1("select id, receipt_id from material_lot where lot_no = %s", (m,))
    assert row["parent_lot_id"] == parent["id"] and int(row["qty"]) == 20 and row["receipt_id"] == parent["receipt_id"]
    mv = conn.q1("select move_kind, source_lot_id from stock_move where lot_kind = '원자재' and lot_id = %s",
                 (conn.q1("select id from material_lot where lot_no = %s", (child,))["id"],))
    assert mv == {"move_kind": "분할", "source_lot_id": parent["id"]}
    assert [(int(s["qty"]), s["status"]) for s in world.stock("원자재", child)] == [(20, "가용")]
    r = pr.post("/inv/moves", data={**base, "qty": "5", "split": "1"})
    assert r.json()["lot_no"] == f"{m}-02"
    r = pr.post("/inv/moves", data={**base, "qty": "999"})
    assert r.status_code == 422 and "가용 수량" in r.json()["message"]
    assert pr.post("/inv/moves", data={**base, "to_location_id": str(world.loc1), "qty": "1"}).status_code == 422
    assert pr.post("/inv/moves", data={**base, "lot_no": "없음", "qty": "1"}).status_code == 422
    assert sh.post("/inv/moves", data={**base, "qty": "1"}).status_code == 403


@pytest.mark.fn("F-INV-022")
def test_move_update_reapplies(world, pr):
    (m,) = world.receive(pr, 40)
    mid = pr.post("/inv/moves", data={"lot_kind": "원자재", "lot_no": m, "from_location_id": str(world.loc1),
                                      "to_location_id": str(world.loc2), "qty": "10"}).json()["move_id"]
    r = pr.post(f"/inv/moves/{mid}", data={"qty": "15"})
    assert r.status_code == 200, r.text
    assert [(s["location_id"], int(s["qty"])) for s in world.stock("원자재", m)] == [(world.loc1, 25), (world.loc2, 15)]
    assert pr.post(f"/inv/moves/{mid}", data={"qty": "999"}).status_code == 422
    assert [(s["location_id"], int(s["qty"])) for s in world.stock("원자재", m)] == [(world.loc1, 25), (world.loc2, 15)]
    assert pr.post("/inv/moves/999999999", data={"qty": "1"}).status_code == 404


@pytest.mark.fn("F-INV-023")
def test_move_list(world, pr):
    (m,) = world.receive(pr, 10)
    pr.post("/inv/moves", data={"lot_kind": "원자재", "lot_no": m, "from_location_id": str(world.loc1),
                                "to_location_id": str(world.loc2), "qty": "4", "split": "1"})
    r = pr.get("/inv/moves", params={"lot": m}, headers={"accept": "text/html"})
    assert r.status_code == 200 and f"{m}-01" in r.text and "분할" in r.text


@pytest.mark.fn("F-INV-031")
def test_adjust_requires_reason_and_is_immutable(world, pr):
    (m,) = world.receive(pr, 10)
    base = {"lot_kind": "원자재", "lot_no": m, "location_id": str(world.loc1), "actual_qty": "8"}
    r = pr.post("/inv/adjustments", data={**base, "reason": "  "})
    assert r.status_code == 422 and "차이 사유" in r.json()["message"]
    r = pr.post("/inv/adjustments", data={**base, "reason": "실사 차이 (예시)"})
    assert r.status_code == 200, r.text
    assert r.json()["diff_qty"] == "-2.000"
    assert int(world.stock("원자재", m)[0]["qty"]) == 8
    aid = r.json()["adjust_id"]
    with pytest.raises(psycopg.Error):                              # 조정 이력은 수정·삭제하지 않는다
        conn.x("update stock_adjust set reason = 'x' where id = %s", (aid,))
    assert pr.post("/inv/adjustments", data={**base, "location_id": str(world.loc2), "reason": "x"}).status_code == 422


@pytest.mark.fn("F-INV-032")
def test_adjust_list(world, pr, sl):
    (m,) = world.receive(pr, 10)
    pr.post("/inv/adjustments", data={"lot_kind": "원자재", "lot_no": m, "location_id": str(world.loc1),
                                      "actual_qty": "11", "reason": "실사 (예시)"})
    r = pr.get("/inv/adjustments", params={"lot": m}, headers={"accept": "text/html"})
    assert r.status_code == 200 and m in r.text and "실사 (예시)" in r.text
    assert sl.get("/inv/adjustments").status_code == 403
