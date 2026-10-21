# tests/test_dev2_qc.py — QC 품질 검사 (QC-010 · 020 · 030) — 판정은 새 행 · lot_stock.status 만 바꾼다 (D-510 · D-515)
import pytest

from lcomfine.app import trace
from lcomfine.db import conn
from tests.test_dev2_world import pr, sh, sl, world  # noqa: F401 — 픽스처


def _insp(table: str, lot_table: str, lot_no: str) -> list[tuple]:
    fk = "material_lot_id" if lot_table == "material_lot" else "product_lot_id"
    return [(r["seq"], r["result"]) for r in conn.q(
        f"select q.seq, q.result from {table} q join {lot_table} t on t.id = q.{fk} where t.lot_no = %s order by q.seq",
        (lot_no,))]


@pytest.mark.fn("F-QC-011")
def test_incoming_pass_makes_available_fail_holds(world, pr, sh):
    a, b = world.receive(pr, 10, 20)
    out = world.pass_incoming(pr, a)
    assert out["seq"] == 1 and out["status"] == "가용"
    assert world.stock("원자재", a)[0]["status"] == "가용"
    world.pass_incoming(pr, b, "불합격")
    assert world.stock("원자재", b)[0]["status"] == "보류"
    r = pr.post("/qc/incoming", data={"lot_no": a, "result": "합격"})
    assert r.status_code == 422 and "검사대기 LOT 이 아닙니다" in r.json()["message"]   # 이미 판정 → 재판정으로
    assert pr.post("/qc/incoming", data={"lot_no": a, "result": "보통"}).status_code == 422
    assert pr.post("/qc/incoming", data={"result": "합격"}).status_code == 422
    assert pr.post("/qc/incoming", data={"lot_no": "MLOT-없음", "result": "합격"}).status_code == 422
    assert sh.post("/qc/incoming", data={"lot_no": a, "result": "합격"}).status_code == 403
    # 입고의 LOT 이 모두 판정되면 입고 알림이 닫힌다
    n = conn.q1("select handled_at from notification where dedupe_key = %s and to_role = 'PR'", (f"material_received:{a}",))
    assert n["handled_at"] is not None


@pytest.mark.fn("F-QC-012")
def test_incoming_rejudge_is_new_row(world, pr):
    (a,) = world.receive(pr, 10)
    world.pass_incoming(pr, a, "불합격")
    lid = conn.q1("select id from material_lot where lot_no = %s", (a,))["id"]
    r = pr.post(f"/qc/incoming/{lid}", data={"result": "합격", "item_name": ["외관"], "item_value": ["양호 (예시)"]})
    assert r.status_code == 200, r.text
    assert _insp("incoming_inspection", "material_lot", a) == [(1, "불합격"), (2, "합격")]
    assert world.stock("원자재", a)[0]["status"] == "가용"
    (b,) = world.receive(pr, 5)
    bid = conn.q1("select id from material_lot where lot_no = %s", (b,))["id"]
    assert pr.post(f"/qc/incoming/{bid}", data={"result": "합격"}).status_code == 422          # 판정 이력 없음
    assert pr.post("/qc/incoming/999999999", data={"result": "합격"}).status_code == 404


@pytest.mark.fn("F-QC-013")
def test_incoming_screen_lists_waiting(world, pr):
    (a,) = world.receive(pr, 3)
    r = pr.get("/qc/incoming", params={"lot": a}, headers={"accept": "text/html"})
    assert r.status_code == 200 and "검사 대기 LOT" in r.text and a in r.text


@pytest.mark.fn("F-QC-021")
def test_product_judge_sets_status_and_notifies_sh_sl(world, pr, sh):
    out = world.product_receive(pr, 40)
    r = pr.post("/qc/product", data={"lot_no": out["lot_no"], "result": "합격"})
    assert r.status_code == 200, r.text
    assert world.stock("제품", out["lot_no"])[0]["status"] == "가용"
    roles = [x["to_role"] for x in conn.q("select to_role from notification where dedupe_key = %s order by to_role",
                                          (f"judged:{out['lot_no']}:1",))]
    assert roles == ["SH", "SL"]
    got = conn.q1("select handled_at from notification where dedupe_key = %s", (f"product_received:{out['lot_no']}",))
    assert got["handled_at"] is not None                         # 제품 입고 알림을 연 화면에서 처리 → 닫힘
    assert pr.post("/qc/product", data={"lot_no": out["lot_no"], "result": "합격"}).status_code == 422
    assert sh.post("/qc/product", data={"lot_no": out["lot_no"], "result": "합격"}).status_code == 403   # 출하실은 R


@pytest.mark.fn("F-QC-022")
def test_product_rejudge_fail_then_pass(world, pr):
    out = world.product_receive(pr, 40)
    pid = out["product_lot_id"]
    pr.post("/qc/product", data={"product_lot_id": str(pid), "result": "불합격"})
    assert world.stock("제품", out["lot_no"])[0]["status"] == "보류"
    r = pr.post(f"/qc/product/{pid}", data={"result": "합격"})
    assert r.status_code == 200 and r.json()["seq"] == 2
    assert world.stock("제품", out["lot_no"])[0]["status"] == "가용"              # 불합격 → 합격 = 보류 → 가용 (D-515 4)
    assert _insp("product_inspection", "product_lot", out["lot_no"]) == [(1, "불합격"), (2, "합격")]
    assert pr.post("/qc/product/999999999", data={"result": "합격"}).status_code == 404


@pytest.mark.fn("F-QC-022")
def test_rejudge_after_shipment_keeps_shipment_and_flags(world, pr):
    """Review Focus 3 (D-515): 출하 확정 뒤 재판정 불합격 — 재판정 행은 남고 출하는 되돌리지 않으며 trace 가 「출하 후 불합격」."""
    (m,) = world.receive(pr, 100)
    world.pass_incoming(pr, m)
    assert world.issue(pr, m, 60).status_code == 200
    world.daily(pr, 50)
    out = world.product_receive(pr)
    plot, pid = out["lot_no"], out["product_lot_id"]
    pr.post("/qc/product", data={"lot_no": plot, "result": "합격"})
    shp = world.ship(plot, 30)                                     # 확정 출하 30 (SHP — SQL 로 직접)
    before = conn.q1("""select so.status, so.confirmed_at, sum(sl.qty) as qty from shipment_order so
                         join shipment_line sl on sl.shipment_order_id = so.id where so.shipment_no = %s
                         group by so.status, so.confirmed_at""", (shp,))
    assert not trace.backward(shipment_no=shp)["rejected_after_shipment"]

    r = pr.post(f"/qc/product/{pid}", data={"result": "불합격", "note": "클레임 (예시)"})
    assert r.status_code == 200, r.text
    assert r.json()["shipped_after"] is True
    # 재판정 행은 남는다
    assert _insp("product_inspection", "product_lot", plot) == [(1, "합격"), (2, "불합격")]
    # 출하는 되돌리지 않는다 — 상태 · 확정 시각 · 수량 그대로, 반품·정정 행도 자동으로 생기지 않는다
    after = conn.q1("""select so.status, so.confirmed_at, sum(sl.qty) as qty from shipment_order so
                        join shipment_line sl on sl.shipment_order_id = so.id where so.shipment_no = %s
                        group by so.status, so.confirmed_at""", (shp,))
    assert after == before and after["status"] == "확정"
    assert conn.q1("""select count(*) as n from shipment_adjust a join shipment_order so on so.id = a.shipment_order_id
                       where so.shipment_no = %s""", (shp,))["n"] == 0
    # 남은 재고만 보류
    st = world.stock("제품", plot)
    assert [(s["status"], int(s["qty"])) for s in st] == [("보류", 20)]
    # trace 에 「출하 후 불합격」
    back = trace.backward(shipment_no=shp)
    flags = back["rejected_after_shipment"]
    assert [(f["shipment_no"], f["product_lot_no"], f["seq"]) for f in flags] == [(shp, plot, 2)]
    assert back["origin_material_lot_nos"] == [m]
    assert trace.backward(product_lot_no=plot)["rejected_after_shipment"][0]["shipment_no"] == shp
    assert [f["product_lot_no"] for f in trace.forward(m)["rejected_after_shipment"]] == [plot]
    html = pr.get("/lot/backward", params={"shipment_no": shp}, headers={"accept": "text/html"}).text
    assert "출하 후 불합격" in html and plot in html


@pytest.mark.fn("F-QC-023")
def test_product_screen_lists(world, pr, sh):
    out = world.product_receive(pr, 5)
    r = sh.get("/qc/product", params={"lot": out["lot_no"]}, headers={"accept": "text/html"})
    assert r.status_code == 200 and out["lot_no"] in r.text and "판정 대기 제품 LOT" in r.text


@pytest.mark.fn("F-QC-031")
def test_history_shows_previous_judgement(world, pr, sl):
    (a,) = world.receive(pr, 10)
    world.pass_incoming(pr, a, "불합격")
    lid = conn.q1("select id from material_lot where lot_no = %s", (a,))["id"]
    pr.post(f"/qc/incoming/{lid}", data={"result": "합격"})
    r = sl.get("/qc/history", params={"lot": a}, headers={"accept": "text/html"})
    assert r.status_code == 200 and a in r.text and "현재 판정" in r.text and "이전" in r.text
    assert r.text.count("불합격") >= 2                             # 1차 행 + 2차 행의 이전 판정
    assert sl.get("/qc/history", params={"result": "보통"}).status_code == 422
