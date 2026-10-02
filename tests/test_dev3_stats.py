"""실적 현황 (F-STA-01~04 · P10) 과 집계 `app/stats.py` (G-10) — 손으로 센 값과 대조한다.

산식은 `contracts/interfaces.md` §7 · D-25 · D-301 · D-302. 대상 행은 SQL 로 직접 만든다(접두 `T3A-`, 날짜는 2001년 3월 —
다른 사람의 데이터와 기간이 겹치지 않고, 그래도 품목 조건으로 한 번 더 가른다). 끝나면 그 접두의 행이 하나도 남지 않는다.
"""
import inspect
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from lcomfine.app import nav, stats
from lcomfine.app.routers import sta

from test_dev3_support import SqlSpy, World, cleanup, client, leftovers

P = "T3A-"
SUMMARY = nav.path_of("STA-01")
BOARD = nav.path_of("STA-02")
KST = timezone(timedelta(hours=9))
MARCH = (date(2001, 3, 1), date(2001, 3, 31))


def at(month: int, day: int, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2001, month, day, hour, minute, second, tzinfo=KST)


@pytest.fixture(scope="module")
def w():
    world = World(P)
    a, b, cust = world.item("A"), world.item("B"), world.customer()
    world.a, world.b = a, b

    # ── 생산 (D5 → D2): 완료 실적 · ended_at 의 날짜가 기간 안 ──
    ja, jb = world.job("JA", a, cust, date(2001, 5, 1)), world.job("JB", b, cust, date(2001, 5, 1))
    world.work(ja, at(3, 10), Decimal("100"), scraps=(Decimal("5"), Decimal("2.5")))
    world.work(ja, at(3, 12), Decimal("50.5"))
    world.work(ja, at(3, 31, 23, 59, 59), Decimal("1"))          # 끝 날짜의 마지막 초 — 포함
    world.work(ja, at(4, 1, 0, 0, 0), Decimal("999"), scraps=(Decimal("9"),))   # 다음 날 0시 — 기간 밖
    world.work(ja, None, None)                                    # 진행 중 — 대상 아님
    world.work(jb, at(3, 20), None, scraps=(Decimal("1"),))       # 실적 수량이 비어 있는 완료 실적

    # ── 품질 (D7 → D2): 검사 행 수 · 불합격 수 · 평균 ΔE(비어 있는 것 제외) ──
    ra, rb = world.roll("RA", ja), world.roll("RB", jb)
    world.inspection(ra, ja, "합격", Decimal("1.0"), at(3, 5))
    world.inspection(ra, ja, "불합격", Decimal("3.0"), at(3, 5, 15))
    world.inspection(ra, ja, "합격", None, at(3, 6))
    world.inspection(ra, ja, "불합격", Decimal("9.0"), at(2, 28, 23, 59, 59))   # 기간 밖
    world.inspection(rb, jb, "불합격", None, at(3, 7))

    # ── 납기 (D2 ← D8): due_date 가 기간 안 · 취소 제외 · 승인된 출하 중 가장 이른 출하일 ──
    def job(no, due, status="등록", item=a):
        return world.job(no, item, cust, date(2001, 3, due) if isinstance(due, int) else due, status)

    j1, j2, j3, j4 = job("J1", 10), job("J2", 10), job("J3", 10), job("J4", 15)
    job("J5", 25), job("J6", 20), job("J7", 12, "취소"), job("J8", 28, item=b), job("J9", date(2001, 4, 2))
    world.shipment("S1", j1, cust, date(2001, 3, 9), "승인")       # 준수
    world.shipment("S2A", j2, cust, date(2001, 3, 12), "승인")     # 지연 (가장 이른 승인 출하 3/12 > 3/10)
    world.shipment("S2B", j2, cust, date(2001, 3, 15), "승인")
    world.shipment("S2C", j2, cust, date(2001, 3, 1), "등록")      # 승인되지 않은 출하는 보지 않는다
    world.shipment("S3A", j3, cust, date(2001, 3, 12), "승인")     # 준수 (가장 이른 3/8 ≤ 3/10)
    world.shipment("S3B", j3, cust, date(2001, 3, 8), "승인")
    world.shipment("S4", j4, cust, date(2001, 3, 14), "등록")      # 승인된 출하 없음 + 납기 지남 → 지연
    world.shipment("S5", world.job("J10", a, cust, date(2001, 3, 30)), cust, date(2001, 3, 29), "취소")   # 취소 출하 → 미출하
    yield world
    cleanup(P)
    assert leftovers(P) == {}


def by_item(rows: list[dict], w) -> dict:
    return {{w.a: "A", w.b: "B"}[r["item_id"]]: r for r in rows if r["item_id"] in (w.a, w.b)}


def test_production_formula(w):
    got = by_item(stats.production(*MARCH), w)
    assert (got["A"]["work_count"], got["A"]["output_qty"], got["A"]["scrap_qty"]) == (3, Decimal("151.5"), Decimal("7.5"))
    assert (got["B"]["work_count"], got["B"]["output_qty"], got["B"]["scrap_qty"]) == (1, 0, Decimal("1"))
    assert (got["A"]["item_code"], got["A"]["item_name"]) == (P + "A", "제품 A (예시)")
    only_a = stats.production(*MARCH, w.a)                         # 품목 조건
    assert [r["item_id"] for r in only_a] == [w.a] and only_a[0]["work_count"] == 3
    april = by_item(stats.production(date(2001, 4, 1), date(2001, 4, 1)), w)
    assert set(april) == {"A"} and (april["A"]["work_count"], april["A"]["output_qty"], april["A"]["scrap_qty"]) == (1, Decimal("999"), Decimal("9"))
    one_day = by_item(stats.production(date(2001, 3, 31), date(2001, 3, 31)), w)
    assert one_day["A"]["work_count"] == 1 and one_day["A"]["scrap_qty"] == 0     # 양 끝 포함 · 폐기 없음 = 0
    assert by_item(stats.production(date(2001, 1, 1), date(2001, 1, 31)), w) == {}


def test_quality_formula(w):
    got = by_item(stats.quality(*MARCH), w)
    a, b = got["A"], got["B"]
    assert (a["inspection_count"], a["fail_count"], a["fail_rate"], a["avg_delta_e"]) == (3, 1, 1 / 3, Decimal("2"))
    assert (b["inspection_count"], b["fail_count"], b["fail_rate"], b["avg_delta_e"]) == (1, 1, 1.0, None)   # ΔE 가 없으면 평균도 없다
    feb = by_item(stats.quality(date(2001, 2, 28), date(2001, 3, 5)), w)["A"]
    assert (feb["inspection_count"], feb["fail_count"]) == (3, 2)
    assert abs(feb["avg_delta_e"] - Decimal("13") / 3) < Decimal("1e-9")       # (1.0 + 3.0 + 9.0) ÷ 3 — DB 의 numeric 평균
    assert [r["item_id"] for r in stats.quality(*MARCH, w.b)] == [w.b]
    assert by_item(stats.quality(date(2001, 1, 1), date(2001, 1, 31)), w) == {}


def test_delivery_formula(w):
    got = by_item(stats.delivery(*MARCH, today=date(2001, 3, 20)), w)
    a, b = got["A"], got["B"]
    # A: J1 준수 · J2 지연 · J3 준수 · J4 지연(미승인 + 납기 지남) · J5·J6·J10 미출하 · J7 취소 제외 · J9 기간 밖
    assert (a["job_count"], a["on_time"], a["late"], a["pending"], a["on_time_rate"]) == (7, 2, 2, 3, 0.5)
    assert (b["job_count"], b["on_time"], b["late"], b["pending"], b["on_time_rate"]) == (1, 0, 0, 1, None)   # 분모 0 → None
    later = by_item(stats.delivery(*MARCH, today=date(2001, 3, 26)), w)["A"]      # 날이 지나면 미출하가 지연으로
    assert (later["on_time"], later["late"], later["pending"], later["on_time_rate"]) == (2, 4, 1, 2 / 6)
    same_day = by_item(stats.delivery(*MARCH, today=date(2001, 3, 25)), w)["A"]   # 납기 = 오늘 은 아직 미출하
    assert (same_day["late"], same_day["pending"]) == (3, 2)
    now = by_item(stats.delivery(*MARCH), w)                                      # 기본 "오늘" = 실행한 날 → 전부 지났다
    assert (now["A"]["late"], now["A"]["pending"], now["B"]["late"], now["B"]["on_time_rate"]) == (5, 0, 1, 0.0)
    assert by_item(stats.delivery(date(2001, 3, 10), date(2001, 3, 10), w.a, today=date(2001, 3, 10)), w)["A"]["job_count"] == 3


def test_totals_and_board(w):
    rows = [r for r in stats.quality(*MARCH) if r["item_id"] in (w.a, w.b)]
    t = stats.totals("quality", rows)
    assert (t["inspection_count"], t["fail_count"], t["fail_rate"], t["avg_delta_e"]) == (4, 2, 0.5, Decimal("2"))
    t = stats.totals("production", [r for r in stats.production(*MARCH) if r["item_id"] in (w.a, w.b)])
    assert (t["work_count"], t["output_qty"], t["scrap_qty"]) == (4, Decimal("151.5"), Decimal("8.5"))
    t = stats.totals("delivery", [r for r in stats.delivery(*MARCH, today=date(2001, 3, 20)) if r["item_id"] in (w.a, w.b)])
    assert (t["job_count"], t["on_time"], t["late"], t["pending"], t["on_time_rate"]) == (8, 2, 2, 4, 0.5)
    assert stats.totals("quality", []) is None                      # 행이 없으면 합계도 없다 → 화면은 미수집
    with pytest.raises(ValueError):
        stats.totals("기타", rows)

    b = stats.board(date(2001, 3, 10))                              # 현황판 = 그날 하루를 같은 함수로 (D-302)
    assert b["today"] == date(2001, 3, 10) and set(b) == {"today", "production", "quality", "delivery", "totals"}
    assert b["production"] == stats.production(date(2001, 3, 10), date(2001, 3, 10))
    assert b["quality"] == stats.quality(date(2001, 3, 10), date(2001, 3, 10))
    assert b["delivery"] == stats.delivery(date(2001, 3, 10), date(2001, 3, 10), today=date(2001, 3, 10))
    prod = by_item(b["production"], w)["A"]
    assert (prod["work_count"], prod["output_qty"], prod["scrap_qty"]) == (1, Decimal("100"), Decimal("7.5"))
    due = by_item(b["delivery"], w)["A"]
    assert (due["job_count"], due["on_time"], due["late"], due["pending"]) == (3, 2, 1, 0)


def test_stats_is_read_only_and_single_place():
    """집계 SQL 은 `stats.py` 한 곳 · 전부 select. 실적 현황 라우터에는 SQL 이 없다 (G-05 · G-10)."""
    write = re.compile(r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from|create\s+table|truncate)\b", re.I)
    assert not write.search(inspect.getsource(stats))
    src = inspect.getsource(sta)
    assert not write.search(src) and "import conn" not in src and "select " not in src.lower()
    assert stats.period("", "", today=date(2001, 3, 20)) == (date(2001, 3, 1), date(2001, 3, 20))   # 기본 기간 = 이번 달


def _section(html: str, kind: str) -> str:
    start = html.index(f'id="{kind}"')
    return html[start:html.index("</section>", start)]


@pytest.mark.fn("F-STA-01")
def test_production_summary_screen(w):
    c = client("field")                                             # 실적 현황은 네 역할 모두 조회
    r = c.get(f"{SUMMARY}/production", params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.a})
    assert r.status_code == 200
    sec = _section(r.text, "production")
    assert f"<code>{P}A</code>" in sec and '<td class="num">3</td>' in sec and "151.5" in sec and "7.5" in sec
    assert 'id="quality"' not in r.text and 'id="delivery"' not in r.text          # 이 기능은 생산 집계만
    r = c.get(f"{SUMMARY}/production", params={"date_from": "1990-01-01", "date_to": "1990-01-31"})
    assert r.status_code == 200 and "미수집" in _section(r.text, "production")       # 0건 (G-11)
    assert c.get(f"{SUMMARY}/production", params={"date_from": "2001-03-31", "date_to": "2001-03-01"}).status_code == 422
    assert c.get(f"{SUMMARY}/production", params={"date_from": "어제"}).status_code == 422
    assert client().get(f"{SUMMARY}/production").status_code == 401


@pytest.mark.fn("F-STA-02")
def test_quality_summary_screen(w):
    r = client("prod").get(f"{SUMMARY}/quality", params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.a})
    assert r.status_code == 200
    sec = _section(r.text, "quality")
    assert f"<code>{P}A</code>" in sec and "33.3%" in sec and "2.00" in sec and 'id="production"' not in r.text
    r = client("prod").get(f"{SUMMARY}/quality", params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.b})
    row = _section(r.text, "quality")
    assert "100.0%" in row and f"<code>{P}B</code>" in row
    assert client("prod").get(f"{SUMMARY}/quality", params={"item_id": "없는품목"}).status_code == 422


@pytest.mark.fn("F-STA-03")
def test_delivery_summary_screen(w):
    r = client("qc").get(f"{SUMMARY}/delivery", params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.a})
    assert r.status_code == 200
    sec = _section(r.text, "delivery")
    cells = re.findall(r'<td class="num">([^<]*)</td>', sec[sec.index(f"<code>{P}A</code>"):])[:5]
    assert cells == ["7", "2", "5", "0", "28.6%"]                    # 오늘 기준 — 2001년의 납기는 전부 지났다 (준수 2 ÷ (2 + 5))
    r = client("qc").get(f"{SUMMARY}/delivery", params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.b})
    cells = re.findall(r'<td class="num">([^<]*)</td>', _section(r.text, "delivery"))[:5]
    assert cells == ["1", "0", "1", "0", "0.0%"]

    r = client("admin").get(SUMMARY, params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.a})   # 화면 GET — 셋 다
    assert r.status_code == 200 and all(f'id="{k}"' in r.text for k in ("production", "quality", "delivery"))
    assert "151.5" in _section(r.text, "production") and "33.3%" in _section(r.text, "quality")


@pytest.mark.fn("F-STA-04")
def test_board_refreshes_itself_and_shows_today(w):
    world = World(P + "B-")                                          # 오늘 날짜의 실적 · 검사 · 납기 한 벌
    try:
        item, cust = world.item("TODAY"), world.customer()
        job = world.job("JT", item, cust, date.today())
        world.work(job, datetime.now().astimezone(), Decimal("12345.5"), scraps=(Decimal("0.5"),))
        world.inspection(world.roll("RT", job), job, "불합격", Decimal("2.75"))
        c = client("field")
        r = c.get(BOARD, params={"device": "board"})
        assert r.status_code == 200
        html = r.text
        assert 'class="ch-board"' in html and 'http-equiv="refresh"' in html      # 조작 없이 자동 새로고침
        assert html.count("마지막 갱신") >= 2 and "초마다 자동 새로고침" in html   # 마지막 갱신 시각
        main = html[html.index('<main class="main">'):html.index("</main>")]
        assert f"<code>{P}B-TODAY</code>" in main and "12,345.5" in main and "2.75" in main
        row = [r for r in stats.board()["delivery"] if r["item_id"] == item][0]
        assert (row["job_count"], row["pending"], row["late"]) == (1, 1, 0)        # 오늘이 납기 = 아직 미출하
        today = stats.board()
        assert today["production"] == stats.production(date.today(), date.today())  # 집계 화면과 같은 함수의 값
        web = c.get(BOARD).text
        assert 'class="ch-web"' in web and "현황판으로 열기" in web and "마지막 갱신" in web
        assert client().get(BOARD).status_code == 401
    finally:
        cleanup(P + "B-")
    assert leftovers(P + "B-") == {}


@pytest.mark.fn("F-STA-01", "F-STA-02", "F-STA-03", "F-STA-04")
def test_status_screens_write_nothing(w, monkeypatch):
    """P10 은 어떤 테이블에도 쓰지 않는다(G-05) — 돌린 SQL 은 select 뿐이고, 쓰기는 공통 접근 로그 한 줄뿐이다."""
    c = client("admin")
    params = {"date_from": "2001-03-01", "date_to": "2001-03-31"}
    for path, q in [(SUMMARY, params), (f"{SUMMARY}/production", params), (f"{SUMMARY}/quality", params),
                    (f"{SUMMARY}/delivery", params), (BOARD, {}), (BOARD, {"device": "board"})]:
        spy = SqlSpy(monkeypatch)
        assert c.get(path, params=q).status_code == 200
        spy.assert_read_only()
        assert len(spy.writes) == 1
        monkeypatch.undo()


@pytest.mark.fn("F-STA-01", "F-STA-02", "F-STA-03")
def test_summary_fits_mobile_width(w):
    """모바일 채널(G-13) — 한 단 레이아웃, 집계 표는 줄을 바꿔 폭 안에 든다(`table.grid.fit`)."""
    r = client("admin").get(SUMMARY, params={"date_from": "2001-03-01", "date_to": "2001-03-31", "device": "mobile"})
    assert r.status_code == 200 and 'class="ch-mobile"' in r.text
    main = r.text[r.text.index('<main class="main">'):r.text.index("</main>")]
    assert main.count('<table class="grid plain fit">') == 3 and "table.grid.fit th,table.grid.fit td{white-space:normal" in r.text
