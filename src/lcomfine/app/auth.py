"""로그인·세션 — 설계도 §4 "공통: 로그인 · 역할별 권한, 접근 로그".

- 비밀번호는 PBKDF2-HMAC-SHA256 해시만 저장한다. 평문·기본 비밀번호는 코드 어디에도 없다 (G-19).
- 로그인 성공·실패는 `sys_access_log`(구분 `로그인`)에 남는다 (G-18).
- 실패 횟수는 세지만 잠그지 않는다 — 잠금 횟수는 설계도에 없다(D-20). 상태가 `정상` 인 계정만 로그인한다.
- 자동 로그아웃은 `LCOMFINE_SESSION_IDLE_MINUTES` 가 있을 때만 한다.
- 세션 무효화(D-26): 세션 쿠키는 **누구의 어느 세션인가**(`login_id` · `sid` · `ep`)만 들고, 그 세션이 지금도 유효한지는
  요청마다 `rbac.current_user` 가 DB 에서 확인한다. 로그아웃은 그 세션 ID 를 `sys_user.revoked_sessions` 에 적어
  로그아웃 전의 쿠키를 다시 써도 통하지 않게 한다. 상태·비밀번호가 바뀌면 DB 트리거가 `session_epoch` 를 올려 그 계정의 세션을 전부 끊는다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..db import conn
from . import nav, rbac
from .rbac import User
from .settings import get_settings
from .util import audit, http

PBKDF2_ITERATIONS = 260_000
PBKDF2_ALGO = "pbkdf2_sha256"
STATUS_ACTIVE = "정상"
DEVICE_SESSION_KEY = "device"
#: 세션 쿠키의 수명(초) = `SessionMiddleware(max_age=…)`. 응답마다 다시 서명되므로 쓰는 동안은 이어진다.
#: 로그아웃한 세션 ID 는 이 시간이 지나면 쿠키 서명도 만료라 더 들고 있을 필요가 없다 (Starlette 기본 14일 — 자동 로그아웃은 D-20)
SESSION_MAX_AGE_SECONDS = 14 * 24 * 60 * 60


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "$".join([PBKDF2_ALGO, str(PBKDF2_ITERATIONS), base64.b64encode(salt).decode(), base64.b64encode(dk).decode()])


def verify_password(password: str, stored: str) -> bool:
    parts = (stored or "").split("$")
    if len(parts) != 4 or parts[0] != PBKDF2_ALGO:
        return False
    try:
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2])
        expected = base64.b64decode(parts[3])
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    user: User | None = None
    reason: str = ""


BAD_CREDENTIALS = "아이디 또는 비밀번호가 올바르지 않습니다"


def _log(login_id: str | None, role_code: str | None, ok: bool, ip: str | None, detail: str) -> None:
    audit.write_log(log_type=audit.LOGIN, login_id=login_id, role_code=role_code, method="POST", path="/login",
                    screen_id="login", ok=ok, detail=detail, ip=ip)


def authenticate(login_id: str, password: str, *, client_ip: str | None = None, via: str = "") -> LoginResult:
    """ID/비밀번호 인증. 결과를 접근 로그에 남기고 실패 횟수를 갱신한다.

    `via` 는 로그에 덧붙이는 경로 표시(예 `퀵 로그인`) — 판정은 같다. 비밀번호 값은 어떤 경우에도 로그에 쓰지 않는다."""
    login_id = (login_id or "").strip()
    tail = f" · {via}" if via else ""
    u = conn.q1(
        """select u.login_id, u.user_name, u.password_hash, u.role_code, u.status, u.fail_count, r.role_name
             from sys_user u join sys_role r on r.role_code = u.role_code
            where u.login_id = %s""",
        (login_id,),
    )
    if u is None:
        _log(login_id[:50] or None, None, False, client_ip, f"로그인 실패: 미등록 ID{tail}")
        return LoginResult(False, reason=BAD_CREDENTIALS)
    if u["status"] != STATUS_ACTIVE:
        _log(u["login_id"], u["role_code"], False, client_ip, f"로그인 실패: {u['status']} 계정{tail}")
        return LoginResult(False, reason=f"{u['status']} 상태 계정은 로그인할 수 없습니다")
    if not verify_password(password or "", u["password_hash"]):
        fails = int(u["fail_count"] or 0) + 1
        conn.x("update sys_user set fail_count = %s where login_id = %s", (fails, u["login_id"]))
        _log(u["login_id"], u["role_code"], False, client_ip, f"로그인 실패: 비밀번호 불일치 ({fails}회){tail}")
        return LoginResult(False, reason=BAD_CREDENTIALS)
    conn.x("update sys_user set fail_count = 0, last_login_at = now() where login_id = %s", (u["login_id"],))
    _log(u["login_id"], u["role_code"], True, client_ip, f"로그인 성공{tail}")
    return LoginResult(True, user=User(login_id=u["login_id"], user_name=u["user_name"], role_code=u["role_code"],
                                       role_name=u["role_name"]))


# ── 퀵 로그인 (D-416) ───────────────────────────────────────────────────
QUICK_VIA = "퀵 로그인"
QUICK_OFF = "퀵 로그인은 이 환경에서 쓸 수 없습니다"


def quick_login_enabled() -> bool:
    """`LCOMFINE_QUICK_LOGIN` 이 켜져 있고 · 시드 비밀번호가 있고 · 운영(`prod`)이 아닐 때만. 운영에서는 켜도 꺼진다."""
    s = get_settings()
    return bool(s.quick_login and s.seed_password and s.env != "prod")


def quick_login_accounts() -> list[dict]:
    """로그인 화면의 퀵 로그인 패널 — 역할(표시 순서)별로 계정을 묶는다. 값은 전부 DB 그대로(계정·역할·상태·권한 칸).

    역할마다: `role` · `summary`(대메뉴 12 중 입력·조회·없음 칸 수) · `primary`(시드 계정 — `created_by = 'seed'`,
    없으면 가장 먼저 만든 정상 계정) · `others`(나머지 — 잠금·중지도 상태와 함께 보인다, 단추는 막힌다)."""
    rows = conn.q(
        """select u.login_id, u.user_name, u.role_code, u.status, u.created_by, u.last_login_at
             from sys_user u join sys_role r on r.role_code = u.role_code
            where r.use_yn = 'Y'
            order by r.sort_no, r.role_code, (u.created_by = 'seed') desc, u.user_id""")
    out: list[dict] = []
    for role in rbac.roles():
        mine = [dict(r) for r in rows if r["role_code"] == role.code]
        if not mine:
            continue
        levels = [rbac.cell(role.code, m.code).level for m in nav.MENUS]
        summary = {lv: levels.count(lv) for lv in (rbac.LEVEL_WRITE, rbac.LEVEL_READ, rbac.LEVEL_NONE)}
        menus_read = [m.name for m in nav.MENUS if rbac.cell(role.code, m.code).can_read]
        primary = next((a for a in mine if a["created_by"] == "seed"), None)             or next((a for a in mine if a["status"] == STATUS_ACTIVE), mine[0])
        others = [a for a in mine if a is not primary]
        out.append({"role": role, "summary": summary, "menus": menus_read, "primary": primary, "others": others,
                    "active": sum(1 for a in mine if a["status"] == STATUS_ACTIVE), "total": len(mine)})
    return out


# ── 채널 (D-19) ─────────────────────────────────────────────────────────
def device_of(request) -> str:
    """이 요청의 채널 코드 — `?device=` > 로그인 때 고정한 세션 값 > `web`."""
    q = request.query_params.get("device")
    if q in nav.DEVICE_CHANNEL:
        return q
    s = request.session.get(DEVICE_SESSION_KEY) if hasattr(request, "session") else None
    return s if s in nav.DEVICE_CHANNEL else "web"


def home_path_for(request, user: User) -> str:
    """로그인 직후 갈 곳. 현장 POP·현황판·모바일로 연 세션은 그 채널의 첫 화면(조회 가능한 것), 아니면 메인."""
    device = request.session.get(DEVICE_SESSION_KEY)
    if device in nav.DEVICE_CHANNEL and device != "web":
        channel = nav.DEVICE_CHANNEL[device]
        for sc in nav.SCREENS:
            if sc.channels[0] == channel and user.can_open(sc.screen_id):
                return sc.path
    return "/"


# ── 세션 ────────────────────────────────────────────────────────────────
def login_session(request, user: User, device: str | None = None) -> None:
    """로그인한 세션을 연다. 쿠키에는 사용자와 **세션 ID · 그때의 세션 판 번호**를 넣는다 — 유효 판정은 `rbac.current_user` 가 DB 로 한다."""
    row = conn.q1("select session_epoch from sys_user where login_id = %s", (user.login_id,))
    if row is None:   # 인증과 세션 열기 사이에 계정이 지워졌다
        raise http.unauthorized()
    request.session["user"] = user.to_session()
    request.session[rbac.SESSION_ID_KEY] = secrets.token_urlsafe(16)
    request.session[rbac.SESSION_EPOCH_KEY] = int(row["session_epoch"])
    rbac.forget_user(request)
    request.session["login_at"] = datetime.now().isoformat(timespec="seconds")
    request.session["last_seen"] = request.session["login_at"]
    request.session[DEVICE_SESSION_KEY] = device if device in nav.DEVICE_CHANNEL else "web"


def revoke_session(login_id: str, session_id: str) -> None:
    """그 세션 ID 를 서버 쪽에서 무효로 만든다 — 로그아웃 전의 쿠키를 다시 써도 통하지 않는다.
    쿠키 수명이 지난 옛 기록은 같이 지운다(서명이 만료라 어차피 통하지 않는다)."""
    now = int(time.time())
    conn.x(
        """update sys_user
              set revoked_sessions = (select coalesce(jsonb_object_agg(e.key, e.value), '{}'::jsonb)
                                        from jsonb_each(revoked_sessions) e
                                       where (e.value #>> '{}')::bigint > %s) || jsonb_build_object(%s::text, %s::bigint)
            where login_id = %s""",
        (now - SESSION_MAX_AGE_SECONDS, session_id, now, login_id))


def logout_session(request) -> None:
    """로그아웃 — 접근 로그를 남기고, 그 세션을 서버에서 무효로 만든 뒤 쿠키를 비운다."""
    user = rbac.current_user(request)
    session_id = request.session.get(rbac.SESSION_ID_KEY)
    if user is not None:
        audit.write_log(log_type=audit.LOGIN, login_id=user.login_id, role_code=user.role_code, method=request.method,
                        path="/logout", screen_id="login", ok=True, detail="로그아웃", ip=audit.client_ip(request))
        if session_id:
            revoke_session(user.login_id, str(session_id))
    request.session.clear()
    rbac.forget_user(request)


def session_expired(request) -> bool:
    """자동 로그아웃 판정. 시간이 설정되지 않았으면 만료시키지 않는다 — 값을 지어내지 않는다 (D-20)."""
    minutes = get_settings().session_idle_minutes
    if minutes is None:
        return False
    last = request.session.get("last_seen")
    if not last:
        return False
    try:
        seen = datetime.fromisoformat(last)
    except ValueError:
        return False
    return datetime.now() - seen > timedelta(minutes=minutes)


def touch_session(request) -> None:
    if request.session.get("user"):
        request.session["last_seen"] = datetime.now().isoformat(timespec="seconds")
