"""SHP 출하 — SHP-010 출하 지시 · SHP-020 출하 확정 · SHP-030 출하 이력 (개발3).

기능 7 (contracts/function-list.md):
  F-SHP-011 POST /shp/orders                 출하 지시 등록 — 가용 안에서 LOT 할당 (`lot_stock.allocated_qty` · 행 잠금)
  F-SHP-012 POST /shp/orders/{id}            출하 지시 수정 — 할당을 풀고 다시 잡는다 · 확정된 출하 422 · 라인 전부 제거 = 지시 취소(Ruling 21)
  F-SHP-013 GET  /shp/orders                 출하 지시 조회 (화면)
  F-SHP-021 POST /shp/confirm/{id}/confirm   출하 확정 — 미판정·불합격 LOT 422 · qty · allocated_qty 함께 감소 · stock_move LOT 라인마다 1행
  F-SHP-022 GET  /shp/confirm                출하 확정 대상 조회 (화면)
  F-SHP-023 POST /shp/confirm/{id}/adjust    반품·정정 등록 — 확정된 출하만 · `shipment_adjust`(불변) · 재고는 바꾸지 않는다 (D-515)
  F-SHP-031 GET  /shp/history                출하 이력 조회 (화면) — 반품·정정을 원 출하 아래에 묶는다

쓰기 경계: `shipment_order` · `shipment_line` · `shipment_adjust` + 예외 `lot_stock`(할당 · 확정 감소) · `stock_move`(확정) · `notification`(notify).
할당의 동시성: 할당할 `lot_stock` 행을 **`select … for update` 로 잠근 뒤** 가용(qty − allocated_qty)을 다시 읽어 판정한다 —
같은 LOT 에 두 지시가 동시에 들어오면 뒤의 것은 앞의 것이 커밋할 때까지 기다렸다가 줄어든 가용으로 판정받는다(422).
잠금 순서는 lot_stock.id 오름차순(교착 방지).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, notify, numbering, rbac, stats, templating
from ..util import audit, http

router = APIRouter()

P_ORDERS = nav.path_of("SHP-010")    # /shp/orders
P_CONFIRM = nav.path_of("SHP-020")   # /shp/confirm
P_HISTORY = nav.path_of("SHP-030")   # /shp/history

#: numeric(14,3) 이 담을 수 있는 가장 큰 수 + 1
_QTY_LIMIT = Decimal("100000000000")
#: 출하 지시 화면의 LOT 할당 입력 줄 수
LINE_SLOTS = 5
ADJUST_KINDS = ("반품", "정정")


# ── 입력 검사 (사람이 읽는 문장으로 먼저 거른다 — 422) ──────────────────────────

def _path_id(raw: str) -> int:
    """경로의 키 — 숫자가 아니면 「그런 대상이 없다」 404 (api-contract §1)."""
    if not raw.isdigit() or len(raw) > 18:
        raise http.not_found()
    return int(raw)


def _qty(raw: str | None, label: str, *, allow_negative: bool = False) -> Decimal:
    text = (raw or "").strip().replace(",", "")
    if not text:
        raise http.validation_error(f"{label}을(를) 입력해 주세요", fields=[{"name": label, "reason": "필수 항목입니다"}])
    try:
        v = Decimal(text)
    except InvalidOperation:
        raise http.validation_error(f"{label}은(는) 숫자여야 합니다",
                                    fields=[{"name": label, "reason": text}]) from None
    if not v.is_finite():
        raise http.validation_error(f"{label}은(는) 숫자여야 합니다", fields=[{"name": label, "reason": text}])
    if v.as_tuple().exponent < -3:
        raise http.validation_error(f"{label}은(는) 소수 셋째 자리까지 입력할 수 있습니다",
                                    fields=[{"name": label, "reason": text}])
    if abs(v) >= _QTY_LIMIT:
        raise http.validation_error(f"{label}이(가) 저장할 수 있는 범위를 넘었습니다",
                                    fields=[{"name": label, "reason": text}])
    if v == 0 or (v < 0 and not allow_negative):
        raise http.validation_error(f"{label}은(는) 0보다 커야 합니다" if not allow_negative else f"{label}은(는) 0 일 수 없습니다",
                                    fields=[{"name": label, "reason": text}])
    return v


def _date(raw: str | None, label: str, *, required: bool) -> date | None:
    text = (raw or "").strip()
    if not text:
        if required:
            raise http.validation_error(f"{label}을(를) 입력해 주세요", fields=[{"name": label, "reason": "필수 항목입니다"}])
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise http.validation_error(f"{label} 형식이 올바르지 않습니다 (YYYY-MM-DD)",
                                    fields=[{"name": label, "reason": text}]) from None


def _opt_id(raw: str | None, label: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    if not text.isdigit() or len(text) > 18:
        raise http.validation_error(f"{label} 값이 올바르지 않습니다", fields=[{"name": label, "reason": text}])
    return int(text)


def _text(raw: str | None, label: str, limit: int = 1000) -> str | None:
    """글자 입력 — 앞뒤 공백 걷기 · 비면 None · NUL 과 길이 초과는 422 로 항목 이름을 짚는다(api-contract §3 · DEF-QA1-003)."""
    if raw is None:
        return None
    if "\x00" in raw:
        raise http.validation_error(f"{label}: 글자에 NUL(0x00)을 넣을 수 없습니다",
                                    fields=[{"name": label, "reason": "글자에 NUL(0x00)을 넣을 수 없습니다"}])
    text = raw.strip()
    if len(text) > limit:
        raise http.validation_error(f"{label}: {limit}자까지 입력할 수 있습니다",
                                    fields=[{"name": label, "reason": f"{len(text)}자 — {limit}자까지"}])
    return text or None


def _lines(stock_ids: list[str], qtys: list[str], *, allow_empty: bool = False) -> list[tuple[int, Decimal]]:
    """LOT 할당 줄 — (재고 행 id, 수량). 둘 다 빈 줄은 건너뛴다. 한 줄도 없으면 422(누락) —
    단 `allow_empty`(F-SHP-012 · Ruling 21: 라인 전부 제거 = 지시 취소)면 빈 목록을 돌려준다."""
    out: list[tuple[int, Decimal]] = []
    n = max(len(stock_ids), len(qtys))
    for i in range(n):
        sid = (stock_ids[i] if i < len(stock_ids) else "").strip()
        q = (qtys[i] if i < len(qtys) else "").strip()
        if not sid and not q:
            continue
        label = f"{i + 1}번 줄"
        if not sid:
            raise http.validation_error("할당할 LOT 를 골라 주세요", fields=[{"name": label, "reason": "LOT 없음"}])
        stock_id = _opt_id(sid, f"{label} LOT")
        out.append((stock_id, _qty(q, f"{label} 수량")))
    if not out and not allow_empty:
        raise http.validation_error("할당할 LOT 가 없습니다 — LOT 와 수량을 한 줄 이상 입력해 주세요",
                                    fields=[{"name": "LOT 할당", "reason": "필수 항목입니다"}])
    seen: set[int] = set()
    for sid, _ in out:
        if sid in seen:
            raise http.validation_error("같은 LOT·위치를 두 줄에 넣었습니다 — 한 줄로 합쳐 주세요",
                                        fields=[{"name": "LOT 할당", "reason": str(sid)}])
        seen.add(sid)
    return out


# ── 재고 잠금 · 할당 판정 ────────────────────────────────────────────────────

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


def _check_allocation(stock: dict[int, dict], lines: list[tuple[int, Decimal]]) -> None:
    """잠근 재고 값(이 지시의 이전 할당을 이미 뺀 값)으로 판정한다 — 없는 LOT · 제품 아님 · 가용 아님 · 사용 중지 · 가용 초과는 422."""
    errors = []
    for n, (sid, q) in enumerate(lines, start=1):
        s = stock.get(sid)
        label = f"{n}번 줄"
        if s is None or s["lot_kind"] != "제품" or s["lot_no"] is None:
            errors.append({"name": label, "reason": f"없는 제품 LOT 재고입니다 ({sid})"})
            continue
        if s["status"] != "가용":
            errors.append({"name": f"{label} {s['lot_no']}", "reason": f"재고 상태가 {s['status']} 입니다 — 가용 LOT 만 할당할 수 있습니다"})
            continue
        if s["use_yn"] != "Y":
            errors.append({"name": f"{label} {s['lot_no']}", "reason": f"사용 중지 품목입니다 ({s['item_code']})"})
            continue
        avail = s["qty"] - s["allocated_qty"]
        if q > avail:
            errors.append({"name": f"{label} {s['lot_no']}", "reason": f"가용 {avail:,} < 할당 {q:,}"})
    if errors:
        over = any("가용 " in e["reason"] and "<" in e["reason"] for e in errors)
        raise http.validation_error("가용 수량을 넘는 할당입니다" if over and len(errors) == 1
                                    else "할당할 수 없는 LOT 가 있습니다", fields=errors)


def _ordered_link(shipment_no: str) -> str:
    """`shipment_ordered` 알림의 link — 출하실이 열어 확정하는 화면. 확정하면 이 link 의 알림이 닫힌다."""
    return f"{P_CONFIRM}?no={shipment_no}"


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


# ── 판정 (D-515: LOT 의 판정 = 그 LOT 의 가장 최근 차수 · 분할 LOT 는 판정이 있는 가장 가까운 원 LOT) ───────

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


def _judge_label(j: dict | None) -> str:
    if j is None:
        return "미판정"
    return j["result"] if j["seq"] == 1 else f"{j['result']} (재판정 {j['seq']}차)"


# ── 화면 공용 조회 ──────────────────────────────────────────────────────────

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


def _bad_request_screen(request: Request, template: str, ctx: dict, screen_id: str, exc) -> HTMLResponse:
    """조회 조건이 틀린 GET — 화면을 422 로 다시 그리고 사유를 위에 보인다(입력칸 유지)."""
    detail = exc.detail
    ctx["notice"] = {"message": detail.get("message"), "fields": detail.get("fields") or []}
    return templating.render(request, template, ctx, screen_id=screen_id, status_code=422)


# ── SHP-010 출하 지시 ───────────────────────────────────────────────────────

@router.get(P_ORDERS, response_class=HTMLResponse)
def orders_screen(request: Request, customer: str | None = None, status: str | None = None,
                  due_from: str | None = None, due_to: str | None = None, request_no: str | None = None,
                  edit: str | None = None, lot: str | None = None,
                  user: rbac.User = rbac.require_screen("SHP-010")) -> HTMLResponse:
    """F-SHP-013 출하 지시 조회 — 거래처 · 납기 · 상태로 검색. `?request_no=` 는 의뢰의 거래처 · 제품 · 수량 · 납기를 채운다.
    `?lot=<제품 LOT>`(판정 완료 알림 `judged` 의 link) 는 그 LOT 의 가용 재고를 1번 줄에 골라 둔다."""
    form = {"customer": customer or "", "status": status or "", "due_from": due_from or "", "due_to": due_to or "",
            "request_no": (request_no or "").strip(), "lot": (lot or "").strip()}
    ctx: dict = {"form": form, "customers": _customers(), "rows": [], "lines": {}, "prefill": None, "edit": None,
                 "stock": [], "slots": LINE_SLOTS, "notice": None, "preselect": None,
                 "requests": conn.q("""select q.request_no, c.customer_name, i.item_name, q.due_date
                                          from production_request q join customer c on c.id = q.customer_id
                                          join item i on i.id = q.item_id
                                         where q.status <> '취소' order by q.id desc limit 200""")}
    if edit is not None:
        oid = _path_id(edit)
        o = conn.q1("""select o.*, c.customer_code, c.customer_name, q.request_no
                         from shipment_order o join customer c on c.id = o.customer_id
                         left join production_request q on q.id = o.request_id where o.id = %s""", (oid,))
        if o is None:
            raise http.not_found()
        o["lines"] = _order_lines([oid]).get(oid, [])
        ctx["edit"] = o
    try:
        cid = _opt_id(customer, "거래처")
        f = _date(due_from, "납기 시작", required=False)
        t = _date(due_to, "납기 끝", required=False)
        if status and status not in ("지시", "확정", "취소"):
            raise http.validation_error("상태 값이 올바르지 않습니다", fields=[{"name": "상태", "reason": status}])
        if form["request_no"]:
            req = conn.q1("""select q.id, q.request_no, q.customer_id, q.item_id, q.qty, q.due_date, q.status,
                                    c.customer_name, i.item_code, i.item_name
                               from production_request q join customer c on c.id = q.customer_id
                               join item i on i.id = q.item_id where q.request_no = %s""", (form["request_no"],))
            if req is None:
                raise http.validation_error("없는 생산의뢰 번호입니다",
                                            fields=[{"name": "생산의뢰 번호", "reason": form["request_no"]}])
            sh = stats.request_shipments([req["id"]]).get(req["id"], {})
            done = (sh.get("ordered_qty") or 0) + (sh.get("shipped_qty") or 0)
            req["already_qty"] = done
            req["remaining_qty"] = max(req["qty"] - done, Decimal(0))
            ctx["prefill"] = req
        if form["lot"]:
            hit = conn.q1("""select s.id from lot_stock s join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
                              where p.lot_no = %s order by (s.status = '가용') desc, s.qty - s.allocated_qty desc limit 1""",
                          (form["lot"],))
            if hit is None:
                raise http.validation_error("없는 제품 LOT 번호입니다", fields=[{"name": "LOT", "reason": form["lot"][:60]}])
            ctx["preselect"] = hit["id"]
    except HTTPException as exc:   # 조회 조건 오류(422)만 화면으로 되그린다 — 그 밖은 그대로 올린다
        if exc.status_code != 422:
            raise
        ctx["stock"] = _available_stock()
        return _bad_request_screen(request, "shp/orders.html", ctx, "SHP-010", exc)
    edit_ids = [ln["stock_id"] for ln in ctx["edit"]["lines"] if ln["stock_id"]] if ctx["edit"] else []
    ctx["stock"] = _available_stock(ctx["prefill"]["item_id"] if ctx["prefill"] else None, edit_ids)
    rows = conn.q(
        """select o.id, o.shipment_no, o.status, o.due_date, o.confirmed_at, o.created_at, o.note,
                  c.customer_code, c.customer_name, q.request_no,
                  (select count(*) from shipment_line l where l.shipment_order_id = o.id) as line_count,
                  (select sum(l.qty) from shipment_line l where l.shipment_order_id = o.id) as total_qty
             from shipment_order o
             join customer c on c.id = o.customer_id
             left join production_request q on q.id = o.request_id
            where (%(c)s::bigint is null or o.customer_id = %(c)s::bigint)
              and (%(s)s::text is null or o.status = %(s)s::text)
              and (%(f)s::date is null or o.due_date >= %(f)s::date)
              and (%(t)s::date is null or o.due_date <= %(t)s::date)
            order by o.id desc limit 500""",
        {"c": cid, "s": status or None, "f": f, "t": t})
    ctx["rows"] = rows
    ctx["lines"] = _order_lines([r["id"] for r in rows])
    return templating.render(request, "shp/orders.html", ctx, screen_id="SHP-010")


@router.post(P_ORDERS)
def create_order(request: Request, request_no: str | None = Form(None), customer_id: str | None = Form(None),
                 due_date: str | None = Form(None), note: str | None = Form(None),
                 stock_id: list[str] = Form([]), qty: list[str] = Form([]),
                 user: rbac.User = rbac.require_fn("F-SHP-011")):
    """F-SHP-011 출하 지시 등록 — 의뢰번호(선택)를 주면 거래처 · 납기를 의뢰에서 가져온다. LOT 할당은 행 잠금 안에서 가용 이하만."""
    lines = _lines(stock_id, qty)
    cid = _opt_id(customer_id, "거래처")
    due = _date(due_date, "납기", required=False)
    memo = _text(note, "비고")
    rno = _text(request_no, "생산의뢰 번호", 100)
    with conn.tx() as cur:
        req = _request(cur, rno)
        if req is not None:
            if cid is not None and cid != req["customer_id"]:
                raise http.validation_error("생산의뢰의 거래처와 다른 거래처입니다",
                                            fields=[{"name": "거래처", "reason": str(cid)}])
            cid = req["customer_id"]
            due = due or req["due_date"]
        _customer(cur, cid)
        if due is None:
            raise http.validation_error("납기를 입력해 주세요", fields=[{"name": "납기", "reason": "필수 항목입니다"}])
        stock = _lock_stock(cur, [sid for sid, _ in lines])
        _check_allocation(stock, lines)
        shipment_no = numbering.next(numbering.SHP, cur)
        cur.execute(
            """insert into shipment_order (shipment_no, request_id, customer_id, due_date, note, created_by)
               values (%s, %s, %s, %s, %s, %s) returning id""",
            (shipment_no, req["id"] if req else None, cid, due, memo, user.login_id))
        oid = cur.fetchone()["id"]
        for sid, q in lines:
            s = stock[sid]
            cur.execute(
                """insert into shipment_line (shipment_order_id, product_lot_id, location_id, qty, created_by)
                   values (%s, %s, %s, %s, %s)""", (oid, s["lot_id"], s["location_id"], q, user.login_id))
            cur.execute(
                """update lot_stock set allocated_qty = allocated_qty + %s, updated_at = now(), updated_by = %s
                    where id = %s""", (q, user.login_id, sid))
        notify.emit(cur, "shipment_ordered", link=_ordered_link(shipment_no),
                    dedupe_key=f"shipment_ordered:{shipment_no}",
                    text=f"출하 지시 {shipment_no} — 납기 {due.isoformat()} · LOT {len(lines)}줄")
        for sid, _ in lines:   # 판정 완료 알림(judged — 개발2 link `/shp/orders?lot=<LOT>`)을 이 LOT 를 할당한 부서에서 닫는다
            notify.handle_by_link(cur, f"{P_ORDERS}?lot={stock[sid]['lot_no']}", user)
    resp = http.saved(request, f"출하 지시 {shipment_no} 를 등록했습니다", data={"id": oid, "shipment_no": shipment_no})
    audit.log_change(request, user, "F-SHP-011", f"shipment_order:{shipment_no}",
                     f"출하 지시 등록 · LOT {len(lines)}줄 · 합 {sum(q for _, q in lines):,}")
    return resp


@router.post(P_ORDERS + "/{id}")
def update_order(request: Request, id: str, due_date: str | None = Form(None), note: str | None = Form(None),
                 stock_id: list[str] = Form([]), qty: list[str] = Form([]),
                 user: rbac.User = rbac.require_fn("F-SHP-012")):
    """F-SHP-012 출하 지시 수정 — 할당 줄을 통째로 바꾼다(이전 할당은 풀고 새 할당을 잡는다). 확정 · 취소된 출하는 422.
    LOT 줄을 전부 지우면 **지시 취소**(Ruling 21): 같은 트랜잭션에서 `status = '취소'` · `shipment_line` 제거 · 할당 전부 해제. 알림 없음."""
    order_id = _path_id(id)
    lines = _lines(stock_id, qty, allow_empty=True)
    due = _date(due_date, "납기", required=False)
    memo = _text(note, "비고")
    with conn.tx() as cur:
        o = _lock_order(cur, order_id)
        if o["status"] != "지시":
            hint = " — 확정 후 정정은 반품·정정 등록으로" if o["status"] == "확정" else ""
            raise http.validation_error(f"{o['status']}된 출하는 고칠 수 없습니다{hint}",
                                        fields=[{"name": "출하 번호", "reason": o["shipment_no"]}])
        cur.execute(
            """select l.id, l.qty, s.id as stock_id
                 from shipment_line l
                 left join lot_stock s on s.lot_kind = '제품' and s.lot_id = l.product_lot_id and s.location_id = l.location_id
                where l.shipment_order_id = %s""", (order_id,))
        old = cur.fetchall()
        if any(r["stock_id"] is None for r in old):
            raise http.validation_error("이 출하 지시의 할당 재고 행을 찾을 수 없습니다 — 재고 담당에게 확인해 주세요",
                                        fields=[{"name": "출하 번호", "reason": o["shipment_no"]}])
        stock = _lock_stock(cur, [r["stock_id"] for r in old] + [sid for sid, _ in lines])
        before = {sid: s["allocated_qty"] for sid, s in stock.items()}
        for r in old:                                   # 이전 할당을 푼다 (잠근 값 위에서)
            stock[r["stock_id"]]["allocated_qty"] -= r["qty"]
        _check_allocation(stock, lines)
        for sid, q in lines:
            stock[sid]["allocated_qty"] += q
        cur.execute("delete from shipment_line where shipment_order_id = %s", (order_id,))
        for sid, q in lines:
            s = stock[sid]
            cur.execute(
                """insert into shipment_line (shipment_order_id, product_lot_id, location_id, qty, created_by)
                   values (%s, %s, %s, %s, %s)""", (order_id, s["lot_id"], s["location_id"], q, user.login_id))
        for sid, s in stock.items():
            if s["allocated_qty"] != before[sid]:
                cur.execute("""update lot_stock set allocated_qty = %s, updated_at = now(), updated_by = %s
                                where id = %s""", (s["allocated_qty"], user.login_id, sid))
        cancelled = not lines
        cur.execute(
            """update shipment_order set status = case when %(cancel)s then '취소' else status end,
                      due_date = coalesce(%(due)s, due_date), note = coalesce(%(note)s, note),
                      updated_at = now(), updated_by = %(by)s where id = %(id)s""",
            {"cancel": cancelled, "due": due, "note": memo, "by": user.login_id, "id": order_id})
    released = sum((r["qty"] for r in old), Decimal(0))
    if cancelled:
        resp = http.saved(request, f"출하 지시 {o['shipment_no']} 를 취소했습니다 — 할당 {len(old)}줄({released:,}) 해제",
                          data={"id": order_id, "status": "취소"})
        audit.log_change(request, user, "F-SHP-012", f"shipment_order:{o['shipment_no']}",
                         f"지시 취소(라인 전부 제거 · Ruling 21) · 할당 {len(old)}줄({released:,}) 해제")
        return resp
    resp = http.saved(request, f"출하 지시 {o['shipment_no']} 를 고쳤습니다", data={"id": order_id, "status": "지시"})
    audit.log_change(request, user, "F-SHP-012", f"shipment_order:{o['shipment_no']}",
                     f"할당 {len(old)}줄 → {len(lines)}줄")
    return resp


# ── SHP-020 출하 확정 ───────────────────────────────────────────────────────

@router.get(P_CONFIRM, response_class=HTMLResponse)
def confirm_screen(request: Request, no: str | None = None,
                   user: rbac.User = rbac.require_screen("SHP-020")) -> HTMLResponse:
    """F-SHP-022 출하 확정 대상 조회 — 지시 상태의 출하와 LOT 별 판정 · 재고 상태. 아래에 최근 확정(반품·정정 등록 대상)."""
    q = (no or "").strip() or None
    pending = conn.q(
        """select o.id, o.shipment_no, o.due_date, o.created_at, o.note, c.customer_code, c.customer_name, q.request_no
             from shipment_order o join customer c on c.id = o.customer_id
             left join production_request q on q.id = o.request_id
            where o.status = '지시' and (%(no)s::text is null or o.shipment_no = %(no)s::text)
            order by o.due_date, o.id""", {"no": q})
    confirmed = conn.q(
        """select o.id, o.shipment_no, o.due_date, o.confirmed_at, o.confirmed_by, c.customer_name, q.request_no
             from shipment_order o join customer c on c.id = o.customer_id
             left join production_request q on q.id = o.request_id
            where o.status = '확정' and (%(no)s::text is null or o.shipment_no = %(no)s::text)
            order by o.confirmed_at desc limit 50""", {"no": q})
    lines = _order_lines([r["id"] for r in pending] + [r["id"] for r in confirmed])
    judge = _judgements([ln["product_lot_id"] for r in pending for ln in lines.get(r["id"], [])])
    for r in pending:
        blockers = []
        for ln in lines.get(r["id"], []):
            j = judge.get(ln["product_lot_id"])
            ln["judgement"] = _judge_label(j)
            ln["ok"] = j is not None and j["result"] == "합격" and ln["stock_status"] == "가용"
            if not ln["ok"]:
                blockers.append(ln["lot_no"])
        r["blockers"] = blockers
    return templating.render(request, "shp/confirm.html",
                             {"pending": pending, "confirmed": confirmed, "lines": lines, "form": {"no": q or ""},
                              "adjust_kinds": ADJUST_KINDS},
                             screen_id="SHP-020")


@router.post(P_CONFIRM + "/{id}/confirm")
def confirm_order(request: Request, id: str, user: rbac.User = rbac.require_fn("F-SHP-021")):
    """F-SHP-021 출하 확정 — 미판정 · 불합격 LOT 가 하나라도 있으면 422. 확정하면 LOT 라인마다 재고 qty · allocated_qty 를
    출하 수량만큼 함께 줄이고(가용은 그대로) `stock_move`(출하) 한 행씩. 알림 shipment_confirmed → 영업부 · 회계부."""
    order_id = _path_id(id)
    with conn.tx() as cur:
        o = _lock_order(cur, order_id)
        if o["status"] != "지시":
            raise http.validation_error(f"이미 {o['status']}된 출하입니다", fields=[{"name": "출하 번호", "reason": o["shipment_no"]}])
        cur.execute(
            """select l.id, l.product_lot_id, l.location_id, l.qty, p.lot_no, s.id as stock_id
                 from shipment_line l join product_lot p on p.id = l.product_lot_id
                 left join lot_stock s on s.lot_kind = '제품' and s.lot_id = l.product_lot_id and s.location_id = l.location_id
                where l.shipment_order_id = %s order by l.id""", (order_id,))
        lines = cur.fetchall()
        if not lines:
            raise http.validation_error("할당된 LOT 가 없는 출하입니다", fields=[{"name": "출하 번호", "reason": o["shipment_no"]}])
        stock = _lock_stock(cur, [ln["stock_id"] for ln in lines if ln["stock_id"]])
        judge = _judgements([ln["product_lot_id"] for ln in lines], cur)
        errors = []
        for ln in lines:
            j = judge.get(ln["product_lot_id"])
            s = stock.get(ln["stock_id"])
            if j is None:
                errors.append({"name": ln["lot_no"], "reason": "검사 미판정"})
            elif j["result"] != "합격":
                errors.append({"name": ln["lot_no"], "reason": _judge_label(j)})
            elif s is None:
                errors.append({"name": ln["lot_no"], "reason": "재고 행 없음"})
            elif s["status"] != "가용":
                errors.append({"name": ln["lot_no"], "reason": f"재고 상태 {s['status']}"})
            elif s["allocated_qty"] < ln["qty"] or s["qty"] < ln["qty"]:
                errors.append({"name": ln["lot_no"], "reason": f"할당 {s['allocated_qty']:,} · 현재고 {s['qty']:,} < 출하 {ln['qty']:,}"})
        if errors:
            raise http.validation_error("확정할 수 없는 LOT 가 있습니다 — 검사 미판정·불합격 LOT 는 출하 확정을 막습니다", fields=errors)
        for ln in lines:
            cur.execute(
                """update lot_stock set qty = qty - %s, allocated_qty = allocated_qty - %s, updated_at = now(), updated_by = %s
                    where id = %s""", (ln["qty"], ln["qty"], user.login_id, ln["stock_id"]))
            cur.execute(
                """insert into stock_move (move_kind, lot_kind, lot_id, from_location_id, to_location_id, qty,
                                           ref_table, ref_id, note, created_by)
                   values ('출하', '제품', %s, %s, null, %s, 'shipment_order', %s, %s, %s)""",
                (ln["product_lot_id"], ln["location_id"], ln["qty"], order_id, f"출하 확정 {o['shipment_no']}",
                 user.login_id))
        cur.execute(
            """update shipment_order set status = '확정', confirmed_at = now(), confirmed_by = %s,
                      updated_at = now(), updated_by = %s where id = %s""", (user.login_id, user.login_id, order_id))
        notify.handle_by_link(cur, _ordered_link(o["shipment_no"]), user)
        notify.emit(cur, "shipment_confirmed", link=f"{P_HISTORY}?no={o['shipment_no']}",
                    dedupe_key=f"shipment_confirmed:{o['shipment_no']}",
                    text=f"출하 확정 {o['shipment_no']} — LOT {len(lines)}줄 · 합 {sum(ln['qty'] for ln in lines):,}")
    resp = http.saved(request, f"출하 {o['shipment_no']} 를 확정했습니다", data={"id": order_id, "shipment_no": o["shipment_no"]})
    audit.log_change(request, user, "F-SHP-021", f"shipment_order:{o['shipment_no']}", f"출하 확정 · LOT {len(lines)}줄")
    return resp


@router.post(P_CONFIRM + "/{id}/adjust")
def adjust_order(request: Request, id: str, kind: str | None = Form(None), qty: str | None = Form(None),
                 reason: str | None = Form(None), lot_no: str | None = Form(None),
                 user: rbac.User = rbac.require_fn("F-SHP-023")):
    """F-SHP-023 반품·정정 등록 — 확정된 출하만. 구분(반품 · 정정) · 수량 · 사유 필수. 재고는 바꾸지 않는다(재고 반영 미확정 D-515).

    수량 규약(가설 D-515 · db-schema): 저장 값의 음수 = 반품(줄어든 수량), 양수 = 정정으로 늘어난 수량.
    반품은 양수로 입력해도 음수로 저장하고, 반품 누계는 그 출하(LOT 를 고르면 그 LOT)의 출하 수량을 넘을 수 없다.
    """
    order_id = _path_id(id)
    k = (kind or "").strip()
    if k not in ADJUST_KINDS:
        raise http.validation_error("구분을 골라 주세요 (반품 · 정정)", fields=[{"name": "구분", "reason": k or "필수 항목입니다"}])
    v = _qty(qty, "수량", allow_negative=True)
    why = _text(reason, "사유")
    if not why:
        raise http.validation_error("사유를 입력해 주세요", fields=[{"name": "사유", "reason": "필수 항목입니다"}])
    lot = _text(lot_no, "LOT 번호", 100)
    stored = -abs(v) if k == "반품" else v
    with conn.tx() as cur:
        o = _lock_order(cur, order_id)
        if o["status"] != "확정":
            raise http.validation_error("확정된 출하만 반품·정정을 등록할 수 있습니다",
                                        fields=[{"name": "출하 번호", "reason": f"{o['shipment_no']} ({o['status']})"}])
        cur.execute("""select l.product_lot_id, p.lot_no, l.qty from shipment_line l
                         join product_lot p on p.id = l.product_lot_id where l.shipment_order_id = %s""", (order_id,))
        shipped = cur.fetchall()
        lot_id = None
        if lot:
            hit = [r for r in shipped if r["lot_no"] == lot]
            if not hit:
                raise http.validation_error("이 출하에 없는 LOT 입니다", fields=[{"name": "LOT", "reason": lot}])
            lot_id = hit[0]["product_lot_id"]
        if k == "반품":
            scope = [r for r in shipped if lot_id is None or r["product_lot_id"] == lot_id]
            out_qty = sum((r["qty"] for r in scope), Decimal(0))
            cur.execute("""select coalesce(sum(qty), 0) as n from shipment_adjust
                            where shipment_order_id = %s and kind = '반품'
                              and (%s::bigint is null or product_lot_id = %s::bigint)""", (order_id, lot_id, lot_id))
            returned = -cur.fetchone()["n"]
            if returned + abs(v) > out_qty:
                raise http.validation_error("반품 수량이 출하 수량을 넘습니다",
                                            fields=[{"name": "수량", "reason": f"출하 {out_qty:,} · 이미 반품 {returned:,} · 이번 {abs(v):,}"}])
        cur.execute(
            """insert into shipment_adjust (shipment_order_id, kind, qty, reason, product_lot_id, created_by)
               values (%s, %s, %s, %s, %s, %s) returning id""", (order_id, k, stored, why, lot_id, user.login_id))
        aid = cur.fetchone()["id"]
    resp = http.saved(request, f"출하 {o['shipment_no']} 에 {k} 행을 남겼습니다 — 재고는 바뀌지 않습니다 (D-515)",
                      data={"id": aid, "qty": str(stored)})
    audit.log_change(request, user, "F-SHP-023", f"shipment_adjust:{o['shipment_no']}", f"{k} {stored:,} · {why}")
    return resp


# ── SHP-030 출하 이력 ───────────────────────────────────────────────────────

@router.get(P_HISTORY, response_class=HTMLResponse)
def history_screen(request: Request, date_from: str | None = None, date_to: str | None = None,
                   customer: str | None = None, item: str | None = None, no: str | None = None,
                   user: rbac.User = rbac.require_screen("SHP-030")) -> HTMLResponse:
    """F-SHP-031 출하 이력 — 확정된 출하(기간 = 확정일 · 거래처 · 품목). 반품·정정 행을 원 출하 아래에 묶는다."""
    form = {"date_from": date_from or "", "date_to": date_to or "", "customer": customer or "", "item": item or "",
            "no": (no or "").strip()}
    ctx: dict = {"form": form, "customers": _customers(), "rows": [], "lines": {}, "adjusts": {}, "notice": None,
                 "items": conn.q("select id, item_code, item_name from item where item_type = '제품' order by item_code"),
                 "trace_path": nav.path_of("LOT-020")}
    try:
        f = _date(date_from, "확정일 시작", required=False)
        t = _date(date_to, "확정일 끝", required=False)
        cid = _opt_id(customer, "거래처")
        iid = _opt_id(item, "품목")
    except HTTPException as exc:   # 조회 조건 오류(422)만 화면으로 되그린다 — 그 밖은 그대로 올린다
        if exc.status_code != 422:
            raise
        return _bad_request_screen(request, "shp/history.html", ctx, "SHP-030", exc)
    rows = conn.q(
        """select o.id, o.shipment_no, o.due_date, o.confirmed_at, o.confirmed_by, c.customer_code, c.customer_name,
                  q.request_no, (select sum(l.qty) from shipment_line l where l.shipment_order_id = o.id) as shipped_qty,
                  (select sum(a.qty) from shipment_adjust a where a.shipment_order_id = o.id) as adjust_qty
             from shipment_order o join customer c on c.id = o.customer_id
             left join production_request q on q.id = o.request_id
            where o.status = '확정'
              and (%(f)s::date is null or o.confirmed_at::date >= %(f)s::date)
              and (%(t)s::date is null or o.confirmed_at::date <= %(t)s::date)
              and (%(c)s::bigint is null or o.customer_id = %(c)s::bigint)
              and (%(no)s::text is null or o.shipment_no = %(no)s::text)
              and (%(i)s::bigint is null or exists (select 1 from shipment_line l join product_lot p on p.id = l.product_lot_id
                                                     where l.shipment_order_id = o.id and p.item_id = %(i)s::bigint))
            order by o.confirmed_at desc, o.id desc limit 500""",
        {"f": f, "t": t, "c": cid, "i": iid, "no": form["no"] or None})
    ids = [r["id"] for r in rows]
    adjusts: dict[int, list[dict]] = {}
    if ids:
        for a in conn.q("""select a.shipment_order_id, a.kind, a.qty, a.reason, a.created_at, a.created_by, p.lot_no
                             from shipment_adjust a left join product_lot p on p.id = a.product_lot_id
                            where a.shipment_order_id = any(%s) order by a.id""", (ids,)):
            adjusts.setdefault(a["shipment_order_id"], []).append(a)
    ctx.update(rows=rows, lines=_order_lines(ids), adjusts=adjusts)
    return templating.render(request, "shp/history.html", ctx, screen_id="SHP-030")
