# tests/test_dev1_home.py — HOME 내 할 일 · 알림함 · 알림 설정 — 실제 DB · 시드 뒤 · 만든 행은 지운다
import pytest

from lcomfine.app import notify
from lcomfine.app.routers.home import CARDS
from lcomfine.db import conn
from test_dev1_common import cleanup, client, login, make_customer, make_item, make_request, make_user, uniq


@pytest.fixture
def p():
    prefix = uniq("home")
    yield prefix
    cleanup(prefix)


@pytest.mark.fn("F-HOME-011")
def test_my_work_cards_due_and_today(p):
    it, cu = make_item(p), make_customer(p)
    rq = make_request(p, customer_id=cu["id"], item_id=it["id"], due="current_date + 1")
    c = client("sl")
    # 오늘 처리한 건 — sl 이 방금 한 쓰기 1건
    assert c.post(f"/bas/customers/{cu['id']}", data={"customer_name": f"{p} 거래처 (예시)"}).status_code == 200
    r = c.get("/")
    assert r.status_code == 200 and "미구현" not in r.text
    for card in CARDS["SL"]:
        assert f'data-card="{card.title}"' in r.text
    assert 'data-card="지시 대기 의뢰"' not in r.text                     # 다른 부서의 카드는 없다
    assert rq["request_no"] in r.text                        # 납기 임박 (D-1 · 미출하)
    assert f"customer:{cu['customer_code']}" in r.text        # 오늘 처리한 건
    assert 'href="/wo/requests?status=확인대기"' in r.text      # 카드 → 조건이 걸린 처리 화면
    # 건수는 질의 그대로
    n = conn.q1("select count(*) as n from production_request where status = '확인대기'")["n"]
    assert n >= 1
    r = client("pr").get("/")
    assert 'data-card="지시 대기 의뢰"' in r.text and 'data-card="불출 대기 지시"' in r.text
    assert 'data-card="단가·납기 확인이 필요한 의뢰"' not in r.text
    r = client("admin").get("/")                              # 전산 관리자 — 전 부서 카드 (D-601)
    assert all(f'data-card="{cd.title}"' in r.text for cards in CARDS.values() for cd in cards)
    r = client("ac").get("/")
    assert "90일 초과 미수" in r.text and "미수집" in r.text


@pytest.mark.fn("F-HOME-021")
def test_notification_list(p):
    key = f"{p}:judged"
    with conn.tx() as cur:
        notify.emit(cur, "judged", link="/qc/product", dedupe_key=key, text=f"{p} 판정 완료 (예시)")
    r = client("sh").get("/home/notifications")
    assert r.status_code == 200 and f"{p} 판정 완료" in r.text
    assert f"{p} 판정 완료" not in client("pr").get("/home/notifications").text   # 다른 부서


@pytest.mark.fn("F-HOME-022")
def test_notification_handle(p):
    key = f"{p}:judged"
    with conn.tx() as cur:
        notify.emit(cur, "judged", link="/qc/product", dedupe_key=key, text=f"{p} 판정 완료 (예시)")
    ids = {r["to_role"]: r["id"] for r in conn.q("select id, to_role from notification where dedupe_key = %s", (key,))}
    c = client("sl")                                          # 권한 예외 — 화면 R 이면 처리한다
    assert c.post(f"/home/notifications/{ids['SL']}/handle").status_code == 200
    assert conn.q1("select handled_by from notification where id = %s", (ids["SL"],))["handled_by"] == "sl"
    assert c.post(f"/home/notifications/{ids['SL']}/handle").status_code == 200   # 이미 처리 — 그대로
    assert c.post(f"/home/notifications/{ids['SH']}/handle").status_code == 404   # 다른 부서
    assert c.post("/home/notifications/99999999999/handle").status_code == 404
    assert c.post("/home/notifications/abc/handle").status_code == 404
    assert conn.q1("select handled_at from notification where id = %s", (ids["SH"],))["handled_at"] is None
    assert f"{p} 판정 완료" in c.get("/home/notifications").text.split("<h2>처리됨")[1]


@pytest.mark.fn("F-HOME-031")
def test_notification_settings_save(p):
    login_id, pw, uid = make_user(p, "SL")
    c = login(login_id, pw)
    all_keys = list(notify.EVENTS)
    defaults = [k for k, roles in notify.EVENTS.items() if "SL" in roles]
    r = c.post("/home/notification-settings", data={"events": all_keys, "enabled": defaults + ["order_issued"]})
    assert r.status_code == 200, r.text
    rows = {x["event_key"]: x["enabled"] for x in
            conn.q("select event_key, enabled from notification_setting where user_id = %s", (uid,))}
    assert rows["order_issued"] is True and rows["request_created"] is False
    assert not set(defaults) & set(rows)                       # 부서 기본은 행을 만들지 않는다(끌 수 없다)
    r = c.post("/home/notification-settings", data={"events": all_keys, "enabled": ["order_issued"]})
    assert r.status_code == 422 and "부서 기본 알림은 끌 수 없습니다" in r.json()["message"]
    assert c.post("/home/notification-settings", data={"events": all_keys, "enabled": defaults,
                                                       "mail": "on"}).status_code == 501
    assert c.post("/home/notification-settings", data={}).status_code == 422
    assert c.post("/home/notification-settings", data={"events": ["nope"]}).status_code == 422


@pytest.mark.fn("F-HOME-032")
def test_notification_settings_view(p):
    r = client("pr").get("/home/notification-settings")
    assert r.status_code == 200 and "부서 기본" in r.text and "개인 추가" in r.text and "미확정 (D-518)" in r.text
