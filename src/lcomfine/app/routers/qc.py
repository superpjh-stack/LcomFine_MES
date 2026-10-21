"""QC 품질 검사 — QC-010 입고검사 · QC-020 제품검사 판정 · QC-030 검사 이력 (개발2).

판정은 고치지 않고 차수(seq) 새 행으로 남긴다 — LOT 의 판정 = 가장 큰 seq (D-515).
쓰기 경계 예외: `lot_stock.status` 만 바꾼다 — 합격 → 가용 · 불합격 → 보류 (D-510 · db-schema §2.2).
판정은 그 LOT 과, 자기 판정이 없는 분할 자식 LOT 의 재고 행에 함께 적용한다(분할 LOT 은 원 LOT 의 판정을 따른다 — trace 와 같은 규칙).
출하 확정 뒤의 재판정은 나간 출하를 바꾸지 않는다 — 남은 재고 상태만 바꾸고 trace 가 「출하 후 불합격」을 보인다(D-515).
경로의 `{id}` 는 재판정할 **LOT 의 id**(QC-010 은 material_lot.id · QC-020 은 product_lot.id) 다.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, notify, rbac, templating
from ..util import audit, http
from .inv import _bad, date_in, id_in, path_id, qs, text_in

router = APIRouter()

RESULTS = ("합격", "불합격")
STATUS_OF = {"합격": "가용", "불합격": "보류"}

KIND = {   # 구분 → (LOT 테이블, 판정 테이블, 판정 FK, lot_stock.lot_kind, 화면)
    "원자재": ("material_lot", "incoming_inspection", "material_lot_id", "원자재", "QC-010"),
    "제품": ("product_lot", "product_inspection", "product_lot_id", "제품", "QC-020"),
}


def _result_in(value: str | None) -> str:
    v = (value or "").strip()
    if v not in RESULTS:
        raise _bad("판정", "합격 또는 불합격을 고르세요")
    return v


def _items_in(names: list[str], values: list[str]) -> dict:
    if len(names) != len(values):
        raise http.validation_error("검사 항목의 칸 수가 맞지 않습니다", fields=[{"name": "검사 항목", "reason": "칸 수 불일치"}])
    out = {}
    for n, (k, v) in enumerate(zip(names, values), start=1):
        k = text_in(k, f"{n}행 검사 항목", max_len=100)
        v = text_in(v, f"{n}행 값", max_len=200)
        if k is None and v is None:
            continue
        if k is None:
            raise _bad(f"{n}행 검사 항목", "항목 이름을 입력하세요")
        out[k] = v
    return out


def _lot_for(cur, kind: str, lot_id: int | None, lot_no: str | None, *, lock: bool = True) -> dict:
    table = KIND[kind][0]
    if lot_id is not None:
        cur.execute(f"select * from {table} where id = %s" + (" for update" if lock else ""), (lot_id,))
    else:
        cur.execute(f"select * from {table} where lot_no = %s" + (" for update" if lock else ""), (lot_no,))
    lot = cur.fetchone()
    if lot is None:
        raise _bad("LOT", f"없는 {kind} LOT 입니다: {lot_id if lot_id is not None else lot_no}")
    if lot.get("canceled_at"):
        raise _bad("LOT", f"취소된 LOT 입니다: {lot['lot_no']}")
    return lot


def _judge(cur, kind: str, lot: dict, result: str, items: dict, note: str | None, user, *, rejudge: bool) -> dict:
    """판정 한 행 + 재고 상태. 같은 트랜잭션 안에서 부른다. 반환 = {seq, status, lots(상태를 바꾼 LOT id)}."""
    table, insp, fk, lot_kind, _sid = KIND[kind]
    cur.execute(f"select coalesce(max(seq), 0) as seq from {insp} where {fk} = %s", (lot["id"],))
    last = cur.fetchone()["seq"]
    cur.execute("select status from lot_stock where lot_kind = %s and lot_id = %s", (lot_kind, lot["id"]))
    statuses = {r["status"] for r in cur.fetchall()}
    if rejudge:
        if last == 0:
            raise _bad("재판정", f"{lot['lot_no']} 은(는) 아직 판정이 없습니다 — 먼저 판정합니다")
    else:
        if last > 0 or (statuses and statuses != {"검사대기"}):
            raise _bad("판정", f"검사대기 LOT 이 아닙니다: {lot['lot_no']} — 이미 판정한 LOT 은 재판정합니다")
        if not statuses:
            raise _bad("판정", f"{lot['lot_no']} 의 재고 행이 없습니다")
    seq = last + 1
    cur.execute(f"""insert into {insp} ({fk}, seq, result, items, inspector, note, created_by)
                    values (%s, %s, %s, %s::jsonb, %s, %s, %s) returning id, inspected_at""",
                (lot["id"], seq, result, json.dumps(items, ensure_ascii=False), user.login_id, note, user.login_id))
    row = cur.fetchone()
    # 분할 자식 중 자기 판정이 없는 LOT 은 원 LOT 의 판정을 따른다
    cur.execute(f"""with recursive down as (
                        select id from {table} where id = %s
                        union all
                        select t.id from down join {table} t on t.parent_lot_id = down.id
                         where not exists (select 1 from {insp} q where q.{fk} = t.id)
                    ) select id from down""", (lot["id"],))
    ids = [r["id"] for r in cur.fetchall()]
    status = STATUS_OF[result]
    cur.execute("update lot_stock set status = %s, updated_at = now(), updated_by = %s "
                "where lot_kind = %s and lot_id = any(%s)", (status, user.login_id, lot_kind, ids))
    return {"seq": seq, "status": status, "lots": ids, "inspection_id": row["id"], "inspected_at": row["inspected_at"]}


# ── QC-010 입고검사 ────────────────────────────────────────────────────────
@router.get(nav.path_of("QC-010"), response_class=HTMLResponse)
def incoming(request: Request, user: rbac.User = rbac.require_fn("F-QC-013")):
    f = {k: qs(request, k) for k in ("receipt", "lot")}
    sql = """select m.id, m.lot_no, m.qty, m.supplier_lot_no, r.id as receipt_id, r.supplier_name, r.received_on,
                    i.item_code, i.item_name,
                    (select string_agg(distinct s.status, '·') from lot_stock s where s.lot_kind = '원자재' and s.lot_id = m.id) as status,
                    q.seq, q.result, q.inspected_at, q.inspector
               from material_lot m
               join material_receipt r on r.id = m.receipt_id
               join item i on i.id = m.item_id
               left join lateral (select seq, result, inspected_at, inspector from incoming_inspection
                                   where material_lot_id = m.id order by seq desc limit 1) q on true
              where m.canceled_at is null"""
    params: list = []
    if f["receipt"]:
        sql += " and r.id = %s"
        params.append(path_id(f["receipt"]))
    if f["lot"]:
        sql += " and m.lot_no ilike %s"
        params.append(f"%{f['lot']}%")
    rows = conn.q(sql + " order by q.seq is not null, r.received_on desc, m.lot_no limit 500", params)
    return templating.render(request, "qc/incoming.html", {
        "pending": [r for r in rows if r["seq"] is None], "judged": [r for r in rows if r["seq"] is not None],
        "f": f, "results": RESULTS, "can_w": rbac.can(user, "QC-010", "W")}, screen_id="QC-010")


def _incoming_write(request, user, fn_id: str, lot_id: int | None, lot_no: str | None, result: str, items: dict,
                    note: str | None, *, rejudge: bool):
    with conn.tx() as cur:
        lot = _lot_for(cur, "원자재", lot_id, lot_no)
        out = _judge(cur, "원자재", lot, result, items, note, user, rejudge=rejudge)
        # 입고 알림을 눌러 연 화면 — 그 입고의 LOT 이 모두 판정되면 닫힌다
        cur.execute("""select count(*) as n from material_lot m where m.receipt_id = %s and m.canceled_at is null
                          and not exists (select 1 from incoming_inspection q where q.material_lot_id = m.id)""",
                    (lot["receipt_id"],))
        if cur.fetchone()["n"] == 0:
            notify.handle_by_link(cur, f"{nav.path_of('QC-010')}?receipt={lot['receipt_id']}", user)
    verb = "재판정" if rejudge else "판정"
    resp = http.saved(request, f"{lot['lot_no']} 입고검사 {verb}: {result} → 재고 {out['status']}",
                      data={"lot_no": lot["lot_no"], "seq": out["seq"], "status": out["status"]})
    audit.log_change(request, user, fn_id, f"incoming_inspection:{lot['lot_no']}#{out['seq']}", f"입고검사 {verb} {result}")
    return resp


@router.post("/qc/incoming")
def create_incoming(request: Request, material_lot_id: str = Form(""), lot_no: str = Form(""), result: str = Form(""),
                    item_name: list[str] = Form([]), item_value: list[str] = Form([]), note: str = Form(""),
                    user: rbac.User = rbac.require_fn("F-QC-011")):
    lid = id_in(material_lot_id, "원자재 LOT", required=False)
    no = text_in(lot_no, "LOT 번호")
    if lid is None and no is None:
        raise _bad("원자재 LOT", "필수 선택입니다", "판정할 원자재 LOT 을 고르세요")
    return _incoming_write(request, user, "F-QC-011", lid, no, _result_in(result), _items_in(item_name, item_value),
                           text_in(note, "비고"), rejudge=False)


@router.post("/qc/incoming/{id}")
def rejudge_incoming(request: Request, id: str, result: str = Form(""),
                     item_name: list[str] = Form([]), item_value: list[str] = Form([]), note: str = Form(""),
                     user: rbac.User = rbac.require_fn("F-QC-012")):
    lid = path_id(id)
    if conn.q1("select 1 from material_lot where id = %s", (lid,)) is None:
        raise http.not_found()
    return _incoming_write(request, user, "F-QC-012", lid, None, _result_in(result), _items_in(item_name, item_value),
                           text_in(note, "비고"), rejudge=True)


# ── QC-020 제품검사 판정 ──────────────────────────────────────────────────
@router.get(nav.path_of("QC-020"), response_class=HTMLResponse)
def product(request: Request, user: rbac.User = rbac.require_fn("F-QC-023")):
    f = {k: qs(request, k) for k in ("lot", "wo")}
    sql = """select p.id, p.lot_no, p.qty, p.parent_lot_id, w.work_order_no, i.item_code, i.item_name,
                    (select string_agg(distinct s.status, '·') from lot_stock s where s.lot_kind = '제품' and s.lot_id = p.id) as status,
                    (select coalesce(sum(s.allocated_qty), 0) from lot_stock s where s.lot_kind = '제품' and s.lot_id = p.id) as allocated_qty,
                    q.seq, q.result, q.inspected_at, q.inspector,
                    (select count(*) from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
                      where sl.product_lot_id = p.id and so.status = '확정') as shipped_n
               from product_lot p
               join work_order w on w.id = p.work_order_id
               join item i on i.id = p.item_id
               left join lateral (select seq, result, inspected_at, inspector from product_inspection
                                   where product_lot_id = p.id order by seq desc limit 1) q on true
              where not exists (select 1 from product_receipt pr where pr.product_lot_id = p.id and pr.canceled_at is not null)"""
    params: list = []
    if f["lot"]:
        sql += " and p.lot_no ilike %s"
        params.append(f"%{f['lot']}%")
    if f["wo"]:
        sql += " and w.work_order_no ilike %s"
        params.append(f"%{f['wo']}%")
    rows = conn.q(sql + " order by q.seq is not null, p.created_at desc, p.lot_no limit 500", params)
    return templating.render(request, "qc/product.html", {
        "pending": [r for r in rows if r["seq"] is None], "judged": [r for r in rows if r["seq"] is not None],
        "f": f, "results": RESULTS, "can_w": rbac.can(user, "QC-020", "W")}, screen_id="QC-020")


def _product_write(request, user, fn_id: str, lot_id: int | None, lot_no: str | None, result: str, items: dict,
                   note: str | None, *, rejudge: bool):
    with conn.tx() as cur:
        lot = _lot_for(cur, "제품", lot_id, lot_no)
        out = _judge(cur, "제품", lot, result, items, note, user, rejudge=rejudge)
        verb = "재판정" if rejudge else "판정"
        notify.emit(cur, "judged", link=f"{nav.path_of('SHP-010')}?lot={lot['lot_no']}",
                    dedupe_key=f"judged:{lot['lot_no']}:{out['seq']}",
                    text=f"제품검사 {verb} {lot['lot_no']} {result}" + (" — 출하 확정 불가" if result == "불합격" else " — 출하 가능"))
        notify.handle_by_link(cur, f"{nav.path_of('QC-020')}?lot={lot['lot_no']}", user)
        cur.execute("""select count(*) as n from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
                        where sl.product_lot_id = %s and so.status = '확정'""", (lot["id"],))
        shipped = cur.fetchone()["n"]
    msg = f"{lot['lot_no']} 제품검사 {verb}: {result} → 재고 {out['status']}"
    if shipped and result == "불합격":
        msg += " — 이미 확정된 출하는 바꾸지 않습니다(D-515 · 반품·정정은 SHP-020)"
    resp = http.saved(request, msg, data={"lot_no": lot["lot_no"], "seq": out["seq"], "status": out["status"],
                                          "shipped_after": bool(shipped)})
    audit.log_change(request, user, fn_id, f"product_inspection:{lot['lot_no']}#{out['seq']}", f"제품검사 {verb} {result}")
    return resp


@router.post("/qc/product")
def create_product(request: Request, product_lot_id: str = Form(""), lot_no: str = Form(""), result: str = Form(""),
                   item_name: list[str] = Form([]), item_value: list[str] = Form([]), note: str = Form(""),
                   user: rbac.User = rbac.require_fn("F-QC-021")):
    lid = id_in(product_lot_id, "제품 LOT", required=False)
    no = text_in(lot_no, "LOT 번호")
    if lid is None and no is None:
        raise _bad("제품 LOT", "필수 선택입니다", "판정할 제품 LOT 을 고르세요")
    return _product_write(request, user, "F-QC-021", lid, no, _result_in(result), _items_in(item_name, item_value),
                          text_in(note, "비고"), rejudge=False)


@router.post("/qc/product/{id}")
def rejudge_product(request: Request, id: str, result: str = Form(""),
                    item_name: list[str] = Form([]), item_value: list[str] = Form([]), note: str = Form(""),
                    user: rbac.User = rbac.require_fn("F-QC-022")):
    lid = path_id(id)
    if conn.q1("select 1 from product_lot where id = %s", (lid,)) is None:
        raise http.not_found()
    return _product_write(request, user, "F-QC-022", lid, None, _result_in(result), _items_in(item_name, item_value),
                          text_in(note, "비고"), rejudge=True)


# ── QC-030 검사 이력 ──────────────────────────────────────────────────────
HISTORY_SQL = """
select * from (
  select '입고검사' as kind, m.lot_no, i.item_code, i.item_name, q.seq, q.result, q.inspected_at, q.inspector, q.note, q.items,
         lag(q.result) over (partition by q.material_lot_id order by q.seq) as prev_result,
         lag(q.inspected_at) over (partition by q.material_lot_id order by q.seq) as prev_at,
         q.seq = max(q.seq) over (partition by q.material_lot_id) as is_latest
    from incoming_inspection q join material_lot m on m.id = q.material_lot_id join item i on i.id = m.item_id
  union all
  select '제품검사', p.lot_no, i.item_code, i.item_name, q.seq, q.result, q.inspected_at, q.inspector, q.note, q.items,
         lag(q.result) over (partition by q.product_lot_id order by q.seq),
         lag(q.inspected_at) over (partition by q.product_lot_id order by q.seq),
         q.seq = max(q.seq) over (partition by q.product_lot_id)
    from product_inspection q join product_lot p on p.id = q.product_lot_id join item i on i.id = p.item_id
) h where true"""


@router.get(nav.path_of("QC-030"), response_class=HTMLResponse)
def history(request: Request, user: rbac.User = rbac.require_fn("F-QC-031")):
    f = {k: qs(request, k) for k in ("from", "to", "item", "result", "kind", "lot")}
    d_from, d_to = date_in(f["from"], "시작일"), date_in(f["to"], "종료일")
    if f["result"] and f["result"] not in RESULTS:
        raise _bad("판정", f"모르는 판정입니다: {f['result'][:20]}")
    sql, params = HISTORY_SQL, []
    if d_from:
        sql += " and h.inspected_at >= %s"
        params.append(d_from)
    if d_to:
        sql += " and h.inspected_at < %s::date + 1"
        params.append(d_to)
    if f["item"]:
        sql += " and (h.item_code ilike %s or h.item_name ilike %s)"
        params += [f"%{f['item']}%"] * 2
    if f["result"]:
        sql += " and h.result = %s"
        params.append(f["result"])
    if f["kind"]:
        sql += " and h.kind = %s"
        params.append(f["kind"])
    if f["lot"]:
        sql += " and h.lot_no ilike %s"
        params.append(f"%{f['lot']}%")
    rows = conn.q(sql + " order by h.inspected_at desc, h.lot_no, h.seq desc limit 1000", params)
    return templating.render(request, "qc/history.html", {"rows": rows, "f": f, "results": RESULTS}, screen_id="QC-030")
