"""DB와 업무 라우터에 의존하지 않는 공용 입력 검증.

근거: contracts/api-contract.md §1·§3. 입력 오류는 422, 잘못된 경로 키는 404.
기존 BAS 계열(qty/day/pk 등)과 INV 계열(num_in/date_in/path_id 등)의
필수값 기본 설정·수량 상한·ID 허용 범위·오류 문구가 다르므로 각각 보존한다.
두 계열의 정책 통합은 업무 동작 변경이므로 이 모듈 추출에 포함하지 않는다.
DB 조회와 잠금이 필요한 선택값 검증은 업무 모듈에서 처리한다.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import Request

from . import http

BIGINT_MAX = 9_223_372_036_854_775_807
BAS_QTY_MAX = Decimal("99999999999.999")
INV_QTY_MAX = Decimal("99999999999")
NUL_REASON = "글자에 NUL(0x00)을 넣을 수 없습니다"


def s(v: str | None, label: str) -> str | None:
    """앞뒤 공백을 걷어 낸 글자. 비면 None. NUL(0x00) 이 들어 있으면 422 — 어느 항목인지 `label` 로 짚는다
    (api-contract §3: DataError 핸들러의 「입력」 한 줄은 마지막 방어선 · DEF-QA3-002)."""
    if v is None:
        return None
    if "\x00" in v:
        raise bad(label, NUL_REASON)
    v = v.strip()
    return v or None


def bad(label: str, reason: str, message: str | None = None):
    return http.validation_error(message or f"{label}: {reason}", fields=[{"name": label, "reason": reason}])


def need(v: str | None, label: str) -> str:
    """필수 글자 — 비면 422 「<label>: 필수 항목입니다」 · NUL 은 s() 가 422."""
    out = s(v, label)
    if out is None:
        raise bad(label, "필수 항목입니다", f"필수 항목을 입력해 주세요 — {label}")
    return out


def pk(v: str | int | None) -> int:
    """경로의 키 — 숫자가 아니거나 bigint 를 넘으면 그런 대상이 없다(404)."""
    t = str(v or "").strip()
    if not t.isdigit() or int(t) > BIGINT_MAX or int(t) == 0:
        raise http.not_found()
    return int(t)


def ref_id(v: str | None, label: str, *, required: bool = True) -> int | None:
    """폼으로 고른 행의 키 — 사용자가 입력한 값이므로 틀리면 422 (경로의 키와 다르다)."""
    t = s(v, label)
    if t is None:
        if required:
            raise bad(label, "필수 항목입니다", f"필수 항목을 입력해 주세요 — {label}")
        return None
    if not t.isdigit() or int(t) > BIGINT_MAX:
        raise bad(label, "목록에서 고른 값이 아닙니다")
    return int(t)


def qty(v: str | None, label: str, *, required: bool = True, positive: bool = True) -> Decimal | None:
    t = s(v, label)
    if t is None:
        if required:
            raise bad(label, "필수 항목입니다", f"필수 항목을 입력해 주세요 — {label}")
        return None
    try:
        d = Decimal(t.replace(",", ""))
    except InvalidOperation:
        raise bad(label, "숫자여야 합니다") from None
    if not d.is_finite():
        raise bad(label, "숫자여야 합니다")
    if positive and d <= 0:
        raise bad(label, "0 보다 커야 합니다")
    if abs(d) > BAS_QTY_MAX or d.as_tuple().exponent < -3:
        raise bad(label, "정수 11자리 · 소수 3자리까지 입력할 수 있습니다")
    return d


def integer(v: str | None, label: str, *, required: bool = False, minimum: int | None = None) -> int | None:
    t = s(v, label)
    if t is None:
        if required:
            raise bad(label, "필수 항목입니다", f"필수 항목을 입력해 주세요 — {label}")
        return None
    if not t.lstrip("-").isdigit() or abs(int(t)) > 2_147_483_647:
        raise bad(label, "정수여야 합니다")
    n = int(t)
    if minimum is not None and n < minimum:
        raise bad(label, f"{minimum} 이상이어야 합니다")
    return n


def day(v: str | None, label: str, *, required: bool = True) -> date | None:
    t = s(v, label)
    if t is None:
        if required:
            raise bad(label, "필수 항목입니다", f"필수 항목을 입력해 주세요 — {label}")
        return None
    try:
        return date.fromisoformat(t)
    except ValueError:
        raise bad(label, "날짜 형식(YYYY-MM-DD)이 아닙니다") from None


def yn(v: str | None, label: str = "사용 여부") -> str:
    t = s(v, label) or "Y"
    if t not in ("Y", "N"):
        raise bad(label, "Y 또는 N 이어야 합니다")
    return t


def choice(v: str | None, label: str, allowed: tuple[str, ...], *, required: bool = True) -> str | None:
    t = s(v, label)
    if t is None:
        if required:
            raise bad(label, "필수 항목입니다", f"필수 항목을 입력해 주세요 — {label}")
        return None
    if t not in allowed:
        raise bad(label, f"{' · '.join(allowed)} 중 하나여야 합니다")
    return t


def kv_text(v: str | None, label: str) -> dict[str, str]:
    """`항목=값` 한 줄에 하나 → dict. 양식을 받은 적이 없어 항목 이름을 정하지 않는다(사람이 적는 그대로)."""
    out: dict[str, str] = {}
    if v and "\x00" in v:
        raise bad(label, NUL_REASON)
    for n, raw in enumerate((v or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise bad(label, f"{n}번째 줄에 `=` 가 없습니다 — 한 줄에 `항목=값` 하나")
        k, val = (p.strip() for p in line.split("=", 1))
        if not k:
            raise bad(label, f"{n}번째 줄의 항목 이름이 비었습니다")
        if k in out:
            raise bad(label, f"항목 `{k}` 이(가) 두 번 나옵니다")
        out[k] = val
    return out


def kv_lines(d: dict | None) -> str:
    return "\n".join(f"{k}={v}" for k, v in (d or {}).items())


def like(v: str | None, label: str = "검색어") -> str | None:
    t = s(v, label)
    return None if t is None else "%" + t.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _bad(name: str, reason: str, message: str | None = None):
    return http.validation_error(message or f"{name}: {reason}", fields=[{"name": name, "reason": reason}])


def text_in(value: str | None, name: str, *, required: bool = False, max_len: int = 500) -> str | None:
    v = (value or "").strip()
    if "\x00" in v:
        raise _bad(name, "글자에 NUL(0x00)을 넣을 수 없습니다")
    if not v:
        if required:
            raise _bad(name, "필수 입력입니다", f"{name}을(를) 입력하세요")
        return None
    if len(v) > max_len:
        raise _bad(name, f"{max_len}자를 넘을 수 없습니다")
    return v


def num_in(value: str | None, name: str, *, required: bool = True, positive: bool = True,
           allow_zero: bool = False) -> Decimal | None:
    """수량 — numeric(14,3). positive: > 0 (allow_zero 면 >= 0)."""
    v = (value or "").strip().replace(",", "")
    if not v:
        if required:
            raise _bad(name, "필수 입력입니다", f"{name}을(를) 입력하세요")
        return None
    try:
        d = Decimal(v)
    except InvalidOperation:
        raise _bad(name, f"숫자가 아닙니다: {v[:30]}") from None
    if not d.is_finite():
        raise _bad(name, f"숫자가 아닙니다: {v[:30]}")
    if abs(d) > INV_QTY_MAX:
        raise _bad(name, "숫자가 저장할 수 있는 범위를 넘었습니다")
    if d.as_tuple().exponent < -3:
        raise _bad(name, "소수점 아래 세 자리까지 입력할 수 있습니다")
    if positive and (d < 0 or (d == 0 and not allow_zero)):
        raise _bad(name, "0 보다 커야 합니다" if not allow_zero else "0 이상이어야 합니다")
    return d


def int_in(value: str | None, name: str, *, required: bool = False) -> int | None:
    v = (value or "").strip()
    if not v:
        if required:
            raise _bad(name, "필수 입력입니다", f"{name}을(를) 입력하세요")
        return None
    if not re.fullmatch(r"\d{1,9}", v):
        raise _bad(name, f"0 이상의 정수가 아닙니다: {v[:30]}")
    return int(v)


def date_in(value: str | None, name: str, *, required: bool = False) -> date | None:
    v = (value or "").strip()
    if not v:
        if required:
            raise _bad(name, "필수 입력입니다", f"{name}을(를) 입력하세요")
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise _bad(name, f"날짜 형식(YYYY-MM-DD)이 아닙니다: {v[:30]}") from None


def id_in(value: str | None, name: str, *, required: bool = True) -> int | None:
    """폼으로 고른 ID — 숫자가 아니면 422 (사용자 입력)."""
    v = (value or "").strip()
    if not v:
        if required:
            raise _bad(name, "필수 선택입니다", f"{name}을(를) 고르세요")
        return None
    if not re.fullmatch(r"\d{1,18}", v):
        raise _bad(name, f"올바른 선택이 아닙니다: {v[:30]}")
    return int(v)


def path_id(value: str) -> int:
    """경로의 키 — 숫자가 아니면 「그런 대상이 없다」 404 (api-contract §1)."""
    if not re.fullmatch(r"\d{1,18}", value or ""):
        raise http.not_found()
    return int(value)


def qs(request: Request, key: str) -> str:
    """조회 조건 한 칸 (없으면 빈 글자)."""
    return (request.query_params.get(key) or "").strip()
