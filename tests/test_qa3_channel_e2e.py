"""QA3 — 채널(G-13) · 출력물(G-14) · 접근 로그(G-18) · 세션. 임시 세계를 화면 API 로 만들고 **실제 브라우저**로도 잰다.

기대값의 출처: goal.md §2.3 G-13·G-14 · §2.4 G-18 · §2.5 오류 계약("POP 은 큰 글씨로, 다음 스캔을 막지 않는다").
실패하는 테스트는 결함이다 — `outputs/qa3-채널보안.md` 의 DEF-QA3-nnn 과 이어진다.
"""

from __future__ import annotations

import pytest
from test_qa3_support import HTML, build_world, conn, cs, login, run_probe, temp_user

from lcomfine.app import contracts

SCAN_ENTRY = cs.SCAN_ENTRY


@pytest.fixture(scope="module")
def world():
    w = build_world()
    yield w
    w.cleanup()


@pytest.fixture(scope="module")
def probe(world):
    assert world.error is None, f"임시 세계를 만들지 못했다: {world.error}"
    return run_probe(world, "--skip-board")


# ── G-13 POP (HTTP) ─────────────────────────────────────────────────────
@pytest.mark.fn("F-POP-03", "F-MAT-04", "F-MAT-05", "F-RLL-03", "F-RLL-05", "F-RLL-06", "F-QUA-04", "F-SHP-04")
@pytest.mark.parametrize("path", SCAN_ENTRY)
def test_scan_of_unknown_number_keeps_the_scan_box(path):
    """없는 번호를 스캔해도(GET 422) 그 화면이 다시 그려져 스캔칸이 남아야 한다 — 다음 스캔을 막지 않는다 (DEF-QA3-002)."""
    r = cs.cl("field", "pop").get(f"{path}?{cs.scan_param(path)}={cs.NOPE}", headers=HTML)
    assert r.status_code == 422
    assert "data-scan" in r.text, f"{path}: 없는 번호 스캔 뒤 오류 화면으로 가서 스캔칸이 사라진다"


def test_one_scan_makes_one_row_and_duplicates_are_422(world):
    assert world.error is None, world.error
    v = world.v
    assert v["dup_input"] == {"status": 422, "rows": 1}
    assert v["bad_input"] == {"status": 422, "rows": 1}
    assert v["reship"] == {"status": 422, "rows": 1}


@pytest.mark.fn("F-STA-04")
def test_board_keeps_refreshing_after_an_error_page():
    """현황판은 조작 없이 돌아야 한다. 한 번 오류 화면(일시적 503 · 404)으로 떨어지면 refresh 태그가 없어 거기서 멈춘다 (DEF-QA3-004)."""
    c = cs.cl("prod")
    ok = c.get("/sta/board?device=board", headers=HTML)
    assert 'http-equiv="refresh"' in ok.text
    err = c.get("/sta/board/none?device=board", headers=HTML)
    assert err.status_code == 404
    assert 'http-equiv="refresh"' in err.text, "현황판 채널의 오류 화면에 자동 새로고침이 없다 — 사람이 누를 때까지 오류 화면에 머문다"


# ── G-13 POP · 모바일 (실제 브라우저) ───────────────────────────────────
def test_browser_pop_is_enlarged_and_scan_box_takes_focus(probe):
    p = probe["pop"]
    assert "ch-pop" in p["body_class"]
    assert p["size"]["body_font_px"] > p["size_web"]["body_font_px"]
    assert p["size"]["button_h_px"] >= 44 and p["size"]["scan_input_h_px"] >= 44
    assert [k for k, x in p["screens"].items() if not x["focus_on_scan"]] == []


def test_browser_next_scan_is_received_after_an_unknown_number(probe):
    """없는 번호를 쏜 뒤 곧바로 다음 바코드를 쏘면 스캔칸이 받아야 한다 (DEF-QA3-002)."""
    blocked = [k for k, x in probe["pop"]["bad_scan"].items() if not (x["scan_present"] and x["next_scan_received"])]
    assert blocked == [], f"스캔칸이 사라져 다음 스캔 글자가 버려지는 화면: {blocked}"


def test_browser_scan_while_popup_is_open_is_not_lost(probe):
    """알림이 떠 있는 동안 쏜 바코드가 버려지면 안 된다 · 「확인」으로 닫으면 스캔칸으로 돌아와야 한다 (DEF-QA3-001)."""
    pop = probe["pop"]["popup"]
    lost = [k for k, x in pop.items() if not x.get("typed_while_popup_reaches_scan")]
    nofocus = [k for k, x in pop.items() if not x.get("focus_on_scan_after_close")]
    assert (lost, nofocus) == ([], []), f"알림 중 스캔이 버려지는 화면 {lost} · 닫은 뒤 포커스가 안 돌아오는 화면 {nofocus}"


@pytest.mark.fn("F-SHP-02")
def test_browser_consecutive_shipment_scans_make_one_row_each(probe):
    """출하 롤 연속 스캔 — 바코드 한 번 = 한 건. 앞 스캔의 알림이 떠 있는 채로 쏜 두 번째 롤이 조용히 사라진다 (DEF-QA3-001)."""
    o = probe["pop"]["one_scan_one_row"]
    assert o["first_scan_rows"] == 1
    assert o["second_scan_while_popup_rows"] == 1, "두 번째 롤이 담기지 않았고 오류도 보이지 않는다"
    assert o["rescan_rows"] == 1 and o["rescan_warn"]


@pytest.mark.fn("F-TRC-01", "F-TRC-02", "F-TRC-03", "F-STA-01", "F-STA-02", "F-STA-03")
def test_browser_mobile_390px_has_no_horizontal_scroll(probe):
    pages = probe["mobile"]["pages"]["mobile"]
    assert sum(k.startswith("/trc/trace") for k in pages) >= 4 and sum(k.startswith("/sta/") for k in pages) >= 4
    wide = {k: (x["scrollWidth"], x["vw"]) for k, x in pages.items() if x["scrollWidth"] > x["vw"] or x["inner_scrollers"]}
    assert wide == {}
    assert all(x["vw"] == 390 and "ch-mobile" in x["body"] for x in pages.values())


# ── G-14 출력물 (실제 브라우저 + 실제 디코더) ───────────────────────────
@pytest.mark.fn("F-JOB-05", "F-MAT-06", "F-POP-08", "F-RLL-07", "F-SHP-07")
def test_browser_five_outputs_decode_and_open_by_scan(probe):
    o = probe["outputs"]
    assert set(o) == {"작업지시서", "원재료 LOT 라벨", "인쇄 롤 라벨", "롤 라벨", "COA"}
    for name, x in o.items():
        assert x["http"] == 200 and x["svg"] >= 1, name
        assert x["decode_ok"], f"{name}: 캡처한 바코드가 zbarimg 로 읽히지 않는다 {x['decoded']}"
        assert x["external_count"] == 0 and x["ext_tags"] == 0 and x["img"] == 0, f"{name}: 외부 요청"
        assert not x["print_media"]["menu"] and not x["print_media"]["buttons"] and x["print_media"]["svg"], f"{name}: 인쇄 매체"
        assert x["scan_opens"]["focus_on_scan"] and x["scan_opens"]["number_shown"] and x["scan_opens"]["http_ok"], f"{name}: 스캔 진입"


# ── G-18 접근 로그 ──────────────────────────────────────────────────────
def test_every_write_function_logs_exactly_one_change(world):
    """쓰기 기능 전수(계약의 등록·수정·삭제·승인·스캔) — 성공할 때마다 `변경` 한 줄에 누가·무엇을·언제."""
    writes = {f.id for f in contracts.functions() if f.is_write} - {"F-SYS-03"}       # F-SYS-03 은 아래 세션 테스트가 부른다
    called = {c["fid"] for c in world.calls}
    assert writes - called == set(), f"부르지 못한 쓰기 기능 (세계 생성 실패: {world.error})"
    wrong = [(c["fid"], c["delta"]) for c in world.calls if c["delta"] != 1 or c["who"] != c["role"] or not c["target"]]
    assert wrong == []


def test_stopped_or_locked_account_loses_its_live_session():
    """중지·잠금된 계정은 살아 있는 세션으로도 더 들어오지 못해야 한다 (DEF-QA3-003 · progress-dev1.md §3-2)."""
    user, pw = temp_user("QC")
    try:
        s = login(user, pw)
        assert s.get("/trc/trace").status_code == 200
        r = cs.cl("admin").post(f"/sys/users/{user}", data={"status": "잠금"})
        assert r.status_code == 200
        locked = s.get("/trc/trace").status_code
        cs.cl("admin").post(f"/sys/users/{user}", data={"status": "정상"})
        since = cs.log_max()
        r = cs.cl("admin").post(f"/sys/users/{user}/delete")                       # F-SYS-03 — 상태 `중지`
        assert r.status_code == 200
        assert len(cs.logs_since(since, log_type="변경", function_id="F-SYS-03", target=f"sys_user:{user}")) == 1
        stopped = s.get("/trc/trace").status_code
        assert login_status(user, pw) == 401
        assert (locked, stopped) != (200, 200), "잠금·중지 뒤에도 같은 세션으로 화면이 200 이다"
        assert locked in (401, 303) and stopped in (401, 303)
    finally:
        conn.x("delete from sys_access_log where login_id = %s or target = %s", (user, f"sys_user:{user}"))
        conn.x("delete from sys_user where login_id = %s", (user,))


def test_logout_makes_the_old_cookie_useless():
    """로그아웃한 뒤에는 그 전의 세션 쿠키가 통하면 안 된다 (DEF-QA3-003 — 세션이 서버에 없어 무효화할 수 없다)."""
    from fastapi.testclient import TestClient

    from lcomfine.app.main import app

    user, pw = temp_user("QC")
    try:
        s = login(user, pw)
        jar = dict(s.cookies)
        assert s.post("/logout", follow_redirects=False).status_code == 303
        replay = TestClient(app, raise_server_exceptions=False, cookies=jar)
        assert replay.get("/trc/trace").status_code in (401, 303), "로그아웃 전의 쿠키로 화면이 열린다"
    finally:
        conn.x("delete from sys_access_log where login_id = %s or target = %s", (user, f"sys_user:{user}"))
        conn.x("delete from sys_user where login_id = %s", (user,))


def login_status(user: str, pw: str) -> int:
    from fastapi.testclient import TestClient

    from lcomfine.app.main import app

    return TestClient(app, raise_server_exceptions=False).post("/login", data={"login_id": user, "password": pw}, follow_redirects=False).status_code


# ── G-15 이관 배치가 살아 있는 Job 을 덮어쓰는가 ─────────────────────────
@pytest.mark.fn("B-MIG-04")
def test_migration_does_not_overwrite_a_job_that_already_has_rolls(world):
    """화면에서 만들어 롤·승인된 출하가 있는 Job 과 같은 번호가 job.csv 에 있으면, 적재가 품목·고객·수량을 갈아치우면 안 된다 (DEF-QA3-005).
    계약 F-JOB-02: 작업 실적이 생긴 뒤에는 품목·수량을 못 바꾼다."""
    assert world.error is None, world.error
    o = cs.probe_migration_overwrite(world)
    assert o is not None
    assert not o["overwritten"], f"load-jobs 가 판정 {o['verdict']} 로 덮어썼다: {o['before']} → {o['after']}"
