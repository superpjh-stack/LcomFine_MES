"""trc 라우터 — LOT 추적 (기능 3) · 담당 개발3 · 프로세스 P9.

**어떤 테이블에도 쓰지 않는다**(G-05). 이 파일에는 SQL 이 한 줄도 없다 — 개발2 `lineage` 의 **읽기 함수만** 부른다
(`resolve` · `search` · `trace_forward` · `trace_backward`). 추적은 `roll_genealogy` 를 따라가는 재귀 조회 하나이고,
경로·결과를 어디에도 저장하지 않는다(매번 다시 조회한다). 화면을 열 때 남는 접근 로그 한 줄은 공통 코드
(`templating.render`)의 것이다(D-15).

번호 하나(원재료 LOT · 롤 · 출하 LOT)를 넣으면 경로가 단계별로 보인다. 자식이 없는 롤은 `재고` 로 표시한다.
모바일 폭 390px 에서 가로 스크롤이 없도록 표가 아니라 세로로 쌓는 목록으로 그린다(G-13).

  TRC-01 추적 (정방향, 역방향, LOT 검색) → /trc/trace
      F-TRC-01 정방향 추적 [조회] GET /trc/trace/forward     `?no=` 원재료 LOT·롤 → 출하 LOT
      F-TRC-02 역방향 추적 [조회] GET /trc/trace/backward    `?no=` 출하 LOT·롤 → 원재료 LOT (완료 기준)
      F-TRC-03 LOT 검색 [조회] GET /trc/trace                `?q=` 번호 일부
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import lineage, nav, rbac, templating
from ..util import http

router = APIRouter()

SEARCH_LIMIT = 50
TEMPLATE = "trc/trace.html"
#: 종류별로 갈 수 있는 방향 — 원재료 LOT 은 계보의 맨 앞(위가 없다), 출하 LOT 은 맨 끝(아래가 없다)
DIRECTIONS: dict[str, tuple[str, ...]] = {
    lineage.MATERIAL_LOT: (lineage.FORWARD,),
    lineage.ROLL: (lineage.FORWARD, lineage.BACKWARD),
    lineage.SHIPMENT: (lineage.BACKWARD,),
}


def _start(no: str, direction: str) -> tuple[lineage.Node | None, Exception | None]:
    """`?no=` 를 (노드, 사유) 로. 비어 있거나 없는 번호, 그 방향으로 갈 수 없는 종류면 노드 없이 422 사유를 돌려준다
    (사용자가 넣은 번호다). **올리지 않는다** — 올릴지 화면을 다시 그릴지는 `_trace` 가 정한다."""
    no = (no or "").strip()
    if not no:
        return None, http.validation_error("번호를 입력해 주세요", fields=[{"name": "번호", "reason": "비어 있음"}])
    node = lineage.resolve(no)
    if node is None:
        return None, http.validation_error("없는 번호입니다 — 원재료 LOT · 롤 · 출하 LOT 번호가 아닙니다",
                                           fields=[{"name": "번호", "reason": no}])
    if direction not in DIRECTIONS[node.kind]:
        if node.kind == lineage.SHIPMENT:
            message = "출하 LOT 은 계보의 맨 끝입니다 — 역방향 추적으로 조회합니다"
        else:
            message = "원재료 LOT 은 계보의 맨 앞입니다 — 정방향 추적으로 조회합니다"
        return None, http.validation_error(message, fields=[{"name": node.no, "reason": node.label}])
    return node, None


def _stages(trace: lineage.Trace) -> list[dict]:
    """화살표를 출발점에서 가까운 순서(`depth`)로 묶는다 — 화면의 "단계". 계산해서 보여 줄 뿐 저장하지 않는다."""
    stages: dict[int, dict] = {}
    for e in trace.edges:
        stage = stages.setdefault(e.depth, {"depth": e.depth, "edges": [], "relations": []})
        stage["edges"].append(e)
        if e.relation not in stage["relations"]:
            stage["relations"].append(e.relation)
    return [stages[d] for d in sorted(stages)]


def _render(request: Request, status_code: int = 200, **ctx) -> HTMLResponse:
    base = {"mode": "search", "q": "", "no": "", "results": None, "trace": None, "stages": [], "limit": SEARCH_LIMIT,
            "directions": DIRECTIONS, "L": lineage, "scan_error": None}
    base.update(ctx)
    return templating.render(request, TEMPLATE, base, screen_id="TRC-01", status_code=status_code)


def _trace(request: Request, no: str, direction: str) -> HTMLResponse:
    """번호 하나에서 그 방향으로 추적한 화면. 없는 번호 · 그 방향으로 갈 수 없는 번호는 422 —
    JSON 은 그대로 올리고, 브라우저는 **이 화면**을 422 로 다시 그린다(사유가 보이고 입력칸이 남는다, D-201)."""
    node, problem = _start(no, direction)
    if problem is not None:
        if not http.wants_html(request):
            raise problem
        detail = problem.detail if isinstance(problem.detail, dict) else {}
        return _render(request, status_code=422, mode="search",
                       scan_error={"message": detail.get("message", ""), "fields": detail.get("fields") or []})
    trace = lineage.trace_forward(node.ref) if direction == lineage.FORWARD else lineage.trace_backward(node.ref)
    return _render(request, mode=direction, no=node.no, q=node.no, trace=trace, stages=_stages(trace))


@router.get(nav.path_of("TRC-01"), response_class=HTMLResponse)                     # F-TRC-03 LOT 검색 = 화면 GET
def search(request: Request, q: str = "", no: str = "", user: rbac.User = rbac.require_fn("F-TRC-03")) -> HTMLResponse:
    q = (q or no).strip()                     # 화면의 입력칸은 세 버튼이 같이 쓰는 `no` 다. `q` 는 링크용
    results = lineage.search(q, limit=SEARCH_LIMIT) if q else None
    return _render(request, mode="search", q=q, results=results)


@router.get(nav.path_of("TRC-01") + "/forward", response_class=HTMLResponse)        # F-TRC-01 정방향 추적
def forward(request: Request, no: str = "", user: rbac.User = rbac.require_fn("F-TRC-01")) -> HTMLResponse:
    return _trace(request, no, lineage.FORWARD)


@router.get(nav.path_of("TRC-01") + "/backward", response_class=HTMLResponse)       # F-TRC-02 역방향 추적
def backward(request: Request, no: str = "", user: rbac.User = rbac.require_fn("F-TRC-02")) -> HTMLResponse:
    return _trace(request, no, lineage.BACKWARD)
