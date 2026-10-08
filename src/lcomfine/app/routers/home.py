"""home 라우터 — 공통 메인(`/`) = IA(정보 구조) 화면. 담당 개발1 (D-419).

로그인(`/login`)·오류(`/error`)·`/health` 는 아키텍트 소관이라 `app/main.py` 에 있다.
메인은 권한 표 밖이다 — 로그인한 누구나 연다. 설계도를 한 장으로 보여 준다: 업무 흐름(프로세스 10 · 저장소 8) → 메뉴(좌측 메뉴와 같은
일하는 순서, D-417) → 데이터(저장소 → 테이블) → Job-Lot-Roll 계보 · 번호 → 사용자 · 채널 → 확인 필요.
글은 `app/ia.py`(설계도에서 옮긴 것), 수는 계약(`contracts`)·메뉴(`nav`)·권한 표(DB)·채번 규칙(DB)에서 센다 — 화면에 지어낸 숫자는 없다.
칸이 `없음` 인 대메뉴는 카드도 링크도 없다(G-17). 확장 대메뉴(영업관리 · D-418)는 물려받은 칸으로 판정한다. 어떤 테이블에도 쓰지 않는다.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import contracts, ia, nav, numbering, rbac, templating

router = APIRouter()


def _number_rules() -> list[dict]:
    """채번 7종 — 형식은 `sys_number_rule` 행(DB)에서. 예시 번호는 행의 형식으로 만든 모양이지 발번이 아니다."""
    out = []
    for kind in numbering.KINDS:
        row = numbering.rule(kind)
        if row is None:
            out.append({"kind": kind, "label": kind, "pattern": "미수집", "ext": kind == numbering.SALES_ORDER})
            continue
        pattern = f"{row['prefix']}{row['date_format']}{'0' * (row['seq_digits'] - 1)}1"
        out.append({"kind": kind, "label": (row["note"] or kind).split(" — ")[0], "pattern": pattern,
                    "ext": kind == numbering.SALES_ORDER})
    return out


def _role_summary() -> list[dict]:
    """역할 4 × 설계도 대메뉴 12 의 칸 수 — 권한 표(DB)의 지금 값. 확장은 세지 않는다."""
    out = []
    for r in rbac.roles():
        levels = [rbac.cell(r.code, m.code).level for m in nav.MENUS]
        out.append({"role": r, "write": levels.count(rbac.LEVEL_WRITE), "read": levels.count(rbac.LEVEL_READ),
                    "none": levels.count(rbac.LEVEL_NONE),
                    "write_menus": [m.name for m in nav.MENUS if rbac.cell(r.code, m.code).level == rbac.LEVEL_WRITE]})
    return out


@router.get("/", response_class=HTMLResponse)
def main_page(request: Request, user: rbac.User = Depends(rbac.require_login)) -> HTMLResponse:
    cells = {m.code: rbac.cell(user.role_code, m.code) for m in nav.MENUS + nav.EXT_MENUS}
    # 카드 순서 = 좌측 메뉴 순서(설계도 12 + 확장, 권한 `없음` 은 뺀다). 메인 자신(공통 화면)은 카드가 아니다.
    cards = [it["menu"] for it in rbac.visible_sidebar(user) if it["kind"] == "menu"]
    visible = [m for m in cards if not m.ext]
    ext_visible = [m for m in cards if m.ext]
    # 대메뉴별로 이 역할이 할 수 있는 쓰기 기능 수 — 권한 표와 계약(function-list.md · extension-list.md)에서 센다
    writable = {m.code: sum(1 for f in contracts.functions_of_menu(m.code) if f.is_write and user.can(f.id)) for m in cards}
    # 중메뉴별 기능 이름 — 계약 그대로 (메뉴 카드의 설명)
    screen_fns = {s.screen_id: [f.name for f in contracts.functions_of(s.screen_id)] for m in cards for s in m.screens}
    return templating.render(request, "home/main.html", {
        "levels": {code: cell.label for code, cell in cells.items()},
        "writable": writable, "cards": cards, "screen_fns": screen_fns,
        "menu_processes": {m.code: ia.processes_of_menu(m.code) for m in cards},
        "steps": ia.process_steps(cards),
        "stores": ia.stores(),
        "number_rules": _number_rules(),
        "role_summary": _role_summary(),
        "batch": contracts.batch_functions(),
        "ia": ia,
        "summary": {"menus": len(visible), "all_menus": len(nav.MENUS),
                    "screens": sum(len(m.screens) for m in visible), "all_screens": len(nav.SCREENS),
                    "ext_menus": len(ext_visible), "all_ext_menus": len(nav.EXT_MENUS),
                    "functions": len(contracts.functions()), "tables": sum(1 for t in contracts.db_tables().values() if t.store != "EXT")},
    }, screen_id="home")
