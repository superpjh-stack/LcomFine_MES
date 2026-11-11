"""경영 목표·경보의 순수 비교 계산. DB 조회·위험 저장은 management.py가 담당한다.

0은 실측값이며 None만 미수집이다. 방향별 판정·달성률과 경계 포함 여부를 보존한다.
"""
from __future__ import annotations

from decimal import Decimal


def compare(metric: dict, actual: Decimal | None, target: dict | None) -> dict:
    if actual is None:
        return {"actual": None, "status": "미수집", "attainment": None, "variance": None}
    if target is None:
        return {"actual": actual, "status": "목표 없음", "attainment": None, "variance": None}
    direction = metric["direction"]
    target_value = target.get("target_value")
    variance = None if target_value is None else actual - target_value
    attainment = None
    if direction == "높을수록 좋음":
        status = "정상" if actual >= target_value else "주의"
        if target_value != 0:
            attainment = actual / target_value * Decimal("100")
    elif direction == "낮을수록 좋음":
        status = "정상" if actual <= target_value else "주의"
    elif direction == "범위 내 정상":
        low, high = target.get("range_min"), target.get("range_max")
        status = "정상" if low is not None and high is not None and low <= actual <= high else "주의"
    else:
        raise ValueError(f"지원하지 않는 지표 방향: {direction}")
    return {"actual": actual, "status": status, "attainment": attainment, "variance": variance}


def _triggered(rule: dict, observed: Decimal) -> bool:
    op, low, high = rule["compare_op"], rule["value_min"], rule.get("value_max")
    return {"gt": observed > low, "gte": observed >= low, "lt": observed < low,
            "lte": observed <= low, "outside": high is not None and not low <= observed <= high}[op]

