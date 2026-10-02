"""QA2 — 스키마(G-04) · 쓰기 경계(G-05) · 시드 (예시)(G-09) · 빈 화면(G-11) · 범위 밖(G-12).

판정은 `tools/check_data.py` · `tools/check_schema.py` 가 내는 행이다. 여기서는 그 행이 전부 PASS 인지 보고,
검사기가 「아무것도 못 읽고 통과」 하지 않는지(읽은 라우트·화면·기능 수)를 같이 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_data as cd  # noqa: E402
import check_schema  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    c = cd.Ctx()
    yield c
    c.cleanup()
    left = {k: v for f in c.flows for k, v in cd.leftovers(c.db, f.tag + "-%").items()}
    c.close()
    assert not left, f"QA2 데이터가 남았다: {left}"


def failed(rep: cd.Report) -> list:
    return [(r[1], r[3][:300]) for r in rep.failed()]


# ── G-04 ────────────────────────────────────────────────────────────────
def test_g04_schema_checker_passes(capsys):
    rc = check_schema.main()
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln.startswith("G-04  ")]
    assert len(rows) == 15, "check_schema 의 검사 행 수가 바뀌었다"
    assert rc == 0, [ln for ln in rows if "  FAIL  " in ln]


def test_g04_design_doc_names_are_parsed_not_hardcoded():
    assert check_schema.design_table_names() == ["material_lot", "roll", "roll_genealogy", "shipment"]
    stores = check_schema.design_stores()
    assert sorted(stores) == [f"D{i}" for i in range(1, 9)] and stores["D6"] == "Roll·계보"
    boundary = check_schema.contract_write_boundary()
    assert boundary["P9"] == [] and boundary["P10"] == [] and boundary["P6"] == ["roll", "roll_genealogy"]


# ── G-05 ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def g05(ctx):
    rep = cd.Report()
    extra = cd.check_g05(ctx, rep)
    return rep, extra


def test_g05_write_boundary_rows_pass(g05):
    rep, _ = g05
    assert len(rep.rows) == 9
    assert not rep.failed(), failed(rep)


def test_g05_static_scan_really_read_the_routes(g05):
    """정적 스캔이 94개 기능의 라우트를 전부 읽었고, 쓰기 기능마다 쓰는 테이블을 찾았다."""
    _, extra = g05
    static = {fid: tables for fid, _proc, tables in extra["static"]}
    assert len(static) == 94
    assert static["F-POP-02"] == ["roll", "roll_genealogy", "sys_access_log", "sys_number_seq", "work_result"]
    assert static["F-SHP-02"] == ["roll_genealogy", "sys_access_log"]
    assert static["F-TRC-01"] == static["F-TRC-02"] == static["F-STA-01"] == ["sys_access_log"]
    assert static["F-MAT-07"] == ["material_input", "sys_access_log"]          # 자재 투입은 D3(material_lot)에 쓰지 않는다


def test_g05_every_write_function_was_really_called(g05):
    _, extra = g05
    want = {f.id for f in cd.contracts.functions() if f.is_write and not f.is_batch and f.process != "공통"}
    assert len(want) == 50 and set(extra["done"]) == want


def test_g05_p9_p10_change_no_business_table(g05):
    _, extra = g05
    r = extra["p9p10"]
    assert r["changed"] == [] and r["writes"] <= {"sys_access_log"} and all(s == 200 for s in r["statuses"])
    assert r["log_delta"] >= len(r["statuses"]), "화면 조회 로그가 남지 않았다 (G-18 — D-15 의 전제)"


def test_g05_processes_wrote_only_their_design_doc_stores(g05):
    _, extra = g05
    stores = {p: sorted({cd.contracts.db_tables()[t].store for t in tables}) for p, tables in extra["per_proc"].items()}
    design = {p: v["writes"] for p, v in cd.design_doc.processes().items()}
    for p, got in stores.items():
        allowed = set(design[p]) | ({"D6"} if p == "P8" else set())             # D-12
        assert set(got) <= allowed, f"{p}: {got} ⊄ {sorted(allowed)}"
    assert stores["P5"] == ["D5", "D6"] and stores["P6"] == ["D6"] and stores["P8"] == ["D6", "D8"]
    assert "P9" not in stores and "P10" not in stores


def test_g05_d12_p8_writes_only_shipping_rows(ctx, g05):
    changes = [c for f in ctx.flows for c in f.p8_changes]
    assert len(changes) >= 5
    assert {r for c in changes for r in c["added"]} == {"출하"}
    assert {r for c in changes for r in c["removed"]} <= {"출하"}
    assert all(not c["added"] and not c["removed"] for c in changes if c["fn"] == "F-SHP-05")


def test_writes_of_recognises_sql_writes():
    w = cd.writes_of
    assert w("insert into roll_genealogy (a) values (1)") == [("insert", "roll_genealogy")]
    assert w("update job set status = 'x' where job_id = 1") == [("update", "job")]
    assert w("delete from roll_genealogy where child_shipment_id = 1") == [("delete", "roll_genealogy")]
    assert w("select 1 from roll where roll_id = 1 for update") == []
    assert w("select roll_id from roll where roll_id = any(%s) order by roll_id for no key update") == []
    assert w("insert into sys_number_seq (a) values (1) on conflict (a) do update set last_value = 2") == [("insert", "sys_number_seq")]
    assert w("with x as (select 1) select * from x") == []


# ── G-09 ────────────────────────────────────────────────────────────────
def test_g09_seed_values_are_marked_as_examples(ctx):
    rep = cd.Report()
    cd.check_g09(ctx, rep, run_seeds=False)
    rows = [r for r in rep.rows if r[2] != cd.UNVERIFIED]
    assert len(rows) == 2 and not rep.failed(), failed(rep)
    n = sum(ctx.db.v(f"select count(*) from {t} where {who} = 'seed' and {col} is not null") for t, col, who in cd.SEED_NAME_COLUMNS)
    assert n >= 30, "시드 행을 읽지 못했다"


# ── G-11 ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def g11(ctx):
    rep = cd.Report()
    results = cd.check_g11(ctx, rep)
    return rep, results


def test_g11_all_32_screens_render_an_empty_state(g11):
    rep, results = g11
    screens = {k: v for k, v in results.items() if not k.startswith("_")}
    assert len(screens) == 32
    bad = {k: v["why"] for k, v in screens.items() if not v["ok"]}
    assert not bad, bad
    assert not rep.failed(), failed(rep)


def test_g11_empty_state_detector_catches_a_bare_table():
    bare = "<main><table><thead><tr><th>a</th></tr></thead><tbody></tbody></table></main>"
    ok = '<main><table><thead><tr><th>a</th></tr></thead><tbody><tr><td class="empty">미수집</td></tr></tbody></table></main>'
    assert cd.empty_state_of(bare)["tables"][0]["bare"] and not cd.empty_state_of(bare)["has_marker"]
    st = cd.empty_state_of(ok)
    assert not st["tables"][0]["bare"] and st["has_marker"]
    # 오른쪽 계약 패널의 「0건이면 미수집」 문장은 본문이 아니다
    assert cd.NOT_COLLECTED not in cd.main_of("<main>x</main><aside>0건이면 미수집</aside>")


# ── G-12 ────────────────────────────────────────────────────────────────
def test_g12_no_out_of_scope_features(ctx):
    rep = cd.Report()
    cd.check_g12(ctx, rep)
    assert len(rep.rows) == 4 and not rep.failed(), failed(rep)


def test_g12_scanner_words():
    hit = cd.SCOPE_RE.search
    for text in ("PLC 수집", "설비 데이터 수집", "비전 검사", "AI 분석", "opc-ua", "import cv2", "실시간 수집"):
        assert hit(text), text
    for text in ("미수집", "equipment", "replace", "revision", "Daily", "detail"):
        assert not hit(text), text
