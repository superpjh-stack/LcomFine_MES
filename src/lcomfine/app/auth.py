"""로그인·세션 — 설계도 §4 "공통: 로그인 · 역할별 권한, 접근 로그".

- 비밀번호는 PBKDF2-HMAC-SHA256 해시만 저장한다. 평문·기본 비밀번호는 코드 어디에도 없다 (G-19).
- 로그인 성공·실패는 `sys_access_log`(구분 `로그인`)에 남는다 (G-18).
- 실패 횟수는 세지만 잠그지 않는다 — 잠금 횟수는 설계도에 없다(D-20). 상태가 `정상` 인 계정만 로그인한다.
- 자동 로그아웃은 `LCOMFINE_SESSION_IDLE_MINUTES` 가 있을 때만 한다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..db import conn
from . import nav, rbac
from .rbac import User
from .settings import get_settings
from .util import audit

PBKDF2_ITERATIONS = 260_000
PBKDF2_ALGO = "pbkdf2_sha256"
STATUS_ACTIVE = "정상"
DEVICE_SESSION_KEY = "device"


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


def authenticate(login_id: str, password: str, *, client_ip: str | None = None) -> LoginResult:
    """ID/비밀번호 인증. 결과를 접근 로그에 남기고 실패 횟수를 갱신한다."""
    login_id = (login_id or "").strip()
    u = conn.q1(
        """select u.login_id, u.user_name, u.password_hash, u.role_code, u.status, u.fail_count, r.role_name
             from sys_user u join sys_role r on r.role_code = u.role_code
            where u.login_id = %s""",
        (login_id,),
    )
    if u is None:
        _log(login_id[:50] or None, None, False, client_ip, "로그인 실패: 미등록 ID")
        return LoginResult(False, reason=BAD_CREDENTIALS)
    if u["status"] != STATUS_ACTIVE:
        _log(u["login_id"], u["role_code"], False, client_ip, f"로그인 실패: {u['status']} 계정")
        return LoginResult(False, reason=f"{u['status']} 상태 계정은 로그인할 수 없습니다")
    if not verify_password(password or "", u["password_hash"]):
        fails = int(u["fail_count"] or 0) + 1
        conn.x("update sys_user set fail_count = %s where login_id = %s", (fails, u["login_id"]))
        _log(u["login_id"], u["role_code"], False, client_ip, f"로그인 실패: 비밀번호 불일치 ({fails}회)")
        return LoginResult(False, reason=BAD_CREDENTIALS)
    conn.x("update sys_user set fail_count = 0, last_login_at = now() where login_id = %s", (u["login_id"],))
    _log(u["login_id"], u["role_code"], True, client_ip, "로그인 성공")
    return LoginResult(True, user=User(login_id=u["login_id"], user_name=u["user_name"], role_code=u["role_code"],
                                       role_name=u["role_name"]))


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
    request.session["user"] = user.to_session()
    request.session["login_at"] = datetime.now().isoformat(timespec="seconds")
    request.session["last_seen"] = request.session["login_at"]
    request.session[DEVICE_SESSION_KEY] = device if device in nav.DEVICE_CHANNEL else "web"


def logout_session(request) -> None:
    user = rbac.current_user(request)
    if user is not None:
        audit.write_log(log_type=audit.LOGIN, login_id=user.login_id, role_code=user.role_code, method=request.method,
                        path="/logout", screen_id="login", ok=True, detail="로그아웃", ip=audit.client_ip(request))
    request.session.clear()


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
