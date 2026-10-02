"""렌더링 — `contracts/interfaces.md` §2.

    render(request, template, ctx, *, screen_id=...) -> HTMLResponse

`screen_id` 를 주면
  · 헤더(시스템명 · 화면 위치 · 현재 일시 · 사용자 · 로그아웃)
  · 좌측 메뉴(묶음 4 > 대메뉴 > 중메뉴 — 권한 `없음` 은 숨김)
  · 우측 계약 패널(그 화면의 기능 줄 — `contracts/function-list.md`)
  · 채널별 레이아웃(`?device=pop|mobile|board` — D-19)
을 자동으로 채우고 접근 로그(`sys_access_log` 구분 `조회`)를 남긴다 (G-18).

개발자는 `{% block search %}` `{% block grid %}` `{% block actions %}` 만 채우거나, `{% block body %}` 를 통째로 바꾼다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import auth, contracts, nav, rbac
from .settings import get_settings
from .util import audit, http, screen

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
env.globals.update(NOT_COLLECTED=screen.NOT_COLLECTED, EXAMPLE=screen.EXAMPLE)
env.filters.update(txt=screen.txt, num=screen.num, dt=screen.dt)

#: 접근 로그에 `조회` 로 남기지 않는 공통 화면 (로그인은 `로그인` 구분으로 따로 남는다)
NO_VIEW_LOG = {"login", "error"}


def _fmt_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def asset_version() -> str:
    """정적 자산 캐시 무효화 키 — style.css·app.js 의 최종 수정시각."""
    try:
        return str(int(max((STATIC_DIR / n).stat().st_mtime for n in ("style.css", "app.js"))))
    except OSError:
        return "0"


def screen_context(request: Request, screen_id: str | None) -> dict[str, Any]:
    """base.html 이 필요로 하는 공통 컨텍스트."""
    s = get_settings()
    user = rbac.current_user(request)
    device = auth.device_of(request)
    ctx: dict[str, Any] = {
        "request": request,
        "asset_v": asset_version(),
        "flash": http.pop_flash(request),
        "system_name": nav.SYSTEM_NAME,
        "now": _fmt_now(),
        "user": user,
        "menus": rbac.visible_menu(user),
        "device": device,                       # web | pop | mobile | board
        "channel": nav.DEVICE_CHANNEL[device],  # 관리자 Web | 현장 POP | 모바일 | 현황판
        "settings": s,
        "nav": nav,
        "screen_id": screen_id,
        "screen": None,
        "screen_name": "",
        "menu_name": "",
        "active_menu": "",
        "functions": [],
        "grid_page_size": s.grid_page_size,
    }
    if screen_id:
        sc = nav.by_id(screen_id)
        ctx["screen"] = sc
        ctx["screen_name"] = sc.name
        ctx["menu_name"] = sc.menu
        ctx["active_menu"] = sc.menu_code
        if not sc.common:
            ctx["functions"] = [{"fn": f, "allowed": bool(user and user.can(f.id))} for f in contracts.functions_of(screen_id)]
    return ctx


def render(request: Request, template: str, ctx: dict | None = None, *, screen_id: str | None = None,
           status_code: int = 200) -> HTMLResponse:
    base = screen_context(request, screen_id)
    if ctx:
        base.update(ctx)
    user = base.get("user")
    if screen_id and screen_id not in NO_VIEW_LOG and user is not None:
        audit.write_log(log_type=audit.VIEW, login_id=user.login_id, role_code=user.role_code, method=request.method,
                        path=request.url.path, screen_id=screen_id, ok=status_code < 400, detail="",
                        ip=audit.client_ip(request))
    html = env.get_template(template).render(**base)
    return HTMLResponse(html, status_code=status_code)


def placeholder(request: Request, screen_id: str) -> HTMLResponse:
    """미구현 화면 — HTTP **200** 으로 "미구현 — 담당 개발N" 과 계약 문장을 보여 준다.

    화면이 비어 있다는 사실을 숨기지 않는다. `tools/check_routes.py` 가 이 표식을 세어 G-03 을 판정한다.
    """
    return render(request, "_placeholder.html", {"item": nav.by_id(screen_id)}, screen_id=screen_id)
