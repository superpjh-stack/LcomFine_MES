"""집계 SQL — PRP 생산 보고서 · 납기 보조 (개발3 · `contracts/interfaces.md` §9 · 공표 `progress-dev3.md` §1).

**읽기만 한다.** 어떤 테이블에도 쓰지 않고, 집계 결과를 캐시 테이블에 쌓지 않는다(G-05 · D-505). 화면을 열 때마다 원천에서 다시 센다.
산식이 정해지지 않은 값은 지어내지 않는다 — 로스율은 `미확정 (D-519)` 이고 원 수량만 낸다. 가동률은 가설 D-801(가동 ÷ (가동 + 정지)).

    utilization(year, month) -> dict                       PRP-010 월별 가동률 — 설비별 가동·정지 분과 가동률
    machine_stats(date_from, date_to) -> list[dict]        PRP-020 기계별통계 — 설비별 생산·양품·로스 수량
    completion(date_from, date_to, customer_id=None) -> dict   PRP-030 생산완료집계 — 제품 입고(취소 제외) 기준
    request_shipments(request_ids=None) -> dict[int, dict]     납기 보조 — 의뢰별 출하 지시 · 확정 수량

W2 에 `customer_receivable(customer_id)` 를 더한다(아직 없다 — 개발1 TRK-030 은 그때까지 `미수집`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..db import conn

#: 가동률 산식 — 가설 D-801 (decisions.md). 화면에 그대로 보인다
UTILIZATION_FORMULA = "가동률 = 가동 시간 ÷ (가동 시간 + 정지 시간) × 100 — 가설 (D-801)"
#: 로스율 산식은 사람이 정하지 않았다 (D-519)
LOSS_RATE_DECISION = "D-519"

# 설비 목록 = 공통코드(그룹 설비) ∪ 일보에 나온 설비 코드. 일보가 없는 설비도 행이 나온다(값은 None → 화면 `미수집`)
_EQUIPMENT_CTE = """
equipment as (
    select c.code as equipment_code, c.code_name as equipment_name, c.sort_no
      from sys_common_code c
     where c.group_code = '설비' and c.use_yn = 'Y'
    union
    select distinct d.equipment_code, null::text, null::integer
      from production_daily d
     where d.work_date >= %(f)s and d.work_date < %(t)s
       and not exists (select 1 from sys_common_code c
                        where c.group_code = '설비' and c.code = d.equipment_code)
)"""


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end


def _rate(run: int | None, stop: int | None) -> Decimal | None:
    """가동률(%) 소수 1자리 — 가동·정지가 모두 없으면(또는 합이 0) None = 미수집."""
    if run is None and stop is None:
        return None
    total = (run or 0) + (stop or 0)
    if total == 0:
        return None
    return (Decimal(run or 0) * 100 / Decimal(total)).quantize(Decimal("0.1"))


def utilization(year: int, month: int) -> dict:
    """PRP-010 — 그 달의 설비별 가동 분 · 정지 분 · 일보 일수 · 가동률(D-801).

    반환 {"period": (시작일, 다음 달 1일), "rows": [{equipment_code, equipment_name, days, entries,
          run_minutes, stop_minutes, rate}], "total": {run_minutes, stop_minutes, rate}, "formula": str}
    run/stop 이 비어 있는 일보 행은 그 칸을 세지 않는다(0 으로 지어내지 않는다).
    """
    f, t = _month_bounds(year, month)
    rows = conn.q(
        f"""with {_EQUIPMENT_CTE},
        agg as (
            select d.equipment_code,
                   count(distinct d.work_date) as days,
                   count(*) as entries,
                   sum(d.run_minutes) as run_minutes,
                   sum(d.stop_minutes) as stop_minutes
              from production_daily d
             where d.work_date >= %(f)s and d.work_date < %(t)s
             group by d.equipment_code
        )
        select e.equipment_code, e.equipment_name, a.days, a.entries, a.run_minutes, a.stop_minutes
          from equipment e left join agg a on a.equipment_code = e.equipment_code
         order by e.sort_no nulls last, e.equipment_code""",
        {"f": f, "t": t})
    for r in rows:
        r["rate"] = _rate(r["run_minutes"], r["stop_minutes"])
    runs = [r["run_minutes"] for r in rows if r["run_minutes"] is not None]
    stops = [r["stop_minutes"] for r in rows if r["stop_minutes"] is not None]
    run_total = sum(runs) if runs else None
    stop_total = sum(stops) if stops else None
    return {"period": (f, t), "rows": rows,
            "total": {"run_minutes": run_total, "stop_minutes": stop_total, "rate": _rate(run_total, stop_total)},
            "formula": UTILIZATION_FORMULA}


def machine_stats(date_from: date, date_to: date) -> list[dict]:
    """PRP-020 — 기간(시작일 ~ 종료일, 양끝 포함)의 설비별 지시 수 · 일보 행 수 · 생산 · 양품 · 로스 수량 · 가동·정지 분.

    로스율은 산식이 정해지지 않아(D-519) 내지 않는다 — 화면이 `미확정 (D-519)` 와 원 수량을 함께 보인다.
    """
    return conn.q(
        f"""with {_EQUIPMENT_CTE},
        agg as (
            select d.equipment_code,
                   count(distinct d.work_order_id) as work_orders,
                   count(*) as entries,
                   sum(d.produced_qty) as produced_qty,
                   sum(d.good_qty) as good_qty,
                   sum(d.loss_qty) as loss_qty,
                   sum(d.run_minutes) as run_minutes,
                   sum(d.stop_minutes) as stop_minutes
              from production_daily d
             where d.work_date >= %(f)s and d.work_date < %(t)s
             group by d.equipment_code
        )
        select e.equipment_code, e.equipment_name, a.work_orders, a.entries, a.produced_qty, a.good_qty,
               a.loss_qty, a.run_minutes, a.stop_minutes
          from equipment e left join agg a on a.equipment_code = e.equipment_code
         order by e.sort_no nulls last, e.equipment_code""",
        {"f": date_from, "t": date.fromordinal(date_to.toordinal() + 1)})


def completion(date_from: date, date_to: date, customer_id: int | None = None) -> dict:
    """PRP-030 — 생산 완료 = 제품 입고(MAT-030 · `product_receipt`, 취소 표시 행 제외). 기간은 입고일(양끝 포함).

    반환 {"rows": [{customer_id, customer_code, customer_name, item_code, item_name, work_orders, receipts, qty}],
          "monthly": [{"ym": "YYYY-MM", "receipts", "qty"}], "total": {"work_orders", "receipts", "qty"}}
    거래처는 지시 → 생산의뢰의 거래처다.
    """
    params = {"f": date_from, "t": date_to, "c": customer_id}
    where = """r.canceled_at is null and r.received_on between %(f)s and %(t)s
               and (%(c)s::bigint is null or q.customer_id = %(c)s::bigint)"""
    base = """from product_receipt r
              join work_order w on w.id = r.work_order_id
              join production_request q on q.id = w.request_id
              join customer c on c.id = q.customer_id
              join item i on i.id = w.item_id"""
    rows = conn.q(
        f"""select c.id as customer_id, c.customer_code, c.customer_name, i.item_code, i.item_name,
                   count(distinct w.id) as work_orders, count(*) as receipts, sum(r.qty) as qty
              {base} where {where}
             group by c.id, c.customer_code, c.customer_name, i.item_code, i.item_name
             order by c.customer_code, i.item_code""", params)
    monthly = conn.q(
        f"""select to_char(r.received_on, 'YYYY-MM') as ym, count(*) as receipts, sum(r.qty) as qty
              {base} where {where}
             group by 1 order by 1""", params)
    total = conn.q1(
        f"""select count(distinct w.id) as work_orders, count(*) as receipts, sum(r.qty) as qty
              {base} where {where}""", params)
    return {"rows": rows, "monthly": monthly, "total": total}


def request_shipments(request_ids: list[int] | None = None) -> dict[int, dict]:
    """납기 보조 — 생산의뢰별 출하 수량. {request_id: {"ordered_qty", "shipped_qty", "last_confirmed_at"}}

    ordered_qty = 상태 `지시` 인 출하 지시의 할당 합 · shipped_qty = `확정` 출하의 출하 행 합(반품·정정은 빼지 않는다 — D-515).
    취소된 출하 지시는 세지 않는다. 출하가 없는 의뢰는 키가 없다. request_ids 가 None 이면 의뢰가 있는 출하 전부.
    """
    rows = conn.q(
        """select o.request_id,
                  coalesce(sum(l.qty) filter (where o.status = '지시'), 0) as ordered_qty,
                  coalesce(sum(l.qty) filter (where o.status = '확정'), 0) as shipped_qty,
                  max(o.confirmed_at) as last_confirmed_at
             from shipment_order o
             join shipment_line l on l.shipment_order_id = o.id
            where o.request_id is not null and o.status <> '취소'
              and (%(ids)s::bigint[] is null or o.request_id = any(%(ids)s::bigint[]))
            group by o.request_id""",
        {"ids": request_ids})
    return {r["request_id"]: {k: r[k] for k in ("ordered_qty", "shipped_qty", "last_confirmed_at")} for r in rows}
