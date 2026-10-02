"""계보 — `roll_genealogy` 에 쓰고(부모 → 자식 한 줄) 그 기록을 따라 읽는(재귀 조회) **한 곳** (G-06 · G-07).

담당 **개발2**. 아키텍트가 만든 것은 시그니처뿐이다 — 본문은 개발2 가 R1 에서 채우고 `progress-dev2.md` §1 에 공표한다.
개발3 의 LOT 추적·출하는 여기 함수만 부른다. **다른 모듈은 `roll_genealogy` 에 직접 쓰지 않는다.**

지킬 것
  · 추적은 조회 하나다. 경로·결과를 다른 테이블에 저장하지 않는다. `trace_*` 는 어떤 테이블에도 쓰지 않는다(G-05).
  · 깊이·분기 수를 가정하지 않는다 — `with recursive` 로 끝까지 따라간다.
  · 쓰기 함수는 전부 `cur`(`conn.tx()` 의 커서)를 받는다. 롤 생성과 계보 행이 한 트랜잭션이어야 한다.
  · 검증 실패는 `http.validation_error(...)`(422)로 올린다. DB 의 지킴이 트리거(schema.sql)는 마지막 방어선이다.

노드는 `(종류, id)` 로 가리킨다. 종류는 MATERIAL_LOT · ROLL · SHIPMENT.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MATERIAL_LOT, ROLL, SHIPMENT = "material_lot", "roll", "shipment"
NODE_KINDS: tuple[str, ...] = (MATERIAL_LOT, ROLL, SHIPMENT)

#: roll_genealogy.relation — 설계도 §3 그림의 관계 이름 + 1:1 후가공
INPUT, FINISHING, SPLICE, SLITTING, SHIPPING = "투입", "후가공", "splice", "슬리팅", "출하"
RELATIONS: tuple[str, ...] = (INPUT, FINISHING, SPLICE, SLITTING, SHIPPING)

#: 롤 상태 (뷰 v_roll_state.state) — 저장하지 않고 계보에서 계산한다
IN_STOCK, CONSUMED, SHIPPED = "재고", "소진", "출하"

NodeRef = tuple[str, int]

_TODO = "미구현 — 담당 개발2 (app/lineage.py)"


@dataclass(frozen=True)
class Node:
    kind: str                 # material_lot | roll | shipment
    id: int
    no: str                   # lot_no · roll_no · shipment_no
    label: str                # 원재료 LOT | 인쇄 | 후가공 | 슬리팅 | 출하 LOT
    state: str | None = None  # 롤: 재고 | 소진 | 출하 · 원재료 LOT: 검사 상태 · 출하: 등록 | 승인
    job_no: str | None = None


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
        """출발점을 포함해 지나간 노드 전부(중복 없음)."""
        raise NotImplementedError(_TODO)

    def material_lots(self) -> list[Node]:
        """역방향 추적의 답 — 닿은 원재료 LOT."""
        raise NotImplementedError(_TODO)

    def shipments(self) -> list[Node]:
        """정방향 추적의 답 — 닿은 출하 LOT."""
        raise NotImplementedError(_TODO)

    def stock_rolls(self) -> list[Node]:
        """정방향 추적에서 자식 없이 끝난 롤 — 화면에 `재고` 로 표시한다."""
        raise NotImplementedError(_TODO)


# ── 쓰기 ────────────────────────────────────────────────────────────────
def link(cur, parent: NodeRef, child: NodeRef, relation: str, *, by: str, qty=None) -> int:
    """계보 한 줄(화살표 하나)을 넣고 genealogy_id 를 돌려준다.

    422: 자기 자신을 부모로 · 순환 · 같은 화살표 중복 · 이미 출하된 롤 재출하 · 소진된 롤 출하 ·
         출하된 롤을 부모로 · 불합격/검사 대기 원재료 LOT 투입 · 관계와 노드 종류가 안 맞음.
    """
    raise NotImplementedError(_TODO)


def assert_usable(cur, parents: list[NodeRef]) -> None:
    """부모로 쓸 수 있는지 확인한다. 롤은 `재고`, 원재료 LOT 은 `합격`. 아니면 422(무엇이 왜 안 되는지 항목별로).
    아래 `make_*`·`slit_roll`·`ship_roll` 이 작업을 시작할 때 한 번 부른다."""
    raise NotImplementedError(_TODO)


def make_print_roll(cur, *, work_result_id: int, by: str, length_m=None, width_mm=None) -> dict:
    """인쇄 롤 1개 (F-POP-02 작업 종료). 그 작업 실적의 `material_input` 마다 `투입` 한 줄. 만든 `roll` 행을 돌려준다.

    롤 번호는 `numbering.next('ROLL', cur=cur)`. Job·생산 LOT·설비는 작업 실적에서 가져온다.
    422: 투입 스캔 0건 · 그 실적에 이미 롤이 있다(실적 1 = 롤 1, D-13).
    """
    raise NotImplementedError(_TODO)


def make_finishing_roll(cur, *, parent_roll_ids: list[int], by: str, job_id: int | None = None,
                        equipment_id: int | None = None, length_m=None, width_mm=None) -> dict:
    """후가공 롤 1개. 부모가 1개면 `후가공` 한 줄(F-RLL-01), 2개 이상이면 `splice` N줄(F-RLL-02).

    `job_id` 를 안 주면 부모 롤들의 Job(전부 같을 때). 부모들의 Job 이 서로 다른데 `job_id` 가 없으면 422.
    422: 부모 0개 · 같은 롤 중복 · 부모가 `재고` 가 아님.
    """
    raise NotImplementedError(_TODO)


def slit_roll(cur, *, parent_roll_id: int, count: int, by: str, equipment_id: int | None = None,
              widths_mm: list | None = None, length_m=None) -> list[dict]:
    """슬리팅 — 부모 롤 1개를 `count` 개로 나눈다(F-RLL-04). 슬리팅 롤 N개와 `슬리팅` N줄. `slit_seq` 는 1..N.

    부모 상태는 시작할 때 한 번만 본다(첫 자식을 만들면 부모는 이미 `소진` 이다).
    422: count < 1 · `widths_mm` 길이가 count 와 다름 · 부모가 `재고` 가 아님.
    """
    raise NotImplementedError(_TODO)


def ship_roll(cur, *, shipment_id: int, roll_id: int, by: str) -> int:
    """출하 롤 스캔 한 건(F-SHP-02) — `link((ROLL, roll_id), (SHIPMENT, shipment_id), '출하')`. genealogy_id.

    422: 이미 출하된 롤 · 소진된 롤 · 다른 Job 의 롤(D-16) · 최신 검사가 불합격(D-17) · `등록` 상태가 아닌 출하.
    P8 이 `roll_genealogy` 에 쓰는 길은 이 함수와 `unlink_shipment` 뿐이다(D-12).
    """
    raise NotImplementedError(_TODO)


def unlink_shipment(cur, shipment_id: int, *, by: str) -> int:
    """승인 전 출하의 `출하` 계보 행을 지운다(출하 취소 F-SHP-03). 지운 행 수. 승인된 출하면 422."""
    raise NotImplementedError(_TODO)


# ── 읽기 (어떤 테이블에도 쓰지 않는다) ──────────────────────────────────
def resolve(no: str) -> Node | None:
    """번호(스캔값) → 노드. 원재료 LOT · 롤 · 출하 LOT 번호에서 찾는다. 없으면 None(호출자가 422 로 바꾼다)."""
    raise NotImplementedError(_TODO)


def search(text: str, limit: int = 50) -> list[Node]:
    """번호 일부로 원재료 LOT · 롤 · 출하 LOT 을 찾는다(LOT 검색 F-TRC-03)."""
    raise NotImplementedError(_TODO)


def roll_state(roll_id: int) -> str:
    """롤 상태 — 재고 | 소진 | 출하 (`v_roll_state`)."""
    raise NotImplementedError(_TODO)


def parents_of(node: NodeRef) -> list[Edge]:
    """한 단계 위(부모 쪽 화살표). 롤 이력 F-RLL-06 이 쓴다."""
    raise NotImplementedError(_TODO)


def children_of(node: NodeRef) -> list[Edge]:
    """한 단계 아래(자식 쪽 화살표)."""
    raise NotImplementedError(_TODO)


def trace_backward(node: NodeRef) -> Trace:
    """역방향 — 출하 LOT(또는 롤)에서 원재료 LOT 까지 화살표를 거꾸로 따라간다. 재귀 조회 하나."""
    raise NotImplementedError(_TODO)


def trace_forward(node: NodeRef) -> Trace:
    """정방향 — 원재료 LOT(또는 롤)에서 출하 LOT 까지. 자식 없는 롤은 `재고` 로 남는다. 재귀 조회 하나."""
    raise NotImplementedError(_TODO)
