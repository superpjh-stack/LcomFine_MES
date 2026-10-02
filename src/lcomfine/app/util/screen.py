"""화면 공용 헬퍼 — 아키텍트 소유. 개발 1·2·3 모두 import 한다 (`contracts/interfaces.md` §8).

값이 없으면 지어내지 않는다. 빈 목록은 `미수집`, 사람이 아직 정하지 않은 값은 `미확정 (D-nn)` 이다 (G-11).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

NOT_COLLECTED = "미수집"     # 데이터가 아직 없다
UNDECIDED = "미확정"         # 사람이 아직 정하지 않았다
EMPTY = "-"
EXAMPLE = "(예시)"           # 시드 값에 붙이는 표기 — 실데이터가 아님을 밝힌다


def txt(v: Any, blank: str = EMPTY) -> str:
    return blank if v is None or v == "" else str(v)


def num(v: Any, digits: int = 0, blank: str = EMPTY) -> str:
    if v is None or v == "":
        return blank
    return f"{Decimal(str(v)):,.{digits}f}"


def dt(v: Any, fmt: str = "%Y-%m-%d %H:%M", blank: str = EMPTY) -> str:
    if v is None:
        return blank
    if isinstance(v, datetime):
        return v.strftime(fmt)
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v)


def undecided(decision: str) -> str:
    """사람이 정하지 않은 칸. 예) `미확정 (D-05)`"""
    return f"{UNDECIDED} ({decision})"


def example(value: str) -> str:
    """시드 값에 `(예시)` 를 붙인다. 이미 붙어 있으면 그대로."""
    return value if EXAMPLE in value else f"{value} {EXAMPLE}"
