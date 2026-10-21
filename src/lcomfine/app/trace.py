"""LOT 추적 — 정방향 · 역방향 (개발2 · `contracts/interfaces.md` §9 · 공표 `progress-dev2.md` §1).

    trace.backward(shipment_no=None, product_lot_no=None) -> dict   출하 / 제품 LOT → 원자재 LOT
    trace.forward(material_lot_no) -> dict                          원자재 LOT → 불출 → 지시 → 제품 LOT → 출하

**읽기만 한다.** 어떤 테이블에도 쓰지 않고, 경로 · 결과를 따로 저장하지 않는다(G-05 · D-505). 길은 FK 척추뿐이다(`db-schema.md` §3):

    material_lot ─(material_issue_line.material_lot_id · work_order_id)→ work_order
    work_order   ─(product_lot.work_order_id · product_receipt)→ product_lot
    product_lot  ─(shipment_line.product_lot_id · shipment_order_id)→ shipment_order
    분할 LOT     ─ parent_lot_id 를 끝까지 따라 원 LOT (stock_move 의 분할 행 source_lot_id 와 같은 고리)

- 취소된 불출(`material_issue.canceled_at`)은 잇지 않는다. 취소된 제품 입고의 LOT 는 정방향에서 뺀다. 출하는 `취소` 를 뺀다.
- 「출하 후 불합격」(D-515): 확정된 출하에 들어간 제품 LOT 의 **현재 판정**(자기 → 원 LOT 순으로 판정이 있는 가장 가까운 LOT 의
  최대 seq)이 불합격이고 그 판정이 출하 확정 뒤에 내려졌다. 출하는 바꾸지 않고 표시만 한다.
- 입력한 번호가 없으면 `NotFound`(LookupError) — 라우터가 422 로 보인다(사용자가 입력한 번호 · api-contract §1).
"""

from __future__ import annotations

from ..db import conn


class NotFound(LookupError):
    """입력한 출하 번호 · LOT 번호가 없다."""


STEPS_BACKWARD = [
    {"key": "shipments", "label": "출하"},
    {"key": "product_lots", "label": "제품 LOT"},
    {"key": "work_orders", "label": "생산지시"},
    {"key": "issues", "label": "불출"},
    {"key": "material_lots", "label": "원자재 LOT"},
]
STEPS_FORWARD = list(reversed(STEPS_BACKWARD))


# ── 분할 LOT 의 원 LOT (parent_lot_id 를 끝까지) ─────────────────────────────
def _roots(table: str, ids: list[int]) -> dict[int, int]:
    """{LOT id: 원 LOT id}. 분할이 아니면 자기 자신."""
    if not ids:
        return {}
    assert table in ("material_lot", "product_lot")
    rows = conn.q(
        f"""with recursive up as (
                select id as start_id, id, parent_lot_id, 0 as depth from {table} where id = any(%s)
                union all
                select up.start_id, t.id, t.parent_lot_id, up.depth + 1
                  from up join {table} t on t.id = up.parent_lot_id
            )
            select distinct on (start_id) start_id, id as root_id from up order by start_id, depth desc""",
        (ids,),
    )
    return {r["start_id"]: r["root_id"] for r in rows}


def _descendants(table: str, root_id: int) -> list[int]:
    """원 LOT 과 그 분할 자식(끝까지) — 자기 자신 먼저."""
    assert table in ("material_lot", "product_lot")
    rows = conn.q(
        f"""with recursive down as (
                select id, 0 as depth from {table} where id = %s
                union all
                select t.id, down.depth + 1 from down join {table} t on t.parent_lot_id = down.id
            )
            select id from down order by depth, id""",
        (root_id,),
    )
    return [r["id"] for r in rows]


# ── 노드 행 ────────────────────────────────────────────────────────────────
def _material_lots(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    roots = _roots("material_lot", ids)
    rows = conn.q(
        """select m.id, m.lot_no, i.item_code, i.item_name, m.qty, m.supplier_lot_no, m.receipt_id,
                  r.supplier_name, r.received_on, m.parent_lot_id
             from material_lot m
             join item i on i.id = m.item_id
             join material_receipt r on r.id = m.receipt_id
            where m.id = any(%s)
            order by m.lot_no""",
        (ids,),
    )
    root_no = {r["id"]: r["lot_no"] for r in conn.q("select id, lot_no from material_lot where id = any(%s)",
                                                       (list(set(roots.values())),))}
    for r in rows:
        r["root_lot_id"] = roots[r["id"]]
        r["root_lot_no"] = root_no[r["root_lot_id"]]
    return rows


def _judgements(ids: list[int]) -> dict[int, dict]:
    """{제품 LOT id: 현재 판정 행} — 자기 → 원 LOT 순으로 판정이 있는 가장 가까운 LOT 의 최대 seq. 판정이 없으면 빠진다(미판정)."""
    if not ids:
        return {}
    rows = conn.q(
        """with recursive up as (
               select id as start_id, id, parent_lot_id, 0 as depth from product_lot where id = any(%s)
               union all
               select up.start_id, p.id, p.parent_lot_id, up.depth + 1
                 from up join product_lot p on p.id = up.parent_lot_id
           )
           select distinct on (up.start_id) up.start_id, q.result, q.seq, q.inspected_at, q.product_lot_id
             from up join product_inspection q on q.product_lot_id = up.id
            order by up.start_id, up.depth, q.seq desc""",
        (ids,),
    )
    return {r["start_id"]: r for r in rows}


def _product_lots(ids: list[int], shipped: dict[int, object] | None) -> list[dict]:
    if not ids:
        return []
    roots = _roots("product_lot", ids)
    judged = _judgements(ids)
    rows = conn.q(
        """select p.id, p.lot_no, i.item_code, i.item_name, p.work_order_id, w.work_order_no, p.parent_lot_id, p.qty
             from product_lot p
             join item i on i.id = p.item_id
             join work_order w on w.id = p.work_order_id
            where p.id = any(%s)
            order by p.lot_no""",
        (ids,),
    )
    root_no = {r["id"]: r["lot_no"] for r in conn.q("select id, lot_no from product_lot where id = any(%s)",
                                                       (list(set(roots.values())),))}
    for r in rows:
        r["root_lot_id"] = roots[r["id"]]
        r["root_lot_no"] = root_no[r["root_lot_id"]]
        r["shipped_qty"] = None if shipped is None else shipped.get(r["id"])
        j = judged.get(r["id"])
        r["judgement"] = j["result"] if j else None
        r["judgement_seq"] = j["seq"] if j else None
        r["judged_at"] = j["inspected_at"] if j else None
    return rows


def _work_orders(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    return conn.q(
        """select w.id, w.work_order_no, w.status, w.qty, i.item_code, i.item_name, w.request_id, r.request_no
             from work_order w
             join item i on i.id = w.item_id
             join production_request r on r.id = w.request_id
            where w.id = any(%s)
            order by w.work_order_no""",
        (ids,),
    )


_ISSUE_SELECT = """select l.id as line_id, l.issue_id, h.issued_on, l.work_order_id, w.work_order_no,
                          l.material_lot_id, m.lot_no as material_lot_no, l.qty, loc.location_code
                     from material_issue_line l
                     join material_issue h on h.id = l.issue_id
                     join work_order w on w.id = l.work_order_id
                     join material_lot m on m.id = l.material_lot_id
                     join location loc on loc.id = l.location_id
                    where h.canceled_at is null"""


def _shipments(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    return conn.q(
        """select so.id, so.shipment_no, so.status, so.confirmed_at, so.due_date,
                  c.customer_code, c.customer_name, r.request_no
             from shipment_order so
             join customer c on c.id = so.customer_id
             left join production_request r on r.id = so.request_id
            where so.id = any(%s)
            order by so.shipment_no""",
        (ids,),
    )


def _rejected_after_shipment(shipment_ids: list[int], product_lot_ids: list[int] | None = None) -> list[dict]:
    """확정된 출하에 들어간 제품 LOT 의 현재 판정이 불합격이고 그 판정이 확정 뒤 (D-515)."""
    if not shipment_ids:
        return []
    lines = conn.q(
        """select distinct so.shipment_no, so.confirmed_at, sl.product_lot_id, p.lot_no
             from shipment_line sl
             join shipment_order so on so.id = sl.shipment_order_id
             join product_lot p on p.id = sl.product_lot_id
            where so.id = any(%s) and so.status = '확정'
              and (%s::bigint[] is null or sl.product_lot_id = any(%s::bigint[]))
            order by so.shipment_no, p.lot_no""",
        (shipment_ids, product_lot_ids, product_lot_ids),
    )
    judged = _judgements(list({r["product_lot_id"] for r in lines}))
    out = []
    for r in lines:
        j = judged.get(r["product_lot_id"])
        if j and j["result"] == "불합격" and j["inspected_at"] > r["confirmed_at"]:
            out.append({"shipment_no": r["shipment_no"], "confirmed_at": r["confirmed_at"],
                        "product_lot_no": r["lot_no"], "seq": j["seq"], "inspected_at": j["inspected_at"]})
    return out


# ── 공개 함수 ──────────────────────────────────────────────────────────────
def backward(shipment_no: str | None = None, product_lot_no: str | None = None) -> dict:
    """출하 번호 또는 제품 LOT 하나 → 제품 LOT → 지시 → 불출 → 원자재 LOT(분할 LOT 는 원 입고 LOT 까지)."""
    shipment_no = (shipment_no or "").strip() or None
    product_lot_no = (product_lot_no or "").strip() or None
    if (shipment_no is None) == (product_lot_no is None):
        raise ValueError("출하 번호와 제품 LOT 번호 중 하나만 준다")

    if shipment_no:
        so = conn.q1("select id from shipment_order where shipment_no = %s", (shipment_no,))
        if so is None:
            raise NotFound(f"출하 번호 {shipment_no}")
        shipment_ids = [so["id"]]
        lines = conn.q("""select product_lot_id, sum(qty) as qty from shipment_line
                           where shipment_order_id = %s group by product_lot_id""", (so["id"],))
        lot_ids = [r["product_lot_id"] for r in lines]
        shipped: dict | None = {r["product_lot_id"]: r["qty"] for r in lines}
        start = {"kind": "출하", "no": shipment_no}
        flag_lots = None
    else:
        pl = conn.q1("select id from product_lot where lot_no = %s", (product_lot_no,))
        if pl is None:
            raise NotFound(f"제품 LOT {product_lot_no}")
        lot_ids = [pl["id"]]
        shipped = None
        start = {"kind": "제품 LOT", "no": product_lot_no}
        family = _descendants("product_lot", pl["id"])      # 이 LOT(과 분할 자식)이 나간 출하
        shipment_ids = [r["id"] for r in conn.q(
            """select distinct so.id from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
                where sl.product_lot_id = any(%s) and so.status <> '취소'""", (family,))]
        flag_lots = family

    product_lots = _product_lots(lot_ids, shipped)
    wo_ids = sorted({r["work_order_id"] for r in product_lots})
    issues = conn.q(_ISSUE_SELECT + " and l.work_order_id = any(%s) order by w.work_order_no, m.lot_no, l.id", (wo_ids,)) \
        if wo_ids else []
    material_lots = _material_lots(sorted({r["material_lot_id"] for r in issues}))
    return {
        "start": start,
        "shipments": _shipments(shipment_ids),
        "product_lots": product_lots,
        "work_orders": _work_orders(wo_ids),
        "issues": issues,
        "material_lots": material_lots,
        "origin_material_lot_nos": sorted({r["root_lot_no"] for r in material_lots}),
        "issued_material_lot_nos": sorted({r["lot_no"] for r in material_lots}),
        "rejected_after_shipment": _rejected_after_shipment(shipment_ids, flag_lots),
        "steps": STEPS_BACKWARD,
    }


def forward(material_lot_no: str) -> dict:
    """원자재 LOT(과 분할 자식) → 불출 → 지시 → 제품 LOT(과 분할 자식) → 출하."""
    material_lot_no = (material_lot_no or "").strip()
    if not material_lot_no:
        raise ValueError("원자재 LOT 번호를 준다")
    ml = conn.q1("select id from material_lot where lot_no = %s", (material_lot_no,))
    if ml is None:
        raise NotFound(f"원자재 LOT {material_lot_no}")
    m_ids = _descendants("material_lot", ml["id"])
    issues = conn.q(_ISSUE_SELECT + " and l.material_lot_id = any(%s) order by w.work_order_no, m.lot_no, l.id", (m_ids,))
    wo_ids = sorted({r["work_order_id"] for r in issues})
    p_ids = [r["id"] for r in conn.q(
        """select p.id from product_lot p
            where p.work_order_id = any(%s)
              and not exists (select 1 from product_receipt pr where pr.product_lot_id = p.id and pr.canceled_at is not null)
            order by p.lot_no""", (wo_ids,))] if wo_ids else []
    lines = conn.q(
        """select sl.product_lot_id, so.id as shipment_id, sl.qty
             from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
            where sl.product_lot_id = any(%s) and so.status <> '취소'""", (p_ids,)) if p_ids else []
    shipped: dict = {}
    for r in lines:
        shipped[r["product_lot_id"]] = shipped.get(r["product_lot_id"], 0) + r["qty"]
    shipment_ids = sorted({r["shipment_id"] for r in lines})
    product_lots = _product_lots(p_ids, shipped)
    shipments = _shipments(shipment_ids)
    return {
        "start": {"kind": "원자재 LOT", "no": material_lot_no},
        "material_lots": _material_lots(m_ids),
        "issues": issues,
        "work_orders": _work_orders(wo_ids),
        "product_lots": product_lots,
        "shipments": shipments,
        "product_lot_nos": sorted(r["lot_no"] for r in product_lots),
        "shipment_nos": sorted(r["shipment_no"] for r in shipments),
        "rejected_after_shipment": _rejected_after_shipment(shipment_ids),
        "steps": STEPS_FORWARD,
    }
