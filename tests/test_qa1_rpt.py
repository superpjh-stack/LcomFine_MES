# tests/test_qa1_rpt.py — QA1 W3 대시보드(RPT 8 화면 · 기능 8) + SYS-040 로그 탭 4 (F-SYS-041). 데이터 질의(RPT-130 · F-RPT-131 · 132)는 D-529 로 없앴다.
# tools/check_screens.py 의 W3 몫을 그대로 돈다: QA1 세계(접두 `QA1-…-` · 의뢰 → 지시 → 입고 → 일보 → 제품 입고 → 출하 확정 · ERP 회차 2 · 전략부 사용자)를
# 화면이 부르는 HTTP 로 만들고, RPT 8 화면의 정본 L3 · logic · D-512 수치 표식 · **인라인 SVG <title> = 같은 숫자의 표** · grid-wrap(390 가로 스크롤 0) ·
# `미확정 (D-519)` · `(D-520)` · RPT-060 ERP 업로드 기준일 · RPT-080 일일 · 주간 · 월간 · 조회 칸 형식 오류 422 · 데이터 질의 제거(옛 경로 404) ·
# SYS-040 탭 4(열 = db-schema 컬럼 · ERP 회차가 보임) 을 확인한 뒤 자기 행만 지운다.
# 기대값은 계약(function-list.md F-RPT-011~081 · F-SYS-041 · ia.json + overrides RPT 8 · SYS-040 ·
# decisions.md D-512 · D-519 · D-520 · D-529 · D-805 · D-609 · goal §3.4)에서 끌어온다. 고치지 않는다.
import pytest

from tools import check_screens as cs

RPT_READS = ("F-RPT-011", "F-RPT-021", "F-RPT-031", "F-RPT-041", "F-RPT-051", "F-RPT-061", "F-RPT-071", "F-RPT-081")
RPT_ALL = RPT_READS


@pytest.fixture(scope="module")
def lab():
    app, clients = cs.app_and_clients()
    w = cs.World(clients)
    try:
        w.build()
        assert not w.failed_steps(), "QA1 세계 만들기 실패:\n" + "\n".join(w.failed_steps())
        assert w.ids.get("user_st") and "qa1st" in w.clients, f"전략부 QA1 사용자 세션이 없다 — {w.ids.get('user_st')}"
        rep = cs.Report()
        contract = cs.check_rpt_contract(w, rep)
        yield {"app": app, "world": w, "clients": clients, "contract": contract, "rep": rep}
    finally:
        w.cleanup()
    assert not w.leftovers(), f"정리 후 남은 QA1 행 {w.leftovers()}"


def _items(contract, *keys) -> list[dict]:
    out = [x for x in contract if any(k in x["item"] for k in keys)]
    assert out, f"계약 문장 항목이 없다 — {keys}"
    return out


def _assert_items(contract, *keys) -> None:
    bad = [f"{x['item']} — {x['actual']}" for x in _items(contract, *keys) if not x["ok"]]
    assert not bad, "\n".join(bad)


def _rows(rep: cs.Report, gate: str | None = None) -> None:
    bad = [(g, item, actual) for g, item, ok, actual in rep.rows if not ok and (gate is None or g == gate)]
    if bad:
        details = dict(rep.details)
        lines = []
        for g, item, actual in bad:
            lines.append(f"{g} {item} — {actual}")
            lines += [f"    - {b}" for b in details.get(f"{g} {item}", [])[:25]]
        pytest.fail("\n".join(lines))


# ── G-02 · G-19 — 기능 8 ↔ 라우트 ↔ 표식 · require_fn / require_screen (정적) ───────────────────────────────

@pytest.mark.fn(*RPT_ALL, "F-SYS-041")
def test_g02_rpt_8_functions_route_marks_and_deps(lab):
    """범위 기능 134(W1 109 + COL 11 + RPT 8 + DOC 6): API 열의 메서드 · 경로가 라우트에 글자 그대로 · @pytest.mark.fn 표식 ·
    쓰기 66 은 require_fn(<그 기능 ID>) 하나 · 조회 68(RPT 8 · SYS-040 포함) 은 require_screen(화면) (G-02 · G-19 정적). RPT 는 쓰기 0 (D-529)."""
    rep = cs.Report()
    cs.check_functions(lab["app"], rep)
    _rows(rep)
    from lcomfine.app import contracts

    rpt = [f for f in cs.w1_functions() if f.menu_code == "RPT"]
    assert len(rpt) == 8 and sum(f.is_write for f in rpt) == 0
    assert not [f for f in contracts.functions() if f.screen_id == "RPT-130" or f.path == "/rpt/query"]   # D-529


# ── G-03 · G-19 — RPT 8 × 8 계정 200/403 · 메뉴 ───────────────

@pytest.mark.fn(*RPT_READS)
def test_g03_g19_rpt_8_x_8_200_403_menu_and_name(lab):
    """RPT 8 × 부서 8: 칸 R → 200 · 칸 없음 → 403 「이 화면을 볼 권한이 없습니다」(브라우저 · JSON) · placeholder 0 · 메뉴 = 권한 칸 ·
    좌측 메뉴 대메뉴 이름 「대시보드」(D-505). 기대값 = permission-matrix(RPT-010 6 · 020~040 4 · 050 6 · 060 · 070 5 · 080 3 = 37 칸 · RPT-130 은 D-529 로 없앴다)."""
    from lcomfine.app import contracts, nav

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    rpt_cells = {k: v for k, v in cells.items() if k[0].startswith("RPT-")}
    assert len(rpt_cells) == 37 and set(rpt_cells.values()) == {"R"}, f"RPT 칸 {len(rpt_cells)} {set(rpt_cells.values())}"
    bad = []
    for s in [s for s in nav.SCREENS if s.menu_code == "RPT"]:
        for lid, c in lab["clients"].items():
            rc = cs.CODE_OF[lid]
            r = c.get(s.path, headers=cs.HTML)
            rj = c.get(s.path)
            if (s.screen_id, rc) in cells:
                if r.status_code != 200 or "placeholder" in r.text.lower() and "준비 중" in r.text:
                    bad.append(f"{lid} {s.screen_id} → {r.status_code}")
            elif not (r.status_code == 403 and rj.status_code == 403 and cs.jget(rj, "message") == "이 화면을 볼 권한이 없습니다"):
                bad.append(f"{lid} {s.screen_id} → {r.status_code}/{rj.status_code} {cs.jget(rj, 'message')!r}")
    assert not bad, "\n".join(bad)
    rep = cs.Report()
    cs.check_screens(lab["app"], lab["clients"], rep)
    _rows(rep)
    assert next(m.name for m in nav.MENUS if m.code == "RPT") == "대시보드"
    item = _items(lab["contract"], "좌측 메뉴 — RPT 대메뉴 이름")[0]
    assert "nav '대시보드' · 메뉴 글자 '대시보드'" in item["actual"], item["actual"]   # 툴팁의 옛 이름 「AI 리포트」 0 은 아래 테스트(DEF-QA1-009 해소)


@pytest.mark.fn("F-RPT-011")
def test_menu_has_no_old_name_ai_report(lab):
    """D-505 RPT 이름 「대시보드」 — 좌측 메뉴(툴팁 포함)에 옛 이름 「AI 리포트」 0."""
    _assert_items(lab["contract"], "좌측 메뉴 — RPT 대메뉴 이름")


def test_data_query_removed_old_path_404_for_former_cell(lab):
    """D-529 — 옛 데이터 질의 칸이 있던 전략부 QA1 사용자도 GET · POST /rpt/query 404 · 대시보드 · 메인 화면에 「데이터 질의」 없음."""
    _assert_items(lab["contract"], "데이터 질의 제거(D-529)")


# ── 오류 계약 — RPT 8 조회 칸 ────────────────────────

@pytest.mark.fn("F-RPT-011", "F-RPT-051", "F-RPT-081")
def test_rpt_filter_format_errors_are_422_not_500(lab):
    """RPT 8 화면 조회 칸 — 틀린 날짜 · NUL · 기간 역순 · 없는 거래처(본문 999999999 = 사용자가 고른 값 → 422) · 거래처 값 틀림 · 탭 · 기준일 → 422 · 500 0 ·
    사람이 읽는 문장(goal §2.7). 응답 모양(Accept 없이 JSON)은 아래 테스트(DEF-QA1-007 해소 · Ruling 28)."""
    _assert_items(lab["contract"], "RPT 조회 칸 형식 오류")


@pytest.mark.fn("F-RPT-011")
def test_rpt_422_json_shape_when_not_browser(lab):
    """api-contract §2 「Accept 에 text/html 이 없으면 JSON」 — `GET /rpt/orders?date_from=2026-13-45`(Accept */*) 는 422 `{code: validation_error, …}` 여야 한다."""
    _assert_items(lab["contract"], "RPT 422 응답 모양")


# ── 계약 문장 — RPT 8 · SYS-040 (정본 L3 · logic · D-512 · D-805 · goal §3.4) ───────────────────────────

@pytest.mark.fn(*RPT_READS[:8])
def test_rpt_8_inline_svg_title_equals_table_and_marks(lab):
    """RPT 8: 200 · 차트는 인라인 SVG 이고 값마다 <title> 「라벨: 값」 = 같은 묶음의 표 행(라벨 · 값) — 같은 숫자(goal §3.4) · QA1 세계가 있는 010~050 은 SVG 묶음 ≥ 1 ·
    KPI · 차트 · 표 표식이 D-805 · progress-dev3 §1.5 의 이름 그대로(정본 L3 · D-512 수치가 화면에 있다는 기계 증거)."""
    for sid in cs.RPT_SCREENS:
        _assert_items(lab["contract"], f"{sid} — 200 · 인라인 SVG", f"{sid} — 정본 L3 · D-512 수치 표식")


@pytest.mark.fn(*RPT_READS, "F-SYS-041")
def test_rpt_8_and_sys040_tables_in_overflow_wrapper_no_scripts(lab):
    """RPT 8 + SYS-040 탭 4: 모든 <table> 이 `grid-wrap`(overflow: auto) 안 — 390 폭 가로 스크롤 0 · 외부·인라인 스크립트 0(base 의 app.js 만)."""
    for sid in cs.RPT_SCREENS:
        _assert_items(lab["contract"], f"{sid} — 표는 전부 grid-wrap 안")
    _assert_items(lab["contract"], "SYS-040 탭 4 → 200")
    from pathlib import Path

    tpl = Path(cs.ROOT / "src/lcomfine/app/templates")
    files = sorted((tpl / "rpt").glob("*.html")) + [tpl / "sys/logs.html", tpl / "_macros.html"]
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "<script" not in text, f"{f.name} 에 <script>"
        for m in __import__("re").finditer(r"<table", text):
            before = text[max(0, m.start() - 200):m.start()]
            assert "grid-wrap" in before, f"{f.name}:{text[:m.start()].count(chr(10)) + 1} <table> 앞 200자에 grid-wrap 래퍼가 없다"


@pytest.mark.fn("F-RPT-011", "F-RPT-021", "F-RPT-031", "F-RPT-041", "F-RPT-051")
def test_rpt_010_050_show_qa1_world_numbers_and_undecided_loss(lab):
    """RPT-010 QA1 의뢰(KPI requests · 거래처 상위) · 미착수 표 / RPT-020 · 030 로스율 = `미확정 (D-519)` + 원 수량 / RPT-040 입고·불출 수치 · 장기 체류 · 실사 차이 표 /
    RPT-050 확정 출하 · 거래처별 · 납기 준수율(due_rate) · 모집단 표 — 0건은 `미수집`(0 으로 지어내지 않음)."""
    _assert_items(lab["contract"], "RPT-010 — 기간 · 거래처 필터", "RPT-020 — 로스율", "RPT-030 — 로스율", "RPT-040 — 입고·불출", "RPT-050 — 확정 출하")


@pytest.mark.fn("F-RPT-061", "F-RPT-071", "F-RPT-081")
def test_rpt_060_asof_070_bottleneck_080_tabs(lab):
    """RPT-060 「가장 최근 업로드 기준일」 명시(글자 + KPI asof = stats.erp_asof() · 없으면 미수집) · 90일 초과 거래처 / RPT-070 의뢰별 단계 소요일(QA1 의뢰 행) ·
    병목 `미확정 (D-520)` · 수금은 거래처·월 단위 / RPT-080 일일 · 주간 · 월간 탭 · 일일 = 040 · 050 · 주간 · 월간 = + 010 · 020 · 060(D-805 · 해설 없음 D-505)."""
    _assert_items(lab["contract"], "RPT-060 — 「가장 최근 업로드 기준일」", "RPT-070 — 의뢰별 단계 소요일", "RPT-080 — 탭 일일")


@pytest.mark.fn("F-SYS-041")
def test_sys_040_four_tabs_columns_logs_visible(lab):
    """SYS-040 탭 4(접속 · 변경 · ERP 업로드 · SSO — AI 호출 · 데이터 질의 탭은 D-529 로 없앴다): 보이는 열 전부 db-schema.md 컬럼(D-609) · 탭마다 200 ·
    표 머리 = 열 수 · 원본 표 이름 · ERP 회차 2(교체 → 2회차 번호)가 머리 수치 · 행에 보인다 (정본 logic 「회차·교체」)."""
    _assert_items(lab["contract"], "SYS-040 탭 4 (access", "SYS-040 탭 4 → 200", "SYS-040 ERP 업로드 탭")


@pytest.mark.fn("F-SYS-041")
def test_sys_040_filter_outside_choices_is_422(lab):
    """SYS-040 필터 — 탭 · 구분 선택지 밖(없앤 ai · dq 탭 포함) · 틀린 날짜 · NUL → 422 (D-609 · DEF-QA1-008 해소)."""
    _assert_items(lab["contract"], "SYS-040 필터")


def test_rpt_contract_items_all_ok(lab):
    """자동 확인 전체 — 어긋난 항목 0 (DEF-QA1-007 · 008 · 009 해소 뒤). 새 어긋남이 생기면 여기서 잡힌다."""
    bad = [f"{x['item']} — {x['actual']}" for x in lab["contract"] if not x["ok"]]
    assert not bad, "\n".join(bad)
    assert len(lab["contract"]) >= 40   # 데이터 질의 항목 13 을 빼고(D-529) 제거 확인 1 을 더했다 — 52 → 40
