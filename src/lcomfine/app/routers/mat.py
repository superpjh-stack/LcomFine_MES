"""MAT 자재·입고 — MAT-010 원자재 입고 · MAT-020 불출 · MAT-030 제품 입고 · MAT-040 입고·불출 내역 (개발2).

추적 척추의 앞 두 고리를 만든다(`db-schema.md` §3):
  원자재 LOT(`numbering.next("MLOT")`) → 불출 행(`material_issue_line.work_order_id`) → 지시
  지시 → 제품 LOT(`numbering.next("PLOT")` · `product_lot.work_order_id` = 입고의 지시 — 복합 FK)
입고 LOT · 제품 LOT 은 `lot_stock` 에 검사대기로 잡힌다(D-510). 검사대기 · 보류 LOT 의 불출은 422(G-09).
입고 · 불출 · 제품 입고의 취소는 지우지 않고 `canceled_at` 표시로 남긴다(MAT-040).
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ...db import conn
from .. import nav, notify, numbering, rbac, templating
from ..util import audit, http
from .inv import (_bad, date_in, id_in, location_in, locations, num_in, open_work_orders, path_id, qs, text_in,
                  work_order_in)

router = APIRouter()

TRUTHY = ("1", "on", "true", "Y", "y")


def _rows(*cols: list[str]) -> list[tuple]:
    """같은 이름으로 여러 번 온 폼 칸들을 행으로 묶는다. 칸 수가 다르면 422."""
    n = max((len(c) for c in cols), default=0)
    if any(len(c) not in (0, n) for c in cols):
        raise http.validation_error("행 입력의 칸 수가 맞지 않습니다", fields=[{"name": "행", "reason": "칸 수 불일치"}])
    return [tuple((c[i] if c else "") for c in cols) for i in range(n)]


def _raw_items() -> list[dict]:
    return conn.q("""select id, item_code, item_name, spec, unit from item
                      where item_type = '원자재' and use_yn = 'Y' order by item_code""")


def _item_in(value: str, name: str = "품목", *, item_type: str = "원자재") -> dict:
    iid = id_in(value, name)
    row = conn.q1("select id, item_code, item_name, item_type, use_yn from item where id = %s", (iid,))
    if row is None:
        raise _bad(name, f"없는 품목입니다: {iid}")
    if row["item_type"] != item_type:
        raise _bad(name, f"{item_type} 품목이 아닙니다: {row['item_code']}")
    if row["use_yn"] != "Y":
        raise _bad(name, f"사용 중지 품목은 고를 수 없습니다: {row['item_code']}")
    return row


# ── MAT-010 원자재 입고 ────────────────────────────────────────────────────
@router.get(nav.path_of("MAT-010"), response_class=HTMLResponse)
def receipts(request: Request, user: rbac.User = rbac.require_fn("F-MAT-013")):
    f = {k: qs(request, k) for k in ("supplier", "lot", "label")}
    sql = """select r.id, r.supplier_name, r.received_on, r.note, r.canceled_at, r.created_by,
                    m.id as lot_id, m.lot_no, m.qty, m.supplier_lot_no, i.item_code, i.item_name,
                    (select string_agg(distinct s.status, '·') from lot_stock s
                      where s.lot_kind = '원자재' and s.lot_id = m.id) as stock_status
               from material_receipt r
               join material_lot m on m.receipt_id = r.id and m.parent_lot_id is null
               join item i on i.id = m.item_id
              where true"""
    params: list = []
    if f["supplier"]:
        sql += " and r.supplier_name ilike %s"
        params.append(f"%{f['supplier']}%")
    if f["lot"]:
        sql += " and m.lot_no ilike %s"
        params.append(f"%{f['lot']}%")
    rows = conn.q(sql + " order by r.received_on desc, r.id desc, m.lot_no limit 500", params)
    label = None
    if f["label"]:          # 라벨 출력 — 입고 건의 LOT 라벨 양식(읽기)
        rid = path_id(f["label"])
        label = conn.q("""select m.lot_no, m.qty, m.supplier_lot_no, i.item_code, i.item_name, i.unit,
                                 r.supplier_name, r.received_on
                            from material_lot m join material_receipt r on r.id = m.receipt_id
                            join item i on i.id = m.item_id
                           where r.id = %s and m.parent_lot_id is null order by m.lot_no""", (rid,))
        if not label:
            raise http.not_found()
    return templating.render(request, "mat/receipts.html", {
        "rows": rows, "f": f, "items": _raw_items(), "locations": locations(), "label": label,
        "next_lot": numbering.peek(numbering.MLOT) if numbering.rule(numbering.MLOT) else None,
        "can_w": rbac.can(user, "MAT-010", "W")}, screen_id="MAT-010")


@router.post("/mat/receipts")
def create_receipt(request: Request, supplier_name: str = Form(""), received_on: str = Form(""), note: str = Form(""),
                   item_id: list[str] = Form([]), qty: list[str] = Form([]), location_id: list[str] = Form([]),
                   supplier_lot_no: list[str] = Form([]),
                   user: rbac.User = rbac.require_fn("F-MAT-011")):
    supplier = text_in(supplier_name, "공급사", required=True)
    on = date_in(received_on, "입고일")
    memo = text_in(note, "비고")
    lines = []
    for n, (it, q, loc, slot) in enumerate(_rows(item_id, qty, location_id, supplier_lot_no), start=1):
        if not (it.strip() or q.strip()):
            continue                                    # 빈 행
        lines.append({"item": _item_in(it, f"{n}행 품목"), "qty": num_in(q, f"{n}행 수량"),
                      "loc": location_in(loc, f"{n}행 위치"), "slot": text_in(slot, f"{n}행 공급사 LOT")})
    if not lines:
        raise _bad("LOT 행", "필수 입력입니다", "입고 LOT 행을 하나 이상 입력하세요")
    with conn.tx() as cur:
        cur.execute("""insert into material_receipt (supplier_name, received_on, note, created_by)
                       values (%s, coalesce(%s, current_date), %s, %s) returning id""",
                    (supplier, on, memo, user.login_id))
        rid = cur.fetchone()["id"]
        lot_nos = []
        for ln in lines:
            no = numbering.next(numbering.MLOT, cur)
            cur.execute("""insert into material_lot (lot_no, receipt_id, item_id, qty, supplier_lot_no, created_by)
                           values (%s, %s, %s, %s, %s, %s) returning id""",
                        (no, rid, ln["item"]["id"], ln["qty"], ln["slot"], user.login_id))
            lot_id = cur.fetchone()["id"]
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                           values ('원자재', %s, %s, %s, '검사대기', %s)""", (lot_id, ln["loc"]["id"], ln["qty"], user.login_id))
            lot_nos.append(no)
        notify.emit(cur, "material_received", link=f"{nav.path_of('QC-010')}?receipt={rid}",
                    dedupe_key=f"material_received:{lot_nos[0]}",
                    text=f"원자재 입고 {len(lot_nos)} LOT ({lot_nos[0]}{' 외' if len(lot_nos) > 1 else ''}) — 입고검사 대기")
    resp = http.saved(request, f"원자재 입고를 등록했습니다 — LOT {', '.join(lot_nos)}",
                      data={"receipt_id": rid, "lot_nos": lot_nos})
    audit.log_change(request, user, "F-MAT-011", f"material_receipt:{rid}", f"입고 {supplier} LOT {', '.join(lot_nos)}")
    return resp


def _lot_untouched(cur, kind: str, lot_id: int, lot_qty: Decimal) -> str | None:
    """입고 그대로인가 — 불출 · 이동 · 분할 · 할당 · 출하가 없으면 None, 있으면 사유."""
    cur.execute("select count(*) as n, coalesce(sum(qty), 0) as qty, coalesce(sum(allocated_qty), 0) as alloc "
                "from lot_stock where lot_kind = %s and lot_id = %s", (kind, lot_id))
    s = cur.fetchone()
    cur.execute("select count(*) as n from stock_move where lot_kind = %s and (lot_id = %s or source_lot_id = %s)",
                (kind, lot_id, lot_id))
    moves = cur.fetchone()["n"]
    if moves or s["n"] != 1 or s["qty"] != lot_qty or s["alloc"]:
        return "이미 불출 · 이동 · 분할 · 할당 · 조정된 LOT 입니다"
    if kind == "원자재":
        cur.execute("select count(*) as n from material_issue_line where material_lot_id = %s", (lot_id,))
    else:
        cur.execute("select count(*) as n from shipment_line where product_lot_id = %s", (lot_id,))
    if cur.fetchone()["n"]:
        return "이미 불출 · 출하에 쓰인 LOT 입니다"
    return None


@router.post("/mat/receipts/{id}")
def update_receipt(request: Request, id: str, supplier_name: str = Form(""), received_on: str = Form(""),
                   note: str = Form(""), cancel: str = Form(""),
                   lot_id: list[str] = Form([]), qty: list[str] = Form([]), supplier_lot_no: list[str] = Form([]),
                   user: rbac.User = rbac.require_fn("F-MAT-012")):
    rid = path_id(id)
    rec = conn.q1("select * from material_receipt where id = %s", (rid,))
    if rec is None:
        raise http.not_found()
    if rec["canceled_at"]:
        raise _bad("입고", "취소된 입고는 고칠 수 없습니다")
    is_cancel = (cancel or "").strip() in TRUTHY
    supplier = text_in(supplier_name, "공급사") or rec["supplier_name"]
    on = date_in(received_on, "입고일") or rec["received_on"]
    memo = text_in(note, "비고")
    edits = []
    for n, (lid, q, slot) in enumerate(_rows(lot_id, qty, supplier_lot_no), start=1):
        if not lid.strip():
            continue
        edits.append((id_in(lid, f"{n}행 LOT"), num_in(q, f"{n}행 수량", required=False), text_in(slot, f"{n}행 공급사 LOT")))
    with conn.tx() as cur:
        cur.execute("select id, lot_no, qty from material_lot where receipt_id = %s and parent_lot_id is null for update", (rid,))
        lots = {r["id"]: r for r in cur.fetchall()}
        if is_cancel:
            for lot in lots.values():
                why = _lot_untouched(cur, "원자재", lot["id"], lot["qty"])
                if why:
                    raise _bad("취소", f"{lot['lot_no']}: {why} — 취소할 수 없습니다")
            cur.execute("update material_receipt set canceled_at = now(), canceled_by = %s, updated_at = now(), updated_by = %s "
                        "where id = %s", (user.login_id, user.login_id, rid))
            cur.execute("update material_lot set canceled_at = now(), canceled_by = %s, updated_at = now(), updated_by = %s "
                        "where receipt_id = %s", (user.login_id, user.login_id, rid))
            cur.execute("delete from lot_stock where lot_kind = '원자재' and lot_id = any(%s)", (list(lots),))
        else:
            cur.execute("""update material_receipt set supplier_name = %s, received_on = %s, note = coalesce(%s, note),
                                  updated_at = now(), updated_by = %s where id = %s""",
                        (supplier, on, memo, user.login_id, rid))
            for lid, q, slot in edits:
                lot = lots.get(lid)
                if lot is None:
                    raise _bad("LOT", f"이 입고의 LOT 이 아닙니다: {lid}")
                if q is not None and q != lot["qty"]:
                    why = _lot_untouched(cur, "원자재", lid, lot["qty"])
                    if why:
                        raise _bad("수량", f"{lot['lot_no']}: {why} — 수량을 고칠 수 없습니다 (재고 조정은 INV-030)")
                    cur.execute("update lot_stock set qty = %s, updated_at = now(), updated_by = %s "
                                "where lot_kind = '원자재' and lot_id = %s", (q, user.login_id, lid))
                cur.execute("""update material_lot set qty = coalesce(%s, qty), supplier_lot_no = coalesce(%s, supplier_lot_no),
                                      updated_at = now(), updated_by = %s where id = %s""", (q, slot, user.login_id, lid))
    resp = http.saved(request, "입고를 취소했습니다" if is_cancel else "입고를 고쳤습니다", data={"receipt_id": rid})
    audit.log_change(request, user, "F-MAT-012", f"material_receipt:{rid}", "입고 취소" if is_cancel else "입고 수정")
    return resp


# ── MAT-020 불출 ──────────────────────────────────────────────────────────
def _issuable(wo: str = "") -> list[dict]:
    """불출 화면의 LOT 목록 — 원자재 재고 행 전부(상태 함께). 가용이 아닌 LOT 은 화면에서 고를 수 없게 보인다."""
    return conn.q("""select s.id as stock_id, m.lot_no, i.item_code, i.item_name, l.id as location_id, l.location_code,
                            s.qty, s.allocated_qty, s.qty - s.allocated_qty as available_qty, s.status
                       from lot_stock s join material_lot m on m.id = s.lot_id
                       join item i on i.id = m.item_id join location l on l.id = s.location_id
                      where s.lot_kind = '원자재' and s.qty > 0 and m.canceled_at is null
                      order by s.status <> '가용', m.lot_no, l.location_code""")


@router.get(nav.path_of("MAT-020"), response_class=HTMLResponse)
def issues(request: Request, user: rbac.User = rbac.require_fn("F-MAT-023")):
    f = {k: qs(request, k) for k in ("wo", "lot")}
    sql = """select h.id as issue_id, h.issued_on, h.note, h.canceled_at, h.created_by,
                    l.id as line_id, w.work_order_no, m.lot_no, i.item_code, i.item_name, loc.location_code, l.qty
               from material_issue h
               join material_issue_line l on l.issue_id = h.id
               join work_order w on w.id = l.work_order_id
               join material_lot m on m.id = l.material_lot_id
               join item i on i.id = m.item_id
               join location loc on loc.id = l.location_id
              where true"""
    params: list = []
    if f["wo"]:
        sql += " and w.work_order_no ilike %s"
        params.append(f"%{f['wo']}%")
    if f["lot"]:
        sql += " and m.lot_no ilike %s"
        params.append(f"%{f['lot']}%")
    rows = conn.q(sql + " order by h.issued_on desc, h.id desc, l.id limit 500", params)
    return templating.render(request, "mat/issues.html", {
        "rows": rows, "f": f, "work_orders": open_work_orders(), "stock": _issuable(),
        "can_w": rbac.can(user, "MAT-020", "W")}, screen_id="MAT-020")


@router.post("/mat/issues")
def create_issue(request: Request, work_order_id: str = Form(""), work_order_no: str = Form(""),
                 issued_on: str = Form(""), note: str = Form(""),
                 lot_no: list[str] = Form([]), location_id: list[str] = Form([]), qty: list[str] = Form([]),
                 user: rbac.User = rbac.require_fn("F-MAT-021")):
    wo = work_order_in(work_order_id, work_order_no)
    on = date_in(issued_on, "불출일")
    memo = text_in(note, "비고")
    wanted = []
    for n, (no, loc, q) in enumerate(_rows(lot_no, location_id, qty), start=1):
        if not q.strip():
            continue                                   # 수량을 비운 행 = 고르지 않은 LOT
        no = text_in(no, f"{n}행 LOT 번호", required=True)
        wanted.append({"no": no, "loc": id_in(loc, f"{n}행 위치", required=False), "qty": num_in(q, f"{n}행 수량"), "n": n})
    if not wanted:
        raise _bad("불출 LOT", "필수 선택입니다", "불출할 LOT 과 수량을 하나 이상 입력하세요")
    with conn.tx() as cur:
        cur.execute("insert into material_issue (issued_on, note, created_by) values (coalesce(%s, current_date), %s, %s) "
                    "returning id", (on, memo, user.login_id))
        iid = cur.fetchone()["id"]
        done = []
        for w in wanted:
            label = f"{w['n']}행 LOT"
            cur.execute("select id, lot_no, canceled_at from material_lot where lot_no = %s", (w["no"],))
            lot = cur.fetchone()
            if lot is None:
                raise _bad(label, f"없는 원자재 LOT 번호입니다: {w['no']}")
            if lot["canceled_at"]:
                raise _bad(label, f"취소된 LOT 입니다: {w['no']}")
            if w["loc"] is None:
                cur.execute("select * from lot_stock where lot_kind = '원자재' and lot_id = %s and qty > 0 for update", (lot["id"],))
                cand = cur.fetchall()
                if len(cand) != 1:
                    raise _bad(label, f"{w['no']} 의 재고가 {'없습니다' if not cand else '여러 위치에 있습니다 — 위치를 고르세요'}")
                st = cand[0]
            else:
                cur.execute("select * from lot_stock where lot_kind = '원자재' and lot_id = %s and location_id = %s for update",
                            (lot["id"], w["loc"]))
                st = cur.fetchone()
                if st is None:
                    raise _bad(label, f"{w['no']} 의 재고가 그 위치에 없습니다")
            if st["status"] == "검사대기":
                raise _bad(label, f"검사대기 LOT 은 불출할 수 없습니다 — 입고검사(QC-010) 합격 뒤 불출합니다: {w['no']}")
            if st["status"] == "보류":
                raise _bad(label, f"보류(입고검사 불합격) LOT 은 불출할 수 없습니다: {w['no']}")
            avail = st["qty"] - st["allocated_qty"]
            if w["qty"] > avail:
                raise _bad(label, f"{w['no']} 의 가용 수량 {avail} 을(를) 넘습니다")
            cur.execute("""insert into material_issue_line (issue_id, material_lot_id, work_order_id, location_id, qty, created_by)
                           values (%s, %s, %s, %s, %s, %s) returning id""",
                        (iid, lot["id"], wo["id"], st["location_id"], w["qty"], user.login_id))
            line_id = cur.fetchone()["id"]
            cur.execute("update lot_stock set qty = qty - %s, updated_at = now(), updated_by = %s where id = %s",
                        (w["qty"], user.login_id, st["id"]))
            cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, from_location_id, qty, ref_table, ref_id, created_by)
                           values ('불출', '원자재', %s, %s, %s, 'material_issue_line', %s, %s)""",
                        (lot["id"], st["location_id"], w["qty"], line_id, user.login_id))
            done.append(w["no"])
        # 지시 발행 알림을 눌러 연 불출 화면에서 처리하면 닫힌다 (D-511 · notify.handle_by_link)
        for link in (f"{nav.path_of('MAT-020')}?wo={wo['work_order_no']}", nav.path_of("MAT-020")):
            notify.handle_by_link(cur, link, user)
    resp = http.saved(request, f"{wo['work_order_no']} 에 {len(done)} LOT 을 불출했습니다",
                      data={"issue_id": iid, "lot_nos": done, "work_order_no": wo["work_order_no"]})
    audit.log_change(request, user, "F-MAT-021", f"material_issue:{iid}", f"불출 {wo['work_order_no']} ← {', '.join(done)}")
    return resp


@router.post("/mat/issues/{id}")
def update_issue(request: Request, id: str, issued_on: str = Form(""), note: str = Form(""), cancel: str = Form(""),
                 user: rbac.User = rbac.require_fn("F-MAT-022")):
    """불출 수정 — 불출일 · 비고, 또는 취소(지우지 않고 표시 · 재고를 되돌리고 `불출 취소` 이동 행). LOT 을 바꾸려면 취소 뒤 다시 불출한다."""
    iid = path_id(id)
    head = conn.q1("select * from material_issue where id = %s", (iid,))
    if head is None:
        raise http.not_found()
    if head["canceled_at"]:
        raise _bad("불출", "취소된 불출은 고칠 수 없습니다")
    is_cancel = (cancel or "").strip() in TRUTHY
    on = date_in(issued_on, "불출일")
    memo = text_in(note, "비고")
    with conn.tx() as cur:
        if is_cancel:
            cur.execute("select * from material_issue_line where issue_id = %s", (iid,))
            for ln in cur.fetchall():
                cur.execute("update lot_stock set qty = qty + %s, updated_at = now(), updated_by = %s "
                            "where lot_kind = '원자재' and lot_id = %s and location_id = %s",
                            (ln["qty"], user.login_id, ln["material_lot_id"], ln["location_id"]))
                if cur.rowcount != 1:
                    raise _bad("취소", "되돌릴 재고 행이 없습니다")
                cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, to_location_id, qty, ref_table, ref_id, created_by)
                               values ('불출 취소', '원자재', %s, %s, %s, 'material_issue_line', %s, %s)""",
                            (ln["material_lot_id"], ln["location_id"], ln["qty"], ln["id"], user.login_id))
            cur.execute("update material_issue set canceled_at = now(), canceled_by = %s, updated_at = now(), updated_by = %s "
                        "where id = %s", (user.login_id, user.login_id, iid))
        else:
            cur.execute("""update material_issue set issued_on = coalesce(%s, issued_on), note = coalesce(%s, note),
                                  updated_at = now(), updated_by = %s where id = %s""", (on, memo, user.login_id, iid))
    resp = http.saved(request, "불출을 취소했습니다" if is_cancel else "불출을 고쳤습니다", data={"issue_id": iid})
    audit.log_change(request, user, "F-MAT-022", f"material_issue:{iid}", "불출 취소" if is_cancel else "불출 수정")
    return resp


# ── MAT-030 제품 입고 ──────────────────────────────────────────────────────
def default_receipt_qty(work_order_id: int) -> Decimal:
    """기본값 = 생산일보 완료(양품) 수량 합 − 이미 입고한 수량(취소 제외)."""
    row = conn.q1("""select (select coalesce(sum(good_qty), 0) from production_daily where work_order_id = %s)
                          - (select coalesce(sum(qty), 0) from product_receipt where work_order_id = %s and canceled_at is null)
                            as qty""", (work_order_id, work_order_id))
    return row["qty"]


@router.get(nav.path_of("MAT-030"), response_class=HTMLResponse)
def product_receipts(request: Request, user: rbac.User = rbac.require_fn("F-MAT-033")):
    f = {k: qs(request, k) for k in ("wo", "lot")}
    sql = """select pr.id, pr.received_on, pr.qty, pr.note, pr.canceled_at, pr.created_by,
                    w.work_order_no, p.lot_no, i.item_code, i.item_name, loc.location_code,
                    (select string_agg(distinct s.status, '·') from lot_stock s
                      where s.lot_kind = '제품' and s.lot_id = p.id) as stock_status
               from product_receipt pr
               join work_order w on w.id = pr.work_order_id
               join product_lot p on p.id = pr.product_lot_id
               join item i on i.id = p.item_id
               join location loc on loc.id = pr.location_id
              where true"""
    params: list = []
    if f["wo"]:
        sql += " and w.work_order_no ilike %s"
        params.append(f"%{f['wo']}%")
    if f["lot"]:
        sql += " and p.lot_no ilike %s"
        params.append(f"%{f['lot']}%")
    rows = conn.q(sql + " order by pr.received_on desc, pr.id desc limit 500", params)
    wos = open_work_orders()
    picked = None
    if f["wo"]:
        picked = next((w for w in wos if w["work_order_no"] == f["wo"]), None)
        if picked:
            picked = {**picked, "default_qty": default_receipt_qty(picked["id"])}
    return templating.render(request, "mat/product_receipts.html", {
        "rows": rows, "f": f, "work_orders": wos, "picked": picked, "locations": locations(),
        "can_w": rbac.can(user, "MAT-030", "W")}, screen_id="MAT-030")


@router.post("/mat/product-receipts")
def create_product_receipt(request: Request, work_order_id: str = Form(""), work_order_no: str = Form(""),
                           qty: str = Form(""), location_id: str = Form(""), received_on: str = Form(""),
                           note: str = Form(""),
                           user: rbac.User = rbac.require_fn("F-MAT-031")):
    wo = work_order_in(work_order_id, work_order_no)
    q = num_in(qty, "수량", required=False)
    if q is None:                                   # 비우면 일보 완료 수량 기본값
        q = default_receipt_qty(wo["id"])
        if q <= 0:
            raise _bad("수량", "생산일보 완료 수량(기존 입고 제외)이 없습니다 — 수량을 입력하세요")
    loc = location_in(location_id, "입고 위치")
    on = date_in(received_on, "입고일")
    memo = text_in(note, "비고")
    with conn.tx() as cur:
        no = numbering.next(numbering.PLOT, cur)
        cur.execute("""insert into product_lot (lot_no, item_id, work_order_id, qty, created_by)
                       values (%s, %s, %s, %s, %s) returning id""", (no, wo["item_id"], wo["id"], q, user.login_id))
        lot_id = cur.fetchone()["id"]
        cur.execute("""insert into product_receipt (work_order_id, product_lot_id, location_id, qty, received_on, note, created_by)
                       values (%s, %s, %s, %s, coalesce(%s, current_date), %s, %s) returning id""",
                    (wo["id"], lot_id, loc["id"], q, on, memo, user.login_id))
        prid = cur.fetchone()["id"]
        cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                       values ('제품', %s, %s, %s, '검사대기', %s)""", (lot_id, loc["id"], q, user.login_id))
        notify.emit(cur, "product_received", link=f"{nav.path_of('QC-020')}?lot={no}", dedupe_key=f"product_received:{no}",
                    text=f"제품 입고 {no} ({wo['work_order_no']} · {q}) — 제품검사 대기")
    resp = http.saved(request, f"제품 입고를 등록했습니다 — 제품 LOT {no}",
                      data={"product_receipt_id": prid, "product_lot_id": lot_id, "lot_no": no, "qty": str(q)})
    audit.log_change(request, user, "F-MAT-031", f"product_receipt:{no}", f"제품 입고 {wo['work_order_no']} {q}")
    return resp


@router.post("/mat/product-receipts/{id}")
def update_product_receipt(request: Request, id: str, qty: str = Form(""), received_on: str = Form(""),
                           note: str = Form(""), cancel: str = Form(""),
                           user: rbac.User = rbac.require_fn("F-MAT-032")):
    prid = path_id(id)
    rec = conn.q1("""select pr.*, p.lot_no, p.qty as lot_qty from product_receipt pr join product_lot p on p.id = pr.product_lot_id
                      where pr.id = %s""", (prid,))
    if rec is None:
        raise http.not_found()
    if rec["canceled_at"]:
        raise _bad("제품 입고", "취소된 입고는 고칠 수 없습니다")
    is_cancel = (cancel or "").strip() in TRUTHY
    q = num_in(qty, "수량", required=False)
    on = date_in(received_on, "입고일")
    memo = text_in(note, "비고")
    with conn.tx() as cur:
        if is_cancel or (q is not None and q != rec["qty"]):
            why = _lot_untouched(cur, "제품", rec["product_lot_id"], rec["lot_qty"])
            if why:
                raise _bad("제품 LOT", f"{rec['lot_no']}: {why} — {'취소' if is_cancel else '수량 수정'}할 수 없습니다")
        if is_cancel:
            cur.execute("update product_receipt set canceled_at = now(), canceled_by = %s, updated_at = now(), updated_by = %s "
                        "where id = %s", (user.login_id, user.login_id, prid))
            cur.execute("delete from lot_stock where lot_kind = '제품' and lot_id = %s", (rec["product_lot_id"],))
        else:
            if q is not None and q != rec["qty"]:
                cur.execute("update product_lot set qty = %s, updated_at = now(), updated_by = %s where id = %s",
                            (q, user.login_id, rec["product_lot_id"]))
                cur.execute("update lot_stock set qty = %s, updated_at = now(), updated_by = %s "
                            "where lot_kind = '제품' and lot_id = %s", (q, user.login_id, rec["product_lot_id"]))
            cur.execute("""update product_receipt set qty = coalesce(%s, qty), received_on = coalesce(%s, received_on),
                                  note = coalesce(%s, note), updated_at = now(), updated_by = %s where id = %s""",
                        (q, on, memo, user.login_id, prid))
    resp = http.saved(request, "제품 입고를 취소했습니다" if is_cancel else "제품 입고를 고쳤습니다",
                      data={"product_receipt_id": prid})
    audit.log_change(request, user, "F-MAT-032", f"product_receipt:{rec['lot_no']}",
                     "제품 입고 취소" if is_cancel else "제품 입고 수정")
    return resp


# ── MAT-040 입고·불출 내역 ──────────────────────────────────────────────────
HISTORY_SQL = """
select * from (
  select '원자재 입고' as kind, r.received_on as on_date, m.lot_no, i.item_code, i.item_name, r.supplier_name,
         null::text as work_order_no, m.qty, r.canceled_at is not null as canceled, r.created_by
    from material_receipt r join material_lot m on m.receipt_id = r.id and m.parent_lot_id is null
    join item i on i.id = m.item_id
  union all
  select '불출', h.issued_on, m.lot_no, i.item_code, i.item_name, r.supplier_name, w.work_order_no, l.qty,
         h.canceled_at is not null, h.created_by
    from material_issue h join material_issue_line l on l.issue_id = h.id
    join material_lot m on m.id = l.material_lot_id join material_receipt r on r.id = m.receipt_id
    join item i on i.id = m.item_id join work_order w on w.id = l.work_order_id
  union all
  select '제품 입고', pr.received_on, p.lot_no, i.item_code, i.item_name, null, w.work_order_no, pr.qty,
         pr.canceled_at is not null, pr.created_by
    from product_receipt pr join product_lot p on p.id = pr.product_lot_id
    join item i on i.id = p.item_id join work_order w on w.id = pr.work_order_id
) h where true"""

HISTORY_COLS = [("kind", "구분"), ("on_date", "일자"), ("lot_no", "LOT"), ("item_code", "품목 코드"), ("item_name", "품목명"),
                ("supplier_name", "공급사"), ("work_order_no", "작업지시"), ("qty", "수량"), ("canceled", "취소")]


@router.get(nav.path_of("MAT-040"), response_class=HTMLResponse)
def history(request: Request, user: rbac.User = rbac.require_fn("F-MAT-041")):
    f = {k: qs(request, k) for k in ("from", "to", "item", "supplier", "kind", "format")}
    d_from, d_to = date_in(f["from"], "시작일"), date_in(f["to"], "종료일")
    sql, params = HISTORY_SQL, []
    if d_from:
        sql += " and h.on_date >= %s"
        params.append(d_from)
    if d_to:
        sql += " and h.on_date <= %s"
        params.append(d_to)
    if f["item"]:
        sql += " and (h.item_code ilike %s or h.item_name ilike %s)"
        params += [f"%{f['item']}%"] * 2
    if f["supplier"]:
        sql += " and h.supplier_name ilike %s"
        params.append(f"%{f['supplier']}%")
    if f["kind"]:
        sql += " and h.kind = %s"
        params.append(f["kind"])
    rows = conn.q(sql + " order by h.on_date desc, h.kind, h.lot_no limit 2000", params)
    if f["format"] == "csv":                       # 엑셀 — 같은 조건의 CSV (엑셀이 연다 · UTF-8 BOM)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([c[1] for c in HISTORY_COLS])
        for r in rows:
            w.writerow([("취소" if r[k] else "") if k == "canceled" else ("" if r[k] is None else r[k])
                        for k, _ in HISTORY_COLS])
        audit.write_log(log_type=audit.VIEW, login_id=user.login_id, role_code=user.role_code, method="GET",
                        path=request.url.path, screen_id="MAT-040", function_id="F-MAT-041", detail="CSV 내려받기",
                        ip=audit.client_ip(request))
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=mat-history.csv"})
    if f["format"]:
        raise _bad("형식", f"모르는 형식입니다: {f['format'][:20]}")
    return templating.render(request, "mat/history.html", {"rows": rows, "f": f}, screen_id="MAT-040")
