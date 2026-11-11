"""출하의 조회·입력 대상 확인·행 잠금 (D-515).

쓰기와 트랜잭션 경계는 routers/shp.py에 둔다. 잠금 함수는 받은 커서만 사용한다.
재고 잠금은 ID 오름차순, 판정은 분할 LOT에서 가장 가까운 부모의 최신 차수다.
기존 SQL·반환값·오류 동작을 유지한다. 밑줄 함수명은 기존 호출 호환을 위해 보존한다.
"""
from __future__ import annotations

from ..db import conn
from .util import http


_LOCK_SQL = """
select s.id, s.lot_kind, s.lot_id, s.location_id, s.qty, s.allocated_qty, s.status,
       p.lot_no, p.item_id, i.item_code, i.item_name, i.use_yn, l.location_code
  from lot_stock s
  left join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
  left join item i on i.id = p.item_id
  left join location l on l.id = s.location_id
 where s.id = any(%s)
 order by s.id
   for update of s"""


def _lock_stock(cur, ids: list[int]) -> dict[int, dict]:
    """재고 행을 id 오름차순으로 잠그고(`for update`) 잠근 뒤의 값을 돌려준다."""
    cur.execute(_LOCK_SQL, (sorted(set(ids)),))
    return {r["id"]: dict(r) for r in cur.fetchall()}


def _request(cur, request_no: str | None) -> dict | None:
    if not request_no:
        return None
    cur.execute("""select q.id, q.request_no, q.customer_id, q.item_id, q.qty, q.due_date, q.status
                     from production_request q where q.request_no = %s""", (request_no,))
    req = cur.fetchone()
    if req is None:   # 사용자가 입력한 번호 — 422 (api-contract §1)
        raise http.validation_error("없는 생산의뢰 번호입니다", fields=[{"name": "생산의뢰 번호", "reason": request_no}])
    if req["status"] == "취소":
        raise http.validation_error("취소된 생산의뢰입니다", fields=[{"name": "생산의뢰 번호", "reason": request_no}])
    return req


def _customer(cur, customer_id: int | None) -> dict:
    if customer_id is None:
        raise http.validation_error("거래처를 골라 주세요", fields=[{"name": "거래처", "reason": "필수 항목입니다"}])
    cur.execute("select id, customer_code, use_yn from customer where id = %s", (customer_id,))
    c = cur.fetchone()
    if c is None:
        raise http.validation_error("없는 거래처입니다", fields=[{"name": "거래처", "reason": str(customer_id)}])
    return c


def _lock_order(cur, oid: int) -> dict:
    cur.execute("select * from shipment_order where id = %s for update", (oid,))
    o = cur.fetchone()
    if o is None:
        raise http.not_found()
    return o


_JUDGE_SQL = """
with recursive up as (
    select p.id as start_id, p.id, p.parent_lot_id, 0 as depth from product_lot p where p.id = any(%s)
    union all
    select up.start_id, p.id, p.parent_lot_id, up.depth + 1
      from up join product_lot p on p.id = up.parent_lot_id
)
select distinct on (up.start_id) up.start_id as lot_id, q.result, q.seq, q.inspected_at
  from up join product_inspection q on q.product_lot_id = up.id
 order by up.start_id, up.depth, q.seq desc"""


def _judgements(lot_ids: list[int], cur=None) -> dict[int, dict]:
    """{제품 LOT id: 현재 판정 행}. 판정이 없는 LOT 는 빠진다(= 미판정)."""
    if not lot_ids:
        return {}
    if cur is not None:
        cur.execute(_JUDGE_SQL, (list(set(lot_ids)),))
        rows = cur.fetchall()
    else:
        rows = conn.q(_JUDGE_SQL, (list(set(lot_ids)),))
    return {r["lot_id"]: dict(r) for r in rows}


def _customers() -> list[dict]:
    return conn.q("select id, customer_code, customer_name, use_yn from customer order by customer_code")


def _available_stock(item_id: int | None = None, include_ids: list[int] | None = None) -> list[dict]:
    """할당할 수 있는 제품 재고 — 가용 · 남은 가용 > 0 · 사용 중인 품목 (+ 수정 중인 지시가 이미 잡은 행)."""
    return conn.q(
        """select s.id, p.lot_no, i.item_code, i.item_name, l.location_code, s.qty, s.allocated_qty,
                  s.qty - s.allocated_qty as available, s.status
             from lot_stock s
             join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
             join item i on i.id = p.item_id
             join location l on l.id = s.location_id
            where (s.status = '가용' and s.qty - s.allocated_qty > 0 and i.use_yn = 'Y'
                   and (%(item)s::bigint is null or p.item_id = %(item)s::bigint))
               or s.id = any(%(inc)s::bigint[])
            order by p.lot_no, l.location_code""",
        {"item": item_id, "inc": include_ids or []})


def _order_lines(order_ids: list[int]) -> dict[int, list[dict]]:
    if not order_ids:
        return {}
    rows = conn.q(
        """select l.shipment_order_id, l.id, l.product_lot_id, l.location_id, l.qty, p.lot_no, i.item_code, i.item_name,
                  loc.location_code, s.id as stock_id, s.status as stock_status
             from shipment_line l
             join product_lot p on p.id = l.product_lot_id
             join item i on i.id = p.item_id
             join location loc on loc.id = l.location_id
             left join lot_stock s on s.lot_kind = '제품' and s.lot_id = l.product_lot_id and s.location_id = l.location_id
            where l.shipment_order_id = any(%s)
            order by l.id""", (order_ids,))
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["shipment_order_id"], []).append(r)
    return out
