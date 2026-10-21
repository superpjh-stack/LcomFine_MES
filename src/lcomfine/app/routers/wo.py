"""WO 작업지시 — 생산의뢰서(WO-010) · 생산지시서(WO-020) · 생산순서관리(WO-030) · 공정상태(WO-040). 담당 개발1.

의뢰가 IA 전체의 「수주」이고 의뢰번호가 지시 → 일보 → 제품 입고 → 출하의 연결 키다.
번호는 `numbering.next` 만(형식 D-509), 알림은 같은 트랜잭션에서 `notify.emit`(D-511). 상태값 · 대기 조건 공표는 progress-dev1 §1.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, notify, numbering, rbac, templating
from ..util import audit, http, screen
from .bas import (bad, choice, day, edit_row, exists_or_404, item_choice, items_for_select, like, pk, qty, ref_id, s)
from .std import data_uri

router = APIRouter()

REQUEST_STATUSES = ("확인대기", "확정", "지시완료", "취소")
REQUEST_EDITABLE = ("확인대기", "확정", "취소")          # 지시완료는 지시서 작성이 바꾼다
ORDER_STATUSES = ("발행", "진행", "완료", "취소")
ORDER_ACTIVE = ("발행", "진행")
REQUEST_ORDERABLE = ("확인대기", "확정", "지시완료")


def request_link(request_no: str) -> str:
    """`request_created` 알림의 link — 수신 PR · DS 가 둘 다 볼 수 있는 의뢰 화면(WO-010) (progress-dev1 §1.3)."""
    return f"{nav.path_of('WO-010')}?q={request_no}"


def order_link(work_order_no: str) -> str:
    """`order_issued` 알림의 link — 불출(MAT-020)."""
    return f"{nav.path_of('MAT-020')}?wo={work_order_no}"


def number_preview(kind: str) -> str:
    """등록 화면의 다음 번호 미리보기. 형식 행이 없으면 `미확정 (D-509)`."""
    if numbering.rule(kind) is None:
        return screen.undecided("D-509")
    return f"{numbering.peek(kind)} (형식 예시 · D-509)"


def customers_for_select() -> list[dict]:
    return conn.q("select id, customer_code, customer_name from customer where use_yn = 'Y' order by customer_code")


def equipment_codes() -> list[dict]:
    return conn.q("select code, code_name from sys_common_code where group_code = '설비' and use_yn = 'Y' "
                  "order by sort_no, code")


def _customer(cur, cid: int, *, allow_inactive_id: int | None = None) -> dict:
    cur.execute("select id, customer_code, use_yn from customer where id = %s", (cid,))
    row = cur.fetchone()
    if row is None:
        raise bad("거래처", "없는 거래처입니다")
    if row["use_yn"] != "Y" and row["id"] != allow_inactive_id:
        raise bad("거래처", f"사용 중지 거래처는 고를 수 없습니다 ({row['customer_code']})")
    return row


def _equipment(cur, code: str | None, *, allow: str | None = None) -> str | None:
    if code is None:
        return None
    cur.execute("select use_yn from sys_common_code where group_code = '설비' and code = %s", (code,))
    row = cur.fetchone()
    if row is None:
        raise bad("설비", f"공통코드(설비)에 없는 코드입니다 ({code})")
    if row["use_yn"] != "Y" and code != allow:
        raise bad("설비", f"사용 중지 설비입니다 ({code})")
    return code


# ── WO-010 생산의뢰서 ───────────────────────────────────────────────────
@router.get(nav.path_of("WO-010"), response_class=HTMLResponse)
def requests(request: Request, q: str | None = None, customer: str | None = None, status: str | None = None,
             due_from: str | None = None, due_to: str | None = None, edit: str | None = None,
             user: rbac.User = rbac.require_screen("WO-010")):
    """F-WO-013 — 의뢰 목록 · 의뢰번호·거래처·납기로 검색."""
    rows = conn.q(
        """select r.id, r.request_no, r.request_date, r.customer_id, c.customer_code, c.customer_name, r.item_id,
                  i.item_code, i.item_name, r.qty, r.due_date, r.status, r.note, r.created_by,
                  (r.due_date - current_date) as d_day,
                  (select count(*) from work_order w where w.request_id = r.id and w.status <> '취소') as order_count,
                  coalesce((select sum(v.shipped_qty) from v_work_order_status v where v.request_id = r.id), 0) as shipped_qty
             from production_request r
             join customer c on c.id = r.customer_id
             join item i on i.id = r.item_id
            where (%(q)s::text is null or r.request_no ilike %(q)s or c.customer_name ilike %(q)s
                   or c.customer_code ilike %(q)s or i.item_code ilike %(q)s or i.item_name ilike %(q)s)
              and (%(cu)s::bigint is null or r.customer_id = %(cu)s)
              and (%(st)s::text is null or r.status = %(st)s)
              and (%(df)s::date is null or r.due_date >= %(df)s)
              and (%(dt)s::date is null or r.due_date <= %(dt)s)
            order by r.id desc limit 1000""",
        {"q": like(q), "cu": ref_id(customer, "거래처", required=False),
         "st": choice(status, "상태", REQUEST_STATUSES, required=False),
         "df": day(due_from, "납기 시작", required=False), "dt": day(due_to, "납기 끝", required=False)})
    return templating.render(request, "wo/requests.html",
                             {"rows": rows, "edit": edit_row("production_request", edit),
                              "customers": customers_for_select(), "items": items_for_select(),
                              "statuses": REQUEST_STATUSES, "editable_statuses": REQUEST_EDITABLE,
                              "next_no": number_preview(numbering.REQ), "can_order": rbac.can(user, "WO-020", "W"),
                              "form": {"q": q or "", "customer": customer or "", "status": status or "",
                                       "due_from": due_from or "", "due_to": due_to or ""}},
                             screen_id="WO-010")


@router.post("/wo/requests")
def request_create(request: Request, customer_id: str | None = Form(None), item_id: str | None = Form(None),
                   qty_: str | None = Form(None, alias="qty"), due_date: str | None = Form(None),
                   request_date: str | None = Form(None), note: str | None = Form(None),
                   user: rbac.User = rbac.require_fn("F-WO-011")):
    cid = ref_id(customer_id, "거래처")
    iid = ref_id(item_id, "제품")
    q_ = qty(qty_, "수량")
    due = day(due_date, "납기")
    rdate = day(request_date, "의뢰일", required=False)
    with conn.tx() as cur:
        cu = _customer(cur, cid)
        it = item_choice(cur, iid, "제품")
        no = numbering.next(numbering.REQ, cur)
        cur.execute("""insert into production_request (request_no, request_date, customer_id, item_id, qty, due_date, note,
                                                       created_by)
                       values (%s, coalesce(%s, current_date), %s, %s, %s, %s, %s, %s) returning id""",
                    (no, rdate, cid, iid, q_, due, s(note), user.login_id))
        new_id = cur.fetchone()["id"]
        notify.emit(cur, "request_created", link=request_link(no), dedupe_key=f"request_created:{no}",
                    text=f"생산의뢰 등록 {no} · {cu['customer_code']} · {it['item_code']} · 납기 {due}")
    resp = http.saved(request, f"생산의뢰를 등록했습니다 ({no})", back=nav.path_of("WO-010"),
                      data={"id": new_id, "request_no": no})
    audit.log_change(request, user, "F-WO-011", f"production_request:{no}", "생산의뢰 등록")
    return resp


@router.post("/wo/requests/{id}")
def request_update(request: Request, id: str, request_no: str | None = Form(None), customer_id: str | None = Form(None),
                   item_id: str | None = Form(None), qty_: str | None = Form(None, alias="qty"),
                   due_date: str | None = Form(None), note: str | None = Form(None), status: str | None = Form(None),
                   user: rbac.User = rbac.require_fn("F-WO-012")):
    rid = pk(id)
    cid = ref_id(customer_id, "거래처")
    iid = ref_id(item_id, "제품")
    q_ = qty(qty_, "수량")
    due = day(due_date, "납기")
    st = choice(status, "상태", REQUEST_STATUSES)
    with conn.tx() as cur:
        row = exists_or_404(cur, "production_request", rid, "id, request_no, customer_id, item_id, status")
        if s(request_no) is not None and s(request_no) != row["request_no"]:
            raise bad("의뢰번호", "의뢰번호는 바꾸지 않습니다", "의뢰번호는 바꿀 수 없습니다")
        cur.execute("select count(*) as n from work_order where request_id = %s and status <> '취소'", (rid,))
        active = cur.fetchone()["n"]
        if st == "지시완료" and row["status"] != "지시완료":
            raise bad("상태", "지시완료는 생산지시서를 작성하면 바뀝니다")
        if active and st != "지시완료":
            raise bad("상태", f"취소되지 않은 지시 {active}건이 있는 의뢰는 {st}(으)로 바꿀 수 없습니다")
        if active and (cid != row["customer_id"] or iid != row["item_id"]):
            raise bad("제품", "지시가 있는 의뢰의 거래처·제품은 바꿀 수 없습니다")
        _customer(cur, cid, allow_inactive_id=row["customer_id"])
        item_choice(cur, iid, "제품", allow_inactive_id=row["item_id"])
        cur.execute("""update production_request set customer_id = %s, item_id = %s, qty = %s, due_date = %s, note = %s,
                              status = %s, updated_at = now(), updated_by = %s where id = %s""",
                    (cid, iid, q_, due, s(note), st, user.login_id, rid))
    resp = http.saved(request, f"생산의뢰를 수정했습니다 ({row['request_no']})", back=nav.path_of("WO-010"),
                      data={"id": rid, "status": st})
    audit.log_change(request, user, "F-WO-012", f"production_request:{row['request_no']}",
                     f"생산의뢰 수정 · 상태 {row['status']} → {st}")
    return resp


# ── WO-020 생산지시서 ───────────────────────────────────────────────────
def _load_for_item(item_id: int | None) -> tuple[list[dict], list[dict]]:
    """그 제품의 사용 중 사양(STD-010) · 시안(STD-040) — 사용 중지는 불러오지 않는다."""
    if item_id is None:
        return [], []
    specs = conn.q("select id, revision, title from spec_sheet where item_id = %s and use_yn = 'Y' order by revision desc",
                   (item_id,))
    arts = conn.q("select id, version, title from artwork where item_id = %s and use_yn = 'Y' order by version desc",
                  (item_id,))
    return specs, arts


@router.get(nav.path_of("WO-020"), response_class=HTMLResponse)
def orders(request: Request, request_no: str | None = None, q: str | None = None, status: str | None = None,
           edit: str | None = None, user: rbac.User = rbac.require_screen("WO-020")):
    """F-WO-023 — 지시 목록. `?request_no=` 로 그 의뢰의 지시서 작성 폼을 연다(사양·시안 불러오기)."""
    rows = conn.q(
        """select w.id, w.work_order_no, r.request_no, c.customer_name, i.item_code, i.item_name, w.qty, w.equipment_code,
                  w.planned_on, w.status, r.due_date, s.revision as spec_revision, a.version as artwork_version
             from work_order w
             join production_request r on r.id = w.request_id
             join customer c on c.id = r.customer_id
             join item i on i.id = w.item_id
             left join spec_sheet s on s.id = w.spec_sheet_id
             left join artwork a on a.id = w.artwork_id
            where (%(q)s::text is null or w.work_order_no ilike %(q)s or r.request_no ilike %(q)s
                   or i.item_code ilike %(q)s or i.item_name ilike %(q)s)
              and (%(st)s::text is null or w.status = %(st)s)
            order by w.id desc limit 1000""",
        {"q": like(q), "st": choice(status, "상태", ORDER_STATUSES, required=False)})
    picked = None
    if s(request_no):
        picked = conn.q1("""select r.id, r.request_no, r.qty, r.due_date, r.status, r.item_id, i.item_code, i.item_name,
                                   c.customer_name
                              from production_request r join item i on i.id = r.item_id
                              join customer c on c.id = r.customer_id where r.request_no = %s""", (s(request_no),))
        if picked is None:
            raise bad("의뢰번호", s(request_no), "없는 의뢰번호입니다")
    ed = edit_row("work_order", edit)
    specs, arts = _load_for_item((ed or picked or {}).get("item_id"))
    open_requests = conn.q(
        """select r.request_no, r.status, c.customer_name, i.item_code, r.qty, r.due_date
             from production_request r join customer c on c.id = r.customer_id join item i on i.id = r.item_id
            where r.status = any(%s) order by r.due_date, r.id limit 500""", (list(REQUEST_ORDERABLE),))
    return templating.render(request, "wo/orders.html",
                             {"rows": rows, "edit": ed, "picked": picked, "specs": specs, "artworks": arts,
                              "open_requests": open_requests, "equipment": equipment_codes(),
                              "statuses": ORDER_STATUSES, "next_no": number_preview(numbering.WO),
                              "form": {"q": q or "", "status": status or "", "request_no": request_no or ""}},
                             screen_id="WO-020")


def _spec_art(cur, item_id: int, spec_id: int | None, art_id: int | None, *, keep_spec=None, keep_art=None) -> None:
    if spec_id is not None:
        cur.execute("select item_id, use_yn from spec_sheet where id = %s", (spec_id,))
        r = cur.fetchone()
        if r is None or r["item_id"] != item_id:
            raise bad("제조사양기준서", "그 제품의 사양이 아닙니다")
        if r["use_yn"] != "Y" and spec_id != keep_spec:
            raise bad("제조사양기준서", "사용 중지 사양은 불러오지 않습니다")
    if art_id is not None:
        cur.execute("select item_id, use_yn from artwork where id = %s", (art_id,))
        r = cur.fetchone()
        if r is None or r["item_id"] != item_id:
            raise bad("시안", "그 제품의 시안이 아닙니다")
        if r["use_yn"] != "Y" and art_id != keep_art:
            raise bad("시안", "사용 중지 시안은 불러오지 않습니다")


@router.post("/wo/orders")
def order_create(request: Request, request_id: str | None = Form(None), request_no: str | None = Form(None),
                 spec_sheet_id: str | None = Form(None), artwork_id: str | None = Form(None),
                 qty_: str | None = Form(None, alias="qty"), equipment_code: str | None = Form(None),
                 planned_on: str | None = Form(None), note: str | None = Form(None),
                 user: rbac.User = rbac.require_fn("F-WO-021")):
    if s(request_id) is None and s(request_no) is None:
        raise bad("생산의뢰", "필수 항목입니다", "필수 항목을 입력해 주세요 — 생산의뢰")
    spec = ref_id(spec_sheet_id, "제조사양기준서", required=False)
    art = ref_id(artwork_id, "시안", required=False)
    q_ = qty(qty_, "지시 수량")
    planned = day(planned_on, "생산 예정일", required=False)
    with conn.tx() as cur:
        if s(request_id) is not None:
            cur.execute("select id, request_no, item_id, status from production_request where id = %s for update",
                        (ref_id(request_id, "생산의뢰"),))
        else:
            cur.execute("select id, request_no, item_id, status from production_request where request_no = %s for update",
                        (s(request_no),))
        rq = cur.fetchone()
        if rq is None:
            raise http.not_found("없는 생산의뢰입니다")
        if rq["status"] not in REQUEST_ORDERABLE:
            raise bad("생산의뢰", f"{rq['status']} 의뢰로는 지시서를 만들 수 없습니다 ({rq['request_no']})")
        _spec_art(cur, rq["item_id"], spec, art)
        eq = _equipment(cur, s(equipment_code))
        no = numbering.next(numbering.WO, cur)
        cur.execute("""insert into work_order (work_order_no, request_id, item_id, spec_sheet_id, artwork_id, qty,
                                               equipment_code, planned_on, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                    (no, rq["id"], rq["item_id"], spec, art, q_, eq, planned, s(note), user.login_id))
        new_id = cur.fetchone()["id"]
        cur.execute("""update production_request set status = '지시완료', updated_at = now(), updated_by = %s
                        where id = %s and status in ('확인대기', '확정')""", (user.login_id, rq["id"]))
        notify.emit(cur, "order_issued", link=order_link(no), dedupe_key=f"order_issued:{no}",
                    text=f"생산지시 발행 {no} · 의뢰 {rq['request_no']} — 불출 준비")
        notify.handle_by_link(cur, request_link(rq["request_no"]), user)
    resp = http.saved(request, f"생산지시서를 작성했습니다 ({no})", back=nav.path_of("WO-020"),
                      data={"id": new_id, "work_order_no": no, "request_no": rq["request_no"]})
    audit.log_change(request, user, "F-WO-021", f"work_order:{no}", f"생산지시 작성 · 의뢰 {rq['request_no']}")
    return resp


@router.post("/wo/orders/{id}")
def order_update(request: Request, id: str, work_order_no: str | None = Form(None), request_no: str | None = Form(None),
                 spec_sheet_id: str | None = Form(None), artwork_id: str | None = Form(None),
                 qty_: str | None = Form(None, alias="qty"), equipment_code: str | None = Form(None),
                 planned_on: str | None = Form(None), note: str | None = Form(None), status: str | None = Form(None),
                 user: rbac.User = rbac.require_fn("F-WO-022")):
    wid = pk(id)
    spec = ref_id(spec_sheet_id, "제조사양기준서", required=False)
    art = ref_id(artwork_id, "시안", required=False)
    q_ = qty(qty_, "지시 수량")
    planned = day(planned_on, "생산 예정일", required=False)
    st = choice(status, "상태", ORDER_STATUSES)
    with conn.tx() as cur:
        row = exists_or_404(cur, "work_order", wid, "id, work_order_no, request_id, item_id, spec_sheet_id, artwork_id, "
                                                    "equipment_code, status")
        if s(work_order_no) is not None and s(work_order_no) != row["work_order_no"]:
            raise bad("지시번호", "지시번호는 바꾸지 않습니다", "지시번호는 바꿀 수 없습니다")
        if s(request_no) is not None:
            cur.execute("select request_no from production_request where id = %s", (row["request_id"],))
            if cur.fetchone()["request_no"] != s(request_no):
                raise bad("의뢰번호", "의뢰번호는 바꾸지 않습니다", "지시의 의뢰번호는 바꿀 수 없습니다")
        _spec_art(cur, row["item_id"], spec, art, keep_spec=row["spec_sheet_id"], keep_art=row["artwork_id"])
        eq = _equipment(cur, s(equipment_code), allow=row["equipment_code"])
        cur.execute("""update work_order set spec_sheet_id = %s, artwork_id = %s, qty = %s, equipment_code = %s,
                              planned_on = %s, note = %s, status = %s, updated_at = now(), updated_by = %s
                        where id = %s""", (spec, art, q_, eq, planned, s(note), st, user.login_id, wid))
    resp = http.saved(request, f"생산지시서를 수정했습니다 ({row['work_order_no']})", back=nav.path_of("WO-020"),
                      data={"id": wid, "status": st})
    audit.log_change(request, user, "F-WO-022", f"work_order:{row['work_order_no']}",
                     f"생산지시 수정 · 상태 {row['status']} → {st}")
    return resp


@router.get("/wo/orders/{id}/print", response_class=HTMLResponse)
def order_print(request: Request, id: str, user: rbac.User = rbac.require_fn("F-WO-024")):
    """F-WO-024 — 지시서 한 건을 출력 양식으로 연다(사양 항목 · 시안 이미지 포함)."""
    row = conn.q1(
        """select w.*, r.request_no, r.request_date, r.qty as request_qty, r.due_date, c.customer_code, c.customer_name,
                  i.item_code, i.item_name, i.spec as item_spec, i.unit,
                  s.revision as spec_revision, s.title as spec_title, s.content as spec_content,
                  a.version as artwork_version, a.title as artwork_title, a.content_type, a.image
             from work_order w
             join production_request r on r.id = w.request_id
             join customer c on c.id = r.customer_id
             join item i on i.id = w.item_id
             left join spec_sheet s on s.id = w.spec_sheet_id
             left join artwork a on a.id = w.artwork_id
            where w.id = %s""", (pk(id),))
    if row is None:
        raise http.not_found()
    row["artwork_src"] = data_uri(row["content_type"], row.pop("image")) if row["content_type"] else None
    return templating.render(request, "wo/order_print.html", {"row": row, "page_title": "생산지시서 출력"},
                             screen_id="WO-020")


# ── WO-030 생산순서관리 ─────────────────────────────────────────────────
_SEQ_SQL = """
select w.id, w.work_order_no, w.status, w.qty, w.planned_on, w.equipment_code, i.item_code, i.item_name,
       r.request_no, r.due_date, ws.seq_no
  from work_order w
  join item i on i.id = w.item_id
  join production_request r on r.id = w.request_id
  left join work_sequence ws on ws.work_order_id = w.id and ws.equipment_code = w.equipment_code
 where w.equipment_code = %s and w.status in ('발행', '진행')
 order by ws.seq_no nulls last, w.planned_on nulls last, w.id
"""


@router.get(nav.path_of("WO-030"), response_class=HTMLResponse)
def sequence(request: Request, user: rbac.User = rbac.require_screen("WO-030")):
    """F-WO-032 — 설비별 작업 순서 (진행 중인 지시 = 발행 · 진행). 설비는 SYS-030 공통코드."""
    groups = []
    codes = conn.q("""select code, code_name, use_yn from sys_common_code where group_code = '설비'
                      union select distinct w.equipment_code, w.equipment_code, 'N' from work_order w
                       where w.equipment_code is not null
                         and not exists (select 1 from sys_common_code c where c.group_code = '설비'
                                          and c.code = w.equipment_code)
                      order by 1""")
    for c in codes:
        rows = conn.q(_SEQ_SQL, (c["code"],))
        if rows or c["use_yn"] == "Y":
            groups.append({"code": c["code"], "name": c["code_name"], "rows": rows})
    unassigned = conn.q("""select w.id, w.work_order_no, w.status, i.item_code, r.request_no from work_order w
                             join item i on i.id = w.item_id join production_request r on r.id = w.request_id
                            where w.equipment_code is null and w.status in ('발행', '진행') order by w.id""")
    return templating.render(request, "wo/sequence.html", {"groups": groups, "unassigned": unassigned},
                             screen_id="WO-030")


@router.post("/wo/sequence/{id}/move")
def sequence_move(request: Request, id: str, direction: str | None = Form(None),
                  user: rbac.User = rbac.require_fn("F-WO-031")):
    """같은 설비 안에서 지시의 순서를 한 칸 옮긴다 — direction = up | down."""
    wid = pk(id)
    dirn = choice(direction, "방향", ("up", "down"))
    with conn.tx() as cur:
        row = exists_or_404(cur, "work_order", wid, "id, work_order_no, equipment_code, status")
        eq = row["equipment_code"]
        if eq is None:
            raise bad("설비", "설비가 없는 지시는 순서를 정할 수 없습니다 — 지시서에서 설비를 먼저 고른다")
        if row["status"] not in ORDER_ACTIVE:
            raise bad("상태", f"{row['status']} 지시는 순서를 옮길 수 없습니다")
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"work_sequence:{eq}",))
        cur.execute(_SEQ_SQL, (eq,))
        ids = [r["id"] for r in cur.fetchall()]
        i = ids.index(wid)
        j = i - 1 if dirn == "up" else i + 1
        if j < 0 or j >= len(ids):
            raise bad("방향", "이미 맨 앞입니다" if dirn == "up" else "이미 맨 뒤입니다")
        ids[i], ids[j] = ids[j], ids[i]
        cur.execute("delete from work_sequence where equipment_code = %s or work_order_id = any(%s)", (eq, ids))
        for n, oid in enumerate(ids, 1):
            cur.execute("insert into work_sequence (work_order_id, equipment_code, seq_no, created_by) "
                        "values (%s, %s, %s, %s)", (oid, eq, n, user.login_id))
    resp = http.saved(request, f"작업 순서를 옮겼습니다 ({row['work_order_no']} → {j + 1}번째)",
                      back=nav.path_of("WO-030"), data={"id": wid, "seq_no": j + 1, "order": ids})
    audit.log_change(request, user, "F-WO-031", f"work_sequence:{eq}/{row['work_order_no']}",
                     f"순서 {i + 1} → {j + 1}")
    return resp


# ── WO-040 공정상태 ─────────────────────────────────────────────────────
@router.get(nav.path_of("WO-040"), response_class=HTMLResponse)
def status(request: Request, q: str | None = None,
           user: rbac.User = rbac.require_screen("WO-040")):
    """F-WO-041 — 지시별 공정 진행 상태. 뷰 `v_work_order_status` 를 읽기만 한다."""
    st = request.query_params.get("status")
    rows = conn.q(
        """select v.*, i.item_code, i.item_name, r.due_date, c.customer_name
             from v_work_order_status v
             join item i on i.id = v.item_id
             join production_request r on r.id = v.request_id
             join customer c on c.id = r.customer_id
            where (%(q)s::text is null or v.work_order_no ilike %(q)s or v.request_no ilike %(q)s or i.item_code ilike %(q)s)
              and (%(st)s::text is null or v.status = %(st)s)
            order by v.work_order_id desc limit 1000""",
        {"q": like(q), "st": choice(st, "상태", ORDER_STATUSES, required=False)})
    return templating.render(request, "wo/status.html",
                             {"rows": rows, "statuses": ORDER_STATUSES, "form": {"q": q or "", "status": st or ""}},
                             screen_id="WO-040")
