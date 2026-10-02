"""shp 라우터 — 출하 (기능 7) · 담당 개발3 · 프로세스 P8.

쓰는 저장소: **D8 (`shipment`)** 와, `lineage.ship_roll` · `lineage.unlink_shipment` 를 거친 계보의 `출하` 행뿐이다(D-12 · G-05).
이 파일에는 `roll_genealogy` 에 쓰는 SQL 이 없다 — 담긴 롤을 **읽기만** 한다. 출하 롤 목록을 담는 테이블도 없다
(계보 한 줄이 곧 "이 롤이 이 출하에 실렸다"). 롤 상태도 적지 않는다(`v_roll_state` 가 계보에서 계산한다).

흐름 (D-17): 출하 등록(`등록`) → 롤 스캔 → 관리자 승인(`승인` = COA 발행) → COA 출력. 승인 전에만 취소(`취소`).
COA 의 내용은 저장하지 않는다 — 그 출하의 롤마다 **최신 검사**(D7)에서 매번 만든다. 검사가 없는 롤은 `미수집`.

  SHP-01 출하 → /shp/shipments
      F-SHP-01 출하 등록 [등록] POST /shp/shipments
      F-SHP-02 출하 롤 스캔 [스캔] POST /shp/shipments/{shipment_no}/rolls
      F-SHP-03 출하 취소 [삭제] POST /shp/shipments/{shipment_no}/cancel
      F-SHP-04 출하 조회 [조회] GET /shp/shipments
  SHP-02 출하 승인 → /shp/approvals
      F-SHP-05 출하 승인 [승인] POST /shp/approvals/{shipment_no}/approve        (관리자만 — 범위 `승인`, D-14)
  SHP-03 COA → /shp/coa
      F-SHP-06 COA 조회 [조회] GET /shp/coa
      F-SHP-07 COA 출력 [출력] GET /shp/coa/{shipment_no}/print
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import lineage, nav, numbering, printing, rbac, stats, templating
from ..util import audit, http
from .qua import FAIL, latest_inspections, scan_failure

router = APIRouter()

REGISTERED, APPROVED, CANCELLED = "등록", "승인", "취소"
STATUSES: tuple[str, ...] = (REGISTERED, APPROVED, CANCELLED)
NOT_ISSUED = "미발행"
LIST_LIMIT = 500

#: 출하 LOT 에 담긴 롤 수 — 계보의 `출하` 행을 센다(읽기)
_ROLL_COUNT = "(select count(*)::int from roll_genealogy g where g.child_shipment_id = s.shipment_id)"

_SHIPMENT_SQL = f"""
select s.shipment_id, s.shipment_no, s.ship_date, s.status, s.registered_at, s.registered_by,
       s.approved_at, s.approved_by, s.coa_no, s.coa_issued_at, s.note, s.job_id, s.customer_id,
       j.job_no, j.due_date, i.item_code, i.item_name, i.spec, c.customer_code, c.customer_name,
       {_ROLL_COUNT} as roll_count
  from shipment s
  join job j on j.job_id = s.job_id
  join item i on i.item_id = j.item_id
  join customer c on c.customer_id = s.customer_id
"""


def _shipment(shipment_no: str) -> dict:
    """경로의 출하 LOT 번호로 한 건. 없으면 404."""
    row = conn.q1(_SHIPMENT_SQL + " where s.shipment_no = %s", (shipment_no,))
    if row is None:
        raise http.not_found()
    return row


def _scanned_shipment(no: str) -> dict:
    """사용자가 입력·스캔한 출하 LOT 번호로 한 건. 다른 스캔 화면처럼 `lineage.resolve` 로 찾는다
    (앞뒤 공백 제거 · 소문자로 들어오면 대문자로도 찾는다, D-201). 없는 번호 · 출하 LOT 이 아닌 번호는 422."""
    node = lineage.resolve(no)
    if node is None:
        raise http.validation_error("없는 출하 LOT 입니다", fields=[{"name": "출하 LOT 번호", "reason": no}])
    if node.kind != lineage.SHIPMENT:
        raise http.validation_error("출하 LOT 번호가 아닙니다", fields=[{"name": no, "reason": node.label}])
    return conn.q1(_SHIPMENT_SQL + " where s.shipment_id = %s", (node.id,))


def _rolls(shipment_id: int) -> list[dict]:
    """그 출하에 담긴 롤(스캔한 순서)과 롤마다의 최신 검사. 검사가 없으면 `inspection` 이 None → 화면은 `미수집`."""
    rolls = conn.q("""select r.roll_id, r.roll_no, r.process_type, r.length_m, r.width_mm,
                             g.created_at as scanned_at, g.created_by as scanned_by
                        from roll_genealogy g
                        join roll r on r.roll_id = g.parent_roll_id
                       where g.child_shipment_id = %s
                       order by g.genealogy_id""", (shipment_id,))
    latest = latest_inspections([r["roll_id"] for r in rolls])
    for r in rolls:
        r["inspection"] = latest.get(r["roll_id"])
    return rolls


def _summary(rolls: list[dict]) -> dict:
    return {"total": len(rolls),
            "passed": sum(1 for r in rolls if r["inspection"] and r["inspection"]["result"] != FAIL),
            "failed": sum(1 for r in rolls if r["inspection"] and r["inspection"]["result"] == FAIL),
            "uninspected": sum(1 for r in rolls if not r["inspection"])}


def _search(shipment_no: str, job_no: str, customer: str, status: str, d1: date | None, d2: date | None,
            statuses: tuple[str, ...] | None = None) -> list[dict]:
    if status and status not in STATUSES:
        raise http.validation_error("상태는 등록 · 승인 · 취소 중 하나입니다", fields=[{"name": "상태", "reason": status}])
    return conn.q(_SHIPMENT_SQL + f"""
         where (%(shipment_no)s::text is null or s.shipment_no ilike '%%' || %(shipment_no)s::text || '%%')
           and (%(job_no)s::text is null or j.job_no ilike '%%' || %(job_no)s::text || '%%')
           and (%(customer)s::text is null or c.customer_name ilike '%%' || %(customer)s::text || '%%'
                                           or c.customer_code ilike '%%' || %(customer)s::text || '%%')
           and (%(status)s::text is null or s.status = %(status)s::text)
           and (%(statuses)s::text[] is null or s.status = any(%(statuses)s::text[]))
           and (%(d1)s::date is null or s.ship_date >= %(d1)s::date)
           and (%(d2)s::date is null or s.ship_date <= %(d2)s::date)
         order by s.shipment_id desc
         limit {LIST_LIMIT}""",
                  {"shipment_no": shipment_no.strip() or None, "job_no": job_no.strip() or None,
                   "customer": customer.strip() or None, "status": status or None,
                   "statuses": list(statuses) if statuses else None, "d1": d1, "d2": d2})


# ── SHP-01 출하 ─────────────────────────────────────────────────────────
@router.get(nav.path_of("SHP-01"), response_class=HTMLResponse)                     # F-SHP-04 출하 조회 = 화면 GET
def shipments(request: Request, no: str = "", shipment_no: str = "", job_no: str = "", customer: str = "",
              status: str = "", date_from: str = "", date_to: str = "",
              user: rbac.User = rbac.require_fn("F-SHP-04")) -> HTMLResponse:
    d1, d2 = stats.parse_date(date_from, "출하일 시작"), stats.parse_date(date_to, "출하일 끝")
    opened, rolls, scan_error = None, [], None
    no = no.strip()
    if no:                                   # 한 건 열기 — 목록에서 고르거나 출하 LOT 번호를 스캔
        try:
            opened = _scanned_shipment(no)
        except HTTPException as exc:         # 없는 번호 — 브라우저면 이 화면을 422 로 다시 그린다 (스캔칸이 남는다, D-201)
            scan_error = scan_failure(request, exc)
        else:
            rolls = _rolls(opened["shipment_id"])
    rows = _search(shipment_no, job_no, customer, status, d1, d2)
    customers = conn.q("select customer_code, customer_name from customer where use_yn = 'Y' order by customer_code")
    return templating.render(request, "shp/shipments.html", {
        "rows": rows, "limit": LIST_LIMIT, "opened": opened, "rolls": rolls, "summary": _summary(rolls),
        "scan_error": scan_error,
        "statuses": STATUSES, "customers": customers, "today": date.today(),
        "number_rule": numbering.rule(numbering.SHIPMENT),
        "q": {"shipment_no": shipment_no, "job_no": job_no, "customer": customer, "status": status,
              "date_from": date_from, "date_to": date_to},
    }, screen_id="SHP-01", status_code=422 if scan_error else 200)


@router.post(nav.path_of("SHP-01"))                                                  # F-SHP-01 출하 등록
def create_shipment(request: Request, job_no: str = Form(""), customer_code: str = Form(""), ship_date: str = Form(""),
                    note: str = Form(""), user: rbac.User = rbac.require_fn("F-SHP-01")):
    job_no, customer_code = job_no.strip(), customer_code.strip()
    missing = [{"name": name, "reason": "비어 있음"} for name, value in (("Job 번호", job_no), ("출하일", ship_date.strip())) if not value]
    if missing:
        raise http.validation_error("필수값을 입력해 주세요", fields=missing)
    day = stats.parse_date(ship_date, "출하일")
    job = conn.q1("select job_id, job_no, customer_id, status from job where job_no = %s", (job_no,))
    if job is None:
        raise http.validation_error("없는 Job 입니다", fields=[{"name": "Job 번호", "reason": job_no}])
    if job["status"] == "취소":
        raise http.validation_error("취소된 Job 은 출하할 수 없습니다", fields=[{"name": job_no, "reason": "상태 취소"}])
    customer_id = job["customer_id"]                      # 고객을 안 주면 그 Job 의 고객
    if customer_code:
        customer = conn.q1("select customer_id from customer where customer_code = %s", (customer_code,))
        if customer is None:
            raise http.validation_error("없는 고객입니다", fields=[{"name": "고객 코드", "reason": customer_code}])
        customer_id = customer["customer_id"]
    with conn.tx() as cur:                                # 채번과 출하 행은 같이 성공하거나 같이 실패한다
        shipment_no = numbering.next(numbering.SHIPMENT, cur=cur)
        cur.execute("""insert into shipment (shipment_no, job_id, customer_id, ship_date, registered_by, note)
                       values (%s, %s, %s, %s, %s, %s)""",
                    (shipment_no, job["job_id"], customer_id, day, user.login_id, note.strip() or None))
    audit.log_change(request, user, "F-SHP-01", f"shipment:{shipment_no}", f"출하 등록 — Job {job_no} · 출하일 {day}")
    return http.saved(request, f"출하를 등록했습니다 — {shipment_no}. 이어서 롤을 스캔합니다",
                      back=f"{nav.path_of('SHP-01')}?no={shipment_no}", data={"shipment_no": shipment_no, "job_no": job_no})


@router.post(nav.path_of("SHP-01") + "/{shipment_no}/rolls")                         # F-SHP-02 출하 롤 스캔
def scan_roll(request: Request, shipment_no: str, roll_no: str = Form(""),
              user: rbac.User = rbac.require_fn("F-SHP-02")):
    shipment = _shipment(shipment_no)
    roll_no = roll_no.strip()
    if not roll_no:
        raise http.validation_error("롤 번호를 스캔해 주세요", fields=[{"name": "롤 번호", "reason": "비어 있음"}])
    node = lineage.resolve(roll_no)
    if node is None:
        raise http.validation_error("없는 롤입니다", fields=[{"name": "롤 번호", "reason": roll_no}])
    if node.kind != lineage.ROLL:
        raise http.validation_error("롤 번호가 아닙니다", fields=[{"name": roll_no, "reason": node.label}])
    if shipment["status"] != REGISTERED:
        raise http.validation_error(f"{shipment['status']}된 출하에는 롤을 담을 수 없습니다",
                                    fields=[{"name": shipment_no, "reason": f"상태 {shipment['status']}"}])
    with conn.tx() as cur:
        # 이미 출하된 롤 · 소진된 롤 · 다른 Job 의 롤 · 최신 검사가 불합격인 롤은 lineage 가 422 로 막는다 (D-12 · D-16 · D-17)
        genealogy_id = lineage.ship_roll(cur, shipment_id=shipment["shipment_id"], roll_id=node.id, by=user.login_id)
    audit.log_change(request, user, "F-SHP-02", f"shipment:{shipment_no} roll:{node.no}", "출하 롤 스캔")
    return http.saved(request, f"{node.no} 을(를) {shipment_no} 에 담았습니다",
                      data={"shipment_no": shipment_no, "roll_no": node.no, "genealogy_id": genealogy_id,
                            "roll_count": shipment["roll_count"] + 1})


@router.post(nav.path_of("SHP-01") + "/{shipment_no}/cancel")                        # F-SHP-03 출하 취소
def cancel_shipment(request: Request, shipment_no: str, user: rbac.User = rbac.require_fn("F-SHP-03")):
    shipment = _shipment(shipment_no)
    if shipment["status"] != REGISTERED:
        reason = "승인된 출하는 취소할 수 없습니다" if shipment["status"] == APPROVED else "이미 취소된 출하입니다"
        raise http.validation_error(reason, fields=[{"name": shipment_no, "reason": f"상태 {shipment['status']}"}])
    with conn.tx() as cur:                                # 계보 행 삭제와 상태 변경은 한 트랜잭션
        removed = lineage.unlink_shipment(cur, shipment["shipment_id"], by=user.login_id)
        cur.execute("""update shipment set status = %s, updated_at = now(), updated_by = %s
                        where shipment_id = %s and status = %s""",
                    (CANCELLED, user.login_id, shipment["shipment_id"], REGISTERED))
        if cur.rowcount != 1:                             # 그 사이 다른 사람이 승인·취소했다 → 전부 되돌린다
            raise http.validation_error("출하 상태가 바뀌어 취소하지 못했습니다", fields=[{"name": shipment_no, "reason": "다시 조회"}])
    audit.log_change(request, user, "F-SHP-03", f"shipment:{shipment_no}", f"출하 취소 — 롤 {removed}개를 재고로 되돌림")
    return http.saved(request, f"출하를 취소했습니다 — {shipment_no} (롤 {removed}개는 다시 재고)",
                      back=nav.path_of("SHP-01"), data={"shipment_no": shipment_no, "removed_rolls": removed})


# ── SHP-02 출하 승인 ────────────────────────────────────────────────────
@router.get(nav.path_of("SHP-02"), response_class=HTMLResponse)                     # 화면 GET (조회 기능이 아닌 중메뉴)
def approvals(request: Request, user: rbac.User = rbac.require_screen("SHP-02")) -> HTMLResponse:
    waiting = _search("", "", "", REGISTERED, None, None)
    for s in waiting:
        s["summary"] = _summary(_rolls(s["shipment_id"]))
    done = _search("", "", "", APPROVED, None, None)[:50]
    return templating.render(request, "shp/approvals.html", {
        "waiting": waiting, "done": done, "number_rule": numbering.rule(numbering.COA),
    }, screen_id="SHP-02")


@router.post(nav.path_of("SHP-02") + "/{shipment_no}/approve")                       # F-SHP-05 출하 승인 (관리자만)
def approve_shipment(request: Request, shipment_no: str, user: rbac.User = rbac.require_fn("F-SHP-05")):
    shipment = _shipment(shipment_no)
    with conn.tx() as cur:                                # 승인 + COA 채번은 같이 성공하거나 같이 실패한다
        cur.execute("select status from shipment where shipment_id = %s for update", (shipment["shipment_id"],))
        status = cur.fetchone()["status"]
        if status != REGISTERED:
            reason = "이미 승인된 출하입니다" if status == APPROVED else "취소된 출하는 승인할 수 없습니다"
            raise http.validation_error(reason, fields=[{"name": shipment_no, "reason": f"상태 {status}"}])
        rolls = _rolls(shipment["shipment_id"])
        if not rolls:
            raise http.validation_error("롤이 담기지 않은 출하는 승인할 수 없습니다", fields=[{"name": shipment_no, "reason": "롤 0개"}])
        failed = [r["roll_no"] for r in rolls if r["inspection"] and r["inspection"]["result"] == FAIL]
        if failed:                                        # 스캔한 뒤에 불합격 판정이 들어온 롤 (D-305)
            raise http.validation_error("최신 검사가 불합격인 롤이 담겨 있어 승인할 수 없습니다",
                                        fields=[{"name": no, "reason": "최신 검사 불합격"} for no in failed])
        coa_no = numbering.next(numbering.COA, cur=cur)
        cur.execute("""update shipment set status = %s, approved_at = now(), approved_by = %s, coa_no = %s,
                              coa_issued_at = now(), updated_at = now(), updated_by = %s
                        where shipment_id = %s""",
                    (APPROVED, user.login_id, coa_no, user.login_id, shipment["shipment_id"]))
    audit.log_change(request, user, "F-SHP-05", f"shipment:{shipment_no}", f"출하 승인 — COA {coa_no} · 롤 {len(rolls)}개")
    return http.saved(request, f"출하를 승인했습니다 — {shipment_no} · COA {coa_no}",
                      data={"shipment_no": shipment_no, "coa_no": coa_no, "roll_count": len(rolls)})


# ── SHP-03 COA ──────────────────────────────────────────────────────────
@router.get(nav.path_of("SHP-03"), response_class=HTMLResponse)                     # F-SHP-06 COA 조회 = 화면 GET
def coa_list(request: Request, shipment_no: str = "", job_no: str = "", customer: str = "", date_from: str = "",
             date_to: str = "", user: rbac.User = rbac.require_fn("F-SHP-06")) -> HTMLResponse:
    d1, d2 = stats.parse_date(date_from, "출하일 시작"), stats.parse_date(date_to, "출하일 끝")
    rows = _search(shipment_no, job_no, customer, "", d1, d2, statuses=(APPROVED, REGISTERED))   # 취소된 출하는 COA 대상이 아니다
    return templating.render(request, "shp/coa.html", {
        "rows": rows, "limit": LIST_LIMIT, "not_issued": NOT_ISSUED,
        "q": {"shipment_no": shipment_no, "job_no": job_no, "customer": customer, "date_from": date_from, "date_to": date_to},
    }, screen_id="SHP-03")


@router.get(nav.path_of("SHP-03") + "/{shipment_no}/print", response_class=HTMLResponse)   # F-SHP-07 COA 출력
def coa_print(request: Request, shipment_no: str, user: rbac.User = rbac.require_fn("F-SHP-07")) -> HTMLResponse:
    shipment = _shipment(shipment_no)
    if shipment["status"] != APPROVED:
        raise http.validation_error("승인되지 않은 출하는 COA 를 출력할 수 없습니다",
                                    fields=[{"name": shipment_no, "reason": f"상태 {shipment['status']} — COA {NOT_ISSUED}"}])
    rolls = _rolls(shipment["shipment_id"])
    return templating.render(request, "shp/coa_print.html", {
        "s": shipment, "rolls": rolls, "summary": _summary(rolls),
        # 바코드는 출하 LOT 번호 — 스캔하면 그 출하(와 역방향 추적)가 열린다 (G-14 · D-305)
        "barcode": printing.barcode_svg(shipment["shipment_no"]),
    }, screen_id="SHP-03")
