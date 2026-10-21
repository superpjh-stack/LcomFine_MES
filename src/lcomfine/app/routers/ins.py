"""INS 검사일보 — INS-010 검사일보 · INS-020 검사일보출력 · INS-030 검사일보현황 · INS-040 검사 로스율 (개발2).

공정 검사 기록(지시 × 일자 한 행) — 입고검사 · 제품검사 판정(QC)과는 다른 기록이다. 불량은 공통코드 그룹 `불량유형` 별 수량(`defects`)과 합(`defect_qty`).
로스율 산식은 미확정 (D-519) — 원 수량(지시 · 검사 · 불량)을 함께 보인다.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http
from .inv import _bad, date_in, num_in, open_work_orders, path_id, qs, text_in, work_order_in

router = APIRouter()

DAILY_SELECT = """select d.id, d.work_date, w.id as work_order_id, w.work_order_no, w.qty as order_qty, i.item_code, i.item_name,
                         d.inspected_qty, d.defect_qty, d.defects, d.note, d.created_by
                    from inspection_daily d
                    join work_order w on w.id = d.work_order_id
                    join item i on i.id = w.item_id
                   where true"""


def defect_types() -> list[dict]:
    return conn.q("""select code, code_name, use_yn from sys_common_code where group_code = '불량유형'
                      order by sort_no, code""")


def _defects_in(codes: list[str], qtys: list[str]) -> dict:
    if len(codes) != len(qtys):
        raise http.validation_error("불량유형 칸 수가 맞지 않습니다", fields=[{"name": "불량유형", "reason": "칸 수 불일치"}])
    known = {r["code"]: r for r in defect_types()}
    out: dict[str, str] = {}
    for c, q in zip(codes, qtys):
        c = (c or "").strip()
        v = num_in(q, f"불량 {c} 수량", required=False, allow_zero=True)
        if not c or v is None:
            continue
        if c not in known:
            raise _bad("불량유형", f"공통코드(불량유형)에 없는 코드입니다: {c[:30]}")
        if v:
            out[c] = str(v)
    return out


def _rows(f: dict) -> list[dict]:
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
    if f.get("item"):
        sql += " and (i.item_code ilike %s or i.item_name ilike %s)"
        params += [f"%{f['item']}%"] * 2
    if f.get("wo"):
        sql += " and w.work_order_no ilike %s"
        params.append(f"%{f['wo']}%")
    return conn.q(sql + " order by d.work_date desc, w.work_order_no limit 2000", params)


def _sum(rows: list[dict], *keys: str) -> dict:
    return {k: sum((r[k] or 0 for r in rows), Decimal(0)) for k in keys}


# ── INS-010 검사일보 ──────────────────────────────────────────────────────
@router.get(nav.path_of("INS-010"), response_class=HTMLResponse)
def daily(request: Request, user: rbac.User = rbac.require_screen("INS-010")):
    f = {k: qs(request, k) for k in ("date", "wo")}
    return templating.render(request, "ins/daily.html", {
        "rows": _rows(f), "f": f, "work_orders": open_work_orders(), "defect_types": [d for d in defect_types() if d["use_yn"] == "Y"],
        "today": date.today().isoformat(), "can_w": rbac.can(user, "INS-010", "W")}, screen_id="INS-010")


def _check(inspected, defect, defects: dict):
    total = sum((Decimal(v) for v in defects.values()), Decimal(0))
    if defect is None:
        defect = total
    elif defects and defect != total:
        raise _bad("불량 수량", f"불량유형 합 {total} 과 불량 수량 {defect} 이 다릅니다")
    if inspected is not None and defect > inspected:
        raise _bad("불량 수량", f"불량 수량 {defect} 이 검사 수량 {inspected} 을(를) 넘습니다")
    return defect


@router.post("/ins/daily")
def create_daily(request: Request, work_order_id: str = Form(""), work_order_no: str = Form(""),
                 work_date: str = Form(""), inspected_qty: str = Form(""), defect_qty: str = Form(""),
                 defect_code: list[str] = Form([]), defect_code_qty: list[str] = Form([]), note: str = Form(""),
                 user: rbac.User = rbac.require_fn("F-INS-011")):
    wo = work_order_in(work_order_id, work_order_no)
    d = date_in(work_date, "일자", required=True)
    insp = num_in(inspected_qty, "검사 수량", allow_zero=True)
    defects = _defects_in(defect_code, defect_code_qty)
    defect = _check(insp, num_in(defect_qty, "불량 수량", required=False, allow_zero=True), defects)
    memo = text_in(note, "비고")
    if conn.q1("select 1 from inspection_daily where work_order_id = %s and work_date = %s", (wo["id"], d)):
        raise _bad("검사일보", f"{wo['work_order_no']} · {d} 검사일보가 이미 있습니다 — 그 행을 고칩니다")
    with conn.tx() as cur:
        cur.execute("""insert into inspection_daily (work_order_id, work_date, inspected_qty, defect_qty, defects, note, created_by)
                       values (%s, %s, %s, %s, %s::jsonb, %s, %s) returning id""",
                    (wo["id"], d, insp, defect, json.dumps(defects), memo, user.login_id))
        did = cur.fetchone()["id"]
    resp = http.saved(request, f"검사일보를 등록했습니다 — {wo['work_order_no']} · {d}", data={"daily_id": did})
    audit.log_change(request, user, "F-INS-011", f"inspection_daily:{wo['work_order_no']}/{d}", f"검사 {insp} 불량 {defect}")
    return resp


@router.post("/ins/daily/{id}")
def update_daily(request: Request, id: str, inspected_qty: str = Form(""), defect_qty: str = Form(""),
                 defect_code: list[str] = Form([]), defect_code_qty: list[str] = Form([]), note: str = Form(""),
                 user: rbac.User = rbac.require_fn("F-INS-012")):
    did = path_id(id)
    row = conn.q1("select * from inspection_daily where id = %s", (did,))
    if row is None:
        raise http.not_found()
    insp = num_in(inspected_qty, "검사 수량", required=False, allow_zero=True)
    defects = _defects_in(defect_code, defect_code_qty)
    defect_given = num_in(defect_qty, "불량 수량", required=False, allow_zero=True)
    memo = text_in(note, "비고")
    if insp is None and defect_given is None and not defects and memo is None:
        raise _bad("검사일보", "고칠 값이 없습니다", "고칠 수량 · 비고를 입력하세요")
    new_insp = insp if insp is not None else row["inspected_qty"]
    if defects or defect_given is not None:
        new_defect = _check(new_insp, defect_given, defects)
        new_defects = defects if defects else (row["defects"] if defect_given == row["defect_qty"] else {})
    else:
        new_defect, new_defects = _check(new_insp, row["defect_qty"], {}), row["defects"]
    with conn.tx() as cur:
        cur.execute("""update inspection_daily set inspected_qty = %s, defect_qty = %s, defects = %s::jsonb,
                              note = coalesce(%s, note), updated_at = now(), updated_by = %s where id = %s""",
                    (new_insp, new_defect, json.dumps(new_defects), memo, user.login_id, did))
    resp = http.saved(request, "검사일보를 고쳤습니다", data={"daily_id": did})
    audit.log_change(request, user, "F-INS-012", f"inspection_daily:{did}", f"검사 {new_insp} 불량 {new_defect}")
    return resp


# ── INS-020 검사일보출력 ──────────────────────────────────────────────────
@router.get(nav.path_of("INS-020"), response_class=HTMLResponse)
def daily_print(request: Request, user: rbac.User = rbac.require_screen("INS-020")):
    f = {"date": qs(request, "date") or date.today().isoformat()}
    rows = _rows(f)
    return templating.render(request, "ins/daily_print.html", {
        "rows": rows, "f": f, "defect_types": defect_types(), "totals": _sum(rows, "inspected_qty", "defect_qty")},
        screen_id="INS-020")


# ── INS-030 검사일보현황 ──────────────────────────────────────────────────
@router.get(nav.path_of("INS-030"), response_class=HTMLResponse)
def status(request: Request, user: rbac.User = rbac.require_screen("INS-030")):
    f = {k: qs(request, k) for k in ("from", "to", "item")}
    rows = _rows(f)
    return templating.render(request, "ins/status.html", {
        "rows": rows, "f": f, "defect_types": defect_types(), "totals": _sum(rows, "inspected_qty", "defect_qty")},
        screen_id="INS-030")


# ── INS-040 생산지시서 대비 검사 로스율 ──────────────────────────────────────
@router.get(nav.path_of("INS-040"), response_class=HTMLResponse)
def loss_rate(request: Request, user: rbac.User = rbac.require_screen("INS-040")):
    f = {k: qs(request, k) for k in ("from", "to", "wo")}
    d_from, d_to = date_in(f["from"], "시작일"), date_in(f["to"], "종료일")
    sql = """select w.id, w.work_order_no, w.qty as order_qty, w.status, i.item_code, i.item_name,
                    count(d.id) as days, sum(d.inspected_qty) as inspected_qty, sum(d.defect_qty) as defect_qty
               from work_order w join item i on i.id = w.item_id
               join inspection_daily d on d.work_order_id = w.id
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
    return templating.render(request, "ins/loss_rate.html", {"rows": rows, "f": f, "decision": "D-519"},
                             screen_id="INS-040")
