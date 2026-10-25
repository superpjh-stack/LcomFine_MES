"""MGT-010/020 경영목표·경보기준 — 버전 보존, 기간 중복, 권한, 감사."""
from decimal import Decimal

import pytest

from lcomfine.app import management
from lcomfine.db import conn
from test_dev1_common import client, uniq


@pytest.fixture()
def scope():
    key = uniq("MGT")
    yield key
    with conn.tx() as cur:
        cur.execute("delete from management_threshold where scope_key = %s", (key,))
        # 목표 버전은 운영과 동일하게 append-only다. 수명주기 테스트가 마지막에 목표를
        # 중지하므로 이력은 보존한다(테스트 정리를 위해 불변 트리거를 우회하지 않는다).


def target_data(scope, **overrides):
    data = {
        "metric_key": "orders.qty", "period_kind": "월간",
        "period_from": "2026-10-01", "period_to": "2026-10-31",
        "scope_kind": "department", "scope_key": scope,
        "target_value": "100", "change_reason": "월 경영계획 수립",
    }
    data.update(overrides)
    return data


@pytest.mark.fn("F-MGT-011")
@pytest.mark.fn("F-MGT-012")
@pytest.mark.fn("F-MGT-013")
@pytest.mark.fn("F-MGT-014")
def test_target_lifecycle_keeps_versions_and_audit(scope):
    assert client("ex").get("/mgt/targets").status_code == 200
    assert client("ac").post("/mgt/targets", data=target_data(scope)).status_code == 403

    before = conn.q1("select count(*) n from sys_change_log where target like %s", (f"management_target:{scope}:%",))["n"]
    made = client("st").post("/mgt/targets", data=target_data(scope))
    assert made.status_code == 200, made.text
    target_id = made.json()["id"]

    duplicate = client("st").post("/mgt/targets", data=target_data(scope, period_from="2026-10-15",
                                                                    period_to="2026-11-15"))
    assert duplicate.status_code == 422
    assert "겹치는" in duplicate.text

    revised = client("st").post(f"/mgt/targets/{target_id}", data={
        "target_value": "120", "change_reason": "수주 전망 상향",
    })
    assert revised.status_code == 200, revised.text
    versions = conn.q("select version_no, target_value, change_reason from management_target_version "
                      "where target_id=%s order by version_no", (target_id,))
    assert [r["version_no"] for r in versions] == [1, 2]
    assert [r["target_value"] for r in versions] == [Decimal("100"), Decimal("120")]

    stopped = client("st").post(f"/mgt/targets/{target_id}/delete")
    assert stopped.status_code == 200, stopped.text
    assert conn.q1("select status from management_target where id=%s", (target_id,))["status"] == "중지"
    after = conn.q1("select count(*) n from sys_change_log where target like %s", (f"management_target:{scope}:%",))["n"]
    assert after - before == 3


@pytest.mark.fn("F-MGT-021")
@pytest.mark.fn("F-MGT-022")
@pytest.mark.fn("F-MGT-023")
@pytest.mark.fn("F-MGT-024")
def test_threshold_lifecycle_and_overlap(scope):
    data = {
        "metric_key": "orders.qty", "level": "주의", "compare_op": "lt", "value_min": "80",
        "period_from": "2026-10-01", "period_to": "2026-10-31",
        "scope_kind": "department", "scope_key": scope,
    }
    assert client("ex").get("/mgt/thresholds").status_code == 200
    made = client("st").post("/mgt/thresholds", data=data)
    assert made.status_code == 200, made.text
    threshold_id = made.json()["id"]
    overlap = client("st").post("/mgt/thresholds", data={**data, "period_from": "2026-10-20",
                                                           "period_to": "2026-11-30"})
    assert overlap.status_code == 422
    updated = client("st").post(f"/mgt/thresholds/{threshold_id}", data={**data, "value_min": "85"})
    assert updated.status_code == 200, updated.text
    stopped = client("st").post(f"/mgt/thresholds/{threshold_id}/delete")
    assert stopped.status_code == 200, stopped.text


def test_management_comparison_directions_and_zero():
    high = {"direction": "높을수록 좋음"}
    low = {"direction": "낮을수록 좋음"}
    bounded = {"direction": "범위 내 정상"}
    assert management.compare(high, Decimal("0"), {"target_value": Decimal("100")})["actual"] == Decimal("0")
    assert management.compare(high, Decimal("110"), {"target_value": Decimal("100")})["status"] == "정상"
    assert management.compare(low, Decimal("8"), {"target_value": Decimal("10")})["status"] == "정상"
    assert management.compare(bounded, Decimal("5"), {"range_min": Decimal("4"), "range_max": Decimal("6")})["status"] == "정상"
    assert management.compare(high, None, {"target_value": Decimal("1")})["status"] == "미수집"
    assert management.compare(high, Decimal("1"), None)["status"] == "목표 없음"
