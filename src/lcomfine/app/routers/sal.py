"""sal 라우터 — 영업관리 (설계도 밖 확장 · D-418) · 담당 개발1.

설계도에는 영업·수주 메뉴가 없다. 사람 요청(2026-10-08)으로 이 회사의 다른 시스템에 있는 영업 화면(주문 조회 · 주문 현황 ·
거래처 이력)을 참고해 **수주 → 작업지시** 앞단을 만들었다. 설계도의 수(대메뉴 12 · 기능 94 · 권한 48칸 · 테이블 30)에는
들어가지 않고, 계약은 `contracts/extension-list.md`(ID `X-SAL-nn`)에 있다.

쓰는 테이블: `sales_order`(EXT) 뿐. Job 은 작업지시 등록·수정(F-JOB-01·02)이 `job.sales_order_id` 로 수주를 가리킨다 —
이 모듈은 `job` 에도 다른 어떤 설계도 테이블에도 쓰지 않는다. 수주의 진행(지시 · 생산 · 출하)은 저장하지 않고 D2 · D5 · D6 · D8 에서 센다.
권한: 영업관리 칸은 따로 없다 — 작업지시 관리 칸을 그대로 따른다(`nav.permission_from`, D-418).

  SAL-01 수주 관리   → /sal/orders     X-SAL-01 수주 등록 · 02 수정 · 03 취소 · 04 조회 (`?no=` 로 한 건)
  SAL-02 수주 현황   → /sal/status     X-SAL-05 수주별 지시 · 생산 · 출하 진행과 납기 지연 (읽기만)
  SAL-03 거래처 이력 → /sal/customers  X-SAL-06 고객별 수주 · 지시 · 출하 이력 (읽기만)
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.datastructures import FormData

from ...db import conn
from .. import nav, numbering, rbac, templating
from ..util import audit, http, screen
from .bas import bad, contains, decimal_of, form_data, int_of, text_of
from .job import date_of

router = APIRouter()

ORDERS, STATUS, CUSTOMERS = nav.path_of("SAL-01"), nav.path_of("SAL-02"), nav.path_of("SAL-03")
ST_OPEN, ST_CANCEL = "등록", "취소"
STATUSES = (ST_OPEN, ST_CANCEL)
JOB_CANCEL, JOB_DONE, WORK_DONE, SHIP_APPROVED = "취소", "완료", "완료", "승인"     # 설계도 테이블의 상태값 (db-schema.md §7)
LIST_LIMIT = 500
#: 진행 단계 표시 — 저장하지 않고 매번 센다
PROGRESS = ("미지시", "지시", "생산 중", "일부 출하", "출하 완료", "취소")

ORDER_SELECT = f"""
select so.sales_order_id, so.order_no, so.status, so.order_qty, so.qty_unit, so.order_date, so.due_date, so.customer_po, so.note,
       so.created_at, so.created_by, so.updated_at, so.updated_by, so.customer_id, so.item_id,
       c.customer_code, c.customer_name, i.item_code, i.item_name, i.spec as item_spec,
       (select count(*) from job j where j.sales_order_id = so.sales_order_id and j.status <> '{JOB_CANCEL}') as job_count,
       (select coalesce(sum(j.order_qty), 0) from job j
         where j.sales_order_id = so.sales_order_id and j.status <> '{JOB_CANCEL}') as job_qty,
       (select count(*) from job j where j.sales_order_id = so.sales_order_id and j.status = '{JOB_DONE}') as done_job_count,
       (select coalesce(sum(w.output_qty), 0) from work_result w join job j on j.job_id = w.job_id
         where j.sales_order_id = so.sales_order_id and w.status = '{WORK_DONE}') as output_qty,
       (select count(*) from roll r join job j on j.job_id = r.job_id where j.sales_order_id = so.sales_order_id) as roll_count,
       (select count(*) from shipment s join job j on j.job_id = s.job_id
         where j.sales_order_id = so.sales_order_id and s.status = '{SHIP_APPROVED}') as shipped_count,
       (select max(s.approved_at) from shipment s join job j on j.job_id = s.job_id
         where j.sales_order_id = so.sales_order_id and s.status = '{SHIP_APPROVED}') as last_shipped_at
  from sales_order so
  join customer c on c.customer_id = so.customer_id
  join item i on i.item_id = so.item_id
"""

# 기준정보 참조 — (폼 이름, 화면 이름, 테이블, pk, 코드 컬럼, 이름 컬럼, 선택 목록 조건)
REFS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("customer_id", "고객", "customer", "customer_id", "customer_code", "customer_name", ""),
    ("item_id", "품목", "item", "item_id", "item_code", "item_name", "item_type = '제품'"),
)


# ── 읽기 도우미 ─────────────────────────────────────────────────────────
def progress_of(row: dict) -> str:
    """수주의 진행 단계 — Job(D2) · 작업 실적(D5) · 출하(D8)에서 읽는다. 저장하지 않는다."""
    if row["status"] == ST_CANCEL:
        return "취소"
    if row["job_count"] == 0:
        return "미지시"
    if row["shipped_count"] > 0 and row["done_job_count"] == row["job_count"]:
        return "출하 완료"
    if row["shipped_count"] > 0:
        return "일부 출하"
    if row["output_qty"] > 0:
        return "생산 중"
    return "지시"


def is_late(row: dict, today: date) -> bool:
    """납기가 지났는데 승인된 출하가 없는 수주."""
    return row["status"] == ST_OPEN and row["due_date"] < today and row["shipped_count"] == 0


def decorate(rows: list[dict], today: date) -> list[dict]:
    for r in rows:
        r["progress"] = progress_of(r)
        r["late"] = is_late(r, today)
    return rows


def order_by_no(order_no: str) -> dict | None:
    return conn.q1(ORDER_SELECT + " where so.order_no = %s", (order_no,))


def order_of_path(order_no: str) -> dict:
    """경로에 박힌 수주 번호 — 없으면 404."""
    row = order_by_no(order_no)
    if row is None:
        raise http.not_found()
    return row


def order_of_input(order_no: str | None) -> dict:
    """사용자가 입력한 수주 번호 — 없으면 422 (api-contract.md §1 · D-201)."""
    row = order_by_no(order_no) if order_no else None
    if row is None:
        raise bad("없는 수주 번호입니다", "수주 번호", order_no or "비어 있습니다")
    return row


def ref_options(current: dict | None = None) -> dict[str, list[tuple[int, str]]]:
    """등록·수정 폼의 선택 목록 — 사용 중인 기준정보만. 수정 중인 수주가 가리키는 값은 `미사용` 이어도 남긴다."""
    out: dict[str, list[tuple[int, str]]] = {}
    for name, _label, table, pk, code, title, where in REFS:
        cond = f"use_yn = 'Y'{' and ' + where if where else ''}"
        rows = conn.q(f"select {pk} as id, {code} as code, {title} as name from {table} where {cond} order by {code}")
        opts = [(r["id"], f'{r["code"]} · {r["name"]}') for r in rows]
        cur_id = current.get(name) if current else None
        if cur_id is not None and all(v != cur_id for v, _ in opts):
            row = conn.q1(f"select {code} as code, {title} as name from {table} where {pk} = %s", (cur_id,))
            if row:
                opts.append((cur_id, f'{row["code"]} · {row["name"]} (미사용)'))
        out[name] = opts
    return out


def parse_ref(form: FormData, spec: tuple, *, creating: bool, required: bool) -> int | None:
    """기준정보 선택값 하나. 없는 ID · 미사용 항목(새로 고를 때) · 제품이 아닌 품목은 422."""
    name, label, table, pk, _code, _title, _where = spec
    ref_id = int_of(form, name, label, required=required)
    if ref_id is None:
        return None
    row = conn.q1(f"select * from {table} where {pk} = %s", (ref_id,))
    if row is None:
        raise bad("입력값을 확인해 주세요", label, "없는 항목입니다")
    if creating and row["use_yn"] != "Y":
        raise bad("입력값을 확인해 주세요", label, "미사용 항목입니다")
    if table == "item" and row["item_type"] != "제품":
        raise bad("입력값을 확인해 주세요", label, "제품 품목만 수주할 수 있습니다")
    return ref_id


def number_preview() -> str:
    return numbering.peek(numbering.SALES_ORDER) if numbering.rule(numbering.SALES_ORDER) else screen.undecided("D-418")


def can_of(user: rbac.User) -> dict[str, bool]:
    return {"create": user.can("X-SAL-01"), "update": user.can("X-SAL-02"), "cancel": user.can("X-SAL-03")}


# ── SAL-01 수주 관리 ────────────────────────────────────────────────────
@router.get(ORDERS, response_class=HTMLResponse)                     # X-SAL-04 수주 조회 = 화면 GET
def orders(request: Request, q: str = "", customer_id: str = "", item_id: str = "", status: str = "",
           due_from: str = "", due_to: str = "", no: str = "",
           user: rbac.User = rbac.require_fn("X-SAL-04")) -> HTMLResponse:
    where, params = ["true"], []
    if q.strip():
        where.append(f"({contains('so.order_no')} or {contains('so.customer_po')})")
        params += [q.strip(), q.strip()]
    if customer_id.strip().isdigit():
        where.append("so.customer_id = %s")
        params.append(int(customer_id))
    if item_id.strip().isdigit():
        where.append("so.item_id = %s")
        params.append(int(item_id))
    if status in STATUSES:
        where.append("so.status = %s")
        params.append(status)
    d_from, d_to = date_of(due_from, "납기 시작"), date_of(due_to, "납기 끝")
    if d_from:
        where.append("so.due_date >= %s")
        params.append(d_from)
    if d_to:
        where.append("so.due_date <= %s")
        params.append(d_to)
    rows = conn.q(f"{ORDER_SELECT} where {' and '.join(where)} order by so.created_at desc, so.sales_order_id desc "
                  f"limit {LIST_LIMIT + 1}", params)
    order = order_of_input(no.strip()) if no.strip() else None       # `?no=` 진입 — 없는 번호는 422
    today = date.today()
    return templating.render(request, "sal/orders.html", {
        "rows": decorate(rows[:LIST_LIMIT], today), "capped": len(rows) > LIST_LIMIT, "limit": LIST_LIMIT,
        "f": {"q": q, "customer_id": customer_id, "item_id": item_id, "status": status, "due_from": due_from, "due_to": due_to},
        "statuses": STATUSES, "order": decorate([order], today)[0] if order else None,
        "jobs": jobs_of(order["sales_order_id"]) if order else [],
        "options": ref_options(order), "search_options": ref_options(),
        "next_no": number_preview(), "today": today, "can": can_of(user),
        "ST_OPEN": ST_OPEN, "ST_CANCEL": ST_CANCEL,
    }, screen_id="SAL-01")


def jobs_of(sales_order_id: int) -> list[dict]:
    return conn.q("""select j.job_no, j.status, j.order_qty, j.qty_unit, j.due_date, j.created_at,
                            (select count(*) from work_result w where w.job_id = j.job_id) as work_count,
                            (select count(*) from roll r where r.job_id = j.job_id) as roll_count,
                            (select count(*) from shipment s where s.job_id = j.job_id and s.status = %s) as shipped_count
                       from job j where j.sales_order_id = %s order by j.job_id""", (SHIP_APPROVED, sales_order_id))


@router.post(ORDERS)                                                  # X-SAL-01 수주 등록
def create_order(request: Request, user: rbac.User = rbac.require_fn("X-SAL-01"),
                 form: FormData = Depends(form_data)):
    refs = {spec[0]: parse_ref(form, spec, creating=True, required=True) for spec in REFS}
    order_qty = decimal_of(form, "order_qty", "수주 수량", required=True, positive=True)
    qty_unit = text_of(form, "qty_unit", "수량 단위", max_len=20)
    if qty_unit is None:                                              # 단위를 안 주면 품목의 단위를 쓴다
        qty_unit = conn.q1("select unit from item where item_id = %s", (refs["item_id"],))["unit"]
    if not qty_unit:
        raise bad("필수값이 빠졌습니다", "수량 단위", "품목에 단위가 없어 직접 적어야 합니다")
    order_date = date_of(form.get("order_date"), "수주일") or date.today()
    due = date_of(form.get("due_date"), "납기", required=True)
    if due < order_date:
        raise bad("입력값을 확인해 주세요", "납기", f"수주일({order_date})보다 앞설 수 없습니다")
    customer_po = text_of(form, "customer_po", "고객 발주 번호", max_len=100)
    note = text_of(form, "note", "비고", max_len=1000)
    with conn.tx() as cur:
        order_no = numbering.next(numbering.SALES_ORDER, cur=cur)   # 번호와 행은 같이 성공하거나 같이 실패한다
        cur.execute("""insert into sales_order (order_no, customer_id, item_id, order_qty, qty_unit, order_date, due_date,
                                                customer_po, status, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning sales_order_id""",
                    (order_no, refs["customer_id"], refs["item_id"], order_qty, qty_unit, order_date, due, customer_po,
                     ST_OPEN, note, user.login_id))
        sales_order_id = cur.fetchone()["sales_order_id"]
    audit.log_change(request, user, "X-SAL-01", f"sales_order:{order_no}", "수주 등록")
    return http.saved(request, f"수주 {order_no} 을(를) 등록했습니다", back=f"{ORDERS}?no={order_no}",
                      data={"order_no": order_no, "sales_order_id": sales_order_id, "status": ST_OPEN})


@router.post(ORDERS + "/{order_no}")                                  # X-SAL-02 수주 수정
def update_order(request: Request, order_no: str, user: rbac.User = rbac.require_fn("X-SAL-02"),
                 form: FormData = Depends(form_data)):
    order = order_of_path(order_no)
    if order["status"] == ST_CANCEL:
        raise bad("취소된 수주는 수정할 수 없습니다", "상태", ST_CANCEL)
    sets: dict[str, Any] = {}
    for spec in REFS:
        if spec[0] in form:                                           # 폼에 없는 항목은 그대로 둔다
            sets[spec[0]] = parse_ref(form, spec, creating=False, required=True)
    if "order_qty" in form:
        sets["order_qty"] = decimal_of(form, "order_qty", "수주 수량", required=True, positive=True)
    if "qty_unit" in form:
        sets["qty_unit"] = text_of(form, "qty_unit", "수량 단위", required=True, max_len=20)
    if "order_date" in form:
        sets["order_date"] = date_of(form.get("order_date"), "수주일", required=True)
    if "due_date" in form:
        sets["due_date"] = date_of(form.get("due_date"), "납기", required=True)
    if "customer_po" in form:
        sets["customer_po"] = text_of(form, "customer_po", "고객 발주 번호", max_len=100)
    if "note" in form:
        sets["note"] = text_of(form, "note", "비고", max_len=1000)
    if "status" in form:
        raise bad("취소는 수주 취소 기능으로 합니다", "상태", str(form.get("status")))
    sets = {k: v for k, v in sets.items() if v != order[k]}           # 실제로 바뀌는 것만
    if not sets:
        raise http.validation_error("바꿀 값이 없습니다")
    if sets.get("due_date", order["due_date"]) < sets.get("order_date", order["order_date"]):
        raise bad("입력값을 확인해 주세요", "납기", "수주일보다 앞설 수 없습니다")
    # 작업지시가 걸린 뒤에는 고객·품목·수량을 못 바꾼다 — 지시는 수주의 값을 그대로 받았다
    locked = [label for key, label in (("customer_id", "고객"), ("item_id", "품목"), ("order_qty", "수주 수량"),
                                       ("qty_unit", "수량 단위")) if key in sets]
    if locked and order["job_count"] > 0:
        raise http.validation_error("작업지시가 걸린 수주는 고객·품목·수량을 바꿀 수 없습니다",
                                    fields=[{"name": n, "reason": f"작업지시 {order['job_count']}건"} for n in locked])
    assign = ", ".join(f"{c} = %s" for c in sets)
    conn.x(f"update sales_order set {assign}, updated_at = now(), updated_by = %s where sales_order_id = %s",
           (*sets.values(), user.login_id, order["sales_order_id"]))
    audit.log_change(request, user, "X-SAL-02", f"sales_order:{order_no}", "수주 수정 " + ", ".join(sets))
    return http.saved(request, f"수주 {order_no} 을(를) 수정했습니다", back=f"{ORDERS}?no={order_no}",
                      data={"order_no": order_no, "changed": sorted(sets)})


@router.post(ORDERS + "/{order_no}/cancel")                           # X-SAL-03 수주 취소
def cancel_order(request: Request, order_no: str, user: rbac.User = rbac.require_fn("X-SAL-03")):
    order = order_of_path(order_no)
    if order["status"] == ST_CANCEL:
        raise bad("이미 취소된 수주입니다", "상태", ST_CANCEL)
    if order["job_count"] > 0:
        raise http.validation_error("작업지시가 걸린 수주는 취소할 수 없습니다 — 작업지시를 먼저 취소합니다",
                                    fields=[{"name": "작업지시", "reason": f"{order['job_count']}건"}])
    conn.x("update sales_order set status = %s, updated_at = now(), updated_by = %s where sales_order_id = %s",
           (ST_CANCEL, user.login_id, order["sales_order_id"]))
    audit.log_change(request, user, "X-SAL-03", f"sales_order:{order_no}", "수주 취소")
    return http.saved(request, f"수주 {order_no} 을(를) 취소했습니다", back=f"{ORDERS}?no={order_no}",
                      data={"order_no": order_no, "status": ST_CANCEL})


# ── SAL-02 수주 현황 ────────────────────────────────────────────────────
@router.get(STATUS, response_class=HTMLResponse)                     # X-SAL-05 수주 현황 조회 = 화면 GET
def status_page(request: Request, customer_id: str = "", progress: str = "", late: str = "",
                due_from: str = "", due_to: str = "",
                user: rbac.User = rbac.require_fn("X-SAL-05")) -> HTMLResponse:
    where, params = ["so.status = %s"], [ST_OPEN]
    if customer_id.strip().isdigit():
        where.append("so.customer_id = %s")
        params.append(int(customer_id))
    d_from, d_to = date_of(due_from, "납기 시작"), date_of(due_to, "납기 끝")
    if d_from:
        where.append("so.due_date >= %s")
        params.append(d_from)
    if d_to:
        where.append("so.due_date <= %s")
        params.append(d_to)
    today = date.today()
    rows = decorate(conn.q(f"{ORDER_SELECT} where {' and '.join(where)} order by so.due_date, so.sales_order_id "
                           f"limit {LIST_LIMIT + 1}", params), today)
    capped = len(rows) > LIST_LIMIT
    rows = rows[:LIST_LIMIT]
    if progress in PROGRESS:
        rows = [r for r in rows if r["progress"] == progress]
    if late == "1":
        rows = [r for r in rows if r["late"]]
    totals = {
        "count": len(rows), "late": sum(1 for r in rows if r["late"]),
        "by_progress": {p: sum(1 for r in rows if r["progress"] == p) for p in PROGRESS if p != "취소"},
        "order_qty": sum(r["order_qty"] for r in rows), "job_qty": sum(r["job_qty"] for r in rows),
        "output_qty": sum(r["output_qty"] for r in rows), "units": sorted({r["qty_unit"] for r in rows}),
    }
    return templating.render(request, "sal/status.html", {
        "rows": rows, "capped": capped, "limit": LIST_LIMIT, "totals": totals, "today": today,
        "f": {"customer_id": customer_id, "progress": progress, "late": late, "due_from": due_from, "due_to": due_to},
        "progress_values": [p for p in PROGRESS if p != "취소"], "search_options": ref_options(),
    }, screen_id="SAL-02")


# ── SAL-03 거래처 이력 ──────────────────────────────────────────────────
@router.get(CUSTOMERS, response_class=HTMLResponse)                  # X-SAL-06 거래처 이력 조회 = 화면 GET
def customers_page(request: Request, q: str = "", date_from: str = "", date_to: str = "",
                   user: rbac.User = rbac.require_fn("X-SAL-06")) -> HTMLResponse:
    d_from, d_to = date_of(date_from, "기간 시작"), date_of(date_to, "기간 끝")
    if d_from and d_to and d_from > d_to:
        raise bad("입력값을 확인해 주세요", "기간", "시작이 끝보다 늦습니다")
    params = {"from": d_from, "to": d_to, "q": q.strip(), "cancel": JOB_CANCEL, "approved": SHIP_APPROVED}
    rows = conn.q(f"""
        select c.customer_id, c.customer_code, c.customer_name, c.use_yn,
               count(so.sales_order_id) filter (where so.status <> %(cancel)s) as order_count,
               coalesce(sum(so.order_qty) filter (where so.status <> %(cancel)s), 0) as order_qty,
               count(distinct so.qty_unit) filter (where so.status <> %(cancel)s) as unit_count,
               max(so.order_date) as last_order_date,
               (select count(*) from job j where j.customer_id = c.customer_id and j.status <> %(cancel)s
                   and (%(from)s::date is null or j.created_at::date >= %(from)s) and (%(to)s::date is null or j.created_at::date <= %(to)s)) as job_count,
               (select count(*) from shipment s where s.customer_id = c.customer_id and s.status = %(approved)s
                   and (%(from)s::date is null or s.ship_date >= %(from)s) and (%(to)s::date is null or s.ship_date <= %(to)s)) as shipment_count,
               (select max(s.ship_date) from shipment s where s.customer_id = c.customer_id and s.status = %(approved)s) as last_ship_date
          from customer c
          left join sales_order so on so.customer_id = c.customer_id
               and (%(from)s::date is null or so.order_date >= %(from)s) and (%(to)s::date is null or so.order_date <= %(to)s)
         where (%(q)s = '' or {contains('c.customer_name').replace('%s', '%(q)s')} or {contains('c.customer_code').replace('%s', '%(q)s')})
         group by c.customer_id order by c.customer_code limit {LIST_LIMIT + 1}""", params)
    totals = {"customers": min(len(rows), LIST_LIMIT), "order_count": sum(r["order_count"] for r in rows[:LIST_LIMIT]),
              "job_count": sum(r["job_count"] for r in rows[:LIST_LIMIT]),
              "shipment_count": sum(r["shipment_count"] for r in rows[:LIST_LIMIT])}
    return templating.render(request, "sal/customers.html", {
        "rows": rows[:LIST_LIMIT], "capped": len(rows) > LIST_LIMIT, "limit": LIST_LIMIT, "totals": totals,
        "f": {"q": q, "date_from": date_from, "date_to": date_to},
    }, screen_id="SAL-03")
