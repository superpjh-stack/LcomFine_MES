"""PRD 생산일보 — PRD-010 생산일보 · PRD-020 생산일보출력 · PRD-030 생산일보현황 · PRD-040 생산 로스율 (개발2).

일보 한 행 = 지시 × 일자 × 설비(스펙 §4.1 · 유일). 설비는 공통코드 그룹 `설비`(SYS-030).
일보의 완료(양품) 수량 합이 제품 입고(MAT-030)의 기본값이 된다.
로스율 산식은 미확정 (D-519) — 비율을 지어내지 않고 원 수량(지시 · 생산 · 양품 · 로스)을 함께 보인다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http
from .inv import _bad, date_in, equipments, int_in, num_in, open_work_orders, path_id, qs, text_in, work_order_in

router = APIRouter()

DAILY_SELECT = """select d.id, d.work_date, d.equipment_code, c.code_name as equipment_name, w.id as work_order_id,
                         w.work_order_no, w.qty as order_qty, i.item_code, i.item_name,
                         d.produced_qty, d.good_qty, d.loss_qty, d.run_minutes, d.stop_minutes, d.note, d.created_by
                    from production_daily d
                    join work_order w on w.id = d.work_order_id
                    join item i on i.id = w.item_id
                    left join sys_common_code c on c.group_code = '설비' and c.code = d.equipment_code
                   where true"""


def _equipment_in(value: str | None) -> str:
    code = text_in(value, "설비", required=True)
    row = conn.q1("select use_yn from sys_common_code where group_code = '설비' and code = %s", (code,))
    if row is None:
        raise _bad("설비", f"공통코드(설비)에 없는 설비입니다: {code}")
    if row["use_yn"] != "Y":
        raise _bad("설비", f"사용 중지된 설비입니다: {code}")
    return code


def _qtys(produced_qty: str, good_qty: str, loss_qty: str, *, required: bool) -> dict:
    out = {"produced_qty": num_in(produced_qty, "생산 수량", required=required, allow_zero=True),
           "good_qty": num_in(good_qty, "완료(양품) 수량", required=required, allow_zero=True),
           "loss_qty": num_in(loss_qty, "로스 수량", required=False, allow_zero=True)}
    if required and out["loss_qty"] is None:
        out["loss_qty"] = Decimal(0)
    return out


def _daily_rows(f: dict) -> list[dict]:
    sql, params = DAILY_SELECT, []
    d = date_in(f.get("date"), "일자")
    if d:
        sql += " and d.work_date = %s"
        params.append(d)
    d_from, d_to = date_in(f.get("from"), "시작일"), date_in(f.get("to"), "종료일")
    if d_from:
        sql += " and d.work_date >= %s"
        params.append(d_from)
    if d_to:
        sql += " and d.work_date <= %s"
        params.append(d_to)
    if f.get("equipment"):
        sql += " and d.equipment_code = %s"
        params.append(f["equipment"])
    if f.get("item"):
        sql += " and (i.item_code ilike %s or i.item_name ilike %s)"
        params += [f"%{f['item']}%"] * 2
    if f.get("wo"):
        sql += " and w.work_order_no ilike %s"
        params.append(f"%{f['wo']}%")
    return conn.q(sql + " order by d.work_date desc, d.equipment_code, w.work_order_no limit 2000", params)


def _sum(rows: list[dict], *keys: str) -> dict:
    return {k: sum((r[k] or 0 for r in rows), Decimal(0)) for k in keys}


# ── PRD-010 생산일보 ──────────────────────────────────────────────────────
@router.get(nav.path_of("PRD-010"), response_class=HTMLResponse)
def daily(request: Request, user: rbac.User = rbac.require_fn("F-PRD-013")):
    f = {k: qs(request, k) for k in ("date", "equipment", "wo")}
    rows = _daily_rows(f)
    return templating.render(request, "prd/daily.html", {
        "rows": rows, "f": f, "equipments": equipments(), "work_orders": open_work_orders(),
        "today": date.today().isoformat(), "can_w": rbac.can(user, "PRD-010", "W")}, screen_id="PRD-010")


@router.post("/prd/daily")
def create_daily(request: Request, work_order_id: str = Form(""), work_order_no: str = Form(""),
                 work_date: str = Form(""), equipment_code: str = Form(""),
                 produced_qty: str = Form(""), good_qty: str = Form(""), loss_qty: str = Form(""),
                 run_minutes: str = Form(""), stop_minutes: str = Form(""), note: str = Form(""),
                 user: rbac.User = rbac.require_fn("F-PRD-011")):
    wo = work_order_in(work_order_id, work_order_no)
    d = date_in(work_date, "일자", required=True)
    eq = _equipment_in(equipment_code)
    q = _qtys(produced_qty, good_qty, loss_qty, required=True)
    run, stop = int_in(run_minutes, "가동 시간(분)"), int_in(stop_minutes, "정지 시간(분)")
    memo = text_in(note, "비고")
    if conn.q1("select 1 from production_daily where work_order_id = %s and work_date = %s and equipment_code = %s",
               (wo["id"], d, eq)):
        raise _bad("일보", f"{wo['work_order_no']} · {d} · {eq} 일보가 이미 있습니다 — 그 행을 고칩니다")
    with conn.tx() as cur:
        cur.execute("""insert into production_daily (work_order_id, work_date, equipment_code, produced_qty, good_qty, loss_qty,
                                                     run_minutes, stop_minutes, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                    (wo["id"], d, eq, q["produced_qty"], q["good_qty"], q["loss_qty"], run, stop, memo, user.login_id))
        did = cur.fetchone()["id"]
    resp = http.saved(request, f"생산일보를 등록했습니다 — {wo['work_order_no']} · {d} · {eq}", data={"daily_id": did})
    audit.log_change(request, user, "F-PRD-011", f"production_daily:{wo['work_order_no']}/{d}/{eq}",
                     f"생산 {q['produced_qty']} 양품 {q['good_qty']} 로스 {q['loss_qty']}")
    return resp


@router.post("/prd/daily/{id}")
def update_daily(request: Request, id: str, produced_qty: str = Form(""), good_qty: str = Form(""),
                 loss_qty: str = Form(""), run_minutes: str = Form(""), stop_minutes: str = Form(""), note: str = Form(""),
                 user: rbac.User = rbac.require_fn("F-PRD-012")):
    did = path_id(id)
    row = conn.q1("select * from production_daily where id = %s", (did,))
    if row is None:
        raise http.not_found()
    q = _qtys(produced_qty, good_qty, loss_qty, required=False)
    run, stop = int_in(run_minutes, "가동 시간(분)"), int_in(stop_minutes, "정지 시간(분)")
    memo = text_in(note, "비고")
    if all(v is None for v in (*q.values(), run, stop, memo)):
        raise _bad("일보", "고칠 값이 없습니다", "고칠 수량 · 시간 · 비고를 입력하세요")
    with conn.tx() as cur:
        cur.execute("""update production_daily set produced_qty = coalesce(%s, produced_qty), good_qty = coalesce(%s, good_qty),
                              loss_qty = coalesce(%s, loss_qty), run_minutes = coalesce(%s, run_minutes),
                              stop_minutes = coalesce(%s, stop_minutes), note = coalesce(%s, note),
                              updated_at = now(), updated_by = %s where id = %s""",
                    (q["produced_qty"], q["good_qty"], q["loss_qty"], run, stop, memo, user.login_id, did))
    resp = http.saved(request, "생산일보를 고쳤습니다", data={"daily_id": did})
    audit.log_change(request, user, "F-PRD-012", f"production_daily:{did}", "생산일보 수정")
    return resp


# ── PRD-020 생산일보출력 ──────────────────────────────────────────────────
@router.get(nav.path_of("PRD-020"), response_class=HTMLResponse)
def daily_print(request: Request, user: rbac.User = rbac.require_fn("F-PRD-021")):
    f = {"date": qs(request, "date") or date.today().isoformat(), "equipment": qs(request, "equipment")}
    rows = _daily_rows(f)
    return templating.render(request, "prd/daily_print.html", {
        "rows": rows, "f": f, "equipments": equipments(),
        "totals": _sum(rows, "produced_qty", "good_qty", "loss_qty")}, screen_id="PRD-020")


# ── PRD-030 생산일보현황 ──────────────────────────────────────────────────
@router.get(nav.path_of("PRD-030"), response_class=HTMLResponse)
def status(request: Request, user: rbac.User = rbac.require_fn("F-PRD-031")):
    f = {k: qs(request, k) for k in ("from", "to", "equipment", "item")}
    rows = _daily_rows(f)
    return templating.render(request, "prd/status.html", {
        "rows": rows, "f": f, "equipments": equipments(),
        "totals": _sum(rows, "produced_qty", "good_qty", "loss_qty")}, screen_id="PRD-030")


# ── PRD-040 생산지시서 대비 생산 로스율 ──────────────────────────────────────
@router.get(nav.path_of("PRD-040"), response_class=HTMLResponse)
def loss_rate(request: Request, user: rbac.User = rbac.require_fn("F-PRD-041")):
    f = {k: qs(request, k) for k in ("from", "to", "wo")}
    d_from, d_to = date_in(f["from"], "시작일"), date_in(f["to"], "종료일")
    sql = """select w.id, w.work_order_no, w.qty as order_qty, w.status, i.item_code, i.item_name,
                    count(d.id) as days, sum(d.produced_qty) as produced_qty, sum(d.good_qty) as good_qty,
                    sum(d.loss_qty) as loss_qty
               from work_order w join item i on i.id = w.item_id
               join production_daily d on d.work_order_id = w.id
              where true"""
    params: list = []
    if d_from:
        sql += " and d.work_date >= %s"
        params.append(d_from)
    if d_to:
        sql += " and d.work_date <= %s"
        params.append(d_to)
    if f["wo"]:
        sql += " and w.work_order_no ilike %s"
        params.append(f"%{f['wo']}%")
    rows = conn.q(sql + " group by w.id, i.id order by w.work_order_no desc limit 1000", params)
    return templating.render(request, "prd/loss_rate.html", {"rows": rows, "f": f, "decision": "D-519"},
                             screen_id="PRD-040")
