"""home 라우터 — 공통 메인(`/`). 담당 개발1.

로그인(`/login`)·오류(`/error`)·`/health` 는 아키텍트 소관이라 `app/main.py` 에 있다.
메인은 권한 표 밖이다 — 로그인한 누구나 연다. 보이는 것은 그 역할의 권한 표(DB)를 따른다:
묶음 4 > 대메뉴 바로가기, 칸이 `없음` 인 대메뉴는 나오지 않는다(G-17). 어떤 테이블에도 쓰지 않는다(조회 로그는 `templating` 이 남긴다).
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import contracts, nav, rbac, templating

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def main_page(request: Request, user: rbac.User = Depends(rbac.require_login)) -> HTMLResponse:
    cells = {m.code: rbac.cell(user.role_code, m.code) for m in nav.MENUS}
    visible = [m for m in nav.MENUS if cells[m.code].can_read]
    # 대메뉴별로 이 역할이 할 수 있는 쓰기 기능 수 — 권한 표와 계약(function-list.md)에서 센다
    writable = {m.code: sum(1 for f in contracts.functions_of_menu(m.code) if f.is_write and user.can(f.id))
                for m in visible}
    return templating.render(request, "home/main.html", {
        "levels": {code: cell.label for code, cell in cells.items()},
        "writable": writable,
        "summary": {"menus": len(visible), "all_menus": len(nav.MENUS),
                    "screens": sum(len(m.screens) for m in visible), "all_screens": len(nav.SCREENS)},
    }, screen_id="home")
