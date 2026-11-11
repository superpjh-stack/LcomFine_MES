"""전사 경영 Cockpit의 목표·경보 판정 서비스.

목표값의 0을 결측으로 취급하지 않으며 목표 버전은 수정하지 않고 항상 추가한다.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any

from .management_rules import compare, _triggered


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


def evaluate(cur, metric_key: str, observed: Decimal | None, context: dict, asof) -> dict | None:
    """확정 임계치에 걸린 가장 높은 단계 하나를 반환한다. 규칙이나 값이 없으면 만들지 않는다."""
    if observed is None:
        return None
    rules = thresholds(cur, metric_key, asof, asof, context.get("scope_kind", "company"), context.get("scope_key"))
    rule = next((r for r in rules if _triggered(r, observed)), None)
    if rule is None:
        return None
    identity = {"metric": metric_key, "scope_kind": rule["scope_kind"], "scope_key": rule["scope_key"],
                "source_screen": context["source_screen"]}
    issue_key = "rule:" + hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    return {"issue_key": issue_key, "metric_key": metric_key, "severity": rule["level"],
            "title": context.get("title") or f"{metric_key} {rule['level']} 기준 이탈",
            "observed_value": observed, "evidence": {**context, "threshold_id": rule["id"], "asof": str(asof)},
            "source_screen": context["source_screen"], "source_query": context.get("source_query", ""),
            "owner_role": context.get("owner_role")}


def upsert_issue(cur, finding: dict, created_by: str) -> int:
    cur.execute("select id,status from management_issue where issue_key=%s for update", (finding["issue_key"],))
    old = cur.fetchone()
    evidence = json.dumps(finding["evidence"], ensure_ascii=False)
    if old:
        cur.execute("""update management_issue set severity=%s,title=%s,observed_value=%s,evidence=%s::jsonb,
                       source_query=%s,owner_role=%s,last_seen_at=now(),updated_at=now(),updated_by=%s,
                       status=case when status='해결' then '신규' else status end,resolved_at=null,close_reason=null where id=%s""",
                    (finding["severity"],finding["title"],finding["observed_value"],evidence,finding["source_query"],
                     finding.get("owner_role"),created_by,old["id"]))
        return old["id"]
    cur.execute("""insert into management_issue(issue_key,metric_key,severity,title,observed_value,evidence,source_screen,
                   source_query,owner_role,created_by) values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) returning id""",
                (finding["issue_key"],finding["metric_key"],finding["severity"],finding["title"],finding["observed_value"],
                 evidence,finding["source_screen"],finding["source_query"],finding.get("owner_role"),created_by))
    return cur.fetchone()["id"]


def assign_action(cur, issue_id: int, payload: dict, user) -> int:
    cur.execute("select id from management_issue where id=%s and status<>'해결' for update", (issue_id,))
    if cur.fetchone() is None:
        raise LookupError(issue_id)
    cur.execute("""insert into management_action(issue_id,owner_role,owner_user_id,due_date,action_text,created_by)
                   values (%s,%s,%s,%s,%s,%s) returning id""",
                (issue_id,payload["owner_role"],payload.get("owner_user_id"),payload["due_date"],payload["action_text"],user.login_id))
    return cur.fetchone()["id"]


def transition_action(cur, action_id: int, status: str, user) -> None:
    cur.execute("select * from management_action where id=%s for update", (action_id,))
    row = cur.fetchone()
    if row is None:
        raise LookupError(action_id)
    completed = status == "완료"
    cur.execute("""update management_action set status=%s,completed_at=case when %s then now() else null end,
                   completed_by=case when %s then %s else null end,updated_at=now(),updated_by=%s where id=%s""",
                (status,completed,completed,user.id,user.login_id,action_id))
