"""QA2 — 계보 10행 재현(G-06) · 양방향 추적(G-07) · 키 연결(G-08)의 독립 검증.

개발2 의 `tests/test_lineage_scenario.py` 와 `app/lineage.py` 의 추적 함수를 쓰지 않는다.
  · 기대값: 설계도 §3 그림의 상자·화살표를 SVG 좌표에서 읽은 그래프 (`check_data.design_graph`)
  · 만들기: 화면이 부르는 것과 같은 API (Job 등록 포함) + 화면의 폼을 그대로 제출
  · 추적: LOT 추적 화면(`GET /trc/trace/forward|backward`)의 결과 ↔ QA2 의 독립 재귀 SQL ↔ 내가 요청한 화살표(모델)

결함을 드러내는 테스트는 실패하는 채로 둔다 (DEF-QA2-001 · 002 · 003 — `outputs/qa2-계보데이터.md`).
만든 데이터는 `Q2-…` 접두이고 모듈이 끝나면 전부 지운다.
"""

from __future__ import annotations

import random
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_data as cd  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    c = cd.Ctx()
    yield c
    c.cleanup()
    left = {k: v for f in c.flows for k, v in cd.leftovers(c.db, f.tag + "-%").items()}
    c.close()
    assert not left, f"QA2 데이터가 남았다: {left}"


@pytest.fixture(scope="module")
def design(ctx):
    """설계도 §3 예시 한 벌 — (flow, 그림, 상자 이름 → 번호)."""
    return ctx.design()


# ── 기대값: 설계도 §3 그림 ──────────────────────────────────────────────
def test_design_figure_is_read_from_the_design_doc():
    g = cd.design_graph()
    by_proc: dict[str, int] = {}
    for n in g["nodes"].values():
        by_proc[n["process"]] = by_proc.get(n["process"], 0) + 1
    assert by_proc == {"입고": 2, "인쇄": 2, "후가공": 1, "슬리팅": 3, "출하": 1}
    assert len(g["edges"]) == g["arrows"] == 10
    rel: dict[str, int] = {}
    for _, _, r in g["edges"]:
        rel[r] = rel.get(r, 0) + 1
    assert rel == {"투입": 3, "splice": 2, "슬리팅": 3, "출하": 2}
    assert ("원재료 LOT ①", "인쇄 Roll ①", "투입") in g["edges"] and ("원재료 LOT ①", "인쇄 Roll ②", "투입") in g["edges"]
    assert ("원재료 LOT ②", "인쇄 Roll ②", "투입") in g["edges"] and ("원재료 LOT ②", "인쇄 Roll ①", "투입") not in g["edges"]
    assert g["stock"] == ["슬리팅 Roll ③"] and g["same_job"] and g["coa"]


# ── G-06 계보 10행 ──────────────────────────────────────────────────────
@pytest.mark.fn("F-JOB-01", "F-MAT-01", "F-MAT-03", "F-POP-01", "F-MAT-07", "F-POP-02", "F-RLL-02", "F-RLL-04", "F-SHP-01", "F-SHP-02",
                "F-SHP-05")
def test_g06_design_example_makes_exactly_ten_rows(ctx, design):
    flow, g, m = design
    rows = ctx.db.q(cd.SCOPE_ROWS_SQL, {"like": flow.tag + "-%"})
    assert len(rows) == 10
    by_rel: dict[str, int] = {}
    for r in rows:
        by_rel[r["relation"]] = by_rel.get(r["relation"], 0) + 1
    assert by_rel == {"투입": 3, "splice": 2, "슬리팅": 3, "출하": 2}
    inv = {v: k for k, v in m.items()}
    got = {(inv[p], inv[c], rel) for p, c, rel in cd.sql_edges_of_tag(ctx.db, flow.tag)}
    assert got == set(g["edges"])


def test_g06_job_was_registered_through_the_api(ctx, design):
    flow, _, m = design
    calls = [c for c in ctx.api.calls if c["method"] == "POST" and c["path"] == "/job/orders" and c["status"] == 200]
    assert calls, "POST /job/orders 로 Job 을 만든 요청이 없다"
    job = ctx.db.q1("select status, created_by from job where job_no = %s", (m["Job"],))
    assert job == {"status": "등록", "created_by": "prod"}


def test_g06_stock_shipped_and_coa(ctx, design):
    _, g, m = design
    state = {r["roll_no"]: r["state"] for r in ctx.db.q("select roll_no, state from v_roll_state where roll_no = any(%s)",
                                                        ([m[k] for k in g["nodes"] if k.startswith("슬리팅")],))}
    assert state[m["슬리팅 Roll ③"]] == "재고"
    assert state[m["슬리팅 Roll ①"]] == state[m["슬리팅 Roll ②"]] == "출하"
    sh = ctx.db.q1("select status, coa_no from shipment where shipment_no = %s", (m["출하 LOT"],))
    assert sh["status"] == "승인" and sh["coa_no"]


def test_g06_by_screen_forms_only(ctx):
    """화면을 열어 그 안의 폼을 그대로 제출해서 같은 10행을 만든다 (goal.md §1-3 「화면 조작만으로」)."""
    g = cd.design_graph()
    flow, m = cd.build_design_by_forms(ctx, g)
    inv = {v: k for k, v in m.items() if isinstance(v, str)}
    got = {(inv.get(p, p), inv.get(c, c), rel) for p, c, rel in cd.sql_edges_of_tag(ctx.db, flow.tag)}
    assert got == set(g["edges"])


# ── G-07 추적 ───────────────────────────────────────────────────────────
@pytest.mark.fn("F-TRC-02")
def test_g07_backward_from_shipment_reaches_both_material_lots(ctx, design):
    _, _, m = design
    scr = cd.screen_trace(ctx.api, m["출하 LOT"], "backward")
    mine = cd.sql_trace(ctx.db, m["출하 LOT"], "backward")
    assert scr["status"] == 200
    assert scr["lots"] == mine["lots"] == {m["원재료 LOT ①"], m["원재료 LOT ②"]}
    assert scr["edges"] == mine["edges"] and len(scr["edges"]) == 9          # 슬리팅 ③ 의 화살표 하나만 빠진다
    assert m["슬리팅 Roll ③"] not in {e[1] for e in scr["edges"]}


@pytest.mark.fn("F-TRC-01")
def test_g07_forward_from_lot1_reaches_shipment_and_marks_stock(ctx, design):
    _, _, m = design
    scr = cd.screen_trace(ctx.api, m["원재료 LOT ①"], "forward")
    mine = cd.sql_trace(ctx.db, m["원재료 LOT ①"], "forward")
    assert scr["status"] == 200 and scr["edges"] == mine["edges"] and len(scr["edges"]) == 9   # LOT ② 의 투입 화살표만 빠진다
    reached = {e[1] for e in scr["edges"]}
    for name in ("인쇄 Roll ①", "인쇄 Roll ②", "후가공 Roll", "슬리팅 Roll ①", "슬리팅 Roll ②", "슬리팅 Roll ③", "출하 LOT"):
        assert m[name] in reached, f"{name} 에 닿지 못했다"
    assert scr["ships"] == {m["출하 LOT"]}
    assert scr["stock"] == mine["stock"] == {m["슬리팅 Roll ③"]}
    assert "재고" in scr["text"]


def test_g07_forward_from_lot2_does_not_include_print_roll_1(ctx, design):
    _, _, m = design
    scr = cd.screen_trace(ctx.api, m["원재료 LOT ②"], "forward")
    nodes = {e[0] for e in scr["edges"]} | {e[1] for e in scr["edges"]}
    assert m["인쇄 Roll ②"] in nodes and m["인쇄 Roll ①"] not in nodes
    assert scr["ships"] == {m["출하 LOT"]}


@pytest.mark.fn("F-TRC-01", "F-TRC-02")
def test_g07_every_node_of_the_example_both_directions(ctx, design):
    flow, g, m = design
    diffs = []
    for name, n in g["nodes"].items():
        dirs = ("forward",) if n["table"] == "material_lot" else ("backward",) if n["table"] == "shipment" else ("forward", "backward")
        for d in dirs:
            diffs += cd.compare_trace(ctx.api, ctx.db, flow, m[name], d)
    assert not diffs, diffs[:5]


@pytest.mark.parametrize("seed, n_jobs", [(11, 1), (22, 2), (33, 3), (44, 2)])
@pytest.mark.fn("F-TRC-01", "F-TRC-02", "F-RLL-01", "F-RLL-02", "F-RLL-04", "F-SHP-03")
def test_g07_random_lineage_screen_equals_independent_sql(ctx, seed, n_jobs):
    """분기·깊이를 키운 임의 계보 — 모든 노드에서 화면 추적 = 독립 재귀 SQL = 모델(내가 요청한 화살표)."""
    flow = ctx.flow()
    meta = cd.build_random_lineage(flow, random.Random(seed), n_jobs=n_jobs)
    assert meta["depth"] >= 5, f"깊이 {meta['depth']}단 — 5단 이상이어야 한다"
    assert meta["ops"]["splice"] >= 2
    assert cd.sql_edges_of_tag(ctx.db, flow.tag) == flow.edges, "내가 요청한 화살표와 DB 의 계보 행이 다르다"
    diffs, n = [], 0
    for no, kind in sorted(flow.kind.items()):
        for d in (("forward",) if kind == "L" else ("backward",) if kind == "S" else ("forward", "backward")):
            n += 1
            diffs += cd.compare_trace(ctx.api, ctx.db, flow, no, d)
    assert n > 30 and not diffs, diffs[:5]
    # 투입되지 않은 LOT 의 정방향 추적은 0건 + 미수집
    scr = cd.screen_trace(ctx.api, meta["unused_lot"], "forward")
    assert scr["status"] == 200 and not scr["edges"] and cd.NOT_COLLECTED in scr["text"]
    if n_jobs > 1:                                              # 한 원재료 LOT 이 여러 Job 으로
        jobs = {flow.job_of[c] for p, c, rel in flow.edges if p == meta["lots"][0] and rel == "투입"}
        assert len(jobs) == n_jobs


def test_g07_trace_is_one_recursive_query_and_writes_nothing(ctx, design):
    _, _, m = design
    for no, d in ((m["출하 LOT"], "backward"), (m["원재료 LOT ①"], "forward"), (m["후가공 Roll"], "backward"), (m["후가공 Roll"], "forward")):
        scr = cd.screen_trace(ctx.api, no, d)
        assert sum(1 for s in scr["sql"] if "with recursive" in s.lower()) == 1
        assert sum(1 for s in scr["sql"] if "roll_genealogy" in s) == 1, "계보를 읽는 문장이 하나가 아니다 (노드마다 다시 조회하는가)"
        assert {t for _, t in scr["writes"]} <= {"sys_access_log"}


def test_g07_wrong_direction_and_unknown_number_are_422(ctx, design):
    _, _, m = design
    assert cd.screen_trace(ctx.api, m["출하 LOT"], "forward")["status"] == 422
    assert cd.screen_trace(ctx.api, m["원재료 LOT ①"], "backward")["status"] == 422
    assert cd.screen_trace(ctx.api, "Q2-NO-SUCH-NUMBER", "backward")["status"] == 422


def test_g07_no_stored_path_trace_follows_genealogy_live(ctx):
    """추적 결과를 따로 쌓지 않는다 — 출하 스캔 → 취소에 따라 같은 LOT 의 정방향 추적이 곧바로 바뀐다."""
    f = ctx.flow()
    fg = f.item("FG", "제품")
    f.item("RM", "원재료")
    job = f.job(fg, f.customer(), date.today())
    lot = f.lot(f.code("RM"))
    roll = f.print_roll(job, [lot])
    sh = f.shipment(job, date.today())
    assert cd.screen_trace(ctx.api, lot, "forward")["ships"] == set()
    f.scan(sh, roll)
    t = cd.screen_trace(ctx.api, lot, "forward")
    assert t["ships"] == {sh} and t["stock"] == set()
    f.cancel_shipment(sh)
    t = cd.screen_trace(ctx.api, lot, "forward")
    assert t["ships"] == set() and t["stock"] == {roll}
    live = {r["table_name"] for r in ctx.db.q(
        "select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE'")}
    assert live == set(cd.contracts.db_tables()), "계약에 없는 테이블이 있다"
    assert ctx.db.v("select count(*) from pg_matviews where schemaname = 'public'") == 0


def test_g07_cycles_self_parent_reshipping_and_reuse_are_blocked(ctx):
    probes = cd.guard_probes(ctx)
    assert len(probes) >= 25
    bad = [(name, detail) for name, ok, detail in probes if not ok]
    assert not bad, bad


# ── G-08 키 연결 ────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def g08_rows(ctx):
    rep = cd.Report()
    cd.check_g08(ctx, rep)
    return {item: (status, actual) for _, item, status, actual in rep.rows}


def _row(rows: dict, needle: str) -> tuple[str, str]:
    hit = [(k, v) for k, v in rows.items() if needle in k]
    assert len(hit) == 1, f"`{needle}` 에 맞는 판정 행이 {len(hit)}개"
    return hit[0][1]


@pytest.mark.parametrize("needle", [
    "[SQL] 롤 번호 하나",
    "[화면] 롤 이력",
    "[화면] Job-Lot-Roll 매핑",
    "[SQL] Job-Lot-Roll 키 무결성",
    "[화면] COA",
    "[정적] 번호를 만드는 코드",
    "[동적] 받은 번호",
])
def test_g08_key_linkage_and_numbering(g08_rows, needle):
    status, actual = _row(g08_rows, needle)
    assert status == cd.PASS, actual


@pytest.mark.fn("F-RLL-06")
def test_g08_roll_history_shows_production_result_for_finishing_and_slit_rolls(g08_rows):
    """DEF-QA2-001 — 후가공·슬리팅 롤의 롤 이력에 생산 실적이 안 나온다.

    기대값: goal.md G-08 「롤 번호 하나로 그 롤의 … 생산 실적 … 이 조회된다」 · contracts/db-schema.md §6
    「후가공·슬리팅 롤: 계보를 거슬러 올라간 인쇄 롤의 실적」. 출하되는 롤은 늘 후가공·슬리팅 롤이다.
    """
    status, actual = _row(g08_rows, "후가공·슬리팅 롤 번호")
    assert status == cd.PASS, actual


@pytest.mark.fn("F-RLL-02")
def test_g08_splice_cannot_put_a_roll_under_a_cancelled_job(g08_rows):
    """DEF-QA2-002 — splice 의 `job_no` 에 취소된 Job 을 주면 그 Job 에 롤이 생긴다.

    기대값: function-list.md F-JOB-03 「작업 실적·롤이 없는 Job 만 상태 `취소`」 · F-POP-01 「취소·완료 Job 은 422」.
    """
    status, actual = _row(g08_rows, "취소된 Job 에 롤이 생기지 않는다")
    assert status == cd.PASS, actual


@pytest.mark.fn("F-QUA-01", "F-QUA-04")
def test_g08_inspection_scan_finds_the_roll_like_the_other_scan_screens(ctx):
    """DEF-QA2-003 — 검사 결과 화면만 소문자로 들어온 롤 번호를 못 찾는다 (슬리팅·출하 스캔·LOT 추적은 찾는다, D-201)."""
    f = ctx.flow()
    fg = f.item("FG", "제품")
    f.item("RM", "원재료")
    job = f.job(fg, f.customer(), date.today())
    roll = f.print_roll(job, [f.lot(f.code("RM"))])
    low = roll.lower()
    assert low != roll
    others = {
        "LOT 추적 (GET /trc/trace/backward)": ctx.api.get("admin", "/trc/trace/backward", {"no": low}).status_code,
        "롤 이력 (GET /rll/history)": ctx.api.get("prod", "/rll/history", {"no": low}).status_code,
    }
    assert set(others.values()) == {200}, others
    status, body = ctx.api.post("qc", "/qua/inspections", {"roll_no": low, "result": "합격", "delta_e": "1.0"})
    opened = ctx.api.get("qc", "/qua/inspections", {"no": low}).status_code
    assert (status, opened) == (200, 200), f"검사 결과 등록 HTTP {status} {body.get('message')} · 스캔 진입 HTTP {opened} (다른 스캔 화면은 200)"


# ── 재검 (웨이브 D 뒤) — 작업 시작과 Job 마감·취소가 겹칠 때 ─────────────────
@pytest.mark.fn("F-POP-01", "F-JOB-02", "F-JOB-03")
@pytest.mark.parametrize("closing", ["취소", "완료"])
def test_g08_work_start_racing_with_job_close_leaves_no_open_work_on_a_closed_job(ctx, closing):
    """DEF-QA2-004 — 작업 시작(F-POP-01)과 Job 취소(F-JOB-03) · 마감(F-JOB-02 `완료`)을 **동시에** 보내면
    둘 다 200 이 되어 닫힌 Job 에 열린(`진행`) 작업 실적이 남는다.

    기대값: function-list.md F-JOB-03 「작업 실적·롤이 없는 Job 만 상태 `취소`」 · F-JOB-02 / D-107 「진행 중인 작업 실적이 있는 Job 은
    `완료` 로 마감할 수 없다」 · F-POP-01 「취소·완료 Job 은 422」. 어느 쪽이 먼저든 둘 중 하나는 422 여야 한다.
    원인(개발1 이 `progress-dev1.md` §3-8 에 추정으로 적은 것): `routers/pop.py` 의 작업 시작이 Job 상태를 트랜잭션 밖에서 읽고
    실적을 따로 넣는다 — 그 사이에 마감·취소가 끝난다. 화면의 작업 시작 폼이 보내는 값(Job · 생산 LOT · 설비)을 그대로 보낸다.
    앱을 건드리지 않고 실제 동시 요청으로 잰다(시도 40회 안에 한 번이라도 어긋나면 실패 — 실측 재현율은 리포트에)."""
    import threading

    f = ctx.flow()
    fg, cu = f.item("FG", "제품"), f.customer()
    eq = ctx.db.v("select equipment_code from equipment order by equipment_id limit 1") or ""
    starter, closer = ctx.api.new_client("field"), ctx.api.new_client("prod")
    bad, outcomes = [], {}
    for attempt in range(1, 41):
        job = f.job(fg, cu, date.today())
        lot = f.job_lot(job, 1)
        got: dict[str, int] = {}
        gate = threading.Barrier(2)

        def start():
            gate.wait()
            got["start"] = starter.post("/pop/work/start", data={"job_no": job, "lot_no": lot, "equipment_code": eq},
                                        follow_redirects=False).status_code

        def close():
            gate.wait()
            if closing == "취소":
                got["close"] = closer.post(f"/job/orders/{job}/cancel", follow_redirects=False).status_code
            else:
                got["close"] = closer.post(f"/job/orders/{job}", data={"status": "완료"}, follow_redirects=False).status_code

        ts = [threading.Thread(target=start), threading.Thread(target=close)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        status = ctx.db.v("select status from job where job_no = %s", (job,))
        open_works = ctx.db.v("""select count(*) from work_result w join job j on j.job_id = w.job_id
                                  where j.job_no = %s and w.status <> '완료'""", (job,))
        key = f"시작 {got.get('start')} · {closing} {got.get('close')} → Job {status} · 열린 실적 {open_works}"
        outcomes[key] = outcomes.get(key, 0) + 1
        if status == closing and open_works:
            bad.append(f"시도 {attempt}: Job {job} — {key}")
            break
    assert not bad, f"{closing} 된 Job 에 열린 작업 실적이 생겼다 — {bad[0]} (그때까지의 결과 {outcomes})"
