"""권한 — 부서 8 × 화면 67 의 권한 칸(`W` · `R` · 없음)을 **DB 데이터**로 읽는다 (D-511 · D-513 · D-514).

부서 목록(`sys_role`)도 권한 칸(`sys_permission(role_code, screen_id, level)`)도 이 파일에 박혀 있지 않다.
칸을 바꾸면 `invalidate()` 를 부른다 — 다음 요청부터 반영된다. 행이 없는 칸은 권한 없음이다(권한을 지어내지 않는다).
칸의 원본은 `contracts/permission-matrix.md` 이고 시드(`db/seed.py`)가 그대로 넣는다.

판정
  R  화면 칸이 `W` 또는 `R`
  W  화면 칸이 `W`
  기능  쓰기 유형(`contracts.WRITE_KINDS`)이면 W, 조회 유형 · 권한 예외(`Function.read_ok` — F-DOC-011 · F-RPT-132 · F-HOME-022)는 R
  공통 화면(login · error)은 권한 표 밖 — 로그인만 하면 연다

    require_login(request) -> User            미로그인 → 401
    require_screen("BAS-010") -> Depends      화면 R 이상. 없으면 403 「이 화면을 볼 권한이 없습니다」
    require_fn("F-BAS-011") -> Depends        기능 판정. 없으면 403 「이 기능을 실행할 권한이 없습니다」
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from fastapi import Depends, Request

from . import contracts, nav
from .util import http

LEVEL_W, LEVEL_R = "W", "R"
LEVELS: tuple[str, ...] = (LEVEL_W, LEVEL_R)
SCREEN_DENIED = "이 화면을 볼 권한이 없습니다"
FN_DENIED = "이 기능을 실행할 권한이 없습니다"


@dataclass(frozen=True)
class Role:
    code: str
    name: str
    sort_no: int = 0


# ── DB 에서 읽기 (짧은 캐시) ────────────────────────────────────────────
_CACHE: dict[str, object] = {"at": 0.0, "roles": None, "cells": None}
CACHE_SECONDS = 5.0


def invalidate() -> None:
    """권한·부서 행을 바꾼 뒤 부른다. 다음 판정부터 DB 를 다시 읽는다."""
    _CACHE["at"], _CACHE["roles"], _CACHE["cells"] = 0.0, None, None


def _load() -> tuple[list[Role], dict[tuple[str, str], str]]:
    """DB 연결 실패는 삼키지 않는다(503)."""
    now = time.monotonic()
    if _CACHE["roles"] is not None and now - float(_CACHE["at"]) < CACHE_SECONDS:  # type: ignore[arg-type]
        return _CACHE["roles"], _CACHE["cells"]  # type: ignore[return-value]
    from ..db import conn  # noqa — 순환 import 회피

    role_rows = conn.q("select role_code, role_name, sort_no from sys_role where use_yn = 'Y' order by sort_no, role_code")
    cell_rows = conn.q("select role_code, screen_id, level from sys_permission")
    roles_ = [Role(r["role_code"], r["role_name"], r["sort_no"]) for r in role_rows]
    cells = {(r["role_code"], r["screen_id"]): r["level"] for r in cell_rows}
    _CACHE["at"], _CACHE["roles"], _CACHE["cells"] = now, roles_, cells
    return roles_, cells


def roles() -> list[Role]:
    """사용 중인 부서 — 표시 순서(권한 표의 열 순서)."""
    return _load()[0]


def role(code: str) -> Role | None:
    return next((r for r in roles() if r.code == code), None)


def level(role_code: str, screen_id: str) -> str | None:
    """권한 표 한 칸 — `W` · `R` · None(칸 없음)."""
    return _load()[1].get((role_code, screen_id))


def counts() -> dict[str, int]:
    """DB 권한 표의 칸 수 — {'W': n, 'R': n, '전체': n}. 행이 없는 칸은 세지 않는다."""
    cells = _load()[1]
    out = {LEVEL_W: 0, LEVEL_R: 0}
    for lv in cells.values():
        out[lv] += 1
    out["전체"] = len(cells)
    return out


def matrix() -> list[dict]:
    """화면 표시용 — 화면 67행 × 부서 열. 값은 DB 그대로(`W` · `R` · None)."""
    rs = roles()
    return [{"screen": sc, "cells": [level(r.code, sc.screen_id) for r in rs]} for sc in nav.SCREENS]


# ── 사용자 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class User:
    id: int              # sys_user.user_id
    login_id: str
    name: str            # sys_user.user_name
    role_code: str       # 부서 코드 — 알림 수신 · 권한 판정
    role_name: str
    status: str

    def to_session(self) -> dict:
        return {"id": self.id, "login_id": self.login_id, "name": self.name, "role_code": self.role_code,
                "role_name": self.role_name, "status": self.status}

    @staticmethod
    def from_session(data: dict) -> "User":
        return User(id=int(data.get("id") or 0), login_id=str(data["login_id"]), name=data.get("name", ""),
                    role_code=data.get("role_code", ""), role_name=data.get("role_name", ""),
                    status=data.get("status", ""))


_USER_SQL = """select u.user_id, u.login_id, u.user_name, u.role_code, r.role_name, u.status, u.session_epoch,
                      (u.revoked_sessions ? %s) as revoked
                 from sys_user u join sys_role r on r.role_code = u.role_code
                where u.login_id = %s"""


def _user_of(row: dict) -> User:
    return User(id=row["user_id"], login_id=row["login_id"], name=row["user_name"], role_code=row["role_code"],
                role_name=row["role_name"], status=row["status"])


def load_user(login_id: str) -> User | None:
    """그 계정의 지금 값(상태와 무관). 없으면 None. 세션 판정은 하지 않는다 — 배치 · 검사 도구 · 테스트용."""
    from ..db import conn  # noqa — 순환 import 회피

    row = conn.q1(_USER_SQL, ("", login_id))
    return None if row is None else _user_of(row)


# ── 판정 ────────────────────────────────────────────────────────────────
def can(user: User | None, screen_id: str, level_: str = LEVEL_R) -> bool:
    """`R` = 칸이 W 또는 R · `W` = 칸이 W. 공통 화면은 로그인만 하면 R. 미로그인은 False."""
    if level_ not in LEVELS:
        raise ValueError(f"권한 수준이 아니다: {level_!r} — W 또는 R")
    sc = nav.by_id(screen_id)
    if user is None:
        return False
    if sc.common:
        return level_ == LEVEL_R
    have = level(user.role_code, screen_id)
    return have == LEVEL_W if level_ == LEVEL_W else have in LEVELS


def can_do(user: User | None, function_id: str) -> bool:
    """기능 수행 가능 여부 — 쓰기 유형은 W, 조회 유형과 권한 예외(`read_ok`)는 R."""
    fn = contracts.function(function_id)
    return can(user, fn.screen_id, LEVEL_R if fn.read_ok else LEVEL_W)


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

        row = conn.q1(_USER_SQL, (str(session_id), claimed.login_id))
    if (row is None or row["status"] != STATUS_ACTIVE or row["revoked"]
            or row["session_epoch"] != request.session.get(SESSION_EPOCH_KEY)):
        request.session.clear()   # 중지·잠금 · 로그아웃한 세션 · 상태/비밀번호가 바뀐 뒤의 옛 세션 · 지워진 계정 → 미로그인
        return None
    return _user_of(row)


def current_user(request: Request) -> User | None:
    """이 요청의 사용자. 세션이 없거나 더는 유효하지 않으면 None (오류를 내지 않는다).

    **요청마다 DB 의 계정을 다시 본다** — 중지·잠금된 계정, 로그아웃한 세션은 곧바로 미로그인이 되고(401),
    부서·이름은 쿠키가 아니라 DB 의 지금 값이다(부서를 바꾸면 다음 요청부터 그 부서의 권한). 한 요청 안에서는 한 번만 조회한다.
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
    """화면 접근 의존성 — 화면 칸이 R 이상이 아니면 403. 공통 화면은 로그인만 본다.

        @router.get(nav.path_of("BAS-010"))
        def items(request: Request, user=rbac.require_screen("BAS-010")): ...
    """
    nav.by_id(screen_id)   # 없는 화면 ID 는 import 시점에 실패

    def _dep(request: Request) -> User:
        user = require_login(request)
        if not can(user, screen_id, LEVEL_R):
            raise http.forbidden(SCREEN_DENIED, screen_id=screen_id)
        return user

    return Depends(_dep)


def require_fn(function_id: str):
    """기능 수행 의존성 — **쓰기 엔드포인트는 반드시 이것을 쓴다.** 쓰기 유형은 W 칸, 권한 예외 · 조회 유형은 R 칸.

        @router.post("/bas/items")
        def create_item(request: Request, user=rbac.require_fn("F-BAS-011")): ...
    """
    contracts.function(function_id)   # 없는 기능 ID 는 import 시점에 실패

    def _dep(request: Request) -> User:
        user = require_login(request)
        if not can_do(user, function_id):
            raise http.forbidden(FN_DENIED, function_id=function_id)
        return user

    return Depends(_dep)


# ── 메뉴 ────────────────────────────────────────────────────────────────
def visible_menu(user: User | None) -> list[dict]:
    """`nav.menu_tree()` 와 같은 모양 — [{bundle, menus: [Menu(screens=볼 수 있는 화면만)]}].
    볼 화면이 없는 대메뉴 · 대메뉴가 없는 묶음은 뺀다. 미로그인이면 빈 목록."""
    if user is None:
        return []
    tree = []
    for node in nav.menu_tree():
        menus = []
        for m in node["menus"]:
            screens = tuple(sc for sc in m.screens if can(user, sc.screen_id, LEVEL_R))
            if screens:
                menus.append(replace(m, screens=screens))
        if menus:
            tree.append({"bundle": node["bundle"], "menus": menus})
    return tree


def can_flow(user: User | None) -> list[tuple[str, bool]]:
    """흐름 띠 7단계(`nav.FLOW`) — (화면 ID, 링크 가능 여부)."""
    return [(sid, can(user, sid, LEVEL_R)) for sid in nav.FLOW]
