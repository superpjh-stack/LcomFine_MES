# tests/test_dev2_mat.py — MAT 자재·입고 (MAT-010 · 020 · 030 · 040) — 실제 DB · 시드 뒤 · 화면이 부르는 HTTP 로
import pytest

from lcomfine.db import conn
from tests.test_dev2_world import pr, sh, sl, world  # noqa: F401 — 픽스처


@pytest.mark.fn("F-MAT-011")
def test_receipt_numbers_lots_waiting_and_notifies(world, pr, sl):
    lots = world.receive(pr, 100, 40)
    assert len(lots) == 2 and all(n.startswith("MLOT-") for n in lots)
    for no, q in zip(lots, (100, 40)):
        st = world.stock("원자재", no)
        assert [(s["status"], int(s["qty"])) for s in st] == [("검사대기", q)]
    n = conn.q("select to_role, link from notification where dedupe_key = %s", (f"material_received:{lots[0]}",))
    assert [r["to_role"] for r in n] == ["PR"] and n[0]["link"].startswith("/qc/incoming?receipt=")
    # 누락 · 중지 품목 · 원자재 아닌 품목 · 권한
    assert pr.post("/mat/receipts", data={"supplier_name": "", "item_id": [str(world.rm)], "qty": ["1"],
                                          "location_id": [str(world.loc1)], "supplier_lot_no": [""]}).status_code == 422
    r = pr.post("/mat/receipts", data={"supplier_name": "공급사 (예시)", "item_id": [str(world.rm_off)], "qty": ["1"],
                                       "location_id": [str(world.loc1)], "supplier_lot_no": [""]})
    assert r.status_code == 422 and "사용 중지" in r.json()["message"]
    r = pr.post("/mat/receipts", data={"supplier_name": "공급사 (예시)", "item_id": [str(world.fg)], "qty": ["1"],
                                       "location_id": [str(world.loc1)], "supplier_lot_no": [""]})
    assert r.status_code == 422
    assert pr.post("/mat/receipts", data={"supplier_name": "공급사 (예시)"}).status_code == 422      # LOT 행 없음
    assert sl.post("/mat/receipts", data={"supplier_name": "x"}).status_code == 403


@pytest.mark.fn("F-MAT-012")
def test_receipt_update_qty_and_cancel_keeps_rows(world, pr):
    (lot,) = world.receive(pr, 10)
    m = conn.q1("select id, receipt_id from material_lot where lot_no = %s", (lot,))
    r = pr.post(f"/mat/receipts/{m['receipt_id']}", data={"supplier_name": "공급사 B (예시)", "lot_id": [str(m["id"])],
                                                          "qty": ["12"], "supplier_lot_no": ["S-1"]})
    assert r.status_code == 200, r.text
    assert int(world.stock("원자재", lot)[0]["qty"]) == 12
    assert conn.q1("select supplier_name from material_receipt where id = %s", (m["receipt_id"],))["supplier_name"] == "공급사 B (예시)"
    r = pr.post(f"/mat/receipts/{m['receipt_id']}", data={"cancel": "1"})
    assert r.status_code == 200
    assert conn.q1("select canceled_at from material_receipt where id = %s", (m["receipt_id"],))["canceled_at"] is not None
    assert world.stock("원자재", lot) == []                        # 재고에서 빠지고 입고 행은 남는다
    assert pr.post(f"/mat/receipts/{m['receipt_id']}", data={"note": "x"}).status_code == 422   # 취소된 입고
    assert pr.post("/mat/receipts/999999999", data={"note": "x"}).status_code == 404
    assert pr.post("/mat/receipts/abc", data={"note": "x"}).status_code == 404


@pytest.mark.fn("F-MAT-013")
def test_receipt_list_and_label(world, pr, sh):
    (lot,) = world.receive(pr, 7)
    rid = conn.q1("select receipt_id from material_lot where lot_no = %s", (lot,))["receipt_id"]
    r = pr.get("/mat/receipts", params={"lot": lot}, headers={"accept": "text/html"})
    assert r.status_code == 200 and lot in r.text and "검사대기" in r.text
    r = pr.get("/mat/receipts", params={"label": rid}, headers={"accept": "text/html"})
    assert r.status_code == 200 and "LOT 라벨" in r.text and lot in r.text
    assert sh.get("/mat/receipts").status_code == 403


@pytest.mark.fn("F-MAT-021")
def test_issue_blocks_waiting_and_held_lots_and_moves_stock(world, pr):
    ok, held = world.receive(pr, 100, 30)
    r = world.issue(pr, ok, 10)
    assert r.status_code == 422 and "검사대기" in r.json()["message"]          # G-09
    world.pass_incoming(pr, ok)
    world.pass_incoming(pr, held, "불합격")
    r = world.issue(pr, held, 5)
    assert r.status_code == 422 and "보류" in r.json()["message"]
    r = world.issue(pr, ok, 101)
    assert r.status_code == 422 and "가용 수량" in r.json()["message"]
    r = world.issue(pr, "MLOT-없는번호", 1)
    assert r.status_code == 422
    r = world.issue(pr, ok, 25)
    assert r.status_code == 200, r.text
    assert int(world.stock("원자재", ok)[0]["qty"]) == 75
    line = conn.q1("""select l.work_order_id, l.qty from material_issue_line l join material_lot m on m.id = l.material_lot_id
                       where m.lot_no = %s""", (ok,))
    assert line["work_order_id"] == world.wo and int(line["qty"]) == 25
    mv = conn.q1("""select move_kind, from_location_id, to_location_id, s.qty from stock_move s join material_lot m on m.id = s.lot_id
                     where s.lot_kind = '원자재' and m.lot_no = %s""", (ok,))
    assert mv["move_kind"] == "불출" and mv["from_location_id"] == world.loc1 and mv["to_location_id"] is None
    # 지시번호를 직접 입력하는 길(공정 FINE_MES)
    r = pr.post("/mat/issues", data={"work_order_no": world.wo_no, "lot_no": [ok], "location_id": [""], "qty": ["5"]})
    assert r.status_code == 200, r.text
    r = pr.post("/mat/issues", data={"work_order_no": "WO-없음", "lot_no": [ok], "location_id": [""], "qty": ["5"]})
    assert r.status_code == 422


@pytest.mark.fn("F-MAT-022")
def test_issue_cancel_restores_stock(world, pr):
    (lot,) = world.receive(pr, 50)
    world.pass_incoming(pr, lot)
    iid = world.issue(pr, lot, 20).json()["issue_id"]
    r = pr.post(f"/mat/issues/{iid}", data={"note": "메모 (예시)"})
    assert r.status_code == 200
    r = pr.post(f"/mat/issues/{iid}", data={"cancel": "1"})
    assert r.status_code == 200, r.text
    assert int(world.stock("원자재", lot)[0]["qty"]) == 50
    kinds = [x["move_kind"] for x in conn.q("""select move_kind from stock_move s join material_lot m on m.id = s.lot_id
                                                where s.lot_kind = '원자재' and m.lot_no = %s order by s.id""", (lot,))]
    assert kinds == ["불출", "불출 취소"]
    assert conn.q1("select canceled_at from material_issue where id = %s", (iid,))["canceled_at"] is not None
    assert pr.post(f"/mat/issues/{iid}", data={"cancel": "1"}).status_code == 422
    assert pr.post("/mat/issues/999999999", data={"note": "x"}).status_code == 404


@pytest.mark.fn("F-MAT-023")
def test_issue_list_search(world, pr):
    (lot,) = world.receive(pr, 9)
    world.pass_incoming(pr, lot)
    world.issue(pr, lot, 3)
    r = pr.get("/mat/issues", params={"wo": world.wo_no}, headers={"accept": "text/html"})
    assert r.status_code == 200 and lot in r.text and world.wo_no in r.text


@pytest.mark.fn("F-MAT-031")
def test_product_receipt_defaults_to_daily_good_qty(world, pr):
    world.daily(pr, 80)
    out = world.product_receive(pr)                                # 수량 비움 → 일보 완료 수량
    assert out["qty"] == "80.000" and out["lot_no"].startswith("PLOT-")
    p = conn.q1("""select p.work_order_id, r.work_order_id as r_wo, p.item_id from product_lot p
                    join product_receipt r on r.product_lot_id = p.id where p.lot_no = %s""", (out["lot_no"],))
    assert p["work_order_id"] == p["r_wo"] == world.wo and p["item_id"] == world.fg
    assert [(s["status"], int(s["qty"])) for s in world.stock("제품", out["lot_no"])] == [("검사대기", 80)]
    n = conn.q("select to_role from notification where dedupe_key = %s", (f"product_received:{out['lot_no']}",))
    assert [r["to_role"] for r in n] == ["PR"]
    r = pr.post("/mat/product-receipts", data={"work_order_id": str(world.wo), "location_id": str(world.loc1)})
    assert r.status_code == 422                                    # 남은 일보 완료 수량 없음
    r = pr.post("/mat/product-receipts", data={"work_order_id": "", "location_id": str(world.loc1), "qty": "1"})
    assert r.status_code == 422
    r = pr.post("/mat/product-receipts", data={"work_order_id": str(world.wo), "location_id": str(world.loc1), "qty": "-3"})
    assert r.status_code == 422


@pytest.mark.fn("F-MAT-032")
def test_product_receipt_update_and_cancel(world, pr):
    out = world.product_receive(pr, 30)
    prid = out["product_receipt_id"]
    assert pr.post(f"/mat/product-receipts/{prid}", data={"qty": "28"}).status_code == 200
    assert int(world.stock("제품", out["lot_no"])[0]["qty"]) == 28
    assert int(conn.q1("select qty from product_lot where lot_no = %s", (out["lot_no"],))["qty"]) == 28
    assert pr.post(f"/mat/product-receipts/{prid}", data={"cancel": "1"}).status_code == 200
    assert world.stock("제품", out["lot_no"]) == []
    assert conn.q1("select canceled_at from product_receipt where id = %s", (prid,))["canceled_at"] is not None
    assert pr.post(f"/mat/product-receipts/{prid}", data={"qty": "1"}).status_code == 422
    assert pr.post("/mat/product-receipts/999999999", data={"qty": "1"}).status_code == 404


@pytest.mark.fn("F-MAT-033")
def test_product_receipt_screen_shows_default(world, pr):
    world.daily(pr, 45)
    r = pr.get("/mat/product-receipts", params={"wo": world.wo_no}, headers={"accept": "text/html"})
    assert r.status_code == 200 and "일보 완료 − 기존 입고 = 45" in r.text


@pytest.mark.fn("F-MAT-041")
def test_history_marks_canceled_and_exports_csv(world, pr):
    a, b = world.receive(pr, 5, 6)
    rid = conn.q1("select receipt_id from material_lot where lot_no = %s", (a,))["receipt_id"]
    pr.post(f"/mat/receipts/{rid}", data={"cancel": "1"})
    r = pr.get("/mat/history", params={"item": world.p + "RM"}, headers={"accept": "text/html"})
    assert r.status_code == 200 and a in r.text and "취소" in r.text
    r = pr.get("/mat/history", params={"item": world.p + "RM", "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("구분,일자,LOT") and a in body and "취소" in body
    assert pr.get("/mat/history", params={"from": "2026-13-40"}).status_code == 422
