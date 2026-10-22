# tests/test_dev1_home.py — HOME 내 할 일 · 알림함 · 알림 설정 — 실제 DB · 시드 뒤 · 만든 행은 지운다
from datetime import date

import re

import pytest

from lcomfine.app import nav, notify, stats
from lcomfine.app.routers.home import CARDS
from lcomfine.db import conn
from test_dev1_common import Erp, cleanup, client, login, make_customer, make_item, make_request, make_user, uniq


def over90_card(html: str) -> str:
    """HOME-010 회계부 「90일 초과 미수」 카드 조각."""
    assert 'data-card="90일 초과 미수"' in html
    return html.split('data-card="90일 초과 미수"')[1].split("</div>")[0]


def over90_expected() -> str:
    """카드가 보여야 하는 값 — stats 그대로: 반영 회차 없음 = 미수집 · 매출액 열 미매핑 = 미확정 (D-516) · 그 밖 = len(aging["over90"])."""
    asof = stats.erp_asof()
    if asof is None:
        return "미수집"
    a = stats.aging(asof)
    return f"미확정 ({a['undecided']})" if a["undecided"] else f"{len(a['over90']):,}"


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
    assert over90_expected() in over90_card(r.text)                      # 집계는 stats (W2)


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
    """Ruling 24 · D-511: 자기 부서가 수신하는 이벤트만 — 부서 기본은 끌 수 없고(422), 다른 부서 이벤트 구독은 저장하지 않고 422."""
    login_id, pw, uid = make_user(p, "SL")
    c = login(login_id, pw)
    all_keys = list(notify.EVENTS)
    defaults = [k for k, roles in notify.EVENTS.items() if "SL" in roles]
    assert "order_issued" not in defaults
    # 범위 밖 행이 남아 있던 경우 — 저장이 지운다
    conn.x("insert into notification_setting (user_id, event_key, enabled, created_by) values (%s, 'order_issued', true, 'test')",
           (uid,))
    r = c.post("/home/notification-settings", data={"events": defaults, "enabled": defaults})
    assert r.status_code == 200, r.text
    assert r.json()["removed_out_of_scope"] == 1
    assert conn.q1("select count(*) as n from notification_setting where user_id = %s", (uid,))["n"] == 0
    # 다른 부서 이벤트 — 보이는 칸이 없고, 보내도 저장하지 않고 422
    r = c.post("/home/notification-settings", data={"events": all_keys, "enabled": defaults + ["order_issued"]})
    assert r.status_code == 422 and "범위 밖" in r.json()["message"], r.text
    assert conn.q1("select count(*) as n from notification_setting where user_id = %s", (uid,))["n"] == 0
    # 부서 기본 알림 끄기 — 422
    r = c.post("/home/notification-settings", data={"events": defaults, "enabled": defaults[1:]})
    assert r.status_code == 422 and "부서 기본 알림은 끌 수 없습니다" in r.json()["message"]
    assert c.post("/home/notification-settings", data={"events": defaults, "enabled": defaults,
                                                       "mail": "on"}).status_code == 501
    assert c.post("/home/notification-settings", data={}).status_code == 422
    assert c.post("/home/notification-settings", data={"events": ["nope"]}).status_code == 422


@pytest.mark.fn("F-HOME-032")
def test_notification_settings_view(p):
    r = client("pr").get("/home/notification-settings")
    assert r.status_code == 200 and "부서 기본" in r.text and "미확정 (D-518)" in r.text
    assert "<code>order_issued</code>" in r.text and "<code>shipment_confirmed</code>" not in r.text   # PR 수신분만 · 개인 추가 칸 없음
    assert 'chip--muted">개인 추가' not in r.text
    assert re.search(r'개인 추가 알림의 범위는 <span class="[^"]*\bundecided\b[^"]*"[^>]*>미확정 \(D-526\)</span>', r.text)   # D-526 차단 — 화면 본문에 보인다(미확정 칩 · ui.undecided)
    # 수신하는 이벤트가 없는 부서(전산 관리자) — 칸 없음 · 저장 버튼 없음
    r = client("admin").get("/home/notification-settings")
    assert r.status_code == 200 and "수신하는 알림이 없다" in r.text and 'name="events"' not in r.text


@pytest.mark.fn("F-HOME-011")
def test_ac_over90_card_from_stats_aging(p):
    """회계부 「90일 초과 미수」 = len(stats.aging(stats.erp_asof())["over90"]) — 반영 회차가 없으면 `미수집` · 링크 COL-060 ·
    (예시) ERP 행(기준일에서 90일 넘게 지난 매출)을 올리면 그 거래처가 센다 · 「업로드 오류 행」 카드에 미처리 알림 건수. 끝에 지운다."""
    cu = make_customer(p)
    erp = Erp(p, cu["id"])
    try:
        c = client("ac")
        r = c.get("/")
        assert r.status_code == 200
        seg = over90_card(r.text)
        assert over90_expected() in seg and f'href="{nav.path_of("COL-060")}"' in seg
        if stats.erp_asof() is None:
            assert "미수집" in seg and "반영된 ERP 업로드 회차가 없다" in seg
        erp.map_code()
        erp.upload(date(1985, 1, 1), date(1985, 1, 31), [(erp.code, "1984-09-01", 500, 0)])    # 기준일 1985-01-31 에서 152일 전
        asof = stats.erp_asof()
        a = stats.aging(asof)
        r = c.get("/")
        seg = over90_card(r.text)
        assert over90_expected() in seg and "ERP 업로드 기준일" in seg
        if not a["undecided"]:
            assert cu["id"] in [row["customer_id"] for row in a["over90"]]
            assert f'kpi__value num">{len(a["over90"]):,}</strong>' in seg
        else:
            assert "미확정 (D-516)" in seg
        err = r.text.split('data-card="업로드 오류 행"')[1].split("</div>")[0]
        n_alerts = conn.q1("""select count(*) as n from notification
                               where event_key = 'erp_upload_error' and to_role = 'AC' and handled_at is null""")["n"]
        assert f"미처리 알림 {n_alerts}건" in err
        assert 'data-card="ERP 업로드 오류' not in r.text                    # 알림 건수는 따로 카드를 두지 않는다(중복)
    finally:
        erp.close()
