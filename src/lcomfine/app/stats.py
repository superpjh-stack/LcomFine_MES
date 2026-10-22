"""집계 SQL — PRP 생산 보고서 · 납기 보조 (개발3 · `contracts/interfaces.md` §9 · 공표 `progress-dev3.md` §1).

**읽기만 한다.** 어떤 테이블에도 쓰지 않고, 집계 결과를 캐시 테이블에 쌓지 않는다(G-05 · D-505). 화면을 열 때마다 원천에서 다시 센다.
산식이 정해지지 않은 값은 지어내지 않는다 — 로스율은 `미확정 (D-519)` 이고 원 수량만 낸다. 가동률은 가설 D-801(가동 ÷ (가동 + 정지)).

    utilization(year, month) -> dict                       PRP-010 월별 가동률 — 설비별 가동·정지 분과 가동률
    machine_stats(date_from, date_to) -> list[dict]        PRP-020 기계별통계 — 설비별 생산·양품·로스 수량
    completion(date_from, date_to, customer_id=None) -> dict   PRP-030 생산완료집계 — 제품 입고(취소 제외) 기준
    request_shipments(request_ids=None) -> dict[int, dict]     납기 보조 — 의뢰별 출하 지시 · 확정 수량

W2 수금 (COL · 공표 `progress-dev3.md` §1 · ERP 원천 = 반영 회차의 오류 없는 행 · 거래처는 `erp_customer_map` 사용 중 매핑으로 잇는다):
    erp_asof() -> date | None                                  반영 회차의 마지막 기준 기간 끝 = 「ERP 업로드 기준일」
    collections(date_from, date_to, customer_id=None, method=None) -> dict      COL-040 수금 현황
    receivables(asof, include_zero=False) -> dict              COL-050 거래처별 미수 (매출 열 미매핑 → `미확정 (D-516)`)
    aging(asof) -> dict                                        COL-060 미수 연령 30 · 60 · 90 · 90 초과 (가설 D-803)
    shipment_vs_collection(ym_from, ym_to, customer_id=None) -> dict   COL-070 MES 출하 ↔ ERP 매출·수금 (월 · 거래처 · 독립 집계 · G-14)
    customer_receivable(customer_id) -> dict                   TRK-030 수금 칸 (개발1)
    due_compliance(period) -> dict                             TRK-020 납기 준수율 (개발1 · Ruling 23 · 가설 D-804)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..db import conn
from . import erp_upload

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


# ══════════════════════════════════════════════════════════════════════════
# W2 수금 — ERP 원천 (반영 회차 · error 없는 행 · 사용 중 매핑) — `v_dq_collections` 와 같은 모양 + customer_id
# ══════════════════════════════════════════════════════════════════════════

#: COL-050 · COL-060 · TRK-030 의 매출 · 잔액이 기대는 열 — 매핑되지 않으면 `미확정 (D-516)`
ERP_DECISION = erp_upload.DECISION
#: 미수 연령 구간 (이름, 경과일 시작, 경과일 끝(None = 상한 없음)) — 매출일 기준 경과일 (정본 COL-060 · 가설 D-803)
AGING_BUCKETS: tuple[tuple[str, int, int | None], ...] = (("0~30일", 0, 30), ("31~60일", 31, 60), ("61~90일", 61, 90),
                                                          ("90일 초과", 91, None))
#: 납기 준수율 산식 — 가설 D-804
DUE_COMPLIANCE_FORMULA = "납기 준수율 = 납기 안 완료 ÷ (납기 안 완료 + 지연 완료 + 지연) × 100 — 가설 (D-804)"

_ERP_CTE = """
erp as (
    select b.id as batch_id, b.batch_no, b.period_from, b.period_to, u.row_no,
           u.parsed ->> 'customer_code' as erp_code,
           cm.customer_id, c.customer_code, c.customer_name,
           nullif(u.parsed ->> 'txn_date', '')::date as txn_date,
           nullif(u.parsed ->> 'sales_amount', '')::numeric(16,2) as sales_amount,
           nullif(u.parsed ->> 'collected_amount', '')::numeric(16,2) as collected_amount,
           nullif(u.parsed ->> 'balance_amount', '')::numeric(16,2) as balance_amount,
           nullif(u.parsed ->> 'method', '') as method,
           nullif(u.parsed ->> 'bill_due_date', '')::date as bill_due_date
      from erp_upload_row u
      join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
      left join erp_customer_map cm on cm.erp_code = u.parsed ->> 'customer_code' and cm.use_yn = 'Y'
      left join customer c on c.id = cm.customer_id
     where u.error is null and u.parsed is not null
)"""


def erp_asof() -> date | None:
    """반영 회차의 마지막 기준 기간 끝 — 화면에 「ERP 업로드 기준일」로 적는다. 회차가 없으면 None(미수집)."""
    return conn.q1("select max(period_to) as d from erp_upload_batch where status = '반영'")["d"]


def _sum_or_none(rows: list[dict], key: str) -> Decimal | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals, Decimal(0)) if vals else None


def collections(date_from: date, date_to: date, customer_id: int | None = None, method: str | None = None) -> dict:
    """COL-040 — 일자별 수금 목록(양끝 포함). 어음은 만기일과 만기 도래 여부(`bill_due` = 도래 · 예정)를 함께.

    반환 {"rows": [...erp 열 + bill_due], "total": {rows, sales_amount, collected_amount},
          "by_method": [{method, rows, collected_amount}], "asof": date | None, "fields": {항목: 매핑 여부}}
    거래처 미매핑 행은 오류라서 반영에 없다 — 여기서도 보이지 않는다(COL-030 에서 매핑한다).
    """
    params = {"f": date_from, "t": date_to, "c": customer_id, "m": method or None}
    where = """e.txn_date between %(f)s and %(t)s
               and (%(c)s::bigint is null or e.customer_id = %(c)s::bigint)
               and (%(m)s::text is null or e.method = %(m)s::text)"""
    rows = conn.q(f"""with {_ERP_CTE}
                      select e.*, case when e.bill_due_date is null then null
                                       when e.bill_due_date <= current_date then '도래' else '예정' end as bill_due
                        from erp e where {where}
                       order by e.txn_date, e.customer_code nulls last, e.erp_code, e.row_no limit 5000""", params)
    by_method = conn.q(f"""with {_ERP_CTE}
                           select e.method, count(*) as rows, sum(e.collected_amount) as collected_amount
                             from erp e where {where} group by e.method order by e.method nulls last""", params)
    return {"rows": rows,
            "total": {"rows": len(rows), "sales_amount": _sum_or_none(rows, "sales_amount"),
                      "collected_amount": _sum_or_none(rows, "collected_amount")},
            "by_method": by_method, "asof": erp_asof(), "fields": erp_upload.mapped_fields()}


def receivables(asof: date, include_zero: bool = False) -> dict:
    """COL-050 — 기준일까지(txn_date ≤ asof) 거래처별 매출 · 수금 · 미수 잔액(= Σ매출 − Σ수금 · `v_dq_receivables` 와 같은 정의).

    매출액 열이 매핑되지 않았으면 미수 잔액을 낼 수 없다 → `undecided = "D-516"` 이고 rows 의 sales_amount · receivable_amount 는 None
    (수금 합은 그대로 보인다). 잔액 열(ERP 잔액)은 매핑되었을 때만 기준일 이전 마지막 행의 값을 `erp_balance` 로 보인다(가설 D-803).
    미수 0(또는 None) 인 거래처는 include_zero 가 아니면 숨긴다(정본). 매핑 없는 ERP 코드 행은 반영에 없다.
    반환 {"asof", "rows": [{customer_id, customer_code, customer_name, erp_codes, rows, sales_amount, collected_amount,
          receivable_amount, erp_balance, last_txn_date}], "total": {...}, "undecided": None | "D-516", "fields"}
    """
    fields = erp_upload.mapped_fields()
    rows = conn.q(f"""with {_ERP_CTE},
                      agg as (
                          select e.customer_id, e.customer_code, e.customer_name,
                                 array_agg(distinct e.erp_code order by e.erp_code) as erp_codes,
                                 count(*) as rows,
                                 sum(e.sales_amount) as sales_amount,
                                 sum(e.collected_amount) as collected_amount,
                                 max(e.txn_date) as last_txn_date
                            from erp e
                           where e.customer_id is not null and e.txn_date <= %(asof)s
                           group by e.customer_id, e.customer_code, e.customer_name),
                      last_bal as (
                          select distinct on (e.customer_id) e.customer_id, e.balance_amount
                            from erp e
                           where e.customer_id is not null and e.txn_date <= %(asof)s and e.balance_amount is not null
                           order by e.customer_id, e.txn_date desc, e.batch_id desc, e.row_no desc)
                      select a.*, coalesce(a.sales_amount, 0) - coalesce(a.collected_amount, 0) as receivable_amount,
                             lb.balance_amount as erp_balance
                        from agg a left join last_bal lb on lb.customer_id = a.customer_id
                       order by a.customer_code""", {"asof": asof})
    undecided = None if fields["sales_amount"] else ERP_DECISION
    for r in rows:
        if undecided:
            r["sales_amount"] = None
            r["receivable_amount"] = None
        if not fields["balance_amount"]:
            r["erp_balance"] = None
    if not include_zero and not undecided:
        rows = [r for r in rows if r["receivable_amount"] != 0]
    total = {"customers": len(rows), "sales_amount": _sum_or_none(rows, "sales_amount"),
             "collected_amount": _sum_or_none(rows, "collected_amount"),
             "receivable_amount": _sum_or_none(rows, "receivable_amount")}
    return {"asof": asof, "rows": rows, "total": total, "undecided": undecided, "fields": fields}


def aging(asof: date) -> dict:
    """COL-060 — 기준일 기준 매출일 경과일로 30 · 60 · 90 · 90 초과 구간을 나눈다(정본 「매출일 기준 경과일로 나눈다」).

    구간 금액 = 그 구간에 든 행들의 Σ매출 − Σ수금 (가설 D-803 — 건 단위 대사가 없어 행 단위 순액으로 센다 · 음수가 나올 수 있다).
    매출액 열이 매핑되지 않았으면 `undecided = "D-516"` 이고 금액은 None. 기준일보다 뒤의 행은 세지 않는다.
    반환 {"asof", "buckets": [이름], "rows": [{customer_id, customer_code, customer_name, cells: {이름: {sales, collected, net}}, total_net}],
          "totals": {이름: {sales, collected, net}}, "over90": [rows 중 90일 초과 순액 > 0], "undecided", "fields", "formula"}
    """
    fields = erp_upload.mapped_fields()
    case = " ".join(f"when (%(asof)s::date - e.txn_date) between {lo} and {hi} then '{name}'" if hi is not None
                    else f"when (%(asof)s::date - e.txn_date) >= {lo} then '{name}'" for name, lo, hi in AGING_BUCKETS)
    rows = conn.q(f"""with {_ERP_CTE}
                      select e.customer_id, e.customer_code, e.customer_name,
                             case {case} end as bucket,
                             sum(e.sales_amount) as sales_amount, sum(e.collected_amount) as collected_amount, count(*) as rows
                        from erp e
                       where e.customer_id is not null and e.txn_date <= %(asof)s
                       group by e.customer_id, e.customer_code, e.customer_name, 4
                       order by e.customer_code, 4""", {"asof": asof})
    undecided = None if fields["sales_amount"] else ERP_DECISION
    names = [b[0] for b in AGING_BUCKETS]
    by_customer: dict[int, dict] = {}
    totals = {n: {"sales_amount": Decimal(0), "collected_amount": Decimal(0), "net": Decimal(0), "rows": 0} for n in names}
    for r in rows:
        c = by_customer.setdefault(r["customer_id"], {
            "customer_id": r["customer_id"], "customer_code": r["customer_code"], "customer_name": r["customer_name"],
            "cells": {n: {"sales_amount": Decimal(0), "collected_amount": Decimal(0), "net": Decimal(0), "rows": 0} for n in names},
            "total_net": Decimal(0)})
        sales = r["sales_amount"] or Decimal(0)
        coll = r["collected_amount"] or Decimal(0)
        cell = c["cells"][r["bucket"]]
        cell["sales_amount"] += sales
        cell["collected_amount"] += coll
        cell["net"] += sales - coll
        cell["rows"] += r["rows"]
        c["total_net"] += sales - coll
        t = totals[r["bucket"]]
        t["sales_amount"] += sales
        t["collected_amount"] += coll
        t["net"] += sales - coll
        t["rows"] += r["rows"]
    out_rows = sorted(by_customer.values(), key=lambda c: c["customer_code"] or "")
    if undecided:
        for c in out_rows:
            c["total_net"] = None
            for cell in c["cells"].values():
                cell["sales_amount"] = None
                cell["net"] = None
        for t in totals.values():
            t["sales_amount"] = None
            t["net"] = None
    over90 = [] if undecided else [c for c in out_rows if c["cells"][names[-1]]["net"] > 0]
    return {"asof": asof, "buckets": names, "rows": out_rows, "totals": totals, "over90": over90,
            "undecided": undecided, "fields": fields,
            "formula": "구간 금액 = 그 구간 매출일 행의 Σ매출 − Σ수금 — 가설 (D-803)"}


def _ym_bounds(ym_from: str, ym_to: str) -> tuple[date, date]:
    f = date(int(ym_from[:4]), int(ym_from[5:7]), 1)
    y, m = int(ym_to[:4]), int(ym_to[5:7])
    t = date(y + (m == 12), m % 12 + 1, 1)
    return f, t


def shipment_vs_collection(ym_from: str, ym_to: str, customer_id: int | None = None) -> dict:
    """COL-070 — 월 · 거래처 단위로 MES 출하(확정 출하 건수 · 수량)와 ERP 매출 · 수금을 나란히(G-14).

    두 쪽을 **따로** 집계해 (월, 거래처) 로 붙인다 — 출하 한 건과 수금 한 건을 짝짓지 않는다(정본). 출하 월 = 출하 확정일(confirmed_at),
    ERP 월 = 일자(txn_date). 거래처는 MES 거래처 id 이고 ERP 쪽은 `erp_customer_map` 사용 중 매핑으로 잇는다.
    반환 {"months": ["YYYY-MM", …], "rows": [{ym, customer_id, customer_code, customer_name, shipments, shipped_qty,
          sales_amount, collected_amount}], "total": {...}, "monthly": [{ym, shipments, shipped_qty, sales_amount, collected_amount}],
          "asof", "fields"} — 한쪽만 있는 (월, 거래처) 는 다른 쪽이 None.
    """
    f, t = _ym_bounds(ym_from, ym_to)
    params = {"f": f, "t": t, "c": customer_id}
    rows = conn.q(f"""with {_ERP_CTE},
                      ship as (
                          select to_char(o.confirmed_at, 'YYYY-MM') as ym, o.customer_id,
                                 count(distinct o.id) as shipments, sum(l.qty) as shipped_qty
                            from shipment_order o join shipment_line l on l.shipment_order_id = o.id
                           where o.status = '확정' and o.confirmed_at >= %(f)s and o.confirmed_at < %(t)s
                             and (%(c)s::bigint is null or o.customer_id = %(c)s::bigint)
                           group by 1, 2),
                      coll as (
                          select to_char(e.txn_date, 'YYYY-MM') as ym, e.customer_id,
                                 sum(e.sales_amount) as sales_amount, sum(e.collected_amount) as collected_amount,
                                 count(*) as erp_rows
                            from erp e
                           where e.customer_id is not null and e.txn_date >= %(f)s and e.txn_date < %(t)s
                             and (%(c)s::bigint is null or e.customer_id = %(c)s::bigint)
                           group by 1, 2)
                      select coalesce(s.ym, k.ym) as ym, coalesce(s.customer_id, k.customer_id) as customer_id,
                             c.customer_code, c.customer_name,
                             s.shipments, s.shipped_qty, k.sales_amount, k.collected_amount, k.erp_rows
                        from ship s full outer join coll k on k.ym = s.ym and k.customer_id = s.customer_id
                        join customer c on c.id = coalesce(s.customer_id, k.customer_id)
                       order by 1, c.customer_code""", params)
    months: list[str] = []
    y, m = f.year, f.month
    while date(y, m, 1) < t:
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    monthly = []
    for ym in months:
        part = [r for r in rows if r["ym"] == ym]
        monthly.append({"ym": ym, "shipments": _sum_or_none(part, "shipments"), "shipped_qty": _sum_or_none(part, "shipped_qty"),
                        "sales_amount": _sum_or_none(part, "sales_amount"),
                        "collected_amount": _sum_or_none(part, "collected_amount")})
    total = {k: _sum_or_none(rows, k) for k in ("shipments", "shipped_qty", "sales_amount", "collected_amount")}
    return {"months": months, "rows": rows, "monthly": monthly, "total": total, "asof": erp_asof(),
            "fields": erp_upload.mapped_fields()}


def customer_receivable(customer_id: int) -> dict:
    """TRK-030 수금 칸 (개발1) — 그 거래처의 ERP 수금 · 미수. **읽기만.**

    반환 {"customer_id", "asof": date | None(ERP 업로드 기준일 = 반영 회차의 마지막 기간 끝), "erp_codes": [str],
          "rows": int(반영 행 수), "sales_amount": Decimal | None, "collected_amount": Decimal | None,
          "receivable_amount": Decimal | None(= Σ매출 − Σ수금), "last_txn_date": date | None,
          "status": "ok" | "미수집" | "미확정 (D-516)", "decision": None | "D-516"}
    - 매핑된 ERP 코드가 없거나 반영 행이 없으면 status = "미수집" (금액 전부 None).
    - 매출액 열이 매핑되지 않았으면 status = "미확정 (D-516)" — collected_amount 는 그대로, sales · receivable 은 None.
    기준일(asof)은 반영 회차의 마지막 기간 끝이고, 그 거래처 행의 txn_date 는 제한하지 않는다(올라온 전부).
    """
    fields = erp_upload.mapped_fields()
    codes = [r["erp_code"] for r in conn.q(
        "select erp_code from erp_customer_map where customer_id = %s and use_yn = 'Y' order by erp_code", (customer_id,))]
    agg = conn.q1(f"""with {_ERP_CTE}
                      select count(*) as rows, sum(e.sales_amount) as sales_amount, sum(e.collected_amount) as collected_amount,
                             max(e.txn_date) as last_txn_date
                        from erp e where e.customer_id = %s""", (customer_id,))
    out = {"customer_id": customer_id, "asof": erp_asof(), "erp_codes": codes, "rows": agg["rows"],
           "sales_amount": None, "collected_amount": None, "receivable_amount": None, "last_txn_date": agg["last_txn_date"],
           "status": "미수집", "decision": None}
    if not codes or not agg["rows"]:
        return out
    out["collected_amount"] = agg["collected_amount"] if agg["collected_amount"] is not None else Decimal(0)
    if not fields["sales_amount"]:
        out["status"] = f"미확정 ({ERP_DECISION})"
        out["decision"] = ERP_DECISION
        return out
    out["sales_amount"] = agg["sales_amount"] if agg["sales_amount"] is not None else Decimal(0)
    out["receivable_amount"] = out["sales_amount"] - out["collected_amount"]
    out["status"] = "ok"
    return out


def _period_arg(period) -> tuple[date, date]:
    """`"YYYY-MM"` 또는 `(시작일, 종료일)`(양끝 포함) → (시작일, 종료일). 그 밖은 ValueError."""
    if isinstance(period, str):
        if len(period) != 7 or period[4] != "-" or not (period[:4] + period[5:]).isdigit():
            raise ValueError(f"기간은 'YYYY-MM' 또는 (시작일, 종료일) — {period!r}")
        f = date(int(period[:4]), int(period[5:]), 1)
        nxt = date(f.year + (f.month == 12), f.month % 12 + 1, 1)
        return f, date.fromordinal(nxt.toordinal() - 1)
    f, t = period
    if not isinstance(f, date) or not isinstance(t, date) or f > t:
        raise ValueError(f"기간은 (시작일 ≤ 종료일) — {period!r}")
    return f, t


def due_compliance(period) -> dict:
    """TRK-020 납기 준수율 (개발1 · Ruling 23) — 납기(생산의뢰 `due_date`)가 기간 안인, 취소 아닌 의뢰를 센다. **읽기만.**

    period  "YYYY-MM" 또는 (시작일, 종료일) — 양끝 포함.
    의뢰마다(가설 D-804 · D-607 의 낱말과 같다): 완료 = 확정 출하 수량 합 ≥ 의뢰 수량 · 완료일 = 마지막 확정 출하일.
      `납기 안 완료`(완료일 ≤ 납기) · `지연 완료`(완료일 > 납기) · `지연`(미완료 · 납기 < 오늘) · `진행`(미완료 · 납기 ≥ 오늘)
    준수율(%) = 납기 안 완료 ÷ (납기 안 완료 + 지연 완료 + 지연) × 100, 소수 1자리 — 분모 0 이면 None(미수집). 진행 중은 분모에 넣지 않는다.
    반환 {"period": (f, t), "total": n, "on_time": n, "late_done": n, "late_open": n, "in_progress": n, "rate": Decimal | None,
          "rows": [{request_id, request_no, customer_code, customer_name, item_code, item_name, qty, due_date, shipped_qty,
                    last_confirmed_on, bucket}], "formula": str}
    """
    f, t = _period_arg(period)
    rows = conn.q(
        """select q.id as request_id, q.request_no, q.qty, q.due_date, c.customer_code, c.customer_name, i.item_code, i.item_name,
                  coalesce(s.shipped_qty, 0) as shipped_qty, s.last_confirmed_on
             from production_request q
             join customer c on c.id = q.customer_id
             join item i on i.id = q.item_id
             left join (select o.request_id, sum(l.qty) as shipped_qty, max(o.confirmed_at)::date as last_confirmed_on
                          from shipment_order o join shipment_line l on l.shipment_order_id = o.id
                         where o.status = '확정' group by o.request_id) s on s.request_id = q.id
            where q.status <> '취소' and q.due_date between %s and %s
            order by q.due_date, q.id""", (f, t))
    today = date.today()
    counts = {"on_time": 0, "late_done": 0, "late_open": 0, "in_progress": 0}
    for r in rows:
        done = r["qty"] is not None and r["qty"] > 0 and r["shipped_qty"] >= r["qty"]
        if done:
            r["bucket"] = "지연 완료" if r["last_confirmed_on"] > r["due_date"] else "납기 안 완료"
            counts["late_done" if r["bucket"] == "지연 완료" else "on_time"] += 1
        elif r["due_date"] < today:
            r["bucket"] = "지연"
            counts["late_open"] += 1
        else:
            r["bucket"] = "진행"
            counts["in_progress"] += 1
    denom = counts["on_time"] + counts["late_done"] + counts["late_open"]
    rate = (Decimal(counts["on_time"]) * 100 / Decimal(denom)).quantize(Decimal("0.1")) if denom else None
    return {"period": (f, t), "total": len(rows), **counts, "rate": rate, "rows": rows, "formula": DUE_COMPLIANCE_FORMULA}
