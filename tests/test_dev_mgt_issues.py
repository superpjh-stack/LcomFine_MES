"""MGT-030 위험·조치 — 중복 위험 갱신, 담당 범위, 상태 이력."""
from datetime import date
from decimal import Decimal

import pytest

from lcomfine.app import management, rbac
from lcomfine.db import conn
from test_dev1_common import client, uniq


@pytest.fixture()
def issue():
    key = uniq("ISS")
    with conn.tx() as cur:
        cur.execute("""insert into management_issue(issue_key,metric_key,severity,title,observed_value,evidence,source_screen,owner_role,created_by)
                       values (%s,'orders.qty','위험','수주 목표 미달',50,'{"period":"2026-10"}','RPT-010','PR','test') returning id""", (key,))
        issue_id = cur.fetchone()["id"]
    yield {"id": issue_id, "key": key}
    with conn.tx() as cur:
        cur.execute("delete from management_action where issue_id=%s", (issue_id,))
        cur.execute("delete from management_issue where id=%s", (issue_id,))


@pytest.mark.fn("F-MGT-031")
@pytest.mark.fn("F-MGT-032")
@pytest.mark.fn("F-MGT-034")
def test_action_scope_and_transition(issue):
    assert client("pr").get("/mgt/issues").status_code == 200
    assert issue["key"] in client("pr").get("/mgt/issues").text
    assert issue["key"] not in client("sl").get("/mgt/issues").text
    assert issue["key"] in client("st").get("/mgt/issues").text

    denied = client("sl").post(f"/mgt/issues/{issue['id']}/actions", data={
        "owner_role": "PR", "due_date": "2026-11-10", "action_text": "생산계획 확인",
    })
    assert denied.status_code == 403
    made = client("pr").post(f"/mgt/issues/{issue['id']}/actions", data={
        "owner_role": "PR", "due_date": "2026-11-10", "action_text": "생산계획 확인",
    })
    assert made.status_code == 200, made.text
    action_id = made.json()["id"]
    assert client("sl").post(f"/mgt/issues/actions/{action_id}", data={"status": "진행"}).status_code == 403
    done = client("pr").post(f"/mgt/issues/actions/{action_id}", data={"status": "완료"})
    assert done.status_code == 200, done.text
    row = conn.q1("select status,completed_at,completed_by from management_action where id=%s", (action_id,))
    assert row["status"] == "완료" and row["completed_at"] is not None and row["completed_by"] is not None


@pytest.mark.fn("F-MGT-033")
def test_force_close_requires_reason(issue):
    assert client("pr").post(f"/mgt/issues/{issue['id']}/delete", data={}).status_code == 422
    closed = client("pr").post(f"/mgt/issues/{issue['id']}/delete", data={"close_reason": "원인 제거를 현장 확인함"})
    assert closed.status_code == 200, closed.text
    row = conn.q1("select status,resolved_at,close_reason from management_issue where id=%s", (issue["id"],))
    assert row["status"] == "해결" and row["resolved_at"] is not None and row["close_reason"]


def test_evaluate_boundary_and_upsert_refreshes_one_issue():
    scope = uniq("RULE")
    with conn.tx() as cur:
        cur.execute("""insert into management_threshold(metric_key,level,compare_op,value_min,period_from,period_to,scope_kind,scope_key,created_by)
                       values ('orders.qty','위험','lt',80,'2026-10-01','2026-10-31','department',%s,'test') returning id""", (scope,))
        threshold_id = cur.fetchone()["id"]
        finding = management.evaluate(cur, "orders.qty", Decimal("80"), {"scope_kind":"department","scope_key":scope,"source_screen":"RPT-010"}, date(2026,10,20))
        assert finding is None
        finding = management.evaluate(cur, "orders.qty", Decimal("70"), {"scope_kind":"department","scope_key":scope,"source_screen":"RPT-010"}, date(2026,10,20))
        assert finding and finding["severity"] == "위험"
        first = management.upsert_issue(cur, finding, "test")
        finding["observed_value"] = Decimal("60")
        second = management.upsert_issue(cur, finding, "test")
        assert first == second
    try:
        row = conn.q1("select observed_value from management_issue where id=%s", (first,))
        assert row["observed_value"] == Decimal("60")
    finally:
        with conn.tx() as cur:
            cur.execute("delete from management_issue where id=%s", (first,))
            cur.execute("delete from management_threshold where id=%s", (threshold_id,))
