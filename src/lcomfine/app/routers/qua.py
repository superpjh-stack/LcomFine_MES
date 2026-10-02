"""qua 라우터 — 품질 검사 기록 (기능 6) · 담당 개발3 · 프로세스 P7.

쓰는 저장소: **D7 (`inspection` · `inspection_defect`) 뿐이다**(G-05). 롤에 판정을 적지 않는다 —
롤의 판정은 그 롤의 **최신 검사**(검사 일시가 가장 늦은 것, 같으면 나중에 등록한 것)에서 읽는다.
Job 키는 롤에서 복사한다(D-16). 출하 승인된 롤의 검사는 등록·수정·삭제할 수 없다(D-304 — COA 는 저장하지 않고
검사 결과에서 매번 만들기 때문에, 발행된 뒤에 검사가 바뀌면 COA 가 바뀐다).

  QUA-01 검사 결과 → /qua/inspections
      F-QUA-01 검사 결과 등록 [등록] POST /qua/inspections
      F-QUA-02 검사 결과 수정 [수정] POST /qua/inspections/{id}
      F-QUA-03 검사 결과 삭제 [삭제] POST /qua/inspections/{id}/delete
      F-QUA-04 검사 결과 조회 [조회] GET /qua/inspections
  QUA-02 불량 집계 → /qua/defect-stats
      F-QUA-05 불량 유형별 집계 조회 [조회] GET /qua/defect-stats        (`stats.defect_by_type`)
      F-QUA-06 불량 롤 조회 [조회] GET /qua/defect-stats/rolls           (`stats.defect_rolls` — 집계의 내역)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import lineage, nav, rbac, stats, templating
from ..util import audit, http

router = APIRouter()

PASS, FAIL = "합격", "불합격"
RESULTS: tuple[str, ...] = (PASS, FAIL)
LIST_LIMIT = 500
#: `inspection.delta_e` 는 numeric(7,2) — 소수 둘째 자리로 맞춘 값이 이 값 이상이면 컬럼에 담기지 않는다
DELTA_E_SCALE, DELTA_E_LIMIT = Decimal("0.01"), Decimal("100000")

#: 롤 하나의 최신 검사 — 그 롤의 판정이다. `{roll}` 자리에 롤 키 식을 넣는다 (출하·COA 도 이 식을 쓴다)
LATEST_OF_ROLL = """(select m.inspection_id from inspection m where m.roll_id = {roll}
                      order by m.inspected_at desc, m.inspection_id desc limit 1)"""

_DEFECT_TEXT = """(select string_agg(d.defect_name || coalesce(' · ' || nullif(x.position, ''), ''), ' / '
                                     order by x.inspection_defect_id)
                     from inspection_defect x join defect_code d on d.defect_code_id = x.defect_code_id
                    where x.inspection_id = n.inspection_id)"""


def latest_inspections(roll_ids: list[int]) -> dict[int, dict]:
    """롤 → 그 롤의 최신 검사(ΔE · 판정 · 불량 글자 · 불량 수). 검사가 없는 롤은 결과에 없다(화면은 `미수집`)."""
    if not roll_ids:
        return {}
    rows = conn.q(f"""
        select n.roll_id, n.inspection_id, n.delta_e, n.result, n.inspected_at, n.inspected_by,
               {_DEFECT_TEXT} as defects,
               (select count(*)::int from inspection_defect x where x.inspection_id = n.inspection_id) as defect_count
          from inspection n
         where n.roll_id = any(%s) and n.inspection_id = {LATEST_OF_ROLL.format(roll='n.roll_id')}""", (roll_ids,))
    return {r["roll_id"]: r for r in rows}


def approved_shipment_of(roll_id: int) -> str | None:
    """그 롤이 **승인된** 출하에 실려 있으면 그 출하 LOT 번호. (계보를 읽기만 한다)"""
    row = conn.q1("""select s.shipment_no from roll_genealogy g
                       join shipment s on s.shipment_id = g.child_shipment_id
                      where g.parent_roll_id = %s and s.status = '승인'""", (roll_id,))
    return row["shipment_no"] if row else None


# ── 스캔 진입 (D-201) ───────────────────────────────────────────────────
def scan_failure(request: Request, problem: Exception) -> dict:
    """GET 스캔 진입(`?no=`)에서 번호를 못 찾았을 때 — JSON 은 422 를 그대로 올리고, 브라우저는 **같은 화면**을 422 로
    다시 그린다(오류 문장이 크게 보이고 스캔칸이 남아 포커스를 잡는다 — 다음 스캔을 막지 않는다). 돌려주는 값은 화면에 넘길 오류.
    `problem` 은 아직 올리지 않은 `http.validation_error(...)` 다 — 올린 것을 `except` 로 받아 가르지 않는다.
    출하 화면(`shp.py`)도 이것을 쓴다."""
    if not http.wants_html(request):
        raise problem
    detail = getattr(problem, "detail", None) or {}
    return {"message": detail.get("message", ""), "fields": detail.get("fields") or []}


def roll_problem(roll_no: str, node: lineage.Node | None) -> Exception | None:
    """`lineage.resolve(roll_no)` 의 결과가 롤이 아니면 그 사유(422) — **올리지 않고 돌려준다.** 롤이면 None.
    스캔 진입 GET 은 이것을 `scan_failure` 에 넘기고, 등록 POST 는 `scanned_roll` 이 올린다."""
    if node is None:
        return http.validation_error("없는 롤입니다", fields=[{"name": "롤 번호", "reason": roll_no}])
    if node.kind != lineage.ROLL:
        return http.validation_error("롤 번호가 아닙니다", fields=[{"name": roll_no, "reason": node.label}])
    return None


def scanned_roll(roll_no: str) -> lineage.Node:
    """사용자가 입력·스캔한 롤 번호 → 롤 노드. 다른 스캔 화면처럼 `lineage.resolve` 로 찾는다
    (앞뒤 공백 제거 · 소문자로 들어오면 대문자로도 찾는다, D-201). 없는 번호 · 롤이 아닌 번호는 422."""
    node = lineage.resolve(roll_no)
    problem = roll_problem(roll_no, node)
    if problem is not None:
        raise problem
    return node


# ── 입력값 ──────────────────────────────────────────────────────────────
def _delta_e(text: str | None) -> Decimal | None:
    """ΔE — 비우면 None. 숫자가 아니거나 음수거나 컬럼(numeric(7,2))에 담기지 않는 값은 422(어느 칸인지 알려 준다).
    소수 셋째 자리부터는 DB 가 하듯 반올림해 둘째 자리로 맞춘다(99999.999 → 100000.00 은 범위 밖)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        raise http.validation_error("ΔE 는 숫자로 입력해 주세요", fields=[{"name": "ΔE", "reason": text}]) from None
    if not value.is_finite():
        raise http.validation_error("ΔE 는 숫자로 입력해 주세요", fields=[{"name": "ΔE", "reason": text}])
    if value < 0:
        raise http.validation_error("ΔE 는 0 이상의 숫자입니다", fields=[{"name": "ΔE", "reason": text}])
    if value >= DELTA_E_LIMIT:                       # 자릿수가 아주 큰 값(1e999)은 맞추기 전에 걸러 낸다
        raise http.validation_error("ΔE 값이 너무 큽니다", fields=[{"name": "ΔE", "reason": f"{text} — 100000 미만이어야 합니다"}])
    value = value.quantize(DELTA_E_SCALE, rounding=ROUND_HALF_UP)
    if value >= DELTA_E_LIMIT:
        raise http.validation_error("ΔE 값이 너무 큽니다", fields=[{"name": "ΔE", "reason": f"{text} — 100000 미만이어야 합니다"}])
    return value


def _result(text: str | None) -> str:
    text = (text or "").strip()
    if text not in RESULTS:
        raise http.validation_error("판정은 합격 또는 불합격입니다", fields=[{"name": "판정", "reason": text or "비어 있음"}])
    return text


def _defect_rows(codes: list[str], positions: list[str], keep: set[str] = frozenset()) -> list[tuple[int, str | None]]:
    """폼의 불량 행(불량 유형 · 위치)을 (defect_code_id, 위치) 로. 불량 유형이 빈 행은 버린다(빈 입력 줄).

    불량 유형은 기준정보의 불량코드여야 한다. 사용 중지된 코드는 새로 고를 수 없다(`keep` = 그 검사에 이미 적혀 있던 코드는 둔다).
    """
    known = {r["defect_code"]: r for r in conn.q("select defect_code_id, defect_code, use_yn from defect_code")}
    out, bad = [], []
    for i, raw in enumerate(codes):
        code = (raw or "").strip()
        position = (positions[i] if i < len(positions) else "").strip() or None
        if not code:
            if position:
                bad.append({"name": f"불량 행 {i + 1}", "reason": "위치만 있고 불량 유형이 없다"})
            continue
        row = known.get(code)
        if row is None:
            bad.append({"name": f"불량 행 {i + 1}", "reason": f"없는 불량코드 {code}"})
        elif row["use_yn"] != "Y" and code not in keep:
            bad.append({"name": f"불량 행 {i + 1}", "reason": f"사용하지 않는 불량코드 {code}"})
        else:
            out.append((row["defect_code_id"], position))
    if bad:
        raise http.validation_error("불량 행을 확인해 주세요", fields=bad)
    return out


#: 경로의 검사 키가 가질 수 있는 가장 큰 값 (bigint) — 이보다 큰 숫자는 그런 검사가 없다
_ID_MAX = 2 ** 63 - 1


def _inspection(inspection_id: str) -> dict:
    """경로의 키로 검사 한 건. 없으면 404 — 숫자가 아닌 키도 "그런 검사는 없다" 로 404 다(다른 화면과 같게)."""
    key = (inspection_id or "").strip()
    if not (key.isascii() and key.isdigit()) or int(key) > _ID_MAX:
        raise http.not_found()
    row = conn.q1("""select n.*, r.roll_no, j.job_no from inspection n
                       join roll r on r.roll_id = n.roll_id join job j on j.job_id = n.job_id
                      where n.inspection_id = %s""", (int(key),))
    if row is None:
        raise http.not_found()
    return row


def _guard_approved(roll_id: int, roll_no: str, action: str) -> None:
    shipment_no = approved_shipment_of(roll_id)
    if shipment_no:
        raise http.validation_error(f"출하 승인된 롤의 검사는 {action}할 수 없습니다",
                                    fields=[{"name": roll_no, "reason": f"출하 LOT {shipment_no} 승인됨 (COA 발행)"}])


# ── QUA-01 검사 결과 ────────────────────────────────────────────────────
@router.get(nav.path_of("QUA-01"), response_class=HTMLResponse)                     # F-QUA-04 검사 결과 조회 = 화면 GET
def inspections(request: Request, no: str = "", roll_no: str = "", job_no: str = "", date_from: str = "",
                date_to: str = "", result: str = "", edit: str = "",
                user: rbac.User = rbac.require_fn("F-QUA-04")) -> HTMLResponse:
    d1, d2 = stats.parse_date(date_from, "검사일 시작"), stats.parse_date(date_to, "검사일 끝")
    if result and result not in RESULTS:
        raise http.validation_error("판정은 합격 또는 불합격입니다", fields=[{"name": "판정", "reason": result}])
    scanned, scan_error = None, None
    no = no.strip()
    if no:                                   # 라벨 바코드로 들어온 롤 (`?no=`) — 그 롤의 검사만 보이고 등록칸에 번호가 채워진다
        node = lineage.resolve(no)
        problem = roll_problem(no, node)
        if problem is not None:              # 없는 번호 — 브라우저면 이 화면을 422 로 다시 그린다 (스캔칸이 남는다, D-201)
            scan_error, no = scan_failure(request, problem), ""
        else:
            scanned = conn.q1("""select v.roll_id, v.roll_no, v.process_type, v.state, j.job_no, i.item_name
                                   from v_roll_state v join job j on j.job_id = v.job_id join item i on i.item_id = j.item_id
                                  where v.roll_id = %s""", (node.id,))
            no = scanned["roll_no"]
    rows = conn.q(f"""
        select n.inspection_id, n.delta_e, n.result, n.inspected_at, n.inspected_by, n.note,
               r.roll_no, r.process_type, j.job_no, i.item_name,
               {_DEFECT_TEXT} as defects,
               n.inspection_id = {LATEST_OF_ROLL.format(roll='n.roll_id')} as is_latest
          from inspection n
          join roll r on r.roll_id = n.roll_id
          join job j on j.job_id = n.job_id
          join item i on i.item_id = j.item_id
         where (%(exact)s::text is null or r.roll_no = %(exact)s::text)
           and (%(roll_no)s::text is null or r.roll_no ilike '%%' || %(roll_no)s::text || '%%')
           and (%(job_no)s::text is null or j.job_no ilike '%%' || %(job_no)s::text || '%%')
           and (%(d1)s::date is null or n.inspected_at::date >= %(d1)s::date)
           and (%(d2)s::date is null or n.inspected_at::date <= %(d2)s::date)
           and (%(result)s::text is null or n.result = %(result)s::text)
         order by n.inspected_at desc, n.inspection_id desc
         limit {LIST_LIMIT}""",
        {"exact": no or None, "roll_no": roll_no.strip() or None, "job_no": job_no.strip() or None,
         "d1": d1, "d2": d2, "result": result or None})
    editing = None
    if edit.strip():
        if not (edit.strip().isascii() and edit.strip().isdigit()) or int(edit) > _ID_MAX:
            raise http.validation_error("없는 검사입니다", fields=[{"name": "검사", "reason": edit}])
        editing = conn.q1("""select n.inspection_id, n.delta_e, n.result, n.note, r.roll_no, j.job_no
                               from inspection n join roll r on r.roll_id = n.roll_id join job j on j.job_id = n.job_id
                              where n.inspection_id = %s""", (int(edit),))
        if editing is None:
            raise http.validation_error("없는 검사입니다", fields=[{"name": "검사", "reason": edit}])
        editing["defects"] = conn.q("""select d.defect_code, x.position from inspection_defect x
                                         join defect_code d on d.defect_code_id = x.defect_code_id
                                        where x.inspection_id = %s order by x.inspection_defect_id""", (int(edit),))
    defect_codes = conn.q("select defect_code, defect_name, use_yn from defect_code order by defect_code")
    return templating.render(request, "qua/inspections.html", {
        "rows": rows, "limit": LIST_LIMIT, "scanned": scanned, "scan_error": scan_error, "editing": editing,
        "results": RESULTS, "defect_codes": defect_codes,
        "q": {"no": no, "roll_no": roll_no, "job_no": job_no, "date_from": date_from, "date_to": date_to, "result": result},
    }, screen_id="QUA-01", status_code=422 if scan_error else 200)


@router.post(nav.path_of("QUA-01"))                                                  # F-QUA-01 검사 결과 등록
def create_inspection(request: Request, roll_no: str = Form(""), delta_e: str = Form(""), result: str = Form(""),
                      note: str = Form(""), defect_code: list[str] = Form(default=[]),
                      position: list[str] = Form(default=[]),
                      user: rbac.User = rbac.require_fn("F-QUA-01")):
    roll_no = roll_no.strip()
    if not roll_no:
        raise http.validation_error("롤 번호를 스캔해 주세요", fields=[{"name": "롤 번호", "reason": "비어 있음"}])
    roll = conn.q1("select roll_id, roll_no, job_id from roll where roll_id = %s", (scanned_roll(roll_no).id,))
    de, res, defects = _delta_e(delta_e), _result(result), _defect_rows(defect_code, position)
    _guard_approved(roll["roll_id"], roll["roll_no"], "등록")
    with conn.tx() as cur:
        cur.execute("""insert into inspection (roll_id, job_id, delta_e, result, inspected_by, note)
                       values (%s, %s, %s, %s, %s, %s) returning inspection_id""",
                    (roll["roll_id"], roll["job_id"], de, res, user.login_id, note.strip() or None))
        inspection_id = cur.fetchone()["inspection_id"]
        for defect_code_id, pos in defects:
            cur.execute("insert into inspection_defect (inspection_id, defect_code_id, position) values (%s, %s, %s)",
                        (inspection_id, defect_code_id, pos))
    audit.log_change(request, user, "F-QUA-01", f"inspection:{inspection_id} roll:{roll['roll_no']}",
                     f"검사 결과 등록 — {res} · 불량 {len(defects)}행")
    return http.saved(request, f"검사 결과를 등록했습니다 — {roll['roll_no']} {res}",
                      data={"inspection_id": inspection_id, "roll_no": roll["roll_no"], "result": res})


@router.post(nav.path_of("QUA-01") + "/{inspection_id}")                             # F-QUA-02 검사 결과 수정
def update_inspection(request: Request, inspection_id: str, delta_e: str = Form(""), result: str = Form(""),
                      note: str = Form(""), defect_code: list[str] = Form(default=[]),
                      position: list[str] = Form(default=[]),
                      user: rbac.User = rbac.require_fn("F-QUA-02")):
    row = _inspection(inspection_id)
    inspection_id = row["inspection_id"]
    kept = {r["defect_code"] for r in conn.q(
        """select d.defect_code from inspection_defect x join defect_code d on d.defect_code_id = x.defect_code_id
            where x.inspection_id = %s""", (inspection_id,))}
    de, res, defects = _delta_e(delta_e), _result(result), _defect_rows(defect_code, position, kept)
    _guard_approved(row["roll_id"], row["roll_no"], "수정")
    with conn.tx() as cur:                                   # 롤(roll_id · job_id)은 바꾸지 않는다
        cur.execute("""update inspection set delta_e = %s, result = %s, note = %s, updated_at = now(), updated_by = %s
                        where inspection_id = %s""", (de, res, note.strip() or None, user.login_id, inspection_id))
        cur.execute("delete from inspection_defect where inspection_id = %s", (inspection_id,))
        for defect_code_id, pos in defects:
            cur.execute("insert into inspection_defect (inspection_id, defect_code_id, position) values (%s, %s, %s)",
                        (inspection_id, defect_code_id, pos))
    audit.log_change(request, user, "F-QUA-02", f"inspection:{inspection_id} roll:{row['roll_no']}",
                     f"검사 결과 수정 — {row['result']} → {res} · 불량 {len(defects)}행")
    return http.saved(request, f"검사 결과를 수정했습니다 — {row['roll_no']} {res}", back=nav.path_of("QUA-01"),
                      data={"inspection_id": inspection_id, "roll_no": row["roll_no"], "result": res})


@router.post(nav.path_of("QUA-01") + "/{inspection_id}/delete")                      # F-QUA-03 검사 결과 삭제
def delete_inspection(request: Request, inspection_id: str, user: rbac.User = rbac.require_fn("F-QUA-03")):
    row = _inspection(inspection_id)
    inspection_id = row["inspection_id"]
    _guard_approved(row["roll_id"], row["roll_no"], "삭제")
    with conn.tx() as cur:
        cur.execute("delete from inspection_defect where inspection_id = %s", (inspection_id,))
        cur.execute("delete from inspection where inspection_id = %s", (inspection_id,))
    audit.log_change(request, user, "F-QUA-03", f"inspection:{inspection_id} roll:{row['roll_no']}",
                     f"검사 결과 삭제 — {row['result']}")
    return http.saved(request, f"검사 결과를 삭제했습니다 — {row['roll_no']}", back=nav.path_of("QUA-01"),
                      data={"inspection_id": inspection_id, "roll_no": row["roll_no"]})


# ── QUA-02 불량 집계 ────────────────────────────────────────────────────
def _conditions(date_from: str, date_to: str, item_id: str) -> tuple:
    d1, d2 = stats.period(date_from, date_to)
    return d1, d2, stats.parse_item(item_id)


@router.get(nav.path_of("QUA-02"), response_class=HTMLResponse)                     # F-QUA-05 불량 유형별 집계 조회 = 화면 GET
def defect_stats(request: Request, date_from: str = "", date_to: str = "", item_id: str = "",
                 user: rbac.User = rbac.require_fn("F-QUA-05")) -> HTMLResponse:
    d1, d2, item = _conditions(date_from, date_to, item_id)
    rows = stats.defect_by_type(d1, d2, item)
    return templating.render(request, "qua/defect_stats.html", {
        "rows": rows, "detail": None, "date_from": d1, "date_to": d2, "item_id": item, "defect_code": "",
        "items": stats.item_options(), "total": sum(r["defect_count"] for r in rows),
    }, screen_id="QUA-02")


@router.get(nav.path_of("QUA-02") + "/rolls", response_class=HTMLResponse)          # F-QUA-06 불량 롤 조회
def defect_rolls(request: Request, defect_code: str = "", date_from: str = "", date_to: str = "", item_id: str = "",
                 user: rbac.User = rbac.require_fn("F-QUA-06")) -> HTMLResponse:
    d1, d2, item = _conditions(date_from, date_to, item_id)
    defect_code = defect_code.strip()
    if defect_code and conn.q1("select 1 from defect_code where defect_code = %s", (defect_code,)) is None:
        raise http.validation_error("없는 불량코드입니다", fields=[{"name": "불량 유형", "reason": defect_code}])
    rows = stats.defect_by_type(d1, d2, item)
    return templating.render(request, "qua/defect_stats.html", {
        "rows": rows, "detail": stats.defect_rolls(d1, d2, defect_code or None, item),
        "date_from": d1, "date_to": d2, "item_id": item, "defect_code": defect_code,
        "items": stats.item_options(), "total": sum(r["defect_count"] for r in rows),
        "defect_codes": conn.q("select defect_code, defect_name from defect_code order by defect_code"),
    }, screen_id="QUA-02")
