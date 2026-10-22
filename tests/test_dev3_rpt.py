# tests/test_dev3_rpt.py — RPT 대시보드 8 (개발3 · W3) + dashboard. 데이터 질의(화면 · ai · dataquery)는 D-529 로 없앴다 — 없어졌는지만 본다.
# 기준 데이터는 2002년 5월(다른 테스트와 겹치지 않는 달) 에 test_dev3_world.World 위에 더 만든다(일보 · 검사 · 자재 · 조정 · 확정 출하 · ERP 회차).
# 화면 값 = 이 테스트가 손으로 센 값 (QA2 G-15 독립 재계산의 모양).
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from lcomfine.app import dashboard, erp_upload
from lcomfine.db import conn
from test_dev3_world import World, login

Y, M = 2002, 5
F, T = date(Y, M, 1), date(Y, M, 31)
P = (F, T)
TS = lambda d, h=9: datetime(d.year, d.month, d.day, h, 0, tzinfo=timezone(timedelta(hours=9)))  # noqa: E731

BUSINESS_TABLES = ("production_request", "work_order", "production_daily", "inspection_daily", "material_receipt", "material_lot",
                   "material_issue", "material_issue_line", "product_lot", "product_receipt", "incoming_inspection", "product_inspection",
                   "lot_stock", "stock_move", "stock_adjust", "shipment_order", "shipment_line", "shipment_adjust",
                   "erp_upload_batch", "erp_upload_row", "erp_customer_map", "notification", "customer", "item")


def _counts() -> dict:
    return {t: conn.q1(f"select count(*) as n from {t}")["n"] for t in BUSINESS_TABLES}


@pytest.fixture(scope="module")
def c():
    return {lid: login(lid) for lid in ("admin", "ex", "st", "pr", "sl", "sh", "ac", "ds")}


class RptWorld(World):
    """World + 2002-05 의 일보 · 검사 · 자재 · 재고 이동 · 조정 · 확정 출하 · ERP 회차. close() 가 전부 지운다."""

    def __init__(self) -> None:
        super().__init__()
        self.mat_lots: list[int] = []
        self.mat_receipts: list[int] = []
        self.mat_issues: list[int] = []
        self.batches: list[int] = []
        self.erp_code = f"{self.tag}-E"
        # 의뢰 2 — 하나는 지시 있음(World.request_id · wo_id) · 하나는 미착수. 의뢰일 · 납기를 2002-05 로
        conn.x("update production_request set request_date = %s, due_date = %s where id = %s", (date(Y, M, 2), date(Y, M, 20), self.request_id))
        self.req2_id, self.req2_no = self.request(self.item_id, Decimal("30"), date(Y, M, 25))
        conn.x("update production_request set request_date = %s where id = %s", (date(Y, M, 10), self.req2_id))
        conn.x("update work_order set created_at = %s, equipment_code = %s where id = %s", (TS(date(Y, M, 3)), f"{self.tag}A", self.wo_id))
        self.eq = f"{self.tag}A"

    def daily(self, day: date, produced, good, loss, run, stop, wo_id: int | None = None) -> None:
        conn.x("""insert into production_daily (work_order_id, work_date, equipment_code, produced_qty, good_qty, loss_qty, run_minutes, stop_minutes, created_by)
                  values (%s, %s, %s, %s, %s, %s, %s, %s, 'test')""", (wo_id or self.wo_id, day, self.eq, produced, good, loss, run, stop))

    def inspection(self, day: date, inspected, defect, defects: dict) -> None:
        import json
        conn.x("""insert into inspection_daily (work_order_id, work_date, inspected_qty, defect_qty, defects, created_by)
                  values (%s, %s, %s, %s, %s::jsonb, 'test')""", (self.wo_id, day, inspected, defect, json.dumps(defects)))

    def material(self, day: date, qty, judge: str | None = "합격") -> int:
        with conn.tx() as cur:
            cur.execute("insert into material_receipt (supplier_name, received_on, created_by) values (%s, %s, 'test') returning id",
                        (f"공급사 {self.tag} (예시)", day))
            rid = cur.fetchone()["id"]
            cur.execute("""insert into material_lot (lot_no, receipt_id, item_id, qty, created_by) values (%s, %s, %s, %s, 'test') returning id""",
                        (f"{self.tag}-ML{len(self.mat_lots) + 1}", rid, self.item_id, qty))
            lid = cur.fetchone()["id"]
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by) values ('원자재', %s, %s, %s, %s, 'test')""",
                        (lid, self.location_id, qty, "가용" if judge == "합격" else "검사대기"))
            if judge:
                cur.execute("""insert into incoming_inspection (material_lot_id, seq, result, items, inspected_at, inspector)
                               values (%s, 1, %s, '{}'::jsonb, %s, 'test')""", (lid, judge, TS(day)))
        self.mat_receipts.append(rid)
        self.mat_lots.append(lid)
        return lid

    def issue(self, day: date, lot_id: int, qty) -> int:
        with conn.tx() as cur:
            cur.execute("insert into material_issue (issued_on, created_by) values (%s, 'test') returning id", (day,))
            iid = cur.fetchone()["id"]
            cur.execute("""insert into material_issue_line (issue_id, material_lot_id, work_order_id, location_id, qty, created_by)
                           values (%s, %s, %s, %s, %s, 'test')""", (iid, lot_id, self.wo_id, self.location_id, qty))
            cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, from_location_id, qty, ref_table, ref_id, moved_at, created_by)
                           values ('불출', '원자재', %s, %s, %s, 'material_issue_line', %s, %s, 'test')""",
                        (lot_id, self.location_id, qty, iid, TS(day)))
            cur.execute("update lot_stock set qty = qty - %s where lot_kind = '원자재' and lot_id = %s", (qty, lot_id))
        self.mat_issues.append(iid)
        return iid

    def adjust(self, day: date, lot_id: int, book, actual) -> None:
        conn.x("""insert into stock_adjust (lot_kind, lot_id, location_id, book_qty, actual_qty, reason, adjusted_at, created_by)
                  values ('원자재', %s, %s, %s, %s, '실사 차이 (예시)', %s, 'test')""", (lot_id, self.location_id, book, actual, TS(day)))

    def ship(self, day: date, lot: dict, qty, *, request_id: int | None = None) -> dict:
        with conn.tx() as cur:
            cur.execute("""insert into shipment_order (shipment_no, request_id, customer_id, due_date, status, confirmed_at, confirmed_by, created_by)
                           values (%s, %s, %s, %s, '확정', %s, 'test', 'test') returning id, shipment_no""",
                        (f"{self.tag}-SHP{day.day}", request_id, self.customer_id, date(Y, M, 20), TS(day, 14)))
            o = dict(cur.fetchone())
            cur.execute("""insert into shipment_line (shipment_order_id, product_lot_id, location_id, qty, created_by) values (%s, %s, %s, %s, 'test')""",
                        (o["id"], lot["id"], self.location_id, qty))
            cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, from_location_id, qty, ref_table, ref_id, moved_at, created_by)
                           values ('출하', '제품', %s, %s, %s, 'shipment_order', %s, %s, 'test')""", (lot["id"], self.location_id, qty, o["id"], TS(day, 14)))
        return o

    def erp(self, rows: list[tuple[date, Decimal | None, Decimal | None]]) -> int:
        """반영 회차 1 + 매핑 — rows = [(일자, 매출, 수금)]. 기준 기간 = 2002-05."""
        with conn.tx() as cur:
            cur.execute("""insert into erp_customer_map (erp_code, erp_name, customer_id, created_by) values (%s, %s, %s, 'test')""",
                        (self.erp_code, f"ERP {self.tag} (예시)", self.customer_id))
            cur.execute("""insert into erp_upload_batch (batch_no, period_from, period_to, round_no, status, source_file, row_count, created_by)
                           values (%s, %s, %s, 1, '반영', 'rpt (예시).xlsx', %s, 'test') returning id""", (f"{self.tag}-ERP", F, T, len(rows)))
            bid = cur.fetchone()["id"]
            for i, (d, s, k) in enumerate(rows, start=2):
                parsed = {"customer_code": self.erp_code, "txn_date": d.isoformat(),
                          "sales_amount": str(s) if s is not None else "", "collected_amount": str(k) if k is not None else ""}
                import json
                cur.execute("insert into erp_upload_row (batch_id, row_no, raw, parsed, created_by) values (%s, %s, '{}'::jsonb, %s::jsonb, 'test')",
                            (bid, i, json.dumps(parsed)))
        self.batches.append(bid)
        return bid

    def close(self) -> None:
        with conn.tx() as cur:
            if self.batches:
                cur.execute("delete from erp_upload_row where batch_id = any(%s)", (self.batches,))
                cur.execute("delete from erp_upload_batch where id = any(%s)", (self.batches,))
            cur.execute("delete from erp_customer_map where erp_code = %s", (self.erp_code,))
            cur.execute("delete from inspection_daily where work_order_id = any(%s)", (self.wos,))
            if self.mat_lots:
                cur.execute("set local session_replication_role = replica")
                cur.execute("delete from stock_adjust where lot_kind = '원자재' and lot_id = any(%s)", (self.mat_lots,))
                cur.execute("set local session_replication_role = origin")
                cur.execute("delete from stock_move where lot_kind = '원자재' and lot_id = any(%s)", (self.mat_lots,))
                cur.execute("delete from material_issue_line where material_lot_id = any(%s)", (self.mat_lots,))
                cur.execute("delete from material_issue where id = any(%s)", (self.mat_issues,))
                cur.execute("delete from incoming_inspection where material_lot_id = any(%s)", (self.mat_lots,))
                cur.execute("delete from lot_stock where lot_kind = '원자재' and lot_id = any(%s)", (self.mat_lots,))
                cur.execute("delete from material_lot where id = any(%s)", (self.mat_lots,))
                cur.execute("delete from material_receipt where id = any(%s)", (self.mat_receipts,))
        super().close()


@pytest.fixture
def w():
    world = RptWorld()
    yield world
    world.close()


def _kpi(data: dict, key: str) -> dict:
    return next(k for k in data["kpis"] if k["key"] == key)


def _kpi_html(page: str, key: str) -> str:
    i = page.index(f'data-kpi="{key}"')
    return page[i:i + 600]


def _series_numbers(page: str, name: str) -> tuple[list[str], list[str]]:
    """SVG <title> 의 「라벨: 값」 과 같은 이름의 표 둘째 열 — 둘이 같은 숫자여야 한다(접근성 · 표가 차트의 숫자를 담는다)."""
    i = page.index(f'data-series="{name}"')
    j = page.index("</section>", i)
    seg = page[i:j]
    titles = re.findall(r"<title>[^<]*?: ([^<]+)</title>", seg)
    cells = re.findall(r'<td class="num">([^<]+)</td>', seg)
    return titles, cells


# ── dashboard 8 — 빈 기간은 미수집 ───────────────────────────────────────────────

def test_dashboard_empty_period_is_not_collected():
    empty = (date(1975, 1, 1), date(1975, 1, 7))
    for fn in (dashboard.orders, dashboard.production, dashboard.quality, dashboard.inventory, dashboard.shipment, dashboard.order_flow):
        d = fn(empty)
        assert set(d) >= {"kpis", "series", "tables", "asof", "period", "bucket"}
        assert d["bucket"] == ("month" if fn is dashboard.order_flow else "day")   # 주문 흐름은 월 단위(수금이 월 단위)
        for k in d["kpis"]:
            assert k["value"] is None, (fn.__name__, k)              # 0건 = 미수집 (0 으로 지어내지 않는다)
        for name, s in d["series"].items():
            assert all(p["value"] is None for p in s), (fn.__name__, name)
    assert _kpi(dashboard.production(empty), "loss_rate")["text"] == "미확정 (D-519)"
    assert _kpi(dashboard.quality(empty), "loss_rate")["text"] == "미확정 (D-519)"
    assert _kpi(dashboard.order_flow(empty), "bottleneck")["text"] == "미확정 (D-520)"
    s = dashboard.summary(empty)
    assert s["kind"] == "주간" and [x["screen_id"] for x in s["tables"]["sections"]] == ["RPT-040", "RPT-050", "RPT-010", "RPT-020", "RPT-060"]
    assert dashboard.summary((F, F))["kind"] == "일일"
    assert dashboard.summary("2002-05")["kind"] == "월간" and dashboard.summary("2002-05")["bucket"] == "day"
    with pytest.raises(ValueError):
        dashboard.orders("2002/05")


# ── RPT-010 수주 ────────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-011")
def test_orders_report(c, w):
    before = _counts()
    d = dashboard.orders(P, w.customer_id)
    assert _kpi(d, "requests")["value"] == 2 and _kpi(d, "qty")["value"] == Decimal("80")
    assert _kpi(d, "not_started")["value"] == 1 and _kpi(d, "customers")["value"] == 1
    assert [r["request_no"] for r in d["tables"]["not_started"]] == [w.req2_no]
    got = {p["label"]: p["value"] for p in d["series"]["requests"]}
    assert got["2002-05-02"] == 1 and got["2002-05-10"] == 1 and got["2002-05-03"] is None and len(got) == 31
    assert d["series"]["due"] == [{"label": "2002-05", "value": 2}]
    assert d["tables"]["top_customers"][0]["requests"] == 2
    r = c["sl"].get("/rpt/orders", params={"date_from": F.isoformat(), "date_to": T.isoformat(), "customer": str(w.customer_id)})
    assert r.status_code == 200 and "미구현" not in r.text
    assert ">2</strong>" in _kpi_html(r.text, "requests").replace(" <small>건</small>", "") or "2 <small>건</small>" in _kpi_html(r.text, "requests")
    titles, cells = _series_numbers(r.text, "requests")
    assert titles and titles[1] == "1" and cells[1] == "1" and len(cells) == 31 and cells.count("미수집") == 29
    assert "<title>" in r.text and 'role="img"' in r.text
    assert c["sl"].get("/rpt/orders", params={"date_from": "2002-13-01"}).status_code == 422
    assert c["sl"].get("/rpt/orders", params={"date_from": T.isoformat(), "date_to": F.isoformat()}).status_code == 422
    assert c["sl"].get("/rpt/orders", params={"customer": "999999999"}).status_code == 422
    assert c["sh"].get("/rpt/orders").status_code == 403                     # 출하실 칸 없음
    assert c["ds"].get("/rpt/orders").status_code == 403
    assert _counts() == before                                               # 읽기만


# ── RPT-020 생산 ────────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-021")
def test_production_report(c, w):
    w.daily(date(Y, M, 5), 100, 90, 10, 300, 100)
    w.daily(date(Y, M, 6), 50, 48, 2, 100, 0)
    w.daily(date(Y, M + 1, 1), 999, 999, 0, 999, 0)                          # 다음 달 — 세지 않는다
    before = _counts()
    d = dashboard.production(P)
    assert _kpi(d, "work_orders")["value"] == 1 and _kpi(d, "order_qty")["value"] == Decimal("100")
    assert _kpi(d, "produced_qty")["value"] == Decimal("150") and _kpi(d, "good_qty")["value"] == Decimal("138")
    assert _kpi(d, "loss_qty")["value"] == Decimal("12") and _kpi(d, "loss_rate")["text"] == "미확정 (D-519)"
    assert _kpi(d, "utilization")["value"] == Decimal("80.0")                 # 400 ÷ (400 + 100) — D-801
    got = {p["label"]: p["value"] for p in d["series"]["good_qty"]}
    assert got["2002-05-05"] == Decimal("90") and got["2002-05-06"] == Decimal("48") and got["2002-05-07"] is None
    eq = {m["equipment_code"]: m for m in d["tables"]["by_equipment"]}
    assert eq[w.eq]["good_qty"] == Decimal("138")
    r = c["pr"].get("/rpt/production", params={"date_from": F.isoformat(), "date_to": T.isoformat()})
    assert r.status_code == 200
    assert "미확정 (D-519)" in _kpi_html(r.text, "loss_rate") and "80.0" in _kpi_html(r.text, "utilization")
    titles, cells = _series_numbers(r.text, "good_qty")
    assert "90" in titles and "90" in cells and titles.count("미수집") == cells.count("미수집") == 29
    assert c["sl"].get("/rpt/production").status_code == 403                 # 영업부 칸 없음
    assert _counts() == before


# ── RPT-030 품질 ────────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-031")
def test_quality_report(c, w):
    w.inspection(date(Y, M, 5), 100, 4, {"DF01": "3", "ZZ": "1"})
    w.inspection(date(Y, M, 6), 50, 1, {"DF01": "1"})
    lot = w.lot("10", judge="불합격")
    conn.x("update product_inspection set inspected_at = %s where product_lot_id = %s", (TS(date(Y, M, 7)), lot["id"]))
    w.judge(lot["id"], "합격", "가용")
    conn.x("update product_inspection set inspected_at = %s where product_lot_id = %s and seq = 2", (TS(date(Y, M, 8)), lot["id"]))
    mlot = w.material(date(Y, M, 4), 20, judge="불합격")
    before = _counts()
    d = dashboard.quality(P)
    assert _kpi(d, "inspected_qty")["value"] == Decimal("150") and _kpi(d, "defect_qty")["value"] == Decimal("5")
    assert _kpi(d, "loss_rate")["text"] == "미확정 (D-519)"
    assert _kpi(d, "judgements")["value"] == 3 and _kpi(d, "rejected_lots")["value"] == 2 and _kpi(d, "rejudged")["value"] == 1
    rej = {(j["inspection_kind"], j["lot_no"]) for j in d["tables"]["rejected"]}
    assert rej == {("제품검사", lot["lot_no"]), ("입고검사", f"{w.tag}-ML1")}
    rj = d["tables"]["rejudged"][0]
    assert rj["seq"] == 2 and rj["previous_result"] == "불합격" and rj["result"] == "합격"
    by_type = {x["defect_code"]: x["qty"] for x in d["tables"]["defects_by_type"]}
    assert by_type["DF01"] == Decimal("4") and by_type["ZZ"] == Decimal("1")
    r = c["pr"].get("/rpt/quality", params={"date_from": F.isoformat(), "date_to": T.isoformat()})
    assert r.status_code == 200 and lot["lot_no"] in r.text and "미확정 (D-519)" in _kpi_html(r.text, "loss_rate")
    titles, cells = _series_numbers(r.text, "defects")
    assert titles == cells and "4" in cells
    assert c["ac"].get("/rpt/quality").status_code == 403
    assert _counts() == before
    assert mlot


# ── RPT-040 재고·창고 ─────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-041")
def test_inventory_report(c, w):
    l1 = w.material(date(Y, M, 3), 100)
    l2 = w.material(date(Y, M, 4), 50)
    w.issue(date(Y, M, 5), l1, 30)
    w.adjust(date(Y, M, 6), l2, 50, 47)
    w.lot("10", received_on=date(Y, M, 7))                                     # 제품 입고 1
    before = _counts()
    d = dashboard.inventory(P)
    assert _kpi(d, "material_receipts")["value"] == 2 and _kpi(d, "material_receipt_qty")["value"] == Decimal("150")
    assert _kpi(d, "issues")["value"] == 1 and _kpi(d, "issue_qty")["value"] == Decimal("30")
    assert _kpi(d, "product_receipts")["value"] == 1 and _kpi(d, "product_receipt_qty")["value"] == Decimal("10")
    assert _kpi(d, "adjusts")["value"] == 1 and _kpi(d, "adjust_diff")["value"] == Decimal("-3")
    top = {m["lot_no"]: m for m in d["tables"]["top_moves"]}
    assert top[f"{w.tag}-ML1"]["qty"] == Decimal("30") and top[f"{w.tag}-ML1"]["kinds"] == "불출"
    assert any(x["lot_no"] == f"{w.tag}-ML2" for x in d["tables"]["long_stay"]) or len(d["tables"]["long_stay"]) == dashboard.TOP_N
    assert d["tables"]["adjusts"][0]["diff_qty"] == Decimal("-3")
    got = {p["label"]: p["value"] for p in d["series"]["receipt_qty"]}
    assert got["2002-05-03"] == Decimal("100") and got["2002-05-04"] == Decimal("50")
    r = c["pr"].get("/rpt/inventory", params={"date_from": F.isoformat(), "date_to": T.isoformat()})
    assert r.status_code == 200 and "-3.000" in r.text and "체류일(오늘 − LOT 생성일)" in r.text   # 장기 체류 정의 — 화면 도움말(옛 본문 「D-805」)
    titles, cells = _series_numbers(r.text, "issue_qty")
    assert "30" in titles and "30" in cells and titles == cells
    assert c["sl"].get("/rpt/inventory").status_code == 403
    assert _counts() == before


# ── RPT-050 출하 ────────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-051")
def test_shipment_report(c, w):
    lot = w.lot("60")
    o = w.ship(date(Y, M, 15), lot, 50, request_id=w.request_id)                # 의뢰 50 · 납기 05-20 · 확정 05-15 → 납기 안 완료
    w.ship(date(Y, M, 16), lot, 5)                                               # 의뢰번호 없음 — 준수율에 안 든다
    before = _counts()
    d = dashboard.shipment(P, w.customer_id)
    assert _kpi(d, "shipments")["value"] == 2 and _kpi(d, "qty")["value"] == Decimal("55") and _kpi(d, "customers")["value"] == 1
    assert _kpi(d, "due_rate")["value"] == Decimal("50.0")                      # 의뢰 2 (납기 05-20 · 05-25 ≤ 2002) → 완료 1 · 지연 1
    assert _kpi(d, "on_time")["value"] == 1 and _kpi(d, "late_open")["value"] == 1
    assert {r["request_no"]: r["bucket"] for r in d["tables"]["due_rows"]} == {w.request_no: "납기 안 완료", w.req2_no: "지연"}
    assert d["tables"]["by_customer"][0]["qty"] == Decimal("55") and d["tables"]["recent"][0]["shipment_no"] == f"{w.tag}-SHP16"
    got = {p["label"]: p["value"] for p in d["series"]["qty"]}
    assert got["2002-05-15"] == Decimal("50") and got["2002-05-16"] == Decimal("5")
    assert dashboard.shipment(P)["kpis"][0]["value"] >= 2                        # 전체 거래처
    r = c["sh"].get("/rpt/shipment", params={"date_from": F.isoformat(), "date_to": T.isoformat(), "customer": str(w.customer_id)})
    assert r.status_code == 200 and o["shipment_no"] in r.text and "50.0" in _kpi_html(r.text, "due_rate") and "납기 안 완료 ÷" in r.text   # 산식 — 화면 도움말(옛 본문 「D-804」)
    titles, cells = _series_numbers(r.text, "qty")
    assert "50" in titles and "50" in cells and "5" in cells and titles == cells
    assert c["pr"].get("/rpt/shipment").status_code == 403
    assert _counts() == before


# ── RPT-060 수금 ────────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-061")
def test_collection_report(c, w):
    lot = w.lot("20")
    w.ship(date(Y, M, 15), lot, 20, request_id=w.request_id)
    asof_before = dashboard.collection(P, w.customer_id)
    if asof_before["asof"] is None:                                              # 반영 회차가 없으면 전부 미수집
        assert _kpi(asof_before, "asof")["text"] == "미수집" and _kpi(asof_before, "over90")["text"] == "미수집"
    bid = w.erp([(date(Y, M, 3), Decimal("1000"), None), (date(Y, M, 20), None, Decimal("400")), (date(1990, 1, 1), Decimal("300"), None)])
    before = _counts()
    d = dashboard.collection(P, w.customer_id)
    assert d["asof"] is not None and d["asof"] >= T
    m = {x["ym"]: x for x in d["tables"]["monthly"]}
    assert m["2002-05"]["collected_amount"] == Decimal("400") and m["2002-05"]["shipped_qty"] == Decimal("20") and m["2002-05"]["shipments"] == 1
    assert _kpi(d, "collected")["value"] == Decimal("400") and _kpi(d, "shipped_qty")["value"] == Decimal("20")
    if erp_upload.mapped_fields()["sales_amount"]:
        assert _kpi(d, "sales")["value"] == Decimal("1000")
        assert any(r["customer_id"] == w.customer_id for r in d["tables"]["over90"])     # 1990 매출 300 은 90일 초과 순액
    else:
        assert _kpi(d, "sales")["text"] == "미확정 (D-516)"
    assert d["series"]["collected"] == [{"label": "2002-05", "value": Decimal("400")}]
    r = c["ac"].get("/rpt/collection", params={"date_from": F.isoformat(), "date_to": T.isoformat(), "customer": str(w.customer_id)})
    assert r.status_code == 200 and "ERP 업로드 기준일" in r.text and d["asof"].isoformat() in r.text
    titles, cells = _series_numbers(r.text, "collected")
    assert titles == ["400"] and cells == ["400"]
    assert c["pr"].get("/rpt/collection").status_code == 403 and c["sh"].get("/rpt/collection").status_code == 403
    assert _counts() == before
    assert bid in w.batches


# ── RPT-070 주문 흐름 ─────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-071")
def test_order_flow_report(c, w):
    w.daily(date(Y, M, 6), 50, 50, 0, 100, 0)
    lot = w.lot("50", received_on=date(Y, M, 8))
    w.ship(date(Y, M, 12), lot, 50, request_id=w.request_id)
    before = _counts()
    d = dashboard.order_flow(P, w.customer_id)
    rows = {r["request_no"]: r for r in d["tables"]["rows"]}
    r1 = rows[w.request_no]
    assert (r1["request_date"], r1["ordered_on"], r1["produced_on"], r1["received_on"], r1["shipped_on"]) == \
        (date(Y, M, 2), date(Y, M, 3), date(Y, M, 6), date(Y, M, 8), date(Y, M, 12))
    assert r1["days"] == {"의뢰 → 지시": 1, "지시 → 생산 완료": 3, "생산 완료 → 제품 입고": 2, "제품 입고 → 출하": 4, "의뢰 → 출하": 10}
    assert r1["bottleneck"] == "미확정 (D-520)"
    r2 = rows[w.req2_no]
    assert r2["ordered_on"] is None and all(v is None for v in r2["days"].values())
    stages = {s["stage"]: s for s in d["tables"]["stages"]}
    assert stages["의뢰 → 출하"]["count"] == 1 and stages["의뢰 → 출하"]["avg_days"] == Decimal("10.0")
    assert _kpi(d, "requests")["value"] == 2 and _kpi(d, "shipped")["value"] == 1 and _kpi(d, "bottleneck")["text"] == "미확정 (D-520)"
    r = c["ex"].get("/rpt/order-flow", params={"date_from": F.isoformat(), "date_to": T.isoformat(), "customer": str(w.customer_id)})
    assert r.status_code == 200 and "미확정 (D-520)" in r.text
    assert "ERP 업로드 기준일" in r.text and (d["asof"].isoformat() if d["asof"] else "미수집") in r.text   # DEF-QA2-005 · Ruling 29 — RPT-060 과 같은 매크로
    seg = r.text[r.text.index(f'data-request="{w.request_no}"'):]
    seg = seg[:seg.index("</tr>")]
    assert seg.count("미수집") == 0 and ">10<" in seg and "2002-05-12" in seg
    titles, cells = _series_numbers(r.text, "avg_days")
    assert titles == cells and "10" in cells
    assert c["pr"].get("/rpt/order-flow").status_code == 403
    assert _counts() == before


# ── RPT-080 경영 요약 ─────────────────────────────────────────────────────────────

@pytest.mark.fn("F-RPT-081")
def test_summary_tabs(c, w):
    lot = w.lot("10")
    w.ship(date(Y, M, 15), lot, 10, request_id=w.request_id)
    before = _counts()
    daily = c["ex"].get("/rpt/summary", params={"tab": "daily", "asof": date(Y, M, 15).isoformat()})
    assert daily.status_code == 200 and 'data-section="RPT-040"' in daily.text and 'data-section="RPT-050"' in daily.text
    assert 'data-section="RPT-010"' not in daily.text and "일일" in daily.text
    assert "10.000" in _kpi_html(daily.text, "qty")
    monthly = c["st"].get("/rpt/summary", params={"tab": "monthly", "asof": T.isoformat(), "customer": str(w.customer_id)})
    assert monthly.status_code == 200
    for sid in ("RPT-040", "RPT-050", "RPT-010", "RPT-020", "RPT-060"):
        assert f'data-section="{sid}"' in monthly.text
    assert "미확정 (D-519)" in monthly.text and "해설 문장은 없습니다" in monthly.text
    weekly = c["admin"].get("/rpt/summary", params={"tab": "weekly"})
    assert weekly.status_code == 200 and "주간" in weekly.text
    assert c["ex"].get("/rpt/summary", params={"tab": "yearly"}).status_code == 422
    assert c["ex"].get("/rpt/summary", params={"asof": "x"}).status_code == 422
    assert c["pr"].get("/rpt/summary").status_code == 403 and c["sl"].get("/rpt/summary").status_code == 403
    assert _counts() == before


# ── 데이터 질의 제거 (D-529) — 화면 · 기능 · 모듈 · 로그 표가 없다 ─────────────────────────

def test_data_query_removed(c):
    """옛 RPT-130 데이터 질의: 경로 GET · POST 404(옛 칸 부서 ex · st · admin 포함) · 대시보드 메뉴에 없음 · ai · dataquery 모듈 없음 · 로그 표 없음."""
    import importlib.util

    from lcomfine.app import contracts, nav

    for lid in ("ex", "st", "admin", "sl"):
        assert c[lid].get("/rpt/query").status_code == 404, lid
        assert c[lid].post("/rpt/query", data={"question": "x"}).status_code == 404, lid
    assert [s_.screen_id for s_ in nav.SCREENS if s_.menu_code == "RPT"] == [f"RPT-0{i}0" for i in range(1, 9)]
    assert not [f for f in contracts.functions() if f.screen_id == "RPT-130"]
    page = c["ex"].get("/rpt/summary", headers={"accept": "text/html"})
    assert page.status_code == 200 and "/rpt/query" not in page.text and "데이터 질의" not in page.text
    assert importlib.util.find_spec("lcomfine.app.ai") is None and importlib.util.find_spec("lcomfine.app.dataquery") is None
    for t in ("data_query_log", "sys_ai_call_log", "v_dq_orders", "v_dq_collections"):
        assert conn.q1("select to_regclass(%s) is null as gone", (t,))["gone"], t


@pytest.mark.fn("F-RPT-011")
def test_dashboard_filter_error_is_json_422_without_html_accept(c):
    """DEF-QA1-007 — Accept 에 text/html 이 없으면 조회 조건 오류가 JSON 422(code · message · fields 항목) · 브라우저는 같은 화면 422 재렌더."""
    r = c["sl"].get("/rpt/orders", params={"date_from": "2002-13-01"})
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["code"] == "validation_error" and "시작일" in body["message"] and body["fields"][0]["name"] == "시작일"
    r = c["sl"].get("/rpt/orders", params={"customer": "abc"})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "거래처"
    r = c["ex"].get("/rpt/summary", params={"tab": "yearly"})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "탭"
    html = c["sl"].get("/rpt/orders", params={"date_from": "2002-13-01"}, headers={"accept": "text/html"})
    assert html.status_code == 422 and html.headers["content-type"].startswith("text/html") and "시작일" in html.text and 'name="date_from"' in html.text
