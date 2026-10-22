"""문서관리 SSO 토큰 — 발급 · 검증의 한 곳 (D-514 · G-18). 담당 개발1 (W4).

    sso.issue(cur, user, *, now=None) -> (token, jti)     # 비활성 · 미매핑(사용 중지 매핑 포함) → sso.NotMapped(사유)
    sso.consume(cur, token, *, now=None) -> dict          # 서명 · 형식 · 만료 · 1회 사용 · 사용자 상태 → 어긋나면 sso.Invalid(사유)
    sso.NotMapped · sso.Invalid · sso.NotConfigured · sso.TTL_SECONDS(60) · sso.REQUEST_MAPPING("관리자에게 계정 연결을 요청하세요")

토큰 = `base64url(JSON 본문) + "." + base64url(HMAC-SHA256(LCOMFINE_SSO_SECRET, 본문 글자))`.
본문 = {"v": 1, "sub": 문서관리 계정 ID, "iat": 발급 epoch 초, "exp": 만료 epoch 초(iat + 60), "jti": uuid}.
`sso_token` 에 jti · 사용자 · 계정 ID · 발급 · 만료 · 사용 시각을 남긴다 — 토큰 글자 자체는 어디에도 저장하지 않는다.

- 사용자 상태 · 매핑은 **DB 에서 다시 읽는다**(rbac.current_user 와 같은 원칙) — 넘겨받은 User 객체의 status 를 믿지 않는다.
- 비밀(`LCOMFINE_SSO_SECRET`)이 비면 발급도 검증도 하지 않는다 → sso.NotConfigured (조용히 서명 없는 토큰을 만들지 않는다).
- 1회 사용: `update sso_token set used_at = … where jti = … and used_at is null and expires_at > … returning` —
  동시에 두 번 써도 한 쪽만 행을 받는다. 서명 비교는 `hmac.compare_digest`(상수 시간).
- 이미 발급된 미사용 토큰도 consume 이 사용자 상태 · 매핑을 다시 본다(그 사이 비활성 · 매핑 사용 중지 → 거부).
- `now` 는 테스트의 시각 주입용(UTC aware datetime). 비우면 지금.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

from .settings import get_settings

TTL_SECONDS = 60
VERSION = 1
ACTIVE_STATUS = "정상"
REQUEST_MAPPING = "관리자에게 계정 연결을 요청하세요"
MAX_TOKEN_CHARS = 2048


class NotMapped(Exception):
    """발급 거부 — 비활성 사용자 · 계정 매핑 없음 · 사용 중지 매핑. `reason` 은 로그 · 화면에 그대로 쓴다(토큰 글자 없음)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Invalid(Exception):
    """검증 거부 — 형식 · 서명 · 만료 · 재사용 · 모르는 jti · 사용자 비활성 · 매핑 변경."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NotConfigured(RuntimeError):
    """서명 비밀이 없다 — 발급 · 검증을 하지 않는다."""

    def __init__(self) -> None:
        super().__init__("SSO 서명 비밀이 설정되지 않았습니다 — LCOMFINE_SSO_SECRET")
        self.reason = str(self)


def configured() -> bool:
    return bool(get_settings().sso_secret)


def _secret() -> bytes:
    s = get_settings().sso_secret
    if not s:
        raise NotConfigured()
    return s.encode("utf-8")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _b64ok(s: str) -> bool:
    return bool(s) and all(c in _B64URL for c in s)


def _b64d(s: str) -> bytes:
    if not _b64ok(s):
        raise Invalid("토큰 형식이 아닙니다")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (ValueError, TypeError):
        raise Invalid("토큰 형식이 아닙니다") from None


def _sign(body: str) -> str:
    return _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())


def _now(now: datetime | None) -> datetime:
    n = now or datetime.now(UTC)
    if n.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 한다")
    return n


def _user_and_mapping(cur, user_id: int) -> tuple[dict | None, dict | None]:
    cur.execute("select user_id, login_id, status from sys_user where user_id = %s", (user_id,))
    u = cur.fetchone()
    cur.execute("select id, account_id, active from doc_account_map where user_id = %s", (user_id,))
    m = cur.fetchone()
    return u, m


def refusal(cur, user_id: int) -> tuple[str | None, dict | None]:
    """발급을 막는 사유(없으면 None)와 매핑 행 — DOC-010 화면 안내와 issue 가 같은 판정을 쓴다."""
    u, m = _user_and_mapping(cur, user_id)
    if u is None:
        return "없는 사용자입니다", None
    if u["status"] != ACTIVE_STATUS:
        return f"비활성 사용자입니다 (상태 {u['status']})", m
    if m is None:
        return "문서관리 계정 매핑이 없습니다", None
    if not m["active"]:
        return "문서관리 계정 매핑이 사용 중지되었습니다", m
    return None, m


def issue(cur, user, *, now: datetime | None = None) -> tuple[str, str]:
    """일회용 토큰 발급 — `cur` 는 쓰기 트랜잭션의 커서(sso_token 1행). 반환 (token, jti)."""
    key = _secret()                                   # 비밀이 없으면 DB 를 보기 전에 NotConfigured
    reason, m = refusal(cur, int(user.id))
    if reason:
        raise NotMapped(reason)
    n = _now(now).replace(microsecond=0)
    exp = n + timedelta(seconds=TTL_SECONDS)
    jti = str(uuid.uuid4())
    payload = {"v": VERSION, "sub": m["account_id"], "iat": int(n.timestamp()), "exp": int(exp.timestamp()), "jti": jti}
    body = _b64e(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
    cur.execute("""insert into sso_token (jti, user_id, account_id, issued_at, expires_at)
                   values (%s, %s, %s, %s, %s)""", (jti, int(user.id), m["account_id"], n, exp))
    return f"{body}.{sig}", jti


def consume(cur, token: str, *, now: datetime | None = None) -> dict:
    """토큰 검증 + 사용 처리(한 번만). 반환 {account_id, user_id, login_id, jti, issued_at, expires_at, used_at}.

    문서관리 시스템 쪽 검증을 MES 안에서 재현한 것이다(테스트 · 연계 상대 참고용). 어긋나면 sso.Invalid(사유).
    """
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise Invalid("토큰 형식이 아닙니다")
    body, sig = token.split(".")
    if not _b64ok(body) or not _b64ok(sig):
        raise Invalid("토큰 형식이 아닙니다")
    expected = _sign(body)
    if not hmac.compare_digest(expected.encode("ascii"), sig.encode("ascii")):
        raise Invalid("서명이 맞지 않습니다")
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Invalid("토큰 형식이 아닙니다") from None
    if (not isinstance(payload, dict) or payload.get("v") != VERSION
            or not isinstance(payload.get("sub"), str) or not isinstance(payload.get("jti"), str)
            or not isinstance(payload.get("iat"), int) or not isinstance(payload.get("exp"), int)
            or payload["exp"] - payload["iat"] != TTL_SECONDS):
        raise Invalid("토큰 형식이 아닙니다")
    try:
        jti = str(uuid.UUID(payload["jti"]))
    except ValueError:
        raise Invalid("토큰 형식이 아닙니다") from None
    n = _now(now)
    if n.timestamp() >= payload["exp"]:
        raise Invalid("만료된 토큰입니다")
    cur.execute("""update sso_token set used_at = %s
                    where jti = %s and used_at is null and expires_at > %s and account_id = %s
                returning jti::text as jti, user_id, account_id, issued_at, expires_at, used_at""",
                (n, jti, n, payload["sub"]))
    row = cur.fetchone()
    if row is None:
        cur.execute("select used_at, expires_at from sso_token where jti = %s", (jti,))
        prev = cur.fetchone()
        if prev is None:
            raise Invalid("발급 기록이 없는 토큰입니다")
        if prev["used_at"] is not None:
            raise Invalid("이미 사용한 토큰입니다")
        raise Invalid("만료된 토큰입니다")
    reason, m = refusal(cur, row["user_id"])
    if reason:
        raise Invalid(reason)
    if m["account_id"] != row["account_id"]:
        raise Invalid("발급 뒤 문서관리 계정 매핑이 바뀌었습니다")
    cur.execute("select login_id from sys_user where user_id = %s", (row["user_id"],))
    return {**row, "login_id": cur.fetchone()["login_id"]}
