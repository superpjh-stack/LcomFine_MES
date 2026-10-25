"""전사 경영 Cockpit의 목표·경보 판정 서비스.

목표값의 0을 결측으로 취급하지 않으며 목표 버전은 수정하지 않고 항상 추가한다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def target_for(cur, metric_key: str, period_from, period_to, scope_kind: str = "company",
               scope_key: str | None = None) -> dict | None:
    cur.execute(
        """select t.*, v.version_no, v.target_value, v.range_min, v.range_max, v.change_reason
             from management_target t
             join lateral (select * from management_target_version
                            where target_id=t.id order by version_no desc limit 1) v on true
            where t.metric_key=%s and t.status='사용' and t.period_from <= %s and t.period_to >= %s
              and t.scope_kind=%s and t.scope_key is not distinct from %s
            order by t.period_from desc, t.id desc limit 1""",
        (metric_key, period_to, period_from, scope_kind, scope_key),
    )
    return cur.fetchone()


def create_target_version(cur, target_id: int, payload: dict[str, Any], user) -> int:
    cur.execute("select id from management_target where id=%s for update", (target_id,))
    if cur.fetchone() is None:
        raise LookupError(target_id)
    cur.execute("select coalesce(max(version_no),0)+1 n from management_target_version where target_id=%s",
                (target_id,))
    version = cur.fetchone()["n"]
    cur.execute(
        """insert into management_target_version
           (target_id,version_no,target_value,range_min,range_max,change_reason,created_by)
           values (%s,%s,%s,%s,%s,%s,%s) returning id""",
        (target_id, version, payload["target_value"], payload.get("range_min"), payload.get("range_max"),
         payload["change_reason"], user.login_id),
    )
    return cur.fetchone()["id"]


def thresholds(cur, metric_key: str, period_from, period_to, scope_kind: str = "company",
               scope_key: str | None = None) -> list[dict]:
    cur.execute(
        """select * from management_threshold
            where metric_key=%s and status='사용' and period_from <= %s and period_to >= %s
              and scope_kind=%s and scope_key is not distinct from %s
            order by case level when '위험' then 1 else 2 end, id""",
        (metric_key, period_to, period_from, scope_kind, scope_key),
    )
    return cur.fetchall()


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
