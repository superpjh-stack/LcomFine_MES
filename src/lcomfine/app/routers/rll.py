"""rll 라우터 — 후가공 · 슬리팅 롤 이력 (기능 7) · 담당 개발2.

쓰는 저장소: D6 (`roll` `roll_genealogy`) — **`lineage` 를 거쳐서만** 쓴다. 이 파일에는 쓰기 SQL 이 없다(G-05).
롤 상태(재고·소진·출하)는 저장하지 않는다 — 뷰 `v_roll_state` 가 계보에서 계산한다.

  RLL-01 후가공 → /rll/finishing
      F-RLL-01 후가공 실적 등록 [등록] POST /rll/finishing            부모 롤 1개 → 후가공 롤 1개 (`후가공` 1줄)
      F-RLL-02 splice 등록 [등록] POST /rll/finishing/splice          부모 롤 N개(2 이상) → 후가공 롤 1개 (`splice` N줄)
      F-RLL-03 후가공 조회 [조회] GET /rll/finishing
  RLL-02 슬리팅 → /rll/slitting
      F-RLL-04 슬리팅 분할 등록 [등록] POST /rll/slitting              부모 롤 1개 → 슬리팅 롤 N개 (`슬리팅` N줄) + 라벨 N장
      F-RLL-05 슬리팅 조회 [조회] GET /rll/slitting
  RLL-03 롤 이력 → /rll/history
      F-RLL-06 롤 이력 조회 [조회] GET /rll/history
      F-RLL-07 롤 라벨 출력 [출력] GET /rll/history/{roll_no}/label
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...db import conn
from .. import lineage, nav, printing, rbac, templating
from ..util import audit, http
from .pop import (LIST_LIMIT, WIDTH, back_to, bad, decimal_of, equipment_of, equipment_options, find_job, int_of,
                  label_page, scan_failure, text_of)

router = APIRouter()

FIN, SLT, HIS = nav.path_of("RLL-01"), nav.path_of("RLL-02"), nav.path_of("RLL-03")


def _label_url(roll_no: str) -> str:
    return f"{HIS}/{roll_no}/label"


def _roll_node(roll_no: str | None, label: str = "롤 번호") -> lineage.Node:
    """사용자가 입력·스캔한 롤 번호 → 롤 노드. 비었거나 없으면(다른 종류의 번호 포함) 422."""
    no = text_of(roll_no, label, required=True)
    node = lineage.resolve(no)
    if node is None or node.kind != lineage.ROLL:
        raise bad("없는 롤 번호입니다", label, no)
    return node


def _split_numbers(values: list[str]) -> list[str]:
    """반복 필드·쉼표·공백·줄바꿈으로 들어온 번호들을 순서대로 편다."""
    out: list[str] = []
    for v in values:
        out.extend(p for p in (v or "").replace(",", " ").split() if p)
    return out


_ROLL_LIST = """
select v.roll_id, v.roll_no, v.process_type, v.state, r.length_m, r.width_mm, r.slit_seq, r.produced_at, r.produced_by,
       j.job_no, j.status as job_status, e.equipment_name,
       (select string_agg(p.roll_no, ', ' order by p.roll_no)
          from roll_genealogy g join roll p on p.roll_id = g.parent_roll_id
         where g.child_roll_id = v.roll_id) as parent_rolls,
       (select min(g.relation) from roll_genealogy g where g.child_roll_id = v.roll_id) as relation
  from v_roll_state v
  join roll r on r.roll_id = v.roll_id
  join job j on j.job_id = r.job_id
  left join equipment e on e.equipment_id = r.equipment_id
"""


#: 인쇄 롤들의 작업 실적 — 롤 이력의 「생산 실적」. 정지·폐기는 그 실적에 매달린 기록을 센다(읽기만 한다)
_WORKS_OF_ROLLS = """
select w.work_result_id, w.status, w.started_at, w.ended_at, w.output_qty, w.qty_unit, w.worker,
       r.roll_no, j.job_no, e.equipment_name,
       (select count(*) from work_stop s where s.work_result_id = w.work_result_id) as stop_count,
       (select count(*) from work_scrap c where c.work_result_id = w.work_result_id) as scrap_count
  from roll r
  join work_result w on w.work_result_id = r.work_result_id
  join job j on j.job_id = w.job_id
  left join equipment e on e.equipment_id = w.equipment_id
 where r.roll_id = any(%s)
 order by w.started_at, w.work_result_id
"""


def _labels_of(roll_nos: list[str]) -> list:
    return [printing.render_label(printing.roll_label(n)) for n in roll_nos]


# ── RLL-01 후가공 ───────────────────────────────────────────────────────
@router.get(FIN, response_class=HTMLResponse)                             # F-RLL-03 후가공 조회
def finishing_list(request: Request, add: str = "", rolls: str = "", made: str = "",
                   user: rbac.User = rbac.require_fn("F-RLL-03")):
    """후가공 롤 목록(부모 롤·설비·길이·상태).

    스캔 흐름 — 부모 롤을 스캔할 때마다 `?add=<롤 번호>` 로 들어와 `rolls`(스캔해 둔 롤, 쉼표로 이은 번호)에 붙는다.
    1개면 후가공 실적 등록, 2개 이상이면 splice 등록으로 보낸다. 스캔해 둔 목록은 주소에만 있다(어디에도 저장하지 않는다).
    부모들의 Job 이 서로 다르면 후가공 롤의 Job 을 **부모 롤들의 Job 가운데 `등록` 상태인 것**에서 고르게 한다(D-208).
    """
    pending = list(dict.fromkeys(_split_numbers([rolls])))
    scan_error = None
    if add.strip():
        node = lineage.resolve(add.strip())
        if node is None or node.kind != lineage.ROLL:
            scan_error = scan_failure(request, bad("없는 롤 번호입니다", "롤 번호", add.strip()))
        elif node.no in pending:
            scan_error = scan_failure(request, bad("이미 스캔한 롤입니다", node.no, "같은 롤 중복"))
        elif node.state != lineage.IN_STOCK:
            scan_error = scan_failure(request, bad(f"이미 {node.state}된 롤은 다시 쓸 수 없습니다", node.no, f"상태 {node.state}"))
        else:
            pending.append(node.no)
            if http.wants_html(request):       # 주소를 정리해 새로 고침해도 같은 롤이 다시 붙지 않게 한다
                device = request.query_params.get("device")
                return RedirectResponse(f"{FIN}?rolls={quote(','.join(pending))}" + (f"&device={device}" if device else ""),
                                        status_code=303)
    pending_rows = []
    if pending:
        found = {r["roll_no"]: r for r in conn.q(_ROLL_LIST + " where v.roll_no = any(%s)", (pending,))}
        pending_rows = [found[n] for n in pending if n in found]
    rows = conn.q(_ROLL_LIST + f" where v.process_type = '후가공' order by r.produced_at desc, v.roll_id desc limit {LIST_LIMIT}")
    made_no = made.strip() if made.strip() and conn.q1("select 1 from roll where roll_no = %s", (made.strip(),)) else ""
    return templating.render(
        request, "rll/finishing.html",
        {"rows": rows, "pending": pending_rows, "pending_csv": ",".join(r["roll_no"] for r in pending_rows),
         "job_count": len({r["job_no"] for r in pending_rows}),
         "job_options": [(j, j) for j in dict.fromkeys(r["job_no"] for r in pending_rows if r["job_status"] == lineage.JOB_OPEN)],
         "scan_error": scan_error, "equipment_options": equipment_options(),
         "made_no": made_no, "made_labels": _labels_of([made_no]) if made_no else [], "lineage": lineage,
         "can_finish": user.can("F-RLL-01"), "can_splice": user.can("F-RLL-02")},
        screen_id="RLL-01", status_code=422 if scan_error else 200)


def _finish(request: Request, user: rbac.User, fn_id: str, nodes: list[lineage.Node], *, job_no: str,
            equipment_code: str, length_m: str, width_mm: str):
    eq = equipment_of(equipment_code)
    length = decimal_of(length_m, "길이", non_negative=True)
    width = decimal_of(width_mm, "폭", positive=True, digits=WIDTH)
    job_id = None
    if (job_no or "").strip():
        job = find_job(job_no)
        if job is None:
            raise bad("없는 Job 번호입니다", "Job 번호", job_no.strip())
        job_id = job["job_id"]
    with conn.tx() as cur:
        roll = lineage.make_finishing_roll(cur, parent_roll_ids=[n.id for n in nodes], by=user.login_id, job_id=job_id,
                                           equipment_id=eq["equipment_id"] if eq else None, length_m=length, width_mm=width)
    roll_no = roll["roll_no"]
    parents = ", ".join(n.no for n in nodes)
    relation = lineage.FINISHING if len(nodes) == 1 else lineage.SPLICE
    audit.log_change(request, user, fn_id, f"roll:{roll_no}", f"{relation} — {parents} → {roll_no}")
    return http.saved(request, f"후가공 롤 {roll_no} 을 만들었습니다 ({relation} · 부모 {len(nodes)}개)",
                      back=back_to(request, f"{FIN}?made={roll_no}"),
                      data={"roll_no": roll_no, "relation": relation, "parents": [n.no for n in nodes],
                            "label_url": _label_url(roll_no)})


@router.post(FIN)                                                         # F-RLL-01 후가공 실적 등록
def finishing_create(request: Request, roll_no: str = Form(""), equipment_code: str = Form(""),
                     length_m: str = Form(""), width_mm: str = Form(""), user: rbac.User = rbac.require_fn("F-RLL-01")):
    """부모 롤 **1개** 스캔 + 설비·길이 → 후가공 롤 1개와 계보 `후가공` 한 줄. 부모는 `재고` 여야 한다."""
    numbers = _split_numbers([roll_no])
    if len(numbers) > 1:
        raise bad("후가공 실적은 부모 롤 1개입니다 — 여러 롤을 합치려면 splice 로 등록하세요", "부모 롤", f"{len(numbers)}개")
    node = _roll_node(roll_no, "부모 롤")
    return _finish(request, user, "F-RLL-01", [node], job_no="", equipment_code=equipment_code, length_m=length_m,
                   width_mm=width_mm)


@router.post(FIN + "/splice")                                             # F-RLL-02 splice 등록
def splice_create(request: Request, roll_no: list[str] = Form(default=[]), job_no: str = Form(""),
                  equipment_code: str = Form(""), length_m: str = Form(""), width_mm: str = Form(""),
                  user: rbac.User = rbac.require_fn("F-RLL-02")):
    """부모 롤 **N개(2 이상)** 스캔 → 후가공 롤 1개와 계보 `splice` N줄. 한 트랜잭션.

    `roll_no` 는 반복 필드(또는 쉼표·공백으로 이은 번호). 부모들의 Job 이 서로 다르면 `job_no` 로 후가공 롤의 Job 을 준다.
    `job_no` 는 부모 롤들의 Job 중 하나여야 하고, 취소·완료 Job 이면 422 — 판정은 `lineage.make_finishing_roll` 이 한다(D-208).
    """
    numbers = _split_numbers(roll_no)
    if len(numbers) < 2:
        raise bad("splice 는 부모 롤이 2개 이상이어야 합니다", "부모 롤", f"{len(numbers)}개")
    nodes = [_roll_node(n, "부모 롤") for n in numbers]
    dup = sorted({n.no for n in nodes if [m.no for m in nodes].count(n.no) > 1})
    if dup:
        raise http.validation_error("같은 롤을 두 번 스캔했습니다", fields=[{"name": d, "reason": "중복"} for d in dup])
    return _finish(request, user, "F-RLL-02", nodes, job_no=job_no, equipment_code=equipment_code, length_m=length_m,
                   width_mm=width_mm)


# ── RLL-02 슬리팅 ───────────────────────────────────────────────────────
@router.get(SLT, response_class=HTMLResponse)                             # F-RLL-05 슬리팅 조회
def slitting_list(request: Request, no: str = "", parent: str = "", user: rbac.User = rbac.require_fn("F-RLL-05")):
    """슬리팅 롤 목록(부모 롤·분할 순번·폭·상태). `?no=<롤 번호>` 는 부모 롤 스캔 진입 — 분할 칸이 열린다.
    `?parent=<롤 번호>` 는 그 부모에서 나온 슬리팅 롤의 라벨 N장을 한 번에 보여 준다."""
    scan_error, opened = None, None
    if no.strip():
        node = lineage.resolve(no.strip())
        if node is None or node.kind != lineage.ROLL:
            scan_error = scan_failure(request, bad("없는 롤 번호입니다", "롤 번호", no.strip()))
        else:
            opened = conn.q1(_ROLL_LIST + " where v.roll_id = %s", (node.id,))
    where, params, made_labels, made_parent = "", [], [], ""
    if parent.strip():
        p = lineage.resolve(parent.strip())
        if p is not None and p.kind == lineage.ROLL:
            made_parent = p.no
            children = [e.child.no for e in lineage.children_of(p.ref) if e.relation == lineage.SLITTING]
            made_labels = _labels_of(sorted(children))
            where, params = " and exists (select 1 from roll_genealogy g where g.child_roll_id = v.roll_id and g.parent_roll_id = %s)", [p.id]
    rows = conn.q(_ROLL_LIST + f" where v.process_type = '슬리팅'{where} order by r.produced_at desc, parent_rolls, r.slit_seq limit {LIST_LIMIT}",
                  params)
    return templating.render(
        request, "rll/slitting.html",
        {"rows": rows, "opened": opened, "scan_error": scan_error, "equipment_options": equipment_options(),
         "made_parent": made_parent, "made_labels": made_labels, "can_slit": user.can("F-RLL-04"), "lineage": lineage},
        screen_id="RLL-02", status_code=422 if scan_error else 200)


@router.post(SLT)                                                         # F-RLL-04 슬리팅 분할 등록
def slitting_create(request: Request, roll_no: str = Form(""), count: str = Form(""), widths_mm: str = Form(""),
                    equipment_code: str = Form(""), length_m: str = Form(""),
                    user: rbac.User = rbac.require_fn("F-RLL-04")):
    """부모 롤 1개 스캔 + 분할 수 N(+ 폭) → 슬리팅 롤 N개와 계보 `슬리팅` N줄, 라벨 N장.

    `widths_mm` 는 쉼표·공백으로 이은 폭 N개(선택). 주면 개수가 분할 수와 같아야 한다.
    """
    node = _roll_node(roll_no, "부모 롤")
    n = int_of(count, "분할 수", required=True, minimum=1)
    widths = [decimal_of(w, f"폭 {i}", positive=True, digits=WIDTH) for i, w in enumerate(_split_numbers([widths_mm]), start=1)] or None
    eq = equipment_of(equipment_code)
    length = decimal_of(length_m, "길이", non_negative=True)
    with conn.tx() as cur:
        made = lineage.slit_roll(cur, parent_roll_id=node.id, count=n, by=user.login_id,
                                 equipment_id=eq["equipment_id"] if eq else None, widths_mm=widths, length_m=length)
    numbers = [r["roll_no"] for r in made]
    audit.log_change(request, user, "F-RLL-04", f"roll:{node.no}", f"슬리팅 — {node.no} → {', '.join(numbers)}")
    return http.saved(request, f"슬리팅 롤 {len(numbers)}개를 만들었습니다 — {numbers[0]} ~ {numbers[-1]}",
                      back=back_to(request, f"{SLT}?parent={node.no}"),
                      data={"parent": node.no, "rolls": numbers, "label_urls": [_label_url(x) for x in numbers]})


# ── RLL-03 롤 이력 ──────────────────────────────────────────────────────
@router.get(HIS, response_class=HTMLResponse)                             # F-RLL-06 롤 이력 조회
def history(request: Request, no: str = "", user: rbac.User = rbac.require_fn("F-RLL-06")):
    """롤 번호(스캔)로 그 롤의 공정 구분·Job·상태·부모·자식 한 단계. 없는 롤은 422.

    롤 번호 하나로 그 롤의 작업지시·조색 기록·생산 실적·검사 결과·출하를 Job-Lot-Roll 키로 이어 읽는다(G-08). 읽기만 한다.
    생산 실적은 인쇄 롤이면 그 롤의 실적, 후가공·슬리팅 롤이면 계보를 거슬러 올라간 조상 인쇄 롤들의 실적이다.
    """
    scan_error, detail = None, None
    if no.strip():
        node = lineage.resolve(no.strip())
        if node is None or node.kind != lineage.ROLL:
            scan_error = scan_failure(request, bad("없는 롤 번호입니다", "롤 번호", no.strip()))
        else:
            roll = conn.q1(
                """select r.roll_id, r.roll_no, r.process_type, r.length_m, r.width_mm, r.slit_seq, r.produced_at,
                          r.produced_by, r.work_result_id, r.note, v.state, v.shipment_id,
                          j.job_id, j.job_no, j.status as job_status, j.due_date, i.item_code, i.item_name,
                          c.customer_name, jl.lot_no as job_lot_no, e.equipment_name
                     from roll r
                     join v_roll_state v on v.roll_id = r.roll_id
                     join job j on j.job_id = r.job_id
                     join item i on i.item_id = j.item_id
                     join customer c on c.customer_id = j.customer_id
                     left join job_lot jl on jl.job_lot_id = r.job_lot_id
                     left join equipment e on e.equipment_id = r.equipment_id
                    where r.roll_id = %s""", (node.id,))
            # 생산 실적 — 인쇄 롤은 자기 실적, 후가공·슬리팅 롤은 계보를 거슬러 올라가 닿은 인쇄 롤들의 실적 (db-schema.md §6).
            # 조상은 역방향 추적(재귀 조회)으로 그때그때 찾는다 — 경로를 저장하지 않는다.
            if roll["process_type"] == lineage.PRINT_ROLL:
                print_roll_ids = [node.id]
            else:
                print_roll_ids = [n.id for n in lineage.trace_backward(node.ref).rolls()
                                  if n.label == lineage.PRINT_ROLL and n.id != node.id]
            works = conn.q(_WORKS_OF_ROLLS, (print_roll_ids,)) if print_roll_ids else []
            detail = {
                "roll": roll,
                "parents": lineage.parents_of(node.ref),
                "children": lineage.children_of(node.ref),
                "works": works, "print_roll_count": len(print_roll_ids),
                "color_count": conn.q1("select count(*) as n from color_record where job_id = %s", (roll["job_id"],))["n"],
                "inspection": conn.q1("""select result, delta_e, inspected_at, inspected_by from inspection
                                          where roll_id = %s order by inspected_at desc, inspection_id desc limit 1""",
                                      (node.id,)),
                "inspection_count": conn.q1("select count(*) as n from inspection where roll_id = %s", (node.id,))["n"],
                "shipment": conn.q1("select shipment_no, status, ship_date from shipment where shipment_id = %s",
                                    (roll["shipment_id"],)) if roll["shipment_id"] else None,
                "label": printing.render_label(printing.roll_label(node.no)),
            }
    recent = conn.q(_ROLL_LIST + f" order by r.produced_at desc, v.roll_id desc limit {LIST_LIMIT}") if detail is None else []
    return templating.render(
        request, "rll/history.html",
        {"detail": detail, "recent": recent, "scan_error": scan_error, "no": no.strip(), "lineage": lineage,
         "can_label": user.can("F-RLL-07"), "can_stops": user.can("F-POP-07")},
        screen_id="RLL-03", status_code=422 if scan_error else 200)


@router.get(HIS + "/{roll_no}/label", response_class=HTMLResponse)        # F-RLL-07 롤 라벨 출력
def history_label(request: Request, roll_no: str, user: rbac.User = rbac.require_fn("F-RLL-07")):
    """후가공·슬리팅 롤 라벨. 인쇄 롤도 같은 양식으로 다시 뽑힌다."""
    if conn.q1("select 1 from roll where roll_no = %s", (roll_no,)) is None:
        raise http.not_found()
    label = printing.roll_label(roll_no)
    return label_page(request, [label], screen_id="RLL-03", back=back_to(request, f"{HIS}?no={roll_no}"), title=f"{label.kind} — {roll_no}")
