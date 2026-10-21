"""TRK 통합 조회 — 주문 진행 조회(TRK-010) · 납기 현황(TRK-020) · 거래처 종합 조회(TRK-030). 담당 개발1.

**읽기만 한다** — 어떤 업무 테이블에도 쓰지 않는다(G-05). 결과를 저장하지 않고 화면을 열 때마다 센다.
계약은 「집계 SQL 은 `stats` 뿐」이지만 `stats` 는 개발3 소유이고 W1 에 아직 공표되지 않아 W1 은 이 파일 안의 조회 SQL 로 보인다
(w1-dev1 지시). `stats` 가 공표되면 옮긴다(progress-dev1 §3). 수금 칸은 W2 `stats.customer_receivable` 로 붙인다 — 그때까지 `미수집`.

단계 막대 = 의뢰 → 지시 → 생산 → 검사 → 제품 입고 → 출하 (정본 TRK-010). 각 단계의 수량 · 날짜:
  의뢰 = 의뢰 수량 · 의뢰일 / 지시 = 취소 아닌 지시 수량 합 · 첫 작성일 / 생산 = 생산일보 양품 합 · 마지막 일자 /
  검사 = 검사일보 검사 수량 합 · 마지막 일자 / 제품 입고 = 취소 아닌 제품 입고 합 · 마지막 입고일 /
  출하 = 확정 출하 수량 합(제품 LOT → 지시 → 의뢰) · 마지막 확정일. 지금 단계 = 수량이 있는 마지막 단계.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, templating
from .bas import bad, choice, like, ref_id, s

router = APIRouter()

#: (키, 단계 이름, 담당 부서 코드) — 이름은 정본 TRK-010 단계 막대 그대로
STAGES: tuple[tuple[str, str, str], ...] = (
    ("request", "의뢰", "SL"), ("order", "지시", "PR"), ("production", "생산", "PR"),
    ("inspection", "검사", "PR"), ("receipt", "제품 입고", "PR"), ("shipment", "출하", "SH"),
)

_PROGRESS_SQL = """
select r.id, r.request_no, r.request_date, r.qty, r.due_date, r.status, r.customer_id, c.customer_code, c.customer_name,
       r.item_id, i.item_code, i.item_name, (r.due_date - current_date) as d_day,
       r.qty as request_qty, r.request_date as request_on,
       o.qty as order_qty, o.n as order_n, o.on_ as order_on,
       d.qty as production_qty, d.on_ as production_on,
       ins.qty as inspection_qty, ins.on_ as inspection_on,
       pr.qty as receipt_qty, pr.on_ as receipt_on,
       sh.qty as shipment_qty, sh.on_ as shipment_on
  from production_request r
  join customer c on c.id = r.customer_id
  join item i on i.id = r.item_id
  left join lateral (select sum(w.qty) as qty, count(*) as n, min(w.created_at)::date as on_
                       from work_order w where w.request_id = r.id and w.status <> '취소') o on true
  left join lateral (select sum(pd.good_qty) as qty, max(pd.work_date) as on_
                       from production_daily pd join work_order w on w.id = pd.work_order_id
                      where w.request_id = r.id) d on true
  left join lateral (select sum(idl.inspected_qty) as qty, max(idl.work_date) as on_
                       from inspection_daily idl join work_order w on w.id = idl.work_order_id
                      where w.request_id = r.id) ins on true
  left join lateral (select sum(p.qty) as qty, max(p.received_on) as on_
                       from product_receipt p join work_order w on w.id = p.work_order_id
                      where w.request_id = r.id and p.canceled_at is null) pr on true
  left join lateral (select sum(sl.qty) as qty, max(so.confirmed_at)::date as on_
                       from shipment_line sl
                       join shipment_order so on so.id = sl.shipment_order_id and so.status = '확정'
                       join product_lot pl on pl.id = sl.product_lot_id
                       join work_order w on w.id = pl.work_order_id
                      where w.request_id = r.id) sh on true
 where {where}
 order by {order}
 limit {limit}
"""


def progress(where: str = "true", params: dict | None = None, *, order: str = "r.id desc", limit: int = 500) -> list[dict]:
    """의뢰마다 단계 6 의 수량 · 날짜 · 지금 단계 · 남은 수량. where/order 는 이 파일의 상수 조각뿐(사용자 값은 params)."""
    rows = conn.q(_PROGRESS_SQL.format(where=where, order=order, limit=int(limit)), params or {})
    names = {code: (rbac.role(code).name if rbac.role(code) else code) for _k, _n, code in STAGES}
    for r in rows:
        stages, current = [], None
        for key, label, dept in STAGES:
            q = r.get(f"{key}_qty")
            reached = q is not None and q > 0
            if reached:
                current = label
            stages.append({"key": key, "label": label, "qty": q, "on": r.get(f"{key}_on"), "dept": names[dept],
                           "reached": reached})
        r["stages"] = stages
        r["current"] = current
        r["remaining"] = r["qty"] - (r["shipment_qty"] or 0)
        r["done"] = r["remaining"] <= 0
    return rows


def _filters(q, customer, item, request_no) -> tuple[str, dict]:
    conds, params = ["true"], {}
    if s(q, "검색어"):
        conds.append("(r.request_no ilike %(q)s or c.customer_name ilike %(q)s or c.customer_code ilike %(q)s "
                     "or i.item_code ilike %(q)s or i.item_name ilike %(q)s)")
        params["q"] = like(q)
    if s(customer, "거래처"):
        conds.append("r.customer_id = %(cu)s")
        params["cu"] = ref_id(customer, "거래처")
    if s(item, "제품"):
        conds.append("r.item_id = %(it)s")
        params["it"] = ref_id(item, "제품")
    if s(request_no, "의뢰번호"):
        conds.append("r.request_no = %(rn)s")
        params["rn"] = s(request_no, "의뢰번호")
    return " and ".join(conds), params


def _customers() -> list[dict]:
    return conn.q("select id, customer_code, customer_name, use_yn from customer order by customer_code")


def _items() -> list[dict]:
    return conn.q("select id, item_code, item_name from item where item_type = '제품' order by item_code")


# ── TRK-010 주문 진행 조회 ──────────────────────────────────────────────
@router.get(nav.path_of("TRK-010"), response_class=HTMLResponse)
def orders(request: Request, q: str | None = None, customer: str | None = None, item: str | None = None,
           user: rbac.User = rbac.require_screen("TRK-010")):
    """F-TRK-011 — 생산의뢰 번호 하나로 지금 어느 단계인지와 남은 수량을 실시간으로 보여 준다(읽기만)."""
    request_no = request.query_params.get("request")
    where, params = _filters(q, customer, item, request_no)
    rows = progress(where, params)
    if s(request_no, "의뢰번호") and not rows:
        raise bad("의뢰번호", s(request_no, "의뢰번호"), "없는 의뢰번호입니다")
    detail = rows[0] if (s(request_no, "의뢰번호") or len(rows) == 1) and rows else None
    orders_of = []
    if detail:
        orders_of = conn.q("""select v.work_order_no, v.order_qty, v.daily_good_qty, v.receipt_qty, v.shipped_qty, v.status
                                from v_work_order_status v where v.request_id = %s order by v.work_order_id""",
                           (detail["id"],))
    return templating.render(request, "trk/orders.html",
                             {"rows": rows, "detail": detail, "orders_of": orders_of, "customers": _customers(),
                              "items": _items(), "stages": STAGES,
                              "form": {"q": q or "", "customer": customer or "", "item": item or "",
                                       "request": request_no or ""}}, screen_id="TRK-010")


# ── TRK-020 납기 현황 ───────────────────────────────────────────────────
BUCKETS = ("D-3", "D-7", "지연", "지연 완료", "완료", "여유")


def bucket_of(r: dict) -> str:
    """납기는 생산의뢰서 값, 완료는 출하 확정일 기준. D-3 ⊂ D-7 은 화면 필터에서 겹쳐 센다."""
    if r["done"]:
        return "지연 완료" if r["shipment_on"] and r["shipment_on"] > r["due_date"] else "완료"
    if r["d_day"] < 0:
        return "지연"
    if r["d_day"] <= 3:
        return "D-3"
    if r["d_day"] <= 7:
        return "D-7"
    return "여유"


@router.get(nav.path_of("TRK-020"), response_class=HTMLResponse)
def due(request: Request, bucket: str | None = None, customer: str | None = None, item: str | None = None,
        user: rbac.User = rbac.require_screen("TRK-020")):
    """F-TRK-021 — 납기 임박(D-7 · D-3) · 납기 지연 · 거래처·제품별. 지연 건은 어느 단계에서 멈췄는지 함께 보인다."""
    b = choice(bucket, "구분", BUCKETS, required=False)
    request_no = request.query_params.get("request")
    where, params = _filters(None, customer, item, request_no)
    rows = progress(where + " and r.status <> '취소'", params, order="r.due_date, r.id", limit=2000)
    for r in rows:
        r["bucket"] = bucket_of(r)
    counts = {k: sum(1 for r in rows if r["bucket"] == k) for k in BUCKETS}
    counts["D-7"] += counts["D-3"]           # D-7 이내 = D-3 포함
    if b == "D-7":
        shown = [r for r in rows if r["bucket"] in ("D-3", "D-7")]
    elif b:
        shown = [r for r in rows if r["bucket"] == b]
    else:
        shown = [r for r in rows if r["bucket"] in ("D-3", "D-7", "지연")]
    by_customer: dict[str, dict] = {}
    by_item: dict[str, dict] = {}
    for r in shown:
        for key, bag, label in ((r["customer_code"], by_customer, r["customer_name"]),
                                (r["item_code"], by_item, r["item_name"])):
            g = bag.setdefault(key, {"code": key, "name": label, "n": 0, "late": 0, "remaining": 0})
            g["n"] += 1
            g["late"] += r["bucket"] == "지연"
            g["remaining"] += r["remaining"] if r["remaining"] > 0 else 0
    return templating.render(request, "trk/due.html",
                             {"rows": shown, "counts": counts, "buckets": BUCKETS, "bucket": b or "",
                              "by_customer": sorted(by_customer.values(), key=lambda g: g["code"]),
                              "by_item": sorted(by_item.values(), key=lambda g: g["code"]),
                              "customers": _customers(), "items": _items(),
                              "form": {"customer": customer or "", "item": item or ""}}, screen_id="TRK-020")


# ── TRK-030 거래처 종합 조회 ────────────────────────────────────────────
@router.get(nav.path_of("TRK-030"), response_class=HTMLResponse)
def customers(request: Request, customer: str | None = None, user: rbac.User = rbac.require_screen("TRK-030")):
    """F-TRK-031 — 거래처 하나의 진행 중 주문 · 가용 재고(그 거래처 제품) · 최근 출하 · 수금·미수(W2 — 미수집)."""
    cid = ref_id(customer, "거래처", required=False)
    picked = None
    data: dict = {}
    if cid is not None:
        picked = conn.q1("select id, customer_code, customer_name, contact_name, phone, use_yn from customer where id = %s",
                         (cid,))
        if picked is None:
            raise bad("거래처", "없는 거래처입니다")
        open_rows = [r for r in progress("r.customer_id = %(cu)s and r.status <> '취소'", {"cu": cid},
                                         order="r.due_date, r.id", limit=500) if not r["done"]]
        stock = conn.q(
            """select i.item_code, i.item_name, pl.lot_no, w.warehouse_code, l.location_code, s.qty, s.allocated_qty,
                      s.qty - s.allocated_qty as available_qty
                 from lot_stock s
                 join product_lot pl on pl.id = s.lot_id
                 join item i on i.id = pl.item_id
                 join location l on l.id = s.location_id
                 join warehouse w on w.id = l.warehouse_id
                where s.lot_kind = '제품' and s.status = '가용' and s.qty - s.allocated_qty > 0
                  and pl.item_id in (select item_id from production_request where customer_id = %s)
                order by i.item_code, pl.lot_no""", (cid,))
        shipments = conn.q(
            """select so.shipment_no, so.status, so.due_date, so.confirmed_at, r.request_no,
                      coalesce((select sum(qty) from shipment_line sl where sl.shipment_order_id = so.id), 0) as qty
                 from shipment_order so left join production_request r on r.id = so.request_id
                where so.customer_id = %s
                order by coalesce(so.confirmed_at, so.created_at) desc limit 20""", (cid,))
        asof = conn.q1("select max(period_to) as d from erp_upload_batch where status = '반영'")["d"]
        data = {"open_rows": open_rows, "stock": stock, "shipments": shipments, "erp_asof": asof}
    return templating.render(request, "trk/customers.html",
                             {"customers": _customers(), "picked": picked, **data,
                              "form": {"customer": customer or ""}}, screen_id="TRK-030")
