"""렌더링 — `contracts/interfaces.md` §5.

    render(request, template, ctx, *, screen_id=..., status_code=200) -> HTMLResponse
    placeholder(request, screen_id) -> HTMLResponse

자동 컨텍스트 (base.html 이 쓴다)
  user        rbac.User | None — 로그인 전 화면(login · error)은 None 이어도 그려진다
  screen      nav.Screen | None (screen_id 를 준 화면)
  bundles     rbac.visible_menu(user) — 묶음 ⓪~⑦ > 대메뉴 > 볼 수 있는 화면 (좌측 메뉴)
  flow        흐름 띠 7단계 — [{screen_id, name, path, allowed, current}] (rbac.can_flow)
  functions   contracts.functions_of(screen_id) — 계약 패널
  fn_allowed  {기능 ID: 이 사용자가 할 수 있는가} (rbac.can_do)
  unread      그 사람 부서의 미처리 알림 수 (notify.unread)
  system_name · settings · flash · asset_v · now · nav · screen_id
화면 렌더마다 접근 로그 1행(`sys_access_log` 구분 `조회`)을 남긴다 (공통 화면 login · error 제외).

개발자는 `{% block search %}` `{% block grid %}` `{% block actions %}` 를 채우거나 `{% block body %}` 를 통째로 바꾼다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import contracts, nav, notify, rbac
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
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def asset_version() -> str:
    """정적 자산 캐시 무효화 키 — style.css·app.js 의 최종 수정시각."""
    try:
        return str(int(max((STATIC_DIR / n).stat().st_mtime for n in ("style.css", "app.js"))))
    except OSError:
        return "0"


def flow_steps(user: rbac.User | None, screen_id: str | None = None) -> list[dict]:
    """흐름 띠 7단계 — 권한 판정은 `rbac.can_flow` 그대로, 이름·경로는 nav 에서."""
    out = []
    for sid, allowed in rbac.can_flow(user):
        sc = nav.by_id(sid)
        out.append({"screen_id": sid, "name": sc.name, "path": sc.path, "allowed": allowed,
                    "current": sid == screen_id})
    return out


def screen_context(request: Request, screen_id: str | None) -> dict[str, Any]:
    """base.html 이 필요로 하는 공통 컨텍스트."""
    s = get_settings()
    user = rbac.current_user(request)
    sc = nav.by_id(screen_id) if screen_id else None
    fns = contracts.functions_of(screen_id) if sc and not sc.common else []
    return {
        "request": request,
        "asset_v": asset_version(),
        "flash": http.pop_flash(request),
        "system_name": nav.SYSTEM_NAME,
        "now": _fmt_now(),
        "user": user,
        "bundles": rbac.visible_menu(user),
        "flow": flow_steps(user, screen_id) if user else [],
        # TODO: notify 에 count(*) 전용 `unread_count(user)` 가 생기면 그것으로 (notify.py 는 아키텍트 소관)
        "unread": len(notify.unread(user)) if user else 0,
        "settings": s,
        "dev": s.env == "dev",
        "nav": nav,
        "screen_id": screen_id,
        "screen": sc,
        "page_title": sc.name if sc else "",
        "functions": fns,
        "fn_allowed": {f.id: rbac.can_do(user, f.id) for f in fns},
        "grid_page_size": s.grid_page_size,
    }


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
    """미구현 화면 — HTTP **200** 으로 「아직 만들지 않음 — 담당 개발N」과 그 화면의 계약 줄을 보여 준다.

    화면이 비어 있다는 사실을 숨기지 않는다. `tools/check_routes.py` 가 이 표식(`class="tag"` + `미구현`)을 센다.
    """
    return render(request, "_placeholder.html", {"item": nav.by_id(screen_id)}, screen_id=screen_id)
