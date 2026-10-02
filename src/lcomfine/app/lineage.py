"""계보 — `roll_genealogy` 에 쓰고(부모 → 자식 한 줄) 그 기록을 따라 읽는(재귀 조회) **한 곳** (G-06 · G-07).

담당 **개발2**. 사용법 공표는 `progress-dev2.md` §1. 개발3 의 LOT 추적·출하는 여기 함수만 부른다.
**다른 모듈은 `roll_genealogy` 에 직접 쓰지 않는다.**

지킬 것
  · 추적은 조회 하나다. 경로·결과를 다른 테이블에 저장하지 않는다. `trace_*` 는 어떤 테이블에도 쓰지 않는다(G-05).
  · 깊이·분기 수를 가정하지 않는다 — `with recursive` 로 끝까지 따라간다.
  · 쓰기 함수는 전부 `cur`(`conn.tx()` 의 커서)를 받는다. 롤 생성과 계보 행이 한 트랜잭션이어야 한다.
  · 검증 실패는 `http.validation_error(...)`(422)로 올린다. DB 의 지킴이 트리거(schema.sql)는 마지막 방어선이다 —
    여기서 놓친 것은 `psycopg.errors.IntegrityError` 로 올라가 `main.py` 가 422 로 바꾼다.

노드는 `(종류, id)` 로 가리킨다. 종류는 MATERIAL_LOT · ROLL · SHIPMENT.

이 모듈이 쓰는 테이블은 `roll`(롤 생성)과 `roll_genealogy` 둘뿐이다. 롤 상태·LOT 잔량은 저장하지 않는다(뷰).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..db import conn
from . import numbering
from .util import http

MATERIAL_LOT, ROLL, SHIPMENT = "material_lot", "roll", "shipment"
NODE_KINDS: tuple[str, ...] = (MATERIAL_LOT, ROLL, SHIPMENT)

#: roll_genealogy.relation — 설계도 §3 그림의 관계 이름 + 1:1 후가공
INPUT, FINISHING, SPLICE, SLITTING, SHIPPING = "투입", "후가공", "splice", "슬리팅", "출하"
RELATIONS: tuple[str, ...] = (INPUT, FINISHING, SPLICE, SLITTING, SHIPPING)

#: 롤 상태 (뷰 v_roll_state.state) — 저장하지 않고 계보에서 계산한다
IN_STOCK, CONSUMED, SHIPPED = "재고", "소진", "출하"

#: roll.process_type
PRINT_ROLL, FINISHING_ROLL, SLIT_ROLL = "인쇄", "후가공", "슬리팅"
#: Node.label — 롤은 공정 구분 그대로
MATERIAL_LOT_LABEL, SHIPMENT_LABEL = "원재료 LOT", "출하 LOT"

FORWARD, BACKWARD = "forward", "backward"

NodeRef = tuple[str, int]

#: 관계 → 자식 롤의 공정 구분 (DB 트리거와 같은 규칙)
_CHILD_TYPE = {INPUT: PRINT_ROLL, FINISHING: FINISHING_ROLL, SPLICE: FINISHING_ROLL, SLITTING: SLIT_ROLL}


@dataclass(frozen=True)
class Node:
    kind: str                 # material_lot | roll | shipment
    id: int
    no: str                   # lot_no · roll_no · shipment_no
    label: str                # 원재료 LOT | 인쇄 | 후가공 | 슬리팅 | 출하 LOT
    state: str | None = None  # 롤: 재고 | 소진 | 출하 · 원재료 LOT: 검사 상태 · 출하: 등록 | 승인
    job_no: str | None = None

    @property
    def ref(self) -> NodeRef:
        return (self.kind, self.id)


@dataclass(frozen=True)
class Edge:
    genealogy_id: int
    parent: Node
    child: Node
    relation: str
    qty: float | None
    depth: int                # 출발점에서 몇 번째 화살표인가 (1부터)


@dataclass(frozen=True)
class Trace:
    start: Node
    direction: str            # forward | backward
    edges: list[Edge] = field(default_factory=list)   # 중복 없는 화살표 (genealogy_id 기준)

    def nodes(self) -> list[Node]:
        """출발점을 포함해 지나간 노드 전부(중복 없음). 출발점이 맨 앞, 그 뒤는 가까운 순서."""
        seen: dict[NodeRef, Node] = {self.start.ref: self.start}
        for e in self.edges:
            for n in ((e.parent, e.child) if self.direction == FORWARD else (e.child, e.parent)):
                seen.setdefault(n.ref, n)
        return list(seen.values())

    def material_lots(self) -> list[Node]:
        """역방향 추적의 답 — 닿은 원재료 LOT."""
        return [n for n in self.nodes() if n.kind == MATERIAL_LOT]

    def shipments(self) -> list[Node]:
        """정방향 추적의 답 — 닿은 출하 LOT."""
        return [n for n in self.nodes() if n.kind == SHIPMENT]

    def stock_rolls(self) -> list[Node]:
        """정방향 추적에서 자식 없이 끝난 롤 — 화면에 `재고` 로 표시한다."""
        return [n for n in self.nodes() if n.kind == ROLL and n.state == IN_STOCK]

    def rolls(self) -> list[Node]:
        """지나간 롤 전부."""
        return [n for n in self.nodes() if n.kind == ROLL]


# ── 내부: 조회 ──────────────────────────────────────────────────────────
def _rows(cur, sql: str, params=None) -> list[dict]:
    """`cur` 가 있으면 그 트랜잭션 안에서, 없으면 새 연결로 읽는다."""
    if cur is None:
        return conn.q(sql, params)
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


#: 세 종류의 노드를 한 모양으로 (kind, id, no, label, state, job_no)
_NODES = f"""
(select '{MATERIAL_LOT}'::text as kind, m.material_lot_id as id, m.lot_no as no, '{MATERIAL_LOT_LABEL}'::text as label,
        m.insp_status as state, null::text as job_no
   from material_lot m
 union all
 select '{ROLL}', v.roll_id, v.roll_no, v.process_type, v.state, j.job_no
   from v_roll_state v join job j on j.job_id = v.job_id
 union all
 select '{SHIPMENT}', s.shipment_id, s.shipment_no, '{SHIPMENT_LABEL}', s.status, j.job_no
   from shipment s join job j on j.job_id = s.job_id) n
"""

#: 화살표 한 줄 + 양 끝 노드. `{source}` 는 `roll_genealogy g` 를 포함하는 FROM 절
_EDGES = """
select g.genealogy_id, g.relation, g.qty, {depth} as depth,
       g.parent_material_lot_id, g.parent_roll_id, g.child_roll_id, g.child_shipment_id,
       pm.lot_no as pm_no, pm.insp_status as pm_state,
       pv.roll_no as pr_no, pv.process_type as pr_label, pv.state as pr_state, pj.job_no as pr_job,
       cv.roll_no as cr_no, cv.process_type as cr_label, cv.state as cr_state, cj.job_no as cr_job,
       sh.shipment_no as sh_no, sh.status as sh_state, sj.job_no as sh_job
  from {source}
  left join material_lot pm on pm.material_lot_id = g.parent_material_lot_id
  left join v_roll_state pv on pv.roll_id = g.parent_roll_id
  left join job pj on pj.job_id = pv.job_id
  left join v_roll_state cv on cv.roll_id = g.child_roll_id
  left join job cj on cj.job_id = cv.job_id
  left join shipment sh on sh.shipment_id = g.child_shipment_id
  left join job sj on sj.job_id = sh.job_id
"""

#: 재귀 조회 — 화살표를 끝까지 따라간다. 같은 화살표가 두 길로 닿으면 가장 가까운 깊이 하나만 남긴다.
#: 순환은 DB 가 막으므로(트리거) 반드시 끝난다. 결과를 어디에도 저장하지 않는다.
_WALK = """
with recursive walk (genealogy_id, next_roll_id, depth) as (
    select g.genealogy_id, g.{next_col}, 1
      from roll_genealogy g
     where g.{start_col} = %(id)s
    union
    select g.genealogy_id, g.{next_col}, w.depth + 1
      from roll_genealogy g
      join walk w on g.{join_col} = w.next_roll_id
), hit as (
    select genealogy_id, min(depth) as depth from walk group by genealogy_id
)
""" + _EDGES.format(depth="h.depth", source="hit h join roll_genealogy g on g.genealogy_id = h.genealogy_id") + """
 order by h.depth, g.genealogy_id
"""


def _edge(r: dict) -> Edge:
    if r["parent_material_lot_id"] is not None:
        parent = Node(MATERIAL_LOT, r["parent_material_lot_id"], r["pm_no"], MATERIAL_LOT_LABEL, r["pm_state"], None)
    else:
        parent = Node(ROLL, r["parent_roll_id"], r["pr_no"], r["pr_label"], r["pr_state"], r["pr_job"])
    if r["child_roll_id"] is not None:
        child = Node(ROLL, r["child_roll_id"], r["cr_no"], r["cr_label"], r["cr_state"], r["cr_job"])
    else:
        child = Node(SHIPMENT, r["child_shipment_id"], r["sh_no"], SHIPMENT_LABEL, r["sh_state"], r["sh_job"])
    qty = float(r["qty"]) if r["qty"] is not None else None
    return Edge(r["genealogy_id"], parent, child, r["relation"], qty, r["depth"])


def _check_ref(node: NodeRef) -> NodeRef:
    try:
        kind, node_id = node
    except (TypeError, ValueError):
        raise http.validation_error("계보 노드는 (종류, id) 로 가리킵니다", fields=[{"name": "노드", "reason": repr(node)}])
    if kind not in NODE_KINDS:
        raise http.validation_error("계보 노드의 종류가 아닙니다", fields=[{"name": "종류", "reason": str(kind)}])
    return kind, int(node_id)


def _node(node: NodeRef, cur=None) -> Node | None:
    kind, node_id = _check_ref(node)
    rows = _rows(cur, f"select n.* from {_NODES} where n.kind = %s and n.id = %s", (kind, node_id))
    return Node(**rows[0]) if rows else None


def _kind_name(kind: str) -> str:
    return {MATERIAL_LOT: MATERIAL_LOT_LABEL, ROLL: "롤", SHIPMENT: SHIPMENT_LABEL}[kind]


# ── 쓰기 ────────────────────────────────────────────────────────────────
def _check_link(cur, parent: NodeRef, child: NodeRef, relation: str) -> None:
    """계보 한 줄을 넣기 전의 검사 — 사람이 읽을 문장으로 422 를 낸다. (DB 트리거가 같은 것을 한 번 더 막는다.)"""
    pk, pid = _check_ref(parent)
    ck, cid = _check_ref(child)
    if relation not in RELATIONS:
        raise http.validation_error("계보의 관계가 아닙니다", fields=[{"name": "관계", "reason": str(relation)}])
    shape_ok = (pk in (MATERIAL_LOT, ROLL) and ck in (ROLL, SHIPMENT)
                and (relation == INPUT) == (pk == MATERIAL_LOT)
                and (relation == SHIPPING) == (ck == SHIPMENT)
                and not (pk == MATERIAL_LOT and ck == SHIPMENT))
    if not shape_ok:
        raise http.validation_error(
            "관계와 노드 종류가 맞지 않습니다",
            fields=[{"name": "관계", "reason": f"{_kind_name(pk)} → {_kind_name(ck)} 에 `{relation}` 은 쓸 수 없다"}])
    if pk == ROLL and ck == ROLL and pid == cid:
        raise http.validation_error("자기 자신을 부모로 하는 계보는 만들 수 없습니다",
                                    fields=[{"name": "롤", "reason": f"roll_id={pid}"}])
    p, c = _node((pk, pid), cur), _node((ck, cid), cur)
    if p is None:
        raise http.validation_error(f"없는 {_kind_name(pk)}입니다", fields=[{"name": "부모", "reason": f"{pk}:{pid}"}])
    if c is None:
        raise http.validation_error(f"없는 {_kind_name(ck)}입니다", fields=[{"name": "자식", "reason": f"{ck}:{cid}"}])

    pcol = "parent_material_lot_id" if pk == MATERIAL_LOT else "parent_roll_id"
    ccol = "child_roll_id" if ck == ROLL else "child_shipment_id"
    if _rows(cur, f"select 1 from roll_genealogy where {pcol} = %s and {ccol} = %s", (pid, cid)):
        raise http.validation_error("이미 있는 계보입니다 (같은 화살표 중복)",
                                    fields=[{"name": "계보", "reason": f"{p.no} → {c.no}"}])

    if ck == ROLL and c.label != _CHILD_TYPE[relation]:
        raise http.validation_error(
            "관계와 자식 롤의 공정 구분이 맞지 않습니다",
            fields=[{"name": c.no, "reason": f"`{relation}` 의 자식은 {_CHILD_TYPE[relation]} 롤이어야 하는데 {c.label} 롤이다"}])

    if pk == MATERIAL_LOT:
        if p.state != "합격":
            raise http.validation_error(f"입고검사 {p.state} LOT 은 투입할 수 없습니다 (합격 LOT 만)",
                                        fields=[{"name": p.no, "reason": f"입고검사 {p.state}"}])
        return

    if p.state == SHIPPED:
        msg = "이미 출하된 롤입니다" if ck == SHIPMENT else "이미 출하된 롤은 다음 공정에 쓸 수 없습니다"
        raise http.validation_error(msg, fields=[{"name": p.no, "reason": "상태 출하"}])

    if ck == ROLL:
        hit = _rows(cur, """
            with recursive down (roll_id) as (
                select %(child)s::bigint
                union
                select g.child_roll_id from roll_genealogy g join down d on g.parent_roll_id = d.roll_id
                 where g.child_roll_id is not null
            )
            select 1 from down where roll_id = %(parent)s limit 1""", {"child": cid, "parent": pid})
        if hit:
            raise http.validation_error("계보 순환 — 자손 롤을 부모로 쓸 수 없습니다",
                                        fields=[{"name": "계보", "reason": f"{p.no} 은 {c.no} 의 자손이다"}])
        return

    # 출하 (롤 → 출하 LOT)
    if p.state == CONSUMED:
        raise http.validation_error("다음 공정에 쓰인(소진) 롤은 출하할 수 없습니다",
                                    fields=[{"name": p.no, "reason": "상태 소진"}])
    if c.state != "등록":
        raise http.validation_error(f"{c.state} 상태의 출하에는 롤을 담을 수 없습니다",
                                    fields=[{"name": c.no, "reason": f"상태 {c.state}"}])
    if p.job_no != c.job_no:
        raise http.validation_error("출하 LOT 과 Job 이 다른 롤입니다 (출하 LOT 1 = Job 1)",
                                    fields=[{"name": p.no, "reason": f"롤 Job {p.job_no} ≠ 출하 Job {c.job_no}"}])
    last = _rows(cur, """select result from inspection where roll_id = %s
                          order by inspected_at desc, inspection_id desc limit 1""", (pid,))
    if last and last[0]["result"] == "불합격":
        raise http.validation_error("최신 검사가 불합격인 롤은 출하할 수 없습니다",
                                    fields=[{"name": p.no, "reason": "검사 판정 불합격"}])


def link(cur, parent: NodeRef, child: NodeRef, relation: str, *, by: str, qty=None) -> int:
    """계보 한 줄(화살표 하나)을 넣고 genealogy_id 를 돌려준다.

    422: 자기 자신을 부모로 · 순환 · 같은 화살표 중복 · 이미 출하된 롤 재출하 · 소진된 롤 출하 ·
         출하된 롤을 부모로 · 불합격/검사 대기 원재료 LOT 투입 · 관계와 노드 종류가 안 맞음 ·
         (출하) 다른 Job 의 롤 · 최신 검사 불합격 · `등록` 이 아닌 출하.
    소진된 롤을 **다른 작업에서** 다시 부모로 쓰는 것은 여기서 막지 않는다(슬리팅은 한 부모에 자식이 여럿이다) —
    작업을 시작할 때 `assert_usable` 이 막는다.
    """
    _check_link(cur, parent, child, relation)
    (pk, pid), (ck, cid) = _check_ref(parent), _check_ref(child)
    cur.execute(
        """insert into roll_genealogy (parent_material_lot_id, parent_roll_id, child_roll_id, child_shipment_id,
                                       relation, qty, created_by)
           values (%s, %s, %s, %s, %s, %s, %s) returning genealogy_id""",
        (pid if pk == MATERIAL_LOT else None, pid if pk == ROLL else None,
         cid if ck == ROLL else None, cid if ck == SHIPMENT else None, relation, qty, by))
    return cur.fetchone()["genealogy_id"]


def assert_usable(cur, parents: list[NodeRef]) -> None:
    """부모로 쓸 수 있는지 확인한다. 롤은 `재고`, 원재료 LOT 은 `합격`. 아니면 422(무엇이 왜 안 되는지 항목별로).
    아래 `make_*`·`slit_roll`·`ship_roll` 이 작업을 시작할 때 한 번 부른다.

    롤 행을 잠근다(`for no key update`) — 같은 롤을 동시에 두 작업이 쓰면 뒤쪽이 앞의 커밋을 기다렸다가 `소진`/`출하` 를 본다.
    """
    refs = [_check_ref(p) for p in parents]
    roll_ids = sorted({i for k, i in refs if k == ROLL})
    lot_ids = sorted({i for k, i in refs if k == MATERIAL_LOT})
    fields: list[dict] = []
    messages: list[str] = []
    for kind, node_id in refs:
        if kind == SHIPMENT:
            fields.append({"name": f"{SHIPMENT}:{node_id}", "reason": "출하 LOT 은 부모가 될 수 없다"})
            messages.append("출하 LOT 은 부모가 될 수 없습니다")

    if roll_ids:
        cur.execute("select roll_id from roll where roll_id = any(%s) order by roll_id for no key update", (roll_ids,))
        cur.fetchall()
        found = {r["roll_id"]: r for r in _rows(
            cur, "select roll_id, roll_no, state from v_roll_state where roll_id = any(%s)", (roll_ids,))}
        for rid in roll_ids:
            r = found.get(rid)
            if r is None:
                fields.append({"name": f"roll_id={rid}", "reason": "없는 롤"})
                messages.append("없는 롤입니다")
            elif r["state"] == SHIPPED:
                fields.append({"name": r["roll_no"], "reason": "이미 출하된 롤"})
                messages.append("이미 출하된 롤입니다")
            elif r["state"] == CONSUMED:
                fields.append({"name": r["roll_no"], "reason": "이미 다음 공정에 쓰인(소진) 롤"})
                messages.append("이미 소진된 롤입니다 (다음 공정에 쓰였습니다)")

    if lot_ids:
        found = {r["material_lot_id"]: r for r in _rows(
            cur, "select material_lot_id, lot_no, insp_status from material_lot where material_lot_id = any(%s)", (lot_ids,))}
        for lid in lot_ids:
            r = found.get(lid)
            if r is None:
                fields.append({"name": f"material_lot_id={lid}", "reason": "없는 원재료 LOT"})
                messages.append("없는 원재료 LOT 입니다")
            elif r["insp_status"] != "합격":
                fields.append({"name": r["lot_no"], "reason": f"입고검사 {r['insp_status']}"})
                messages.append(f"입고검사 {r['insp_status']} LOT 은 투입할 수 없습니다 (합격 LOT 만)")

    if fields:
        raise http.validation_error(messages[0] if len(set(messages)) == 1 else "쓸 수 없는 롤·LOT 이 있습니다",
                                    fields=fields)


def _insert_roll(cur, *, process_type: str, job_id: int, job_lot_id, work_result_id, equipment_id, length_m,
                 width_mm, slit_seq, by: str) -> dict:
    roll_no = numbering.next(numbering.ROLL, cur=cur)
    cur.execute(
        """insert into roll (roll_no, process_type, job_id, job_lot_id, work_result_id, equipment_id,
                             length_m, width_mm, slit_seq, produced_by)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (roll_no, process_type, job_id, job_lot_id, work_result_id, equipment_id, length_m, width_mm, slit_seq, by))
    return dict(cur.fetchone())


def _check_size(length_m, width_mm) -> None:
    fields = []
    if length_m is not None and length_m < 0:
        fields.append({"name": "길이", "reason": "0 이상이어야 한다"})
    if width_mm is not None and width_mm <= 0:
        fields.append({"name": "폭", "reason": "0 보다 커야 한다"})
    if fields:
        raise http.validation_error("길이·폭을 확인해 주세요", fields=fields)


def make_print_roll(cur, *, work_result_id: int, by: str, length_m=None, width_mm=None) -> dict:
    """인쇄 롤 1개 (F-POP-02 작업 종료). 그 작업 실적의 `material_input` 마다 `투입` 한 줄. 만든 `roll` 행을 돌려준다.

    롤 번호는 `numbering.next('ROLL', cur=cur)`. Job·생산 LOT·설비는 작업 실적에서 가져온다.
    422: 투입 스캔 0건 · 그 실적에 이미 롤이 있다(실적 1 = 롤 1, D-13) · 없는 실적.
    작업 실적의 상태·종료 시각은 건드리지 않는다 — 호출한 라우터(P5)가 같은 트랜잭션에서 닫는다.
    """
    work = _rows(cur, """select work_result_id, job_id, job_lot_id, equipment_id from work_result
                          where work_result_id = %s""", (work_result_id,))
    if not work:
        raise http.validation_error("없는 작업 실적입니다", fields=[{"name": "작업 실적", "reason": str(work_result_id)}])
    w = work[0]
    made = _rows(cur, "select roll_no from roll where work_result_id = %s", (work_result_id,))
    if made:
        raise http.validation_error("이 작업 실적에는 이미 인쇄 롤이 있습니다 (실적 1건 = 롤 1개)",
                                    fields=[{"name": "롤 번호", "reason": made[0]["roll_no"]}])
    inputs = _rows(cur, """select material_lot_id, input_qty from material_input
                            where work_result_id = %s order by scanned_at, material_input_id""", (work_result_id,))
    if not inputs:
        raise http.validation_error("자재 투입 스캔이 없습니다 — 원재료 LOT 을 먼저 스캔하세요",
                                    fields=[{"name": "자재 투입", "reason": "0건"}])
    _check_size(length_m, width_mm)
    assert_usable(cur, [(MATERIAL_LOT, i["material_lot_id"]) for i in inputs])
    roll = _insert_roll(cur, process_type=PRINT_ROLL, job_id=w["job_id"], job_lot_id=w["job_lot_id"],
                        work_result_id=work_result_id, equipment_id=w["equipment_id"], length_m=length_m,
                        width_mm=width_mm, slit_seq=None, by=by)
    for i in inputs:
        link(cur, (MATERIAL_LOT, i["material_lot_id"]), (ROLL, roll["roll_id"]), INPUT, by=by, qty=i["input_qty"])
    return roll


def make_finishing_roll(cur, *, parent_roll_ids: list[int], by: str, job_id: int | None = None,
                        equipment_id: int | None = None, length_m=None, width_mm=None) -> dict:
    """후가공 롤 1개. 부모가 1개면 `후가공` 한 줄(F-RLL-01), 2개 이상이면 `splice` N줄(F-RLL-02).

    `job_id` 를 안 주면 부모 롤들의 Job(전부 같을 때). 부모들의 Job 이 서로 다른데 `job_id` 가 없으면 422.
    422: 부모 0개 · 같은 롤 중복 · 부모가 `재고` 가 아님.
    """
    ids = [int(i) for i in parent_roll_ids]
    if not ids:
        raise http.validation_error("부모 롤이 없습니다 — 롤을 스캔하세요", fields=[{"name": "부모 롤", "reason": "0개"}])
    if len(set(ids)) != len(ids):
        raise http.validation_error("같은 롤을 두 번 스캔했습니다", fields=[{"name": "부모 롤", "reason": "중복"}])
    _check_size(length_m, width_mm)
    assert_usable(cur, [(ROLL, i) for i in ids])
    parents = {r["roll_id"]: r for r in _rows(
        cur, "select roll_id, roll_no, job_id, job_lot_id from roll where roll_id = any(%s)", (ids,))}
    jobs = {p["job_id"] for p in parents.values()}
    if job_id is None:
        if len(jobs) != 1:
            raise http.validation_error("부모 롤들의 Job 이 서로 다릅니다 — 후가공 롤의 Job 을 지정하세요",
                                        fields=[{"name": "Job", "reason": f"부모 롤의 Job {len(jobs)}개"}])
        job_id = next(iter(jobs))
    elif not _rows(cur, "select 1 from job where job_id = %s", (job_id,)):
        raise http.validation_error("없는 Job 입니다", fields=[{"name": "Job", "reason": str(job_id)}])
    lots = {p["job_lot_id"] for p in parents.values()}
    job_lot_id = next(iter(lots)) if len(lots) == 1 and jobs == {job_id} else None   # 생산 LOT 이 하나로 모일 때만 물려준다
    roll = _insert_roll(cur, process_type=FINISHING_ROLL, job_id=job_id, job_lot_id=job_lot_id, work_result_id=None,
                        equipment_id=equipment_id, length_m=length_m, width_mm=width_mm, slit_seq=None, by=by)
    relation = FINISHING if len(ids) == 1 else SPLICE
    for i in ids:
        link(cur, (ROLL, i), (ROLL, roll["roll_id"]), relation, by=by)
    return roll


def slit_roll(cur, *, parent_roll_id: int, count: int, by: str, equipment_id: int | None = None,
              widths_mm: list | None = None, length_m=None) -> list[dict]:
    """슬리팅 — 부모 롤 1개를 `count` 개로 나눈다(F-RLL-04). 슬리팅 롤 N개와 `슬리팅` N줄. `slit_seq` 는 1..N.

    부모 상태는 시작할 때 한 번만 본다(첫 자식을 만들면 부모는 이미 `소진` 이다).
    422: count < 1 · `widths_mm` 길이가 count 와 다름 · 부모가 `재고` 가 아님.
    """
    if count is None or int(count) < 1:
        raise http.validation_error("분할 수는 1 이상이어야 합니다", fields=[{"name": "분할 수", "reason": str(count)}])
    count = int(count)
    if widths_mm is not None and len(widths_mm) != count:
        raise http.validation_error("폭의 개수가 분할 수와 다릅니다",
                                    fields=[{"name": "폭", "reason": f"폭 {len(widths_mm)}개 ≠ 분할 수 {count}"}])
    for w in widths_mm or []:
        _check_size(length_m, w)
    _check_size(length_m, None)
    assert_usable(cur, [(ROLL, int(parent_roll_id))])
    parent = _rows(cur, "select roll_id, job_id, job_lot_id from roll where roll_id = %s", (parent_roll_id,))[0]
    out: list[dict] = []
    for seq in range(1, count + 1):
        roll = _insert_roll(cur, process_type=SLIT_ROLL, job_id=parent["job_id"], job_lot_id=parent["job_lot_id"],
                            work_result_id=None, equipment_id=equipment_id, length_m=length_m,
                            width_mm=widths_mm[seq - 1] if widths_mm else None, slit_seq=seq, by=by)
        link(cur, (ROLL, parent["roll_id"]), (ROLL, roll["roll_id"]), SLITTING, by=by)
        out.append(roll)
    return out


def ship_roll(cur, *, shipment_id: int, roll_id: int, by: str) -> int:
    """출하 롤 스캔 한 건(F-SHP-02) — `link((ROLL, roll_id), (SHIPMENT, shipment_id), '출하')`. genealogy_id.

    422: 이미 출하된 롤 · 소진된 롤 · 다른 Job 의 롤(D-16) · 최신 검사가 불합격(D-17) · `등록` 상태가 아닌 출하.
    P8 이 `roll_genealogy` 에 쓰는 길은 이 함수와 `unlink_shipment` 뿐이다(D-12).
    """
    cur.execute("select shipment_id from shipment where shipment_id = %s for share", (shipment_id,))
    if cur.fetchone() is None:
        raise http.validation_error("없는 출하 LOT 입니다", fields=[{"name": "출하 LOT", "reason": str(shipment_id)}])
    assert_usable(cur, [(ROLL, int(roll_id))])
    return link(cur, (ROLL, int(roll_id)), (SHIPMENT, int(shipment_id)), SHIPPING, by=by)


def unlink_shipment(cur, shipment_id: int, *, by: str) -> int:
    """승인 전 출하의 `출하` 계보 행을 지운다(출하 취소 F-SHP-03). 지운 행 수. 승인된 출하면 422.

    `by` 는 계보에 남지 않는다(행이 지워진다) — 누가 취소했는지는 호출자가 `audit.log_change` 로 남긴다.
    """
    cur.execute("select shipment_no, status from shipment where shipment_id = %s for share", (shipment_id,))
    s = cur.fetchone()
    if s is None:
        raise http.validation_error("없는 출하 LOT 입니다", fields=[{"name": "출하 LOT", "reason": str(shipment_id)}])
    if s["status"] == "승인":
        raise http.validation_error("승인된 출하는 취소할 수 없습니다",
                                    fields=[{"name": s["shipment_no"], "reason": "상태 승인"}])
    cur.execute("delete from roll_genealogy where child_shipment_id = %s and relation = %s", (shipment_id, SHIPPING))
    return cur.rowcount


# ── 읽기 (어떤 테이블에도 쓰지 않는다) ──────────────────────────────────
def resolve(no: str) -> Node | None:
    """번호(스캔값) → 노드. 원재료 LOT · 롤 · 출하 LOT 번호에서 찾는다. 없으면 None(호출자가 422 로 바꾼다).

    번호의 첫 글자로 종류를 가정하지 않는다(접두는 `sys_number_rule` 의 데이터다) — 세 테이블에서 찾는다.
    앞뒤 공백은 떼고, 소문자로 들어온 값은 대문자로도 찾는다(번호는 영문 대문자·숫자·`-`).
    """
    text = (no or "").strip()
    if not text:
        return None
    rows = conn.q(f"select n.* from {_NODES} where n.no = any(%s) order by (n.no = %s) desc, n.kind limit 1",
                  (sorted({text, text.upper()}), text))
    return Node(**rows[0]) if rows else None


def search(text: str, limit: int = 50) -> list[Node]:
    """번호 일부로 원재료 LOT · 롤 · 출하 LOT 을 찾는다(LOT 검색 F-TRC-03). 빈 검색어는 빈 목록."""
    text = (text or "").strip()
    if not text:
        return []
    pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = conn.q(f"select n.* from {_NODES} where n.no ilike %s order by n.no, n.kind limit %s",
                  (pattern, max(1, int(limit))))
    return [Node(**r) for r in rows]


def roll_state(roll_id: int) -> str:
    """롤 상태 — 재고 | 소진 | 출하 (`v_roll_state`). 없는 롤은 404."""
    row = conn.q1("select state from v_roll_state where roll_id = %s", (roll_id,))
    if row is None:
        raise http.not_found()
    return row["state"]


def _one_step(node: NodeRef, column: dict[str, str | None]) -> list[Edge]:
    kind, node_id = _check_ref(node)
    col = column[kind]
    if col is None:
        return []
    sql = _EDGES.format(depth="1", source="roll_genealogy g") + f" where g.{col} = %s order by g.genealogy_id"
    return [_edge(r) for r in conn.q(sql, (node_id,))]


def parents_of(node: NodeRef) -> list[Edge]:
    """한 단계 위(부모 쪽 화살표). 롤 이력 F-RLL-06 이 쓴다. 원재료 LOT 은 부모가 없다(빈 목록)."""
    return _one_step(node, {MATERIAL_LOT: None, ROLL: "child_roll_id", SHIPMENT: "child_shipment_id"})


def children_of(node: NodeRef) -> list[Edge]:
    """한 단계 아래(자식 쪽 화살표). 출하 LOT 은 자식이 없다(빈 목록)."""
    return _one_step(node, {MATERIAL_LOT: "parent_material_lot_id", ROLL: "parent_roll_id", SHIPMENT: None})


def _trace(node: NodeRef, direction: str) -> Trace:
    kind, node_id = _check_ref(node)
    start = _node((kind, node_id))
    if start is None:
        raise http.not_found()
    if direction == BACKWARD:
        start_col = {MATERIAL_LOT: None, ROLL: "child_roll_id", SHIPMENT: "child_shipment_id"}[kind]
        next_col, join_col = "parent_roll_id", "child_roll_id"
    else:
        start_col = {MATERIAL_LOT: "parent_material_lot_id", ROLL: "parent_roll_id", SHIPMENT: None}[kind]
        next_col, join_col = "child_roll_id", "parent_roll_id"
    if start_col is None:        # 원재료 LOT 의 위 · 출하 LOT 의 아래에는 아무것도 없다
        return Trace(start, direction, [])
    sql = _WALK.format(start_col=start_col, next_col=next_col, join_col=join_col)
    return Trace(start, direction, [_edge(r) for r in conn.q(sql, {"id": node_id})])


def trace_backward(node: NodeRef) -> Trace:
    """역방향 — 출하 LOT(또는 롤)에서 원재료 LOT 까지 화살표를 거꾸로 따라간다. 재귀 조회 하나.

    `Trace.material_lots()` 가 답이다. `edges` 는 출발점에서 가까운 순서(`depth` 1 부터), 화살표 중복 없음.
    없는 노드는 404 — 스캔값은 먼저 `resolve()` 로 찾고 None 이면 호출자가 422 를 낸다.
    """
    return _trace(node, BACKWARD)


def trace_forward(node: NodeRef) -> Trace:
    """정방향 — 원재료 LOT(또는 롤)에서 출하 LOT 까지. 자식 없는 롤은 `재고` 로 남는다. 재귀 조회 하나.

    `Trace.shipments()` 가 닿은 출하 LOT, `Trace.stock_rolls()` 가 재고로 남은 롤이다.
    """
    return _trace(node, FORWARD)
