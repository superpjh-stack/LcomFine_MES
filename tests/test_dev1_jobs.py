# tests/test_dev1_jobs.py — 배치 due-check (납기 D-3 미출하 → 영업부·생산부 알림) — 실제 DB · 만든 행은 지운다
from datetime import date

import pytest

from lcomfine import jobs
from lcomfine.app import nav
from lcomfine.db import conn
from test_dev1_common import cleanup, make_customer, make_item, make_request, uniq


@pytest.fixture
def p():
    prefix = uniq("job")
    yield prefix
    conn.x("delete from notification where dedupe_key like %s", (f"due:{prefix}%",))
    cleanup(prefix)


def test_due_check_emits_once_per_dept_per_day(p):
    it, cu = make_item(p), make_customer(p)
    soon = make_request(p + "A", customer_id=cu["id"], item_id=it["id"], due="current_date + 2")
    late = make_request(p + "B", customer_id=cu["id"], item_id=it["id"], due="current_date - 1")
    far = make_request(p + "C", customer_id=cu["id"], item_id=it["id"], due="current_date + 10")
    canceled = make_request(p + "D", customer_id=cu["id"], item_id=it["id"], due="current_date", status="취소")
    today = date.today().isoformat()
    mine = [soon["request_no"], late["request_no"], far["request_no"], canceled["request_no"]]
    assert jobs.due_check(request_nos=mine) == {"requests": 2, "created": 4}
    rows = conn.q("select dedupe_key, to_role, link from notification where dedupe_key like %s order by 1, 2",
                  (f"due:{p}%",))
    assert [(r["dedupe_key"], r["to_role"]) for r in rows] == [
        (f"due:{soon['request_no']}:{today}", "PR"), (f"due:{soon['request_no']}:{today}", "SL"),
        (f"due:{late['request_no']}:{today}", "PR"), (f"due:{late['request_no']}:{today}", "SL")]
    assert rows[0]["link"] == nav.path_of("TRK-020") + f"?request={soon['request_no']}"
    assert far["request_no"] not in str(rows) and canceled["request_no"] not in str(rows)
    assert jobs.due_check(request_nos=mine)["created"] == 0       # 같은 날 다시 — 무시(D-522)
    assert conn.q1("select count(*) as n from notification where dedupe_key like %s", (f"due:{p}%",))["n"] == 4


def test_main_usage():
    assert jobs.main([]) == 2
    assert jobs.main(["nope"]) == 2
