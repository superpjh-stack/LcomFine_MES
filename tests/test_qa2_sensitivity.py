"""QA2 — 검사기 자체의 민감도. 앱을 **이 프로세스 안에서만** 일부러 망가뜨려(monkeypatch — `src/` 는 고치지 않는다)
`tools/check_data.py` 의 대조가 그것을 잡아내는지 본다. 잡지 못하는 검사는 PASS 를 내도 믿을 수 없다.

  · 추적 재귀를 두 단에서 끊는다          → 화면 ≠ 독립 SQL 로 잡혀야 한다 (G-07)
  · 부모 롤의 재고 검사를 없앤다          → 소진 롤 재사용이 「안 막힘」 으로 잡혀야 한다 (G-07)
  · 생산 집계에서 기간 끝날을 뺀다        → 화면 ≠ 독립 SQL 로 잡혀야 한다 (G-10)
  · LOT 추적이 업무 테이블에 UPDATE 를 친다 → 실행 SQL 캡처에 잡혀야 한다 (G-05)
  · 빈 목록의 `미수집` 글자를 지운다       → 빈 화면 검사에 잡혀야 한다 (G-11)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_data as cd  # noqa: E402
from lcomfine.app import lineage, stats, templating  # noqa: E402
from lcomfine.db import conn  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    c = cd.Ctx()
    yield c
    c.cleanup()
    c.close()


def test_broken_recursion_is_detected(ctx, monkeypatch):
    flow, _, m = ctx.design()
    assert not cd.compare_trace(ctx.api, ctx.db, flow, m["출하 LOT"], "backward")          # 멀쩡할 때는 차이가 없다
    monkeypatch.setattr(lineage, "_WALK", lineage._WALK.replace("= w.next_roll_id", "= w.next_roll_id and w.depth < 2"))
    diffs = cd.compare_trace(ctx.api, ctx.db, flow, m["출하 LOT"], "backward")
    assert diffs and any("화면" in d and "독립 SQL" in d for d in diffs), diffs
    assert cd.compare_trace(ctx.api, ctx.db, flow, m["원재료 LOT ①"], "forward")


def test_missing_stock_check_is_detected(ctx, monkeypatch):
    monkeypatch.setattr(lineage, "assert_usable", lambda cur, parents: None)
    probes = cd.guard_probes(ctx)
    unblocked = [name for name, ok, _ in probes if not ok]
    assert any("소진" in n or "다시 슬리팅" in n for n in unblocked), unblocked


def test_wrong_period_boundary_in_production_stats_is_detected(ctx, monkeypatch):
    assert "w.ended_at::date between %(date_from)s and %(date_to)s" in stats._PRODUCTION_SQL
    monkeypatch.setattr(stats, "_PRODUCTION_SQL", stats._PRODUCTION_SQL.replace(
        "w.ended_at::date between %(date_from)s and %(date_to)s",
        "w.ended_at::date >= %(date_from)s and w.ended_at::date < %(date_to)s"))
    rep = cd.Report()
    cd.check_g10(ctx, rep)
    bad = [r for r in rep.failed() if r[1].startswith("생산 집계")]
    assert bad, "기간 끝날을 뺀 생산 집계를 검사기가 통과시켰다"
    assert not [r for r in rep.failed() if r[1].startswith(("품질 집계", "납기 집계", "불량 유형별"))]


def test_a_write_from_the_trace_route_is_detected(ctx, monkeypatch):
    _, _, m = ctx.design()
    orig = lineage.trace_forward

    def leaky(node):
        conn.x("update job set note = note where false")                # 행은 안 바뀌어도 쓰기 문장이다
        return orig(node)

    monkeypatch.setattr(lineage, "trace_forward", leaky)
    scr = cd.screen_trace(ctx.api, m["원재료 LOT ①"], "forward")
    assert ("update", "job") in scr["writes"]
    assert not {t for _, t in scr["writes"]} <= {"sys_access_log"}


def test_a_missing_empty_marker_is_detected(ctx, monkeypatch):
    monkeypatch.setitem(templating.env.globals, "NOT_COLLECTED", "")
    templating.env.cache.clear()                    # 이미 읽어 둔 템플릿은 옛 전역 값을 들고 있다
    try:
        r = ctx.api.get("admin", "/bas/items", {"code": "Q2-NO-SUCH-CODE"})
        st = cd.empty_state_of(cd.main_of(r.text))
        assert r.status_code == 200 and not st["has_marker"]
        r = ctx.api.get("admin", "/sta/summary", {"date_from": "1990-01-01", "date_to": "1990-01-02"})
        st = cd.empty_state_of(cd.main_of(r.text))
        assert not st["has_marker"] and all(t["empty_text"] == [""] for t in st["tables"])
        rep = cd.Report()
        cd.check_g11(ctx, rep)
        assert len(rep.failed()) >= 10, "`미수집` 이 사라졌는데 빈 화면 검사가 통과했다"
    finally:
        monkeypatch.undo()
        templating.env.cache.clear()


def test_model_trace_is_independent_of_the_app():
    """모델 추적(파이썬)은 앱도 DB 도 쓰지 않는다 — 손으로 그린 그래프로 확인."""
    edges = {("L1", "P1", "투입"), ("L1", "P2", "투입"), ("L2", "P2", "투입"), ("P1", "F", "splice"), ("P2", "F", "splice"),
             ("F", "S1", "슬리팅"), ("F", "S2", "슬리팅"), ("F", "S3", "슬리팅"), ("S1", "SH", "출하"), ("S2", "SH", "출하")}
    kind = {"L1": "L", "L2": "L", "SH": "S", **{k: "R" for k in ("P1", "P2", "F", "S1", "S2", "S3")}}
    back = cd.model_trace(edges, kind, "SH", "backward")
    assert back["lots"] == {"L1", "L2"} and len(back["edges"]) == 9
    fwd = cd.model_trace(edges, kind, "L1", "forward")
    assert fwd["ships"] == {"SH"} and fwd["stock"] == {"S3"} and len(fwd["edges"]) == 9
    assert cd.model_trace(edges, kind, "L2", "forward")["edges"] == edges - {("L1", "P1", "투입"), ("L1", "P2", "투입"), ("P1", "F", "splice")}
    assert cd.longest_path(edges) == 4               # 화살표 수: LOT → 인쇄 → 후가공 → 슬리팅 → 출하
    assert date.today() >= date(2026, 1, 1)
