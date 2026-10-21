"""접근 로그 · 변경 로그 — `sys_access_log` · `sys_change_log` 에 쓰는 한 곳 (G-18).

    write_log(...)                                  로그인·조회·오류·SSO → `sys_access_log` — auth · templating · main · DOC-010 이 부른다
    log_change(request, user, function_id, target)  데이터 변경 → `sys_change_log` — **개발자는 쓰기 성공 직후 이것을 부른다**

로그 적재 실패를 삼키지 않는다(예외가 그대로 올라간다).
"""

from __future__ import annotations

from ...db import conn

LOGIN, VIEW, CHANGE, ERROR, SSO = "로그인", "조회", "변경", "오류", "SSO"   # sys_access_log.log_type


def client_ip(request) -> str | None:
    return request.client.host if getattr(request, "client", None) else None


def write_log(*, log_type: str, login_id: str | None, role_code: str | None = None, method: str | None = None,
              path: str | None = None, screen_id: str | None = None, function_id: str | None = None,
              target: str | None = None, ok: bool = True, detail: str = "", ip: str | None = None) -> None:
    conn.x(
        """insert into sys_access_log (log_type, login_id, role_code, method, path, screen_id, function_id, target,
                                       result, detail, client_ip)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (log_type, login_id, role_code, method, path, screen_id, function_id, target,
         "성공" if ok else "실패", (detail or "")[:1000], ip),
    )


def log_change(request, user, function_id: str, target: str, detail: str = "") -> None:
    """데이터 변경 로그(`sys_change_log`) — 누가·언제·무엇을.

        audit.log_change(request, user, "F-BAS-011", f"item:{item_code}", "품목 등록")

    `target` 은 `테이블:업무 번호` 로 적는다. 화면 ID 는 기능 ID 에서 찾는다(없는 기능 ID 는 KeyError).
    """
    from .. import contracts  # noqa — 순환 import 회피

    fn = contracts.function(function_id)
    conn.x(
        """insert into sys_change_log (login_id, role_code, function_id, screen_id, method, path, target, detail, client_ip)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (user.login_id, user.role_code, function_id, fn.screen_id, request.method, request.url.path, target,
         (detail or fn.name)[:1000], client_ip(request)),
    )
