"""mat 라우터 — 자재 · 입고 (기능 8) · 담당 개발2.

쓰는 저장소: D3 `material_lot`(입고·입고검사 — P3) · D5 `material_input`(자재 투입 스캔 — P5, D-13). 이 밖의 테이블에는 쓰지 않는다(G-05).
자재 투입은 D3 에 쓰지 않는다 — 원재료 LOT 의 잔량은 저장하지 않고 뷰 `v_material_lot_stock` 이 계산한다.
계보 `투입` 행은 여기서 만들지 않는다 — 작업 종료(F-POP-02) 때 `lineage.make_print_roll` 이 투입 스캔을 옮긴다.

  MAT-01 입고 → /mat/receipts
      F-MAT-01 입고 등록 [등록] POST /mat/receipts
      F-MAT-02 입고 조회 [조회] GET /mat/receipts
  MAT-02 입고검사 → /mat/inspections
      F-MAT-03 입고검사 결과 등록 [등록] POST /mat/inspections      ← 품질만 (범위 `입고검사`, D-14)
      F-MAT-04 입고검사 조회 [조회] GET /mat/inspections
  MAT-03 원재료 LOT → /mat/lots
      F-MAT-05 원재료 LOT 조회 [조회] GET /mat/lots
      F-MAT-06 원재료 LOT 라벨 출력 [출력] GET /mat/lots/{lot_no}/label
  MAT-04 자재 투입 → /mat/inputs
      F-MAT-07 자재 투입 스캔 [스캔] POST /mat/inputs
      F-MAT-08 자재 투입 조회 [조회] GET /mat/inputs
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, numbering, printing, rbac, templating
from ..util import audit, http
from .pop import (LIST_LIMIT, back_to, bad, date_of, decimal_of, int_of, label_page, open_works, scan_failure,
                  text_of, work_of)

router = APIRouter()

INSP_WAIT, INSP_PASS, INSP_FAIL = "대기", "합격", "불합격"
INSP_RESULTS = (INSP_PASS, INSP_FAIL)

_LOT_SELECT = """
select m.material_lot_id, m.lot_no, m.supplier_name, m.supplier_lot_no, m.received_qty, m.qty_unit, m.received_at,
       m.received_by, m.insp_status, m.insp_at, m.insp_by, m.insp_note, m.note,
       i.item_code, i.item_name, s.input_qty, s.remaining_qty, s.input_count
  from material_lot m
  join item i on i.item_id = m.item_id
  join v_material_lot_stock s on s.material_lot_id = m.material_lot_id
"""


def find_lot(lot_no: str) -> dict | None:
    """원재료 LOT 번호(스캔값) → LOT. 앞뒤 공백은 떼고 소문자로 들어온 값은 대문자로도 찾는다. 없으면 None."""
    lot_no = (lot_no or "").strip()
    if not lot_no:
        return None
    return conn.q1(_LOT_SELECT + " where m.lot_no = any(%s) order by (m.lot_no = %s) desc limit 1",
                   (sorted({lot_no, lot_no.upper()}), lot_no))


def _raw_item_options() -> list[tuple[str, str]]:
    return [(r["item_code"], f"{r['item_name']} [{r['item_code']}]") for r in conn.q(
        "select item_code, item_name from item where item_type = '원재료' and use_yn = 'Y' order by item_code")]


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ── MAT-01 입고 ─────────────────────────────────────────────────────────
@router.get(nav.path_of("MAT-01"), response_class=HTMLResponse)          # F-MAT-02 입고 조회
def receipt_list(request: Request, date_from: str = "", date_to: str = "", item_code: str = "", supplier: str = "",
                 user: rbac.User = rbac.require_fn("F-MAT-02")):
    d1, d2 = date_of(date_from, "입고일(부터)"), date_of(date_to, "입고일(까지)")
    where, params = [], []
    if d1:
        where.append("m.received_at::date >= %s")
        params.append(d1)
    if d2:
        where.append("m.received_at::date <= %s")
        params.append(d2)
    if item_code.strip():
        where.append("i.item_code = %s")
        params.append(item_code.strip())
    if supplier.strip():
        where.append("m.supplier_name ilike %s")
        params.append(_like(supplier.strip()))
    rows = conn.q(_LOT_SELECT + (" where " + " and ".join(where) if where else "")
                  + f" order by m.received_at desc, m.material_lot_id desc limit {LIST_LIMIT}", params)
    return templating.render(
        request, "mat/receipts.html",
        {"rows": rows, "f": {"date_from": date_from, "date_to": date_to, "item_code": item_code.strip(),
                             "supplier": supplier.strip()},
         "item_options": _raw_item_options(), "rule": numbering.rule(numbering.MAT_LOT),
         "can_create": user.can("F-MAT-01")},
        screen_id="MAT-01")


@router.post(nav.path_of("MAT-01"))                                       # F-MAT-01 입고 등록
def receipt_create(request: Request, item_code: str = Form(""), supplier_name: str = Form(""),
                   supplier_lot_no: str = Form(""), received_qty: str = Form(""), qty_unit: str = Form(""),
                   note: str = Form(""), user: rbac.User = rbac.require_fn("F-MAT-01")):
    """입고 1건 = 원재료 LOT 1개. LOT 번호는 `numbering.next('MAT_LOT')`, 검사 상태는 `대기` 로 시작한다."""
    code = text_of(item_code, "원재료 품목", required=True)
    item = conn.q1("select item_id, item_code, item_name, item_type, unit, use_yn from item where item_code = %s", (code,))
    if item is None:
        raise bad("없는 품목 코드입니다", "원재료 품목", code)
    if item["item_type"] != "원재료":
        raise bad("원재료 품목만 입고할 수 있습니다", "원재료 품목", f"{code} 은 {item['item_type']}")
    if item["use_yn"] != "Y":
        raise bad("사용하지 않는 품목입니다", "원재료 품목", code)
    qty = decimal_of(received_qty, "입고 수량", required=True, positive=True)
    unit = text_of(qty_unit, "단위") or item["unit"]
    if not unit:
        raise bad("단위를 입력해 주세요", "단위", "품목에 단위가 없다 — 입고할 때 적는다")
    with conn.tx() as cur:
        lot_no = numbering.next(numbering.MAT_LOT, cur=cur)
        cur.execute(
            """insert into material_lot (lot_no, item_id, supplier_name, supplier_lot_no, received_qty, qty_unit,
                                         received_by, insp_status, note)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (lot_no, item["item_id"], text_of(supplier_name, "공급처"), text_of(supplier_lot_no, "공급사 LOT"), qty, unit,
             user.login_id, INSP_WAIT, text_of(note, "비고")))
    audit.log_change(request, user, "F-MAT-01", f"material_lot:{lot_no}", f"입고 — {item['item_code']} {qty} {unit}")
    return http.saved(request, f"입고를 등록했습니다 — 원재료 LOT {lot_no} (입고검사 대기)",
                      data={"lot_no": lot_no, "insp_status": INSP_WAIT,
                            "label_url": f"{nav.path_of('MAT-03')}/{lot_no}/label"})


# ── MAT-02 입고검사 ─────────────────────────────────────────────────────
@router.get(nav.path_of("MAT-02"), response_class=HTMLResponse)          # F-MAT-04 입고검사 조회
def inspection_list(request: Request, no: str = "", insp_status: str = "",
                    user: rbac.User = rbac.require_fn("F-MAT-04")):
    """검사 대기·합격·불합격 LOT 목록(대기 먼저). `?no=<LOT 번호>` 는 라벨 바코드 스캔 진입 — 그 LOT 의 판정 칸이 열린다."""
    scan_error, lot = None, None
    if no.strip():
        lot = find_lot(no)
        if lot is None:
            scan_error = scan_failure(request, bad("없는 원재료 LOT 번호입니다", "LOT 번호", no.strip()))
    where, params = "", []
    if insp_status.strip():
        where, params = " where m.insp_status = %s", [insp_status.strip()]
    rows = conn.q(_LOT_SELECT + where + f"""
        order by case m.insp_status when '대기' then 0 else 1 end, coalesce(m.insp_at, m.received_at) desc,
                 m.material_lot_id desc limit {LIST_LIMIT}""", params)
    return templating.render(
        request, "mat/inspections.html",
        {"rows": rows, "lot": lot, "scan_error": scan_error, "no": no.strip(), "insp_status": insp_status.strip(),
         "status_options": [(s, s) for s in (INSP_WAIT, INSP_PASS, INSP_FAIL)], "can_inspect": user.can("F-MAT-03")},
        screen_id="MAT-02", status_code=422 if scan_error else 200)


@router.post(nav.path_of("MAT-02"))                                       # F-MAT-03 입고검사 결과 등록
def inspection_create(request: Request, lot_no: str = Form(""), result: str = Form(""), note: str = Form(""),
                      user: rbac.User = rbac.require_fn("F-MAT-03")):
    """원재료 LOT(스캔)에 합격/불합격과 비고를 적는다. 이미 투입된 LOT 의 판정은 바꿀 수 없다."""
    no = text_of(lot_no, "LOT 번호", required=True)
    verdict = text_of(result, "판정", required=True)
    if verdict not in INSP_RESULTS:
        raise bad("판정은 합격 또는 불합격입니다", "판정", verdict)
    memo = text_of(note, "비고")
    found = find_lot(no)
    if found is None:
        raise bad("없는 원재료 LOT 번호입니다", "LOT 번호", no)
    with conn.tx() as cur:
        cur.execute("select material_lot_id, lot_no, insp_status from material_lot where material_lot_id = %s for update",
                    (found["material_lot_id"],))
        lot = cur.fetchone()
        cur.execute("select count(*) as n from material_input where material_lot_id = %s", (lot["material_lot_id"],))
        if cur.fetchone()["n"] and verdict != lot["insp_status"]:
            raise bad("이미 투입된 LOT 의 판정은 바꿀 수 없습니다", lot["lot_no"], f"현재 {lot['insp_status']} · 투입 기록 있음")
        cur.execute("""update material_lot
                          set insp_status = %s, insp_at = now(), insp_by = %s, insp_note = %s,
                              updated_at = now(), updated_by = %s
                        where material_lot_id = %s""",
                    (verdict, user.login_id, memo, user.login_id, lot["material_lot_id"]))
    audit.log_change(request, user, "F-MAT-03", f"material_lot:{lot['lot_no']}", f"입고검사 {verdict}")
    return http.saved(request, f"입고검사 {verdict} — 원재료 LOT {lot['lot_no']}",
                      back=back_to(request, nav.path_of("MAT-02")), data={"lot_no": lot["lot_no"], "insp_status": verdict})


# ── MAT-03 원재료 LOT ───────────────────────────────────────────────────
@router.get(nav.path_of("MAT-03"), response_class=HTMLResponse)          # F-MAT-05 원재료 LOT 조회
def lot_list(request: Request, no: str = "", lot: str = "", item_code: str = "", insp_status: str = "",
             user: rbac.User = rbac.require_fn("F-MAT-05")):
    """LOT 번호·품목·검사 상태·잔량(입고량 − 투입량). `?no=<LOT 번호>` 는 라벨 바코드 스캔 진입 — 그 LOT 이 열린다."""
    scan_error, opened, opened_inputs, preview = None, None, [], None
    if no.strip():
        opened = find_lot(no)
        if opened is None:
            scan_error = scan_failure(request, bad("없는 원재료 LOT 번호입니다", "LOT 번호", no.strip()))
        else:
            opened_inputs = conn.q(
                """select mi.work_result_id, mi.input_qty, mi.qty_unit, mi.scanned_at, mi.scanned_by, j.job_no, r.roll_no
                     from material_input mi
                     join work_result w on w.work_result_id = mi.work_result_id
                     join job j on j.job_id = w.job_id
                     left join roll r on r.work_result_id = w.work_result_id
                    where mi.material_lot_id = %s order by mi.scanned_at desc""", (opened["material_lot_id"],))
            preview = printing.render_label(printing.material_lot_label(opened["lot_no"]))
    where, params = [], []
    if lot.strip():
        where.append("m.lot_no ilike %s")
        params.append(_like(lot.strip()))
    if item_code.strip():
        where.append("i.item_code = %s")
        params.append(item_code.strip())
    if insp_status.strip():
        where.append("m.insp_status = %s")
        params.append(insp_status.strip())
    rows = conn.q(_LOT_SELECT + (" where " + " and ".join(where) if where else "")
                  + f" order by m.received_at desc, m.material_lot_id desc limit {LIST_LIMIT}", params)
    return templating.render(
        request, "mat/lots.html",
        {"rows": rows, "opened": opened, "opened_inputs": opened_inputs, "preview": preview, "scan_error": scan_error,
         "f": {"lot": lot.strip(), "item_code": item_code.strip(), "insp_status": insp_status.strip()},
         "item_options": _raw_item_options(), "status_options": [(s, s) for s in (INSP_WAIT, INSP_PASS, INSP_FAIL)],
         "can_label": user.can("F-MAT-06")},
        screen_id="MAT-03", status_code=422 if scan_error else 200)


@router.get(nav.path_of("MAT-03") + "/{lot_no}/label", response_class=HTMLResponse)   # F-MAT-06 원재료 LOT 라벨 출력
def lot_label(request: Request, lot_no: str, user: rbac.User = rbac.require_fn("F-MAT-06")):
    if conn.q1("select 1 from material_lot where lot_no = %s", (lot_no,)) is None:
        raise http.not_found()
    label = printing.material_lot_label(lot_no)
    return label_page(request, [label], screen_id="MAT-03", back=back_to(request, f"{nav.path_of('MAT-03')}?no={lot_no}"),
                      title=f"{label.kind} — {lot_no}")


# ── MAT-04 자재 투입 ────────────────────────────────────────────────────
@router.get(nav.path_of("MAT-04"), response_class=HTMLResponse)          # F-MAT-08 자재 투입 조회
def input_list(request: Request, work_id: str = "", user: rbac.User = rbac.require_fn("F-MAT-08")):
    """실적별 투입 LOT 목록과 투입량. `?work_id=` 로 작업 실적을 고르면 그 실적에 스캔한다."""
    wid = int_of(work_id, "작업 실적")
    work = None
    if wid is not None:
        work = work_of(wid)
        if work is None:
            raise bad("없는 작업 실적입니다", "작업 실적", str(wid))
    where, params = (" where mi.work_result_id = %s", [wid]) if wid is not None else ("", [])
    rows = conn.q(f"""
        select mi.material_input_id, mi.work_result_id, mi.input_qty, mi.qty_unit, mi.scanned_at, mi.scanned_by,
               m.lot_no, m.insp_status, i.item_name, j.job_no, w.status as work_status, r.roll_no
          from material_input mi
          join material_lot m on m.material_lot_id = mi.material_lot_id
          join item i on i.item_id = m.item_id
          join work_result w on w.work_result_id = mi.work_result_id
          join job j on j.job_id = w.job_id
          left join roll r on r.work_result_id = w.work_result_id
          {where} order by mi.scanned_at desc, mi.material_input_id desc limit {LIST_LIMIT}""", params)
    return templating.render(
        request, "mat/inputs.html",
        {"rows": rows, "work": work, "work_id": wid, "works": open_works(), "can_scan": user.can("F-MAT-07")},
        screen_id="MAT-04")


@router.post(nav.path_of("MAT-04"))                                       # F-MAT-07 자재 투입 스캔
def input_scan(request: Request, work_id: str = Form(""), lot_no: str = Form(""), input_qty: str = Form(""),
               qty_unit: str = Form(""), user: rbac.User = rbac.require_fn("F-MAT-07")):
    """진행 중 실적에 원재료 LOT 바코드 한 번 = 한 건. 합격 LOT 만. 계보 행은 작업 종료 때 만들어진다(D-13)."""
    wid = int_of(work_id, "작업 실적", required=True)
    no = text_of(lot_no, "LOT 번호", required=True)
    qty = decimal_of(input_qty, "투입량", positive=True)
    lot = find_lot(no)
    if lot is None:
        raise bad("없는 원재료 LOT 번호입니다", "LOT 번호", no)
    with conn.tx() as cur:
        cur.execute("select work_result_id, status from work_result where work_result_id = %s for update", (wid,))
        w = cur.fetchone()
        if w is None:
            raise bad("없는 작업 실적입니다", "작업 실적", str(wid))
        if w["status"] != "진행":
            raise bad("진행 중인 작업에만 투입할 수 있습니다", "작업 실적", f"{wid} — 상태 {w['status']}")
        cur.execute("select insp_status, qty_unit from material_lot where material_lot_id = %s for share",
                    (lot["material_lot_id"],))
        now = cur.fetchone()
        if now["insp_status"] != INSP_PASS:
            raise bad(f"입고검사 {now['insp_status']} LOT 은 투입할 수 없습니다 (합격 LOT 만)", lot["lot_no"],
                      f"입고검사 {now['insp_status']}")
        cur.execute("select 1 from material_input where work_result_id = %s and material_lot_id = %s",
                    (wid, lot["material_lot_id"]))
        if cur.fetchone():
            raise bad("이 작업에 이미 스캔한 LOT 입니다", lot["lot_no"], "같은 실적에 중복 스캔")
        cur.execute("""insert into material_input (work_result_id, material_lot_id, input_qty, qty_unit, scanned_by)
                       values (%s, %s, %s, %s, %s) returning material_input_id""",
                    (wid, lot["material_lot_id"], qty, text_of(qty_unit, "단위") or (now["qty_unit"] if qty else None),
                     user.login_id))
        input_id = cur.fetchone()["material_input_id"]
    audit.log_change(request, user, "F-MAT-07", f"material_input:{input_id}", f"투입 — 실적 {wid} ← LOT {lot['lot_no']}")
    return http.saved(request, f"투입했습니다 — LOT {lot['lot_no']}",
                      data={"input_id": input_id, "work_id": wid, "lot_no": lot["lot_no"]})
