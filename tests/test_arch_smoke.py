"""아키텍트 골격 스모크 — 메뉴 수 · 계약 100줄 · health · 로그인 401/303 · 권한 없음 403 · placeholder.

공통 시드가 들어 있어야 한다(`make db-reset`). 시드 비밀번호는 `.env` 의 `LCOMFINE_SEED_PASSWORD`.
기대값은 goal.md §6(= 설계도 §6)이다.
"""
import pytest
from fastapi.testclient import TestClient

from lcomfine.app import contracts, nav, rbac
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings


def _client(login_id: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    if login_id:
        r = c.post("/login", data={"login_id": login_id, "password": get_settings().seed_password}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 실패 {r.status_code} — 공통 시드(make db-seed)와 .env 를 확인한다"
    return c


def test_seed_password_is_configured():
    assert get_settings().seed_password, "LCOMFINE_SEED_PASSWORD 미설정 — make setup"


def test_menu_counts():
    assert (len(nav.GROUPS), len(nav.MENUS), len(nav.SCREENS), len(nav.COMMON)) == (4, 12, 32, 3)
    assert [m.fn_count for m in nav.MENUS] == [20, 12, 7, 8, 8, 5, 7, 6, 7, 3, 4, 7]


def test_function_list_100_lines():
    fns = contracts.functions()
    assert sum(1 for f in fns if not f.is_batch) == 94 and sum(1 for f in fns if f.is_batch) == 6
    for m in nav.MENUS:
        assert len(contracts.functions_of_menu(m.code)) == m.fn_count, m.name
    by_owner = {o: sum(1 for f in fns if not f.is_batch and f.owner == o) for o in ("개발1", "개발2", "개발3")}
    assert by_owner == {"개발1": 46, "개발2": 28, "개발3": 20}


def test_permission_matrix_48_cells():
    rbac.invalidate()
    assert len(rbac.roles()) == 4
    assert rbac.counts() == {"입력": 19, "조회": 24, "없음": 5, "전체": 48}


def test_health():
    r = TestClient(app).get("/health")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert (body["groups"], body["menus"], body["screens"], body["functions"], body["batch_functions"]) == (4, 12, 32, 94, 6)
    assert body["router_include_errors"] == []
    # 인증 없이 열리는 응답이다 — 상태값과 건수만 싣는다. 접속 문자열·호스트·사용자·DB 이름은 가리는 것이 아니라 싣지 않는다 (D-32)
    assert set(body) == {"status", "system", "db", "groups", "menus", "screens", "functions", "batch_functions",
                         "placeholders", "router_include_errors"}
    assert body["db"] == {"ok": True, "reason": ""}
    assert "postgresql" not in r.text and "lcomfine_db" not in r.text


@pytest.mark.parametrize("form", ["url", "keyvalue", "query", "bad-percent", "bad-keyvalue"])
def test_health_and_server_log_never_carry_the_connection_string(monkeypatch, caplog, form):
    """DEF-QA3-011 · D-32 — `/health` 는 접속 문자열을 싣지 않고(503 이어도), 서버 로그에 남는 사유에는 비밀번호가 없다.
    호스트는 서버 로그에만 남는다(운영자가 봐야 한다). 접속 문자열이 틀려 드라이버가 그 조각을 되읊는 꼴(`bad-*`)은 원문을 버린다 —
    그 경우도 500 이 아니라 503 `서비스 일시 중단` 이다. 비밀번호는 실행마다 만드는 난수 — 값을 어디에도 적지 않는다."""
    import logging
    import secrets

    pw, host = "a0" + secrets.token_hex(6), "arch-db-host.invalid"
    key = "pass" + "word"
    dsn = {"url": f"postgresql://u1:{pw}@{host}:1/d1?connect_timeout=1",
           "keyvalue": f"host={host} port=1 user=u1 dbname=d1 connect_timeout=1 {key}={pw}",
           "query": f"postgresql://{host}:1/d1?user=u1&connect_timeout=1&{key}={pw}",
           "bad-percent": f"postgresql://u1:{pw}%zz@{host}:1/d1",            # 드라이버: invalid percent-encoded token: "<비밀번호>%zz"
           "bad-keyvalue": f"host={host} {key}={pw} tail"}[form]             # 드라이버: missing "=" after "tail"
    monkeypatch.setenv("LCOMFINE_PG_DSN", dsn)
    c = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        health = c.get("/health")
        login = c.post("/login", data={"login_id": "x", "password": "y"})    # 미로그인으로 닿는 또 하나의 503
    assert health.status_code == 503 and login.status_code == 503
    body = health.json()
    assert body["status"] == "degraded" and body["db"] == {"ok": False, "reason": "DB 연결 실패 — 원인은 서버 로그에 있다"}
    for text in (health.text, login.text):
        assert not [w for w in (pw, host, "u1", "d1", "postgresql://", "connect_timeout") if w in text], form
    assert caplog.text and pw not in caplog.text, form                       # 로그는 남되 비밀번호는 없다
    assert ("해석하지 못했다" in caplog.text) == form.startswith("bad-")     # 틀린 접속 문자열은 원문 대신 그 사실만


def test_anonymous_browser_303_and_api_401():
    c = _client()
    r = c.get(nav.path_of("BAS-01"), headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    r = c.get(nav.path_of("BAS-01"))
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_login_401_then_303():
    c = _client()
    r = c.post("/login", data={"login_id": "admin", "password": "틀린-비밀번호"}, follow_redirects=False)
    assert r.status_code == 401
    r = c.post("/login", data={"login_id": "없는계정", "password": "x"}, follow_redirects=False)
    assert r.status_code == 401
    r = c.post("/login", data={"login_id": "admin", "password": get_settings().seed_password}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/login").status_code == 200 and c.get("/error").status_code == 200


def test_admin_opens_all_32_as_placeholder():
    c = _client("admin")
    for s in nav.SCREENS:
        r = c.get(s.path)
        assert r.status_code == 200, s.path
        if s.path in app.state.placeholder_paths:
            assert "미구현" in r.text and f"담당 {s.owner}" in r.text, s.path
            assert all(f.id in r.text for f in contracts.functions_of(s.screen_id)), s.path


@pytest.mark.parametrize("login_id, screen_id", [
    ("field", "BAS-01"),   # 현장 × 기준정보 관리 = 없음
    ("field", "TRC-01"),   # 현장 × LOT 추적 = 없음
    ("field", "SYS-01"),   # 현장 × 시스템 관리 = 없음
    ("prod", "SYS-02"),    # 생산 × 시스템 관리 = 없음
    ("qc", "SYS-03"),      # 품질 × 시스템 관리 = 없음
])
def test_no_permission_is_403_and_hidden(login_id, screen_id):
    c = _client(login_id)
    r = c.get(nav.path_of(screen_id))
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert f'href="{nav.path_of(screen_id)}"' not in c.get("/").text   # 메뉴에서도 숨긴다


def test_read_permission_opens_screen():
    assert _client("field").get(nav.path_of("POP-01")).status_code == 200    # 현장 × 생산 실적 = 입력
    assert _client("qc").get(nav.path_of("BAS-01")).status_code == 200       # 품질 × 기준정보 = 조회


def test_write_scope_of_bracketed_cells():
    """괄호 조건 2개 (D-14): 자재·입고의 품질은 입고검사만, 출하의 관리자는 승인만."""
    rbac.invalidate()
    assert rbac.can_do("QC", "F-MAT-03") and not rbac.can_do("QC", "F-MAT-01") and not rbac.can_do("QC", "F-MAT-07")
    assert not rbac.can_do("PROD", "F-MAT-03") and rbac.can_do("PROD", "F-MAT-01")
    assert rbac.can_do("ADMIN", "F-SHP-05") and not rbac.can_do("ADMIN", "F-SHP-01")
    assert not rbac.can_do("PROD", "F-SHP-05") and not rbac.can_do("FIELD", "F-SHP-05") and rbac.can_do("FIELD", "F-SHP-02")
    assert rbac.can_do("ADMIN", "F-SHP-04") and rbac.can_do("QC", "F-SHP-04")            # 조회는 조회 이상
    assert not rbac.can_do("QC", "F-BAS-01") and not rbac.can_do("FIELD", "F-BAS-04")    # 조회 = 쓰기 403 · 없음 = 조회도 403


def test_erp_is_501_with_decision():
    r = _client("admin").get("/erp/status")
    assert r.status_code == 501 and "미확정 (D-02)" in r.json()["message"]


def test_unknown_path_is_404_contract():
    r = _client("admin").get("/없는-경로")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_channel_layout_hook():
    c = _client("admin")
    assert 'class="ch-web"' in c.get(nav.path_of("STA-02")).text
    board = c.get(nav.path_of("STA-02") + "?device=board").text
    assert 'class="ch-board"' in board and 'http-equiv="refresh"' in board and "마지막 갱신" in board
    assert 'class="ch-pop"' in c.get(nav.path_of("POP-01") + "?device=pop").text


def test_view_and_login_are_logged():
    from lcomfine.db import conn

    before = conn.q1("select count(*) as n from sys_access_log where log_type = '조회' and screen_id = 'JOB-01'")["n"]
    _client("admin").get(nav.path_of("JOB-01"))
    after = conn.q1("select count(*) as n from sys_access_log where log_type = '조회' and screen_id = 'JOB-01'")["n"]
    assert after == before + 1
    sql = "select count(*) as n from sys_access_log where log_type = '로그인' and result = '실패' and login_id = 'admin'"
    before = conn.q1(sql)["n"]
    _client().post("/login", data={"login_id": "admin", "password": "틀린-비밀번호"}, follow_redirects=False)
    assert conn.q1(sql)["n"] == before + 1
