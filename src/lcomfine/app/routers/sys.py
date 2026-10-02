"""sys 라우터 — 시스템 관리 (기능 7) · 담당 개발1.

쓰는 저장소: SYS (`sys_user` `sys_permission`). D1~D8 에는 쓰지 않는다(G-05 · D-15).

  · 사용자 — 비밀번호는 해시만 저장하고 화면·응답에 내보내지 않는다(G-19). 삭제는 행을 지우지 않고 상태 `중지`(D-21).
  · 권한 — 권한 표는 DB 데이터다. 한 칸을 바꾸면 `rbac.invalidate()` 로 즉시 반영한다. 역할·칸을 코드에 박지 않는다(D-14).
  · 로그 — `sys_access_log` 를 읽기만 한다(G-18). 로그는 `auth` · `templating` · `audit` · `main` 이 쓴다.

담당 화면과 기능 (contracts/function-list.md)
  SYS-01 사용자 → /sys/users
      F-SYS-01 사용자 등록 [등록] POST /sys/users
      F-SYS-02 사용자 수정 [수정] POST /sys/users/{login_id}
      F-SYS-03 사용자 삭제 [삭제] POST /sys/users/{login_id}/delete
      F-SYS-04 사용자 조회 [조회] GET /sys/users
  SYS-02 권한 → /sys/permissions
      F-SYS-05 권한 조회 [조회] GET /sys/permissions
      F-SYS-06 권한 수정 [수정] POST /sys/permissions
  SYS-03 로그 → /sys/logs
      F-SYS-07 로그 조회 [조회] GET /sys/logs
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.datastructures import FormData

from ...db import conn
from .. import auth, contracts, nav, rbac, templating
from ..util import audit, http
from .bas import bad, contains, form_data, text_of

router = APIRouter()

USERS, PERMISSIONS, LOGS = nav.path_of("SYS-01"), nav.path_of("SYS-02"), nav.path_of("SYS-03")
ST_ACTIVE, ST_LOCKED, ST_STOPPED = "정상", "잠금", "중지"
USER_STATUSES = (ST_ACTIVE, ST_LOCKED, ST_STOPPED)
LOGIN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,49}")      # 경로(`/sys/users/{login_id}`)에 그대로 들어가는 글자만
LOG_TYPES = (audit.LOGIN, audit.VIEW, audit.CHANGE, audit.ERROR)
LOG_LIMIT = 500
USER_LIMIT = 1000

SYS_MENU = "SYS"
#: 잠김 방지로 지키는 칸의 역할 — function-list.md F-SYS-06 「관리자의 시스템 관리 칸」. 역할 코드는 공통 시드의 것이다(D-20)
GUARDED_ROLE = "ADMIN"

# 비밀번호 해시는 어떤 조회에도 넣지 않는다
USER_COLUMNS = """u.login_id, u.user_name, u.role_code, r.role_name, u.status, u.fail_count, u.last_login_at,
                  u.created_at, u.created_by, u.updated_at, u.updated_by"""


# ── SYS-01 사용자 ───────────────────────────────────────────────────────
def all_roles() -> list[dict]:
    return conn.q("select role_code, role_name, use_yn from sys_role order by sort_no, role_code")


def user_of_path(login_id: str) -> dict:
    row = conn.q1(f"select {USER_COLUMNS} from sys_user u join sys_role r on r.role_code = u.role_code where u.login_id = %s",
                  (login_id,))
    if row is None:
        raise http.not_found()
    return row


def role_of(form: FormData, *, required: bool) -> str | None:
    role_code = text_of(form, "role_code", "역할", required=required, max_len=50)
    if role_code is not None and conn.q1("select 1 as hit from sys_role where role_code = %s", (role_code,)) is None:
        raise bad("입력값을 확인해 주세요", "역할", f"없는 역할입니다: {role_code}")
    return role_code


def password_of(form: FormData, label: str, *, required: bool) -> str | None:
    """비밀번호는 앞뒤 공백도 값이다 — 다듬지 않는다. 복잡도 규칙은 정해진 것이 없다(D-20)."""
    raw = form.get("password")
    value = raw if isinstance(raw, str) else ""
    if "\x00" in value or len(value) > 200:
        raise bad("입력값을 확인해 주세요", label, "쓸 수 없는 값입니다")
    if not value:
        if required:
            raise bad("필수값이 빠졌습니다", label, "필수값입니다")
        return None
    return value


@router.get(USERS, response_class=HTMLResponse)                      # F-SYS-04 사용자 조회 = 화면 GET
def users(request: Request, login_id: str = "", name: str = "", role_code: str = "", status: str = "", edit: str = "",
          user: rbac.User = rbac.require_fn("F-SYS-04")) -> HTMLResponse:
    where, params = ["true"], []
    if login_id.strip():
        where.append(contains("u.login_id"))
        params.append(login_id.strip())
    if name.strip():
        where.append(contains("u.user_name"))
        params.append(name.strip())
    if role_code.strip():
        where.append("u.role_code = %s")
        params.append(role_code.strip())
    if status in USER_STATUSES:
        where.append("u.status = %s")
        params.append(status)
    rows = conn.q(f"""select {USER_COLUMNS} from sys_user u join sys_role r on r.role_code = u.role_code
                       where {' and '.join(where)} order by u.login_id limit {USER_LIMIT}""", params)
    return templating.render(request, "sys/users.html", {
        "rows": rows, "roles": all_roles(), "statuses": USER_STATUSES,
        "f": {"login_id": login_id, "name": name, "role_code": role_code, "status": status},
        "editing": user_of_path(edit) if edit else None,
        "can": {"create": user.can("F-SYS-01"), "update": user.can("F-SYS-02"), "delete": user.can("F-SYS-03")},
        "ST_STOPPED": ST_STOPPED,
    }, screen_id="SYS-01")


@router.post(USERS)                                                   # F-SYS-01 사용자 등록
def create_user(request: Request, user: rbac.User = rbac.require_fn("F-SYS-01"), form: FormData = Depends(form_data)):
    login_id = text_of(form, "login_id", "로그인 ID", required=True, max_len=50)
    if not LOGIN_ID_RE.fullmatch(login_id):
        raise bad("입력값을 확인해 주세요", "로그인 ID", "영문·숫자·`_` `.` `-` 로 2~50자 (첫 글자는 영문·숫자)")
    user_name = text_of(form, "user_name", "이름", required=True, max_len=100)
    role_code = role_of(form, required=True)
    password = password_of(form, "초기 비밀번호", required=True)
    if conn.q1("select 1 as hit from sys_user where login_id = %s", (login_id,)):
        raise bad("이미 있는 로그인 ID 입니다", "로그인 ID", login_id)
    conn.x("""insert into sys_user (login_id, user_name, password_hash, role_code, created_by)
              values (%s, %s, %s, %s, %s)""",
           (login_id, user_name, auth.hash_password(password), role_code, user.login_id))   # 해시만 저장한다
    audit.log_change(request, user, "F-SYS-01", f"sys_user:{login_id}", f"사용자 등록 (역할 {role_code})")
    return http.saved(request, f"사용자 {login_id} 을(를) 등록했습니다", back=USERS,
                      data={"login_id": login_id, "role_code": role_code, "status": ST_ACTIVE})


@router.post(USERS + "/{login_id}")                                   # F-SYS-02 사용자 수정
def update_user(request: Request, login_id: str, user: rbac.User = rbac.require_fn("F-SYS-02"),
                form: FormData = Depends(form_data)):
    target = user_of_path(login_id)
    sets: dict[str, Any] = {}
    if "user_name" in form:
        sets["user_name"] = text_of(form, "user_name", "이름", required=True, max_len=100)
    if "role_code" in form:
        sets["role_code"] = role_of(form, required=True)
    if "status" in form:
        status = text_of(form, "status", "상태", required=True)
        if status not in USER_STATUSES:
            raise bad("입력값을 확인해 주세요", "상태", f"{' · '.join(USER_STATUSES)} 중 하나여야 합니다: {status}")
        if status != ST_ACTIVE and target["login_id"] == user.login_id:
            raise bad("자기 자신의 계정은 잠그거나 중지할 수 없습니다", "상태", status)
        sets["status"] = status
    sets = {k: v for k, v in sets.items() if v != target[k]}
    password = password_of(form, "새 비밀번호", required=False)       # 비밀번호 초기화 — 비워 두면 그대로
    changed = list(sets)
    if password is not None:
        sets["password_hash"] = auth.hash_password(password)
        sets["fail_count"] = 0
        changed.append("비밀번호 초기화")
    if sets.get("status") == ST_ACTIVE:
        sets["fail_count"] = 0
    if not sets:
        raise http.validation_error("바꿀 값이 없습니다")
    assign = ", ".join(f"{c} = %s" for c in sets)
    conn.x(f"update sys_user set {assign}, updated_at = now(), updated_by = %s where login_id = %s",
           [*sets.values(), user.login_id, login_id])
    audit.log_change(request, user, "F-SYS-02", f"sys_user:{login_id}", f"사용자 수정 ({' · '.join(changed)})")
    return http.saved(request, f"사용자 {login_id} 을(를) 수정했습니다", back=USERS,
                      data={"login_id": login_id, "status": sets.get("status", target["status"]),
                            "role_code": sets.get("role_code", target["role_code"])})


@router.post(USERS + "/{login_id}/delete")                            # F-SYS-03 사용자 삭제 = 상태 `중지`
def delete_user(request: Request, login_id: str, user: rbac.User = rbac.require_fn("F-SYS-03")):
    target = user_of_path(login_id)
    if target["login_id"] == user.login_id:
        raise bad("자기 자신의 계정은 삭제할 수 없습니다", "로그인 ID", login_id)
    if target["status"] == ST_STOPPED:
        raise bad("이미 중지된 계정입니다", "상태", ST_STOPPED)
    conn.x("update sys_user set status = %s, updated_at = now(), updated_by = %s where login_id = %s",
           (ST_STOPPED, user.login_id, login_id))                     # 행은 지우지 않는다 — 로그가 이 계정을 가리킨다 (D-21)
    audit.log_change(request, user, "F-SYS-03", f"sys_user:{login_id}", "사용자 삭제 (상태 중지)")
    return http.saved(request, f"사용자 {login_id} 을(를) 중지했습니다", back=USERS,
                      data={"login_id": login_id, "status": ST_STOPPED})


# ── SYS-02 권한 ─────────────────────────────────────────────────────────
def known_scopes() -> list[str]:
    """쓰기 기능이 갖는 범위 이름 — 계약 표에서 읽는다(`일반` 이 먼저)."""
    scopes = {f.scope for f in contracts.functions() if f.is_write}
    return sorted(scopes, key=lambda s: (s != rbac.SCOPE_GENERAL, s))


def scoped_functions() -> dict[str, list[str]]:
    """대메뉴 코드 → 그 대메뉴에 있는 쓰기 범위들 (권한 표 편집 화면의 선택지)."""
    out: dict[str, list[str]] = {}
    for f in contracts.functions():
        if f.is_write and f.scope not in out.setdefault(f.menu_code, []):
            out[f.menu_code].append(f.scope)
    return out


@router.get(PERMISSIONS, response_class=HTMLResponse)                # F-SYS-05 권한 조회 = 화면 GET
def permissions(request: Request, user: rbac.User = rbac.require_fn("F-SYS-05")) -> HTMLResponse:
    rbac.invalidate()                                                 # 화면은 캐시가 아니라 DB 의 지금 값을 보여 준다
    roles = rbac.roles()
    stamps = {(r["role_code"], r["menu_code"]): r for r in conn.q(
        "select role_code, menu_code, write_scope, updated_at, updated_by from sys_permission")}
    return templating.render(request, "sys/permissions.html", {
        "roles": roles, "matrix": rbac.matrix(), "counts": rbac.counts(), "stamps": stamps,
        "levels": rbac.LEVELS, "scopes": known_scopes(), "menu_scopes": scoped_functions(),
        "can_write": user.can("F-SYS-06"), "LEVEL_WRITE": rbac.LEVEL_WRITE, "SCOPE_GENERAL": rbac.SCOPE_GENERAL,
        "guarded": (GUARDED_ROLE, SYS_MENU),
    }, screen_id="SYS-02")


@router.post(PERMISSIONS)                                             # F-SYS-06 권한 수정 — 한 칸
def update_permission(request: Request, user: rbac.User = rbac.require_fn("F-SYS-06"),
                      form: FormData = Depends(form_data)):
    role_code = role_of(form, required=True)
    menu_code = text_of(form, "menu_code", "대메뉴", required=True, max_len=20)
    if menu_code not in {m.code for m in nav.MENUS}:
        raise bad("입력값을 확인해 주세요", "대메뉴", f"없는 대메뉴 코드입니다: {menu_code}")
    level = text_of(form, "level", "권한", required=True)
    if level not in rbac.LEVELS:
        raise bad("입력값을 확인해 주세요", "권한", f"{' · '.join(rbac.LEVELS)} 중 하나여야 합니다: {level}")
    scopes: list[str] = []
    if level == rbac.LEVEL_WRITE:
        raw = [s.strip() for v in form.getlist("write_scope") if isinstance(v, str) for s in v.split(",") if s.strip()]
        scopes = list(dict.fromkeys(raw)) or [rbac.SCOPE_GENERAL]    # 범위를 안 주면 괄호 없는 `입력` = 일반
        unknown = [s for s in scopes if s not in known_scopes()]
        if unknown:
            raise bad("입력값을 확인해 주세요", "입력 범위", f"없는 범위입니다: {', '.join(unknown)}")
    write_scope = ",".join(scopes)                                    # 입력이 아니면 빈 글자 (sys_permission_scope_chk)

    # 잠김 방지 — 이 칸을 내리면 권한 표를 고칠 수 있는 사람이 없어지는 경우를 막는다
    if menu_code == SYS_MENU and not (level == rbac.LEVEL_WRITE and rbac.SCOPE_GENERAL in scopes):
        rbac.invalidate()
        others = [r.code for r in rbac.roles()
                  if r.code != role_code and rbac.cell(r.code, SYS_MENU).can_write(rbac.SCOPE_GENERAL)]
        if role_code == GUARDED_ROLE or role_code == user.role_code or not others:
            raise bad("이 칸은 `입력` 아래로 내릴 수 없습니다 (잠김 방지)", "시스템 관리", f"{role_code} → {level}")

    before = conn.q1("select level, write_scope from sys_permission where role_code = %s and menu_code = %s",
                     (role_code, menu_code))
    conn.x("""insert into sys_permission (role_code, menu_code, level, write_scope, updated_at, updated_by)
              values (%s, %s, %s, %s, now(), %s)
              on conflict (role_code, menu_code) do update
                 set level = excluded.level, write_scope = excluded.write_scope,
                     updated_at = now(), updated_by = excluded.updated_by""",
           (role_code, menu_code, level, write_scope, user.login_id))
    rbac.invalidate()                                                 # 즉시 반영 — 다음 요청부터 DB 를 다시 읽는다
    was = f"{before['level']}{'(' + before['write_scope'] + ')' if before['write_scope'] else ''}" if before else rbac.LEVEL_NONE
    now = f"{level}{'(' + write_scope + ')' if write_scope else ''}"
    audit.log_change(request, user, "F-SYS-06", f"sys_permission:{role_code}/{menu_code}", f"권한 수정 {was} → {now}")
    return http.saved(request, f"권한을 바꿨습니다 — {role_code} × {menu_code}: {now}", back=PERMISSIONS,
                      data={"role_code": role_code, "menu_code": menu_code, "level": level, "write_scope": write_scope})


# ── SYS-03 로그 ─────────────────────────────────────────────────────────
def _date(value: str, label: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad("입력값을 확인해 주세요", label, f"날짜(YYYY-MM-DD)가 아닙니다: {value}") from None


@router.get(LOGS, response_class=HTMLResponse)                       # F-SYS-07 로그 조회 = 화면 GET
def logs(request: Request, date_from: str = "", date_to: str = "", login_id: str = "", log_type: str = "",
         result: str = "", user: rbac.User = rbac.require_fn("F-SYS-07")) -> HTMLResponse:
    where, params = ["true"], []
    d_from, d_to = _date(date_from, "시작일"), _date(date_to, "종료일")
    if d_from:
        where.append("l.logged_at >= %s::date")
        params.append(d_from)
    if d_to:
        where.append("l.logged_at < %s::date + 1")                    # 종료일을 포함한다
        params.append(d_to)
    if login_id.strip():
        where.append(contains("coalesce(l.login_id, '')"))
        params.append(login_id.strip())
    if log_type in LOG_TYPES:
        where.append("l.log_type = %s")
        params.append(log_type)
    if result in ("성공", "실패"):
        where.append("l.result = %s")
        params.append(result)
    cond = " and ".join(where)
    rows = conn.q(f"""select l.log_id, l.logged_at, l.log_type, l.login_id, l.role_code, l.method, l.path, l.screen_id,
                             l.function_id, l.target, l.result, l.detail, l.client_ip
                        from sys_access_log l where {cond}
                       order by l.logged_at desc, l.log_id desc limit {LOG_LIMIT}""", params)
    by_type = {r["log_type"]: r["n"] for r in conn.q(
        f"select l.log_type, count(*) as n from sys_access_log l where {cond} group by l.log_type", params)}
    return templating.render(request, "sys/logs.html", {
        "rows": rows, "by_type": by_type, "total": sum(by_type.values()), "limit": LOG_LIMIT, "log_types": LOG_TYPES,
        "f": {"date_from": date_from, "date_to": date_to, "login_id": login_id, "log_type": log_type, "result": result},
    }, screen_id="SYS-03")
