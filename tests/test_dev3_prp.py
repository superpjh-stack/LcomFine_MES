# tests/test_dev3_prp.py — PRP 생산 보고서 (개발3) + stats.
# 일보 · 제품 입고는 2001년 3월(다른 데이터와 겹치지 않는 달)에 고유 설비 코드로 만든다. 화면 값 = 이 테스트가 손으로 센 값.
from datetime import date, timedelta
from decimal import Decimal

import pytest

from lcomfine.app import stats
from lcomfine.db import conn
from test_dev3_world import World, login



@pytest.fixture(scope="module")
def c():
    return {lid: login(lid) for lid in ("pr", "st", "sh", "sl", "admin")}


@pytest.fixture
def w():
    world = World()
    yield world
    world.close()


def _counts(w):
    """이 World 의 업무 행 수 — 같은 DB 를 쓰는 다른 테스트와 섞이지 않게 자기 행만 센다(조회 전후가 같아야 한다)."""
    return conn.q1("""select (select count(*) from production_daily where work_order_id = any(%(wo)s)) as daily,
                             (select count(*) from product_receipt where work_order_id = any(%(wo)s)) as receipt,
                             (select count(*) from lot_stock where lot_kind = '제품' and lot_id = any(%(lots)s)) as stock,
                             (select count(*) from stock_move where lot_kind = '제품' and lot_id = any(%(lots)s)) as moves,
                             (select count(*) from shipment_order where customer_id = %(c)s) as orders""",
                   {"wo": w.wos, "lots": w.lots, "c": w.customer_id})


def _daily(w, wo, day, eq, produced, good, loss, run, stop):
    conn.x("""insert into production_daily (work_order_id, work_date, equipment_code, produced_qty, good_qty, loss_qty,
                                            run_minutes, stop_minutes, created_by)
              values (%s, %s, %s, %s, %s, %s, %s, %s, 'test')""", (wo, day, eq, produced, good, loss, run, stop))


@pytest.fixture
def daily(w):
    eq_a, eq_b = f"{w.tag}A", f"{w.tag}B"
    wo2 = w.work_order(w.request_id, w.item_id)
    _daily(w, w.wo_id, date(2001, 3, 5), eq_a, 100, 90, 10, 300, 100)
    _daily(w, wo2, date(2001, 3, 6), eq_a, 50, 50, 0, 100, 0)
    _daily(w, w.wo_id, date(2001, 3, 7), eq_b, 10, 10, 0, None, None)    # 시간 미입력 → 가동률 미수집
    _daily(w, w.wo_id, date(2001, 4, 1), eq_a, 999, 999, 0, 999, 0)      # 다음 달 — 세지 않는다
    return eq_a, eq_b


@pytest.mark.fn("F-PRP-011")
def test_utilization_per_equipment(c, w, daily):
    eq_a, eq_b = daily
    before = _counts(w)
    r = c["pr"].get("/prp/utilization", params={"year": "2001", "month": "3"})
    assert r.status_code == 200
    data = stats.utilization(2001, 3)
    rows = {x["equipment_code"]: x for x in data["rows"]}
    assert (rows[eq_a]["run_minutes"], rows[eq_a]["stop_minutes"], rows[eq_a]["days"]) == (400, 100, 2)
    assert rows[eq_a]["rate"] == Decimal("80.0")                          # 400 ÷ (400 + 100) — D-801
    assert rows[eq_b]["rate"] is None and rows[eq_b]["entries"] == 1
    page = r.text
    seg = page[page.index(f'data-equipment="{eq_a}"'):]
    assert "80.0" in seg[:600] and "임시 산식" in page                         # 가동률 산식(가설) — 화면 도움말 · KPI 보조 문장(옛 본문 「D-801」)
    seg_b = page[page.index(f'data-equipment="{eq_b}"'):]
    assert "미수집" in seg_b[:600]
    for eq in ("EQ01", "EQ02"):                                              # 공통코드 설비는 일보가 없어도 행이 있다
        assert eq in rows
    assert c["st"].get("/prp/utilization", params={"month": "13"}).status_code == 422
    assert c["st"].get("/prp/utilization", params={"year": "x"}).status_code == 422
    assert c["sh"].get("/prp/utilization").status_code == 403                # 출하실 칸 없음
    assert _counts(w) == before                                               # 읽기만


@pytest.mark.fn("F-PRP-021")
def test_machine_stats_raw_quantities_and_undecided_loss_rate(c, w, daily):
    eq_a, eq_b = daily
    before = _counts(w)
    r = c["admin"].get("/prp/machines", params={"date_from": "2001-03-01", "date_to": "2001-03-31"})
    assert r.status_code == 200 and "미확정 (D-519)" in r.text
    rows = {x["equipment_code"]: x for x in stats.machine_stats(date(2001, 3, 1), date(2001, 3, 31))}
    a = rows[eq_a]
    assert (a["work_orders"], a["entries"], a["produced_qty"], a["good_qty"], a["loss_qty"]) == \
        (2, 2, Decimal("150"), Decimal("140"), Decimal("10"))
    assert rows[eq_b]["good_qty"] == Decimal("10")
    seg = r.text[r.text.index(f'data-equipment="{eq_a}"'):][:900]
    assert "150.000" in seg and "140.000" in seg and "미확정 (D-519)" in seg
    # 종료일 포함: 3/5 하루만
    one = {x["equipment_code"]: x for x in stats.machine_stats(date(2001, 3, 5), date(2001, 3, 5))}[eq_a]
    assert one["entries"] == 1 and one["produced_qty"] == Decimal("100")
    assert c["pr"].get("/prp/machines", params={"date_from": "2001-04-01", "date_to": "2001-03-01"}).status_code == 422
    assert c["pr"].get("/prp/machines", params={"date_from": "bad"}).status_code == 422
    assert c["sl"].get("/prp/machines").status_code == 403
    assert _counts(w) == before


@pytest.mark.fn("F-PRP-031")
def test_completion_counts_product_receipts(c, w):
    w.lot("10", received_on=date(2001, 3, 10))
    w.lot("5", received_on=date(2001, 3, 20))
    canceled = w.lot("7", received_on=date(2001, 3, 21))
    conn.x("update product_receipt set canceled_at = now(), canceled_by = 'test' where product_lot_id = %s", (canceled["id"],))
    w.lot("3", received_on=date(2001, 4, 2))                               # 기간 밖
    before = _counts(w)
    r = c["sh"].get("/prp/completion", params={"date_from": "2001-03-01", "date_to": "2001-03-31",
                                               "customer": str(w.customer_id)})
    assert r.status_code == 200
    data = stats.completion(date(2001, 3, 1), date(2001, 3, 31), w.customer_id)
    assert data["total"] == {"work_orders": 1, "receipts": 2, "qty": Decimal("15")}
    assert data["monthly"] == [{"ym": "2001-03", "receipts": 2, "qty": Decimal("15")}]
    assert [(x["item_code"], x["qty"]) for x in data["rows"]] == [(f"{w.tag}-I1", Decimal("15"))]
    seg = r.text[r.text.index(f'data-customer="{w.customer_id}"'):][:600]
    assert "15.000" in seg
    empty = c["sh"].get("/prp/completion", params={"date_from": "2000-01-01", "date_to": "2000-01-31",
                                                   "customer": str(w.customer_id)})
    assert empty.status_code == 200 and "미수집" in empty.text
    assert c["sh"].get("/prp/completion", params={"customer": "abc"}).status_code == 422
    assert c["sl"].get("/prp/completion").status_code == 403
    assert _counts(w) == before


def test_stats_request_shipments(w):
    """납기 보조 — 의뢰별 지시(미확정) · 확정 출하 수량. 취소는 세지 않는다."""
    lot = w.lot("10")
    with conn.tx() as cur:
        for no, status, q in (("A", "지시", 2), ("B", "확정", 3), ("C", "취소", 4)):
            cur.execute("""insert into shipment_order (shipment_no, request_id, customer_id, due_date, status, confirmed_at)
                           values (%s, %s, %s, %s, %s, case when %s = '확정' then now() end) returning id""",
                        (f"{w.tag}-S{no}", w.request_id, w.customer_id, date.today() + timedelta(days=1), status, status))
            oid = cur.fetchone()["id"]
            cur.execute("insert into shipment_line (shipment_order_id, product_lot_id, location_id, qty) values (%s, %s, %s, %s)",
                        (oid, lot["id"], w.location_id, q))
    got = stats.request_shipments([w.request_id])[w.request_id]
    assert (got["ordered_qty"], got["shipped_qty"]) == (Decimal("2"), Decimal("3")) and got["last_confirmed_at"] is not None
    assert w.request_id not in stats.request_shipments([-1])
