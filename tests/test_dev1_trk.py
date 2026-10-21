# tests/test_dev1_trk.py — TRK 통합 조회 3 화면 (읽기만) — 실제 DB · 시드 뒤 · 만든 행은 지운다
import pytest

from lcomfine.db import conn
from test_dev1_common import cleanup, client, make_customer, make_item, make_order, make_request, uniq


def _counts() -> dict:
    """읽기만 하는지 — 테스트가 만든 행 주변의 업무 행 수 (다른 개발자가 같은 DB 에 쓰므로 전체 행 수는 보지 않는다)."""
    like = "T%-trk%"
    return conn.q1("""select (select count(*) from production_request r join item i on i.id = r.item_id
                                where i.item_code like %(l)s) as req,
                             (select count(*) from work_order w join item i on i.id = w.item_id where i.item_code like %(l)s) as wo,
                             (select count(*) from production_daily d join work_order w on w.id = d.work_order_id
                                join item i on i.id = w.item_id where i.item_code like %(l)s) as daily,
                             (select count(*) from notification where message like %(l)s) as noti,
                             (select count(*) from sys_change_log where path like '/trk/%%') as changes""",
                   {"l": like})


@pytest.fixture
def p():
    prefix = uniq("trk")
    yield prefix
    conn.x("delete from production_daily where work_order_id in (select w.id from work_order w join item i "
           "on i.id = w.item_id where i.item_code like %s)", (prefix + "%",))
    cleanup(prefix)


def _flow(p, due="current_date + 2"):
    it, cu = make_item(p), make_customer(p)
    rq = make_request(p, customer_id=cu["id"], item_id=it["id"], qty=50, due=due, status="지시완료")
    wo = make_order(p, request_id=rq["id"], item_id=it["id"], qty=50)
    conn.x("insert into production_daily (work_order_id, work_date, equipment_code, produced_qty, good_qty) "
           "values (%s, current_date, 'EQ01', 30, 28)", (wo["id"],))
    return it, cu, rq, wo


@pytest.mark.fn("F-TRK-011")
def test_order_progress_one_request(p):
    it, cu, rq, wo = _flow(p)
    before = _counts()
    r = client("sh").get("/trk/orders", params={"request": rq["request_no"]})
    assert r.status_code == 200 and f'data-request="{rq["request_no"]}"' in r.text
    assert "지금 단계 <strong>생산</strong>" in r.text and "50.000" in r.text and wo["work_order_no"] in r.text
    assert _counts() == before                                  # 읽기만 — 업무 테이블 행 수 그대로
    assert client("sh").get("/trk/orders", params={"request": "없는번호"}).status_code == 422
    r = client("ds").get("/trk/orders", params={"q": p})
    assert r.status_code == 200 and rq["request_no"] in r.text


@pytest.mark.fn("F-TRK-021")
def test_due_buckets_and_stopped_stage(p):
    _it, cu, rq, _wo = _flow(p, due="current_date - 1")          # 지연 · 생산에서 멈춤
    p2 = p + "B"
    it2, cu2 = make_item(p2), make_customer(p2)
    soon = make_request(p2, customer_id=cu2["id"], item_id=it2["id"], due="current_date + 2")
    before = _counts()
    c = client("pr")
    r = c.get("/trk/due", params={"bucket": "지연", "customer": str(cu["id"])})
    assert r.status_code == 200 and rq["request_no"] in r.text and 'data-bucket="지연"' in r.text
    assert "<td>생산</td>" in r.text
    r = c.get("/trk/due", params={"bucket": "D-3", "customer": str(cu2["id"])})
    assert soon["request_no"] in r.text
    r = c.get("/trk/due", params={"bucket": "D-7", "customer": str(cu2["id"])})   # D-7 은 D-3 을 포함
    assert soon["request_no"] in r.text
    assert c.get("/trk/due", params={"bucket": "모름"}).status_code == 422
    assert _counts() == before
    assert client("ds").get("/trk/due").status_code == 403


@pytest.mark.fn("F-TRK-031")
def test_customer_overview(p):
    it, cu, rq, _wo = _flow(p)
    before = _counts()
    r = client("sl").get("/trk/customers", params={"customer": str(cu["id"])})
    assert r.status_code == 200 and f'data-customer="{cu["customer_code"]}"' in r.text
    assert rq["request_no"] in r.text and "미수집" in r.text and "stats.customer_receivable" in r.text
    assert _counts() == before
    assert client("sl").get("/trk/customers").status_code == 200
    assert client("sl").get("/trk/customers", params={"customer": "99999999999"}).status_code == 422
    assert client("pr").get("/trk/customers").status_code == 403
