"""QA2 — 집계의 독립 재계산(G-10): 실적 현황(생산 · 품질 · 납기) · 불량 유형별 집계 · 현황판.

데이터는 QA2 가 화면 API 로 만든다(경계 시각만 내 행에 한해 SQL 로 옮긴다). 기대값은 세 겹이다.
  ① 데이터를 만들면서 손으로 정한 값 (`build_stats_data` 의 `expect`)
  ② `contracts/interfaces.md` §7 · D-25 · D-301 의 **문장**만 보고 따로 짠 SQL (`check_data.sql_*` — `app/stats.py` 의 SQL 을 쓰지 않는다)
  ③ 화면(`GET /sta/summary/*` · `/qua/defect-stats` · `/sta/board`)에 보이는 값
경계: 기간 끝날 23:59:59 / 다음 날 00:00:00 · 첫날 00:00:00 · 실적 수량 0 · 단위가 섞인 수량(m + kg) · 한 롤에 검사 3번 ·
ΔE 가 없는 검사 · 출하일 = 납기 · 납기 = 오늘 · 분모 0.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_data as cd  # noqa: E402

KINDS = ("production", "quality", "delivery")
SQL = {"production": cd.sql_production, "quality": cd.sql_quality, "delivery": cd.sql_delivery}


@pytest.fixture(scope="module")
def ctx():
    c = cd.Ctx()
    yield c
    c.cleanup()
    c.close()


@pytest.fixture(scope="module")
def data(ctx):
    return cd.build_stats_data(ctx)


def period(data, kind):
    return data["P"] if kind != "delivery" else data["D"]


def same(a, b, tol="0.0000001") -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal(tol)


@pytest.mark.parametrize("kind", KINDS)
def test_independent_sql_equals_the_values_designed_into_the_data(ctx, data, kind):
    d1, d2 = period(data, kind)
    mine = SQL[kind](ctx.db, d1, d2)
    for item in (data["a"], data["b"]):
        for key, want in data["expect"][kind][item].items():
            assert same(mine[item][key], want), f"{kind} {data['codes'][item]}.{key}: 독립 SQL {mine[item][key]} ≠ {want}"


@pytest.mark.fn("F-STA-01", "F-STA-02", "F-STA-03")
@pytest.mark.parametrize("kind", KINDS)
def test_summary_screen_equals_independent_sql(ctx, data, kind):
    d1, d2 = period(data, kind)
    for item in (data["a"], data["b"]):
        want = SQL[kind](ctx.db, d1, d2, item).get(item)
        for path in (f"/sta/summary/{kind}", "/sta/summary"):
            r = ctx.api.get("admin", path, {"date_from": str(d1), "date_to": str(d2), "item_id": str(item)})
            assert r.status_code == 200
            scr = cd.parse_summary(r.text)[kind]
            code = data["codes"][item]
            _, bad = cd.diff_cells(kind, code, scr["rows"].get(code), want)
            assert not bad, bad
            _, bad = cd.diff_cells(kind, code + " 합계", scr["total"], cd.total_of(kind, {item: want}))
            assert not bad, bad


@pytest.mark.parametrize("kind", KINDS)
def test_stats_function_values_equal_designed_values(data, kind):
    """화면이 자르기 전의 값(`stats.production|quality|delivery` 의 반환값)도 같아야 한다."""
    from lcomfine.app import stats

    d1, d2 = period(data, kind)
    rows = {r["item_id"]: r for r in getattr(stats, kind)(d1, d2)}
    for item in (data["a"], data["b"]):
        for key, want in data["expect"][kind][item].items():
            if key.startswith("_"):
                continue
            assert same(rows[item][key], want, "0.000000001"), f"stats.{kind} {data['codes'][item]}.{key} {rows[item][key]} ≠ {want}"


def test_production_boundaries(ctx, data):
    """끝날 23:59:59 는 들어가고 다음 날 00:00:00 은 빠진다. 첫날 00:00:00 은 들어가고 전날 23:59:59 는 빠진다."""
    a = data["a"]
    day = lambda s: cd.date.fromisoformat(s)   # noqa: E731

    def shown(d1: str, d2: str):
        r = ctx.api.get("admin", "/sta/summary/production", {"date_from": d1, "date_to": d2, "item_id": str(a)})
        return cd.parse_summary(r.text)["production"]["rows"].get(data["codes"][a])

    assert shown("2001-03-31", "2001-03-31") == [Decimal("1"), Decimal("0.0"), Decimal("0.0")]      # 끝날의 마지막 초 — 실적 수량 0
    assert shown("2001-04-01", "2001-04-01") == [Decimal("1"), Decimal("7.0"), Decimal("0.0")]      # 다음 날 0시는 4월 1일
    assert shown("2001-03-01", "2001-03-01") == [Decimal("1"), Decimal("20.2"), Decimal("0.0")] or \
        shown("2001-03-01", "2001-03-01") == [Decimal("1"), Decimal("20.3"), Decimal("0.0")]         # 20.25 의 표시(반올림 방식은 묻지 않는다)
    assert shown("2001-02-28", "2001-02-28") == [Decimal("1"), Decimal("9.0"), Decimal("1.0")]      # 전날
    assert cd.sql_production(ctx.db, day("2001-03-31"), day("2001-03-31"), a)[a]["work_count"] == 1


def test_quality_counts_every_inspection_of_a_roll_and_skips_empty_delta_e(ctx, data):
    a, b = data["a"], data["b"]
    d1, d2 = data["P"]
    mine = cd.sql_quality(ctx.db, d1, d2)
    assert mine[a]["inspection_count"] == 4 and mine[a]["fail_count"] == 2          # 한 롤에 검사 3번 = 3행
    assert same(mine[a]["avg_delta_e"], Decimal("7.00") / 3)                        # ΔE 없는 검사는 평균의 분모에서 빠진다
    assert mine[b]["avg_delta_e"] is None                                           # ΔE 가 하나도 없으면 평균은 없다
    r = ctx.api.get("admin", "/sta/summary/quality", {"date_from": str(d1), "date_to": str(d2), "item_id": str(b)})
    assert cd.parse_summary(r.text)["quality"]["rows"][data["codes"][b]] == [Decimal("1"), Decimal("0"), Decimal("0.0"), None]


def test_delivery_denominator_zero_is_shown_as_dash_not_zero(ctx, data):
    b = data["b"]
    d1, d2 = data["D"]
    r = ctx.api.get("admin", "/sta/summary/delivery", {"date_from": str(d1), "date_to": str(d2), "item_id": str(b)})
    scr = cd.parse_summary(r.text)["delivery"]
    assert scr["rows"][data["codes"][b]] == [Decimal("1"), Decimal("0"), Decimal("0"), Decimal("1"), None]
    assert scr["total"][-1] is None


@pytest.mark.fn("F-QUA-05", "F-QUA-06")
def test_defect_stats_screen_equals_independent_sql(ctx, data):
    d1, d2 = data["P"]
    for label, item, expect in (("품목 A", data["a"], data["defects"]["a"]), ("전체", None, data["defects"]["all"])):
        mine = cd.sql_defects(ctx.db, d1, d2, item)
        assert {k: v for k, v in mine.items() if k in (data["dx"], data["dy"])} == expect, label
        params = {"date_from": str(d1), "date_to": str(d2)} | ({"item_id": str(item)} if item else {})
        r = ctx.api.get("qc", "/qua/defect-stats", params)
        assert r.status_code == 200
        body = cd.main_of(r.text)
        for code, want in expect.items():
            m = cd.re.search(rf"<code>{cd.re.escape(code)}</code></td>\s*<td>.*?</td>\s*<td class=\"num\">(\d+)</td>\s*<td class=\"num\">(\d+)</td>",
                             body, cd.re.S)
            assert m, f"{label}: 화면에 {code} 가 없다"
            assert (int(m.group(1)), int(m.group(2))) == (want["defect_count"], want["roll_count"]), f"{label} {code}"
            r2 = ctx.api.get("qc", "/qua/defect-stats/rolls", params | {"defect_code": code})
            sec = cd.re.search(r'<section class="panel grid-panel" id="rolls">(.*?)</section>', r2.text, cd.re.S).group(1)
            assert len(cd.re.findall(r"<tr>\s*<td>", cd.re.search(r"<tbody>(.*?)</tbody>", sec, cd.re.S).group(1))) == want["defect_count"]


@pytest.mark.fn("F-STA-04")
def test_board_equals_independent_sql_for_today(ctx, data):
    """현황판의 큰 숫자 = 오늘의 독립 SQL. 다른 QA 의 동시 쓰기와 구분하려고 앞뒤 SQL 이 같을 때의 화면만 본다."""
    today = data["today"]
    for _ in range(5):
        want = {k: cd.total_of(k, SQL[k](ctx.db, today, today)) for k in KINDS}
        r = ctx.api.get("field", "/sta/board", {"device": "board"}, client=ctx.api.new_client("field"))
        if want == {k: cd.total_of(k, SQL[k](ctx.db, today, today)) for k in KINDS}:
            break
    else:
        pytest.fail("현황판을 재는 동안 오늘 데이터가 계속 바뀌었다 (다른 QA 의 동시 쓰기) — 다시 돌린다")
    assert r.status_code == 200
    names = {"생산": "production", "품질": "quality", "납기": "delivery"}
    tiles = cd.re.findall(r'<section class="panel tile">(.*?)</section>', r.text, cd.re.S)
    assert len(tiles) == 3
    for tile in tiles:
        kind = names[cd.text_of_html(cd.re.search(r"<h2>(.*?)<small", tile, cd.re.S).group(1))]
        kpis = [cd._cell(v) for v in cd.re.findall(r'<div class="kpi[^"]*"><span>.*?</span><b>(.*?)</b></div>', tile, cd.re.S)]
        _, bad = cd.diff_cells(kind, f"현황판 {kind}", None if kpis == [cd.NOT_COLLECTED] else kpis, want[kind])
        assert not bad, bad


def test_empty_period_shows_not_collected_and_reversed_period_is_422(ctx):
    r = ctx.api.get("admin", "/sta/summary", {"date_from": "1990-01-01", "date_to": "1990-01-31"})
    scr = cd.parse_summary(r.text)
    assert len(scr) == 3 and all(v["empty"] and not v["rows"] and v["total"] is None for v in scr.values())
    assert ctx.api.get("admin", "/sta/summary", {"date_from": "2001-04-02", "date_to": "2001-03-01"}).status_code == 422


def test_g10_all_rows_pass(ctx):
    rep = cd.Report()
    cd.check_g10(ctx, rep)
    assert len(rep.rows) == 6
    assert not rep.failed(), [(r[1], r[3][:200]) for r in rep.failed()]
