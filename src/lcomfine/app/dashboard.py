"""대시보드 8 의 집계 SQL — RPT-010~080 (개발3 · W3 · `contracts/interfaces.md` §9 · 공표 `progress-dev3.md` §1.5 · 집계 정의 D-512 · 가설 D-805).

**읽기만 한다.** 어떤 테이블에도 쓰지 않고 결과를 캐시 테이블에 쌓지 않는다(G-05 · D-505). 화면을 열 때마다 원천에서 다시 센다.
수금 · 납기 준수율 · 설비 집계는 `stats` 의 함수를 다시 쓴다 — 같은 집계 SQL 이 두 곳에 있지 않게(`collection` → `stats.shipment_vs_collection` ·
`stats.aging` · `stats.erp_asof`, `shipment` → `stats.due_compliance`, `production` → `stats.machine_stats` · `stats._rate`).
지어내지 않는다: 0건이면 값은 None(화면 `미수집`) · 로스율은 `미확정 (D-519)` 글자 · 병목 기준일은 `미확정 (D-520)` 글자(단계 소요일만 낸다).

    orders(period, customer_id=None)      RPT-010 수주 — 의뢰 건수·수량 · 거래처 상위 · 납기 분포 · 미착수
    production(period, customer_id=None)  RPT-020 생산 — 지시 대비 실적 · 로스율(D-519) · 가동률(D-801) · 기계별
    quality(period, customer_id=None)     RPT-030 품질 — 검사 로스율(D-519) · 불합격 LOT · 재판정
    inventory(period, customer_id=None)   RPT-040 재고·창고 — 입고·불출 · 재고 변동 상위 · 장기 체류 LOT · 실사 차이
    shipment(period, customer_id=None)    RPT-050 출하 — 건수·수량 · 거래처별 · 납기 준수율(D-804 · 의뢰번호 있는 출하만)
    collection(period, customer_id=None)  RPT-060 수금 — 월별 수금 · 출하 대비 수금 · 미수 연령 · 90일 초과 · 최근 업로드 기준일
    order_flow(period, customer_id=None)  RPT-070 주문 흐름 — 의뢰별 단계 소요일 · 병목(D-520) · 거래처·월별 수금
    summary(period, customer_id=None)     RPT-080 경영 요약 — 일일(창고·출하) · 주간·월간(+ 수주·생산·수금) · 해설 없음(D-505)

반환 모양(8 함수 공통):
    {"kpis": [{"key", "label", "value": 수 | None, "digits": 소수 자리, "unit": str, "text": str | None, "note": str}],
     "series": {이름: [{"label": str, "value": 수 | None}]},     # value None = 그 구간 0건 = 미수집
     "tables": {이름: [dict, ...]},
     "asof": date | None,                                       # 수금 화면만 (ERP 업로드 기준일) · 그 밖 None
     "period": (시작일, 종료일), "bucket": "day" | "month", "customer_id": int | None, "notes": [str]}
`text` 가 있으면 화면은 수 대신 그 글자를 적는다(`미확정 (D-519)` 등). `period` 는 `"YYYY-MM"` 또는 `(시작일, 종료일)`(양끝 포함).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..db import conn
from . import stats

#: 산식이 정해지지 않은 것 (decisions.md)
LOSS_RATE_DECISION = stats.LOSS_RATE_DECISION          # D-519 — 생산 · 검사 로스율
BOTTLENECK_DECISION = "D-520"                          # 주문 흐름 병목 기준일
UNDECIDED_LOSS = f"미확정 ({LOSS_RATE_DECISION})"
UNDECIDED_BOTTLENECK = f"미확정 ({BOTTLENECK_DECISION})"
#: 상위 N (거래처 상위 · 재고 변동 상위 · 장기 체류) — 가설 D-805
TOP_N = 10
#: 기간이 31일 이하면 일 단위, 넘으면 월 단위 구간 (가설 D-805)
DAY_BUCKET_MAX_DAYS = 31
#: 주문 흐름의 단계 (앞 단계 → 뒤 단계) — 정본 RPT-070 「의뢰 → 지시 → 생산 완료 → 제품 입고 → 출하」
FLOW_STAGES: tuple[tuple[str, str, str], ...] = (
    ("의뢰 → 지시", "request_date", "ordered_on"),
    ("지시 → 생산 완료", "ordered_on", "produced_on"),
    ("생산 완료 → 제품 입고", "produced_on", "received_on"),
    ("제품 입고 → 출하", "received_on", "shipped_on"),
    ("의뢰 → 출하", "request_date", "shipped_on"),
)


# ── 공통 ────────────────────────────────────────────────────────────────────

def period_bounds(period) -> tuple[date, date]:
    """`"YYYY-MM"` 또는 `(시작일, 종료일)`(양끝 포함) → (시작일, 종료일). 그 밖 ValueError (`stats.period_bounds` 와 같다)."""
    return stats.period_bounds(period)


def _bucket(f: date, t: date) -> tuple[str, str]:
    """(구간 종류, to_char 형식). 31일 이하 = 일 · 그 밖 = 월 (D-805)."""
    return ("day", "YYYY-MM-DD") if (t - f).days < DAY_BUCKET_MAX_DAYS else ("month", "YYYY-MM")


def _labels(f: date, t: date, bucket: str) -> list[str]:
    out: list[str] = []
    if bucket == "day":
        d = f
        while d <= t:
            out.append(d.isoformat())
            d += timedelta(days=1)
        return out
    y, m = f.year, f.month
    while date(y, m, 1) <= t:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _series(labels: list[str], rows: list[dict], key: str, value: str) -> list[dict]:
    """구간 라벨 전부에 값을 붙인다 — 행이 없는 구간은 None(미수집 · 0 으로 지어내지 않는다)."""
    got = {r[key]: r[value] for r in rows}
    return [{"label": lb, "value": got.get(lb)} for lb in labels]


def _kpi(key: str, label: str, value, *, digits: int = 0, unit: str = "", text: str | None = None, note: str = "") -> dict:
    return {"key": key, "label": label, "value": value, "digits": digits, "unit": unit, "text": text, "note": note}


def _n(v):
    """0 · None → None(미수집). 그 밖 그대로."""
    return None if v is None or v == 0 else v


def _avg_days(vals: list[int]) -> Decimal | None:
    if not vals:
        return None
    return (Decimal(sum(vals)) / Decimal(len(vals))).quantize(Decimal("0.1"))


def _base(f: date, t: date, bucket: str, customer_id: int | None) -> dict:
    return {"kpis": [], "series": {}, "tables": {}, "asof": None, "period": (f, t), "bucket": bucket,
            "customer_id": customer_id, "notes": []}


def _customer_code(customer_id: int | None) -> str | None:
    if customer_id is None:
        return None
    row = conn.q1("select customer_code from customer where id = %s", (customer_id,))
    return row["customer_code"] if row else None


# ── RPT-010 수주 ──────────────────────────────────────────────────────────────

def orders(period, customer_id: int | None = None) -> dict:
    """RPT-010 — 모집단 = 의뢰일(`request_date`)이 기간 안인 취소 아닌 생산의뢰(거래처 필터 적용).

    kpis: requests(건수) · qty(수량) · customers(거래처 수) · not_started(미착수 = 취소 아닌 지시가 하나도 없는 의뢰)
    series: requests(구간별 건수) · qty(구간별 수량) · due(납기 월별 건수 — 납기 분포)
    tables: top_customers(건수·수량 상위 TOP_N) · not_started(미착수 의뢰) · due_distribution(납기 월 · 건수 · 수량)
    """
    f, t = period_bounds(period)
    bucket, fmt = _bucket(f, t)
    out = _base(f, t, bucket, customer_id)
    params = {"f": f, "t": t, "c": customer_id, "fmt": fmt}
    where = """r.request_date between %(f)s and %(t)s and r.status <> '취소'
               and (%(c)s::bigint is null or r.customer_id = %(c)s::bigint)"""
    rows = conn.q(
        f"""select r.id, r.request_no, r.request_date, r.qty, r.due_date, r.status, to_char(r.request_date, %(fmt)s) as bucket,
                   to_char(r.due_date, 'YYYY-MM') as due_month, c.id as customer_id, c.customer_code, c.customer_name,
                   i.item_code, i.item_name,
                   exists (select 1 from work_order w where w.request_id = r.id and w.status <> '취소') as has_order
              from production_request r
              join customer c on c.id = r.customer_id
              join item i on i.id = r.item_id
             where {where}
             order by r.request_date, r.id""", params)
    labels = _labels(f, t, bucket)
    by_bucket: dict[str, dict] = {}
    by_customer: dict[int, dict] = {}
    by_due: dict[str, dict] = {}
    for r in rows:
        b = by_bucket.setdefault(r["bucket"], {"bucket": r["bucket"], "requests": 0, "qty": Decimal(0)})
        b["requests"] += 1
        b["qty"] += r["qty"]
        c = by_customer.setdefault(r["customer_id"], {"customer_id": r["customer_id"], "customer_code": r["customer_code"],
                                                       "customer_name": r["customer_name"], "requests": 0, "qty": Decimal(0)})
        c["requests"] += 1
        c["qty"] += r["qty"]
        d = by_due.setdefault(r["due_month"], {"due_month": r["due_month"], "requests": 0, "qty": Decimal(0)})
        d["requests"] += 1
        d["qty"] += r["qty"]
    not_started = [r for r in rows if not r["has_order"]]
    top = sorted(by_customer.values(), key=lambda c: (-c["requests"], -c["qty"], c["customer_code"]))[:TOP_N]
    due_rows = sorted(by_due.values(), key=lambda d: d["due_month"])
    out["kpis"] = [
        _kpi("requests", "의뢰 건수", _n(len(rows)), unit="건"),
        _kpi("qty", "의뢰 수량", _n(sum((r["qty"] for r in rows), Decimal(0))) if rows else None, digits=3),
        _kpi("customers", "거래처 수", _n(len(by_customer)), unit="곳"),
        _kpi("not_started", "미착수 의뢰", _n(len(not_started)), unit="건", note="생산지시가 아직 없는 의뢰"),
    ]
    out["series"] = {"requests": _series(labels, list(by_bucket.values()), "bucket", "requests"),
                     "qty": _series(labels, list(by_bucket.values()), "bucket", "qty"),
                     "due": [{"label": d["due_month"], "value": d["requests"]} for d in due_rows]}
    out["tables"] = {"top_customers": top, "not_started": not_started, "due_distribution": due_rows}
    return out


# ── RPT-020 생산 ──────────────────────────────────────────────────────────────

def production(period, customer_id: int | None = None) -> dict:
    """RPT-020 — 모집단 = 일자(`work_date`)가 기간 안인 생산일보. 거래처 필터는 적용하지 않는다(정본 필터 = 기간).

    kpis: work_orders(일보가 있는 지시 수) · order_qty(그 지시들의 지시 수량 합) · produced_qty · good_qty · loss_qty ·
          loss_rate(text `미확정 (D-519)`) · utilization(가동률 % — D-801 · 가동·정지가 없으면 None)
    series: good_qty(구간별 양품) · produced_qty(구간별 생산) · by_equipment(설비별 양품 — `stats.machine_stats`)
    tables: by_work_order(지시 대비 실적) · by_equipment(`stats.machine_stats` 행 그대로)
    """
    f, t = period_bounds(period)
    bucket, fmt = _bucket(f, t)
    out = _base(f, t, bucket, customer_id)
    params = {"f": f, "t": t, "fmt": fmt}
    by_wo = conn.q(
        """select w.id as work_order_id, w.work_order_no, w.qty as order_qty, w.status, w.equipment_code, i.item_code, i.item_name,
                  count(*) as entries, sum(d.produced_qty) as produced_qty, sum(d.good_qty) as good_qty, sum(d.loss_qty) as loss_qty,
                  sum(d.run_minutes) as run_minutes, sum(d.stop_minutes) as stop_minutes
             from production_daily d
             join work_order w on w.id = d.work_order_id
             join item i on i.id = w.item_id
            where d.work_date between %(f)s and %(t)s
            group by w.id, w.work_order_no, w.qty, w.status, w.equipment_code, i.item_code, i.item_name
            order by w.work_order_no""", params)
    by_bucket = conn.q(
        """select to_char(d.work_date, %(fmt)s) as bucket, sum(d.produced_qty) as produced_qty, sum(d.good_qty) as good_qty
             from production_daily d where d.work_date between %(f)s and %(t)s group by 1 order by 1""", params)
    machines = stats.machine_stats(f, t)
    labels = _labels(f, t, bucket)
    runs = [r["run_minutes"] for r in by_wo if r["run_minutes"] is not None]
    stops = [r["stop_minutes"] for r in by_wo if r["stop_minutes"] is not None]
    rate = stats._rate(sum(runs) if runs else None, sum(stops) if stops else None)
    out["kpis"] = [
        _kpi("work_orders", "일보가 있는 지시", _n(len(by_wo)), unit="건"),
        _kpi("order_qty", "지시 수량", _n(sum((r["order_qty"] for r in by_wo), Decimal(0))) if by_wo else None, digits=3),
        _kpi("produced_qty", "생산 수량", _n(sum((r["produced_qty"] for r in by_wo), Decimal(0))) if by_wo else None, digits=3),
        _kpi("good_qty", "양품 수량", _n(sum((r["good_qty"] for r in by_wo), Decimal(0))) if by_wo else None, digits=3),
        _kpi("loss_qty", "로스 수량", sum((r["loss_qty"] for r in by_wo), Decimal(0)) if by_wo else None, digits=3),
        _kpi("loss_rate", "생산 로스율", None, text=UNDECIDED_LOSS, note="산식 확정 전 — 수량으로 판단"),
        _kpi("utilization", "가동률(%)", rate, digits=1, unit="%", note="가동 ÷ (가동 + 정지) · 임시 산식"),
    ]
    out["series"] = {"good_qty": _series(labels, by_bucket, "bucket", "good_qty"),
                     "produced_qty": _series(labels, by_bucket, "bucket", "produced_qty"),
                     "by_equipment": [{"label": m["equipment_name"] or m["equipment_code"], "value": m["good_qty"]} for m in machines]}
    out["tables"] = {"by_work_order": by_wo, "by_equipment": machines}
    out["notes"] = [stats.UTILIZATION_FORMULA, f"로스율 산식은 {UNDECIDED_LOSS}"]
    return out


# ── RPT-030 품질 ──────────────────────────────────────────────────────────────

def quality(period, customer_id: int | None = None) -> dict:
    """RPT-030 — 검사일보(`work_date` 기간 안) + 입고검사·제품검사 판정(`inspected_at` 기간 안). 거래처 필터 없음.

    kpis: inspected_qty · defect_qty · loss_rate(text `미확정 (D-519)`) · judgements(판정 행) · rejected_lots(불합격 LOT 수 — 그 기간 불합격 판정이
          있는 LOT · 종류 구분) · rejudged(재판정 행 = seq > 1)
    series: defect_qty(구간별 불량) · inspected_qty(구간별 검사) · defects(불량유형별 합)
    tables: rejected(불합격 판정 행) · rejudged(재판정 행 · 이전 판정 함께) · defects_by_type(불량유형 · 수량) · daily_by_work_order
    """
    f, t = period_bounds(period)
    bucket, fmt = _bucket(f, t)
    out = _base(f, t, bucket, customer_id)
    params = {"f": f, "t": t, "t1": t + timedelta(days=1), "fmt": fmt}
    daily = conn.q(
        """select w.work_order_no, i.item_code, i.item_name, count(*) as entries,
                  sum(d.inspected_qty) as inspected_qty, sum(d.defect_qty) as defect_qty
             from inspection_daily d join work_order w on w.id = d.work_order_id join item i on i.id = w.item_id
            where d.work_date between %(f)s and %(t)s
            group by w.work_order_no, i.item_code, i.item_name order by w.work_order_no""", params)
    by_bucket = conn.q(
        """select to_char(d.work_date, %(fmt)s) as bucket, sum(d.inspected_qty) as inspected_qty, sum(d.defect_qty) as defect_qty
             from inspection_daily d where d.work_date between %(f)s and %(t)s group by 1 order by 1""", params)
    defects = conn.q(
        """select e.key as defect_code, coalesce(c.code_name, e.key) as defect_name, sum(nullif(e.value, '')::numeric) as qty
             from inspection_daily d, jsonb_each_text(d.defects) e
             left join sys_common_code c on c.group_code = '불량유형' and c.code = e.key
            where d.work_date between %(f)s and %(t)s
            group by e.key, c.code_name order by 3 desc nulls last, 1""", params)
    judgements = conn.q(
        """select * from (
               select '입고검사' as inspection_kind, m.lot_no, i.item_code, i.item_name, q.seq, q.result, q.inspected_at, q.inspector,
                      lag(q.result) over (partition by q.material_lot_id order by q.seq) as previous_result
                 from incoming_inspection q join material_lot m on m.id = q.material_lot_id join item i on i.id = m.item_id
               union all
               select '제품검사', p.lot_no, i.item_code, i.item_name, q.seq, q.result, q.inspected_at, q.inspector,
                      lag(q.result) over (partition by q.product_lot_id order by q.seq)
                 from product_inspection q join product_lot p on p.id = q.product_lot_id join item i on i.id = p.item_id
           ) j
            where j.inspected_at >= %(f)s and j.inspected_at < %(t1)s
            order by j.inspected_at desc, j.lot_no, j.seq""", params)
    rejected = [j for j in judgements if j["result"] == "불합격"]
    rejudged = [j for j in judgements if j["seq"] > 1]
    labels = _labels(f, t, bucket)
    out["kpis"] = [
        _kpi("inspected_qty", "검사 수량", _n(sum((d["inspected_qty"] for d in daily), Decimal(0))) if daily else None, digits=3),
        _kpi("defect_qty", "불량 수량", sum((d["defect_qty"] for d in daily), Decimal(0)) if daily else None, digits=3),
        _kpi("loss_rate", "검사 로스율", None, text=UNDECIDED_LOSS, note="산식 확정 전 — 수량으로 판단"),
        _kpi("judgements", "판정 건수", _n(len(judgements)), unit="건", note="입고검사 + 제품검사"),
        _kpi("rejected_lots", "불합격 LOT", _n(len({(j["inspection_kind"], j["lot_no"]) for j in rejected})), unit="LOT"),
        _kpi("rejudged", "재판정", _n(len(rejudged)), unit="건", note="차수 2 이상"),
    ]
    out["series"] = {"defect_qty": _series(labels, by_bucket, "bucket", "defect_qty"),
                     "inspected_qty": _series(labels, by_bucket, "bucket", "inspected_qty"),
                     "defects": [{"label": d["defect_name"], "value": d["qty"]} for d in defects]}
    out["tables"] = {"rejected": rejected, "rejudged": rejudged, "defects_by_type": defects, "daily_by_work_order": daily}
    out["notes"] = [f"로스율 산식은 {UNDECIDED_LOSS}"]
    return out


# ── RPT-040 재고·창고 ──────────────────────────────────────────────────────────

def inventory(period, customer_id: int | None = None) -> dict:
    """RPT-040 — 입고(원자재 `material_receipt`·제품 `product_receipt` · 취소 제외 · 입고일 기간 안) · 불출(`material_issue` 취소 제외 · 불출일) ·
    재고 변동 상위(`stock_move` 이동 일시 기간 안 · LOT 별 수량 합 TOP_N) · 장기 체류 LOT(현재고 > 0 인 LOT 의 체류일 = 오늘 − LOT 생성일 · 내림차순 TOP_N ·
    기준일 수 없음 — D-805) · 실사 차이(`stock_adjust` 조정 일시 기간 안). 거래처 필터 없음.

    kpis: material_receipts(건) · material_receipt_qty · issues(건) · issue_qty · product_receipts(건) · product_receipt_qty · adjusts(건) · adjust_diff(차이 합)
    series: receipt_qty(구간별 원자재 입고 수량) · issue_qty(구간별 불출 수량)
    tables: top_moves · long_stay · adjusts · receipts_by_item
    """
    f, t = period_bounds(period)
    bucket, fmt = _bucket(f, t)
    out = _base(f, t, bucket, customer_id)
    params = {"f": f, "t": t, "t1": t + timedelta(days=1), "fmt": fmt, "n": TOP_N}
    rec = conn.q1(
        """select count(distinct r.id) as receipts, sum(l.qty) as qty
             from material_receipt r join material_lot l on l.receipt_id = r.id and l.canceled_at is null and l.parent_lot_id is null
            where r.canceled_at is null and r.received_on between %(f)s and %(t)s""", params)
    rec_series = conn.q(
        """select to_char(r.received_on, %(fmt)s) as bucket, sum(l.qty) as qty
             from material_receipt r join material_lot l on l.receipt_id = r.id and l.canceled_at is null and l.parent_lot_id is null
            where r.canceled_at is null and r.received_on between %(f)s and %(t)s group by 1 order by 1""", params)
    rec_items = conn.q(
        """select i.item_code, i.item_name, count(distinct r.id) as receipts, count(*) as lots, sum(l.qty) as qty
             from material_receipt r join material_lot l on l.receipt_id = r.id and l.canceled_at is null and l.parent_lot_id is null
             join item i on i.id = l.item_id
            where r.canceled_at is null and r.received_on between %(f)s and %(t)s
            group by i.item_code, i.item_name order by 5 desc, 1""", params)
    iss = conn.q1(
        """select count(distinct m.id) as issues, sum(l.qty) as qty
             from material_issue m join material_issue_line l on l.issue_id = m.id
            where m.canceled_at is null and m.issued_on between %(f)s and %(t)s""", params)
    iss_series = conn.q(
        """select to_char(m.issued_on, %(fmt)s) as bucket, sum(l.qty) as qty
             from material_issue m join material_issue_line l on l.issue_id = m.id
            where m.canceled_at is null and m.issued_on between %(f)s and %(t)s group by 1 order by 1""", params)
    prod = conn.q1(
        """select count(*) as receipts, sum(qty) as qty from product_receipt
            where canceled_at is null and received_on between %(f)s and %(t)s""", params)
    top_moves = conn.q(
        """select s.lot_kind, s.lot_id, coalesce(m.lot_no, p.lot_no) as lot_no, i.item_code, i.item_name,
                  count(*) as moves, sum(s.qty) as qty,
                  string_agg(distinct s.move_kind, ' · ' order by s.move_kind) as kinds
             from stock_move s
             left join material_lot m on s.lot_kind = '원자재' and m.id = s.lot_id
             left join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
             left join item i on i.id = coalesce(m.item_id, p.item_id)
            where s.moved_at >= %(f)s and s.moved_at < %(t1)s
            group by s.lot_kind, s.lot_id, coalesce(m.lot_no, p.lot_no), i.item_code, i.item_name
            order by 7 desc, 3 limit %(n)s""", params)
    long_stay = conn.q(
        """select s.lot_kind, coalesce(m.lot_no, p.lot_no) as lot_no, i.item_code, i.item_name, wh.warehouse_code, l.location_code,
                  s.qty, s.allocated_qty, s.status, coalesce(m.created_at, p.created_at)::date as since,
                  current_date - coalesce(m.created_at, p.created_at)::date as days
             from lot_stock s
             left join material_lot m on s.lot_kind = '원자재' and m.id = s.lot_id
             left join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
             left join item i on i.id = coalesce(m.item_id, p.item_id)
             join location l on l.id = s.location_id join warehouse wh on wh.id = l.warehouse_id
            where s.qty > 0
            order by 11 desc, 2 limit %(n)s""", params)
    adjusts = conn.q(
        """select a.lot_kind, coalesce(m.lot_no, p.lot_no) as lot_no, i.item_code, i.item_name, a.book_qty, a.actual_qty, a.diff_qty,
                  a.reason, a.adjusted_at, a.created_by
             from stock_adjust a
             left join material_lot m on a.lot_kind = '원자재' and m.id = a.lot_id
             left join product_lot p on a.lot_kind = '제품' and p.id = a.lot_id
             left join item i on i.id = coalesce(m.item_id, p.item_id)
            where a.adjusted_at >= %(f)s and a.adjusted_at < %(t1)s
            order by abs(a.diff_qty) desc, a.adjusted_at desc""", params)
    labels = _labels(f, t, bucket)
    out["kpis"] = [
        _kpi("material_receipts", "원자재 입고", _n(rec["receipts"]), unit="건"),
        _kpi("material_receipt_qty", "원자재 입고 수량", _n(rec["qty"]), digits=3),
        _kpi("issues", "불출", _n(iss["issues"]), unit="건"),
        _kpi("issue_qty", "불출 수량", _n(iss["qty"]), digits=3),
        _kpi("product_receipts", "제품 입고", _n(prod["receipts"]), unit="건"),
        _kpi("product_receipt_qty", "제품 입고 수량", _n(prod["qty"]), digits=3),
        _kpi("adjusts", "실사 조정", _n(len(adjusts)), unit="건"),
        _kpi("adjust_diff", "실사 차이 합", sum((a["diff_qty"] for a in adjusts), Decimal(0)) if adjusts else None, digits=3,
             note="실사 − 장부"),
    ]
    out["series"] = {"receipt_qty": _series(labels, rec_series, "bucket", "qty"),
                     "issue_qty": _series(labels, iss_series, "bucket", "qty")}
    out["tables"] = {"top_moves": top_moves, "long_stay": long_stay, "adjusts": adjusts, "receipts_by_item": rec_items}
    out["notes"] = [f"장기 체류 = 현재고가 남은 LOT 의 체류일(오늘 − LOT 생성일) 상위 {TOP_N} — 기준일 수는 없다(D-805)"]
    return out


# ── RPT-050 출하 ──────────────────────────────────────────────────────────────

def shipment(period, customer_id: int | None = None) -> dict:
    """RPT-050 — 모집단 = 확정 출하(`status='확정'` · 확정일 `confirmed_at` 이 기간 안 · 거래처 필터). 수량 = 출하 행 합(반품·정정은 빼지 않는다 D-515).
    납기 준수율 = `stats.due_compliance((f, t))`(D-804 · 납기가 기간 안인 의뢰 · 출하 지시에 의뢰번호가 있을 때만 출하로 센다) — 거래처 필터는 행을 거른 뒤 다시 센다.

    kpis: shipments(건) · qty · customers(곳) · due_rate(납기 준수율 % · None = 미수집) · on_time · late_done · late_open
    series: qty(구간별 출하 수량) · shipments(구간별 건수) · by_customer(거래처별 수량)
    tables: by_customer · by_item · recent(확정 출하 목록) · due_rows(준수율 모집단)
    """
    f, t = period_bounds(period)
    bucket, fmt = _bucket(f, t)
    out = _base(f, t, bucket, customer_id)
    params = {"f": f, "t": t, "t1": t + timedelta(days=1), "fmt": fmt, "c": customer_id}
    where = """o.status = '확정' and o.confirmed_at >= %(f)s and o.confirmed_at < %(t1)s
               and (%(c)s::bigint is null or o.customer_id = %(c)s::bigint)"""
    recent = conn.q(
        f"""select o.id, o.shipment_no, o.confirmed_at, o.due_date, o.customer_id, c.customer_code, c.customer_name,
                   r.request_no, to_char(o.confirmed_at, %(fmt)s) as bucket, sum(l.qty) as qty, count(*) as lines
              from shipment_order o join customer c on c.id = o.customer_id
              left join production_request r on r.id = o.request_id
              join shipment_line l on l.shipment_order_id = o.id
             where {where}
             group by o.id, o.shipment_no, o.confirmed_at, o.due_date, o.customer_id, c.customer_code, c.customer_name, r.request_no
             order by o.confirmed_at desc, o.id desc""", params)
    by_item = conn.q(
        f"""select i.item_code, i.item_name, count(distinct o.id) as shipments, sum(l.qty) as qty
              from shipment_order o join shipment_line l on l.shipment_order_id = o.id
              join product_lot p on p.id = l.product_lot_id join item i on i.id = p.item_id
             where {where}
             group by i.item_code, i.item_name order by 4 desc, 1""", params)
    by_bucket: dict[str, dict] = {}
    by_customer: dict[int, dict] = {}
    for r in recent:
        b = by_bucket.setdefault(r["bucket"], {"bucket": r["bucket"], "shipments": 0, "qty": Decimal(0)})
        b["shipments"] += 1
        b["qty"] += r["qty"]
        c = by_customer.setdefault(r["customer_id"], {"customer_id": r["customer_id"], "customer_code": r["customer_code"],
                                                       "customer_name": r["customer_name"], "shipments": 0, "qty": Decimal(0)})
        c["shipments"] += 1
        c["qty"] += r["qty"]
    cust_rows = sorted(by_customer.values(), key=lambda c: (-c["qty"], c["customer_code"]))
    due = stats.due_compliance((f, t))
    due_rows = due["rows"]
    code = _customer_code(customer_id)
    if customer_id is not None:
        due_rows = [r for r in due_rows if r["customer_code"] == code]
    counts = {"on_time": 0, "late_done": 0, "late_open": 0, "in_progress": 0}
    for r in due_rows:
        counts[{"납기 안 완료": "on_time", "지연 완료": "late_done", "지연": "late_open", "진행": "in_progress"}[r["bucket"]]] += 1
    denom = counts["on_time"] + counts["late_done"] + counts["late_open"]
    rate = (Decimal(counts["on_time"]) * 100 / Decimal(denom)).quantize(Decimal("0.1")) if denom else None
    labels = _labels(f, t, bucket)
    out["kpis"] = [
        _kpi("shipments", "출하 건수", _n(len(recent)), unit="건"),
        _kpi("qty", "출하 수량", _n(sum((r["qty"] for r in recent), Decimal(0))) if recent else None, digits=3),
        _kpi("customers", "거래처 수", _n(len(by_customer)), unit="곳"),
        _kpi("due_rate", "납기 준수율(%)", rate, digits=1, unit="%", note="의뢰번호가 있는 출하만 셈"),
        _kpi("on_time", "납기 안 완료", _n(counts["on_time"]), unit="건"),
        _kpi("late_done", "지연 완료", _n(counts["late_done"]), unit="건"),
        _kpi("late_open", "지연", _n(counts["late_open"]), unit="건"),
    ]
    out["series"] = {"qty": _series(labels, list(by_bucket.values()), "bucket", "qty"),
                     "shipments": _series(labels, list(by_bucket.values()), "bucket", "shipments"),
                     "by_customer": [{"label": c["customer_code"], "value": c["qty"]} for c in cust_rows[:TOP_N]]}
    out["tables"] = {"by_customer": cust_rows, "by_item": by_item, "recent": recent, "due_rows": due_rows}
    out["notes"] = [due["formula"]]
    return out


# ── RPT-060 수금 ──────────────────────────────────────────────────────────────

def collection(period, customer_id: int | None = None) -> dict:
    """RPT-060 — 원천 = ERP 수금현황 반영 회차(`stats` 재사용 · 집계 SQL 은 `stats` 에만). **asof = `stats.erp_asof()`**(가장 최근 업로드 기준일 · 없으면 None = 미수집).
    월별 수금 · 출하 대비 수금 = `stats.shipment_vs_collection(기간의 첫 달, 끝 달, 거래처)` · 미수 연령 · 90일 초과 = `stats.aging(asof)`(거래처 필터는 행을 거른다).

    kpis: collected(기간 수금액) · sales(기간 매출액 · 매출 열 미매핑이면 text `미확정 (D-516)`) · shipped_qty(기간 확정 출하 수량) · over90(90일 초과 거래처 수)
    series: collected(월별 수금액) · shipped_qty(월별 출하 수량) · aging(구간별 순액)
    tables: monthly(월 · 출하 · 매출 · 수금) · by_customer(월 · 거래처) · over90(거래처 · 90일 초과 순액) · aging(거래처 × 구간)
    """
    f, t = period_bounds(period)
    bucket, fmt = _bucket(f, t)
    out = _base(f, t, "month", customer_id)
    asof = stats.erp_asof()
    out["asof"] = asof
    svc = stats.shipment_vs_collection(f"{f.year:04d}-{f.month:02d}", f"{t.year:04d}-{t.month:02d}", customer_id)
    fields = svc["fields"]
    monthly = svc["monthly"]
    collected = stats._sum_or_none(monthly, "collected_amount")
    sales = stats._sum_or_none(monthly, "sales_amount") if fields.get("sales_amount") else None
    sales_text = None if fields.get("sales_amount") else f"미확정 ({stats.ERP_DECISION})"
    aging_rows: list[dict] = []
    over90: list[dict] = []
    aging_series: list[dict] = []
    aging_data = None
    if asof is not None:
        aging_data = stats.aging(asof)
        aging_rows = aging_data["rows"]
        over90 = aging_data["over90"]
        if customer_id is not None:
            aging_rows = [r for r in aging_rows if r["customer_id"] == customer_id]
            over90 = [r for r in over90 if r["customer_id"] == customer_id]
        if aging_data["undecided"]:
            aging_series = [{"label": b, "value": None} for b in aging_data["buckets"]]
        else:
            aging_series = [{"label": b, "value": sum((r["cells"][b]["net"] for r in aging_rows), Decimal(0)) if aging_rows else None}
                            for b in aging_data["buckets"]]
    over90_text = None
    if asof is None:
        over90_text = "미수집"
    elif aging_data and aging_data["undecided"]:
        over90_text = f"미확정 ({aging_data['undecided']})"
    out["kpis"] = [
        _kpi("asof", "ERP 업로드 기준일", None, text=asof.isoformat() if asof else "미수집", note="반영 회차의 마지막 기준 기간 끝"),
        _kpi("collected", "기간 수금액", collected, digits=0, unit="원"),
        _kpi("sales", "기간 매출액", sales, digits=0, unit="원", text=sales_text),
        _kpi("shipped_qty", "기간 확정 출하 수량", stats._sum_or_none(monthly, "shipped_qty"), digits=3),
        _kpi("over90", "90일 초과 거래처", _n(len(over90)) if over90_text is None else None, unit="곳", text=over90_text,
             note="기준일에 90일 넘은 미수"),
    ]
    out["series"] = {"collected": [{"label": m["ym"], "value": m["collected_amount"]} for m in monthly],
                     "shipped_qty": [{"label": m["ym"], "value": m["shipped_qty"]} for m in monthly],
                     "aging": aging_series}
    out["tables"] = {"monthly": monthly, "by_customer": svc["rows"], "over90": over90, "aging": aging_rows,
                     "aging_buckets": list(aging_data["buckets"]) if aging_data else list(b[0] for b in stats.AGING_BUCKETS)}
    out["notes"] = ["월 · 거래처 단위로 붙인다(건 단위로 짝짓지 않음)", "구간 금액 = 그 구간 매출일 행의 Σ매출 − Σ수금 — 가설 (D-803)"]
    if aging_data and aging_data["undecided"]:
        out["notes"].append(f"매출액 열이 매핑되지 않아 미수 연령을 낼 수 없다 — 미확정 ({aging_data['undecided']})")
    return out


# ── RPT-070 주문 흐름 ───────────────────────────────────────────────────────────

def order_flow(period, customer_id: int | None = None) -> dict:
    """RPT-070 — 모집단 = 의뢰일이 기간 안인 취소 아닌 생산의뢰(거래처 필터). 의뢰번호를 키로 단계 날짜를 잇는다(D-805):
    지시일 = 취소 아닌 지시의 첫 `created_at` · 생산 완료일 = 그 지시들의 마지막 일보 `work_date` · 제품 입고일 = 취소 아닌 제품 입고의 마지막 `received_on` ·
    출하일 = 확정 출하의 마지막 `confirmed_at`. 단계 소요일 = 뒤 날짜 − 앞 날짜(둘 중 하나가 없으면 None). 병목 기준일은 `미확정 (D-520)` — 소요일만 보인다.
    수금은 거래처 · 월 단위(`stats.shipment_vs_collection`) — 건 단위로 짝짓지 않는다.

    kpis: requests(건) · shipped(출하까지 간 의뢰) · 단계마다 avg_<n>(평균 소요일 · None = 미수집) · bottleneck(text `미확정 (D-520)`)
    series: avg_days(단계별 평균 소요일) · collected(월별 수금)
    tables: rows(의뢰별 단계 날짜 · 소요일 days[단계 이름]) · stages(단계 · 건수 · 평균 · 최대) · collection_monthly
    """
    f, t = period_bounds(period)
    out = _base(f, t, "month", customer_id)
    rows = conn.q(
        """select r.id, r.request_no, r.request_date, r.qty, r.due_date, r.status, c.customer_code, c.customer_name, i.item_code, i.item_name,
                  (select min(w.created_at)::date from work_order w where w.request_id = r.id and w.status <> '취소') as ordered_on,
                  (select max(d.work_date) from production_daily d join work_order w on w.id = d.work_order_id
                    where w.request_id = r.id and w.status <> '취소') as produced_on,
                  (select max(p.received_on) from product_receipt p join work_order w on w.id = p.work_order_id
                    where w.request_id = r.id and p.canceled_at is null) as received_on,
                  (select max(o.confirmed_at)::date from shipment_order o where o.request_id = r.id and o.status = '확정') as shipped_on
             from production_request r join customer c on c.id = r.customer_id join item i on i.id = r.item_id
            where r.request_date between %(f)s and %(t)s and r.status <> '취소'
              and (%(c)s::bigint is null or r.customer_id = %(c)s::bigint)
            order by r.request_date, r.id""", {"f": f, "t": t, "c": customer_id})
    stage_vals: dict[str, list[int]] = {name: [] for name, _, _ in FLOW_STAGES}
    for r in rows:
        r["days"] = {}
        for name, a, b in FLOW_STAGES:
            if r[a] is not None and r[b] is not None:
                d = (r[b] - r[a]).days
                r["days"][name] = d
                stage_vals[name].append(d)
            else:
                r["days"][name] = None
        r["bottleneck"] = UNDECIDED_BOTTLENECK
    stages = [{"stage": name, "count": len(v), "avg_days": _avg_days(v), "max_days": max(v) if v else None}
              for name, v in stage_vals.items()]
    svc = stats.shipment_vs_collection(f"{f.year:04d}-{f.month:02d}", f"{t.year:04d}-{t.month:02d}", customer_id)
    out["kpis"] = [_kpi("requests", "의뢰 건수", _n(len(rows)), unit="건"),
                   _kpi("shipped", "출하까지 간 의뢰", _n(sum(1 for r in rows if r["shipped_on"] is not None)), unit="건")]
    for n, s in enumerate(stages, start=1):
        out["kpis"].append(_kpi(f"avg_{n}", f"평균 {s['stage']}", s["avg_days"], digits=1, unit="일"))
    out["kpis"].append(_kpi("bottleneck", "병목 단계", None, text=UNDECIDED_BOTTLENECK, note="기준 일수 확정 전 — 단계 소요일로 판단"))
    out["series"] = {"avg_days": [{"label": s["stage"], "value": s["avg_days"]} for s in stages],
                     "collected": [{"label": m["ym"], "value": m["collected_amount"]} for m in svc["monthly"]]}
    out["tables"] = {"rows": rows, "stages": stages, "collection_monthly": svc["monthly"], "collection_by_customer": svc["rows"]}
    out["asof"] = svc["asof"]
    out["notes"] = [f"병목 기준일은 {UNDECIDED_BOTTLENECK}", "수금은 거래처 · 월 단위로 붙인다(건 단위로 짝짓지 않음)"]
    return out


# ── RPT-080 경영 요약 ───────────────────────────────────────────────────────────

def summary_kind(f: date, t: date) -> str:
    """기간 길이 → 일일(1일) · 주간(7일 이하) · 월간(그 밖)."""
    span = (t - f).days + 1
    return "일일" if span <= 1 else ("주간" if span <= 7 else "월간")


def summary(period, customer_id: int | None = None) -> dict:
    """RPT-080 — 위 대시보드의 핵심 수치만(해설 문장 없음 · D-505). 일일 = 창고(재고·창고) · 출하, 주간 · 월간 = + 수주 · 생산 · 수금.
    kpis 의 `group` 이 어느 리포트에서 왔는지 적는다. tables["sections"] = [{"title", "screen_id", "kpis"}].
    """
    f, t = period_bounds(period)
    kind = summary_kind(f, t)
    out = _base(f, t, _bucket(f, t)[0], customer_id)
    parts: list[tuple[str, str, dict, tuple[str, ...]]] = [
        ("재고·창고", "RPT-040", inventory((f, t)), ("material_receipts", "material_receipt_qty", "issues", "issue_qty", "product_receipts",
                                                   "product_receipt_qty", "adjusts")),
        ("출하", "RPT-050", shipment((f, t), customer_id), ("shipments", "qty", "customers", "due_rate", "late_open")),
    ]
    if kind != "일일":
        parts += [
            ("수주", "RPT-010", orders((f, t), customer_id), ("requests", "qty", "not_started")),
            ("생산", "RPT-020", production((f, t)), ("work_orders", "good_qty", "loss_qty", "loss_rate", "utilization")),
            ("수금", "RPT-060", collection((f, t), customer_id), ("asof", "collected", "sales", "over90")),
        ]
    sections = []
    for title, screen_id, data, keys in parts:
        picked = [dict(k, group=title) for k in data["kpis"] if k["key"] in keys]
        sections.append({"title": title, "screen_id": screen_id, "kpis": picked})
        out["kpis"].extend(picked)
        if screen_id == "RPT-060":
            out["asof"] = data["asof"]
    ship = parts[1][2]
    out["series"] = {"shipment_qty": ship["series"]["qty"], "issue_qty": parts[0][2]["series"]["issue_qty"]}
    out["tables"] = {"sections": sections}
    out["kind"] = kind
    out["notes"] = [f"{kind} 요약 — 해설 문장은 없다(D-505)"]
    return out
