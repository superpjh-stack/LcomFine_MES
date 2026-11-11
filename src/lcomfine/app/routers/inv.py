"""INV 재고 — INV-010 LOT별 재고 조회 · INV-020 재고 이동 · INV-030 재고 조정·실사 (개발2).

재고 행 = `lot_stock`(구분, LOT, 위치). 가용 수량 = qty − allocated_qty (D-510). 상태 칩 4: 검사대기 · 가용 · 보류 · 할당
(「할당」은 상태 값이 아니라 allocated_qty > 0 일 때 붙는 칩 — 아키텍트 판정).
분할 이동은 새 LOT 행(원 번호 + `-01` 순번 · `parent_lot_id` = 원 LOT · D-509)과 `stock_move` 분할 행을 남긴다.
조정 이력(`stock_adjust`)은 수정 · 삭제하지 않는다(트리거).

입력 검증은 `app.util.forms`에서 가져온다. 공통 선택 목록·업무 검증은 `app.lookups`에서 가져온다.
헬퍼는 읽기만 한다 — 쓰기 SQL 은 그 기능의 라우터 파일에 있다(쓰기 경계 정적 스캔이 라우터마다 센다).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http
from ..lookups import (
    equipments, location_in, locations, lot_by_no, open_work_orders, work_order_in,
)
from ..util.forms import (
    INV_QTY_MAX as QTY_MAX,
    _bad, date_in, id_in, int_in, num_in, path_id, qs, text_in,
)

router = APIRouter()

LOT_KINDS = ("원자재", "제품")
STATUSES = ("가용", "검사대기", "보류")


# ── 재고 전용 입력·화면 헬퍼 ───────────────────────────────────────────


def kind_in(value: str | None) -> str:
    v = (value or "").strip()
    if v not in LOT_KINDS:
        raise _bad("LOT 구분", "원자재 또는 제품을 고르세요")
    return v


def _wants_html(request: Request) -> bool:
    return http.wants_html(request)


# ── INV-010 LOT별 재고 조회 ─────────────────────────────────────────────────
STOCK_SELECT = """
select s.id, s.lot_kind, s.lot_id, coalesce(m.lot_no, p.lot_no) as lot_no,
       i.item_code, i.item_name, wh.warehouse_code, wh.warehouse_name, l.id as location_id, l.location_code,
       s.qty, s.allocated_qty, s.qty - s.allocated_qty as available_qty, s.status,
       coalesce(m.parent_lot_id, p.parent_lot_id) as parent_lot_id
  from lot_stock s
  left join material_lot m on s.lot_kind = '원자재' and m.id = s.lot_id
  left join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
  join item i on i.id = coalesce(m.item_id, p.item_id)
  join location l on l.id = s.location_id
  join warehouse wh on wh.id = l.warehouse_id
 where m.canceled_at is null"""


@router.get(nav.path_of("INV-010"), response_class=HTMLResponse)
def stock(request: Request, user: rbac.User = rbac.require_screen("INV-010")):
    f = {k: qs(request, k) for k in ("item", "warehouse", "lot", "status", "kind")}
    if f["status"] and f["status"] not in (*STATUSES, "할당"):
        raise _bad("상태", f"모르는 상태입니다: {f['status'][:20]}")
    if f["kind"] and f["kind"] not in LOT_KINDS:
        raise _bad("LOT 구분", f"모르는 구분입니다: {f['kind'][:20]}")
    sql, params = STOCK_SELECT, []
    if f["item"]:
        sql += " and (i.item_code ilike %s or i.item_name ilike %s)"
        params += [f"%{f['item']}%"] * 2
    if f["warehouse"]:
        sql += " and (wh.warehouse_code ilike %s or wh.warehouse_name ilike %s)"
        params += [f"%{f['warehouse']}%"] * 2
    if f["lot"]:
        sql += " and coalesce(m.lot_no, p.lot_no) ilike %s"
        params.append(f"%{f['lot']}%")
    if f["kind"]:
        sql += " and s.lot_kind = %s"
        params.append(f["kind"])
    if f["status"] == "할당":
        sql += " and s.allocated_qty > 0"
    elif f["status"]:
        sql += " and s.status = %s"
        params.append(f["status"])
    rows = conn.q(sql + " order by s.lot_kind, lot_no, l.location_code", params)
    totals = {"qty": sum((r["qty"] for r in rows), Decimal(0)), "allocated": sum((r["allocated_qty"] for r in rows), Decimal(0)),
              "available": sum((r["available_qty"] for r in rows), Decimal(0))}
    return templating.render(request, "inv/stock.html", {"rows": rows, "f": f, "statuses": STATUSES, "kinds": LOT_KINDS,
                                                         "totals": totals}, screen_id="INV-010")


# ── INV-020 재고 이동 · 분할 ─────────────────────────────────────────────────
def _stock_row(cur, kind: str, lot_id: int, location_id: int, *, lock: bool = True) -> dict | None:
    cur.execute("select * from lot_stock where lot_kind = %s and lot_id = %s and location_id = %s"
                + (" for update" if lock else ""), (kind, lot_id, location_id))
    return cur.fetchone()


def _split_no(cur, table: str, parent: dict) -> str:
    """원 LOT 번호 + `-NN` 분할 순번 (D-509 · 정본 INV-020). 순번 = 그 LOT 의 분할 자식 수 + 1 (이미 있으면 다음)."""
    cur.execute(f"select lot_no from {table} where parent_lot_id = %s", (parent["id"],))
    used = {r["lot_no"] for r in cur.fetchall()}
    n = len(used) + 1
    while True:
        no = f"{parent['lot_no']}-{n:02d}"
        cur.execute(f"select 1 from {table} where lot_no = %s", (no,))
        if no not in used and cur.fetchone() is None:
            return no
        n += 1


@router.get(nav.path_of("INV-020"), response_class=HTMLResponse)
def moves(request: Request, user: rbac.User = rbac.require_screen("INV-020")):
    f = {k: qs(request, k) for k in ("lot", "location")}
    sql = """select mv.id, mv.move_kind, mv.lot_kind, coalesce(m.lot_no, p.lot_no) as lot_no,
                    coalesce(sm.lot_no, sp.lot_no) as source_lot_no,
                    fl.location_code as from_code, tl.location_code as to_code, mv.from_location_id, mv.to_location_id,
                    mv.qty, mv.moved_at, mv.note, mv.created_by, mv.ref_table
               from stock_move mv
               left join material_lot m on mv.lot_kind = '원자재' and m.id = mv.lot_id
               left join product_lot p on mv.lot_kind = '제품' and p.id = mv.lot_id
               left join material_lot sm on mv.lot_kind = '원자재' and sm.id = mv.source_lot_id
               left join product_lot sp on mv.lot_kind = '제품' and sp.id = mv.source_lot_id
               left join location fl on fl.id = mv.from_location_id
               left join location tl on tl.id = mv.to_location_id
              where true"""
    params: list = []
    if f["lot"]:
        sql += " and (coalesce(m.lot_no, p.lot_no) ilike %s or coalesce(sm.lot_no, sp.lot_no) ilike %s)"
        params += [f"%{f['lot']}%"] * 2
    if f["location"]:
        sql += " and (fl.location_code ilike %s or tl.location_code ilike %s)"
        params += [f"%{f['location']}%"] * 2
    rows = conn.q(sql + " order by mv.moved_at desc, mv.id desc limit 500", params)
    return templating.render(request, "inv/moves.html", {
        "rows": rows, "f": f, "locations": locations(), "kinds": LOT_KINDS,
        "can_w": rbac.can(user, "INV-020", "W")}, screen_id="INV-020")


@router.post("/inv/moves")
def create_move(request: Request, lot_kind: str = Form(""), lot_no: str = Form(""),
                from_location_id: str = Form(""), to_location_id: str = Form(""), qty: str = Form(""),
                split: str = Form(""), note: str = Form(""),
                user: rbac.User = rbac.require_fn("F-INV-021")):
    kind = kind_in(lot_kind)
    lot = lot_by_no(kind, lot_no)
    src = location_in(from_location_id, "출발 위치")
    dst = location_in(to_location_id, "도착 위치")
    q = num_in(qty, "수량")
    memo = text_in(note, "비고")
    is_split = (split or "").strip() in ("1", "on", "true", "Y", "y")
    if not is_split and src["id"] == dst["id"]:
        raise _bad("도착 위치", "출발 위치와 같습니다 — 이동은 다른 위치로, 같은 위치에서 나누려면 분할을 고르세요")
    table = "material_lot" if kind == "원자재" else "product_lot"
    with conn.tx() as cur:
        row = _stock_row(cur, kind, lot["id"], src["id"])
        if row is None:
            raise _bad("출발 위치", f"{lot['lot_no']} 의 재고가 {src['location_code']} 에 없습니다")
        avail = row["qty"] - row["allocated_qty"]
        if q > avail:
            raise _bad("수량", f"가용 수량 {avail} 을(를) 넘습니다 (현재고 {row['qty']} − 할당 {row['allocated_qty']})")
        # 전량 분할도 허용한다 — 원 LOT 의 재고가 0 이 될 뿐 원 LOT 행은 남는다
        cur.execute("update lot_stock set qty = qty - %s, updated_at = now(), updated_by = %s where id = %s",
                    (q, user.login_id, row["id"]))
        if is_split:
            new_no = _split_no(cur, table, lot)
            if kind == "원자재":
                cur.execute("""insert into material_lot (lot_no, receipt_id, item_id, qty, supplier_lot_no, parent_lot_id, created_by)
                               values (%s, %s, %s, %s, %s, %s, %s) returning id""",
                            (new_no, lot["receipt_id"], lot["item_id"], q, lot["supplier_lot_no"], lot["id"], user.login_id))
            else:
                cur.execute("""insert into product_lot (lot_no, item_id, work_order_id, parent_lot_id, qty, created_by)
                               values (%s, %s, %s, %s, %s, %s) returning id""",
                            (new_no, lot["item_id"], lot["work_order_id"], lot["id"], q, user.login_id))
            new_id = cur.fetchone()["id"]
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                           values (%s, %s, %s, %s, %s, %s)""", (kind, new_id, dst["id"], q, row["status"], user.login_id))
            cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, source_lot_id, from_location_id, to_location_id,
                                                   qty, note, created_by)
                           values ('분할', %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                        (kind, new_id, lot["id"], src["id"], dst["id"], q, memo, user.login_id))
            move_id = cur.fetchone()["id"]
            moved_no = new_no
        else:
            to_row = _stock_row(cur, kind, lot["id"], dst["id"])
            if to_row is None:
                cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                               values (%s, %s, %s, %s, %s, %s)""", (kind, lot["id"], dst["id"], q, row["status"], user.login_id))
            else:
                cur.execute("update lot_stock set qty = qty + %s, updated_at = now(), updated_by = %s where id = %s",
                            (q, user.login_id, to_row["id"]))
            cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, from_location_id, to_location_id, qty, note, created_by)
                           values ('이동', %s, %s, %s, %s, %s, %s, %s) returning id""",
                        (kind, lot["id"], src["id"], dst["id"], q, memo, user.login_id))
            move_id = cur.fetchone()["id"]
            moved_no = lot["lot_no"]
    msg = (f"{lot['lot_no']} 에서 {moved_no} 을(를) 나눠 옮겼습니다" if is_split
           else f"{lot['lot_no']} 을(를) {dst['location_code']} 로 옮겼습니다")
    resp = http.saved(request, msg, data={"move_id": move_id, "lot_no": moved_no})
    audit.log_change(request, user, "F-INV-021", f"stock_move:{move_id}",
                     f"{'분할' if is_split else '이동'} {lot['lot_no']}→{moved_no} {src['location_code']}→{dst['location_code']} {q}")
    return resp


@router.post("/inv/moves/{id}")
def update_move(request: Request, id: str, from_location_id: str = Form(""), to_location_id: str = Form(""),
                qty: str = Form(""), note: str = Form(""),
                user: rbac.User = rbac.require_fn("F-INV-022")):
    """위치 이동 행 고치기 — 옛 이동을 되돌리고 새 값으로 다시 옮긴다(한 트랜잭션). 분할 · 불출 · 출하 행은 그 화면에서 고친다."""
    mid = path_id(id)
    mv = conn.q1("select * from stock_move where id = %s", (mid,))
    if mv is None:
        raise http.not_found()
    if mv["move_kind"] != "이동":
        raise _bad("이동 구분", f"{mv['move_kind']} 행은 여기서 고칠 수 없습니다 — 위치 이동 행만 고칩니다")
    src = location_in(from_location_id, "출발 위치") if from_location_id.strip() else {"id": mv["from_location_id"]}
    dst = location_in(to_location_id, "도착 위치") if to_location_id.strip() else {"id": mv["to_location_id"]}
    q_new = num_in(qty, "수량", required=False)
    q = q_new or mv["qty"]
    memo = text_in(note, "비고")
    if not from_location_id.strip() and not to_location_id.strip() and q_new is None and memo is None:
        raise _bad("수정", "고칠 항목이 없습니다 — 출발 위치 · 도착 위치 · 수량 · 비고 중 하나 이상",
                   "고칠 항목이 없습니다 — 출발 위치 · 도착 위치 · 수량 · 비고 중 하나 이상")
    if src["id"] == dst["id"]:
        raise _bad("도착 위치", "출발 위치와 같습니다")
    kind, lot_id = mv["lot_kind"], mv["lot_id"]
    with conn.tx() as cur:
        old_to = _stock_row(cur, kind, lot_id, mv["to_location_id"])
        if old_to is None or old_to["qty"] - old_to["allocated_qty"] < mv["qty"]:
            raise _bad("수량", "도착 위치의 가용 수량이 옮긴 수량보다 적어 되돌릴 수 없습니다 (이미 불출 · 할당 · 이동됨)")
        cur.execute("update lot_stock set qty = qty - %s, updated_at = now(), updated_by = %s where id = %s",
                    (mv["qty"], user.login_id, old_to["id"]))
        old_from = _stock_row(cur, kind, lot_id, mv["from_location_id"])
        cur.execute("update lot_stock set qty = qty + %s, updated_at = now(), updated_by = %s where id = %s",
                    (mv["qty"], user.login_id, old_from["id"]))
        new_from = _stock_row(cur, kind, lot_id, src["id"])
        if new_from is None:
            raise _bad("출발 위치", "그 위치에 이 LOT 의 재고가 없습니다")
        if new_from["qty"] - new_from["allocated_qty"] < q:
            raise _bad("수량", f"가용 수량 {new_from['qty'] - new_from['allocated_qty']} 을(를) 넘습니다")
        cur.execute("update lot_stock set qty = qty - %s, updated_at = now(), updated_by = %s where id = %s",
                    (q, user.login_id, new_from["id"]))
        new_to = _stock_row(cur, kind, lot_id, dst["id"])
        if new_to is None:
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                           values (%s, %s, %s, %s, %s, %s)""", (kind, lot_id, dst["id"], q, new_from["status"], user.login_id))
        else:
            cur.execute("update lot_stock set qty = qty + %s, updated_at = now(), updated_by = %s where id = %s",
                        (q, user.login_id, new_to["id"]))
        cur.execute("""update stock_move set from_location_id = %s, to_location_id = %s, qty = %s,
                              note = coalesce(%s, note), updated_at = now(), updated_by = %s where id = %s""",
                    (src["id"], dst["id"], q, memo, user.login_id, mid))
    resp = http.saved(request, "재고 이동을 고쳤습니다", data={"move_id": mid})
    audit.log_change(request, user, "F-INV-022", f"stock_move:{mid}", f"이동 수정 수량 {mv['qty']}→{q}")
    return resp


# ── INV-030 재고 조정 · 실사 ────────────────────────────────────────────────
@router.get(nav.path_of("INV-030"), response_class=HTMLResponse)
def adjustments(request: Request, user: rbac.User = rbac.require_screen("INV-030")):
    f = {k: qs(request, k) for k in ("lot",)}
    sql = """select a.id, a.lot_kind, coalesce(m.lot_no, p.lot_no) as lot_no, i.item_code, i.item_name,
                    l.location_code, a.book_qty, a.actual_qty, a.diff_qty, a.reason, a.adjusted_at, a.created_by
               from stock_adjust a
               left join material_lot m on a.lot_kind = '원자재' and m.id = a.lot_id
               left join product_lot p on a.lot_kind = '제품' and p.id = a.lot_id
               left join item i on i.id = coalesce(m.item_id, p.item_id)
               join location l on l.id = a.location_id
              where true"""
    params: list = []
    if f["lot"]:
        sql += " and coalesce(m.lot_no, p.lot_no) ilike %s"
        params.append(f"%{f['lot']}%")
    rows = conn.q(sql + " order by a.adjusted_at desc, a.id desc limit 500", params)
    return templating.render(request, "inv/adjustments.html", {
        "rows": rows, "f": f, "locations": locations(), "kinds": LOT_KINDS,
        "can_w": rbac.can(user, "INV-030", "W")}, screen_id="INV-030")


@router.post("/inv/adjustments")
def create_adjustment(request: Request, lot_kind: str = Form(""), lot_no: str = Form(""), location_id: str = Form(""),
                      actual_qty: str = Form(""), reason: str = Form(""),
                      user: rbac.User = rbac.require_fn("F-INV-031")):
    kind = kind_in(lot_kind)
    lot = lot_by_no(kind, lot_no)
    loc = location_in(location_id)
    actual = num_in(actual_qty, "실사 수량", allow_zero=True)
    why = text_in(reason, "차이 사유", required=True)
    with conn.tx() as cur:
        row = _stock_row(cur, kind, lot["id"], loc["id"])
        if row is None:
            raise _bad("위치", f"{lot['lot_no']} 의 재고 행이 {loc['location_code']} 에 없습니다")
        if actual < row["allocated_qty"]:
            raise _bad("실사 수량", f"출하 지시 할당량 {row['allocated_qty']} 보다 작게 조정할 수 없습니다 — 할당을 먼저 조정하세요")
        cur.execute("""insert into stock_adjust (lot_kind, lot_id, location_id, book_qty, actual_qty, reason, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s) returning id, diff_qty""",
                    (kind, lot["id"], loc["id"], row["qty"], actual, why, user.login_id))
        adj = cur.fetchone()
        cur.execute("update lot_stock set qty = %s, updated_at = now(), updated_by = %s where id = %s",
                    (actual, user.login_id, row["id"]))
    resp = http.saved(request, f"{lot['lot_no']} 재고를 {actual} 로 조정했습니다 (차이 {adj['diff_qty']})",
                      data={"adjust_id": adj["id"], "diff_qty": str(adj["diff_qty"])})
    audit.log_change(request, user, "F-INV-031", f"stock_adjust:{adj['id']}",
                     f"{lot['lot_no']} {row['qty']}→{actual} 사유 {why}")
    return resp
