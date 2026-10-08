"""FastAPI 앱 — 세션 · 오류 핸들러 · 라우터 include · 로그인 · /health.

**개발자는 이 파일을 만지지 않는다.** 라우터는 모듈명으로 자동 include 한다 — `routers/<모듈>.py` 의 `router`.
라우터가 아직 등록하지 않은 중메뉴 화면 경로는 `_placeholder.html` 로 **HTTP 200** + "미구현 — 담당 개발N" +
계약 문장을 낸다. 화면이 없다는 사실을 숨기지 않는다. 라우터가 그 경로를 등록하면 placeholder 는 저절로 빠진다.
"""

from __future__ import annotations

import importlib
import logging
import secrets
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from ..db import conn
from . import auth, contracts, erp, nav, rbac, templating
from .settings import get_settings
from .templating import STATIC_DIR, render
from .util import audit, http

log = logging.getLogger("lcomfine")


def _placeholder_routes() -> list:
    """중메뉴 32 의 GET 경로를 placeholder 로 만든다. RBAC 는 그대로 탄다 — 미로그인 401 · 권한 없음 403."""
    router = APIRouter()

    def make(screen_id: str):
        def view(request: Request, user=rbac.require_screen(screen_id)) -> HTMLResponse:
            return templating.placeholder(request, screen_id)

        view.__name__ = f"placeholder_{screen_id.replace('-', '_').lower()}"
        return view

    for s in nav.SCREENS:
        router.add_api_route(s.path, make(s.screen_id), methods=["GET"], response_class=HTMLResponse,
                             include_in_schema=False)
    return list(router.routes)


def create_app() -> FastAPI:
    s = get_settings()
    contracts.functions()   # 계약 표가 깨졌으면 여기서 실패한다 (조용히 기동하지 않는다)
    # API 문서는 엔드포인트와 입력 항목을 전부 보여 준다 — 인증 없이 열리는 것은 /health · /static · 로그인 화면뿐이다.
    # 그래서 기본 주소(/docs · /redoc · /openapi.json)를 닫고, 명세만 로그인한 시스템 관리 조회 권한자에게 준다(아래 /openapi.json).
    app = FastAPI(title=nav.SYSTEM_NAME, description="엘컴화인 MES — Job-Lot-Roll 계보", version="0.1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)

    # Starlette 는 나중에 add_middleware 한 것이 바깥이다. 이 미들웨어는 request.session 을 읽으므로
    # SessionMiddleware 보다 **먼저** 등록해 안쪽에서 돌게 한다.
    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        if request.url.path.startswith("/static"):
            response = await call_next(request)
        else:
            if auth.session_expired(request):
                request.session.clear()
            response = await call_next(request)
            auth.touch_session(request)
        for k, v in http.SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    app.add_middleware(SessionMiddleware, secret_key=s.session_secret or secrets.token_urlsafe(32),
                       session_cookie=s.session_cookie, same_site="lax", https_only=False,
                       max_age=auth.SESSION_MAX_AGE_SECONDS)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── 라우터 include (모듈명 = nav.MODULES) ──
    registered: set[tuple[str, str]] = set()
    include_errors: list[str] = []          # 원문까지 — 서버 쪽(`app.state` · check-routes · 서버 로그)만 본다
    include_error_names: list[str] = []     # `/health` 에 싣는 것 — 모듈과 예외 종류뿐 (예외 문구는 인증 없는 응답에 싣지 않는다, D-32)
    for module in nav.MODULES:
        try:
            mod = importlib.import_module(f"lcomfine.app.routers.{module}")
        except Exception as exc:  # noqa: BLE001 — 임포트 실패를 숨기지 않는다: /health(모듈·예외 종류)와 게이트·서버 로그(원문)에 나온다
            log.exception("라우터 임포트 실패: %s", module)
            include_errors.append(f"{module}: {type(exc).__name__}: {exc}")
            include_error_names.append(f"{module}: {type(exc).__name__}")
            continue
        r = getattr(mod, "router", None)
        if r is None:
            include_errors.append(f"{module}: router 없음")
            include_error_names.append(f"{module}: router 없음")
            continue
        app.include_router(r)
        for route in r.routes:
            for m in getattr(route, "methods", None) or ():
                registered.add((m, getattr(route, "path", "")))
    app.state.include_errors = include_errors

    # ── 인증 (아키텍트 소관) ──
    def _safe_next(nxt: str | None) -> str | None:
        """같은 사이트 상대경로만 허용(오픈 리다이렉트 방지)."""
        if nxt and nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
            return nxt
        return None

    def _login_page(request: Request, *, message: str = "", login_id: str = "", next: str | None = None,
                    device: str | None = None, status_code: int = 200) -> HTMLResponse:
        """로그인 화면 한 장 — 퀵 로그인 패널(D-416)은 켜진 환경에서만 그린다. 비밀번호 값은 어디에도 싣지 않는다."""
        quick = auth.quick_login_accounts() if auth.quick_login_enabled() else None
        return render(request, "login.html",
                      {"message": message, "login_id": login_id, "next": _safe_next(next) or "",
                       "login_device": device if device in nav.DEVICE_CHANNEL else "web", "quick": quick},
                      screen_id="login", status_code=status_code)

    def _after_login(request: Request, result: auth.LoginResult, *, login_id: str, next: str | None,
                     device: str | None, failed_prefix: str = ""):
        if not result.ok or result.user is None:
            if not http.wants_html(request):
                return JSONResponse({"code": "unauthorized", "message": failed_prefix + result.reason}, status_code=401)
            return _login_page(request, message=failed_prefix + result.reason, login_id=login_id, next=next,
                               device=device, status_code=401)
        auth.login_session(request, result.user, device)
        return RedirectResponse(_safe_next(next) or auth.home_path_for(request, result.user), status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str | None = None, device: str | None = None) -> HTMLResponse:
        return _login_page(request, message="로그인이 필요합니다" if next else "", next=next, device=device)

    @app.post("/login")
    def login_submit(request: Request, login_id: str = Form(...), password: str = Form(...),
                     next: str | None = Form(None), device: str | None = Form(None)):
        result = auth.authenticate(login_id, password, client_ip=audit.client_ip(request))
        return _after_login(request, result, login_id=login_id, next=next, device=device)

    @app.post("/login/quick")
    def login_quick(request: Request, quick_id: str = Form(...), next: str | None = Form(None),
                    device: str | None = Form(None)):
        """퀵 로그인(D-416) — 고른 계정을 **시드 비밀번호**로 인증한다. 판정·접근 로그·실패 횟수는 보통 로그인과 같다.
        꺼진 환경(운영 · 플래그 없음 · 시드 비밀번호 없음)에서는 404 — 단추도 없고 주소도 없다."""
        if not auth.quick_login_enabled():
            raise http.not_found(auth.QUICK_OFF)
        result = auth.authenticate(quick_id, get_settings().seed_password or "", client_ip=audit.client_ip(request),
                                   via=auth.QUICK_VIA)
        return _after_login(request, result, login_id=quick_id, next=next, device=device,
                            failed_prefix="" if result.ok else f"{auth.QUICK_VIA} 실패 — ")

    @app.post("/logout")
    @app.get("/logout")
    def logout(request: Request):
        auth.logout_session(request)
        return RedirectResponse("/login", status_code=303)

    @app.get("/error", response_class=HTMLResponse)
    def error_screen(request: Request, status: int | None = None) -> HTMLResponse:
        """공통 오류 화면. 인자 없이 열면 오류 계약 안내(200), `?status=` 를 주면 그 상태코드로 응답한다."""
        st = status if (status is not None and 400 <= status <= 599) else None
        shown = st or 422
        return render(request, "_error.html",
                      {"status": shown, "code": http.code_for_status(shown), "message": http.status_message(shown),
                       "fields": [], "detail_note": "", "guide": st is None,
                       "board_refresh_seconds": s.board_refresh_seconds},
                      screen_id="error", status_code=st or 200)

    @app.get("/openapi.json", include_in_schema=False)
    def openapi_spec(user: rbac.User = Depends(rbac.require_login)) -> JSONResponse:
        """API 명세 — 미로그인 401, 시스템 관리 대메뉴를 조회할 수 없는 역할 403. (/docs · /redoc 화면은 두지 않는다 — 외부 CDN 을 부른다)"""
        if not rbac.can_read_menu(user.role_code, nav.by_id("SYS-01").menu_code):
            raise http.forbidden()
        return JSONResponse(app.openapi())

    # ── ERP 연계 (G-16 · D-02) — 연계가 정해지기 전에는 무엇을 부르든 501 `ERP 연계 미확정 (D-02)` ──
    @app.get("/erp/{kind}")
    def erp_receive(kind: str, user: rbac.User = Depends(rbac.require_login)):
        erp_adapter = erp.adapter()
        return erp_adapter.status() if kind == "status" else erp_adapter.receive(kind)

    @app.post("/erp/{kind}")
    def erp_send(kind: str, user: rbac.User = Depends(rbac.require_login)):
        erp_adapter = erp.adapter()
        return erp_adapter.status() if kind == "status" else erp_adapter.send(kind, {})

    # ── /health (인증 없이 열린다 — 상태값과 건수만 싣는다. 접속 문자열·호스트·사용자·DB 이름은 **가리는 것이 아니라 싣지 않는다**, D-32) ──
    @app.get("/health")
    def health() -> JSONResponse:
        try:
            conn.ping()
            db_ok, db_reason = True, ""
        except conn.DbUnavailable as exc:   # 원문(소켓 경로·호스트)은 인증 없는 응답에 싣지 않는다 — 서버 로그에만 (비밀번호는 conn 이 가린다)
            log.error("/health — DB 연결 실패: %s", exc)
            db_ok, db_reason = False, "DB 연결 실패 — 원인은 서버 로그에 있다"
        fns = contracts.functions()
        body = {
            "status": "ok" if db_ok and not include_errors else "degraded",
            "system": nav.SYSTEM_NAME,
            "db": {"ok": db_ok, "reason": db_reason},
            "groups": len(nav.GROUPS),
            "menus": len(nav.MENUS),
            "screens": len(nav.SCREENS),
            "functions": sum(1 for f in fns if not f.is_batch),
            "batch_functions": sum(1 for f in fns if f.is_batch),
            "placeholders": len(app.state.placeholder_paths),
            "router_include_errors": include_error_names,
        }
        return JSONResponse(body, status_code=200 if db_ok else 503)

    # ── 오류 핸들러 (goal.md §2.5 · contracts/api-contract.md) ──
    def _error_page(request: Request, status: int, code: str, message: str, *, fields=None, note: str = ""):
        """오류 화면. DB 가 끊긴 상태에서도 그려져야 하므로 메뉴·접근 로그를 타지 않는다."""
        html = templating.env.get_template("_error.html").render(
            request=request, system_name=nav.SYSTEM_NAME, asset_v=templating.asset_version(), status=status,
            code=code, message=message, fields=fields or [], detail_note=note, guide=False, device=auth.device_of(request),
            board_refresh_seconds=s.board_refresh_seconds)
        return HTMLResponse(html, status_code=status, headers=http.SECURITY_HEADERS)

    def _screen_to_return(request: Request) -> str:
        """Referer 없는 폼 POST 가 돌아갈 **열리는 화면**. POST 전용 주소(`/pop/work/start` 등)로 보내면 405 가 되어 알림을 볼 수 없다.
        요청 경로와 같거나 그 앞부분인 화면 경로 중 가장 긴 것 → 없으면 메인."""
        path = request.url.path
        hits = [sc.path for sc in nav.ALL if sc.path != "/" and (path == sc.path or path.startswith(sc.path + "/"))]
        return max(hits, key=len) if hits else "/"

    def _back_with_flash(request: Request, message: str, fields: list[dict]):
        """브라우저 폼 POST 의 422 — 입력하던 화면으로 303 돌아가 알림으로 보인다. POP 은 다음 스캔을 막지 않는다."""
        http.flash(request, "입력값을 확인해 주세요", message, fields=fields, kind="warn")
        return RedirectResponse(request.headers.get("referer") or _screen_to_return(request), status_code=303)

    def _invalid_input(request: Request, message: str, fields: list[dict]):
        """422 응답의 세 모양 — 폼 POST 는 303 + 알림, 브라우저 GET 은 오류 화면, 그 밖은 JSON (api-contract.md §2)."""
        if http.wants_html(request) and request.method == "POST":
            return _back_with_flash(request, message, fields)
        if http.wants_html(request):
            return _error_page(request, 422, "validation_error", message, fields=fields)
        return JSONResponse({"code": "validation_error", "message": message, "fields": fields}, status_code=422)

    @app.exception_handler(StarletteHTTPException)   # 라우터 미매치 404 도 계약대로
    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code") or http.code_for_status(exc.status_code)
        message = detail.get("message") or http.status_message(exc.status_code)
        html = http.wants_html(request)
        if exc.status_code == 401 and html and request.method in ("GET", "HEAD") and request.url.path != "/login":
            nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(nxt, safe='')}", status_code=303)
        if exc.status_code == 422 and html and request.method == "POST":
            return _back_with_flash(request, message, detail.get("fields") or [])
        if html:
            return _error_page(request, exc.status_code, code, message, fields=detail.get("fields"),
                               note=detail.get("decision", ""))
        return JSONResponse({"code": code, "message": message,
                             **{k: v for k, v in detail.items() if k not in {"code", "message"}}},
                            status_code=exc.status_code)

    #: 요청 형식 검증(FastAPI)의 영문 사유 → 화면에 보일 한국어. 표에 없는 종류는 원문 그대로 보인다(숨기지 않는다)
    _REASONS = {"missing": "필수 항목입니다", "int_parsing": "정수여야 합니다", "float_parsing": "숫자여야 합니다",
                "decimal_parsing": "숫자여야 합니다", "date_parsing": "날짜 형식(YYYY-MM-DD)이 아닙니다",
                "date_from_datetime_parsing": "날짜 형식(YYYY-MM-DD)이 아닙니다", "datetime_parsing": "일시 형식이 아닙니다",
                "datetime_from_date_parsing": "일시 형식이 아닙니다", "bool_parsing": "예/아니오 값이어야 합니다"}

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        fields = [{"name": ".".join(str(x) for x in e.get("loc", [])[1:]) or "입력",
                   "reason": _REASONS.get(e.get("type", ""), e.get("msg", ""))} for e in exc.errors()]
        return _invalid_input(request, http.status_message(422), fields)

    @app.exception_handler(psycopg.errors.IntegrityError)
    async def on_integrity_error(request: Request, exc: psycopg.errors.IntegrityError):
        """DB 제약 위반(중복 코드 · FK · CHECK · 계보 지킴이 트리거) → 422. 라우터가 먼저 검증하는 것이 원칙이고 이것은 마지막 방어선이다."""
        diag = getattr(exc, "diag", None)
        reason = (getattr(diag, "message_primary", None) or str(exc)).strip()
        return _invalid_input(request, http.status_message(422),
                              [{"name": getattr(diag, "constraint_name", None) or "제약", "reason": reason}])

    @app.exception_handler(psycopg.DataError)
    async def on_data_error(request: Request, exc: psycopg.DataError):
        """DB 가 담을 수 없는 **입력값**(글자 속 NUL 0x00 · 컬럼 자릿수를 넘는 수 · 형식이 틀린 날짜·숫자) → 422.
        입력값 오류이지 서버 오류가 아니다(goal.md §2.5 1행). 라우터가 사람이 읽을 문장으로 먼저 거르는 것이 원칙이고,
        이것은 놓친 경우에도 500 이 되지 않게 하는 마지막 방어선이다 — 경로·조회 인자·본문 어디로 들어와도 여기 한 곳에서 막는다."""
        if isinstance(exc, psycopg.errors.NumericValueOutOfRange):
            reason = "숫자가 저장할 수 있는 범위를 넘었습니다"
        elif isinstance(exc, psycopg.errors.StringDataRightTruncation):
            reason = "글자 수가 저장할 수 있는 길이를 넘었습니다"
        elif isinstance(exc, (psycopg.errors.InvalidDatetimeFormat, psycopg.errors.DatetimeFieldOverflow)):
            reason = "날짜·일시 형식이 올바르지 않습니다"
        elif isinstance(exc, psycopg.errors.InvalidTextRepresentation):
            reason = "값의 형식이 올바르지 않습니다"
        elif "NUL" in str(exc):
            reason = "쓸 수 없는 글자(NUL)가 들어 있습니다"
        else:
            reason = "저장할 수 없는 값입니다"
        return _invalid_input(request, http.status_message(422), [{"name": "입력", "reason": reason}])

    @app.exception_handler(conn.DbUnavailable)
    async def on_db_unavailable(request: Request, exc: conn.DbUnavailable):
        """503 `서비스 일시 중단`. 접속 오류 원문(소켓 경로·호스트·DB 이름)은 응답에 싣지 않고 서버 로그에만 남긴다 —
        미로그인 로그인 POST 에서도 나오는 응답이다."""
        log.error("DB 연결 실패 %s %s — %s", request.method, request.url.path, exc)
        if http.wants_html(request):
            return _error_page(request, 503, "db_unavailable", "서비스 일시 중단")
        return JSONResponse({"code": "db_unavailable", "message": "서비스 일시 중단"},
                            status_code=503, headers=http.SECURITY_HEADERS)

    @app.exception_handler(Exception)
    async def on_unhandled_exception(request: Request, exc: Exception):
        """처리되지 않은 예외 → 500 `예상하지 못한 오류`. 원인은 서버 로그와 접근 로그(구분 `오류`)에 남긴다.
        dev 에서는 원인을 응답에 보이고 prod 에서는 숨긴다."""
        log.exception("미처리 예외 %s %s", request.method, request.url.path)
        user = rbac.unverified_user(request)   # 오류를 처리하는 중에 DB 를 다시 보지 않는다 (쿠키에 적힌 사용자 그대로 로그에 남긴다)
        try:
            sc = nav.by_path(request.url.path)
            audit.write_log(log_type=audit.ERROR, login_id=user.login_id if user else None,
                            role_code=user.role_code if user else None, method=request.method, path=request.url.path,
                            screen_id=sc.screen_id if sc else None, ok=False,
                            detail=f"500 {type(exc).__name__}: {exc}", ip=audit.client_ip(request))
        except Exception:  # noqa: BLE001 — 로그 적재 실패가 원래의 500 응답을 가리지 않게 한다 (서버 로그에는 남는다)
            log.exception("접근 로그(오류) 기록 실패")
        reason = f"{type(exc).__name__}: {exc}" if get_settings().env == "dev" else ""
        if http.wants_html(request):
            return _error_page(request, 500, "internal_error", "예상하지 못한 오류", note=reason)
        body = {"code": "internal_error", "message": "예상하지 못한 오류"}
        if reason:
            body["reason"] = reason
        return JSONResponse(body, status_code=500, headers=http.SECURITY_HEADERS)

    # ── 미구현 화면 placeholder (라우터가 GET 을 등록하지 않은 중메뉴 경로만) ──
    ph = APIRouter()
    for r in _placeholder_routes():
        if ("GET", getattr(r, "path", "")) not in registered:
            ph.routes.append(r)
    app.include_router(ph)
    app.state.placeholder_paths = [getattr(r, "path", "") for r in ph.routes]
    return app


app = create_app()
