"""home 라우터 — 공통 메인(`/`). 담당 개발1 (아키텍트가 최소 구현을 넣어 두었다. 개발1 이 이어받아 채운다).

로그인(`/login`)·오류(`/error`)·`/health` 는 아키텍트 소관이라 `app/main.py` 에 있다.
메인은 권한 표 밖이다 — 로그인한 누구나 연다. 보이는 메뉴만 권한(`없음` 은 숨김)을 따른다.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import nav, rbac, templating

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def main_page(request: Request, user: rbac.User = Depends(rbac.require_login)) -> HTMLResponse:
    levels = {m.code: rbac.cell(user.role_code, m.code).label for m in nav.MENUS}
    return templating.render(request, "home/main.html", {"levels": levels}, screen_id="home")
