# tests/test_dev1_trk.py — TRK 통합 조회 3 화면 (읽기만) — 실제 DB · 시드 뒤 · 만든 행은 지운다
from datetime import date
from decimal import Decimal

import pytest

from lcomfine.app import nav, stats
from lcomfine.app.routers import trk
from lcomfine.db import conn
from test_dev1_common import Erp, cleanup, client, make_customer, make_item, make_order, make_request, uniq


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
    assert rq["request_no"] in r.text and 'data-receivable="미수집"' in r.text     # 매핑 · 반영 회차 없음 = 미수집
    assert _counts() == before
    assert client("sl").get("/trk/customers").status_code == 200
    assert client("sl").get("/trk/customers", params={"customer": "99999999999"}).status_code == 422
    assert client("pr").get("/trk/customers").status_code == 403


# ── W2 — stats 공표 연결 (Ruling 23 · progress-dev3 §1.3) ───────────────────────────────────────────
@pytest.mark.fn("F-TRK-031")
def test_customer_receivable_from_erp_upload(p, monkeypatch):
    """수금·미수 칸 = stats.customer_receivable: 반영 회차가 없으면 `미수집`, (예시) xlsx 를 올리면 매출 · 수금 · 미수 잔액 · 마지막 거래일 ·
    ERP 업로드 기준일(asof) 이 보인다. 매출액 열 미매핑(status 미확정)은 글자 그대로. 끝에 회차 · 행 · 알림 · 매핑을 지운다."""
    it, cu, rq, _wo = _flow(p)
    erp = Erp(p, cu["id"])
    try:
        c = client("sl")
        r = c.get("/trk/customers", params={"customer": str(cu["id"])})
        assert r.status_code == 200 and 'data-receivable="미수집"' in r.text and "매핑된 ERP 거래처코드가 없다" in r.text
        erp.map_code()
        erp.upload(date(1985, 1, 1), date(1985, 1, 31), [(erp.code, "1985-01-10", 1000, 300), (erp.code, "1985-01-20", 500, 0)])
        cr = stats.customer_receivable(cu["id"])
        assert cr["status"] == "ok" and cr["receivable_amount"] == Decimal("1200.00") and cr["asof"] is not None
        before = _counts()
        r = c.get("/trk/customers", params={"customer": str(cu["id"])})
        assert r.status_code == 200 and 'data-receivable="ok"' in r.text
        assert f'data-asof="{cr["asof"].isoformat()}"' in r.text and "ERP 업로드 기준일" in r.text
        seg = r.text.split('data-receivable="ok"')[1]
        assert "1,500" in seg and "1,200" in seg and "1985-01-20" in seg and erp.code in seg and "D-803" in seg
        assert "수금 칸은 W2 에 개발3 의" not in r.text                        # W1 자리표시 문장은 없다(계약 문장은 /ia 기능 계약 표에 남는다)
        assert _counts() == before                                            # 읽기만
        # 매출액 열이 매핑되지 않은 모양(status 미확정) — 전역 열 매핑을 건드리지 않고 공표 반환 모양으로 화면만 검사한다
        und = dict(cr, status="미확정 (D-516)", decision="D-516", sales_amount=None, receivable_amount=None)
        monkeypatch.setattr(trk.stats, "customer_receivable", lambda cid: und)
        r = c.get("/trk/customers", params={"customer": str(cu["id"])})
        assert r.status_code == 200 and 'data-receivable="미확정 (D-516)"' in r.text
        assert r.text.count("미확정 (D-516)") >= 3 and "300" in r.text.split("<h2>수금·미수")[1]   # 매출 · 미수는 미확정 · 수금 합은 그대로
        monkeypatch.undo()
    finally:
        erp.close()
    assert stats.customer_receivable(cu["id"])["status"] == "미수집"


@pytest.mark.fn("F-TRK-021")
def test_due_compliance_from_stats(p):
    """납기 준수율 수치 = stats.due_compliance(period) — period `YYYY-MM`(기본 이번 달) · 산식 문장(가설 D-804) 이 수치 옆에 ·
    분모 0 이면 `미수집` · 형식이 틀리면 422."""
    it, cu = make_item(p), make_customer(p)
    late = make_request(p, customer_id=cu["id"], item_id=it["id"], due="date '1986-03-15'", status="지시완료")   # 지연 (미완료)
    c = client("pr")

    def expected(ym: str) -> str:
        comp = stats.due_compliance(ym)
        return f"{comp['rate']:,.1f}" if comp["rate"] is not None else "미수집"

    r = c.get("/trk/due", params={"period": "1986-03", "customer": str(cu["id"])})
    assert r.status_code == 200 and late["request_no"] in r.text and 'data-period="1986-03"' in r.text
    assert f'data-compliance="{expected("1986-03")}"' in r.text and stats.due_compliance("1986-03")["late_open"] >= 1
    assert stats.DUE_COMPLIANCE_FORMULA in r.text and "D-804" in r.text and "data-formula" in r.text   # 산식 문장(D-804) — 함수 이름은 화면에 두지 않는다(ui-guide §1)
    r = c.get("/trk/due")                                                       # 기본 = 이번 달
    assert r.status_code == 200 and f'data-period="{date.today():%Y-%m}"' in r.text
    assert f'data-compliance="{expected(date.today().strftime("%Y-%m"))}"' in r.text
    comp = stats.due_compliance("1987-01")                                      # 아무도 쓰지 않는 달 — 분모 0 = 미수집
    r = c.get("/trk/due", params={"period": "1987-01"})
    assert f'data-compliance="{"미수집" if comp["rate"] is None else f"{comp["rate"]:,.1f}"}"' in r.text
    for bad_period in ("1986-3", "abcd-ef", "1986/03"):
        assert c.get("/trk/due", params={"period": bad_period}).status_code == 422, bad_period
