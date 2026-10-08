"""권한 — 설계도 §6 권한 표 48칸(4역할 × 12대메뉴)을 **DB 데이터**로 읽는다 (G-17 · decisions.md D-14).

역할 목록(`sys_role`)도 권한 칸(`sys_permission`)도 이 파일에 박혀 있지 않다. 역할을 늘리거나(D-06) 칸을 바꿔도
코드를 고치지 않는다 — 시스템 관리 > 권한 화면이 행을 바꾸고 `invalidate()` 를 부르면 곧바로 반영된다.
행이 없는 칸은 `없음` 이다(권한을 지어내지 않는다).

판정
  조회  그 대메뉴 칸의 level 이 `조회` 또는 `입력`
  쓰기  칸의 level 이 `입력` 이고, 기능의 범위(`function-list.md` 의 `범위` 열)가 칸의 `write_scope` 에 들어 있다
        → `입력 (입고검사)` 는 입고검사 결과 등록만, `입력 (승인)` 은 출하 승인만. 괄호 없는 `입력` 은 `일반` 기능만.
  없음  메뉴에서 숨기고 403

    require_login(request) -> User            미로그인 → 401
    require_screen("BAS-01") -> Depends       그 화면(중메뉴)을 열 권한. 없으면 403
    require_fn("F-BAS-01") -> Depends         그 기능을 할 권한. 쓰기 기능이면 쓰기 판정, 읽기 기능이면 조회 판정
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Depends, Request

from . import contracts, nav
from .util import http

LEVEL_WRITE, LEVEL_READ, LEVEL_NONE = "입력", "조회", "없음"
LEVELS: tuple[str, ...] = (LEVEL_WRITE, LEVEL_READ, LEVEL_NONE)
SCOPE_GENERAL = contracts.SCOPE_GENERAL


@dataclass(frozen=True)
class Role:
    code: str
    name: str
    sort_no: int = 0


@dataclass(frozen=True)
class Cell:
    """권한 표의 한 칸."""
    level: str = LEVEL_NONE
    scopes: frozenset[str] = frozenset()

    @property
    def can_read(self) -> bool:
        return self.level in (LEVEL_WRITE, LEVEL_READ)

    def can_write(self, scope: str) -> bool:
        return self.level == LEVEL_WRITE and scope in self.scopes

    @property
    def label(self) -> str:
        """설계도 표기 그대로 — `입력` · `입력 (입고검사)` · `조회` · `없음`."""
        if self.level != LEVEL_WRITE:
            return self.level
        extra = sorted(self.scopes - {SCOPE_GENERAL})
        if SCOPE_GENERAL in self.scopes:
            return LEVEL_WRITE + (f" (+{'·'.join(extra)})" if extra else "")
        return f"{LEVEL_WRITE} ({'·'.join(extra)})"


NO_CELL = Cell()


def parse_scopes(write_scope: str | None) -> frozenset[str]:
    return frozenset(p.strip() for p in (write_scope or "").split(",") if p.strip())


# ── DB 에서 읽기 (짧은 캐시) ────────────────────────────────────────────
_CACHE: dict[str, object] = {"at": 0.0, "roles": None, "cells": None}
CACHE_SECONDS = 5.0


def invalidate() -> None:
    """권한·역할 행을 바꾼 뒤 부른다. 다음 요청부터 DB 를 다시 읽는다."""
    _CACHE["at"], _CACHE["roles"], _CACHE["cells"] = 0.0, None, None


def _load() -> tuple[list[Role], dict[tuple[str, str], Cell]]:
    """DB 연결 실패는 삼키지 않는다(503)."""
    now = time.monotonic()
    if _CACHE["roles"] is not None and now - float(_CACHE["at"]) < CACHE_SECONDS:  # type: ignore[arg-type]
        return _CACHE["roles"], _CACHE["cells"]  # type: ignore[return-value]
    from ..db import conn  # noqa — 순환 import 회피

    role_rows = conn.q("select role_code, role_name, sort_no from sys_role where use_yn = 'Y' order by sort_no, role_code")
    cell_rows = conn.q("select role_code, menu_code, level, write_scope from sys_permission")
    roles = [Role(r["role_code"], r["role_name"], r["sort_no"]) for r in role_rows]
    cells = {(r["role_code"], r["menu_code"]): Cell(r["level"], parse_scopes(r["write_scope"])) for r in cell_rows}
    _CACHE["at"], _CACHE["roles"], _CACHE["cells"] = now, roles, cells
    return roles, cells


def roles() -> list[Role]:
    return _load()[0]


def role(code: str) -> Role | None:
    return next((r for r in roles() if r.code == code), None)


def cell(role_code: str, menu_code: str) -> Cell:
    """권한 표 한 칸. 행이 없으면 `없음`. 확장 대메뉴(D-418)는 설계도 대메뉴 한 칸을 그대로 따른다 — 칸을 늘리지 않는다."""
    return _load()[1].get((role_code, nav.permission_menu(menu_code)), NO_CELL)


def can_read_menu(role_code: str, menu_code: str) -> bool:
    return cell(role_code, menu_code).can_read


def can_open(role_code: str, screen_id: str) -> bool:
    """화면(중메뉴) 조회 가능 여부. 공통 화면(메인·로그인·오류)은 권한 표 밖 — 로그인만 하면 연다."""
    sc = nav.by_id(screen_id)
    if sc.common:
        return True
    return can_read_menu(role_code, sc.menu_code)


def can_do(role_code: str, function_id: str) -> bool:
    """기능 수행 가능 여부. 쓰기 기능 = 쓰기 판정(범위 포함), 읽기 기능 = 조회 판정."""
    fn = contracts.function(function_id)
    if fn.is_batch:
        return False   # 배치는 화면 권한으로 돌리지 않는다 (명령)
    c = cell(role_code, fn.menu_code)
    return c.can_write(fn.scope) if fn.is_write else c.can_read


def matrix() -> list[dict]:
    """화면 표시용 — 대메뉴 12행 × 역할 열. 값은 DB 그대로."""
    rs = roles()
    return [{"menu": m, "cells": [cell(r.code, m.code) for r in rs]} for m in nav.MENUS]


def counts() -> dict[str, int]:
    """현재 DB 권한 표의 칸 수 — {'입력': n, '조회': n, '없음': n, '전체': n}. (사용 중 역할 × 대메뉴 12)"""
    out = {LEVEL_WRITE: 0, LEVEL_READ: 0, LEVEL_NONE: 0}
    for r in roles():
        for m in nav.MENUS:
            out[cell(r.code, m.code).level] += 1
    out["전체"] = sum(out.values())
    return out


# ── 사용자 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class User:
    login_id: str
    user_name: str
    role_code: str
    role_name: str

    def can_open(self, screen_id: str) -> bool:
        return can_open(self.role_code, screen_id)

    def can(self, function_id: str) -> bool:
        return can_do(self.role_code, function_id)

    def to_session(self) -> dict:
        return {"login_id": self.login_id, "user_name": self.user_name, "role_code": self.role_code,
                "role_name": self.role_name}

    @staticmethod
    def from_session(data: dict) -> "User":
        return User(login_id=str(data["login_id"]), user_name=data["user_name"], role_code=data["role_code"],
                    role_name=data["role_name"])


# ── 세션 → 사용자 (D-26) ────────────────────────────────────────────────
SESSION_ID_KEY = "sid"       # 세션 ID — 로그아웃하면 `sys_user.revoked_sessions` 에 올라간다
SESSION_EPOCH_KEY = "ep"     # 로그인 때의 `sys_user.session_epoch` — 상태·비밀번호가 바뀌면 DB 값이 올라가 어긋난다
STATUS_ACTIVE = "정상"
_STATE_ATTR = "lcomfine_user"
_UNSET = object()


def unverified_user(request: Request) -> User | None:
    """세션 쿠키에 적힌 사용자 그대로(**DB 확인 없음**). 오류 로그처럼 DB 를 다시 볼 수 없는 자리에서만 쓴다 — 권한 판정에 쓰지 않는다."""
    data = request.session.get("user") if hasattr(request, "session") else None
    if not data or "login_id" not in data:
        return None
    return User.from_session(data)


def forget_user(request: Request) -> None:
    """이 요청에서 확인해 둔 사용자를 버린다 (로그인·로그아웃 직후)."""
    if hasattr(request, "state"):
        setattr(request.state, _STATE_ATTR, _UNSET)


def _verified_user(request: Request) -> User | None:
    claimed = unverified_user(request)
    if claimed is None:
        return None
    session_id = request.session.get(SESSION_ID_KEY)
    row = None
    if session_id:
        from ..db import conn  # noqa — 순환 import 회피

        row = conn.q1(
            """select u.user_name, u.role_code, r.role_name, u.status, u.session_epoch,
                      (u.revoked_sessions ? %s) as revoked
                 from sys_user u join sys_role r on r.role_code = u.role_code
                where u.login_id = %s""",
            (str(session_id), claimed.login_id))
    if (row is None or row["status"] != STATUS_ACTIVE or row["revoked"]
            or row["session_epoch"] != request.session.get(SESSION_EPOCH_KEY)):
        request.session.clear()   # 중지·잠금 · 로그아웃한 세션 · 상태/비밀번호가 바뀐 뒤의 옛 세션 · 지워진 계정 → 미로그인
        return None
    return User(login_id=claimed.login_id, user_name=row["user_name"], role_code=row["role_code"], role_name=row["role_name"])


def current_user(request: Request) -> User | None:
    """이 요청의 사용자. 세션이 없거나 더는 유효하지 않으면 None (오류를 내지 않는다).

    **요청마다 DB 의 계정을 다시 본다** — 중지·잠금된 계정, 로그아웃한 세션은 곧바로 미로그인이 되고(401),
    역할·이름은 쿠키가 아니라 DB 의 지금 값이다(역할을 바꾸면 다음 요청부터 그 역할의 권한). 한 요청 안에서는 한 번만 조회한다.
    DB 연결 실패는 삼키지 않는다(503).
    """
    if not hasattr(request, "state"):
        return _verified_user(request)
    cached = getattr(request.state, _STATE_ATTR, _UNSET)
    if cached is _UNSET:
        cached = _verified_user(request)
        setattr(request.state, _STATE_ATTR, cached)
    return cached


def require_login(request: Request) -> User:
    """미로그인 → 401 `로그인이 필요합니다` (브라우저 GET 은 main.py 가 /login 303 으로 바꾼다)."""
    user = current_user(request)
    if user is None:
        raise http.unauthorized()
    return user


def require_screen(screen_id: str):
    """화면 접근 의존성. 그 대메뉴 칸이 `없음` 이면 403.

        @router.get(nav.path_of("BAS-01"))
        def items(request: Request, user=rbac.require_screen("BAS-01")): ...
    """
    nav.by_id(screen_id)   # 없는 화면 ID 는 import 시점에 실패

    def _dep(request: Request) -> User:
        user = require_login(request)
        if not user.can_open(screen_id):
            raise http.forbidden(screen_id=screen_id)
        return user

    return Depends(_dep)


def require_fn(function_id: str):
    """기능 수행 의존성 — **쓰기 엔드포인트는 반드시 이것을 쓴다.** 조회 권한만 있는 역할의 쓰기는 403.

        @router.post("/bas/items")
        def create_item(request: Request, user=rbac.require_fn("F-BAS-01")): ...
    """
    contracts.function(function_id)   # 없는 기능 ID 는 import 시점에 실패

    def _dep(request: Request) -> User:
        user = require_login(request)
        if not user.can(function_id):
            raise http.forbidden(function_id=function_id)
        return user

    return Depends(_dep)


def visible_menu(user: User | None) -> list[dict]:
    """설계도 묶음 > 대메뉴 > 중메뉴 (화면에는 그리지 않는다 — 로그인 여부 판정 · 검사용). `없음` 인 대메뉴는 숨긴다(G-17). 미로그인이면 빈 목록."""
    if user is None:
        return []
    tree = []
    for node in nav.menu_tree():
        menus = [m for m in node["menus"] if can_read_menu(user.role_code, m.code)]
        if menus:
            tree.append({"group": node["group"], "menus": menus})
    return tree


def visible_sidebar(user: User | None) -> list[dict]:
    """좌측 메뉴와 메인 화면 카드 — 묶음 없이 일하는 순서(`nav.SIDEBAR`, D-417). 숨김 규칙은 `visible_menu` 와 같고(확장 대메뉴는 물려받은 칸),
    공통 화면(메인)은 권한 표 밖이라 로그인만 하면 보인다. 미로그인이면 빈 목록."""
    if user is None:
        return []
    return [it for it in nav.sidebar_items()
            if it["kind"] == "screen" or can_read_menu(user.role_code, it["menu"].code)]
