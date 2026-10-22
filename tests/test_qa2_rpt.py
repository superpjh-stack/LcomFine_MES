# tests/test_qa2_rpt.py — QA2 W3 대시보드: G-15 「RPT-010~080 의 모든 수치 = QA2 가 따로 짠 SQL 재계산(D-512 · D-805)」 + G-05 RPT 8 화면 diff 0.
#
# - tools/check_data.py 의 흐름 중 기준정보(BAS) → E2E(의뢰 → 출하 확정) → 수금(ERP 업로드) → 대시보드(dashboards) 만 한 번 돌리고 그 실측 위에서 판정한다.
#   대시보드 단계는 화면 8 마다 `dashboard.<fn>(period, customer_id)` 반환 · **check_data 의 독립 SQL** · 화면 HTML(`data-kpi` 글자 · `data-series` SVG <title>
#   「라벨: 값」 · 표 둘째 열 · `data-table` 행) 셋을 대조한다. 세계 = 이 흐름의 달(S1 확정 월) · 거래처 C1(흐름) · C2(ERP 만 · 의뢰 · 출하 없음).
# - 이 파일은 그 위에 **두 번째 독립 SQL**(허용 뷰 `v_dq_*` · 다른 꼴의 문장)로 핵심 KPI 를 한 번 더 센다. 020 · 030 · 040 은 전 DB 집계라(다른 QA 가 같은 DB 에
#   쓴다) 이 파일의 두 번째 SQL 은 「이 흐름의 행이 든 값」(지시 · 일보 · 입고 LOT)만 본다.
# - 앱 코드는 고치지 않는다. 만든 행은 접두 `QA2-` 로 구분하고 모듈이 끝나면 지운다.
from datetime import date, timedelta
from decimal import Decimal

import pytest

from lcomfine.app import dashboard
from tools import check_data as cd


@pytest.fixture(scope="module")
def flow():
    """기준정보 → E2E → 수금 → 대시보드 단계만 돈다(추적 · 차단 · 할당 · 알림 · diff 는 tests/test_qa2_flow.py · 수금 세부는 tests/test_qa2_col.py)."""
    report = cd.Report()
    f = cd.Flow(report)
    f.run(keep=True, only={"base", "e2e", "collections", "dashboards"})
    try:
        yield f
    finally:
        note = f.cleanup()
        assert note.startswith("정리 완료"), note


def _rows(f: cd.Flow, gate: str, prefix: str) -> list[cd.Check]:
    rows = [c for c in f.r.checks if c.gate == gate and c.item.startswith(prefix)]
    assert rows, f"{gate} {prefix!r} 검사 행이 없다 — 앞 단계 실패: " + "; ".join(
        f"{c.item}: {c.measured}" for c in f.r.checks if c.status == cd.FAIL)
    return rows


def _all_pass(rows: list[cd.Check]) -> None:
    bad = [f"{c.gate}  {c.item}  {c.status}  {c.measured}" for c in rows if c.status != cd.PASS]
    assert not bad, "\n".join(bad)


def _period(flow: cd.Flow) -> tuple[date, date]:
    return flow.v["g15"]["period"]


def _eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return Decimal(str(a)) == Decimal(str(b))


# ── RPT-010 수주 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-011")
def test_g15_rpt010_orders_equals_independent_sql_and_screen(flow):
    """dashboard.orders(이 달, C1) = check_data 독립 SQL = 화면 KPI · SVG title · 표. 두 번째 독립 SQL: 허용 뷰 v_dq_orders 로 건수 · 수량 · 미착수."""
    _all_pass(_rows(flow, "G-15", "RPT-010"))
    g = flow.v["g15"]["orders"]
    f, t = _period(flow)
    row = flow.q1("""select count(*) as n, sum(o.qty) as q,
                            count(*) filter (where not exists (select 1 from work_order w join production_request r on r.id = w.request_id
                                                                 where r.request_no = o.request_no and w.status <> '취소')) as ns
                       from v_dq_orders o
                      where o.customer_code = %s and o.request_date between %s and %s and o.status <> '취소'""", (f"{flow.tag}-C", f, t))
    assert g["kpis"] == g["indep"], (g["kpis"], g["indep"])
    assert (g["kpis"]["requests"], g["kpis"]["not_started"]) == (row["n"], row["ns"]) and _eq(g["kpis"]["qty"], row["q"]), (g, dict(row))
    assert row["n"] >= 2 and row["ns"] >= 1          # 이 흐름의 R1(지시 있음) · R2(미착수) 가 들어 있다


# ── RPT-020 생산 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-021")
def test_g15_rpt020_production_equals_independent_sql_and_screen(flow):
    """dashboard.production(이 달) = 독립 SQL = 화면 · 로스율 「미확정 (D-519)」 · 가동률 D-801 · 기계별 = 설비별 합. 두 번째 SQL: 이 흐름의 지시 일보 100/95/5 · 480/30."""
    _all_pass(_rows(flow, "G-15", "RPT-020"))
    g = flow.v["g15"]["production"]
    assert g["kpis"] == g["indep"], (g["kpis"], g["indep"])
    mine = flow.q1("select sum(produced_qty) as p, sum(good_qty) as g, sum(loss_qty) as l, sum(run_minutes) as r, sum(stop_minutes) as s from production_daily where work_order_id = %s",
                   (flow.v["WOid"],))
    assert (mine["p"], mine["g"], mine["l"], mine["r"], mine["s"]) == (100, 95, 5, 480, 30), dict(mine)
    assert g["kpis"]["produced_qty"] >= 100 and g["kpis"]["good_qty"] >= 95 and g["kpis"]["work_orders"] >= 1
    assert g["kpis"]["utilization"] is not None and 0 <= g["kpis"]["utilization"] <= 100


# ── RPT-030 품질 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-031")
def test_g15_rpt030_quality_equals_independent_sql_and_screen(flow):
    """dashboard.quality(이 달) = 독립 SQL = 화면 · 검사 로스율 「미확정 (D-519)」 · 불합격 LOT · 재판정. 두 번째 SQL: 이 흐름의 검사일보 95/2 · DF01 2 · 판정 행이 든다."""
    _all_pass(_rows(flow, "G-15", "RPT-030"))
    g = flow.v["g15"]["quality"]
    assert g["kpis"] == g["indep"], (g["kpis"], g["indep"])
    mine = flow.q1("select sum(inspected_qty) as i, sum(defect_qty) as d, sum((defects ->> 'DF01')::numeric) as df from inspection_daily where work_order_id = %s",
                   (flow.v["WOid"],))
    assert (mine["i"], mine["d"], mine["df"]) == (95, 2, 2), dict(mine)
    judged = flow.q1("""select count(*) as n from (select 1 from incoming_inspection q join material_lot m on m.id = q.material_lot_id where m.lot_no = any(%s)
                                                  union all select 1 from product_inspection q join product_lot p on p.id = q.product_lot_id where p.lot_no = any(%s)) x""",
                     (flow.mlot_nos, flow.plot_nos))["n"]
    assert judged >= 4 and g["kpis"]["judgements"] >= judged           # 입고검사 2 + 제품검사 2 이상이 이 달 판정에 든다
    assert g["kpis"]["inspected_qty"] >= 95 and g["kpis"]["defect_qty"] >= 2


# ── RPT-040 재고·창고 ────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-041")
def test_g15_rpt040_inventory_equals_independent_sql_and_screen(flow):
    """dashboard.inventory(이 달) = 독립 SQL = 화면 · 변동 상위 · 장기 체류 · 실사 차이. 두 번째 SQL: 이 흐름의 입고 LOT(원 LOT 120 + 80 · 분할 LOT 제외) · 불출 150 · 제품 입고 110."""
    _all_pass(_rows(flow, "G-15", "RPT-040"))
    g = flow.v["g15"]["inventory"]
    assert g["kpis"] == g["indep"], (g["kpis"], g["indep"])
    lots = flow.q1("select sum(qty) as q, count(*) as n from material_lot where receipt_id = any(%s) and parent_lot_id is null and canceled_at is null", (flow.receipt_ids,))
    assert (lots["q"], lots["n"]) == (200, 2), dict(lots)
    issued = flow.q1("select sum(l.qty) as q from material_issue_line l where l.issue_id = any(%s)", (flow.issue_ids,))["q"]
    prod = flow.q1("select sum(qty) as q, count(*) as n from product_receipt where work_order_id = %s and canceled_at is null", (flow.v["WOid"],))
    assert issued == 150 and (prod["q"], prod["n"]) == (110, 3)
    assert g["kpis"]["material_receipt_qty"] >= 200 and g["kpis"]["issue_qty"] >= 150 and g["kpis"]["product_receipt_qty"] >= 110


# ── RPT-050 출하 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-051")
def test_g15_rpt050_shipment_equals_independent_sql_and_screen(flow):
    """dashboard.shipment(이 달, C1) = 독립 SQL = 화면 · 납기 준수율 D-804. 두 번째 독립 SQL: 허용 뷰 v_dq_shipments(확정 · 확정일 · 거래처 코드)."""
    _all_pass(_rows(flow, "G-15", "RPT-050"))
    g = flow.v["g15"]["shipment"]
    f, t = _period(flow)
    assert g["kpis"] == g["indep"], (g["kpis"], g["indep"])
    row = flow.q1("""select count(distinct shipment_no) as n, sum(qty) as q from v_dq_shipments
                      where customer_code = %s and status = '확정' and confirmed_at::date between %s and %s""", (f"{flow.tag}-C", f, t))
    assert g["kpis"]["shipments"] == row["n"] and _eq(g["kpis"]["qty"], row["q"]), (g, dict(row))
    assert row["n"] >= 1 and row["q"] >= 60                         # S1 60 이 든다
    # 납기 준수율 모집단(D-804) — 이 거래처 · 납기가 이 달인 취소 아닌 의뢰 수 = 네 묶음의 합(진행 포함)
    due_n = flow.q1("select count(*) as n from production_request where customer_id = %s and status <> '취소' and due_date between %s and %s",
                    (flow.customer_id, f, t))["n"]
    denom = sum((g["kpis"][k] or 0) for k in ("on_time", "late_done", "late_open"))
    assert denom <= due_n
    assert (g["kpis"]["due_rate"] is None) == (denom == 0)          # 분모 0 = 미수집 · 0 % 로 적지 않는다


# ── RPT-060 수금 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-061")
def test_g15_rpt060_collection_equals_independent_sql_asof_shown(flow):
    """dashboard.collection(이 달, C1) = 독립 SQL(ERP 반영 회차 테이블 직접) = 화면 · 「ERP 업로드 기준일」 머리 · KPI 명시.
    두 번째 독립 SQL: 허용 뷰 v_dq_collections(월) 와 erp_upload_batch 의 반영 회차 period_to 최댓값."""
    _all_pass(_rows(flow, "G-15", "RPT-060"))
    _all_pass(_rows(flow, "G-15", "ERP 업로드 기준일"))
    g = flow.v["g15"]["collection"]
    f, t = _period(flow)
    assert g["kpis"] == g["indep"] and g["asof"] == g["indep_asof"], g
    row = flow.q1("select sum(collected_amount) as c, sum(sales_amount) as s from v_dq_collections where customer_code = %s and txn_date between %s and %s",
                  (f"{flow.tag}-C", f, t))
    assert _eq(g["kpis"]["collected"], row["c"]) and _eq(g["kpis"]["sales"], row["s"]), (g, dict(row))
    assert (row["c"], row["s"]) == (Decimal(300), Decimal(1000))          # E 행 2 (매출 1,000 · 수금 300)
    asof = flow.q1("select max(period_to) as d from erp_upload_batch where status = '반영'")["d"]
    assert g["asof"] == asof.isoformat() and asof >= flow.v["P"][1]        # 이 흐름의 기간 P 회차가 반영이라 그 끝 이상
    assert _eq(g["kpis"]["shipped_qty"], 60)


# ── RPT-070 주문 흐름 ────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-071")
def test_g15_rpt070_order_flow_equals_independent_sql_bottleneck_undecided(flow):
    """dashboard.order_flow(이 달, C1) = 독립 SQL = 화면 · 단계 5 소요일 · 병목 「미확정 (D-520)」. 두 번째 SQL: R1 의 의뢰 → 출하 = 확정일 − 의뢰일."""
    _all_pass(_rows(flow, "G-15", "RPT-070"))
    g = flow.v["g15"]["order_flow"]
    assert g["kpis"] == g["indep"], (g["kpis"], g["indep"])
    r1 = g["R1_days"]
    assert r1 and all(v is not None for v in r1.values()) and len(r1) == 5, r1
    span = flow.q1("""select (max(o.confirmed_at)::date - r.request_date) as d from production_request r join shipment_order o on o.request_id = r.id and o.status = '확정'
                       where r.id = %s group by r.request_date""", (flow.v["R1id"],))["d"]
    assert r1["의뢰 → 출하"] == span
    assert g["kpis"]["requests"] >= 2 and g["kpis"]["shipped"] >= 1
    # 반환 asof 는 있다(수금 월 합을 보이므로) — 화면 글자 유무는 check_data 행에 적는다(DEF-QA2-005 경미 · 계약 밖)
    assert g["asof"] is not None


# ── RPT-080 경영 요약 ────────────────────────────────────────────────────────
@pytest.mark.fn("F-RPT-081")
def test_g15_rpt080_summary_sections_and_kpis(flow):
    """일일 = RPT-040 · 050 / 주간 · 월간 = + 010 · 020 · 060 (D-512) · 절 KPI = 개별 함수 = 독립 SQL = 화면 · 해설 문장 없음."""
    _all_pass(_rows(flow, "G-15", "RPT-080"))
    today = flow.today
    C1 = flow.customer_id
    daily = dashboard.summary((today, today), C1)
    monthly = dashboard.summary((today.replace(day=1), today), C1)
    assert daily["kind"] == "일일" and [s["screen_id"] for s in daily["tables"]["sections"]] == ["RPT-040", "RPT-050"]
    assert monthly["kind"] == "월간" and [s["screen_id"] for s in monthly["tables"]["sections"]] == ["RPT-040", "RPT-050", "RPT-010", "RPT-020", "RPT-060"]
    assert dashboard.summary((today - timedelta(days=6), today), C1)["kind"] == "주간"
    # 월간 수주 절의 의뢰 건수 = dashboard.orders 같은 기간 = 두 번째 SQL
    f = today.replace(day=1)
    sec = {s["screen_id"]: {k["key"]: k["value"] for k in s["kpis"]} for s in monthly["tables"]["sections"]}
    n = flow.q1("select count(*) as n from production_request where customer_id = %s and status <> '취소' and request_date between %s and %s", (C1, f, today))["n"]
    assert sec["RPT-010"]["requests"] == (n or None) == {k["key"]: k["value"] for k in dashboard.orders((f, today), C1)["kpis"]}["requests"]
    assert all(("해설" not in k["label"]) for k in monthly["kpis"])     # 해설 문장 없음(D-505) — KPI 만


# ── 미수집 · 미확정 글자 · 거래처 필터 · 캐시 없음 ─────────────────────────────
@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-021")
@pytest.mark.fn("F-RPT-031")
@pytest.mark.fn("F-RPT-071")
def test_g15_none_is_missing_and_undecided_text(flow):
    """0건 None → 「미수집」(KPI · 표 · SVG title · 0 으로 지어내지 않음) · 로스율 「미확정 (D-519)」 · 병목 「미확정 (D-520)」."""
    _all_pass(_rows(flow, "G-15", "미수집 · 미확정 글자"))
    f, t = _period(flow)
    d = dashboard.orders((f, t), flow.customer2_id)                # C2 = 의뢰 없음
    assert all(k["value"] is None for k in d["kpis"]) and all(p["value"] is None for p in d["series"]["requests"])
    assert dashboard.UNDECIDED_LOSS == "미확정 (D-519)" and dashboard.UNDECIDED_BOTTLENECK == "미확정 (D-520)"


@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-051")
@pytest.mark.fn("F-RPT-061")
@pytest.mark.fn("F-RPT-071")
@pytest.mark.fn("F-RPT-081")
def test_g15_customer_filter_only_on_010_050_060_070_080(flow):
    """거래처 필터는 010 · 050 · 060 · 070 · 080 에만(D-805) — 020 · 030 · 040 은 인자를 줘도 값이 같고 화면에 거래처 칸이 없다."""
    _all_pass(_rows(flow, "G-15", "거래처 필터"))
    f, t = _period(flow)
    C2 = flow.customer2_id
    assert {k["key"]: k["value"] for k in dashboard.production((f, t))["kpis"]} == {k["key"]: k["value"] for k in dashboard.production((f, t), C2)["kpis"]}
    c2 = {k["key"]: k["value"] for k in dashboard.collection((f, t), C2)["kpis"]}
    assert c2["collected"] == Decimal(200) and c2["sales"] == Decimal(500) and c2["shipped_qty"] is None     # ERP 만 있는 거래처


@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-021")
@pytest.mark.fn("F-RPT-031")
@pytest.mark.fn("F-RPT-041")
@pytest.mark.fn("F-RPT-051")
@pytest.mark.fn("F-RPT-061")
@pytest.mark.fn("F-RPT-071")
@pytest.mark.fn("F-RPT-081")
def test_g05_rpt_screens_write_nothing(flow):
    """G-05 — RPT 8 화면 GET 전후 업무 테이블 diff 0(캐시 없음 · D-512) · rpt.py · dashboard.py 직접 쓰기 0(정적)."""
    _all_pass(_rows(flow, "G-05", "RPT 대시보드 8 화면"))
    report = cd.Report()
    cd.static_scan(report)
    _all_pass([c for c in report.checks if c.item.startswith("RPT 라우터") or c.item.startswith("TRK · LOT · PRP")])


# ── 정리 확인 ────────────────────────────────────────────────────────────────
def test_zz_previous_runs_left_no_rows():
    """직전 실행들의 QA2 접두 행이 없음을 본다(이번 실행 분은 모듈 픽스처의 finally 가 지운다 — 1분 전보다 오래된 행만 센다)."""
    from lcomfine.db import conn

    left = conn.q1(
        """select (select count(*) from customer where customer_code like 'QA2-%%' and created_at < now() - interval '1 minute')
                + (select count(*) from erp_upload_batch where source_file like 'QA2-%%' and created_at < now() - interval '1 minute') as n""")["n"]
    assert left == 0, f"직전 실행의 QA2 행 {left}"
