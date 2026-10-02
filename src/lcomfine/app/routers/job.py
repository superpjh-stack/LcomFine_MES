"""job 라우터 — 작업지시 관리 (기능 7) · 담당 개발1.

쓰는 저장소: D2 (`job` `job_lot`). 이 밖의 테이블에는 쓰지 않는다(G-05) — 원재료 LOT·롤을 미리 묶지 않는다(D-10).
읽는 것: D1(기준정보) · D5(작업 실적이 있는가 — 진행 여부는 저장하지 않는다) · D6·D8(매핑 조회의 실제 롤과 출하 LOT).

Job 번호·생산 LOT 번호는 `numbering.next` 만 만든다(G-08). 경로의 키는 내부 ID 가 아니라 Job 번호다(D-21) —
작업지시서의 바코드를 스캔칸에 넣으면 `?no=<Job 번호>` 로 그 Job 이 열린다.

담당 화면과 기능 (contracts/function-list.md)
  JOB-01 작업지시 → /job/orders
      F-JOB-01 작업지시 등록 [등록] POST /job/orders
      F-JOB-02 작업지시 수정 [수정] POST /job/orders/{job_no}
      F-JOB-03 작업지시 취소 [삭제] POST /job/orders/{job_no}/cancel
      F-JOB-04 작업지시 조회 [조회] GET /job/orders
      F-JOB-05 작업지시서 출력 [출력] GET /job/orders/{job_no}/print
  JOB-02 Job-Lot-Roll 매핑 → /job/mapping
      F-JOB-06 Job-Lot-Roll 매핑 등록 [등록] POST /job/mapping
      F-JOB-07 Job-Lot-Roll 매핑 조회 [조회] GET /job/mapping
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.datastructures import FormData

from ...db import conn
from .. import nav, numbering, printing, rbac, templating
from ..util import audit, http, screen
from .bas import bad, contains, decimal_of, form_data, int_of, text_of

router = APIRouter()

ORDERS, MAPPING = nav.path_of("JOB-01"), nav.path_of("JOB-02")
ST_OPEN, ST_DONE, ST_CANCEL = "등록", "완료", "취소"
STATUSES = (ST_OPEN, ST_DONE, ST_CANCEL)
WORK_DONE = "완료"            # `work_result.status` — 진행 ⇄ 정지 → 완료 (db-schema.md §7). 이 값이 아니면 아직 열려 있는 실적이다
LIST_LIMIT = 500

# 기준정보 참조 — (폼 이름, 화면 이름, 테이블, pk, 코드 컬럼, 이름 컬럼, 필수, 선택 목록 조건)
REFS: tuple[tuple[str, str, str, str, str, str, bool, str], ...] = (
    ("item_id", "품목", "item", "item_id", "item_code", "item_name", True, "item_type = '제품'"),
    ("customer_id", "고객", "customer", "customer_id", "customer_code", "customer_name", True, ""),
    ("plate_spec_id", "판사양", "plate_spec", "plate_spec_id", "plate_code", "plate_name", False, ""),
    ("anilox_id", "아니록스", "anilox", "anilox_id", "anilox_code", "anilox_name", False, ""),
    ("ink_formula_id", "잉크조성", "ink_formula", "ink_formula_id", "ink_code", "ink_name", False, ""),
    ("equipment_id", "계획 설비", "equipment", "equipment_id", "equipment_code", "equipment_name", False, ""),
)

JOB_SELECT = """
select j.job_id, j.job_no, j.status, j.order_qty, j.qty_unit, j.due_date, j.note,
       j.created_at, j.created_by, j.updated_at, j.updated_by,
       j.item_id, j.customer_id, j.plate_spec_id, j.anilox_id, j.ink_formula_id, j.equipment_id,
       i.item_code, i.item_name, i.spec as item_spec, c.customer_code, c.customer_name,
       p.plate_code, p.plate_name, p.color_count, p.spec_note,
       a.anilox_code, a.anilox_name, a.line_count, a.cell_volume,
       k.ink_code, k.ink_name, k.color_name, k.target_l, k.target_a, k.target_b,
       e.equipment_code, e.equipment_name,
       (select count(*) from work_result w where w.job_id = j.job_id) as work_count,
       (select count(*) from work_result w where w.job_id = j.job_id and w.status <> '완료') as open_work_count,
       (select count(*) from roll r where r.job_id = j.job_id) as roll_count,
       (select count(*) from job_lot l where l.job_id = j.job_id) as lot_count
  from job j
  join item i on i.item_id = j.item_id
  join customer c on c.customer_id = j.customer_id
  left join plate_spec p on p.plate_spec_id = j.plate_spec_id
  left join anilox a on a.anilox_id = j.anilox_id
  left join ink_formula k on k.ink_formula_id = j.ink_formula_id
  left join equipment e on e.equipment_id = j.equipment_id
"""


# ── 읽기 도우미 ─────────────────────────────────────────────────────────
def job_by_no(job_no: str) -> dict | None:
    return conn.q1(JOB_SELECT + " where j.job_no = %s", (job_no,))


def job_of_path(job_no: str) -> dict:
    """경로에 박힌 Job 번호 — 없으면 404."""
    row = job_by_no(job_no)
    if row is None:
        raise http.not_found()
    return row


def job_of_input(job_no: str | None) -> dict:
    """사용자가 입력하거나 스캔한 Job 번호 — 없으면 422 (api-contract.md §1)."""
    row = job_by_no(job_no) if job_no else None
    if row is None:
        raise bad("없는 Job 번호입니다", "Job 번호", job_no or "비어 있습니다")
    return row


def lock_job(cur, job_id: int) -> None:
    """Job 행을 잠근다 — 마감·취소를 판정하고 상태를 바꾸는 동안 그 Job 에 작업 실적·롤이 새로 붙지 못한다.

    실적·롤을 넣는 쪽은 `job` 을 가리키는 FK 검사로 이 행에 `for key share` 를 건다. `for update` 는 그것과 부딪히므로
    아직 커밋되지 않은 실적·롤이 있으면 그 트랜잭션이 끝날 때까지 기다린 뒤에 센다(읽기만 한다 — D5·D6 에 쓰지 않는다)."""
    cur.execute("select job_id from job where job_id = %s for update", (job_id,))


def open_works(cur, job_id: int) -> list[dict]:
    """종료되지 않은(`진행`·`정지`) 작업 실적 — 이것이 있는 Job 은 마감하지 못한다(D-107)."""
    cur.execute("""select w.work_result_id, w.status, w.started_at, w.worker
                     from work_result w where w.job_id = %s and w.status <> %s order by w.work_result_id""",
                (job_id, WORK_DONE))
    return cur.fetchall()


def lots_of(job_id: int) -> list[dict]:
    return conn.q("""select l.job_lot_id, l.lot_no, l.planned_roll_count, l.planned_length_m, l.note, l.created_at,
                            (select count(*) from roll r where r.job_lot_id = l.job_lot_id) as roll_count
                       from job_lot l where l.job_id = %s order by l.job_lot_id""", (job_id,))


def ref_options(current: dict | None = None) -> dict[str, list[tuple[int, str]]]:
    """등록·수정 폼의 선택 목록 — 사용 중인 기준정보만. 수정 중인 Job 이 가리키는 값은 `미사용` 이어도 남긴다."""
    out: dict[str, list[tuple[int, str]]] = {}
    for name, _label, table, pk, code, title, _req, where in REFS:
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


def date_of(value: str | None, label: str, *, required: bool = False) -> date | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise bad("필수값이 빠졌습니다", label, "필수값입니다")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad("입력값을 확인해 주세요", label, f"날짜(YYYY-MM-DD)가 아닙니다: {value}") from None


def parse_ref(form: FormData, spec: tuple, *, creating: bool) -> int | None:
    """기준정보 선택값 하나. 없는 ID · 미사용 항목(새로 고를 때) · 제품이 아닌 품목은 422."""
    name, label, table, pk, _code, _title, required, _where = spec
    ref_id = int_of(form, name, label, required=required)
    if ref_id is None:
        return None
    row = conn.q1(f"select * from {table} where {pk} = %s", (ref_id,))
    if row is None:
        raise bad("입력값을 확인해 주세요", label, "없는 항목입니다")
    if creating and row["use_yn"] != "Y":
        raise bad("입력값을 확인해 주세요", label, "미사용 항목입니다")
    if table == "item" and row["item_type"] != "제품":
        raise bad("입력값을 확인해 주세요", label, "제품 품목만 지시할 수 있습니다")
    return ref_id


def number_preview(kind: str) -> str:
    """등록 폼의 번호 미리보기. 형식 행이 없으면 `미확정 (D-05)`."""
    return numbering.peek(kind) if numbering.rule(kind) else screen.undecided("D-05")


# ── JOB-01 작업지시 ─────────────────────────────────────────────────────
@router.get(ORDERS, response_class=HTMLResponse)                     # F-JOB-04 작업지시 조회 = 화면 GET
def orders(request: Request, q: str = "", item_id: str = "", customer_id: str = "", status: str = "",
           due_from: str = "", due_to: str = "", no: str = "",
           user: rbac.User = rbac.require_fn("F-JOB-04")) -> HTMLResponse:
    where, params = ["true"], []
    if q.strip():
        where.append(contains("j.job_no"))
        params.append(q.strip())
    if item_id.strip().isdigit():
        where.append("j.item_id = %s")
        params.append(int(item_id))
    if customer_id.strip().isdigit():
        where.append("j.customer_id = %s")
        params.append(int(customer_id))
    if status in STATUSES:
        where.append("j.status = %s")
        params.append(status)
    d_from, d_to = date_of(due_from, "납기 시작"), date_of(due_to, "납기 끝")
    if d_from:
        where.append("j.due_date >= %s")
        params.append(d_from)
    if d_to:
        where.append("j.due_date <= %s")
        params.append(d_to)
    rows = conn.q(f"{JOB_SELECT} where {' and '.join(where)} order by j.created_at desc, j.job_id desc "
                  f"limit {LIST_LIMIT + 1}", params)
    job = job_of_input(no.strip()) if no.strip() else None            # `?no=` 스캔 진입 — 없는 번호는 422
    return templating.render(request, "job/orders.html", {
        "rows": rows[:LIST_LIMIT], "capped": len(rows) > LIST_LIMIT, "limit": LIST_LIMIT,
        "f": {"q": q, "item_id": item_id, "customer_id": customer_id, "status": status,
              "due_from": due_from, "due_to": due_to},
        "statuses": STATUSES, "job": job, "lots": lots_of(job["job_id"]) if job else [],
        "options": ref_options(job), "search_options": ref_options(),
        "next_no": number_preview(numbering.JOB),
        "can": {"create": user.can("F-JOB-01"), "update": user.can("F-JOB-02"), "cancel": user.can("F-JOB-03")},
        "ST_OPEN": ST_OPEN, "ST_DONE": ST_DONE, "ST_CANCEL": ST_CANCEL,
    }, screen_id="JOB-01")


@router.post(ORDERS)                                                  # F-JOB-01 작업지시 등록
def create_order(request: Request, user: rbac.User = rbac.require_fn("F-JOB-01"),
                 form: FormData = Depends(form_data)):
    refs = {spec[0]: parse_ref(form, spec, creating=True) for spec in REFS}
    order_qty = decimal_of(form, "order_qty", "지시 수량", required=True, positive=True)
    due = date_of(form.get("due_date"), "납기", required=True)
    qty_unit = text_of(form, "qty_unit", "수량 단위", max_len=20)
    if qty_unit is None:                                              # 단위를 안 주면 품목의 단위를 쓴다
        qty_unit = conn.q1("select unit from item where item_id = %s", (refs["item_id"],))["unit"]
    if not qty_unit:
        raise bad("필수값이 빠졌습니다", "수량 단위", "품목에 단위가 없어 직접 적어야 합니다")
    note = text_of(form, "note", "비고", max_len=1000)
    with conn.tx() as cur:
        job_no = numbering.next(numbering.JOB, cur=cur)               # 번호와 Job 행은 같이 성공하거나 같이 실패한다
        cur.execute("""insert into job (job_no, item_id, customer_id, plate_spec_id, anilox_id, ink_formula_id,
                                        equipment_id, order_qty, qty_unit, due_date, status, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning job_id""",
                    (job_no, refs["item_id"], refs["customer_id"], refs["plate_spec_id"], refs["anilox_id"],
                     refs["ink_formula_id"], refs["equipment_id"], order_qty, qty_unit, due, ST_OPEN, note,
                     user.login_id))
        job_id = cur.fetchone()["job_id"]
    audit.log_change(request, user, "F-JOB-01", f"job:{job_no}", "작업지시 등록")
    return http.saved(request, f"작업지시 {job_no} 을(를) 등록했습니다", back=f"{ORDERS}?no={job_no}",
                      data={"job_no": job_no, "job_id": job_id, "status": ST_OPEN})


@router.post(ORDERS + "/{job_no}")                                    # F-JOB-02 작업지시 수정
def update_order(request: Request, job_no: str, user: rbac.User = rbac.require_fn("F-JOB-02"),
                 form: FormData = Depends(form_data)):
    job = job_of_path(job_no)
    if job["status"] == ST_CANCEL:
        raise bad("취소된 작업지시는 수정할 수 없습니다", "상태", ST_CANCEL)
    sets: dict[str, Any] = {}
    for spec in REFS:
        if spec[0] in form:                                           # 폼에 없는 항목은 그대로 둔다
            sets[spec[0]] = parse_ref(form, spec, creating=False)
    if "order_qty" in form:
        sets["order_qty"] = decimal_of(form, "order_qty", "지시 수량", required=True, positive=True)
    if "qty_unit" in form:
        sets["qty_unit"] = text_of(form, "qty_unit", "수량 단위", required=True, max_len=20)
    if "due_date" in form:
        sets["due_date"] = date_of(form.get("due_date"), "납기", required=True)
    if "note" in form:
        sets["note"] = text_of(form, "note", "비고", max_len=1000)
    if "status" in form:
        status = text_of(form, "status", "상태", required=True)
        if status == ST_CANCEL:
            raise bad("취소는 작업지시 취소 기능으로 합니다", "상태", status)
        if status not in (ST_OPEN, ST_DONE):
            raise bad("입력값을 확인해 주세요", "상태", f"{ST_OPEN} 또는 {ST_DONE} 이어야 합니다: {status}")
        sets["status"] = status
    sets = {k: v for k, v in sets.items() if v != job[k]}             # 실제로 바뀌는 것만
    if not sets:
        raise http.validation_error("바꿀 값이 없습니다")
    # 작업 실적이 생긴 뒤에는 품목·수량을 못 바꾼다. 진행 여부는 저장하지 않고 D5 에서 읽는다
    locked = [label for key, label in (("item_id", "품목"), ("order_qty", "지시 수량"), ("qty_unit", "수량 단위")) if key in sets]
    if locked and job["work_count"] > 0:
        raise http.validation_error("작업 실적이 있는 작업지시는 품목·수량을 바꿀 수 없습니다",
                                    fields=[{"name": n, "reason": f"작업 실적 {job['work_count']}건"} for n in locked])
    assign = ", ".join(f"{c} = %s" for c in sets)
    with conn.tx() as cur:
        if sets.get("status") == ST_DONE:
            # 열린 실적이 있는 채로 마감하면, 그 실적을 종료할 때(F-POP-02) 마감된 Job 에 인쇄 롤이 생긴다.
            # 종료 쪽에서 막으면 열린 실적을 닫을 길이 없으므로 마감 쪽에서 막는다 (D-107 · D-208)
            lock_job(cur, job["job_id"])
            still_open = open_works(cur, job["job_id"])
            if still_open:
                raise http.validation_error(
                    "진행 중인 작업 실적이 있는 작업지시는 마감할 수 없습니다 — 작업을 종료한 뒤 마감합니다",
                    fields=[{"name": f"작업 실적 {w['work_result_id']}",
                             "reason": f"{w['status']} · 시작 {screen.dt(w['started_at'])} · 작업자 {w['worker']}"}
                            for w in still_open])
        cur.execute(f"update job set {assign}, updated_at = now(), updated_by = %s where job_id = %s",
                    [*sets.values(), user.login_id, job["job_id"]])
    changed = " · ".join(sets)
    audit.log_change(request, user, "F-JOB-02", f"job:{job_no}", f"작업지시 수정 ({changed})")
    return http.saved(request, f"작업지시 {job_no} 을(를) 수정했습니다", back=f"{ORDERS}?no={job_no}",
                      data={"job_no": job_no, "status": sets.get("status", job["status"])})


@router.post(ORDERS + "/{job_no}/cancel")                             # F-JOB-03 작업지시 취소
def cancel_order(request: Request, job_no: str, user: rbac.User = rbac.require_fn("F-JOB-03")):
    job = job_of_path(job_no)
    if job["status"] == ST_CANCEL:
        raise bad("이미 취소된 작업지시입니다", "상태", ST_CANCEL)
    with conn.tx() as cur:
        lock_job(cur, job["job_id"])                                  # 세는 것과 바꾸는 것을 한 트랜잭션에 — 그 사이에 실적이 끼어들지 못한다
        cur.execute("""select (select count(*) from work_result w where w.job_id = %(id)s) as work_count,
                              (select count(*) from roll r where r.job_id = %(id)s) as roll_count""", {"id": job["job_id"]})
        now = cur.fetchone()                                          # 종료 여부와 무관하다 — 진행 중인 실적 하나만 있어도 취소하지 못한다
        used = [{"name": name, "reason": f"{n}건"} for name, n in (("작업 실적", now["work_count"]), ("롤", now["roll_count"])) if n]
        if used:
            raise http.validation_error("작업 실적이나 롤이 있는 작업지시는 취소할 수 없습니다", fields=used)
        cur.execute("update job set status = %s, updated_at = now(), updated_by = %s where job_id = %s",
                    (ST_CANCEL, user.login_id, job["job_id"]))        # 행은 지우지 않는다 (D-21)
    audit.log_change(request, user, "F-JOB-03", f"job:{job_no}", "작업지시 취소")
    return http.saved(request, f"작업지시 {job_no} 을(를) 취소했습니다", back=f"{ORDERS}?no={job_no}",
                      data={"job_no": job_no, "status": ST_CANCEL})


@router.get(ORDERS + "/{job_no}/print", response_class=HTMLResponse)  # F-JOB-05 작업지시서 출력
def print_order(request: Request, job_no: str, user: rbac.User = rbac.require_fn("F-JOB-05")) -> HTMLResponse:
    job = job_of_path(job_no)
    components = conn.q("""select seq_no, component_name, ratio_pct from ink_formula_component
                            where ink_formula_id = %s order by seq_no""", (job["ink_formula_id"],)) if job["ink_formula_id"] else []
    return templating.render(request, "job/print.html", {
        "job": job, "lots": lots_of(job["job_id"]), "components": components,
        "barcode": printing.barcode_svg(job["job_no"]),               # 바코드가 담는 값 = Job 번호 글자 그대로 (G-14)
    }, screen_id="JOB-01")


# ── JOB-02 Job-Lot-Roll 매핑 ────────────────────────────────────────────
@router.get(MAPPING, response_class=HTMLResponse)                     # F-JOB-07 매핑 조회 = 화면 GET (읽기만 한다)
def mapping(request: Request, no: str = "", lot: str = "", q: str = "",
            user: rbac.User = rbac.require_fn("F-JOB-07")) -> HTMLResponse:
    job = job_of_input(no.strip()) if no.strip() else None
    lots: list[dict] = []
    rolls: list[dict] = []
    editing = None
    if job:
        lots = lots_of(job["job_id"])
        rolls = conn.q("""select r.roll_id, r.roll_no, r.process_type, r.length_m, r.width_mm, r.slit_seq, r.produced_at,
                                 l.lot_no, v.state, s.shipment_no, s.status as shipment_status
                            from roll r
                            join v_roll_state v on v.roll_id = r.roll_id
                            left join job_lot l on l.job_lot_id = r.job_lot_id
                            left join shipment s on s.shipment_id = v.shipment_id
                           where r.job_id = %s
                           order by l.lot_no nulls last, r.roll_id""", (job["job_id"],))
        if lot.strip():
            editing = next((x for x in lots if x["lot_no"] == lot.strip()), None)
            if editing is None:
                raise bad("이 Job 의 생산 LOT 이 아닙니다", "생산 LOT 번호", lot.strip())
    where, params = ["true"], []
    if q.strip():
        where.append(contains("j.job_no"))
        params.append(q.strip())
    jobs = conn.q(f"""select j.job_no, j.status, j.due_date, i.item_code, i.item_name,
                             (select count(*) from job_lot l where l.job_id = j.job_id) as lot_count,
                             (select coalesce(sum(l.planned_roll_count), 0) from job_lot l where l.job_id = j.job_id) as planned_rolls,
                             (select count(*) from roll r where r.job_id = j.job_id) as roll_count,
                             (select count(*) from shipment s where s.job_id = j.job_id and s.status <> '취소') as shipment_count
                        from job j join item i on i.item_id = j.item_id
                       where {' and '.join(where)}
                       order by j.created_at desc, j.job_id desc limit {LIST_LIMIT + 1}""", params)
    return templating.render(request, "job/mapping.html", {
        "job": job, "lots": lots, "rolls": rolls, "editing": editing, "jobs": jobs[:LIST_LIMIT],
        "capped": len(jobs) > LIST_LIMIT, "limit": LIST_LIMIT, "f": {"no": no, "q": q},
        "next_no": number_preview(numbering.JOB_LOT), "can": {"write": user.can("F-JOB-06")},
        "ST_OPEN": ST_OPEN,
    }, screen_id="JOB-02")


@router.post(MAPPING)                                                 # F-JOB-06 매핑 등록 (같은 요청으로 계획값 수정)
def save_mapping(request: Request, user: rbac.User = rbac.require_fn("F-JOB-06"),
                 form: FormData = Depends(form_data)):
    job = job_of_input(text_of(form, "job_no", "Job 번호", required=True, max_len=50))
    lot_no = text_of(form, "lot_no", "생산 LOT 번호", max_len=50)
    planned_rolls = int_of(form, "planned_roll_count", "계획 롤 수", positive=True)
    planned_length = decimal_of(form, "planned_length_m", "계획 길이 (m)", positive=True)
    note = text_of(form, "note", "비고", max_len=1000)
    if job["status"] != ST_OPEN:
        raise bad(f"{job['status']} 상태의 작업지시에는 생산 LOT 을 붙이거나 계획을 바꿀 수 없습니다", "상태", job["status"])
    back = f"{MAPPING}?no={job['job_no']}"
    if lot_no:                                                        # 계획값 수정
        lot = conn.q1("select job_lot_id, job_id from job_lot where lot_no = %s", (lot_no,))
        if lot is None or lot["job_id"] != job["job_id"]:
            raise bad("이 Job 의 생산 LOT 이 아닙니다", "생산 LOT 번호", lot_no)
        sets: dict[str, Any] = {}
        if "planned_roll_count" in form:
            sets["planned_roll_count"] = planned_rolls
        if "planned_length_m" in form:
            sets["planned_length_m"] = planned_length
        if "note" in form:
            sets["note"] = note
        if not sets:
            raise http.validation_error("바꿀 값이 없습니다")
        assign = ", ".join(f"{c} = %s" for c in sets)
        conn.x(f"update job_lot set {assign}, updated_at = now(), updated_by = %s where job_lot_id = %s",
               [*sets.values(), user.login_id, lot["job_lot_id"]])
        audit.log_change(request, user, "F-JOB-06", f"job_lot:{lot_no}", f"매핑 계획 수정 (Job {job['job_no']})")
        return http.saved(request, f"생산 LOT {lot_no} 의 계획을 수정했습니다", back=back,
                          data={"job_no": job["job_no"], "lot_no": lot_no, "created": False})
    with conn.tx() as cur:
        lot_no = numbering.next(numbering.JOB_LOT, cur=cur)
        cur.execute("""insert into job_lot (job_id, lot_no, planned_roll_count, planned_length_m, note, created_by)
                       values (%s, %s, %s, %s, %s, %s)""",
                    (job["job_id"], lot_no, planned_rolls, planned_length, note, user.login_id))
    audit.log_change(request, user, "F-JOB-06", f"job_lot:{lot_no}", f"매핑 등록 (Job {job['job_no']})")
    return http.saved(request, f"생산 LOT {lot_no} 을(를) Job {job['job_no']} 에 붙였습니다", back=back,
                      data={"job_no": job["job_no"], "lot_no": lot_no, "created": True})
